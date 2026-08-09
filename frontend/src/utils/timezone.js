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

// Mirrors backend/app/modules/auth/models.py's Shift enum (MORNING/
// NIGHT — the hospital's own two-shift model), but the actual
// clock-hour boundary between them is not defined anywhere in this
// codebase (confirmed: no backend config, no existing frontend
// component). This is a reasonable, standard two-shift hospital split
// (08:00-20:00 = morning, else night) picked to build the "which shift
// is it right now" badge Reception/Vitals both need — adjust here if
// the hospital's actual shift changeover time differs.
const _MORNING_SHIFT_START_HOUR = 8;
const _MORNING_SHIFT_END_HOUR = 20;

/** Which `Shift` enum value the current moment falls into, in
 * DISPLAY_TIMEZONE — backs the "Morning/Night" badge shown to shift-
 * based staff (Reception, Vitals) so they can see at a glance which
 * shift is currently active, independent of their own account's
 * `shift` field (that's which shift they're assigned to, not which one
 * is live right now). */
export function getCurrentShift() {
  const hour = Number(_hourFormatter.format(new Date()));
  return hour >= _MORNING_SHIFT_START_HOUR && hour < _MORNING_SHIFT_END_HOUR ? 'morning' : 'night';
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
