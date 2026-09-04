'use client';

import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from '@/shared/components/ui/Table';
import { DetailsDialog } from '@/shared/components/ui/DetailsDialog';
import { formatDisplayDate, formatDisplayTime, displayDayKey } from '@/utils/timezone';

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

/** Shared "Show Details" breakdown for one grouped Inventory Usage
 * submission (see groupUsageEntries's own docstring for how raw entries
 * are grouped back into one row per "Record Usage" submission) — every
 * item + unit + quantity + reason in that one submission, plus patient
 * and used-on date.
 *
 * Originally MyInventoryUsage.jsx's own inline dialog content; extracted
 * verbatim (2026-09-04) so the new hospital-wide Daily Usage view
 * (DailyInventoryUsage.jsx) shows the identical detail shape rather than
 * a second hand-rolled dialog — the two screens differ only in *which*
 * submissions they list (mine vs. everyone's for one day), never in what
 * "Show Details" reveals once a row is picked. */
export function InventoryUsageGroupDetailsDialog({ open, group, items, onClose }) {
  return (
    <DetailsDialog
      open={open}
      onClose={onClose}
      title={group?.patientDisplayName ?? 'Usage Details'}
      subtitle={
        group
          ? `Recorded ${formatDisplayDate(displayDayKey(group.createdAt))} at ${formatDisplayTime(group.createdAt)}`
          : undefined
      }
    >
      {group ? (
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
              {group.lines.map((line) => {
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
            <DetailRow label="Patient" value={group.patientDisplayName ?? '—'} />
            <DetailRow label="Used On" value={group.usedOn} />
          </div>
        </div>
      ) : null}
    </DetailsDialog>
  );
}
