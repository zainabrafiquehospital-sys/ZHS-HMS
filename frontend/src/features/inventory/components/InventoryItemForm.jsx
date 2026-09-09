'use client';

import { useEffect, useState } from 'react';
import { useForm } from 'react-hook-form';
import { zodResolver } from '@hookform/resolvers/zod';
import { PlusCircle } from 'lucide-react';
import {
  useCreateInventoryItem,
  useReceiveStock,
  useUpdateInventoryItem,
} from '@/features/inventory/hooks/useInventory';
import {
  INVENTORY_CATEGORIES,
  CATEGORY_ALLOWED_UNITS,
  inventoryItemFormSchema,
} from '@/features/inventory/schemas/inventorySchemas';
import { Card, CardContent, CardHeader, CardTitle } from '@/shared/components/ui/Card';
import { Button } from '@/shared/components/ui/Button';
import { Input } from '@/shared/components/ui/Input';
import { Label } from '@/shared/components/ui/Label';
import { Select } from '@/shared/components/ui/Select';
import { useToast } from '@/shared/components/toast/ToastProvider';
import { todayDisplayDayKey } from '@/utils/timezone';

const EMPTY_VALUES = {
  name: '',
  category: '',
  unit: '',
  low_stock_threshold: '',
  initial_quantity_received: '',
};

/** Doubles as the "Add Item" and "Edit Item" form — `editing` (an
 * InventoryItemOut, or null) picks which mode it's in — same shape as
 * features/pharmacy/components/MedicineManagement.jsx's
 * MedicineFormPanel. The Unit select is filtered live to only the units
 * standardized for whichever category is currently selected (see
 * inventorySchemas.js's CATEGORY_ALLOWED_UNITS) — never a free-typed
 * unit, matching the confirmed design's "standardized per category, not
 * free text" requirement.
 *
 * Extracted from InventoryCatalogPanel.jsx (2026-09) so both the
 * Inventory Manager's Catalog panel and Vitals' own gated "Add Item"
 * tab render the exact same form — creation is now a two-actor action
 * (`inventory:create_item`, granted to both), while the surrounding
 * Catalog management table stays Inventory-Manager-only. In pure
 * add mode (`editing={null}`), `onDoneEditing` is never invoked and
 * may be omitted.
 *
 * `showInitialReceipt` (2026-09) surfaces an optional "Initial Quantity
 * Received" field: when filled on *add*, the form creates the item and
 * then immediately fires a second `POST /inventory/items/{id}/receive`
 * for that quantity into Main Stock — one click, two sequential calls,
 * no combined backend endpoint. Left blank, the item is just created at
 * 0, exactly as before. Only the Inventory Manager's Catalog form
 * passes this: receiving is `inventory:manage`-gated, which Vitals (who
 * holds only `inventory:create_item`) does not have, so their Add Item
 * tab never shows the field. */
