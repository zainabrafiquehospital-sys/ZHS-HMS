'use client';

import { useMemo, useState } from 'react';
import { Search, Trash2 } from 'lucide-react';
import { stockBatchLineItemSchema } from '@/features/inventory/schemas/inventorySchemas';
import { Card, CardContent, CardHeader, CardTitle } from '@/shared/components/ui/Card';
import { Button } from '@/shared/components/ui/Button';
import { Input } from '@/shared/components/ui/Input';
import { PageLoader } from '@/shared/components/PageLoader';
import { PageError } from '@/shared/components/PageError';
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from '@/shared/components/ui/Table';
import { useToast } from '@/shared/components/toast/ToastProvider';
import { useDebouncedValue } from '@/shared/hooks/useDebouncedValue';

/** One row's parsed quantity, or an error string — same shape
 * RecordInventoryUsageForm.jsx's own `parseLineQuantity` establishes,
 * minus that function's "must not exceed available" check: unlike
 * Emergency Stock usage (which can never exceed what's on hand), every
 * screen this component backs is a *receiving* or *transfer* action
 * whose own upper bound (if any — Transfer's Main Stock ceiling) is
 * enforced server-side and surfaced as this batch's own submit error,
 * not a per-row client-side cap requiring the live level be re-checked
 * on every keystroke. */
function parseLineQuantity(rawQuantity) {
  const parsed = stockBatchLineItemSchema.safeParse({ quantity: rawQuantity });
  if (!parsed.success) {
    return { error: parsed.error.issues[0]?.message ?? 'Invalid quantity' };
  }
  return { quantity: parsed.data.quantity };
}

/** The one shared checklist-batch widget behind all three Ward/
 * Emergency Inventory stock-movement screens (2026-09 redesign):
 * Receive to Main Stock, Transfer to Emergency, and Receive Directly to
 * Emergency (see backend/app/modules/inventory/models.py's
 * `InventoryEmergencyDirectReceipt` docstring for why that third one
 * exists). Mirrors RecordInventoryUsageForm.jsx's exact pattern — a
 * single filterable table of active items, a debounced search box, a
 * quantity input per row, a running "items to submit" recap with a
 * remove option per row, one submit button that posts the whole batch
 * atomically — rather than three separately hand-rolled forms, since
 * the only things that genuinely differ between the three screens are:
 * which stock level to show per row, whether a row carries an extra
 * badge (the pending-restock-request indicator, Receive Directly to
 * Emergency only), and which batch-wide fields (a date; or a date plus
 * who carried the stock) sit below the table — all supplied by the
 * caller as props, never branched on internally by a "mode" flag.
 *
 * `items` is expected pre-filtered by the caller to whichever items are
 * eligible for that screen (every screen currently shows every active
 * item — Transfer included: seeing a `0` in the Main Stock column is
 * exactly the "so the Inventory Manager won't over-transfer" visibility
 * this was built for, not a reason to hide the row). `getLevel` reads
 * whichever stock level column that screen cares about; `renderBadge`
 * (optional) returns extra per-row JSX (e.g. a "Pending Request"
 * badge) or `null`. `extraFields` is arbitrary JSX rendered below the
 * table, inside the same card, for whatever batch-wide inputs the
 * screen needs. `onSubmit(lines)` receives `[{item_id, quantity}]` and
 * is expected to throw (with a `.message`) on failure — this component
 * owns only the picker/recap/submit-button UI and its own error/success
 * banners, never the actual API call. */
