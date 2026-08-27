'use client';

import { useState } from 'react';
import { useForm } from 'react-hook-form';
import { zodResolver } from '@hookform/resolvers/zod';
import { ArrowRightLeft } from 'lucide-react';
import { inventoryService } from '@/features/inventory/api/inventoryService';
import { useInventoryItems, useTransferStock } from '@/features/inventory/hooks/useInventory';
import { transferStockFormSchema } from '@/features/inventory/schemas/inventorySchemas';
import { Card, CardContent, CardHeader, CardTitle } from '@/shared/components/ui/Card';
import { Button } from '@/shared/components/ui/Button';
import { Input } from '@/shared/components/ui/Input';
import { Label } from '@/shared/components/ui/Label';
import { SearchSelect } from '@/shared/components/SearchSelect';
import { PageLoader } from '@/shared/components/PageLoader';
import { PageError } from '@/shared/components/PageError';
import { todayDisplayDayKey } from '@/utils/timezone';

/** Records a Main Stock -> Emergency Stock transfer — the only way
 * emergency_stock_level increases (see backend/app/modules/inventory/
 * models.py's InventoryTransfer docstring). Shows the selected item's
 * current Main Stock level right on the form so the Inventory Manager
 * can see how much room there is before the backend's own
 * InsufficientMainStockError would reject an over-large transfer. */
export function InventoryTransferPanel() {
  const { data: items, isLoading, isError, error, refetch } = useInventoryItems();
  const transferStock = useTransferStock();
  const [selectedItem, setSelectedItem] = useState(null);
  const [submitError, setSubmitError] = useState(null);
  const [successItemName, setSuccessItemName] = useState(null);
  const {
    register,
    handleSubmit,
    reset,
    setValue,
    formState: { errors, isSubmitting },
  } = useForm({
    resolver: zodResolver(transferStockFormSchema),
    defaultValues: { item_id: '', quantity: '', transferred_on: todayDisplayDayKey() },
  });

  const activeItems = (items ?? []).filter((item) => item.is_active);

  async function onSubmit(values) {
    setSubmitError(null);
    setSuccessItemName(null);
    try {
      const updatedItem = await transferStock.mutateAsync({
        itemId: values.item_id,
        payload: { quantity: values.quantity, transferred_on: values.transferred_on },
      });
      setSuccessItemName(updatedItem.data.name);
      setSelectedItem(null);
      reset({ item_id: '', quantity: '', transferred_on: values.transferred_on });
    } catch (submitErr) {
      setSubmitError(submitErr.message || 'Unable to record this transfer.');
    }
  }

  if (isLoading) return <PageLoader label="Loading items" />;
  if (isError) {
    return <PageError error={error} reset={refetch} message="Couldn't load the item catalog." />;
  }

  return (
    <Card>
      <CardHeader>
        <CardTitle>Transfer to Emergency Stock</CardTitle>
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
              <Label>Item</Label>
              <SearchSelect
                queryKey={['inventory', 'items', 'search']}
                queryFn={(term) => inventoryService.searchItems(term).then((res) => res.data)}
                getLabel={(item) => item.name}
                getDescription={(item) => `${item.unit} — ${item.main_stock_level} in Main Stock`}
                placeholder="Search item by name"
                selectedLabel={selectedItem ? selectedItem.name : ''}
                onSelect={(item) => {
                  setSelectedItem(item);
                  setValue('item_id', item.id, { shouldValidate: true });
                }}
              />
              {errors.item_id ? (
                <p className="text-xs text-destructive">{errors.item_id.message}</p>
              ) : null}
              {selectedItem ? (
                <p className="text-xs text-muted-foreground">
                  Main Stock available: {selectedItem.main_stock_level} {selectedItem.unit}
                </p>
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
              <Label htmlFor="transferred_on">Transferred On</Label>
              <Input id="transferred_on" type="date" {...register('transferred_on')} />
              {errors.transferred_on ? (
                <p className="text-xs text-destructive">{errors.transferred_on.message}</p>
              ) : null}
            </div>
            <Button type="submit" disabled={isSubmitting}>
              <ArrowRightLeft className="h-4 w-4" />
              {isSubmitting ? 'Transferring…' : 'Transfer to Emergency'}
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
            Transfer recorded for {successItemName}.
          </p>
        ) : null}
      </CardContent>
    </Card>
  );
}
