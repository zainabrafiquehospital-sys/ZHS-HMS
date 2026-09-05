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
 * on every keystroke.
 *
 * `allowEmptyQuantity` (2026-09 addition, Vitals' "Build Requirement"
 * screen) — a blank quantity parses to `null` rather than an error, the
 * identical "just flag it low, manager's judgment" design
 * `InventoryRestockRequest.requested_quantity` already allows server-
 * side (see that model's own docstring); every other caller of this
 * checklist requires a real positive quantity per row, unchanged. */
function parseLineQuantity(rawQuantity, { allowEmptyQuantity = false } = {}) {
  if (allowEmptyQuantity && String(rawQuantity).trim() === '') {
    return { quantity: null };
  }
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
 * banners, never the actual API call.
 *
 * `allowEmptyQuantity` (2026-09 addition, Vitals' "Build Requirement"
 * screen) — the other three screens select a row purely by typing a
 * quantity into it; this mode adds a checkbox per row instead, since a
 * restock requirement's own quantity is optional ("just flag it low").
 * A row's inclusion is then governed by the checkbox alone — typing (or
 * clearing) its quantity field never adds or removes it from the batch
 * — matching `InventoryRestockRequest.requested_quantity`'s own
 * optional design exactly (see `parseLineQuantity`'s own docstring).
 *
 * `secondaryActionLabel`/`secondaryActionIcon`/`onSecondaryAction`
 * (2026-09 addition, same screen) — an optional second button rendered
 * beside the primary submit button, reusing the identical validated
 * `[{item_id, quantity}]` lines the primary action already computes
 * (e.g. "Download Requirement PDF" alongside "Raise Requests" — two
 * genuinely independent actions over the same in-progress selection,
 * neither one a prerequisite for the other). Omitted entirely by every
 * other caller. */
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
  allowEmptyQuantity = false,
  secondaryActionLabel,
  secondaryActionIcon: SecondaryActionIcon,
  onSecondaryAction,
}) {
  const { toast } = useToast();
  const [searchTerm, setSearchTerm] = useState('');
  const debouncedSearch = useDebouncedValue(searchTerm, 200);
  // `{ [itemId]: quantityString }` — in the default (required-quantity)
  // mode, a key is present iff the user has typed something into that
  // row's quantity input, and a row counts toward the batch only once
  // its quantity parses to a positive number (the "blank means not part
  // of the batch" convention RecordInventoryUsageForm.jsx's own
  // `selections` state establishes). In `allowEmptyQuantity` mode, key
  // presence alone means "included" — the checkbox adds/removes the
  // key; the quantity string can legitimately stay `''` forever.
  const [selections, setSelections] = useState({});
  const [submitError, setSubmitError] = useState(null);
  const [successMessage, setSuccessMessage] = useState(null);
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [isRunningSecondaryAction, setIsRunningSecondaryAction] = useState(false);

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
      if (!allowEmptyQuantity && quantity === '') {
        const next = { ...current };
        delete next[itemId];
        return next;
      }
      // allowEmptyQuantity: a blank quantity is a legitimate value here
      // ("just flag it low") — never removes an already-included row.
      // Typing into a not-yet-included row also includes it (the same
      // one-step ergonomics the other three screens have), without
      // requiring the checkbox to be clicked first.
      return { ...current, [itemId]: quantity };
    });
  }

  // allowEmptyQuantity only — the checkbox is the sole source of truth
  // for "is this item in my requirement list"; the quantity field is
  // purely optional supplementary detail once checked.
  function toggleRowIncluded(itemId) {
    setSelections((current) => {
      if (itemId in current) {
        const next = { ...current };
        delete next[itemId];
        return next;
      }
      return { ...current, [itemId]: '' };
    });
  }

  function removeRow(itemId) {
    setSelections((current) => {
      const next = { ...current };
      delete next[itemId];
      return next;
    });
  }

  /** Shared by both the primary submit action and the optional
   * secondary action — validates the current selection and returns
   * `[{item_id, quantity}]`, or `null` (having already set
   * `submitError`) if nothing is ready to send. `quantity` is `null`
   * for a flagged-but-unquantified row in `allowEmptyQuantity` mode,
   * never for the other three (required-quantity) callers. */
  function buildParsedLines() {
    setSubmitError(null);
    setSuccessMessage(null);

    const activeRows = allowEmptyQuantity
      ? selectedRows
      : selectedRows.filter((row) => String(row.quantity).trim() !== '');
    if (activeRows.length === 0) {
      setSubmitError(
        allowEmptyQuantity
          ? 'Select at least one item before submitting.'
          : 'Enter a quantity for at least one item before submitting.',
      );
      return null;
    }

    const parsedLines = [];
    for (const row of activeRows) {
      const result = parseLineQuantity(row.quantity, { allowEmptyQuantity });
      if (result.error) {
        setSubmitError(`${row.item.name}: ${result.error}`);
        return null;
      }
      parsedLines.push({ item_id: row.item.id, quantity: result.quantity });
    }
    return parsedLines;
  }

  async function handleSubmit() {
    const parsedLines = buildParsedLines();
    if (!parsedLines) return;

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

  async function handleSecondaryAction() {
    const parsedLines = buildParsedLines();
    if (!parsedLines) return;

    setIsRunningSecondaryAction(true);
    try {
      await onSecondaryAction(parsedLines);
      setSuccessMessage(null);
    } catch (actionError) {
      const message = actionError.message || `Unable to ${secondaryActionLabel?.toLowerCase()}.`;
      setSubmitError(message);
      toast.error({ title: `Unable to ${secondaryActionLabel?.toLowerCase()}`, description: message });
    } finally {
      setIsRunningSecondaryAction(false);
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
                  {allowEmptyQuantity ? <TableHead className="w-10" /> : null}
                  <TableHead>Item</TableHead>
                  <TableHead className="text-right">{levelColumnLabel}</TableHead>
                  <TableHead className="w-32">
                    {allowEmptyQuantity ? 'Quantity (optional)' : 'Quantity'}
                  </TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {visibleItems.map((item) => {
                  const quantity = selections[item.id] ?? '';
                  const isSelected = allowEmptyQuantity
                    ? item.id in selections
                    : String(quantity).trim() !== '';
                  const badge = renderBadge ? renderBadge(item) : null;
                  return (
                    <TableRow key={item.id} className={isSelected ? 'bg-muted/40' : undefined}>
                      {allowEmptyQuantity ? (
                        <TableCell>
                          <input
                            type="checkbox"
                            aria-label={`Include ${item.name} in the requirement list`}
                            checked={isSelected}
                            onChange={() => toggleRowIncluded(item.id)}
                            className="h-4 w-4"
                          />
                        </TableCell>
                      ) : null}
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
              {allowEmptyQuantity
                ? 'No items selected yet — check an item above to add it to the list.'
                : 'No items selected yet — enter a quantity against an item above.'}
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
                        {String(row.quantity).trim() === ''
                          ? allowEmptyQuantity
                            ? 'Flagged (no qty)'
                            : '—'
                          : row.quantity}
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
              <div className="flex flex-wrap gap-2">
                <Button type="button" onClick={handleSubmit} disabled={isSubmitting}>
                  {SubmitIcon ? <SubmitIcon className="h-4 w-4" /> : null}
                  {isSubmitting ? submittingLabel : submitLabel}
                </Button>
                {onSecondaryAction ? (
                  <Button
                    type="button"
                    variant="outline"
                    onClick={handleSecondaryAction}
                    disabled={isRunningSecondaryAction}
                  >
                    {SecondaryActionIcon ? <SecondaryActionIcon className="h-4 w-4" /> : null}
                    {isRunningSecondaryAction ? 'Preparing…' : secondaryActionLabel}
                  </Button>
                ) : null}
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
