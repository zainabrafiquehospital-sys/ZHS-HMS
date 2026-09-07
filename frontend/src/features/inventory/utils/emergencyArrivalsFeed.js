/**
 * Merges the two "stock arriving into Emergency Stock" ledgers into one
 * chronological feed for InventoryEmergencyFeedPanel.jsx:
 *   - direct-to-Emergency receipts  (GET /inventory/emergency-receipts)
 *   - Main-Stock -> Emergency transfers (GET /inventory/transfers)
 *
 * Each ledger already comes back newest-first server-side. This tags
 * every row with its `source`, normalizes the two differently-named
 * "effective date" columns (`received_on` vs `transferred_on`) to one
 * `effective_on`, then merge-sorts by `created_at` (the real wall-clock
 * entry time, present on both) and caps the result.
 *
 * Pure — no React, no network — so it is unit-tested directly, the same
 * rationale as features/pharmacy/utils/patientLinkage.js (this repo's
 * frontend has no component-test setup).
 */

export const ARRIVAL_SOURCE = {
  DIRECT: 'direct',
  TRANSFER: 'transfer',
};

export const ARRIVAL_SOURCE_LABEL = {
  [ARRIVAL_SOURCE.DIRECT]: 'Direct Receipt',
  [ARRIVAL_SOURCE.TRANSFER]: 'Transfer from Main Stock',
};

export const DEFAULT_FEED_LIMIT = 40;

/**
 * @param {Array} directReceipts  rows from GET /inventory/emergency-receipts
 * @param {Array} transfers       rows from GET /inventory/transfers
 * @param {{limit?: number}} [options]
 * @returns {Array} normalized feed entries, most recent `created_at` first
 */
export function buildEmergencyArrivalsFeed(
  directReceipts,
  transfers,
  { limit = DEFAULT_FEED_LIMIT } = {},
) {
  const direct = (directReceipts ?? []).map((row) => ({
    id: row.id,
    source: ARRIVAL_SOURCE.DIRECT,
    item_id: row.item_id,
    quantity: row.quantity,
    effective_on: row.received_on,
    created_at: row.created_at,
    created_by_display_name: row.created_by_display_name ?? null,
    carried_by_name: null,
  }));
  const transferred = (transfers ?? []).map((row) => ({
    id: row.id,
    source: ARRIVAL_SOURCE.TRANSFER,
    item_id: row.item_id,
    quantity: row.quantity,
    effective_on: row.transferred_on,
    created_at: row.created_at,
    created_by_display_name: row.created_by_display_name ?? null,
    carried_by_name: row.carried_by_name ?? null,
  }));

  return [...direct, ...transferred]
    .sort((a, b) => {
      // `created_at` desc, then `id` desc as a stable tiebreaker — a
      // batch writes N rows in one transaction sharing one `created_at`,
      // so the raw timestamp alone is not a total order.
      if (a.created_at !== b.created_at) return a.created_at < b.created_at ? 1 : -1;
      if (a.id === b.id) return 0;
      return a.id < b.id ? 1 : -1;
    })
    .slice(0, limit);
}
