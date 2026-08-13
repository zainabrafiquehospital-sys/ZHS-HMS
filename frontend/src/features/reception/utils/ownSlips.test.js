import { describe, expect, it } from 'vitest';
import { selectOwnSlipsToday } from './ownSlips';

const TODAY = '2026-08-12';
const YESTERDAY = '2026-08-11';

function visit({ id, createdBy, dayKey, hour = 10 }) {
  // DISPLAY_TIMEZONE (Asia/Karachi) is UTC+5 — see utils/timezone.js.
  const [y, m, d] = dayKey.split('-').map(Number);
  return {
    id,
    created_by: createdBy,
    created_at: new Date(Date.UTC(y, m - 1, d, hour - 5, 0, 0)).toISOString(),
  };
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
