'use client';

import { useMemo, useState } from 'react';
import { Eye } from 'lucide-react';
import { useAuth } from '@/features/auth/hooks/useAuth';
import { useInventoryItems, useMyInventoryUsage } from '@/features/inventory/hooks/useInventory';
import { groupUsageEntries } from '@/features/inventory/utils/groupUsageEntries';
import { InventoryUsageGroupDetailsDialog } from '@/features/inventory/components/InventoryUsageGroupDetailsDialog';
import { Card, CardContent, CardHeader, CardTitle } from '@/shared/components/ui/Card';
import { Button } from '@/shared/components/ui/Button';
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
import { formatDisplayTime, displayDayKey } from '@/utils/timezone';

const PAGE_SIZE = 10;

function findItem(items, itemId) {
  return (items ?? []).find((item) => item.id === itemId);
}

/** Every Emergency Stock usage entry this Vitals staff member has
 * personally recorded, newest first — the fix for the reported "usage
 * recorded against a patient isn't visible anywhere" gap. Investigation
 * confirmed the write itself was always correct (a real, correctly-
 * linked, correctly-decrementing InventoryUsageEntry row); the entry
 * simply had no UI anywhere surfacing it back to the person who
 * recorded it (`GET /inventory/usage/mine` existed but had zero
 * frontend callers) — see useMyInventoryUsage's own docstring for the
 * real server-side-paginated fix, reusing the general `GET /inventory/
 * usage` endpoint (already supports `created_by`) rather than adding a
 * new one. Rows are grouped back into one-per-submission via
 * `groupUsageEntries` (features/inventory/utils/groupUsageEntries.js) —
 * a real second round of feedback once the first version of this list
 * shipped one row per item instead.
 *
 * Rendered inline on the Record Usage tab below RecordInventoryUsageForm
 * — the same "form, then a read-only record of what was submitted
 * right below it" stacking MyRegistrations.jsx/MyVitalsRecords.jsx
 * already establish elsewhere in this app.
 *
 * Each row is a compact summary line (Time/Items/Patient) — "Show
 * Details" opens `InventoryUsageGroupDetailsDialog`, the shared
 * DetailsDialog content extracted (2026-09-04) so the hospital-wide
 * Daily Usage view (features/inventory/components/
 * DailyInventoryUsage.jsx) shows the identical per-item breakdown: every
 * item + unit + quantity + reason in that one submission, plus the
 * patient and effective date — all from this row's own already-fetched
 * data, no second request. */
export function MyInventoryUsage() {
  const { user } = useAuth();
  const [page, setPage] = useState(1);
  const [detailsGroup, setDetailsGroup] = useState(null);

  // Item name/unit resolution only — a small (<=100), already-cached
  // catalog fetch, the same client-side join InventoryHistoryPanel.jsx's
  // own itemName helper already does for this exact reason (a usage
  // entry itself only carries item_id).
  const { data: items } = useInventoryItems();
  const { entries, meta, isLoading, isError, error, refetch } = useMyInventoryUsage({
    userId: user?.id,
    page,
    pageSize: PAGE_SIZE,
  });
  const groups = useMemo(() => groupUsageEntries(entries), [entries]);

  const pageCount = Math.max(1, Math.ceil((meta?.total ?? 0) / PAGE_SIZE));

  return (
    <>
      <Card>
        <CardHeader>
          <CardTitle>My Inventory Usage</CardTitle>
        </CardHeader>
        <CardContent className="flex flex-col gap-4">
          {isLoading ? (
            <PageLoader label="Loading your inventory usage" />
          ) : isError ? (
            <PageError
              error={error}
              reset={refetch}
              message="Couldn't load your inventory usage."
            />
          ) : groups.length === 0 ? (
            <p className="py-10 text-center text-sm text-muted-foreground">
              No usage recorded by you yet — new recordings will appear here immediately.
            </p>
          ) : (
            <>
              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead>Time</TableHead>
                    <TableHead>Items</TableHead>
                    <TableHead>Patient</TableHead>
                    <TableHead />
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {groups.map((group) => {
                    const firstItem = findItem(items, group.lines[0].item_id);
                    const summary =
                      group.lines.length === 1
                        ? (firstItem ? firstItem.name : 'Unknown item')
                        : `${firstItem ? firstItem.name : 'Unknown item'} + ${group.lines.length - 1} more`;
                    return (
                      <TableRow key={group.key}>
                        <TableCell className="whitespace-nowrap">
                          {displayDayKey(group.createdAt)} {formatDisplayTime(group.createdAt)}
                        </TableCell>
                        <TableCell className="max-w-[280px] truncate font-medium text-foreground">
                          {summary}
                        </TableCell>
                        <TableCell className="max-w-[200px] truncate">
                          {group.patientDisplayName ?? '—'}
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

              {pageCount > 1 ? (
                <div className="flex items-center justify-between text-sm text-muted-foreground">
                  <span>
                    Page {page} of {pageCount} · {meta.total} usage entr
                    {meta.total === 1 ? 'y' : 'ies'} recorded
                  </span>
                  <div className="flex gap-2">
                    <Button
                      size="sm"
                      variant="outline"
                      disabled={page <= 1}
                      onClick={() => setPage((p) => Math.max(1, p - 1))}
                    >
                      Previous
                    </Button>
                    <Button
                      size="sm"
                      variant="outline"
                      disabled={page >= pageCount}
                      onClick={() => setPage((p) => Math.min(pageCount, p + 1))}
                    >
                      Next
                    </Button>
                  </div>
                </div>
              ) : null}
            </>
          )}
        </CardContent>
      </Card>

      <InventoryUsageGroupDetailsDialog
        open={Boolean(detailsGroup)}
        group={detailsGroup}
        items={items}
        onClose={() => setDetailsGroup(null)}
      />
    </>
  );
}
