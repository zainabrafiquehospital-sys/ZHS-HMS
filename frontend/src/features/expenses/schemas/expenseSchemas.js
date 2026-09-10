import { z } from 'zod';

// Mirrors backend/app/modules/expenses/schemas.py's CreateExpenseRequest
// exactly — amount > 0, reason 1–200 chars, recipient_name 1–150 chars,
// both text fields trimmed and rejected when blank (the backend's
// ExpenseService._nonblank re-checks this regardless — see that
// module's own docstring). Same manual-mirror + transform-then-refine
// convention as inventorySchemas.js (the frontend can't read backend
// constants at build time).
const trimmedText = (min, max, requiredMessage) =>
  z
    .string()
    .transform((value) => value.trim())
    .refine((value) => value.length >= min, { message: requiredMessage })
    .refine((value) => value.length <= max, { message: 'This is too long' });

export const expenseFormSchema = z.object({
  amount: z
    .union([z.string(), z.number()])
    .transform((value) => Number(value))
    .refine((value) => Number.isFinite(value) && value > 0, {
      message: 'Amount must be greater than 0',
    }),
  reason: trimmedText(1, 200, 'Reason is required'),
  recipient_name: trimmedText(1, 150, 'Recipient name is required'),
});
