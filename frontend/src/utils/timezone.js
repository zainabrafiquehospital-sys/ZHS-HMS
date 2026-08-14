/**
 * Mirrors the backend's `DISPLAY_TIMEZONE` setting (see
 * backend/app/core/config.py — default "Asia/Karachi", used there to
 * render local wall-clock times on printed documents). Every timestamp
 * this app receives from the API is UTC; this is the one place that
 * gets converted to the hospital's display timezone on the frontend,
 * mirroring the backend's own single-conversion-point convention.
 *
 * Follow-up: there is currently no API-exposed way for the frontend to
 * read the backend's actual configured `DISPLAY_TIMEZONE` value, so this
 * is a hardcoded mirror of its default rather than a live setting — if
 * that default is ever changed in a deployment's `.env`, this constant
 * must be updated to match (or, better, exposed via a public config
 * endpoint/response field so the two can never drift).
 */
export const DISPLAY_TIMEZONE = 'Asia/Karachi';

const _dayKeyFormatter = new Intl.DateTimeFormat('en-CA', {
  timeZone: DISPLAY_TIMEZONE,
  year: 'numeric',
  month: '2-digit',
  day: '2-digit',
});

const _timeFormatter = new Intl.DateTimeFormat('en-US', {
  timeZone: DISPLAY_TIMEZONE,
  hour: 'numeric',
  minute: '2-digit',
  hour12: true,
});

const _friendlyDateFormatter = new Intl.DateTimeFormat('en-US', {
  timeZone: DISPLAY_TIMEZONE,
  weekday: 'long',
  year: 'numeric',
  month: 'long',
  day: 'numeric',
});

/** "2026-08-07"-style calendar-day key for `isoTimestamp`, computed in
 * DISPLAY_TIMEZONE rather than the browser's local timezone — two
 * timestamps sharing this key fall on the same hospital-local day. */
export function displayDayKey(isoTimestamp) {
  return _dayKeyFormatter.format(new Date(isoTimestamp));
}

/** Today's calendar-day key in DISPLAY_TIMEZONE, computed from the
 * caller's current moment (not the browser's local calendar day, which
 * can differ from Asia/Karachi's near midnight). */
export function todayDisplayDayKey() {
  return _dayKeyFormatter.format(new Date());
}

/** "10:45 AM"-style wall-clock time for `isoTimestamp`, in
 * DISPLAY_TIMEZONE — for showing a UTC-stored `created_at` the way
 * front-desk staff actually experience the time of day. */
export function formatDisplayTime(isoTimestamp) {
  return _timeFormatter.format(new Date(isoTimestamp));
}

/** Shifts a `displayDayKey`-shaped "YYYY-MM-DD" string by `deltaDays` —
 * pure calendar-date arithmetic (no timezone conversion involved: a
 * date-only key has no time-of-day component to convert), used to
 * build day-by-day prev/next navigation without re-deriving today's
 * date through the DISPLAY_TIMEZONE formatter on every step. */
export function shiftDisplayDayKey(dayKey, deltaDays) {
  const [year, month, day] = dayKey.split('-').map(Number);
  const date = new Date(Date.UTC(year, month - 1, day));
  date.setUTCDate(date.getUTCDate() + deltaDays);
  const y = date.getUTCFullYear();
  const m = String(date.getUTCMonth() + 1).padStart(2, '0');
  const d = String(date.getUTCDate()).padStart(2, '0');
  return `${y}-${m}-${d}`;
}

const _hourFormatter = new Intl.DateTimeFormat('en-US', {
  timeZone: DISPLAY_TIMEZONE,
  hour: 'numeric',
  hour12: false,
});

// A "which shift is it right now" concept, computed live from clock
// time only — never a stored assignment. This is deliberately a
// *different* concept from backend/app/modules/auth/models.py's stored
// `Shift` enum (MORNING/NIGHT) a staff member picks once at signup
// (see SignupForm.jsx) and which only ever gets *displayed* elsewhere
// (PendingApprovals.jsx) — that field answers "which shift is this
// person assigned to work"; everything in this section answers "which
// shift is it right now", and the two are allowed to disagree (a
// Morning-assigned receptionist working late still sees "Night" here).
// The stored field stays a 2-way Morning/Night choice; it is out of
// scope here — expanding it would mean a migration inside the frozen
// auth module, which nothing below needs.
//
// Three ~8h shifts, mirroring a realistic hospital rotation. Boundary
// hours (24h clock, DISPLAY_TIMEZONE): adjust here if the hospital's
// actual shift changeover times differ. `night` is the one shift that
// spans across midnight (22:00 on one calendar day to 06:00 on the
// next) — see `_shiftForHour` below for how a wrapping range is
// matched.
export const SHIFT_ORDER = ['morning', 'evening', 'night'];
const _SHIFT_BOUNDARIES = {
  morning: { startHour: 6, endHour: 14 },
  evening: { startHour: 14, endHour: 22 },
  night: { startHour: 22, endHour: 6 }, // wraps past midnight
};

