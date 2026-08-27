'use client';

import { useState } from 'react';
import { Printer } from 'lucide-react';
import {
  useInventoryItems,
  useInventoryReceipts,
  useInventoryTransfers,
  useInventoryUsageEntries,
  usePrintInventoryHistoryLog,
} from '@/features/inventory/hooks/useInventory';
import { Card, CardContent, CardHeader, CardTitle } from '@/shared/components/ui/Card';
import { Button } from '@/shared/components/ui/Button';
import { Input } from '@/shared/components/ui/Input';
import { Label } from '@/shared/components/ui/Label';
import { Select } from '@/shared/components/ui/Select';
import { Tabs } from '@/shared/components/ui/Tabs';
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
import { formatDisplayTime } from '@/utils/timezone';

const HISTORY_TABS = [
  { value: 'receipts', label: 'Receipts' },
  { value: 'transfers', label: 'Transfers' },
  { value: 'usage', label: 'Usage' },
];

// This panel's own tab values are plural (matching the tab labels);
// backend/app/modules/inventory/router.py's `log_type` query param is
// singular (`"receipt" | "transfer" | "usage"`) — this is the one place
// that translates between the two.
const HISTORY_TAB_TO_LOG_TYPE = {
  receipts: 'receipt',
  transfers: 'transfer',
  usage: 'usage',
};

function itemName(items, itemId) {
  return items.find((item) => item.id === itemId)?.name ?? 'Unknown item';
}

function ReceiptsTable({ items, itemId, startDate, endDate }) {
  const { data, isLoading, isError, error, refetch } = useInventoryReceipts({
    itemId: itemId || undefined,
    startDate: startDate || undefined,
    endDate: endDate || undefined,
  });

  if (isLoading) return <PageLoader label="Loading receipts" />;
  if (isError) {
    return <PageError error={error} reset={refetch} message="Couldn't load receipts." />;
  }
  const rows = data ?? [];
  if (rows.length === 0) return <p className="text-sm text-muted-foreground">No receipts found.</p>;

  return (
    <Table>
      <TableHeader>
        <TableRow>
          <TableHead>Item</TableHead>
          <TableHead className="text-right">Quantity</TableHead>
          <TableHead>Received On</TableHead>
          <TableHead>Entered</TableHead>
        </TableRow>
      </TableHeader>
      <TableBody>
        {rows.map((receipt) => (
          <TableRow key={receipt.id}>
            <TableCell className="font-medium text-foreground">
              {itemName(items, receipt.item_id)}
            </TableCell>
            <TableCell className="text-right tabular-nums">{receipt.quantity}</TableCell>
            <TableCell>{receipt.received_on}</TableCell>
            <TableCell className="text-muted-foreground">
              {formatDisplayTime(receipt.created_at)}
            </TableCell>
          </TableRow>
        ))}
      </TableBody>
    </Table>
  );
}

function TransfersTable({ items, itemId, startDate, endDate }) {
  const { data, isLoading, isError, error, refetch } = useInventoryTransfers({
    itemId: itemId || undefined,
    startDate: startDate || undefined,
    endDate: endDate || undefined,
  });

  if (isLoading) return <PageLoader label="Loading transfers" />;
  if (isError) {
    return <PageError error={error} reset={refetch} message="Couldn't load transfers." />;
  }
  const rows = data ?? [];
  if (rows.length === 0) return <p className="text-sm text-muted-foreground">No transfers found.</p>;

  return (
    <Table>
      <TableHeader>
        <TableRow>
          <TableHead>Item</TableHead>
          <TableHead className="text-right">Quantity</TableHead>
          <TableHead>Transferred On</TableHead>
          <TableHead>Carried By</TableHead>
          <TableHead>Entered</TableHead>
        </TableRow>
      </TableHeader>
      <TableBody>
        {rows.map((transfer) => (
          <TableRow key={transfer.id}>
            <TableCell className="font-medium text-foreground">
              {itemName(items, transfer.item_id)}
            </TableCell>
            <TableCell className="text-right tabular-nums">{transfer.quantity}</TableCell>
            <TableCell>{transfer.transferred_on}</TableCell>
            {/* `null` for every transfer recorded before this field
                existed — see InventoryTransfer.carried_by_name's own
                docstring. */}
            <TableCell>{transfer.carried_by_name ?? '—'}</TableCell>
            <TableCell className="text-muted-foreground">
              {formatDisplayTime(transfer.created_at)}
            </TableCell>
          </TableRow>
        ))}
      </TableBody>
    </Table>
  );
}

