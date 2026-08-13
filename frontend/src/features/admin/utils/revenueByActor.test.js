import { describe, expect, it } from 'vitest';
import {
  computeRevenueByActor,
  MAX_NAMED_SLICES,
  OTHER_ACTOR_ID,
  resolveActorSlices,
} from './revenueByActor';

function record(createdBy, amount) {
  return { created_at: '2026-08-12T10:00:00.000Z', created_by: createdBy, amount };
}

describe('computeRevenueByActor', () => {
  it("sums each receptionist's own revenue separately", () => {
    const records = [
      record('user-1', '100.00'),
      record('user-2', '250.50'),
      record('user-1', '50.00'),
    ];

    const breakdown = computeRevenueByActor(records, 'amount');

    expect(breakdown.find((e) => e.actorId === 'user-1').amount).toBe(150);
    expect(breakdown.find((e) => e.actorId === 'user-2').amount).toBe(250.5);
  });

  it('reconciles exactly to the full-day total, for a realistic mixed day', () => {
    const records = [
      record('user-1', '100'),
      record('user-2', '200'),
      record('user-1', '50'),
      record('user-3', '30'),
      record('user-2', '75'),
      record(null, '10'),
    ];
    const expectedTotal = records.reduce((sum, r) => sum + Number(r.amount), 0);

    const breakdown = computeRevenueByActor(records, 'amount');
    const breakdownTotal = breakdown.reduce((sum, entry) => sum + entry.amount, 0);

    expect(breakdownTotal).toBeCloseTo(expectedTotal, 10);
  });

  it('supports a different amount key (e.g. medicine bills\' total_amount)', () => {
    const records = [{ created_at: '2026-08-12T10:00:00.000Z', created_by: 'user-1', total_amount: '41.00' }];

    expect(computeRevenueByActor(records, 'total_amount')).toEqual([{ actorId: 'user-1', amount: 41 }]);
  });

  it('returns one bucket per actor with no records omitted, for 3 or fewer contributors', () => {
    const records = [record('user-1', '10'), record('user-2', '20'), record('user-3', '5')];

    const breakdown = computeRevenueByActor(records, 'amount');

    expect(breakdown).toHaveLength(3);
    expect(breakdown.some((e) => e.actorId === OTHER_ACTOR_ID)).toBe(false);
  });

  it('sorts descending by revenue', () => {
    const records = [record('low', '5'), record('high', '50'), record('mid', '20')];

    const breakdown = computeRevenueByActor(records, 'amount');

    expect(breakdown.map((e) => e.actorId)).toEqual(['high', 'mid', 'low']);
  });

  it('folds every contributor beyond the top 3 into a single Other bucket', () => {
    const records = [
      record('a', '100'),
      record('b', '80'),
      record('c', '60'),
      record('d', '40'),
      record('e', '20'),
    ];

    const breakdown = computeRevenueByActor(records, 'amount');

    expect(breakdown).toHaveLength(MAX_NAMED_SLICES + 1);
    expect(breakdown.slice(0, 3).map((e) => e.actorId)).toEqual(['a', 'b', 'c']);
    const other = breakdown.find((e) => e.actorId === OTHER_ACTOR_ID);
    expect(other.amount).toBe(60); // d (40) + e (20)
    // Still reconciles to the full-day total even with folding.
    const total = breakdown.reduce((sum, entry) => sum + entry.amount, 0);
    expect(total).toBe(300);
  });

  it('groups records with no recorded creator (created_by null) into their own bucket', () => {
    const records = [record(null, '15'), record(null, '5'), record('user-1', '10')];

    const breakdown = computeRevenueByActor(records, 'amount');

    expect(breakdown.find((e) => e.actorId === null).amount).toBe(20);
  });

  it('returns an empty array for no records', () => {
    expect(computeRevenueByActor([], 'amount')).toEqual([]);
  });

  it('treats a null/undefined record list as empty', () => {
    expect(computeRevenueByActor(null, 'amount')).toEqual([]);
    expect(computeRevenueByActor(undefined, 'amount')).toEqual([]);
  });
});

describe('resolveActorSlices', () => {
  it("labels a resolved user by full_name", () => {
    const breakdown = [{ actorId: 'user-1', amount: 100 }];
    const usersById = { 'user-1': { full_name: 'Ayesha Khan', email: 'ayesha@example.com' } };

    expect(resolveActorSlices(breakdown, usersById)).toEqual([
      { actorId: 'user-1', label: 'Ayesha Khan', amount: 100, isOther: false },
    ]);
  });

  it('falls back to email only when the resolved user has no display name', () => {
    const breakdown = [{ actorId: 'user-1', amount: 100 }];
    const usersById = { 'user-1': { full_name: '', email: 'ayesha@example.com' } };

    expect(resolveActorSlices(breakdown, usersById)[0].label).toBe('ayesha@example.com');
  });

  it('shows a loading placeholder while the user join has not resolved yet', () => {
    const breakdown = [{ actorId: 'user-1', amount: 100 }];

    expect(resolveActorSlices(breakdown, {})[0].label).toBe('…');
  });

  it('labels the null-actor bucket "Unknown" without a lookup', () => {
    const breakdown = [{ actorId: null, amount: 40 }];

    const [slice] = resolveActorSlices(breakdown, {});

    expect(slice).toEqual({ actorId: 'unknown', label: 'Unknown', amount: 40, isOther: false });
  });

  it('labels the Other bucket and marks isOther', () => {
    const breakdown = [{ actorId: OTHER_ACTOR_ID, amount: 60 }];

    const [slice] = resolveActorSlices(breakdown, {});

    expect(slice).toEqual({ actorId: OTHER_ACTOR_ID, label: 'Other', amount: 60, isOther: true });
  });

  it('treats a null/undefined breakdown as empty', () => {
    expect(resolveActorSlices(null, {})).toEqual([]);
    expect(resolveActorSlices(undefined, {})).toEqual([]);
  });
});
