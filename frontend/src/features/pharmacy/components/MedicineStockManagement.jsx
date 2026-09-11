'use client';

import { useState } from 'react';
import { useForm } from 'react-hook-form';
import { zodResolver } from '@hookform/resolvers/zod';
import { PackagePlus } from 'lucide-react';
import { useAddMedicineStock, useMedicines } from '@/features/pharmacy/hooks/usePharmacy';
import { addMedicineStockSchema } from '@/features/pharmacy/schemas/pharmacySchemas';
import { Card, CardContent, CardHeader, CardTitle } from '@/shared/components/ui/Card';
import { Badge } from '@/shared/components/ui/Badge';
import { Button } from '@/shared/components/ui/Button';
import { ConfirmDialog } from '@/shared/components/ui/ConfirmDialog';
import { Input } from '@/shared/components/ui/Input';
import { Label } from '@/shared/components/ui/Label';
import { PageLoader } from '@/shared/components/PageLoader';
import { PageError } from '@/shared/components/PageError';
import { useToast } from '@/shared/components/toast/ToastProvider';
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from '@/shared/components/ui/Table';

function money(amount) {
  return `Rs. ${Number(amount).toFixed(2)}`;
}

/** The stock cell's status: "Out of stock" at 0, "Low" at/below the
 * global threshold (backend sends `is_low_stock`), otherwise nothing. */
function StockBadge({ medicine }) {
  if (medicine.stock_quantity <= 0) {
    return <Badge variant="destructive">Out of stock</Badge>;
  }
  if (medicine.is_low_stock) {
    return <Badge variant="warning">Low</Badge>;
  }
  return null;
}

/** Per-row "Add Stock" — an additive "received N more units" action
 * (never "set stock to N"). Reuses `ConfirmDialog` + a validated
 * quantity input, the same shape AdminOverview's own
 * RecordBillPaymentDialog uses. */
function AddStockDialog({ medicine, onClose }) {
  const { toast } = useToast();
  const addStock = useAddMedicineStock();
  const [error, setError] = useState(null);
  const {
    register,
    handleSubmit,
    formState: { errors, isSubmitting },
  } = useForm({
    resolver: zodResolver(addMedicineStockSchema),
    defaultValues: { quantity: '' },
  });

  async function onSubmit(values) {
    setError(null);
    try {
      const updated = await addStock.mutateAsync({
        medicineId: medicine.id,
        quantity: values.quantity,
      });
      toast.success({
        title: 'Stock added',
        description: `${medicine.name} — now ${updated.data.stock_quantity} in stock`,
      });
      onClose();
    } catch (submitError) {
      setError(submitError.message || 'Unable to add stock.');
    }
  }

  return (
    <ConfirmDialog
      open
      title={`Add Stock — ${medicine.name}`}
      confirmLabel={isSubmitting ? 'Adding…' : 'Add Stock'}
      cancelLabel="Cancel"
      onCancel={onClose}
      onConfirm={handleSubmit(onSubmit)}
      description={
        <div className="flex flex-col gap-3">
          <p className="text-sm text-muted-foreground">
            Currently {medicine.stock_quantity} in stock. Enter how many units were received —
            this is added to the current count, not a replacement value.
          </p>
          <div className="flex flex-col gap-1.5">
            <Label htmlFor="add-stock-quantity">Units received</Label>
            <Input
              id="add-stock-quantity"
              type="number"
              min="1"
              step="1"
              {...register('quantity')}
            />
            {errors.quantity ? (
              <p className="text-xs text-destructive">{errors.quantity.message}</p>
            ) : null}
          </div>
          {error ? <p className="text-xs text-destructive">{error}</p> : null}
        </div>
      }
    />
  );
}

export function MedicineStockManagement() {
  const { data: medicines, isLoading, isError, error, refetch } = useMedicines();
  const [addingStockFor, setAddingStockFor] = useState(null);

  const rows = medicines ?? [];
  const lowCount = rows.filter((m) => m.is_active && m.is_low_stock).length;

  return (
    <div className="flex flex-col gap-6">
      <div className="flex flex-col gap-1">
        <h1 className="text-lg font-semibold text-foreground">Medicine Stock</h1>
        <p className="text-sm text-muted-foreground">
          On-hand dispensing stock for every medicine. Add received units per row — the price
          list itself is managed separately under Medicines.
        </p>
      </div>

      {isLoading ? (
        <PageLoader label="Loading medicine stock" />
      ) : isError ? (
        <PageError error={error} reset={refetch} message="Couldn't load the medicine list." />
      ) : (
        <Card>
          <CardHeader className="flex-row items-center justify-between gap-2">
            <CardTitle>All Medicines</CardTitle>
            {lowCount > 0 ? (
              <Badge variant="warning">
                {lowCount} low on stock
              </Badge>
            ) : null}
          </CardHeader>
          <CardContent>
            {rows.length === 0 ? (
              <p className="text-sm text-muted-foreground">No medicines added yet.</p>
            ) : (
              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead>Name</TableHead>
                    <TableHead>Category</TableHead>
                    <TableHead className="text-right">Unit Price</TableHead>
                    <TableHead className="text-right">In Stock</TableHead>
                    <TableHead>Status</TableHead>
                    <TableHead />
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {rows.map((medicine) => (
                    <TableRow key={medicine.id}>
                      <TableCell className="font-medium text-foreground">
                        {medicine.name}
                        {!medicine.is_active ? (
                          <Badge variant="outline" className="ml-2">
                            Inactive
                          </Badge>
                        ) : null}
                      </TableCell>
                      <TableCell className="capitalize">{medicine.category}</TableCell>
                      <TableCell className="text-right tabular-nums">
                        {money(medicine.unit_price)}
                      </TableCell>
                      <TableCell className="text-right font-semibold tabular-nums">
                        {medicine.stock_quantity}
                      </TableCell>
                      <TableCell>
                        <StockBadge medicine={medicine} />
                      </TableCell>
                      <TableCell>
                        <div className="flex justify-end">
                          <Button
                            size="sm"
                            variant="outline"
                            onClick={() => setAddingStockFor(medicine)}
                          >
                            <PackagePlus className="h-4 w-4" />
                            Add Stock
                          </Button>
                        </div>
                      </TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
            )}
          </CardContent>
        </Card>
      )}

      {addingStockFor ? (
        <AddStockDialog medicine={addingStockFor} onClose={() => setAddingStockFor(null)} />
      ) : null}
    </div>
  );
}
