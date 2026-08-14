import { describe, expect, it } from 'vitest';
import { SHIFT_ORDER, getShiftForTimestamp } from './timezone';

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
