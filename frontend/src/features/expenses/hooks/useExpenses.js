import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { expensesService } from '@/features/expenses/api/expensesService';
import { useAuth } from '@/features/auth/hooks/useAuth';

/** Invalidates every cached expense list/rollup (`['expenses']` is a
 * prefix match — a written expense can be showing on the receptionist's
 * own "today" list, the admin day list, or the admin breakdown at
 * once) plus the calling receptionist's own "My Revenue" aggregate
 * (`['reception', 'revenue', 'own', id]`), since Net Revenue there is
 * `total_revenue - Σ own expenses` and must move the moment an expense
 * is logged, edited, or removed. */
function useExpenseWriteInvalidation() {
  const queryClient = useQueryClient();
  const { user } = useAuth();
  return () => {
    queryClient.invalidateQueries({ queryKey: ['expenses'] });
    queryClient.invalidateQueries({ queryKey: ['reception', 'revenue', 'own', user?.id] });
  };
}

/** The calling receptionist's own expenses for one Asia/Karachi day
 * (default: today) — newest first, hard-scoped server-side to
 * `actor.id` (see backend expensesService.listMine). `date` is a
 * `displayDayKey`-shaped "YYYY-MM-DD" string or undefined for today. */
export function useMyExpenses({ date } = {}) {
  const { user } = useAuth();
  const query = useQuery({
    queryKey: ['expenses', 'mine', user?.id, date ?? null],
    queryFn: () => expensesService.listMine({ date }).then((res) => res.data),
    enabled: Boolean(user?.id),
    refetchInterval: 30000,
  });
  return { ...query, expenses: query.data ?? [] };
}

export function useCreateExpense() {
  const invalidate = useExpenseWriteInvalidation();
  return useMutation({
    mutationFn: (payload) => expensesService.create(payload),
    onSuccess: invalidate,
  });
}

export function useUpdateExpense() {
  const invalidate = useExpenseWriteInvalidation();
  return useMutation({
    mutationFn: ({ expenseId, payload }) => expensesService.update(expenseId, payload),
    onSuccess: invalidate,
  });
}

export function useDeleteExpense() {
  const invalidate = useExpenseWriteInvalidation();
  return useMutation({
    mutationFn: (expenseId) => expensesService.remove(expenseId),
    onSuccess: invalidate,
  });
}

/** Admin-only (expenses:read_all) — every receptionist's expenses for
 * one day, optionally narrowed to a single receptionist. */
export function useAllExpenses({ date, receptionistId } = {}) {
  const query = useQuery({
    queryKey: ['expenses', 'all', date ?? null, receptionistId ?? null],
    queryFn: () => expensesService.listAll({ date, receptionistId }).then((res) => res.data),
    enabled: Boolean(date),
    refetchInterval: 30000,
  });
  return { ...query, expenses: query.data ?? [] };
}

/** Admin-only (expenses:read_all) — the per-receptionist rollup for one
 * day: `rows` (each `{receptionist_id, receptionist_name, expense_count,
 * total_amount}`) plus `total_count` / `grand_total`. */
export function useExpenseBreakdown({ date } = {}) {
  const query = useQuery({
    queryKey: ['expenses', 'stats', date ?? null],
    queryFn: () => expensesService.getBreakdown({ date }).then((res) => res.data),
    enabled: Boolean(date),
    refetchInterval: 30000,
  });
  return { ...query, breakdown: query.data ?? null };
}
