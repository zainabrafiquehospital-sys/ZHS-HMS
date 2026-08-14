import { describe, expect, it } from 'vitest';
import {
  computeRevenueByActor,
  computeRevenueByActorWithSecondary,
  MAX_NAMED_SLICES,
  OTHER_ACTOR_ID,
  resolveActorSlices,
  resolveActorSlicesWithSecondary,
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

describe('computeRevenueByActorWithSecondary', () => {
  it("attaches each actor's secondary total alongside their primary one", () => {
    const primary = [record('user-1', '100.00'), record('user-2', '50.00')];
    const secondary = [record('user-1', '30.00'), record('user-2', '10.00')];

    const breakdown = computeRevenueByActorWithSecondary({
      primaryRecords: primary,
      primaryAmountKey: 'amount',
      secondaryRecords: secondary,
      secondaryAmountKey: 'amount',
    });

    expect(breakdown.find((e) => e.actorId === 'user-1')).toEqual({
      actorId: 'user-1',
      amount: 100,
      secondaryAmount: 30,
    });
    expect(breakdown.find((e) => e.actorId === 'user-2')).toEqual({
      actorId: 'user-2',
      amount: 50,
      secondaryAmount: 10,
    });
  });

  it('ranks/caps/folds purely by the primary metric, never the secondary one', () => {
    const primary = [
      record('a', '100'),
      record('b', '80'),
      record('c', '60'),
      record('d', '40'),
    ];
    // 'd' has far more secondary revenue than everyone, but that must
    // never promote it out of the "Other" fold — primary alone ranks.
    const secondary = [record('d', '999')];

    const breakdown = computeRevenueByActorWithSecondary({
      primaryRecords: primary,
      primaryAmountKey: 'amount',
      secondaryRecords: secondary,
      secondaryAmountKey: 'amount',
    });

    expect(breakdown.map((e) => e.actorId)).toEqual(['a', 'b', 'c', OTHER_ACTOR_ID]);
    expect(breakdown.find((e) => e.actorId === OTHER_ACTOR_ID).secondaryAmount).toBe(999);
  });

  it("never drops an actor's secondary revenue even with zero primary records at all — the cross-midnight case", () => {
    // A Night-shift receptionist whose only contribution so far is the
    // pre-midnight portion of the shift: zero of today's own (primary)
    // records, but real shift (secondary) revenue.
    const primary = [record('user-a', '200')];
    const secondary = [record('user-a', '50'), record('night-owl', '75')];

    const breakdown = computeRevenueByActorWithSecondary({
      primaryRecords: primary,
      primaryAmountKey: 'amount',
      secondaryRecords: secondary,
      secondaryAmountKey: 'amount',
    });

    const nightOwl = breakdown.find((e) => e.actorId === 'night-owl');
    expect(nightOwl).toBeDefined();
    expect(nightOwl.amount).toBe(0);
    expect(nightOwl.secondaryAmount).toBe(75);
  });

  it('reconciles the secondary total exactly across the returned breakdown, even when folded into Other', () => {
    const primary = [
      record('a', '100'),
      record('b', '80'),
      record('c', '60'),
      record('d', '40'),
      record('e', '20'),
    ];
    const secondary = [
      record('a', '5'),
      record('b', '10'),
      record('c', '15'),
      record('d', '20'),
      record('e', '25'),
      record('ghost', '999'), // no primary records at all
    ];
    const expectedSecondaryTotal = secondary.reduce((sum, r) => sum + Number(r.amount), 0);

    const breakdown = computeRevenueByActorWithSecondary({
      primaryRecords: primary,
      primaryAmountKey: 'amount',
      secondaryRecords: secondary,
      secondaryAmountKey: 'amount',
    });
    const actualSecondaryTotal = breakdown.reduce((sum, e) => sum + e.secondaryAmount, 0);

    expect(actualSecondaryTotal).toBe(expectedSecondaryTotal);
  });

  it('returns one bucket per actor with no Other fold for 3 or fewer contributors', () => {
    const primary = [record('a', '10'), record('b', '20')];
    const secondary = [record('a', '1'), record('b', '2')];

    const breakdown = computeRevenueByActorWithSecondary({
      primaryRecords: primary,
      primaryAmountKey: 'amount',
      secondaryRecords: secondary,
      secondaryAmountKey: 'amount',
    });

    expect(breakdown).toHaveLength(2);
    expect(breakdown.some((e) => e.actorId === OTHER_ACTOR_ID)).toBe(false);
  });

  it('groups the null-actor (deleted user) bucket on the same footing as any other actor', () => {
    const primary = [record(null, '15'), record('user-1', '10')];
    const secondary = [record(null, '5')];

    const breakdown = computeRevenueByActorWithSecondary({
      primaryRecords: primary,
      primaryAmountKey: 'amount',
      secondaryRecords: secondary,
      secondaryAmountKey: 'amount',
    });

    const nullEntry = breakdown.find((e) => e.actorId === null);
    expect(nullEntry.amount).toBe(15);
    expect(nullEntry.secondaryAmount).toBe(5);
  });

  it('treats null/undefined record lists as empty on both sides', () => {
    expect(
      computeRevenueByActorWithSecondary({
        primaryRecords: null,
        primaryAmountKey: 'amount',
        secondaryRecords: undefined,
        secondaryAmountKey: 'amount',
      }),
    ).toEqual([]);
  });
});

describe('resolveActorSlicesWithSecondary', () => {
  it('resolves a named actor, carrying secondaryAmount through unchanged', () => {
    const breakdown = [{ actorId: 'user-1', amount: 100, secondaryAmount: 30 }];
    const usersById = { 'user-1': { full_name: 'Ayesha Khan', email: 'ayesha@example.com' } };

    expect(resolveActorSlicesWithSecondary(breakdown, usersById)).toEqual([
      { actorId: 'user-1', label: 'Ayesha Khan', amount: 100, secondaryAmount: 30, isOther: false },
    ]);
  });

  it('labels the Other bucket and carries its secondaryAmount through', () => {
    const breakdown = [{ actorId: OTHER_ACTOR_ID, amount: 60, secondaryAmount: 15 }];

    const [slice] = resolveActorSlicesWithSecondary(breakdown, {});

    expect(slice).toEqual({
      actorId: OTHER_ACTOR_ID,
      label: 'Other',
      amount: 60,
      secondaryAmount: 15,
      isOther: true,
    });
  });

  it('labels the null-actor bucket "Unknown" and carries its secondaryAmount through', () => {
    const breakdown = [{ actorId: null, amount: 40, secondaryAmount: 5 }];

    const [slice] = resolveActorSlicesWithSecondary(breakdown, {});

    expect(slice).toEqual({
      actorId: 'unknown',
      label: 'Unknown',
      amount: 40,
      secondaryAmount: 5,
      isOther: false,
    });
  });

  it('treats a null/undefined breakdown as empty', () => {
    expect(resolveActorSlicesWithSecondary(null, {})).toEqual([]);
    expect(resolveActorSlicesWithSecondary(undefined, {})).toEqual([]);
  });
});
