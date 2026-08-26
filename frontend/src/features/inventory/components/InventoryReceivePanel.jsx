'use client';

import { useState } from 'react';
import { useForm } from 'react-hook-form';
import { zodResolver } from '@hookform/resolvers/zod';
import { PackagePlus } from 'lucide-react';
import { useInventoryItems, useReceiveStock } from '@/features/inventory/hooks/useInventory';
import { receiveStockFormSchema } from '@/features/inventory/schemas/inventorySchemas';
import { Card, CardContent, CardHeader, CardTitle } from '@/shared/components/ui/Card';
import { Button } from '@/shared/components/ui/Button';
import { Input } from '@/shared/components/ui/Input';
import { Label } from '@/shared/components/ui/Label';
import { Select } from '@/shared/components/ui/Select';
import { PageLoader } from '@/shared/components/PageLoader';
import { PageError } from '@/shared/components/PageError';
import { todayDisplayDayKey } from '@/utils/timezone';

/** Records a Main Stock receipt against an item — the only way
 * InventoryItem.main_stock_level ever increases (see backend/app/
 * modules/inventory/models.py's InventoryMainStockReceipt docstring).
 * Inactive items are excluded from the picker — receiving stock for an
 * item nobody can dispense makes no sense, and the backend rejects it
 * outright regardless (InventoryItemInactiveError). */
export function InventoryReceivePanel() {
  const { data: items, isLoading, isError, error, refetch } = useInventoryItems();
  const receiveStock = useReceiveStock();
  const [submitError, setSubmitError] = useState(null);
  const [successItemName, setSuccessItemName] = useState(null);
  const {
    register,
    handleSubmit,
    reset,
    formState: { errors, isSubmitting },
  } = useForm({
    resolver: zodResolver(receiveStockFormSchema),
    defaultValues: { item_id: '', quantity: '', received_on: todayDisplayDayKey() },
  });

  const activeItems = (items ?? []).filter((item) => item.is_active);

  async function onSubmit(values) {
    setSubmitError(null);
    setSuccessItemName(null);
    try {
      const updatedItem = await receiveStock.mutateAsync({
        itemId: values.item_id,
        payload: { quantity: values.quantity, received_on: values.received_on },
      });
      setSuccessItemName(updatedItem.data.name);
      reset({ item_id: '', quantity: '', received_on: values.received_on });
    } catch (submitErr) {
      setSubmitError(submitErr.message || 'Unable to record this receipt.');
    }
  }

  if (isLoading) return <PageLoader label="Loading items" />;
  if (isError) {
    return <PageError error={error} reset={refetch} message="Couldn't load the item catalog." />;
  }

  return (
    <Card>
      <CardHeader>
        <CardTitle>Record a Main Stock Receipt</CardTitle>
      </CardHeader>
      <CardContent>
        {activeItems.length === 0 ? (
          <p className="text-sm text-muted-foreground">
            No active items in the catalog yet — add one under Catalog first.
          </p>
        ) : (
          <form
            onSubmit={handleSubmit(onSubmit)}
            className="flex flex-col gap-4 sm:flex-row sm:flex-wrap sm:items-end"
          >
            <div className="flex min-w-[220px] flex-1 flex-col gap-1.5">
              <Label htmlFor="item_id">Item</Label>
              <Select id="item_id" {...register('item_id')}>
                <option value="">Select an item…</option>
                {activeItems.map((item) => (
                  <option key={item.id} value={item.id}>
                    {item.name} ({item.unit})
                  </option>
                ))}
              </Select>
              {errors.item_id ? (
                <p className="text-xs text-destructive">{errors.item_id.message}</p>
              ) : null}
            </div>
            <div className="flex flex-col gap-1.5">
              <Label htmlFor="quantity">Quantity</Label>
              <Input id="quantity" type="number" step="0.01" min="0" {...register('quantity')} />
              {errors.quantity ? (
                <p className="text-xs text-destructive">{errors.quantity.message}</p>
              ) : null}
            </div>
            <div className="flex flex-col gap-1.5">
              <Label htmlFor="received_on">Received On</Label>
              <Input id="received_on" type="date" {...register('received_on')} />
              {errors.received_on ? (
                <p className="text-xs text-destructive">{errors.received_on.message}</p>
              ) : null}
            </div>
            <Button type="submit" disabled={isSubmitting}>
              <PackagePlus className="h-4 w-4" />
              {isSubmitting ? 'Recording…' : 'Record Receipt'}
            </Button>
          </form>
        )}
        {submitError ? (
          <p className="mt-3 rounded-md bg-destructive/10 px-3 py-2 text-sm text-destructive">
            {submitError}
          </p>
        ) : null}
        {successItemName ? (
          <p className="mt-3 rounded-md bg-emerald-50 px-3 py-2 text-sm text-emerald-700">
            Receipt recorded for {successItemName}.
          </p>
        ) : null}
      </CardContent>
    </Card>
  );
}
