'use client';

import { useState } from 'react';
import { useForm } from 'react-hook-form';
import { zodResolver } from '@hookform/resolvers/zod';
import { Bell } from 'lucide-react';
import {
  useInventoryItems,
  useRaiseInventoryRestockRequest,
} from '@/features/inventory/hooks/useInventory';
import { raiseRestockRequestFormSchema } from '@/features/inventory/schemas/inventorySchemas';
import { Card, CardContent, CardHeader, CardTitle } from '@/shared/components/ui/Card';
import { Button } from '@/shared/components/ui/Button';
import { Input } from '@/shared/components/ui/Input';
import { Label } from '@/shared/components/ui/Label';
import { Select } from '@/shared/components/ui/Select';
import { Textarea } from '@/shared/components/ui/Textarea';
import { Badge } from '@/shared/components/ui/Badge';
import { PageLoader } from '@/shared/components/PageLoader';
import { PageError } from '@/shared/components/PageError';

/** Raises a restock request against a low/out Emergency Stock item —
 * `requested_quantity` is optional (confirmed design: "just flag it
 * low" with no specific number is a legitimate request, see backend/
 * app/modules/inventory/models.py's InventoryRestockRequest docstring).
 * Every item (not just active ones) can be flagged here — an item
 * someone just deactivated by mistake is exactly the kind of thing
 * worth surfacing to the Inventory Manager, not hidden from this
 * picker. */
export function RaiseRestockRequestForm() {
  const { data: items, isLoading, isError, error, refetch } = useInventoryItems();
  const raiseRequest = useRaiseInventoryRestockRequest();
  const [submitError, setSubmitError] = useState(null);
  const [successMessage, setSuccessMessage] = useState(null);
  const {
    register,
    handleSubmit,
    reset,
    watch,
    formState: { errors, isSubmitting },
  } = useForm({
    resolver: zodResolver(raiseRestockRequestFormSchema),
    defaultValues: { item_id: '', requested_quantity: '', note: '' },
  });

  const selectedItem = (items ?? []).find((item) => item.id === watch('item_id'));

  async function onSubmit(values) {
    setSubmitError(null);
    setSuccessMessage(null);
    try {
      await raiseRequest.mutateAsync(values);
      setSuccessMessage('Restock request raised — the Inventory Manager has been notified.');
      reset({ item_id: '', requested_quantity: '', note: '' });
    } catch (submitErr) {
      setSubmitError(submitErr.message || 'Unable to raise this restock request.');
    }
  }

  if (isLoading) return <PageLoader label="Loading items" />;
  if (isError) {
    return <PageError error={error} reset={refetch} message="Couldn't load the item catalog." />;
  }

  return (
    <Card>
      <CardHeader>
        <CardTitle>Raise a Restock Request</CardTitle>
      </CardHeader>
      <CardContent>
        <form onSubmit={handleSubmit(onSubmit)} className="flex flex-col gap-4">
          <div className="flex flex-col gap-4 sm:flex-row sm:flex-wrap sm:items-end">
            <div className="flex min-w-[220px] flex-1 flex-col gap-1.5">
              <Label htmlFor="restock_item_id">Item</Label>
              <Select id="restock_item_id" {...register('item_id')}>
                <option value="">Select an item…</option>
                {(items ?? []).map((item) => (
                  <option key={item.id} value={item.id}>
                    {item.name} ({item.unit})
                  </option>
                ))}
              </Select>
              {errors.item_id ? (
                <p className="text-xs text-destructive">{errors.item_id.message}</p>
              ) : null}
              {selectedItem ? (
                <p className="text-xs text-muted-foreground">
                  Emergency Stock available: {selectedItem.emergency_stock_level} {selectedItem.unit}
                  {selectedItem.is_low_stock ? (
                    <Badge variant="warning" className="ml-2">
                      Low
                    </Badge>
                  ) : null}
                </p>
              ) : null}
            </div>
            <div className="flex flex-col gap-1.5">
              <Label htmlFor="restock_requested_quantity">Requested Quantity (optional)</Label>
              <Input
                id="restock_requested_quantity"
                type="number"
                step="0.01"
                min="0"
                placeholder="Manager's judgment"
                {...register('requested_quantity')}
              />
              {errors.requested_quantity ? (
                <p className="text-xs text-destructive">{errors.requested_quantity.message}</p>
              ) : null}
            </div>
          </div>
          <div className="flex flex-col gap-1.5">
            <Label htmlFor="restock_note">Note (optional)</Label>
            <Textarea id="restock_note" {...register('note')} />
          </div>
          <div>
            <Button type="submit" disabled={isSubmitting}>
              <Bell className="h-4 w-4" />
              {isSubmitting ? 'Raising…' : 'Raise Request'}
            </Button>
          </div>
        </form>
        {submitError ? (
          <p className="mt-3 rounded-md bg-destructive/10 px-3 py-2 text-sm text-destructive">
            {submitError}
          </p>
        ) : null}
        {successMessage ? (
          <p className="mt-3 rounded-md bg-emerald-50 px-3 py-2 text-sm text-emerald-700">
            {successMessage}
          </p>
        ) : null}
      </CardContent>
    </Card>
  );
}
