'use client';

import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { inventoryService } from '@/features/inventory/api/inventoryService';

/** Catalog listing — every item, active and inactive alike (mirrors
 * usePharmacy.js's useMedicines identical shape). `category`/
 * `lowStockOnly` are optional server-side filters (History/Catalog
 * panels each use a subset). */
export function useInventoryItems({ category, lowStockOnly } = {}) {
  return useQuery({
    queryKey: ['inventory', 'items', { category, lowStockOnly }],
    queryFn: () =>
      inventoryService.listItems({ category, lowStockOnly }).then((res) => res.data),
  });
}

function invalidateItems(queryClient) {
  queryClient.invalidateQueries({ queryKey: ['inventory', 'items'] });
}

/** Writes a just-mutated item straight into every cached items-list
 * query, synchronously, in addition to the `invalidateItems` background
 * refetch below — found necessary via an actual Playwright click-
 * through (not a hypothetical): switching from Receive Stock straight
 * to Transfer to Emergency remounts that panel's own `useInventoryItems`
 * call, which — with invalidation alone — briefly renders the *stale*
 * cached stock level (a real "0.00 available" flash right after
 * receiving 50) before its background refetch resolves and corrects it.
 * That's ordinary, expected React Query stale-while-revalidate behavior,
 * not a bug in the invalidation logic — but this hint text is exactly
 * what an Inventory Manager reads to decide how much to transfer, so a
 * multi-hundred-ms window of a visibly wrong number is worth closing
 * outright: the mutation response already *is* the fresh item, with no
 * network round-trip needed to get it, so patch the cache with it
 * immediately rather than waiting on a refetch to correct a flash that
 * never needed to happen. `invalidateItems` stays as a safety net for
 * eventual consistency (e.g. a second browser tab watching the same
 * data), not the primary mechanism for this tab's own read-after-write. */
function patchItemInCache(queryClient, item) {
  if (!item?.id) return;
  queryClient.setQueriesData({ queryKey: ['inventory', 'items'] }, (old) =>
    Array.isArray(old) ? old.map((existing) => (existing.id === item.id ? item : existing)) : old,
  );
}

export function useCreateInventoryItem() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (payload) => inventoryService.createItem(payload),
    onSuccess: () => {
      invalidateItems(queryClient);
      queryClient.invalidateQueries({ queryKey: ['inventory', 'stats'] });
    },
  });
}

export function useUpdateInventoryItem() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({ itemId, payload }) => inventoryService.updateItem(itemId, payload),
    onSuccess: (response) => {
      patchItemInCache(queryClient, response.data);
      invalidateItems(queryClient);
      queryClient.invalidateQueries({ queryKey: ['inventory', 'stats'] });
    },
  });
}

/** Every mutation that moves stock (receipt/transfer/fulfill) also
 * invalidates the relevant history list and stats, so those never lag
 * behind what was just recorded — the catalog itself is handled by
 * `patchItemInCache` at each call site instead (see that function's own
 * docstring for why a plain invalidate isn't enough there). */
function invalidateAfterStockMovement(queryClient) {
  queryClient.invalidateQueries({ queryKey: ['inventory', 'stats'] });
  queryClient.invalidateQueries({ queryKey: ['inventory', 'receipts'] });
  queryClient.invalidateQueries({ queryKey: ['inventory', 'transfers'] });
}

export function useReceiveStock() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({ itemId, payload }) => inventoryService.receiveStock(itemId, payload),
    onSuccess: (response) => {
      patchItemInCache(queryClient, response.data);
      invalidateItems(queryClient);
      invalidateAfterStockMovement(queryClient);
    },
  });
}

export function useTransferStock() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({ itemId, payload }) => inventoryService.transferStock(itemId, payload),
    onSuccess: (response) => {
      patchItemInCache(queryClient, response.data);
      invalidateItems(queryClient);
      invalidateAfterStockMovement(queryClient);
    },
  });
}

export function useInventoryReceipts({ itemId, startDate, endDate } = {}) {
  return useQuery({
    queryKey: ['inventory', 'receipts', { itemId, startDate, endDate }],
    queryFn: () =>
      inventoryService.listReceipts({ itemId, startDate, endDate }).then((res) => res.data),
  });
}

