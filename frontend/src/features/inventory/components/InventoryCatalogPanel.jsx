'use client';

import { useEffect, useState } from 'react';
import { useForm } from 'react-hook-form';
import { zodResolver } from '@hookform/resolvers/zod';
import { Pencil, PlusCircle, Power, PowerOff } from 'lucide-react';
import {
  useInventoryItems,
  useCreateInventoryItem,
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
import { Badge } from '@/shared/components/ui/Badge';
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

const EMPTY_VALUES = { name: '', category: '', unit: '', low_stock_threshold: '' };

/** Doubles as the "Add Item" and "Edit Item" form — `editing` (an
 * InventoryItemOut, or null) picks which mode it's in — same shape as
 * features/pharmacy/components/MedicineManagement.jsx's
 * MedicineFormPanel. The Unit select is filtered live to only the units
 * standardized for whichever category is currently selected (see
 * inventorySchemas.js's CATEGORY_ALLOWED_UNITS) — never a free-typed
 * unit, matching the confirmed design's "standardized per category, not
 * free text" requirement. */
function ItemFormPanel({ editing, onDoneEditing }) {
  const createItem = useCreateInventoryItem();
  const updateItem = useUpdateInventoryItem();
  const [submitError, setSubmitError] = useState(null);
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
    try {
      if (editing) {
        await updateItem.mutateAsync({ itemId: editing.id, payload: values });
        onDoneEditing?.();
      } else {
        await createItem.mutateAsync(values);
        reset(EMPTY_VALUES);
      }
    } catch (error) {
      setSubmitError(error.message || 'Unable to save this item.');
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

function ItemsListPanel({ items, onEdit }) {
  const updateItem = useUpdateInventoryItem();
  const [toggleError, setToggleError] = useState(null);

  async function handleToggleActive(item) {
    setToggleError(null);
    try {
      await updateItem.mutateAsync({ itemId: item.id, payload: { is_active: !item.is_active } });
    } catch (error) {
      setToggleError(error.message || 'Unable to update this item.');
    }
  }

  return (
    <Card>
      <CardHeader>
        <CardTitle>Item Catalog</CardTitle>
      </CardHeader>
      <CardContent className="flex flex-col gap-4">
        {items.length === 0 ? (
          <p className="text-sm text-muted-foreground">No items added yet.</p>
        ) : (
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>Name</TableHead>
                <TableHead>Category</TableHead>
                <TableHead>Unit</TableHead>
                <TableHead className="text-right">Main Stock</TableHead>
                <TableHead className="text-right">Emergency Stock</TableHead>
                <TableHead>Status</TableHead>
                <TableHead />
              </TableRow>
            </TableHeader>
            <TableBody>
              {items.map((item) => (
                <TableRow key={item.id}>
                  <TableCell className="font-medium text-foreground">{item.name}</TableCell>
                  <TableCell className="capitalize">{item.category}</TableCell>
                  <TableCell className="capitalize">{item.unit}</TableCell>
                  <TableCell className="text-right tabular-nums">{item.main_stock_level}</TableCell>
                  <TableCell className="text-right tabular-nums">
                    <span className="inline-flex items-center gap-1.5">
                      {item.emergency_stock_level}
                      {item.is_low_stock ? <Badge variant="warning">Low</Badge> : null}
                    </span>
                  </TableCell>
                  <TableCell>
                    <Badge variant={item.is_active ? 'success' : 'outline'}>
                      {item.is_active ? 'Active' : 'Inactive'}
                    </Badge>
                  </TableCell>
                  <TableCell>
                    <div className="flex justify-end gap-2">
                      <Button size="sm" variant="outline" onClick={() => onEdit(item)}>
                        <Pencil className="h-4 w-4" />
                        Edit
                      </Button>
                      <Button
                        size="sm"
                        variant="ghost"
                        onClick={() => handleToggleActive(item)}
                        disabled={updateItem.isPending}
                      >
                        {item.is_active ? (
                          <>
                            <PowerOff className="h-4 w-4" />
                            Deactivate
                          </>
                        ) : (
                          <>
                            <Power className="h-4 w-4" />
                            Activate
                          </>
                        )}
                      </Button>
                    </div>
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        )}
        {toggleError ? <p className="text-sm text-destructive">{toggleError}</p> : null}
      </CardContent>
    </Card>
  );
}

export function InventoryCatalogPanel() {
  const { data: items, isLoading, isError, error, refetch } = useInventoryItems();
  const [editing, setEditing] = useState(null);

  return (
    <div className="flex flex-col gap-6">
      <ItemFormPanel editing={editing} onDoneEditing={() => setEditing(null)} />

      {isLoading ? (
        <PageLoader label="Loading catalog" />
      ) : isError ? (
        <PageError error={error} reset={refetch} message="Couldn't load the item catalog." />
      ) : (
        <ItemsListPanel items={items ?? []} onEdit={setEditing} />
      )}
    </div>
  );
}
