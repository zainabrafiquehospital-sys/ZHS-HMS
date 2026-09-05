'use client';

import { useMemo, useState } from 'react';
import { PackagePlus } from 'lucide-react';
import { useInventoryItems, useReceiveStockBatch } from '@/features/inventory/hooks/useInventory';
import { InventoryStockChecklist } from '@/features/inventory/components/InventoryStockChecklist';
import { Input } from '@/shared/components/ui/Input';
import { Label } from '@/shared/components/ui/Label';
import { todayDisplayDayKey } from '@/utils/timezone';

/** Records one-or-more Main Stock receipts in a single batch — the only
 * way `InventoryItem.main_stock_level` ever increases (see backend/app/
 * modules/inventory/models.py's `InventoryMainStockReceipt` docstring).
 *
 * Checklist-batch shape (2026-09 redesign, replacing the earlier
 * search-one-item-then-submit form): the whole active catalogue is
 * shown as one filterable table via the shared `InventoryStockChecklist`
 * — see that component's own docstring for why this one widget backs
 * all three stock-movement screens instead of three bespoke forms.
 * `POST /inventory/receipts` (batch) backs this now; the original
 * single-item `POST /items/{item_id}/receive` stays available
 * unchanged for any other caller. */
export function InventoryReceivePanel() {
  const { data: items, isLoading, isError, error, refetch } = useInventoryItems();
  const receiveStockBatch = useReceiveStockBatch();
  const [receivedOn, setReceivedOn] = useState(todayDisplayDayKey());

  const activeItems = useMemo(() => (items ?? []).filter((item) => item.is_active), [items]);

  async function handleSubmit(lines) {
    await receiveStockBatch.mutateAsync({ items: lines, received_on: receivedOn });
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
      pickerTitle="Select Items to Receive"
      searchPlaceholder="Search item by name…"
      emptyItemsMessage="No active items in the catalog yet — add one under Catalog first."
      extraFields={
        <div className="flex flex-col gap-1.5 sm:max-w-xs">
          <Label htmlFor="receive_received_on">Received On</Label>
          <Input
            id="receive_received_on"
            type="date"
            value={receivedOn}
            onChange={(event) => setReceivedOn(event.target.value)}
          />
        </div>
      }
      recapTitle="Items to Receive"
      submitLabel="Record Receipt"
      submittingLabel="Recording…"
      submitIcon={PackagePlus}
      onSubmit={handleSubmit}
    />
  );
}