function UsageTable({ items, itemId, startDate, endDate }) {
  const { data, isLoading, isError, error, refetch } = useInventoryUsageEntries({
    itemId: itemId || undefined,
    startDate: startDate || undefined,
    endDate: endDate || undefined,
  });

  if (isLoading) return <PageLoader label="Loading usage entries" />;
  if (isError) {
    return <PageError error={error} reset={refetch} message="Couldn't load usage entries." />;
  }
  const rows = data ?? [];
  if (rows.length === 0) {
    return <p className="text-sm text-muted-foreground">No usage entries found.</p>;
  }

  return (
    <Table>
      <TableHeader>
        <TableRow>
          <TableHead>Item</TableHead>
          <TableHead className="text-right">Quantity</TableHead>
          <TableHead>Patient</TableHead>
          <TableHead>Reason</TableHead>
          <TableHead>Used On</TableHead>
        </TableRow>
      </TableHeader>
      <TableBody>
        {rows.map((entry) => (
          <TableRow key={entry.id}>
            <TableCell className="font-medium text-foreground">
              {itemName(items, entry.item_id)}
            </TableCell>
            <TableCell className="text-right tabular-nums">{entry.quantity}</TableCell>
            <TableCell>{entry.patient_display_name ?? '—'}</TableCell>
            <TableCell className="max-w-[220px] truncate text-muted-foreground">
              {entry.reason_note ?? '—'}
            </TableCell>
            <TableCell>{entry.used_on}</TableCell>
          </TableRow>
        ))}
      </TableBody>
    </Table>
  );
}

/** Receipts/Transfers/Usage, each its own sub-tab, sharing one item +
 * date-range filter strip — the confirmed design's "History: receipts/
 * transfers/usage entries, filterable by item/date range." Reused
 * wholesale by Admin's own Inventory History tab (see AdminOverview.jsx).
 *
 * Patient identity on a usage row is `entry.patient_display_name` —
 * already fully resolved server-side (2026-08-28 fix; this table used
 * to fall back to a shortened raw patient id for every search-linked
 * patient, the exact "one more join this read-only log doesn't need"
 * tradeoff this docstring used to defend, overridden by real production
 * confusion — see backend/app/modules/inventory/router.py's
 * list_usage_entries docstring for the actual resolution). */
export function InventoryHistoryPanel() {
  const { data: items } = useInventoryItems();
  const [activeTab, setActiveTab] = useState('receipts');
  const [itemId, setItemId] = useState('');
  const [startDate, setStartDate] = useState('');
  const [endDate, setEndDate] = useState('');
  const printHistoryLog = usePrintInventoryHistoryLog();
  const [printError, setPrintError] = useState(null);

  async function handlePrint() {
    setPrintError(null);
    try {
      await printHistoryLog.mutateAsync({
        logType: HISTORY_TAB_TO_LOG_TYPE[activeTab],
        itemId,
        startDate,
        endDate,
      });
    } catch (error) {
      setPrintError(error.message || 'Unable to print this log.');
    }
  }

  return (
    <Card>
      <CardHeader className="flex flex-col gap-4">
        <div className="flex items-center justify-between gap-3">
          <CardTitle>History</CardTitle>
          <Button size="sm" variant="outline" onClick={handlePrint} disabled={printHistoryLog.isPending}>
            <Printer className="h-4 w-4" />
            {printHistoryLog.isPending ? 'Preparing…' : 'Print'}
          </Button>
        </div>
        <div className="flex flex-wrap items-end gap-3">
          <div className="flex flex-col gap-1.5">
            <Label htmlFor="history-item">Item</Label>
            <Select
              id="history-item"
              value={itemId}
              onChange={(event) => setItemId(event.target.value)}
              className="w-auto"
            >
              <option value="">All items</option>
              {(items ?? []).map((item) => (
                <option key={item.id} value={item.id}>
                  {item.name}
                </option>
              ))}
            </Select>
          </div>
          <div className="flex flex-col gap-1.5">
            <Label htmlFor="history-start">From</Label>
            <Input
              id="history-start"
              type="date"
              value={startDate}
              onChange={(event) => setStartDate(event.target.value)}
              className="w-auto"
            />
          </div>
          <div className="flex flex-col gap-1.5">
            <Label htmlFor="history-end">To</Label>
            <Input
              id="history-end"
              type="date"
              value={endDate}
              onChange={(event) => setEndDate(event.target.value)}
              className="w-auto"
            />
          </div>
          <Tabs value={activeTab} onValueChange={setActiveTab} tabs={HISTORY_TABS} />
        </div>
      </CardHeader>
      <CardContent>
        {activeTab === 'receipts' ? (
          <ReceiptsTable
            items={items ?? []}
            itemId={itemId}
            startDate={startDate}
            endDate={endDate}
          />
        ) : activeTab === 'transfers' ? (
          <TransfersTable
            items={items ?? []}
            itemId={itemId}
            startDate={startDate}
            endDate={endDate}
          />
        ) : (
          <UsageTable items={items ?? []} itemId={itemId} startDate={startDate} endDate={endDate} />
        )}
        {printError ? <p className="mt-3 text-sm text-destructive">{printError}</p> : null}
      </CardContent>
    </Card>
  );
}
