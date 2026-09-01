'use client';

import { useState } from 'react';
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
 * new one.
 *
 * Rendered inline on the Record Usage tab below RecordInventoryUsageForm
 * — the same "form, then a read-only record of what was submitted
 * right below it" stacking MyRegistrations.jsx/MyVitalsRecords.jsx
 * already establish elsewhere in this app.
 *
 * Each row is a compact summary line (Time/Item/Quantity/Patient) —
 * "Show Details" opens the shared DetailsDialog primitive (the same one
 * VitalsHistoryDialog.jsx already uses for its own "show everything for
 * this record" view) with the full breakdown: item + unit, quantity,
 * patient, reason, and both the effective ("Used On") and recorded-at
 * dates — all from this row's own already-fetched data, no second
 * request. */
export function MyInventoryUsage() {
  const { user } = useAuth();
  const [page, setPage] = useState(1);
  const [detailsEntry, setDetailsEntry] = useState(null);

  // Item name/unit resolution only — a small (<=100), already-cached
  // catalog fetch, the same client-side join InventoryHistoryPanel.jsx's
  // own itemName helper already does for this exact reason (the usage
  // entry itself only carries item_id).
  const { data: items } = useInventoryItems();
  const { entries, meta, isLoading, isError, error, refetch } = useMyInventoryUsage({
    userId: user?.id,
    page,
    pageSize: PAGE_SIZE,
  });

  const pageCount = Math.max(1, Math.ceil((meta?.total ?? 0) / PAGE_SIZE));
  const detailsItem = detailsEntry ? findItem(items, detailsEntry.item_id) : null;

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
          ) : entries.length === 0 ? (
            <p className="py-10 text-center text-sm text-muted-foreground">
              No usage recorded by you yet — new recordings will appear here immediately.
            </p>
          ) : (
            <>
              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead>Time</TableHead>
                    <TableHead>Item</TableHead>
                    <TableHead className="text-right">Quantity</TableHead>
                    <TableHead>Patient</TableHead>
                    <TableHead />
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {entries.map((entry) => {
                    const item = findItem(items, entry.item_id);
                    return (
                      <TableRow key={entry.id}>
                        <TableCell className="whitespace-nowrap">
                          {displayDayKey(entry.created_at)} {formatDisplayTime(entry.created_at)}
                        </TableCell>
                        <TableCell className="font-medium text-foreground">
                          {item ? item.name : 'Unknown item'}
                        </TableCell>
                        <TableCell className="whitespace-nowrap text-right tabular-nums">
                          {entry.quantity} {item?.unit ?? ''}
                        </TableCell>
                        <TableCell className="max-w-[200px] truncate">
                          {entry.patient_display_name ?? '—'}
                        </TableCell>
                        <TableCell>
                          <Button size="sm" variant="outline" onClick={() => setDetailsEntry(entry)}>
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
                    Page {page} of {pageCount} · {meta.total} entr{meta.total === 1 ? 'y' : 'ies'}
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
        open={Boolean(detailsEntry)}
        onClose={() => setDetailsEntry(null)}
        title={detailsItem ? detailsItem.name : 'Usage Details'}
        subtitle={
          detailsEntry
            ? `Recorded ${formatDisplayDate(displayDayKey(detailsEntry.created_at))} at ${formatDisplayTime(detailsEntry.created_at)}`
            : undefined
        }
      >
        {detailsEntry ? (
          <div className="flex flex-col gap-3 text-sm">
            <DetailRow
              label="Item"
              value={`${detailsItem ? detailsItem.name : 'Unknown item'}${detailsItem ? ` (${detailsItem.unit})` : ''}`}
            />
            <DetailRow
              label="Quantity"
              value={`${detailsEntry.quantity}${detailsItem ? ` ${detailsItem.unit}` : ''}`}
            />
            <DetailRow label="Patient" value={detailsEntry.patient_display_name ?? '—'} />
            <DetailRow label="Reason" value={detailsEntry.reason_note ?? '—'} />
            <DetailRow label="Used On" value={detailsEntry.used_on} />
          </div>
        ) : null}
      </DetailsDialog>
    </>
  );
}
