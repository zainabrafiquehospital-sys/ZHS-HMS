/** How many pages a `PaginationMeta.total` count spans at `pageSize`
 * per page — shared by both the Patient Directory and Employee
 * Accounts & Stats pages' Previous/Next controls. Always at least 1
 * (an empty result set is still "page 1 of 1", not "page 1 of 0" —
 * matches `AdminOverview.jsx`'s own client-side pagination block's
 * identical floor). */
export function computePageCount(total, pageSize) {
  if (!total || total <= 0 || !pageSize || pageSize <= 0) return 1;
  return Math.max(1, Math.ceil(total / pageSize));
}