export function InventoryItemForm({ editing = null, onDoneEditing, showInitialReceipt = false }) {
  const { toast } = useToast();
  const createItem = useCreateInventoryItem();
  const updateItem = useUpdateInventoryItem();
  const receiveStock = useReceiveStock();
  const [submitError, setSubmitError] = useState(null);
  const offerInitialReceipt = showInitialReceipt && !editing;
  const {
    register,
    handleSubmit,
    reset,
    watch,
    setValue,
    formState: { errors, isSubmitting },
  } = useForm({
    resolver: zodResolver(inventoryItemFormSchema),
    defaultValues: EMPTY_VALUES,
  });

  const selectedCategory = watch('category');
  const allowedUnits = CATEGORY_ALLOWED_UNITS[selectedCategory] ?? [];

  useEffect(() => {
    if (editing) {
      reset({
        name: editing.name,
        category: editing.category,
        unit: editing.unit,
        low_stock_threshold: editing.low_stock_threshold ?? '',
        initial_quantity_received: '',
      });
    } else {
      reset(EMPTY_VALUES);
    }
  }, [editing, reset]);

  // Switching category away from the currently-selected unit's own
  // category invalidates that unit — clear it rather than silently
  // submitting a now-mismatched combination the backend would reject.
  function handleCategoryChange(event) {
    const nextCategory = event.target.value;
    setValue('category', nextCategory, { shouldValidate: true });
    const stillValid = (CATEGORY_ALLOWED_UNITS[nextCategory] ?? []).includes(watch('unit'));
    if (!stillValid) {
      setValue('unit', '');
    }
  }

  async function onSubmit(values) {
    setSubmitError(null);
    // `initial_quantity_received` is form-only — neither POST
    // /inventory/items nor PATCH accepts it; it drives the follow-up
    // receive call below.
    const { initial_quantity_received: initialQty, ...itemPayload } = values;
    try {
      if (editing) {
        await updateItem.mutateAsync({ itemId: editing.id, payload: itemPayload });
        toast.success({ title: 'Item updated', description: values.name });
        onDoneEditing?.();
        return;
      }

      const created = await createItem.mutateAsync(itemPayload);

      if (offerInitialReceipt && initialQty != null) {
        try {
          await receiveStock.mutateAsync({
            itemId: created.data.id,
            payload: { quantity: initialQty, received_on: todayDisplayDayKey() },
          });
          toast.success({
            title: 'Item added & stock received',
            description: `${values.name} — ${initialQty} ${values.unit} into Main Stock`,
          });
        } catch (receiveError) {
          // The item was created; only the follow-up receipt failed.
          // Surface it plainly so it can be redone from Receive Stock
          // rather than leaving a silent "created at 0" surprise.
          const detail = receiveError.message || 'record it from Receive Stock';
          setSubmitError(`Item "${values.name}" was added, but the initial receipt failed — ${detail}`);
          toast.error({
            title: 'Item added, but the initial receipt failed',
            description: detail,
          });
          reset(EMPTY_VALUES);
          return;
        }
      } else {
        toast.success({ title: 'Item added', description: values.name });
      }
      reset(EMPTY_VALUES);
    } catch (error) {
      const message = error.message || 'Unable to save this item.';
      setSubmitError(message);
      toast.error({
        title: editing ? 'Unable to update item' : 'Unable to add item',
        description: message,
      });
    }
  }

  return (
    <Card>
      <CardHeader>
        <CardTitle>{editing ? `Edit ${editing.name}` : 'Add Item'}</CardTitle>
      </CardHeader>
      <CardContent>
        <form
          onSubmit={handleSubmit(onSubmit)}
          className="flex flex-col gap-4 sm:flex-row sm:flex-wrap sm:items-end"
        >
          <div className="flex min-w-[200px] flex-1 flex-col gap-1.5">
            <Label htmlFor="name">Item Name</Label>
            <Input id="name" {...register('name')} />
            {errors.name ? <p className="text-xs text-destructive">{errors.name.message}</p> : null}
          </div>
          <div className="flex flex-col gap-1.5">
            <Label htmlFor="category">Category</Label>
            <Select id="category" {...register('category')} onChange={handleCategoryChange}>
              <option value="">Select…</option>
              {INVENTORY_CATEGORIES.map((category) => (
                <option key={category} value={category} className="capitalize">
                  {category}
                </option>
              ))}
            </Select>
            {errors.category ? (
              <p className="text-xs text-destructive">{errors.category.message}</p>
            ) : null}
          </div>
          <div className="flex flex-col gap-1.5">
            <Label htmlFor="unit">Unit</Label>
            <Select id="unit" {...register('unit')} disabled={!selectedCategory}>
              <option value="">Select…</option>
              {allowedUnits.map((unit) => (
                <option key={unit} value={unit}>
                  {unit}
                </option>
              ))}
            </Select>
            {errors.unit ? <p className="text-xs text-destructive">{errors.unit.message}</p> : null}
          </div>
          <div className="flex flex-col gap-1.5">
            <Label htmlFor="low_stock_threshold">Low-Stock Alert Below</Label>
            <Input
              id="low_stock_threshold"
              type="number"
              step="0.01"
              min="0"
              placeholder="No alert"
              {...register('low_stock_threshold')}
            />
            {errors.low_stock_threshold ? (
              <p className="text-xs text-destructive">{errors.low_stock_threshold.message}</p>
            ) : null}
          </div>
          {offerInitialReceipt ? (
            <div className="flex flex-col gap-1.5">
              <Label htmlFor="initial_quantity_received">Initial Quantity Received</Label>
              <Input
                id="initial_quantity_received"
                type="number"
                step="0.01"
                min="0"
                placeholder="Optional"
                {...register('initial_quantity_received')}
              />
              {errors.initial_quantity_received ? (
                <p className="text-xs text-destructive">
                  {errors.initial_quantity_received.message}
                </p>
              ) : (
                <p className="text-xs text-muted-foreground">Also receives this into Main Stock.</p>
              )}
            </div>
          ) : null}
          <div className="flex gap-2">
            <Button type="submit" disabled={isSubmitting}>
              <PlusCircle className="h-4 w-4" />
              {isSubmitting ? 'Saving…' : editing ? 'Save Changes' : 'Add Item'}
            </Button>
            {editing ? (
              <Button type="button" variant="outline" onClick={onDoneEditing}>
                Cancel
              </Button>
            ) : null}
          </div>
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
