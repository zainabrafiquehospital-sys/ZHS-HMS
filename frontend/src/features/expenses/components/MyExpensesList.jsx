'use client';

import { useState } from 'react';
import { useForm } from 'react-hook-form';
import { zodResolver } from '@hookform/resolvers/zod';
import { Pencil, Trash2 } from 'lucide-react';
import { useDeleteExpense, useMyExpenses, useUpdateExpense } from '@/features/expenses/hooks/useExpenses';
import { expenseFormSchema } from '@/features/expenses/schemas/expenseSchemas';
import { Card, CardContent, CardHeader, CardTitle } from '@/shared/components/ui/Card';
import { Button } from '@/shared/components/ui/Button';
import { ConfirmDialog } from '@/shared/components/ui/ConfirmDialog';
import { Input } from '@/shared/components/ui/Input';
import { Label } from '@/shared/components/ui/Label';
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
import { formatDisplayTime, todayDisplayDayKey } from '@/utils/timezone';

const currencyFormatter = new Intl.NumberFormat('en-US', {
  minimumFractionDigits: 2,
  maximumFractionDigits: 2,
});

function formatPkr(amount) {
  return `PKR ${currencyFormatter.format(Number(amount))}`;
}

/** Inline "Edit Expense" — Amount / Reason / Recipient Name, same three
 * fields as AddExpenseForm. Only ever rendered for an expense whose
 * `expense_date` is still today (the Edit button that opens it is
 * itself gated below); the backend re-checks both ownership (403) and
 * the same-day window (409 EXPENSE_EDIT_WINDOW_CLOSED) regardless, so
 * this dialog is not a second authorization boundary. */
function EditExpenseDialog({ expense, onClose }) {
  const updateExpense = useUpdateExpense();
  const [error, setError] = useState(null);
  const {
    register,
    handleSubmit,
    formState: { errors, isSubmitting },
  } = useForm({
    resolver: zodResolver(expenseFormSchema),
    defaultValues: {
      amount: expense.amount,
      reason: expense.reason,
      recipient_name: expense.recipient_name,
    },
  });

  async function onSubmit(values) {
    setError(null);
    try {
      await updateExpense.mutateAsync({ expenseId: expense.id, payload: values });
      onClose();
    } catch (submitError) {
      setError(submitError.message || 'Unable to update this expense.');
    }
  }

  return (
    <ConfirmDialog
      open
      title="Edit Expense"
      confirmLabel={isSubmitting ? 'Saving…' : 'Save Changes'}
      cancelLabel="Cancel"
      onCancel={onClose}
      onConfirm={handleSubmit(onSubmit)}
      description={
        <div className="flex flex-col gap-3">
          <div className="flex flex-col gap-1.5">
            <Label htmlFor="edit-expense-amount">Amount (Rs.)</Label>
            <Input
              id="edit-expense-amount"
              type="number"
              step="0.01"
              min="0"
              {...register('amount')}
            />
            {errors.amount ? (
              <p className="text-xs text-destructive">{errors.amount.message}</p>
            ) : null}
          </div>
          <div className="flex flex-col gap-1.5">
            <Label htmlFor="edit-expense-reason">Reason</Label>
            <Input id="edit-expense-reason" {...register('reason')} />
            {errors.reason ? (
              <p className="text-xs text-destructive">{errors.reason.message}</p>
            ) : null}
          </div>
          <div className="flex flex-col gap-1.5">
            <Label htmlFor="edit-expense-recipient">Recipient Name</Label>
            <Input id="edit-expense-recipient" {...register('recipient_name')} />
            {errors.recipient_name ? (
              <p className="text-xs text-destructive">{errors.recipient_name.message}</p>
            ) : null}
          </div>
          {error ? <p className="text-xs text-destructive">{error}</p> : null}
        </div>
      }
    />
  );
}

