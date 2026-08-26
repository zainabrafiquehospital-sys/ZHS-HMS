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
    onSuccess: () => {
      invalidateItems(queryClient);
      queryClient.invalidateQueries({ queryKey: ['inventory', 'stats'] });
    },
  });
}

/** Every mutation that moves stock (receipt/transfer/fulfill) also
 * invalidates the catalog (both stock levels live on InventoryItem) and
 * the relevant history list, so the numbers on screen never lag behind
 * what was just recorded. */
function invalidateAfterStockMovement(queryClient) {
  invalidateItems(queryClient);
  queryClient.invalidateQueries({ queryKey: ['inventory', 'stats'] });
  queryClient.invalidateQueries({ queryKey: ['inventory', 'receipts'] });
  queryClient.invalidateQueries({ queryKey: ['inventory', 'transfers'] });
}

export function useReceiveStock() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({ itemId, payload }) => inventoryService.receiveStock(itemId, payload),
    onSuccess: () => invalidateAfterStockMovement(queryClient),
  });
}

export function useTransferStock() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({ itemId, payload }) => inventoryService.transferStock(itemId, payload),
    onSuccess: () => invalidateAfterStockMovement(queryClient),
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
