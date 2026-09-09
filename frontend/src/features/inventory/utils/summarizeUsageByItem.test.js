import { describe, expect, it } from 'vitest';
import { fromHundredths, summarizeUsageByItem, toHundredths } from './summarizeUsageByItem';

const items = [
  { id: 'a', name: 'Avil Injection', unit: 'ampoule' },
  { id: 'b', name: 'Normal Saline', unit: 'ml' },
];
const entry = (item_id, quantity) => ({ item_id, quantity });

describe('toHundredths / fromHundredths', () => {
  it('round-trips a two-decimal string exactly', () => {
    expect(toHundredths('0.50')).toBe(50);
    expect(fromHundredths(50)).toBe('0.50');
  });
});

describe('summarizeUsageByItem', () => {
  it('collapses multiple entries for one item into a single Decimal-exact total', () => {
    // 0.1 + 0.2 via plain float is 0.30000000000000004 — must be "0.30".
    const rows = summarizeUsageByItem([entry('b', '0.10'), entry('b', '0.20')], items);
    expect(rows).toHaveLength(1);
    expect(rows[0]).toMatchObject({ itemId: 'b', name: 'Normal Saline', unit: 'ml', total: '0.30' });
  });

  it('sorts by total quantity descending, then item name ascending', () => {
    const rows = summarizeUsageByItem(
      [entry('a', '1.00'), entry('b', '3.00'), entry('a', '1.00')],
      items,
    );
    expect(rows.map((r) => r.itemId)).toEqual(['b', 'a']); // b=3.00, a=2.00
  });

  it('falls back to "Unknown item" when the item is not in the catalog', () => {
    const [row] = summarizeUsageByItem([entry('gone', '1.00')], items);
    expect(row).toMatchObject({ name: 'Unknown item', unit: '', total: '1.00' });
  });

  it('is empty-safe', () => {
    expect(summarizeUsageByItem([], items)).toEqual([]);
    expect(summarizeUsageByItem(null, null)).toEqual([]);
  });
});