function _shiftForHour(hour) {
  return SHIFT_ORDER.find((shift) => {
    const { startHour, endHour } = _SHIFT_BOUNDARIES[shift];
    return startHour < endHour
      ? hour >= startHour && hour < endHour
      : hour >= startHour || hour < endHour;
  });
}

/** Which shift `isoTimestamp` (or "now", if omitted) falls into, in
 * DISPLAY_TIMEZONE — classifies a single moment by its own hour, with
 * no notion of which continuous shift-instance it belongs to. Used by
 * `getCurrentShift` below. */
export function getShiftForTimestamp(isoTimestamp) {
  const hour = Number(_hourFormatter.format(isoTimestamp ? new Date(isoTimestamp) : new Date()));
  return _shiftForHour(hour);
}

/** Which shift is live right now, in DISPLAY_TIMEZONE — backs the
 * "Morning/Evening/Night" badge shown to shift-based staff (Reception,
 * Vitals) so they can see at a glance which shift is currently active.
 * See this section's own docstring for why this is unrelated to the
 * account's own stored `shift` field. */
export function getCurrentShift() {
  return getShiftForTimestamp();
}

// DISPLAY_TIMEZONE is a fixed UTC+5 offset (Asia/Karachi, no DST) — see
// formatDisplayDate's docstring for the identical assumption. That
// fixed offset is what makes "DISPLAY_TIMEZONE hour H on calendar day
// D" convertible to a real UTC instant by plain hour arithmetic, no
// timezone-database lookup needed.
const _DISPLAY_TIMEZONE_UTC_OFFSET_HOURS = 5;

function _displayTimeToUtcInstant(dayKey, hour) {
  const [year, month, day] = dayKey.split('-').map(Number);
  return new Date(Date.UTC(year, month - 1, day, hour - _DISPLAY_TIMEZONE_UTC_OFFSET_HOURS, 0, 0));
}

/** The currently-active shift's real start/end instants (`Date`
 * objects), not just which shift it is — safe to compare directly
 * against any `created_at` timestamp. This is what makes "show me
 * everything created during my current shift" correct across a
 * midnight rollover: a plain calendar-day filter
 * (`displayDayKey(x) === todayDisplayDayKey()`) silently drops
 * anything created before midnight the moment the day rolls over,
 * even though that receptionist's shift (Night, 22:00->06:00) is
 * still ongoing. Correctly resolves which calendar day the window's
 * start/end actually fall on, whichever half of a wrapping shift
 * "now" happens to be in.
 *
 * Relies on DISPLAY_TIMEZONE (Asia/Karachi) being a fixed UTC+5 offset
 * with no DST — the same assumption `formatDisplayDate`'s docstring
 * already documents and relies on. */
export function getCurrentShiftWindow(now = new Date()) {
  const hour = Number(_hourFormatter.format(now));
  const todayKey = _dayKeyFormatter.format(now);
  const shift = _shiftForHour(hour);
  const { startHour, endHour } = _SHIFT_BOUNDARIES[shift];
  const wraps = startHour > endHour;
  // For a wrapping shift, "now" is either in its late half (started
  // today, ends tomorrow — e.g. 23:00 within Night's 22:00->06:00) or
  // its early/post-midnight half (started yesterday, ends today — e.g.
  // 02:00 within that same window).
  const startedYesterday = wraps && hour < endHour;
  const startDayKey = startedYesterday ? shiftDisplayDayKey(todayKey, -1) : todayKey;
  const endDayKey = wraps ? shiftDisplayDayKey(startDayKey, 1) : startDayKey;
  return {
    shift,
    startsAt: _displayTimeToUtcInstant(startDayKey, startHour),
    endsAt: _displayTimeToUtcInstant(endDayKey, endHour),
  };
}

/** Whether `isoTimestamp` falls within the currently-active shift's
 * window — the cross-midnight-safe replacement for a calendar-day
 * filter (`displayDayKey(x) === todayDisplayDayKey()`), used by
 * anything that must show "everything created during the current
 * shift" rather than "everything created on today's calendar date". */
export function isWithinCurrentShiftWindow(isoTimestamp, now = new Date()) {
  const { startsAt, endsAt } = getCurrentShiftWindow(now);
  const moment = new Date(isoTimestamp);
  return moment >= startsAt && moment < endsAt;
}

/** "Friday, August 7, 2026"-style label for a `displayDayKey` — safe
 * only for a DISPLAY_TIMEZONE with a non-negative UTC offset (true for
 * Asia/Karachi, UTC+5, fixed, no DST): formatting a UTC-midnight moment
 * in a zone ahead of UTC keeps the same calendar date. A future
 * negative-offset DISPLAY_TIMEZONE would need this reworked — same
 * hardcoded-mirror caveat as this module's docstring already flags. */
export function formatDisplayDate(dayKey) {
  const [year, month, day] = dayKey.split('-').map(Number);
  return _friendlyDateFormatter.format(new Date(Date.UTC(year, month - 1, day)));
}
