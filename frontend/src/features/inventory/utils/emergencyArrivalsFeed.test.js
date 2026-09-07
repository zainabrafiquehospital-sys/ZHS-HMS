import { describe, expect, it } from 'vitest';
import {
  ARRIVAL_SOURCE,
  ARRIVAL_SOURCE_LABEL,
  buildEmergencyArrivalsFeed,
} from './emergencyArrivalsFeed';

const directReceipt = (over = {}) => ({
  id: 'd1',
  item_id: 'item-a',
  quantity: '10.00',
  received_on: '2026-09-07',
  created_at: '2026-09-07T10:00:00+00:00',
  created_by_display_name: 'Manager One',
  ...over,
});

const transfer = (over = {}) => ({
  id: 't1',
  item_id: 'item-b',
  quantity: '5.00',
  transferred_on: '2026-09-07',
  created_at: '2026-09-07T09:00:00+00:00',
  carried_by_name: 'A Porter',
  created_by_display_name: 'Manager Two',
  ...over,
});

describe('buildEmergencyArrivalsFeed', () => {
  it('merges both ledgers into one list, tagging each entry with its source', () => {
    const feed = buildEmergencyArrivalsFeed([directReceipt()], [transfer()]);
    expect(feed).toHaveLength(2);
    expect(feed.map((e) => e.source).sort()).toEqual([ARRIVAL_SOURCE.DIRECT, ARRIVAL_SOURCE.TRANSFER]);
  });

  it('sorts strictly by created_at descending across both sources', () => {
    const feed = buildEmergencyArrivalsFeed(
      [
        directReceipt({ id: 'd-old', created_at: '2026-09-07T08:00:00+00:00' }),
        directReceipt({ id: 'd-new', created_at: '2026-09-07T12:00:00+00:00' }),
      ],
      [transfer({ id: 't-mid', created_at: '2026-09-07T10:00:00+00:00' })],
    );
    expect(feed.map((e) => e.id)).toEqual(['d-new', 't-mid', 'd-old']);
  });

  it('normalizes received_on / transferred_on to a single effective_on field', () => {
    const [d, t] = buildEmergencyArrivalsFeed(
      [directReceipt({ received_on: '2026-09-05' })],
      [transfer({ transferred_on: '2026-09-04' })],
    );
    expect(d.effective_on).toBe('2026-09-05');
    expect(t.effective_on).toBe('2026-09-04');
  });

  it('carries created_by_display_name through, and null when the API sent none', () => {
    const [withName, withoutName] = buildEmergencyArrivalsFeed(
      [
        directReceipt({ id: 'has', created_at: '2026-09-07T11:00:00+00:00' }),
        directReceipt({
          id: 'none',
          created_at: '2026-09-07T10:00:00+00:00',
          created_by_display_name: null,
        }),
      ],
      [],
    );
    expect(withName.created_by_display_name).toBe('Manager One');
    expect(withoutName.created_by_display_name).toBeNull();
  });

  it('keeps carried_by_name for transfers only (always null for direct receipts)', () => {
    const feed = buildEmergencyArrivalsFeed([directReceipt()], [transfer({ carried_by_name: 'Ali' })]);
    const d = feed.find((e) => e.source === ARRIVAL_SOURCE.DIRECT);
    const t = feed.find((e) => e.source === ARRIVAL_SOURCE.TRANSFER);
    expect(d.carried_by_name).toBeNull();
    expect(t.carried_by_name).toBe('Ali');
  });

  it('uses id as a stable descending tiebreaker when two rows share created_at (one batch)', () => {
    const feed = buildEmergencyArrivalsFeed(
      [
        directReceipt({ id: 'aaa', created_at: '2026-09-07T10:00:00+00:00' }),
        directReceipt({ id: 'ccc', created_at: '2026-09-07T10:00:00+00:00' }),
        directReceipt({ id: 'bbb', created_at: '2026-09-07T10:00:00+00:00' }),
      ],
      [],
    );
    expect(feed.map((e) => e.id)).toEqual(['ccc', 'bbb', 'aaa']);
  });

  it('caps the result at the given limit, keeping the most recent', () => {
    const many = Array.from({ length: 10 }, (_, i) =>
      directReceipt({ id: `d${i}`, created_at: `2026-09-07T${String(i).padStart(2, '0')}:00:00+00:00` }),
    );
    const feed = buildEmergencyArrivalsFeed(many, [], { limit: 3 });
    expect(feed.map((e) => e.id)).toEqual(['d9', 'd8', 'd7']);
  });

  it('is empty-safe (null / undefined / empty for either source)', () => {
    expect(buildEmergencyArrivalsFeed(null, undefined)).toEqual([]);
    expect(buildEmergencyArrivalsFeed([], [])).toEqual([]);
  });

  it('exposes human-readable source labels', () => {
    expect(ARRIVAL_SOURCE_LABEL[ARRIVAL_SOURCE.DIRECT]).toBe('Direct Receipt');
    expect(ARRIVAL_SOURCE_LABEL[ARRIVAL_SOURCE.TRANSFER]).toBe('Transfer from Main Stock');
  });
});
