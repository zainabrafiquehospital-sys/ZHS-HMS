import { describe, expect, it } from 'vitest';
import { mergeEmployeeStats, toLookup } from './employeeStats';

describe('toLookup', () => {
  it('keys each row by user_id, projecting only the requested fields', () => {
    const rows = [
      { user_id: 'u1', count: 3, revenue: '100.00' },
      { user_id: 'u2', count: 5, revenue: '250.00' },
    ];

    expect(toLookup(rows, ['count', 'revenue'])).toEqual({
      u1: { count: 3, revenue: '100.00' },
      u2: { count: 5, revenue: '250.00' },
    });
  });

  it('projects only the named fields, dropping anything else on the row', () => {
    const rows = [{ user_id: 'u1', count: 3, revenue: '100.00' }];

    expect(toLookup(rows, ['count'])).toEqual({ u1: { count: 3 } });
  });

  it('treats a null/undefined row list as empty', () => {
    expect(toLookup(null, ['count'])).toEqual({});
    expect(toLookup(undefined, ['count'])).toEqual({});
  });

  it('returns an empty lookup for an empty row list', () => {
    expect(toLookup([], ['count'])).toEqual({});
  });
});

describe('mergeEmployeeStats', () => {
  it("combines all four modules' counts for a user present in every one", () => {
    const merged = mergeEmployeeStats({
      userId: 'u1',
      visitsByUser: { u1: { count: 4 } },
      billsByUser: { u1: { count: 2, revenue: '150.00' } },
      consultationsByUser: { u1: { count: 1 } },
      vitalsByUser: { u1: { count: 6 } },
    });

    expect(merged).toEqual({ visits: 4, bills: 2, revenue: '150.00', consultations: 1, vitals: 6 });
  });

  it('defaults every category to 0 (revenue to "0.00") for a user with no rows anywhere', () => {
    const merged = mergeEmployeeStats({
      userId: 'ghost',
      visitsByUser: {},
      billsByUser: {},
      consultationsByUser: {},
      vitalsByUser: {},
    });

    expect(merged).toEqual({
      visits: 0,
      bills: 0,
      revenue: '0.00',
      consultations: 0,
      vitals: 0,
    });
  });

  it('never fabricates a stat for a category a user has no rows in — only real 0s', () => {
    // A receptionist: real visits/bills, genuinely no consultations/vitals.
    const merged = mergeEmployeeStats({
      userId: 'reception-1',
      visitsByUser: { 'reception-1': { count: 12 } },
      billsByUser: { 'reception-1': { count: 3, revenue: '400.00' } },
      consultationsByUser: {},
      vitalsByUser: {},
    });

    expect(merged.consultations).toBe(0);
    expect(merged.vitals).toBe(0);
    expect(merged.visits).toBe(12);
  });
});