function DeleteExpenseDialog({ expense, onClose }) {
  const deleteExpense = useDeleteExpense();
  const [error, setError] = useState(null);

  async function handleConfirm() {
    setError(null);
    try {
      await deleteExpense.mutateAsync(expense.id);
      onClose();
    } catch (deleteError) {
      setError(deleteError.message || 'Unable to delete this expense.');
    }
  }

  return (
    <ConfirmDialog
      open
      variant="destructive"
      title="Delete this expense?"
      confirmLabel={deleteExpense.isPending ? 'Deleting…' : 'Delete Expense'}
      cancelLabel="Cancel"
      onCancel={onClose}
      onConfirm={handleConfirm}
      description={
        <div className="flex flex-col gap-2">
          <p>
            This removes {formatPkr(expense.amount)} paid to {expense.recipient_name} from today's
            expenses — your Net Revenue will go back up by that amount. This can only be done on
            the day the expense was logged.
          </p>
          {error ? <p className="text-destructive">{error}</p> : null}
        </div>
      }
    />
  );
}

/** Today's own cash expenses — newest first (see useMyExpenses, which
 * defaults to the current Asia/Karachi day). Edit/Delete are shown only
 * while an expense's `expense_date` is still today: once the calendar
 * day rolls over (Karachi time) the record is locked, matching the
 * backend's same-day-only window exactly (ExpenseService.update /
 * .delete raise 409 after that). */
export function MyExpensesList() {
  const { expenses, isLoading, isError, error, refetch } = useMyExpenses();
  const [editing, setEditing] = useState(null);
  const [deleting, setDeleting] = useState(null);
  const today = todayDisplayDayKey();

  const total = expenses.reduce((sum, expense) => sum + Number(expense.amount), 0);

  return (
    <Card>
      <CardHeader className="flex-row items-center justify-between gap-2">
        <CardTitle>Today's Expenses</CardTitle>
        {expenses.length > 0 ? (
          <span className="text-sm text-muted-foreground">
            {expenses.length} · {formatPkr(total)}
          </span>
        ) : null}
      </CardHeader>
      <CardContent>
        {isLoading ? (
          <PageLoader label="Loading your expenses" />
        ) : isError ? (
          <PageError error={error} reset={refetch} message="Couldn't load your expenses." />
        ) : expenses.length === 0 ? (
          <p className="py-8 text-center text-sm text-muted-foreground">
            No expenses logged today.
          </p>
        ) : (
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>Time</TableHead>
                <TableHead className="text-right">Amount</TableHead>
                <TableHead>Reason</TableHead>
                <TableHead>Recipient</TableHead>
                <TableHead />
              </TableRow>
            </TableHeader>
            <TableBody>
              {expenses.map((expense) => {
                const editable = expense.expense_date === today;
                return (
                  <TableRow key={expense.id}>
                    <TableCell className="whitespace-nowrap">
                      {formatDisplayTime(expense.created_at)}
                    </TableCell>
                    <TableCell className="whitespace-nowrap text-right font-medium tabular-nums">
                      {formatPkr(expense.amount)}
                    </TableCell>
                    <TableCell className="max-w-[220px] truncate">{expense.reason}</TableCell>
                    <TableCell className="max-w-[160px] truncate">
                      {expense.recipient_name}
                    </TableCell>
                    <TableCell>
                      {editable ? (
                        <div className="flex justify-end gap-2">
                          <Button
                            size="sm"
                            variant="outline"
                            onClick={() => setEditing(expense)}
                            title="Edit this expense"
                          >
                            <Pencil className="h-3.5 w-3.5" />
                          </Button>
                          <Button
                            size="sm"
                            variant="outline"
                            onClick={() => setDeleting(expense)}
                            title="Delete this expense"
                          >
                            <Trash2 className="h-3.5 w-3.5" />
                          </Button>
                        </div>
                      ) : (
                        <span className="block text-right text-xs text-muted-foreground">
                          Locked
                        </span>
                      )}
                    </TableCell>
                  </TableRow>
                );
              })}
            </TableBody>
          </Table>
        )}
      </CardContent>
      {editing ? (
        <EditExpenseDialog expense={editing} onClose={() => setEditing(null)} />
      ) : null}
      {deleting ? (
        <DeleteExpenseDialog expense={deleting} onClose={() => setDeleting(null)} />
      ) : null}
    </Card>
  );
}
