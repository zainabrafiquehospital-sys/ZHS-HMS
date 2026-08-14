// Sentinel actorId for the folded "everyone past the top 3" bucket —
// exported so callers (RevenueByActorPieChart's consumer) can compare
// against it without duplicating the literal. An empty string/UUID can
// never coincide with a real `created_by`, so this is safe as a plain
// string constant rather than needing a Symbol.
export const OTHER_ACTOR_ID = '__other__';

// A pie/donut is an "all-pairs" chart form (any two slices can sit next
// to each other depending on the day's ranking, not just neighbors) —
// per the `dataviz` skill's palette.md, the documented default
// categorical palette only validates all-pairs CVD-safety for its
// first THREE slots; past three, more hues is not a passing option
// ("fold to Other or facet — not a palette change"). That caps how
// many receptionists this chart can name directly at once, regardless
// of how many actually posted revenue that day.
export const MAX_NAMED_SLICES = 3;

/** Buckets `records` (each shaped `{ created_at, created_by,
 * [amountKey]: number|string }`) into per-receptionist revenue totals,
 * derived live every time this is called from whatever day's records
 * the caller already fetched — never a stored/"cleared" running total.
 * Every bucket sums back to exactly the full-day total by construction
 * (every input record lands in exactly one bucket), so the caller
 * never needs a separate reconciliation step.
 *
 * Grouped by `created_by` — `null` (a record whose creating user was
 * later deleted; BaseEntity's `created_by` is `ON DELETE SET NULL`) is
 * its own distinct bucket, exactly like any other actor id, and
 * competes for a named slot on the same footing.
 *
 * Sorted descending by revenue and capped at `MAX_NAMED_SLICES`: the
 * top contributors are returned as their own `{ actorId, amount }`
 * entries, and everyone beyond that is summed into one final
 * `{ actorId: OTHER_ACTOR_ID, amount }` entry — never more entries
 * than the palette can safely carry (see `MAX_NAMED_SLICES`'s own
 * comment). With `MAX_NAMED_SLICES` or fewer contributors that day,
 * there is no "Other" entry at all. */
export function computeRevenueByActor(records, amountKey) {
  const totalsByActor = new Map();
  for (const record of records ?? []) {
    const actorId = record.created_by ?? null;
    totalsByActor.set(actorId, (totalsByActor.get(actorId) ?? 0) + Number(record[amountKey]));
  }

  const sorted = [...totalsByActor.entries()]
    .map(([actorId, amount]) => ({ actorId, amount }))
    .sort((a, b) => b.amount - a.amount);

  if (sorted.length <= MAX_NAMED_SLICES) return sorted;

  const named = sorted.slice(0, MAX_NAMED_SLICES);
  const otherAmount = sorted
    .slice(MAX_NAMED_SLICES)
    .reduce((sum, entry) => sum + entry.amount, 0);
  return [...named, { actorId: OTHER_ACTOR_ID, amount: otherAmount }];
}

/** Resolves `computeRevenueByActor`'s output to what
 * RevenueByActorPieChart actually renders: `[{ actorId, label, amount,
 * isOther }]`. `usersById` is whatever the caller's own join hook
 * already produced (useReceptionistsForVisits / useUsersForMedicineBills
 * — see those hooks' docstrings), so this does no fetching of its own.
 *
 * A resolved user's label is `full_name`, falling back to `email` only
 * when the user object has no display name — no further fallback
 * chain beyond that. A `null` actorId (the record's creating user was
 * later deleted) gets its own fixed "Unknown" label rather than being
 * looked up. The `OTHER_ACTOR_ID` sentinel becomes "Other". Both keep
 * a stable, always-defined `actorId` string for React keying, since a
 * label alone (two receptionists can plausibly share a display name)
 * is not guaranteed unique. */
export function resolveActorSlices(breakdown, usersById) {
  return (breakdown ?? []).map((entry) => {
    if (entry.actorId === OTHER_ACTOR_ID) {
      return { actorId: OTHER_ACTOR_ID, label: 'Other', amount: entry.amount, isOther: true };
    }
    if (entry.actorId === null) {
      return { actorId: 'unknown', label: 'Unknown', amount: entry.amount, isOther: false };
    }
    const user = usersById?.[entry.actorId];
    const label = user?.full_name || user?.email || '…';
    return { actorId: entry.actorId, label, amount: entry.amount, isOther: false };
  });
}
