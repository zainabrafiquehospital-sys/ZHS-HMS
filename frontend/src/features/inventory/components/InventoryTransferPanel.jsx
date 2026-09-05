'use client';

import { useMemo, useState } from 'react';
import { ArrowRightLeft } from 'lucide-react';
import { useInventoryItems, useTransferStock } from '@/features/inventory/hooks/useInventory';
import { carriedByNameSchema } from '@/features/inventory/schemas/inventorySchemas';
import { InventoryStockChecklist } from '@/features/inventory/components/InventoryStockChecklist';
import { Input } from '@/shared/components/ui/Input';
import { Label } from '@/shared/components/ui/Label';
import { todayDisplayDayKey } from '@/utils/timezone';

/** Records one-or-more Main Stock -> Emergency Stock transfers in a
 * single batch — the only way `emergency_stock_level` increases via
 * this path (see backend/app/modules/inventory/models.py's
 * `InventoryTransfer` docstring; `InventoryEmergencyDirectReceipt` is
 * the other, 2026-09 addition — see that model's own docstring, and
 * `InventoryReceiveToEmergencyPanel.jsx` for its own screen).
 *
 * Checklist-batch shape (2026-09 redesign, same `InventoryStockChecklist`
 * this module's other two stock-movement screens now share — see that
 * component's own docstring) — the Main Stock column is shown per row
 * (not just the item being transferred) specifically so the Inventory
 * Manager can see what's actually available before over-transferring;
 * the backend's own `InsufficientMainStockError` is still the real
 * enforcement boundary, this is purely the same visibility the previous
 * single-item flow's "Main Stock available: N" hint already gave. */
export function InventoryTransferPanel() {
  const { data: items, isLoading, isError, error, refetch } = useInventoryItems();
  const transferStock = useTransferStock();
  const [transferredOn, setTransferredOn] = useState(todayDisplayDayKey());
  const [carriedByName, setCarriedByName] = useState('');
  const [carriedByError, setCarriedByError] = useState(null);

  const activeItems = useMemo(() => (items ?? []).filter((item) => item.is_active), [items]);

  async function handleSubmit(lines) {
    setCarriedByError(null);
    const parsed = carriedByNameSchema.safeParse(carriedByName);
    if (!parsed.success) {
      const message = parsed.error.issues[0]?.message ?? 'Enter who carried this stock.';
      setCarriedByError(message);
      throw new Error(message);
    }
    await transferStock.mutateAsync({
      items: lines,
      transferred_on: transferredOn,
      carried_by_name: parsed.data,
    });
    setCarriedByName('');
  }

  return (
    <InventoryStockChecklist
      items={activeItems}
      isLoading={isLoading}
      isError={isError}
      error={error}
      onRetry={refetch}
      levelColumnLabel="Main Stock"
      getLevel={(item) => item.main_stock_level}
      pickerTitle="Select Items to Transfer"
      searchPlaceholder="Search item by name…"
      emptyItemsMessage="No active items in the catalog yet — add one under Catalog first."
      extraFields={
        <div className="flex flex-col gap-4 sm:flex-row sm:flex-wrap">
          <div className="flex flex-col gap-1.5 sm:max-w-xs">
            <Label htmlFor="transfer_transferred_on">Transferred On</Label>
            <Input
              id="transfer_transferred_on"
              type="date"
              value={transferredOn}
              onChange={(event) => setTransferredOn(event.target.value)}
            />
          </div>
          <div className="flex min-w-[220px] flex-1 flex-col gap-1.5">
            <Label htmlFor="transfer_carried_by_name">Carried By</Label>
            <Input
              id="transfer_carried_by_name"
              placeholder="Name of the person carrying this stock"
              value={carriedByName}
              onChange={(event) => setCarriedByName(event.target.value)}
            />
            {carriedByError ? <p className="text-xs text-destructive">{carriedByError}</p> : null}
          </div>
        </div>
      }
      recapTitle="Items to Transfer"
      submitLabel="Transfer to Emergency"
      submittingLabel="Transferring…"
      submitIcon={ArrowRightLeft}
      onSubmit={handleSubmit}
    />
  );
}
