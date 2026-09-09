/** Per-item total across every patient/submission in `entries` —
 * "Avil Injection given 0.5 to one patient and 0.5 to another" collapses
 * to one "Avil Injection: 1.00" line, sorted by total quantity
 * descending (item name ascending as the tie-break).
 *
 * Extracted verbatim from DailyInventoryUsage.jsx (2026-09) so the new
 * Live Inventory dashboard surfaces the same "what got used most today"
 * figure without reimplementing the Decimal-exact summation — see
 * `toHundredths`'s comment. `InventoryUsageEntry.quantity` is a
 * Decimal(12,2) the backend always serializes as a fixed two-decimal
 * string; summing those as plain floats risks binary-FP drift
 * (0.1 + 0.2 !== 0.3), so this parses each into integer hundredths,
 * sums those exactly, and converts back only at the end — mirroring
 * backend/app/modules/inventory/router.py's own Decimal-exact sum in
 * `print_daily_usage`, so the on-screen and printed totals always
 * agree.
 */

export function toHundredths(quantityString) {
  return Math.round(Number(quantityString) * 100);
}

export function fromHundredths(hundredths) {
  return (hundredths / 100).toFixed(2);
}

export function summarizeUsageByItem(entries, items) {
  const findItem = (itemId) => (items ?? []).find((item) => item.id === itemId);
  const hundredthsByItemId = new Map();
  for (const entry of entries ?? []) {
    const current = hundredthsByItemId.get(entry.item_id) ?? 0;
    hundredthsByItemId.set(entry.item_id, current + toHundredths(entry.quantity));
  }
  return Array.from(hundredthsByItemId.entries())
    .map(([itemId, hundredths]) => {
      const item = findItem(itemId);
      return {
        itemId,
        name: item?.name ?? 'Unknown item',
        unit: item?.unit ?? '',
        total: fromHundredths(hundredths),
        totalHundredths: hundredths,
      };
    })
    .sort((a, b) => b.totalHundredths - a.totalHundredths || a.name.localeCompare(b.name));
}
