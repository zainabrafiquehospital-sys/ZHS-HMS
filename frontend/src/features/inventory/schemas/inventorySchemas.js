import { z } from 'zod';

// Mirrors backend/app/modules/inventory/models.py's InventoryCategory/
// InventoryUnit/CATEGORY_ALLOWED_UNITS exactly — kept in sync manually
// (the frontend has no way to read backend constants at build time,
// same convention as pharmacySchemas.js's MEDICINE_CATEGORIES). Used to
// filter the Unit select down to only the units standardized for the
// selected category, so a user can't even pick an invalid combination
// client-side; the backend re-validates regardless (InventoryService.
// update_item/create_item are the real enforcement boundary — see that
// module's own docstring on why this can't be a pure schema-level rule).
export const INVENTORY_CATEGORIES = ['medicine', 'injection', 'drip', 'equipment'];

export const CATEGORY_ALLOWED_UNITS = {
  medicine: ['piece', 'bottle', 'box'],
  injection: ['vial', 'ampoule', 'piece'],
  drip: ['bottle', 'ml'],
  equipment: ['piece', 'box'],
};

const positiveQuantity = (message) =>
  z
    .union([z.string(), z.number()])
    .transform((value) => Number(value))
    .refine((value) => Number.isFinite(value) && value > 0, { message });

export const inventoryItemFormSchema = z
  .object({
    name: z.string().min(1, 'Item name is required').max(150),
    category: z.enum(INVENTORY_CATEGORIES, {
      errorMap: () => ({ message: 'Select a category' }),
    }),
    unit: z.string().min(1, 'Select a unit'),
    // Blank means "no low-stock alert configured" — the same
    // blank/optional convention pharmacySchemas.js's finalizeBillSchema
    // uses for an optional money field, just mapped to `null` (never
    // `0`, which would mean "always low") rather than `0`.
    low_stock_threshold: z
      .union([z.string(), z.number()])
      .transform((value) => (value === '' || value === null || value === undefined ? null : Number(value)))
      .refine((value) => value === null || (Number.isFinite(value) && value > 0), {
        message: 'Threshold must be greater than 0',
      }),
  })
  .refine((data) => (CATEGORY_ALLOWED_UNITS[data.category] ?? []).includes(data.unit), {
    message: 'Select a unit that is standardized for this category',
    path: ['unit'],
  });

export const receiveStockFormSchema = z.object({
  item_id: z.string().min(1, 'Select an item'),
  quantity: positiveQuantity('Quantity must be greater than 0'),
  received_on: z.string().min(1, 'Select a date'),
});

export const transferStockFormSchema = z.object({
  item_id: z.string().min(1, 'Select an item'),
  quantity: positiveQuantity('Quantity must be greater than 0'),
  transferred_on: z.string().min(1, 'Select a date'),
});

export const fulfillRequestFormSchema = z.object({
  transfer_quantity: positiveQuantity('Transfer quantity must be greater than 0'),
  transferred_on: z.string().min(1, 'Select a date'),
});

// rejection_reason is always optional (confirmed design — see
// backend/app/modules/inventory/models.py's InventoryRestockRequest
// docstring: a rejection needs no mandatory justification).
export const rejectRequestFormSchema = z.object({
  rejection_reason: z.string().max(200).optional().or(z.literal('')),
});

// ---------------------------------------------------------------------
// Vitals' own two forms (step 4)
// ---------------------------------------------------------------------

// Same three fields/shape as pharmacySchemas.js's manualPatientSchema —
// duplicated locally rather than imported cross-feature, matching this
// codebase's established per-feature schema-file independence (see that
// module's own nonNegativeAmount docstring for the same convention
// stated explicitly).
export const inventoryManualPatientSchema = z.object({
  manual_patient_name: z.string().min(1, 'Name is required').max(150),
  manual_patient_age: z
    .union([z.string(), z.number()])
    .transform((value) => Number(value))
    .refine((value) => Number.isInteger(value) && value >= 0 && value <= 150, {
      message: 'Age must be a whole number between 0 and 150',
    }),
  manual_patient_phone: z.string().min(6, 'Contact number is required').max(20),
});

export const recordUsageFormSchema = z.object({
  item_id: z.string().min(1, 'Select an item'),
  quantity: positiveQuantity('Quantity must be greater than 0'),
  used_on: z.string().min(1, 'Select a date'),
  reason_note: z.string().max(200).optional().or(z.literal('')),
});

export const raiseRestockRequestFormSchema = z.object({
  item_id: z.string().min(1, 'Select an item'),
  requested_quantity: z
    .union([z.string(), z.number()])
    .transform((value) => (value === '' || value === null || value === undefined ? null : Number(value)))
    .refine((value) => value === null || (Number.isFinite(value) && value > 0), {
      message: 'Requested quantity must be greater than 0',
    }),
  note: z.string().max(200).optional().or(z.literal('')),
});
