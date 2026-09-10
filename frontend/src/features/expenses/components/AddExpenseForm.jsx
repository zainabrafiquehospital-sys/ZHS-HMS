'use client';

import { useState } from 'react';
import { useForm } from 'react-hook-form';
import { zodResolver } from '@hookform/resolvers/zod';
import { PlusCircle } from 'lucide-react';
import { useCreateExpense } from '@/features/expenses/hooks/useExpenses';
import { expenseFormSchema } from '@/features/expenses/schemas/expenseSchemas';
import { Card, CardContent, CardHeader, CardTitle } from '@/shared/components/ui/Card';
import { Button } from '@/shared/components/ui/Button';
import { Input } from '@/shared/components/ui/Input';
import { Label } from '@/shared/components/ui/Label';
import { useToast } from '@/shared/components/toast/ToastProvider';
import { formatDisplayDate, todayDisplayDayKey } from '@/utils/timezone';

const EMPTY_VALUES = { amount: '', reason: '', recipient_name: '' };

/** The receptionist's "Log Cash Expense" form — Amount / Reason /
 * Recipient Name only. The expense's date is always the current
 * Asia/Karachi day, set server-side (no backdating — see
 * ExpenseService.create); it is shown here read-only so the
 * receptionist can see exactly which day this will land on, never
 * chosen. On success the amount is deducted from Net Revenue on the
 * "My Registrations" view (both queries are invalidated together — see
 * useExpenses' write-invalidation helper). */
export function AddExpenseForm() {
  const { toast } = useToast();
  const createExpense = useCreateExpense();
  const [submitError, setSubmitError] = useState(null);
  const {
    register,
    handleSubmit,
    reset,
    formState: { errors, isSubmitting },
  } = useForm({
    resolver: zodResolver(expenseFormSchema),
    defaultValues: EMPTY_VALUES,
  });

  async function onSubmit(values) {
    setSubmitError(null);
    try {
      await createExpense.mutateAsync(values);
      toast.success({
        title: 'Expense logged',
        description: `PKR ${values.amount} — ${values.recipient_name}`,
      });
      reset(EMPTY_VALUES);
    } catch (error) {
      const message = error.message || 'Unable to log this expense.';
      setSubmitError(message);
      toast.error({ title: 'Unable to log expense', description: message });
    }
  }

  return (
    <Card>
      <CardHeader>
        <CardTitle>Log Cash Expense</CardTitle>
      </CardHeader>
      <CardContent>
        <form
          onSubmit={handleSubmit(onSubmit)}
          className="flex flex-col gap-4 sm:flex-row sm:flex-wrap sm:items-end"
        >
          <div className="flex flex-col gap-1.5">
            <Label htmlFor="expense-amount">Amount (Rs.)</Label>
            <Input
              id="expense-amount"
              type="number"
              step="0.01"
              min="0"
              className="sm:w-40"
              {...register('amount')}
            />
            {errors.amount ? (
              <p className="text-xs text-destructive">{errors.amount.message}</p>
            ) : null}
          </div>
          <div className="flex min-w-[200px] flex-1 flex-col gap-1.5">
            <Label htmlFor="expense-reason">Reason</Label>
            <Input id="expense-reason" {...register('reason')} />
            {errors.reason ? (
              <p className="text-xs text-destructive">{errors.reason.message}</p>
            ) : null}
          </div>
          <div className="flex min-w-[180px] flex-1 flex-col gap-1.5">
            <Label htmlFor="expense-recipient">Recipient Name</Label>
            <Input id="expense-recipient" {...register('recipient_name')} />
            {errors.recipient_name ? (
              <p className="text-xs text-destructive">{errors.recipient_name.message}</p>
            ) : null}
          </div>
          <div className="flex flex-col gap-1.5">
            <Label>Date</Label>
            <p className="rounded-md border border-border bg-muted/30 px-3 py-2 text-sm text-muted-foreground">
              {formatDisplayDate(todayDisplayDayKey())}
            </p>
          </div>
          <Button type="submit" disabled={isSubmitting}>
            <PlusCircle className="h-4 w-4" />
            {isSubmitting ? 'Saving…' : 'Log Expense'}
          </Button>
        </form>
        {submitError ? (
          <p className="mt-3 rounded-md bg-destructive/10 px-3 py-2 text-sm text-destructive">
            {submitError}
          </p>
        ) : null}
      </CardContent>
    </Card>
  );
}
