import { describe, expect, it } from 'vitest';
import { selectOwnSlipsCurrentShift, selectOwnSlipsToday } from './ownSlips';

const TODAY = '2026-08-12';
const YESTERDAY = '2026-08-11';

function visit({ id, createdBy, dayKey, hour = 10, minute = 0 }) {
  // DISPLAY_TIMEZONE (Asia/Karachi) is UTC+5 — see utils/timezone.js.
  const [y, m, d] = dayKey.split('-').map(Number);
  return {
    id,
    created_by: createdBy,
    created_at: new Date(Date.UTC(y, m - 1, d, hour - 5, minute, 0)).toISOString(),
  };
}

// Same DISPLAY_TIMEZONE (UTC+5) fixed-offset helper `visit()` above
// uses, but returning a plain `Date` (not an ISO string) — matches
// `isWithinCurrentShiftWindow`'s own optional `now` override shape.
function karachi(dayKey, hour, minute = 0) {
  const [y, m, d] = dayKey.split('-').map(Number);
  return new Date(Date.UTC(y, m - 1, d, hour - 5, minute, 0));
}

describe('selectOwnSlipsToday', () => {
  it('returns only this user\'s visits created today', () => {
    const visits = [
      visit({ id: 'a', createdBy: 'user-1', dayKey: TODAY }),
      visit({ id: 'b', createdBy: 'user-2', dayKey: TODAY }),
      visit({ id: 'c', createdBy: 'user-1', dayKey: YESTERDAY }),
    ];

    const result = selectOwnSlipsToday(visits, 'user-1', TODAY);

    expect(result.map((v) => v.id)).toEqual(['a']);
  });

  it('excludes a visit by the same user on a different calendar day', () => {
    const visits = [visit({ id: 'a', createdBy: 'user-1', dayKey: YESTERDAY })];

    expect(selectOwnSlipsToday(visits, 'user-1', TODAY)).toEqual([]);
  });

  it("cross-receptionist isolation: user A never sees user B's slips, even same day", () => {
    const visits = [
      visit({ id: 'a1', createdBy: 'user-a', dayKey: TODAY }),
      visit({ id: 'a2', createdBy: 'user-a', dayKey: TODAY }),
      visit({ id: 'b1', createdBy: 'user-b', dayKey: TODAY }),
    ];

    const forA = selectOwnSlipsToday(visits, 'user-a', TODAY);
    const forB = selectOwnSlipsToday(visits, 'user-b', TODAY);

    expect(forA.map((v) => v.id).sort()).toEqual(['a1', 'a2']);
    expect(forB.map((v) => v.id)).toEqual(['b1']);
    // Neither result leaks a row created by the other user.
    expect(forA.some((v) => v.created_by === 'user-b')).toBe(false);
    expect(forB.some((v) => v.created_by === 'user-a')).toBe(false);
  });

  it('is deterministic given the same inputs — logout/login must never change the result', () => {
    // The property under test: this function reads nothing but its own
    // arguments (no session, no module-level state, no clock read
    // internally), so calling it twice — simulating "before logout"
    // and "after logging back in" — with the same visits/userId/today
    // must yield an identical result. Passing fresh array/object
    // references each time (not the same in-memory array) proves this
    // isn't relying on referential/cached state either.
    const buildVisits = () => [
      visit({ id: 'a', createdBy: 'user-1', dayKey: TODAY }),
      visit({ id: 'b', createdBy: 'user-2', dayKey: TODAY }),
    ];

    const beforeLogout = selectOwnSlipsToday(buildVisits(), 'user-1', TODAY);
    const afterLoginAgain = selectOwnSlipsToday(buildVisits(), 'user-1', TODAY);

    expect(afterLoginAgain).toEqual(beforeLogout);
    expect(afterLoginAgain.map((v) => v.id)).toEqual(['a']);
  });

  it('never matches when userId is undefined (session not yet resolved)', () => {
    const visits = [visit({ id: 'a', createdBy: 'user-1', dayKey: TODAY })];

    expect(selectOwnSlipsToday(visits, undefined, TODAY)).toEqual([]);
  });

  it('never matches a visit with no recorded creator (created_by null)', () => {
    const visits = [visit({ id: 'a', createdBy: null, dayKey: TODAY })];

    expect(selectOwnSlipsToday(visits, 'user-1', TODAY)).toEqual([]);
    expect(selectOwnSlipsToday(visits, null, TODAY)).toEqual([]);
  });

  it('treats a null/undefined visit list as empty', () => {
    expect(selectOwnSlipsToday(null, 'user-1', TODAY)).toEqual([]);
    expect(selectOwnSlipsToday(undefined, 'user-1', TODAY)).toEqual([]);
  });
});

