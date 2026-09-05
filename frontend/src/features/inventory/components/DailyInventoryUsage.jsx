'use client';

import { useMemo, useState } from 'react';
import { Eye, Printer, Search } from 'lucide-react';
import {
  useInventoryItems,
  useInventoryUsageEntries,
  usePrintDailyInventoryUsage,
} from '@/features/inventory/hooks/useInventory';
import { groupUsageEntries } from '@/features/inventory/utils/groupUsageEntries';
import { InventoryUsageGroupDetailsDialog } from '@/features/inventory/components/InventoryUsageGroupDetailsDialog';
import { DateNavigator } from '@/features/admin/components/DateNavigator';
import { Card, CardContent, CardHeader, CardTitle } from '@/shared/components/ui/Card';
import { Button } from '@/shared/components/ui/Button';
import { Badge } from '@/shared/components/ui/Badge';
import { Input } from '@/shared/components/ui/Input';
import { PageLoader } from '@/shared/components/PageLoader';
import { PageError } from '@/shared/components/PageError';
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from '@/shared/components/ui/Table';
import { useDebouncedValue } from '@/shared/hooks/useDebouncedValue';
import { formatDisplayTime, todayDisplayDayKey } from '@/utils/timezone';

// `GET /inventory/usage`'s own hard server-side cap (`page_size: int =
// Query(default=20, ge=1, le=100)` in backend/app/modules/inventory/
// router.py) — this screen requests the max the *on-screen* endpoint
// allows in one fetch, both to group the day's result set into
// submissions and to search it client-side, without pagination UI of
// its own (a day rarely nears 100 individual usage entries in practice;
// if one ever does, the Print pipeline below is still unaffected — it
// calls the service layer directly via a bespoke endpoint that bypasses
// this query-param cap entirely, using the internal
// `_ALL_ROWS_PAGE_SIZE = 1000` bound instead, so the printed report is
// always genuinely complete for the day even on a fetch this large).
const DAILY_USAGE_PAGE_SIZE = 100;

function findItem(items, itemId) {
  return (items ?? []).find((item) => item.id === itemId);
}

function itemNamesForGroup(group, items) {
  return group.lines.map((line) => findItem(items, line.item_id)?.name ?? 'Unknown item');
}

// `InventoryUsageEntry.quantity` is a Decimal(12,2) column — the backend
// always serializes it as a fixed two-decimal string (e.g. "0.50"), never
// a bare JSON number. Summing those via plain float addition risks the
// same binary-floating-point drift Decimal exists to avoid (0.1 + 0.2 is
// not exactly 0.3 in a double) — so this parses each quantity into
// integer hundredths first and sums *those* as integers (always exact,
// and nowhere near JS's safe-integer ceiling for a single day's volume),
// converting back to a fixed two-decimal string only at the end. Mirrors
// backend/app/modules/inventory/router.py's own Decimal-exact sum in
// `print_daily_usage` — the on-screen total and the printed total must
// always agree.
function toHundredths(quantityString) {
  return Math.round(Number(quantityString) * 100);
}

function fromHundredths(hundredths) {
  return (hundredths / 100).toFixed(2);
}

/** Per-item total across every patient/submission for the day —
 * "Avil Injection given 0.5 to one patient and 0.5 to another" collapses
 * to one "Avil Injection: 1.00" line, not two 0.50 lines. Deliberately
 * aggregated from the *full* day's `entries` (not `visibleGroups`, the
 * search-filtered set below) — the same "independent of whatever the
 * viewer currently has filtered on screen" rule the print endpoint's own
 * aggregation follows (see print_daily_usage's docstring), so this
 * on-screen total always matches the printed one. Sorted by total
 * quantity descending, item name ascending as a tie-break — a
 * reconciliation reader wants "what got used the most today" surfaced
 * first, not an alphabetical scan (same ordering the print's own summary
 * section uses). */
