'use client';

import { keepPreviousData, useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { inventoryService } from '@/features/inventory/api/inventoryService';
import { openAndPrintHtml } from '@/utils/printWindow';

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
function patchItemInCache(queryClient, itemOrItems) {
  // Accepts either one item (receive/update's own response shape) or an
  // array (transfer's batch response, 2026-08-28 — a batch can touch
  // more than one item at once) — same synchronous-write-into-cache
  // fix either way.
  const items = (Array.isArray(itemOrItems) ? itemOrItems : [itemOrItems]).filter((item) => item?.id);
  if (items.length === 0) return;
  const byId = new Map(items.map((item) => [item.id, item]));
  queryClient.setQueriesData({ queryKey: ['inventory', 'items'] }, (old) =>
    Array.isArray(old) ? old.map((existing) => byId.get(existing.id) ?? existing) : old,
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
    mutationFn: (payload) => inventoryService.transferStock(payload),
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

/** `pageSize` (2026-09-04 addition) lets a caller widen the default
 * page-1-of-50 fetch this endpoint otherwise uses — the Daily Usage view
 * (DailyInventoryUsage.jsx) passes a generous bound (mirroring the
 * backend's own `_ALL_ROWS_PAGE_SIZE` the print endpoint uses) since it
 * needs one hospital-wide day's *entire* result set to group and search
 * client-side, not one page of it.
 *
 * `isToday` (same addition) opts this query into the app's established
 * `refetchInterval` + `refetchIntervalInBackground: true` live-polling
 * convention (see useMyQueue/useUnassignedQueue/useVitalsForVisits for
 * precedent, and QueryProvider.jsx's global `refetchOnWindowFocus:
 * false` for why `refetchIntervalInBackground` specifically must be
 * true — otherwise a backgrounded tab's poll silently pauses and never
 * self-corrects). Deliberately never set for a past date: a past day's
 * usage history is immutable, so polling it would just be wasted
 * network traffic. */
export function useInventoryUsageEntries({
  itemId,
  createdBy,
  startDate,
  endDate,
  pageSize,
  isToday,
} = {}) {
  return useQuery({
    queryKey: ['inventory', 'usage', { itemId, createdBy, startDate, endDate, pageSize }],
    queryFn: () =>
      inventoryService
        .listUsageEntries({ itemId, createdBy, startDate, endDate, pageSize })
        .then((res) => res.data),
    ...(isToday ? { refetchInterval: 15000, refetchIntervalInBackground: true } : {}),
  });
}

/** Every Emergency Stock usage entry the calling Vitals staff member
 * has personally recorded, newest first — real server-side pagination
 * (unlike MyVitalsRecords.jsx's own client-capped-fetch shape:
 * `GET /inventory/usage` already supports genuine `page`/`page_size`/
 * `meta.total`, so there's no reason to approximate it client-side
 * here). Backs "My Inventory Usage" (features/vitals/components/
 * MyInventoryUsage.jsx) — the fix for usage entries that were being
 * recorded correctly but were never visible anywhere to the person who
 * recorded them (confirmed: `GET /inventory/usage/mine` existed but had
 * no frontend caller; this reuses the general, already-paginated
 * `GET /inventory/usage` instead, scoped via `created_by`). */
export function useMyInventoryUsage({ userId, page, pageSize }) {
  const query = useQuery({
    queryKey: ['inventory', 'usage', 'mine', userId, { page, pageSize }],
    queryFn: () =>
      inventoryService
        .listUsageEntries({ createdBy: userId, page, pageSize })
        .then((res) => ({ entries: res.data, meta: res.meta })),
    enabled: Boolean(userId),
    placeholderData: keepPreviousData,
  });
  return {
    ...query,
    entries: query.data?.entries ?? [],
    meta: query.data?.meta ?? null,
  };
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

// ------------------------------------------------------------------
// Print (step 6) — fetches the report as an HTML document and opens it
// in a hidden iframe for the browser's own print pipeline (Print, or
// "Save as PDF" as a destination in that same dialog — see
// backend/app/shared/printing/service.py's own module docstring on why
// this is the whole mechanism, no separate PDF-generation endpoint).
// Same `usePrintMedicineBill`/`fetchMedicineBillReceiptHtml` shape
// every other print action in this app already uses.
// ------------------------------------------------------------------

export function usePrintInventoryHistoryLog() {
  return useMutation({
    mutationFn: async ({ logType, itemId, startDate, endDate }) => {
      const html = await inventoryService.fetchHistoryLogHtml({
        logType,
        itemId,
        startDate,
        endDate,
      });
      await openAndPrintHtml(html);
    },
  });
}

/** The Daily Usage view's day-wise A4 print (2026-09-04 addition) —
 * reuses this exact fetch-then-openAndPrintHtml shape, hitting the new
 * thin `GET /inventory/usage/daily/print?date=` wrapper (see
 * backend/app/modules/inventory/router.py's print_daily_usage docstring)
 * rather than a second print mechanism. Independent of whatever the
 * on-screen search box currently filters to — always the full day. */
export function usePrintDailyInventoryUsage() {
  return useMutation({
    mutationFn: async ({ date }) => {
      const html = await inventoryService.fetchDailyUsagePrintHtml(date);
      await openAndPrintHtml(html);
    },
  });
}