describe('selectOwnSlipsCurrentShift', () => {
  const nowJustAfterMidnight = karachi('2026-08-13', 0, 30); // within the Night shift

  it("keeps a Night-shift receptionist's pre-midnight visit counted after the calendar day rolls over", () => {
    const createdBeforeMidnight = visit({
      id: 'a',
      createdBy: 'user-1',
      dayKey: '2026-08-12',
      hour: 23,
      minute: 50,
    });
    const createdJustAfterMidnight = visit({
      id: 'b',
      createdBy: 'user-1',
      dayKey: '2026-08-13',
      hour: 0,
      minute: 20,
    });

    const result = selectOwnSlipsCurrentShift(
      [createdBeforeMidnight, createdJustAfterMidnight],
      'user-1',
      nowJustAfterMidnight,
    );

    // Both calendar dates the Night shift touches are represented —
    // neither the earlier (yesterday) nor the later (today) portion is
    // dropped just because they fall on different displayDayKeys.
    expect(result.map((v) => v.id).sort()).toEqual(['a', 'b']);
  });

  it('excludes a visit created during the previous (Evening) shift, even by the same user', () => {
    const createdDuringEvening = visit({
      id: 'a',
      createdBy: 'user-1',
      dayKey: '2026-08-12',
      hour: 18,
    });

    expect(
      selectOwnSlipsCurrentShift([createdDuringEvening], 'user-1', nowJustAfterMidnight),
    ).toEqual([]);
  });

  it('excludes another user\'s visits, even within the same shift window', () => {
    const visits = [
      visit({ id: 'a', createdBy: 'user-a', dayKey: '2026-08-12', hour: 23 }),
      visit({ id: 'b', createdBy: 'user-b', dayKey: '2026-08-12', hour: 23 }),
    ];

    const forA = selectOwnSlipsCurrentShift(visits, 'user-a', nowJustAfterMidnight);

    expect(forA.map((v) => v.id)).toEqual(['a']);
    expect(forA.some((v) => v.created_by === 'user-b')).toBe(false);
  });

  it('is deterministic given the same inputs — logout/login must never change the result', () => {
    const buildVisits = () => [
      visit({ id: 'a', createdBy: 'user-1', dayKey: '2026-08-12', hour: 23 }),
      visit({ id: 'b', createdBy: 'user-2', dayKey: '2026-08-12', hour: 23 }),
    ];

    const beforeLogout = selectOwnSlipsCurrentShift(buildVisits(), 'user-1', nowJustAfterMidnight);
    const afterLoginAgain = selectOwnSlipsCurrentShift(
      buildVisits(),
      'user-1',
      nowJustAfterMidnight,
    );

    expect(afterLoginAgain).toEqual(beforeLogout);
    expect(afterLoginAgain.map((v) => v.id)).toEqual(['a']);
  });

  it('never matches when userId is undefined (session not yet resolved)', () => {
    const visits = [visit({ id: 'a', createdBy: 'user-1', dayKey: TODAY })];

    expect(selectOwnSlipsCurrentShift(visits, undefined, nowJustAfterMidnight)).toEqual([]);
  });

  it('never matches a visit with no recorded creator (created_by null)', () => {
    const visits = [visit({ id: 'a', createdBy: null, dayKey: TODAY, hour: 23 })];

    expect(selectOwnSlipsCurrentShift(visits, 'user-1', nowJustAfterMidnight)).toEqual([]);
    expect(selectOwnSlipsCurrentShift(visits, null, nowJustAfterMidnight)).toEqual([]);
  });

  it('treats a null/undefined visit list as empty', () => {
    expect(selectOwnSlipsCurrentShift(null, 'user-1', nowJustAfterMidnight)).toEqual([]);
    expect(selectOwnSlipsCurrentShift(undefined, 'user-1', nowJustAfterMidnight)).toEqual([]);
  });

  it('is unaffected for a non-wrapping shift: only visits within that window count', () => {
    const nowMidMorning = karachi('2026-08-12', 10, 0);
    const createdEarlierThisMorning = visit({
      id: 'a',
      createdBy: 'user-1',
      dayKey: '2026-08-12',
      hour: 6,
      minute: 30,
    });
    const createdYesterdayMorning = visit({
      id: 'b',
      createdBy: 'user-1',
      dayKey: '2026-08-11',
      hour: 7,
    });

    const result = selectOwnSlipsCurrentShift(
      [createdEarlierThisMorning, createdYesterdayMorning],
      'user-1',
      nowMidMorning,
    );

    expect(result.map((v) => v.id)).toEqual(['a']);
  });
});
