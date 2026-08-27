'use client';

import { useState } from 'react';
import { ArrowRightLeft, Plus, Trash2 } from 'lucide-react';
import { inventoryService } from '@/features/inventory/api/inventoryService';
import { useTransferStock } from '@/features/inventory/hooks/useInventory';
import {
  carriedByNameSchema,
  transferLineItemSchema,
} from '@/features/inventory/schemas/inventorySchemas';
import { Card, CardContent, CardHeader, CardTitle } from '@/shared/components/ui/Card';
import { Button } from '@/shared/components/ui/Button';
import { Input } from '@/shared/components/ui/Input';
import { Label } from '@/shared/components/ui/Label';
import { SearchSelect } from '@/shared/components/SearchSelect';
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from '@/shared/components/ui/Table';
import { useToast } from '@/shared/components/toast/ToastProvider';
import { todayDisplayDayKey } from '@/utils/timezone';

let nextLineKey = 0;

/** Records a Main Stock -> Emergency Stock transfer — the only way
 * emergency_stock_level increases (see backend/app/modules/inventory/
 * models.py's InventoryTransfer docstring).
 *
 * Add-to-a-running-list-then-submit-once shape (2026-08-28 redesign,
 * matching RecordInventoryUsageForm.jsx's own identical batch pattern):
 * pick an item + quantity, add it to the visible list, repeat, then one
 * "Transfer to Emergency" submit sends the whole list together — one
 * `transferred_on`/`carried_by_name` shared by the whole batch. The
 * backend still writes one fully independent InventoryTransfer row per
 * line, just atomically — see TransferStockRequest's own docstring. */
export function InventoryTransferPanel() {
  const { toast } = useToast();
  const transferStock = useTransferStock();

  const [selectedItem, setSelectedItem] = useState(null);
  const [quantity, setQuantity] = useState('');
  const [lineError, setLineError] = useState(null);
  const [lines, setLines] = useState([]);

  const [transferredOn, setTransferredOn] = useState(todayDisplayDayKey());
  const [carriedByName, setCarriedByName] = useState('');

  const [submitError, setSubmitError] = useState(null);
  const [successMessage, setSuccessMessage] = useState(null);
  const [isSubmitting, setIsSubmitting] = useState(false);

  function handleAddLine() {
    setLineError(null);
    if (!selectedItem) return;
    const parsed = transferLineItemSchema.safeParse({ quantity });
    if (!parsed.success) {
      setLineError(parsed.error.issues[0]?.message ?? 'Invalid quantity');
      return;
    }

    setLines((current) => [
      ...current,
      {
        key: nextLineKey++,
        item_id: selectedItem.id,
        name: selectedItem.name,
        unit: selectedItem.unit,
        mainStockAvailable: selectedItem.main_stock_level,
        quantity: parsed.data.quantity,
      },
    ]);
    setSelectedItem(null);
    setQuantity('');
  }

  function handleRemoveLine(key) {
    setLines((current) => current.filter((line) => line.key !== key));
  }

  async function handleSubmitBatch() {
    setSubmitError(null);
    setSuccessMessage(null);

    if (lines.length === 0) {
      setSubmitError('Add at least one item before transferring.');
      return;
    }
    const carriedByParsed = carriedByNameSchema.safeParse(carriedByName);
    if (!carriedByParsed.success) {
      setSubmitError(carriedByParsed.error.issues[0]?.message ?? 'Enter who carried this stock.');
      return;
    }

    setIsSubmitting(true);
    try {
      await transferStock.mutateAsync({
        items: lines.map((line) => ({ item_id: line.item_id, quantity: line.quantity })),
        transferred_on: transferredOn,
        carried_by_name: carriedByParsed.data,
      });
      const message =
        lines.length === 1 ? 'Transfer recorded.' : `${lines.length} transfers recorded.`;
      setSuccessMessage(message);
      toast.success({ title: 'Transfer to Emergency recorded', description: message });
      setLines([]);
      setCarriedByName('');
    } catch (submitErr) {
      const message = submitErr.message || 'Unable to record this transfer.';
      setSubmitError(message);
      toast.error({ title: 'Unable to record transfer', description: message });
    } finally {
      setIsSubmitting(false);
    }
  }

  return (
    <div className="flex flex-col gap-6">
      <Card>
        <CardHeader>
          <CardTitle>Add Item</CardTitle>
        </CardHeader>
        <CardContent className="flex flex-col gap-4">
          <div className="flex flex-col gap-4 sm:flex-row sm:flex-wrap sm:items-end">
            <div className="flex min-w-[220px] flex-1 flex-col gap-1.5">
              <Label>Item</Label>
              <SearchSelect
                queryKey={['inventory', 'items', 'search']}
                queryFn={(term) => inventoryService.searchItems(term).then((res) => res.data)}
                getLabel={(item) => item.name}
                getDescription={(item) => `${item.unit} — ${item.main_stock_level} in Main Stock`}
                placeholder="Search item by name"
                selectedLabel={selectedItem ? selectedItem.name : ''}
                onSelect={(item) => setSelectedItem(item)}
              />
              {selectedItem ? (
                <p className="text-xs text-muted-foreground">
                  Main Stock available: {selectedItem.main_stock_level} {selectedItem.unit}
                </p>
              ) : null}
            </div>
            <div className="flex flex-col gap-1.5">
              <Label htmlFor="transfer_quantity">Quantity</Label>
              <Input
                id="transfer_quantity"
                type="number"
                step="0.01"
                min="0"
                className="w-28"
                value={quantity}
                onChange={(event) => setQuantity(event.target.value)}
              />
            </div>
            <Button type="button" onClick={handleAddLine} disabled={!selectedItem}>
              <Plus className="h-4 w-4" />
              Add Item
            </Button>
          </div>
          {lineError ? <p className="text-xs text-destructive">{lineError}</p> : null}
          <div className="flex flex-col gap-4 sm:flex-row sm:flex-wrap">
            <div className="flex flex-col gap-1.5 sm:max-w-xs">
              <Label htmlFor="transferred_on">Transferred On</Label>
              <Input
                id="transferred_on"
                type="date"
                value={transferredOn}
                onChange={(event) => setTransferredOn(event.target.value)}
              />
            </div>
            <div className="flex min-w-[220px] flex-1 flex-col gap-1.5">
              <Label htmlFor="carried_by_name">Carried By</Label>
              <Input
                id="carried_by_name"
                placeholder="Name of the person carrying this stock"
                value={carriedByName}
                onChange={(event) => setCarriedByName(event.target.value)}
              />
            </div>
          </div>
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle>Items to Transfer</CardTitle>
        </CardHeader>
        <CardContent className="flex flex-col gap-4">
          {lines.length === 0 ? (
            <p className="text-sm text-muted-foreground">No items added yet.</p>
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
                  {lines.map((line) => (
                    <TableRow key={line.key}>
                      <TableCell className="font-medium text-foreground">
                        {line.name} <span className="text-muted-foreground">({line.unit})</span>
                      </TableCell>
                      <TableCell className="text-right tabular-nums">{line.quantity}</TableCell>
                      <TableCell>
                        <Button
                          type="button"
                          size="sm"
                          variant="ghost"
                          onClick={() => handleRemoveLine(line.key)}
                        >
                          <Trash2 className="h-4 w-4" />
                        </Button>
                      </TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
              <div>
                <Button type="button" onClick={handleSubmitBatch} disabled={isSubmitting}>
                  <ArrowRightLeft className="h-4 w-4" />
                  {isSubmitting ? 'Transferring…' : 'Transfer to Emergency'}
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
