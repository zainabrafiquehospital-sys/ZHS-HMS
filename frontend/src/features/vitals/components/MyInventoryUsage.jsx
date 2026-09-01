'use client';

import { useMemo, useState } from 'react';
import { Eye } from 'lucide-react';
import { useAuth } from '@/features/auth/hooks/useAuth';
import { useInventoryItems, useMyInventoryUsage } from '@/features/inventory/hooks/useInventory';
import { Card, CardContent, CardHeader, CardTitle } from '@/shared/components/ui/Card';
import { Button } from '@/shared/components/ui/Button';
import { DetailsDialog } from '@/shared/components/ui/DetailsDialog';
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
import { formatDisplayDate, formatDisplayTime, displayDayKey } from '@/utils/timezone';

const PAGE_SIZE = 10;

function findItem(items, itemId) {
  return (items ?? []).find((item) => item.id === itemId);
}

function DetailRow({ label, value }) {
  return (
    <div className="flex items-center justify-between gap-4 border-b border-border pb-2 last:border-0 last:pb-0">
      <span className="text-muted-foreground">{label}</span>
      <span className="max-w-[70%] text-right font-medium text-foreground">{value}</span>
    </div>
  );
}

/** Collapses `entries` (individual `InventoryUsageEntry` rows, each
 * item its own row by design — see backend/app/modules/inventory/
 * models.py's own "no batch/session parent entity" docstring) back
 * into one group per actual "Record Usage" submission — real-world
 * feedback: a receptionist recording 4 items against one patient in
 * one sitting saw 4 separate rows, all identical except the item, and
 * had no way to see them as the one action they actually were.
 *
 * There is no batch id to group by (deliberately, per that same
 * docstring), but every line inserted by one `record_usage` call
 * shares the exact same `created_at` — confirmed directly against a
 * real 3-item batch: Postgres's `now()` (the `server_default` this
 * column uses) is frozen for the lifetime of one transaction, and
 * `record_usage` writes its whole batch, then commits, in exactly one
 * transaction — so `created_at` down to the microsecond is a reliable
 * grouping key here, not a coincidence. Combined with
 * `patient_display_name` (already-resolved, so two different
 * anonymous/manual entries never merge unless they're also the exact
 * same submission) rather than raw `patient_id`, which is `null` for
 * both the fully-anonymous and manual-name cases and would otherwise
 * collide across genuinely different batches recorded in the same
 * process tick. Grouping happens within the current page only (the
 * same "current volume" scope every other client-side grouping in this
 * codebase already accepts) — a batch split across a page boundary is
 * a real but rare edge case at PAGE_SIZE=10 against typical batch
 * sizes, not worth a server-side redesign for. */
function groupEntries(entries) {
  const groups = new Map();
  for (const entry of entries) {
    const key = `${entry.created_at}::${entry.patient_display_name ?? ''}`;
    if (!groups.has(key)) {
      groups.set(key, {
        key,
        createdAt: entry.created_at,
        usedOn: entry.used_on,
        patientDisplayName: entry.patient_display_name,
        lines: [],
      });
    }
    groups.get(key).lines.push(entry);
  }
  return Array.from(groups.values());
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
 * `groupEntries` above — a real second round of feedback once the
 * first version of this list shipped one row per item instead.
 *
 * Rendered inline on the Record Usage tab below RecordInventoryUsageForm
 * — the same "form, then a read-only record of what was submitted
 * right below it" stacking MyRegistrations.jsx/MyVitalsRecords.jsx
 * already establish elsewhere in this app.
 *
 * Each row is a compact summary line (Time/Items/Patient) — "Show
 * Details" opens the shared DetailsDialog primitive (the same one
 * VitalsHistoryDialog.jsx already uses) with the full per-item
 * breakdown: every item + unit + quantity + reason in that one
 * submission, plus the patient and effective date — all from this
 * row's own already-fetched data, no second request. */
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
  const groups = useMemo(() => groupEntries(entries), [entries]);

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

      <DetailsDialog
        open={Boolean(detailsGroup)}
        onClose={() => setDetailsGroup(null)}
        title={detailsGroup?.patientDisplayName ?? 'Usage Details'}
        subtitle={
          detailsGroup
            ? `Recorded ${formatDisplayDate(displayDayKey(detailsGroup.createdAt))} at ${formatDisplayTime(detailsGroup.createdAt)}`
            : undefined
        }
      >
        {detailsGroup ? (
          <div className="flex flex-col gap-4">
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>Item</TableHead>
                  <TableHead className="text-right">Quantity</TableHead>
                  <TableHead>Reason</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {detailsGroup.lines.map((line) => {
                  const lineItem = findItem(items, line.item_id);
                  return (
                    <TableRow key={line.id}>
                      <TableCell className="font-medium text-foreground">
                        {lineItem ? lineItem.name : 'Unknown item'}
                      </TableCell>
                      <TableCell className="whitespace-nowrap text-right tabular-nums">
                        {line.quantity} {lineItem?.unit ?? ''}
                      </TableCell>
                      <TableCell className="max-w-[200px] truncate text-muted-foreground">
                        {line.reason_note ?? '—'}
                      </TableCell>
                    </TableRow>
                  );
                })}
              </TableBody>
            </Table>
            <div className="flex flex-col gap-3 text-sm">
              <DetailRow label="Patient" value={detailsGroup.patientDisplayName ?? '—'} />
              <DetailRow label="Used On" value={detailsGroup.usedOn} />
            </div>
          </div>
        ) : null}
      </DetailsDialog>
    </>
  );
}
