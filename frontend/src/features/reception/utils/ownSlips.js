import { displayDayKey, isWithinCurrentShiftWindow } from '@/utils/timezone';

/** Pure "which of these visits did this specific user create today"
 * filter — extracted out of `useTodaysRegistrations`
 * (features/reception/hooks/useReception.js) so it is testable without
 * any React/DOM machinery, the same "logic lives in a plain function,
 * the hook just calls it" split as features/admin/utils/
 * revenueByActor.js's `computeRevenueByActor`.
 *
 * Depends on nothing but its own arguments — no session object read
 * internally, no module-level state, no clock read internally (the
 * caller supplies `today`, e.g. via utils/timezone.js's
 * `todayDisplayDayKey()`) — so calling it twice with the same
 * `visits`/`userId`/`today` always returns the same result. That
 * determinism is the property the whole "own slips" feature depends
 * on: what is shown is always exactly a fresh `created_by === userId
 * AND displayDayKey(created_at) === today` comparison against the
 * real fetched records, never anything a logout/login, a closed tab,
 * or a lost session could change independently of the underlying
 * data. `userId` falsy (session not yet resolved, or a caller
 * explicitly passing `null`) never matches anything, including a
 * visit whose own `created_by` happens to be `null` (a visit whose
 * creating user was later deleted — BaseEntity's `created_by` is `ON
 * DELETE SET NULL`) — "no known user" must never coincidentally match
 * "no recorded creator". */
export function selectOwnSlipsToday(visits, userId, today) {
  if (!userId) return [];
  return (visits ?? []).filter(
    (visit) => visit.created_by === userId && displayDayKey(visit.created_at) === today,
  );
}

/** Pure "which of these visits did this specific user create during the
 * CURRENTLY-ACTIVE shift" filter — the cross-midnight-safe sibling of
 * `selectOwnSlipsToday` above, added alongside it rather than replacing
 * it (see useReception.js's `useTodaysRegistrations` docstring for why
 * the calendar-day selector alone stays the primary "My Revenue Today"/
 * "My Slips Today" figures unchanged). Uses `isWithinCurrentShiftWindow`
 * (utils/timezone.js) rather than a calendar-day comparison specifically
 * so a Night-shift receptionist's pre-midnight visits stay counted after
 * the calendar day rolls over — the same real start/end-instant window
 * `getCurrentShiftWindow` resolves, not just "same hour-of-day bucket".
 *
 * `now` is an optional override (defaults to the real current moment)
 * purely for deterministic testing — every real caller omits it, the
 * same convention `getCurrentShiftWindow`/`isWithinCurrentShiftWindow`
 * themselves already use. Same falsy-`userId`/null-`created_by`
 * isolation guarantees as `selectOwnSlipsToday`. */
export function selectOwnSlipsCurrentShift(visits, userId, now = new Date()) {
  if (!userId) return [];
  return (visits ?? []).filter(
    (visit) => visit.created_by === userId && isWithinCurrentShiftWindow(visit.created_at, now),
  );
}
