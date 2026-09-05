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

// One row's quantity in any of the three stock-movement checklists
// (2026-09 redesign — InventoryStockChecklist.jsx, shared by Receive to
// Main Stock, Transfer to Emergency, and Receive Directly to Emergency)
// — same shape as usageLineItemSchema below, no per-line note (nothing
// about "how much of this item moved" needs a per-line reason the way a
// usage entry's reason_note does; the batch-wide context — received_on,
// or transferred_on+carried_by_name — is validated separately by
// whichever screen owns those fields).
export const stockBatchLineItemSchema = z.object({
  quantity: positiveQuantity('Quantity must be greater than 0'),
});

// carried_by_name (2026-08-28 addition) is required — free text, the
// person who physically carried the stock — shared by the whole batch,
// validated alongside `transferred_on` the same "plain local state"
// way `used_on` is for Record Usage's own batch.
export const carriedByNameSchema = z
  .string()
  .min(1, 'Enter who carried this stock')
  .max(150);

export const fulfillRequestFormSchema = z.object({
  transfer_quantity: positiveQuantity('Transfer quantity must be greater than 0'),
  transferred_on: z.string().min(1, 'Select a date'),
  carried_by_name: carriedByNameSchema,
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

// `used_on` is shared by the whole batch (validated ad hoc alongside the
// patient-linkage fields in RecordInventoryUsageForm.jsx, the same "plain
// local state, not folded into a zod schema" convention
// MedicineBillingWorkspace.jsx's own linkMode toggles already follow) —
// this only validates one line being added to the running list, same
// shape as pharmacySchemas.js's billLineItemSchema.
export const usageLineItemSchema = z.object({
  quantity: positiveQuantity('Quantity must be greater than 0'),
  reason_note: z.string().max(200).optional().or(z.literal('')),
});

// (raiseRestockRequestFormSchema removed 2026-09 — the one-item-at-a-
// time RaiseRestockRequestForm.jsx it validated was replaced by the
// checklist-batch VitalsBuildRequirementForm.jsx, which reuses the
// shared InventoryStockChecklist's own per-row quantity handling and
// needs no dedicated form schema of its own.)