export function InventoryStockChecklist({
  items,
  isLoading,
  isError,
  error,
  onRetry,
  levelColumnLabel,
  getLevel,
  renderBadge,
  pickerTitle,
  searchPlaceholder,
  emptyItemsMessage,
  extraFields,
  recapTitle,
  submitLabel,
  submittingLabel,
  submitIcon: SubmitIcon,
  onSubmit,
}) {
  const { toast } = useToast();
  const [searchTerm, setSearchTerm] = useState('');
  const debouncedSearch = useDebouncedValue(searchTerm, 200);
  // `{ [itemId]: quantityString }` — a key is present iff the user has
  // typed something into that row's quantity input; a row counts toward
  // the batch only once its quantity parses to a positive number, same
  // "blank means not part of the batch" convention
  // RecordInventoryUsageForm.jsx's own `selections` state establishes.
  const [selections, setSelections] = useState({});
  const [submitError, setSubmitError] = useState(null);
  const [successMessage, setSuccessMessage] = useState(null);
  const [isSubmitting, setIsSubmitting] = useState(false);

  const visibleItems = useMemo(() => {
    const term = debouncedSearch.trim().toLowerCase();
    if (!term) return items;
    return items.filter((item) => item.name.toLowerCase().includes(term));
  }, [items, debouncedSearch]);

  // Every touched row, resolved back to its catalogue item — drives the
  // recap list independent of the search filter, so a selected item
  // never vanishes just because it's filtered out of the picker above.
  const selectedRows = useMemo(() => {
    return Object.entries(selections)
      .map(([itemId, quantity]) => {
        const item = items.find((candidate) => candidate.id === itemId);
        if (!item) return null;
        return { item, quantity };
      })
      .filter(Boolean);
  }, [selections, items]);

  function setRowQuantity(itemId, quantity) {
    setSelections((current) => {
      if (quantity === '') {
        const next = { ...current };
        delete next[itemId];
        return next;
      }
      return { ...current, [itemId]: quantity };
    });
  }

  function removeRow(itemId) {
    setSelections((current) => {
      const next = { ...current };
      delete next[itemId];
      return next;
    });
  }

  async function handleSubmit() {
    setSubmitError(null);
    setSuccessMessage(null);

    const activeRows = selectedRows.filter((row) => String(row.quantity).trim() !== '');
    if (activeRows.length === 0) {
      setSubmitError('Enter a quantity for at least one item before submitting.');
      return;
    }

    const parsedLines = [];
    for (const row of activeRows) {
      const result = parseLineQuantity(row.quantity);
      if (result.error) {
        setSubmitError(`${row.item.name}: ${result.error}`);
        return;
      }
      parsedLines.push({ item_id: row.item.id, quantity: result.quantity });
    }

    setIsSubmitting(true);
    try {
      await onSubmit(parsedLines);
      const message =
        parsedLines.length === 1 ? '1 item recorded.' : `${parsedLines.length} items recorded.`;
      setSuccessMessage(message);
      toast.success({ title: 'Recorded', description: message });
      setSelections({});
      setSearchTerm('');
    } catch (submitErr) {
      const message = submitErr.message || 'Unable to submit this batch.';
      setSubmitError(message);
      toast.error({ title: 'Unable to submit', description: message });
    } finally {
      setIsSubmitting(false);
    }
  }

  return (
    <div className="flex flex-col gap-6">
      <Card>
        <CardHeader>
          <div className="flex flex-col gap-4 sm:flex-row sm:items-center sm:justify-between">
            <CardTitle>{pickerTitle}</CardTitle>
            <div className="relative w-full sm:w-64">
              <Search className="pointer-events-none absolute left-2.5 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground" />
              <Input
                value={searchTerm}
                onChange={(event) => setSearchTerm(event.target.value)}
                placeholder={searchPlaceholder}
                className="pl-8"
              />
            </div>
          </div>
        </CardHeader>
        <CardContent className="flex flex-col gap-4">
          {isLoading ? (
            <PageLoader label="Loading items" />
          ) : isError ? (
            <PageError error={error} reset={onRetry} message="Couldn't load the item catalog." />
          ) : items.length === 0 ? (
            <p className="text-sm text-muted-foreground">{emptyItemsMessage}</p>
          ) : visibleItems.length === 0 ? (
            <p className="text-sm text-muted-foreground">
              No items match &quot;{debouncedSearch}&quot;.
            </p>
          ) : (
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>Item</TableHead>
                  <TableHead className="text-right">{levelColumnLabel}</TableHead>
                  <TableHead className="w-32">Quantity</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {visibleItems.map((item) => {
                  const quantity = selections[item.id] ?? '';
                  const isSelected = String(quantity).trim() !== '';
                  const badge = renderBadge ? renderBadge(item) : null;
                  return (
                    <TableRow key={item.id} className={isSelected ? 'bg-muted/40' : undefined}>
                      <TableCell className="font-medium text-foreground">
                        <div className="flex items-center gap-2">
                          <span>
                            {item.name} <span className="text-muted-foreground">({item.unit})</span>
                          </span>
                          {badge}
                        </div>
                      </TableCell>
                      <TableCell className="text-right tabular-nums text-muted-foreground">
                        {getLevel(item)}
                      </TableCell>
                      <TableCell>
                        <Input
                          type="number"
                          step="0.01"
                          min="0"
                          aria-label={`Quantity for ${item.name}`}
                          className="w-28"
                          value={quantity}
                          onChange={(event) => setRowQuantity(item.id, event.target.value)}
                        />
                      </TableCell>
                    </TableRow>
                  );
                })}
              </TableBody>
            </Table>
          )}
          {extraFields}
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle>{recapTitle}</CardTitle>
        </CardHeader>
        <CardContent className="flex flex-col gap-4">
          {selectedRows.length === 0 ? (
            <p className="text-sm text-muted-foreground">
              No items selected yet — enter a quantity against an item above.
            </p>
          ) : (
            <>
              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead>Item</TableHead>
                    <TableHead className="text-right">Qty</TableHead>
                    <TableHead />
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {selectedRows.map((row) => (
                    <TableRow key={row.item.id}>
                      <TableCell className="font-medium text-foreground">
                        {row.item.name}{' '}
                        <span className="text-muted-foreground">({row.item.unit})</span>
                      </TableCell>
                      <TableCell className="text-right tabular-nums">
                        {String(row.quantity).trim() === '' ? '—' : row.quantity}
                      </TableCell>
                      <TableCell>
                        <Button
                          type="button"
                          size="sm"
                          variant="ghost"
                          aria-label={`Remove ${row.item.name}`}
                          onClick={() => removeRow(row.item.id)}
                        >
                          <Trash2 className="h-4 w-4" />
                        </Button>
                      </TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
              <div>
                <Button type="button" onClick={handleSubmit} disabled={isSubmitting}>
                  {SubmitIcon ? <SubmitIcon className="h-4 w-4" /> : null}
                  {isSubmitting ? submittingLabel : submitLabel}
                </Button>
              </div>
            </>
          )}
          {submitError ? (
            <p className="rounded-md bg-destructive/10 px-3 py-2 text-sm text-destructive">
              {submitError}
            </p>
          ) : null}
          {successMessage ? (
            <p className="rounded-md bg-emerald-50 px-3 py-2 text-sm text-emerald-700">
              {successMessage}
            </p>
          ) : null}
        </CardContent>
      </Card>
    </div>
  );
}
