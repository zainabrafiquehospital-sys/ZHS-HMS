import { describe, expect, it } from 'vitest';
import { computeShiftRevenueBreakdown } from './shiftRevenue';

function karachi(dayKey, hour, minute = 0) {
  const [y, m, d] = dayKey.split('-').map(Number);
  return new Date(Date.UTC(y, m - 1, d, hour - 5, minute, 0)).toISOString();
}

describe('computeShiftRevenueBreakdown', () => {
  it('buckets each record into exactly one shift, by its own created_at hour', () => {
    const records = [
      { created_at: karachi('2026-08-12', 8, 0), amount: '100.00' },
      { created_at: karachi('2026-08-12', 16, 0), amount: '250.50' },
      { created_at: karachi('2026-08-12', 23, 0), amount: '75.25' },
    ];

    expect(computeShiftRevenueBreakdown(records, 'amount')).toEqual([
      { shift: 'morning', amount: 100 },
      { shift: 'evening', amount: 250.5 },
      { shift: 'night', amount: 75.25 },
    ]);
  });

  it('sums multiple records within the same shift', () => {
    const records = [
      { created_at: karachi('2026-08-12', 7, 0), amount: '50' },
      { created_at: karachi('2026-08-12', 9, 0), amount: '25' },
    ];

    const breakdown = computeShiftRevenueBreakdown(records, 'amount');

    expect(breakdown.find((entry) => entry.shift === 'morning').amount).toBe(75);
  });

  it('reconciles exactly to the full-day total, for a realistic mixed day', () => {
    const records = [
      { created_at: karachi('2026-08-12', 6, 30), amount: '100' },
      { created_at: karachi('2026-08-12', 13, 0), amount: '200' },
      { created_at: karachi('2026-08-12', 15, 0), amount: '50' },
      { created_at: karachi('2026-08-12', 21, 0), amount: '30' },
      { created_at: karachi('2026-08-12', 22, 30), amount: '75' },
      { created_at: karachi('2026-08-12', 2, 0), amount: '10' },
    ];
    const expectedTotal = records.reduce((sum, record) => sum + Number(record.amount), 0);

    const breakdown = computeShiftRevenueBreakdown(records, 'amount');
    const breakdownTotal = breakdown.reduce((sum, entry) => sum + entry.amount, 0);

    expect(breakdownTotal).toBeCloseTo(expectedTotal, 10);
  });

  it("supports a different amount key (e.g. medicine bills' total_amount)", () => {
    const records = [{ created_at: karachi('2026-08-12', 8, 0), total_amount: '41.00' }];

    expect(computeShiftRevenueBreakdown(records, 'total_amount')).toEqual([
      { shift: 'morning', amount: 41 },
      { shift: 'evening', amount: 0 },
      { shift: 'night', amount: 0 },
    ]);
  });

  it('returns a zero entry for every shift, even with no records', () => {
    expect(computeShiftRevenueBreakdown([], 'amount')).toEqual([
      { shift: 'morning', amount: 0 },
      { shift: 'evening', amount: 0 },
      { shift: 'night', amount: 0 },
    ]);
  });

  it('treats a null/undefined record list as empty', () => {
    expect(computeShiftRevenueBreakdown(null, 'amount')).toEqual([
      { shift: 'morning', amount: 0 },
      { shift: 'evening', amount: 0 },
      { shift: 'night', amount: 0 },
    ]);
    expect(computeShiftRevenueBreakdown(undefined, 'amount')).toEqual([
      { shift: 'morning', amount: 0 },
      { shift: 'evening', amount: 0 },
      { shift: 'night', amount: 0 },
    ]);
  });
});
