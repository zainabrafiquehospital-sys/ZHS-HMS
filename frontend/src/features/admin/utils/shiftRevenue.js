import { SHIFT_ORDER, getShiftForTimestamp } from '@/utils/timezone';

/** Buckets `records` (each shaped `{ created_at, [amountKey]: number|string }`)
 * into per-shift revenue totals, in `SHIFT_ORDER` order — classified by
 * each record's own `created_at` hour (utils/timezone.js's
 * `getShiftForTimestamp`), derived live every time this is called,
 * never a stored/"cleared" shift total. Every bucket sums back to
 * exactly the full-day total by construction: every input record lands
 * in exactly one of the three buckets, nothing dropped or double-
 * counted — so the caller never needs a separate reconciliation step.
 *
 * Scoped to whatever day's records the caller already fetched (Admin
 * Overview's day picker is a calendar-day concept). For a shift that
 * spans midnight (Night, 22:00->06:00), this buckets a day's own
 * 22:00-24:00 records as "Night", and that SAME day's 00:00-06:00
 * records also as "Night" — by their own creation hour, not by which
 * continuous shift-instance they truly belong to (the instance
 * covering a day's 00:00-06:00 actually started the previous calendar
 * day). That is a deliberate simplification: it keeps "per-shift sum
 * reconciles to the full-day total" trivially true for whichever day
 * is selected, rather than introducing a shift-spans-two-calendar-days
 * concept the day picker isn't built around. */
export function computeShiftRevenueBreakdown(records, amountKey) {
  const totals = Object.fromEntries(SHIFT_ORDER.map((shift) => [shift, 0]));
  for (const record of records ?? []) {
    const shift = getShiftForTimestamp(record.created_at);
    totals[shift] += Number(record[amountKey]);
  }
  return SHIFT_ORDER.map((shift) => ({ shift, amount: totals[shift] }));
}
