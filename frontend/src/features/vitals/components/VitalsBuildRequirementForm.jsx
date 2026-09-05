'use client';

import { useMemo } from 'react';
import { Bell, FileDown } from 'lucide-react';
import {
  useInventoryItems,
  usePrintRequirementList,
  useRaiseInventoryRestockRequests,
} from '@/features/inventory/hooks/useInventory';
import { InventoryStockChecklist } from '@/features/inventory/components/InventoryStockChecklist';
import { Badge } from '@/shared/components/ui/Badge';

/** Vitals' "Build Requirement" checklist (2026-09 redesign, replacing
 * the earlier one-item-at-a-time RaiseRestockRequestForm.jsx) — the
 * first half of a two-step real-world cycle: Vitals builds this list
 * and shares the downloaded PDF to the hospital's WhatsApp group, then
 * whatever arrives gets logged by the Inventory Manager via the
 * "Receive to Emergency" checklist (see backend/app/modules/inventory/
 * models.py's `InventoryEmergencyDirectReceipt` docstring), which
 * auto-resolves whichever items here were also formally raised as
 * tracked requests below.
 *
 * Built on the same shared `InventoryStockChecklist` as the Inventory
 * Manager's own three stock-movement screens, with its
 * `allowEmptyQuantity` mode (a checkbox per row, since
 * `InventoryRestockRequest.requested_quantity` is optional — "just flag
 * it low" is a legitimate request with no number attached) and its
 * `secondaryAction` slot (this screen's two genuinely independent
 * actions: raising the tracked requests, and downloading the PDF —
 * neither is a prerequisite for the other).
 *
 * Every item is shown, not just active ones — the identical reasoning
 * RaiseRestockRequestForm.jsx's own docstring gave: an item someone
 * just deactivated by mistake is exactly the kind of thing worth
 * surfacing, not hidden from this picker.
 *
 * Raising requests fires one `POST /inventory/requests` per line
 * *concurrently*, not a new atomic batch endpoint — see
 * `useRaiseInventoryRestockRequests`'s own docstring for why a bare,
 * lock-free insert has no atomicity property worth building a batch
 * endpoint to protect. A partial failure is reported by name so the
 * user knows exactly which items still need a retry, without losing
 * the ones that already succeeded.
 *
 * The per-request free-text "note" field the old single-item form had
 * is deliberately dropped here (confirmed design) — the shared
 * checklist's row shape has no room for it without deviating from the
 * established pattern every other screen already uses. */
export function VitalsBuildRequirementForm() {
  const { data: items, isLoading, isError, error, refetch } = useInventoryItems();
  const raiseRequests = useRaiseInventoryRestockRequests();
  const printRequirementList = usePrintRequirementList();

  const eligibleItems = useMemo(() => items ?? [], [items]);

  async function handleSubmit(lines) {
    const result = await raiseRequests.mutateAsync(lines);
    if (result.failed.length > 0) {
      const failedNames = result.failed
        .map(
          ({ line }) =>
            eligibleItems.find((item) => item.id === line.item_id)?.name ?? 'Unknown item',
        )
        .join(', ');
      throw new Error(
        `${result.succeeded.length} of ${lines.length} raised. Failed: ${failedNames} — try again for these.`,
      );
    }
  }

  async function handleDownloadPdf(lines) {
    await printRequirementList.mutateAsync(lines);
  }

  return (
    <InventoryStockChecklist
      items={eligibleItems}
      isLoading={isLoading}
      isError={isError}
      error={error}
      onRetry={refetch}
      levelColumnLabel="Emergency Stock"
      getLevel={(item) => (
        <span className="inline-flex items-center gap-1.5">
          {item.emergency_stock_level}
          {item.is_low_stock ? (
            <Badge variant="destructive" className="text-[10px]">
              Low
            </Badge>
          ) : null}
        </span>
      )}
      renderBadge={(item) =>
        !item.is_active ? (
          <Badge variant="outline" className="shrink-0 text-[10px]">
            Inactive
          </Badge>
        ) : null
      }
      pickerTitle="Select Items Needed"
      searchPlaceholder="Search item by name…"
      emptyItemsMessage="No items in the catalog yet."
      allowEmptyQuantity
      recapTitle="Requirement List"
      submitLabel="Raise Requests"
      submittingLabel="Raising…"
      submitIcon={Bell}
      onSubmit={handleSubmit}
      secondaryActionLabel="Download Requirement PDF"
      secondaryActionIcon={FileDown}
      onSecondaryAction={handleDownloadPdf}
    />
  );
}