export function useInventoryTransfers({ itemId, startDate, endDate } = {}) {
  return useQuery({
    queryKey: ['inventory', 'transfers', { itemId, startDate, endDate }],
    queryFn: () =>
      inventoryService.listTransfers({ itemId, startDate, endDate }).then((res) => res.data),
  });
}

export function useInventoryUsageEntries({ itemId, startDate, endDate } = {}) {
  return useQuery({
    queryKey: ['inventory', 'usage', { itemId, startDate, endDate }],
    queryFn: () =>
      inventoryService.listUsageEntries({ itemId, startDate, endDate }).then((res) => res.data),
  });
}

export function useInventoryRequests({ status } = {}) {
  return useQuery({
    queryKey: ['inventory', 'requests', { status }],
    queryFn: () => inventoryService.listRequests({ status }).then((res) => res.data),
  });
}

function invalidateRequests(queryClient) {
  queryClient.invalidateQueries({ queryKey: ['inventory', 'requests'] });
  queryClient.invalidateQueries({ queryKey: ['inventory', 'stats'] });
}

export function useFulfillRequest() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({ requestId, payload }) => inventoryService.fulfillRequest(requestId, payload),
    onSuccess: () => {
      // Unlike receive/transfer, this response is the resolved
      // InventoryRestockRequestOut, not the mutated item — no direct
      // patch target, so this falls back to plain invalidation (a
      // background refetch, same small stale-read window
      // patchItemInCache exists to close for receive/transfer's own
      // more decision-critical "available to transfer" hint). Accepted
      // here: the Restock Requests panel has no equivalent live figure
      // a manager reads mid-action the way Transfer's hint does.
      invalidateItems(queryClient);
      invalidateRequests(queryClient);
      invalidateAfterStockMovement(queryClient);
    },
  });
}

export function useRejectRequest() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({ requestId, payload }) => inventoryService.rejectRequest(requestId, payload),
    onSuccess: () => invalidateRequests(queryClient),
  });
}

/** Pending-requests + low-stock-items counts — the Inventory Manager's
 * own dashboard indicator (Admin Overview gets the identical figures
 * via its own fetch, added in a later step). */
export function useInventoryStats() {
  return useQuery({
    queryKey: ['inventory', 'stats'],
    queryFn: () => inventoryService.getStats().then((res) => res.data),
  });
}

// ------------------------------------------------------------------
// Vitals' own two actions (step 4) — record usage against Emergency
// Stock, raise a restock request. Both live here (not a separate
// vitals-owned hooks module) since they're thin wrappers over the same
// inventoryService/query-key space every hook above already shares —
// the Vitals feature's own components import these directly, the same
// cross-feature-imports-a-service pattern RegisterVisitForm.jsx already
// establishes for pharmacyService.
// ------------------------------------------------------------------

export function useRecordInventoryUsage() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (payload) => inventoryService.recordUsage(payload),
    onSuccess: () => {
      // record_usage's response has no item to spare for
      // patchItemInCache (InventoryUsageEntryOut, not InventoryItemOut)
      // — plain invalidation here, same acceptance as useFulfillRequest.
      invalidateItems(queryClient);
      queryClient.invalidateQueries({ queryKey: ['inventory', 'stats'] });
      queryClient.invalidateQueries({ queryKey: ['inventory', 'usage'] });
    },
  });
}

export function useRaiseInventoryRestockRequest() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (payload) => inventoryService.raiseRestockRequest(payload),
    onSuccess: () => invalidateRequests(queryClient),
  });
}

/** The usage-entry screen's read-only patient preview — see
 * inventoryService.getPatientContext's own docstring. Disabled until a
 * patient is actually picked, same `enabled: Boolean(...)` convention
 * as every other on-demand hook in this codebase (e.g. usePharmacy.js's
 * useMedicineBillDetail). */
export function useInventoryPatientContext(patientId) {
  return useQuery({
    queryKey: ['inventory', 'patient-context', patientId],
    queryFn: () => inventoryService.getPatientContext(patientId).then((res) => res.data),
    enabled: Boolean(patientId),
  });
}
