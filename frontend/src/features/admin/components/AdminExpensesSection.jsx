'use client';

import { useMemo, useState } from 'react';
import { Wallet } from 'lucide-react';
import { DateNavigator } from '@/features/admin/components/DateNavigator';
import { useAllExpenses, useExpenseBreakdown } from '@/features/expenses/hooks/useExpenses';
import { Card, CardContent, CardHeader, CardTitle } from '@/shared/components/ui/Card';
import { Label } from '@/shared/components/ui/Label';
import { Select } from '@/shared/components/ui/Select';
import { PageError } from '@/shared/components/PageError';
import { PageLoader } from '@/shared/components/PageLoader';
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from '@/shared/components/ui/Table';
import { formatDisplayDate, formatDisplayTime, todayDisplayDayKey } from '@/utils/timezone';

const currencyFormatter = new Intl.NumberFormat('en-US', {
  minimumFractionDigits: 2,
  maximumFractionDigits: 2,
});

function formatPkr(amount) {
  return `PKR ${currencyFormatter.format(Number(amount))}`;
}

/** Admin's per-receptionist expense oversight (expenses:read_all) — one
 * day at a time via the shared `DateNavigator`, optionally narrowed to
 * a single receptionist. Two reads: the day's per-receptionist rollup
 * (`useExpenseBreakdown`, names resolved server-side) drives both the
 * summary table and the receptionist filter's option list; the flat
 * per-expense list (`useAllExpenses`) is the detail table below it.
 * Read-only throughout — Admin never edits or deletes a receptionist's
 * expense (there is no admin-correction endpoint for expenses, by
 * design; same-day owner-only is the whole edit story). */
export function AdminExpensesSection() {
  const [selectedDate, setSelectedDate] = useState(() => todayDisplayDayKey());
  const [receptionistId, setReceptionistId] = useState('');

  const { breakdown, isLoading: breakdownLoading } = useExpenseBreakdown({ date: selectedDate });
  const {
    expenses,
    isLoading: expensesLoading,
    isError,
    error,
    refetch,
  } = useAllExpenses({ date: selectedDate, receptionistId: receptionistId || undefined });

  const receptionistOptions = useMemo(
    () =>
      (breakdown?.rows ?? []).map((row) => ({
        id: row.receptionist_id,
        name: row.receptionist_name || 'Unknown receptionist',
      })),
    [breakdown],
  );

  // A previously-selected receptionist with no expenses on the newly-
  // chosen day drops out of the options — fall back to "All" rather
  // than filtering by an id that isn't offered anymore.
  const activeReceptionistId = receptionistOptions.some((option) => option.id === receptionistId)
    ? receptionistId
    : '';

  function handleDateChange(nextDate) {
    setSelectedDate(nextDate);
    setReceptionistId('');
  }

  return (
    <Card>
      <CardHeader className="flex-col items-start gap-3 sm:flex-row sm:items-center sm:justify-between">
        <CardTitle className="flex items-center gap-2">
          <Wallet className="h-4 w-4 text-muted-foreground" />
          Cash Expenses
        </CardTitle>
        <div className="flex flex-wrap items-center gap-3">
          <div className="flex items-center gap-2">
            <Label htmlFor="admin-expense-receptionist" className="text-xs text-muted-foreground">
              Receptionist
            </Label>
            <Select
              id="admin-expense-receptionist"
              value={activeReceptionistId}
              onChange={(event) => setReceptionistId(event.target.value)}
              className="w-auto"
            >
              <option value="">All</option>
              {receptionistOptions.map((option) => (
                <option key={option.id} value={option.id}>
                  {option.name}
                </option>
              ))}
            </Select>
          </div>
          <DateNavigator selectedDate={selectedDate} onChange={handleDateChange} />
        </div>
      </CardHeader>
      <CardContent className="flex flex-col gap-5">
        <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
          <div className="flex items-center gap-3 rounded-md border border-border bg-muted/30 p-4">
            <div className="flex h-9 w-9 shrink-0 items-center justify-center rounded-full bg-primary/10 text-primary">
              <Wallet className="h-4 w-4" />
            </div>
            <div className="flex flex-col">
              <span className="text-xs text-muted-foreground">
                Total Expenses · {formatDisplayDate(selectedDate)}
              </span>
              <span className="text-xl font-semibold tabular-nums text-foreground">
                {formatPkr(breakdown?.grand_total ?? 0)}
              </span>
            </div>
          </div>
        </div>

        <div className="flex flex-col gap-2">
          <p className="text-xs font-medium text-muted-foreground">By Receptionist</p>
          {breakdownLoading ? (
            <PageLoader label="Loading expense breakdown" />
          ) : (breakdown?.rows ?? []).length === 0 ? (
            <p className="py-6 text-center text-sm text-muted-foreground">
              No expenses were logged on {formatDisplayDate(selectedDate)}.
            </p>
          ) : (
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>Receptionist</TableHead>
                  <TableHead className="text-right">Entries</TableHead>
                  <TableHead className="text-right">Total</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {breakdown.rows.map((row) => (
                  <TableRow key={row.receptionist_id}>
                    <TableCell className="font-medium text-foreground">
                      {row.receptionist_name || 'Unknown receptionist'}
                    </TableCell>
                    <TableCell className="text-right tabular-nums">{row.expense_count}</TableCell>
                    <TableCell className="whitespace-nowrap text-right font-medium tabular-nums">
                      {formatPkr(row.total_amount)}
                    </TableCell>
                  </TableRow>
                ))}
                <TableRow>
                  <TableCell className="font-semibold text-foreground">Grand total</TableCell>
                  <TableCell className="text-right font-semibold tabular-nums">
                    {breakdown.total_count}
                  </TableCell>
                  <TableCell className="whitespace-nowrap text-right font-semibold tabular-nums">
                    {formatPkr(breakdown.grand_total)}
                  </TableCell>
                </TableRow>
              </TableBody>
            </Table>
          )}
        </div>

        <div className="flex flex-col gap-2">
          <p className="text-xs font-medium text-muted-foreground">Entries</p>
          {expensesLoading ? (
            <PageLoader label="Loading expenses" />
          ) : isError ? (
            <PageError error={error} reset={refetch} message="Couldn't load expenses." />
          ) : expenses.length === 0 ? (
            <p className="py-6 text-center text-sm text-muted-foreground">
              {activeReceptionistId
                ? 'This receptionist logged no expenses on this day.'
                : `No expenses were logged on ${formatDisplayDate(selectedDate)}.`}
            </p>
          ) : (
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>Time</TableHead>
                  <TableHead className="text-right">Amount</TableHead>
                  <TableHead>Reason</TableHead>
                  <TableHead>Recipient</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {expenses.map((expense) => (
                  <TableRow key={expense.id}>
                    <TableCell className="whitespace-nowrap">
                      {formatDisplayTime(expense.created_at)}
                    </TableCell>
                    <TableCell className="whitespace-nowrap text-right font-medium tabular-nums">
                      {formatPkr(expense.amount)}
                    </TableCell>
                    <TableCell className="max-w-[240px] truncate">{expense.reason}</TableCell>
                    <TableCell className="max-w-[160px] truncate">
                      {expense.recipient_name}
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          )}
        </div>
      </CardContent>
    </Card>
  );
}
