'use client';

import { useMemo, useState } from 'react';
import { PackagePlus } from 'lucide-react';
import {
  useInventoryItems,
  useInventoryRequests,
  useReceiveDirectlyToEmergency,
} from '@/features/inventory/hooks/useInventory';
import { InventoryStockChecklist } from '@/features/inventory/components/InventoryStockChecklist';
import { Badge } from '@/shared/components/ui/Badge';
import { Input } from '@/shared/components/ui/Input';
import { Label } from '@/shared/components/ui/Label';
import { todayDisplayDayKey } from '@/utils/timezone';

/** Records one-or-more direct-to-Emergency-Stock receipts in a single
 * batch — the real-world-shaped receiving path (2026-09 addition): a
 * supplier's delivery arrives addressed straight to Emergency Stock,
 * with no physical Main Stock leg in between, so this lands in
 * `emergency_stock_level` directly rather than forcing the
 * Receive-then-Transfer two-step (still fully available on its own two
 * tabs for whichever items genuinely do pass through a real
 * intermediate store — see backend/app/modules/inventory/models.py's
 * `InventoryEmergencyDirectReceipt` docstring for the full rationale).
 *
 * Same shared `InventoryStockChecklist` as Receive to Main Stock/
 * Transfer to Emergency — the Emergency Stock column shows what's
 * already on hand before topping up, and a row for an item with at
 * least one currently-PENDING restock request carries a small "Pending
 * Request" badge, so the Inventory Manager can see at a glance which of
 * today's deliveries are actually satisfying a flagged shortage.
 * Resolving that request is not a separate step here — landing any
 * quantity of the item auto-fulfills every pending request against it
 * server-side (see `InventoryService.receive_directly_to_emergency`'s
 * own docstring for why this is auto-resolved rather than an explicit
 * per-item request link the Inventory Manager would otherwise have to
 * pick). */
export function InventoryReceiveToEmergencyPanel() {
  const { data: items, isLoading, isError, error, refetch } = useInventoryItems();
  const { data: pendingRequests } = useInventoryRequests({ status: 'pending' });
  const receiveDirectlyToEmergency = useReceiveDirectlyToEmergency();
  const [receivedOn, setReceivedOn] = useState(todayDisplayDayKey());

  const activeItems = useMemo(() => (items ?? []).filter((item) => item.is_active), [items]);
  const pendingRequestItemIds = useMemo(
    () => new Set((pendingRequests ?? []).map((request) => request.item_id)),
    [pendingRequests],
  );

  async function handleSubmit(lines) {
    await receiveDirectlyToEmergency.mutateAsync({ items: lines, received_on: receivedOn });
  }

  return (
    <InventoryStockChecklist
      items={activeItems}
      isLoading={isLoading}
      isError={isError}
      error={error}
      onRetry={refetch}
      levelColumnLabel="Emergency Stock"
      getLevel={(item) => item.emergency_stock_level}
      renderBadge={(item) =>
        pendingRequestItemIds.has(item.id) ? (
          <Badge variant="warning" className="shrink-0 text-[10px]">
            Pending Request
          </Badge>
        ) : null
      }
      pickerTitle="Select Items to Receive"
      searchPlaceholder="Search item by name…"
      emptyItemsMessage="No active items in the catalog yet — add one under Catalog first."
      extraFields={
        <div className="flex flex-col gap-1.5 sm:max-w-xs">
          <Label htmlFor="direct_receive_received_on">Received On</Label>
          <Input
            id="direct_receive_received_on"
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
