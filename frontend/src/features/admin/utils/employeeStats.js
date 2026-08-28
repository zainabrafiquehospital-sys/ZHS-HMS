/** Turns one stats endpoint's `[{ user_id, ...fields }]` response into a
 * `{ [user_id]: { ...fields } }` lookup — shared shape for all four of
 * `adminStatsService`'s per-module aggregate responses (visits/bills/
 * consultations/vitals), each already a single `GROUP BY` query
 * server-side. Extracted as its own pure function (rather than left
 * inline in `useEmployeeAccounts.js`) so the merge logic is unit-
 * testable without rendering anything — this codebase's frontend test
 * suite runs under Vitest's `node` environment (see vitest.config.mjs),
 * with no DOM/component-rendering support, so pure-function extraction
 * is how every other non-trivial piece of frontend logic here gets
 * test coverage (e.g. `revenueByActor.js`). */
export function toLookup(rows, valueFields) {
  const byUserId = {};
  for (const row of rows ?? []) {
    byUserId[row.user_id] = Object.fromEntries(valueFields.map((field) => [field, row[field]]));
  }
  return byUserId;
}

/** Merges the five per-module lookups into one user's full activity
 * row, defaulting every category to 0 (or '0.00' for revenue) when
 * that user has no rows in a given module — never `undefined`, so
 * every consumer can render a real number/badge unconditionally.
 * `labBills`/`labRevenue` (Step 4 addition) are named distinctly from
 * `bills`/`revenue` (Medicine's own, unchanged) rather than merged
 * into the same two fields — the two module's bill counts/revenue are
 * always shown as separate columns, never summed together, matching
 * Admin Overview's own Medicine Revenue/Lab Revenue tile split. */
export function mergeEmployeeStats({
  userId,
  visitsByUser,
  billsByUser,
  labBillsByUser,
  consultationsByUser,
  vitalsByUser,
}) {
  return {
    visits: visitsByUser[userId]?.count ?? 0,
    bills: billsByUser[userId]?.count ?? 0,
    revenue: billsByUser[userId]?.revenue ?? '0.00',
    labBills: labBillsByUser[userId]?.count ?? 0,
    labRevenue: labBillsByUser[userId]?.revenue ?? '0.00',
    consultations: consultationsByUser[userId]?.count ?? 0,
    vitals: vitalsByUser[userId]?.count ?? 0,
  };
}