function summarizeByItem(entries, items) {
  const hundredthsByItemId = new Map();
  for (const entry of entries) {
    const current = hundredthsByItemId.get(entry.item_id) ?? 0;
    hundredthsByItemId.set(entry.item_id, current + toHundredths(entry.quantity));
  }
  return Array.from(hundredthsByItemId.entries())
    .map(([itemId, hundredths]) => {
      const item = findItem(items, itemId);
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

/** Patient name cell for one grouped row — same "Walk-in" badge
 * PatientHistorySearch.jsx's own `PatientCells` established for a
 * MedicineBill/LabBill row with no linked `Patient`: `patientId` unset
 * means there is genuinely no `Patient` row (either a manually-typed
 * walk-in name or a fully anonymous entry), not a broken join. */
function PatientCell({ group }) {
  if (group.patientId) {
    return <span className="truncate">{group.patientDisplayName}</span>;
  }
  return (
    <div className="flex items-center gap-1.5">
      <span className="truncate text-muted-foreground">
        {group.manualPatientName || 'Anonymous'}
      </span>
      <Badge variant="outline" className="shrink-0 text-[10px]">
        Walk-in
      </Badge>
    </div>
  );
}

/** Live, hospital-wide "who used what, on whom, and who recorded it"
 * view (2026-09-04 addition) — the confirmed design's replacement for
 * the old, undiagnosed-broken "Daily Usage Slip" (see git history:
 * removed with no recorded root cause, its backend routes deliberately
 * left in place "in case revisited later" — this screen does not reuse
 * that mechanism at all, only the currently-live-and-working
 * `render_inventory_history_log` print pipeline InventoryHistoryPanel's
 * own "Print" button already uses today).
 *
 * Visible to exactly the three roles holding `inventory:read` (Inventory
 * Manager, Admin, Vitals — confirmed against the actual grant
 * migrations, not assumed): a live, comprehensive log of every
 * Ward/Emergency Inventory item used against every patient hospital-
 * wide, not just the viewing actor's own recordings (that narrower view
 * stays MyInventoryUsage.jsx's job).
 *
 * Grouped one row per "Record Usage" submission — identical grouping key
 * MyInventoryUsage.jsx's own list already established, see
 * `groupUsageEntries`'s own docstring. Live-polls only when `date` is
 * today (`useInventoryUsageEntries`'s own `isToday` flag) — a past day's
 * history is immutable, so there is nothing to poll for. Search is a
 * debounced client-side filter over the day's already-fetched result set
 * (by patient name/MR or by any item name in a submission), matching
 * Inventory Catalog/Overview's own established debounced-search
 * pattern — this screen's per-day dataset is naturally small enough that
 * a new backend search param isn't warranted. "Show Details" reuses the
 * exact same shared dialog MyInventoryUsage.jsx uses. Print is always
 * the *full* selected day, independent of whatever the on-screen search
 * currently filters to (see usePrintDailyInventoryUsage's own
 * docstring).
 *
 * A "Total Usage Summary" card (2026-09-05 addition) sits above the
 * per-submission table: one line per distinct item, its quantity summed
 * across every patient/submission that day (see `summarizeByItem`'s own
 * docstring) — the same aggregation `print_daily_usage`'s printed report
 * now also shows, in the same order, so the on-screen total always
 * matches the printed one. Derived from the exact same already-fetched
 * `entries` the per-submission table below uses — no second fetch — so
 * it automatically inherits the identical date-scoping and
 * today-only-live-polling behavior for free. */
export function DailyInventoryUsage() {
  const [date, setDate] = useState(todayDisplayDayKey());
  const [searchTerm, setSearchTerm] = useState('');
  const [detailsGroup, setDetailsGroup] = useState(null);
  const debouncedSearch = useDebouncedValue(searchTerm, 200);
  const isToday = date === todayDisplayDayKey();

  const { data: items } = useInventoryItems();
  const {
    data: entries,
    isLoading,
    isError,
    error,
    refetch,
  } = useInventoryUsageEntries({
    startDate: date,
    endDate: date,
    pageSize: DAILY_USAGE_PAGE_SIZE,
    isToday,
  });
  const printDailyUsage = usePrintDailyInventoryUsage();
  const [printError, setPrintError] = useState(null);

  const groups = useMemo(() => groupUsageEntries(entries ?? []), [entries]);
  const itemTotals = useMemo(() => summarizeByItem(entries ?? [], items), [entries, items]);

  const visibleGroups = useMemo(() => {
    const term = debouncedSearch.trim().toLowerCase();
    if (!term) return groups;
    return groups.filter((group) => {
      const patientText = (
        group.patientId
          ? group.patientDisplayName
          : (group.manualPatientName ?? 'Anonymous')
      ).toLowerCase();
      if (patientText.includes(term)) return true;
      return itemNamesForGroup(group, items)
        .join(' ')
        .toLowerCase()
        .includes(term);
    });
  }, [groups, items, debouncedSearch]);

  async function handlePrint() {
    setPrintError(null);
    try {
      await printDailyUsage.mutateAsync({ date });
    } catch (err) {
      setPrintError(err.message || 'Unable to print this day’s Daily Usage report.');
    }
  }

  return (
    <div className="flex flex-col gap-4">
      <Card>
        <CardHeader>
          <CardTitle>Total Usage Summary</CardTitle>
        </CardHeader>
        <CardContent>
          {isLoading ? (
            <PageLoader label="Loading Total Usage Summary" />
          ) : isError ? (
            <PageError error={error} reset={refetch} message="Couldn't load Total Usage Summary." />
          ) : itemTotals.length === 0 ? (
            <p className="py-6 text-center text-sm text-muted-foreground">
              No inventory usage recorded for this day yet.
            </p>
          ) : (
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>Item</TableHead>
                  <TableHead>Unit</TableHead>
                  <TableHead className="text-right">Total Quantity Used</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {itemTotals.map((row) => (
                  <TableRow key={row.itemId}>
                    <TableCell className="font-medium text-foreground">{row.name}</TableCell>
                    <TableCell className="text-muted-foreground">{row.unit}</TableCell>
                    <TableCell className="text-right tabular-nums">{row.total}</TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          )}
        </CardContent>
      </Card>

      <Card>
        <CardHeader className="flex flex-col gap-4">
          <div className="flex flex-wrap items-center justify-between gap-3">
            <CardTitle>Daily Usage</CardTitle>
            <Button size="sm" variant="outline" onClick={handlePrint} disabled={printDailyUsage.isPending}>
              <Printer className="h-4 w-4" />
              {printDailyUsage.isPending ? 'Preparing…' : 'Print'}
            </Button>
          </div>
          <div className="flex flex-wrap items-center gap-3">
            <DateNavigator selectedDate={date} onChange={setDate} />
            <div className="relative w-full max-w-xs">
              <Search className="pointer-events-none absolute left-2.5 top-2.5 h-4 w-4 text-muted-foreground" />
              <Input
                className="pl-8"
                placeholder="Search patient name/MR or item"
                value={searchTerm}
                onChange={(event) => setSearchTerm(event.target.value)}
              />
            </div>
          </div>
        </CardHeader>
        <CardContent className="flex flex-col gap-4">
          {isLoading ? (
            <PageLoader label="Loading Daily Usage" />
          ) : isError ? (
            <PageError error={error} reset={refetch} message="Couldn't load Daily Usage." />
          ) : visibleGroups.length === 0 ? (
            <p className="py-10 text-center text-sm text-muted-foreground">
              {groups.length === 0
                ? 'No inventory usage recorded for this day yet.'
                : 'No usage entries match your search.'}
            </p>
          ) : (
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>Patient</TableHead>
                  <TableHead>Time</TableHead>
                  <TableHead>Items</TableHead>
                  <TableHead>Recorded By</TableHead>
                  <TableHead />
                </TableRow>
              </TableHeader>
              <TableBody>
                {visibleGroups.map((group) => {
                  const names = itemNamesForGroup(group, items);
                  const summary =
                    names.length === 1 ? names[0] : `${names[0]} + ${names.length - 1} more`;
                  return (
                    <TableRow key={group.key}>
                      <TableCell className="max-w-[220px]">
                        <PatientCell group={group} />
                      </TableCell>
                      <TableCell className="whitespace-nowrap">
                        {formatDisplayTime(group.createdAt)}
                      </TableCell>
                      <TableCell className="max-w-[280px] truncate font-medium text-foreground">
                        {summary}
                      </TableCell>
                      <TableCell className="max-w-[180px] truncate">
                        {group.createdByDisplayName ?? '—'}
                      </TableCell>
                      <TableCell>
                        <Button size="sm" variant="outline" onClick={() => setDetailsGroup(group)}>
                          <Eye className="h-3.5 w-3.5" />
                          Show Details
                        </Button>
                      </TableCell>
                    </TableRow>
                  );
                })}
              </TableBody>
            </Table>
          )}
          {printError ? <p className="text-sm text-destructive">{printError}</p> : null}
        </CardContent>
      </Card>

      <InventoryUsageGroupDetailsDialog
        open={Boolean(detailsGroup)}
        group={detailsGroup}
        items={items}
        onClose={() => setDetailsGroup(null)}
      />
    </div>
  );
}
