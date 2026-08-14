import { describe, expect, it } from 'vitest';
import {
  SHIFT_ORDER,
  getCurrentShiftWindow,
  getShiftForTimestamp,
  isWithinCurrentShiftWindow,
} from './timezone';

// DISPLAY_TIMEZONE (Asia/Karachi) is a fixed UTC+5 offset — builds a
// UTC Date instant for a given DISPLAY_TIMEZONE wall-clock time,
// mirroring timezone.js's own fixed-offset assumption exactly.
function karachi(dayKey, hour, minute = 0) {
  const [y, m, d] = dayKey.split('-').map(Number);
  return new Date(Date.UTC(y, m - 1, d, hour - 5, minute, 0));
}

describe('SHIFT_ORDER', () => {
  it('is exactly the three shifts, in display order', () => {
    expect(SHIFT_ORDER).toEqual(['morning', 'evening', 'night']);
  });
});

describe('getShiftForTimestamp — boundary edges', () => {
  it('classifies every exact shift-changeover hour correctly', () => {
    expect(getShiftForTimestamp(karachi('2026-08-12', 5, 59))).toBe('night');
    expect(getShiftForTimestamp(karachi('2026-08-12', 6, 0))).toBe('morning');
    expect(getShiftForTimestamp(karachi('2026-08-12', 13, 59))).toBe('morning');
    expect(getShiftForTimestamp(karachi('2026-08-12', 14, 0))).toBe('evening');
    expect(getShiftForTimestamp(karachi('2026-08-12', 21, 59))).toBe('evening');
    expect(getShiftForTimestamp(karachi('2026-08-12', 22, 0))).toBe('night');
  });

  it('classifies 11:59pm and 12:01am as the same (Night) shift, across the calendar-day rollover', () => {
    expect(getShiftForTimestamp(karachi('2026-08-12', 23, 59))).toBe('night');
    expect(getShiftForTimestamp(karachi('2026-08-13', 0, 1))).toBe('night');
  });
});

describe('getCurrentShiftWindow', () => {
  it('resolves the identical absolute window from either half of a wrapping (Night) shift', () => {
    const lateHalf = getCurrentShiftWindow(karachi('2026-08-12', 23, 0));
    const postMidnightHalf = getCurrentShiftWindow(karachi('2026-08-13', 0, 30));

    expect(lateHalf.shift).toBe('night');
    expect(postMidnightHalf.shift).toBe('night');
    expect(lateHalf.startsAt.toISOString()).toBe(postMidnightHalf.startsAt.toISOString());
    expect(lateHalf.endsAt.toISOString()).toBe(postMidnightHalf.endsAt.toISOString());
  });

  it('computes the correct absolute start/end instants for the wrapping shift', () => {
    const window = getCurrentShiftWindow(karachi('2026-08-12', 23, 0));

    expect(window.startsAt.toISOString()).toBe(karachi('2026-08-12', 22, 0).toISOString());
    expect(window.endsAt.toISOString()).toBe(karachi('2026-08-13', 6, 0).toISOString());
  });

  it('does not change behavior for a shift that does not cross midnight (Morning)', () => {
    const window = getCurrentShiftWindow(karachi('2026-08-12', 10, 0));

    expect(window.shift).toBe('morning');
    expect(window.startsAt.toISOString()).toBe(karachi('2026-08-12', 6, 0).toISOString());
    expect(window.endsAt.toISOString()).toBe(karachi('2026-08-12', 14, 0).toISOString());
  });

  it('does not change behavior for a shift that does not cross midnight (Evening)', () => {
    const window = getCurrentShiftWindow(karachi('2026-08-12', 18, 0));

    expect(window.shift).toBe('evening');
    expect(window.startsAt.toISOString()).toBe(karachi('2026-08-12', 14, 0).toISOString());
    expect(window.endsAt.toISOString()).toBe(karachi('2026-08-12', 22, 0).toISOString());
  });
});

describe('isWithinCurrentShiftWindow — cross-midnight visibility', () => {
  const nowJustAfterMidnight = karachi('2026-08-13', 0, 30);

  it('keeps a visit created before midnight visible after the calendar day rolls over, within the same Night shift', () => {
    const createdBeforeMidnight = karachi('2026-08-12', 23, 50).toISOString();

    expect(isWithinCurrentShiftWindow(createdBeforeMidnight, nowJustAfterMidnight)).toBe(true);
  });

  it('excludes a visit created during the previous (Evening) shift', () => {
    const createdDuringEvening = karachi('2026-08-12', 18, 0).toISOString();

    expect(isWithinCurrentShiftWindow(createdDuringEvening, nowJustAfterMidnight)).toBe(false);
  });

  it('excludes a visit created after the current Night shift ends', () => {
    const createdAfterShiftEnds = karachi('2026-08-13', 7, 0).toISOString();

    expect(isWithinCurrentShiftWindow(createdAfterShiftEnds, nowJustAfterMidnight)).toBe(false);
  });

  it('is unaffected for a non-wrapping shift: only same-calendar-day visits within the window are visible', () => {
    const nowMidMorning = karachi('2026-08-12', 10, 0);
    const createdEarlierThisMorning = karachi('2026-08-12', 6, 30).toISOString();
    const createdYesterdayMorning = karachi('2026-08-11', 7, 0).toISOString();

    expect(isWithinCurrentShiftWindow(createdEarlierThisMorning, nowMidMorning)).toBe(true);
    expect(isWithinCurrentShiftWindow(createdYesterdayMorning, nowMidMorning)).toBe(false);
  });
});
