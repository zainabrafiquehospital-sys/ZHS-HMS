'use client';

import { useEffect, useState } from 'react';
import { useForm } from 'react-hook-form';
import { zodResolver } from '@hookform/resolvers/zod';
import { Pencil, PlusCircle, PowerOff, Power } from 'lucide-react';
import {
  useMedicines,
  useCreateMedicine,
  useUpdateMedicine,
} from '@/features/pharmacy/hooks/usePharmacy';
import {
  medicineFormSchema,
  MEDICINE_CATEGORIES,
} from '@/features/pharmacy/schemas/pharmacySchemas';
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

function money(amount) {
  return `Rs. ${Number(amount).toFixed(2)}`;
}

const EMPTY_VALUES = { name: '', category: '', unit_price: '' };

/** Doubles as the "Add Medicine" and "Edit Medicine" form — `editing`
 * (a MedicineOut, or null) picks which mode it's in, the same
 * form-per-screen composite-file convention as
 * features/billing/components/BillingWorkspace.jsx's own sub-panels. */
function MedicineFormPanel({ editing, onDoneEditing }) {
  const createMedicine = useCreateMedicine();
  const updateMedicine = useUpdateMedicine();
  const [submitError, setSubmitError] = useState(null);
  const {
    register,
    handleSubmit,
    reset,
    formState: { errors, isSubmitting },
  } = useForm({
    resolver: zodResolver(medicineFormSchema),
    defaultValues: EMPTY_VALUES,
  });

  useEffect(() => {
    if (editing) {
      reset({
        name: editing.name,
        category: editing.category,
        unit_price: editing.unit_price,
      });
    } else {
      reset(EMPTY_VALUES);
    }
  }, [editing, reset]);

  async function onSubmit(values) {
    setSubmitError(null);
    try {
      if (editing) {
        await updateMedicine.mutateAsync({ medicineId: editing.id, payload: values });
        onDoneEditing?.();
      } else {
        await createMedicine.mutateAsync(values);
        reset(EMPTY_VALUES);
      }
    } catch (error) {
      setSubmitError(error.message || 'Unable to save this medicine.');
    }
  }

  return (
    <Card>
      <CardHeader>
        <CardTitle>{editing ? `Edit ${editing.name}` : 'Add Medicine'}</CardTitle>
      </CardHeader>
      <CardContent>
        <form
          onSubmit={handleSubmit(onSubmit)}
          className="flex flex-col gap-4 sm:flex-row sm:flex-wrap sm:items-end"
        >
          <div className="flex min-w-[180px] flex-1 flex-col gap-1.5">
            <Label htmlFor="name">Medicine Name</Label>
            <Input id="name" {...register('name')} />
            {errors.name ? <p className="text-xs text-destructive">{errors.name.message}</p> : null}
          </div>
          <div className="flex flex-col gap-1.5">
            <Label htmlFor="category">Category</Label>
            <Select id="category" {...register('category')}>
              <option value="">Select…</option>
              {MEDICINE_CATEGORIES.map((category) => (
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
            <Label htmlFor="unit_price">Unit Price (Rs.)</Label>
            <Input id="unit_price" type="number" step="0.01" min="0" {...register('unit_price')} />
            {errors.unit_price ? (
              <p className="text-xs text-destructive">{errors.unit_price.message}</p>
            ) : null}
          </div>
          <div className="flex gap-2">
            <Button type="submit" disabled={isSubmitting}>
              <PlusCircle className="h-4 w-4" />
              {isSubmitting ? 'Saving…' : editing ? 'Save Changes' : 'Add Medicine'}
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

function MedicinesListPanel({ medicines, onEdit }) {
  const updateMedicine = useUpdateMedicine();
  const [toggleError, setToggleError] = useState(null);

  async function handleToggleActive(medicine) {
    setToggleError(null);
    try {
      await updateMedicine.mutateAsync({
        medicineId: medicine.id,
        payload: { is_active: !medicine.is_active },
      });
    } catch (error) {
      setToggleError(error.message || 'Unable to update this medicine.');
    }
  }

  return (
    <Card>
      <CardHeader>
        <CardTitle>Medicine Price List</CardTitle>
      </CardHeader>
      <CardContent className="flex flex-col gap-4">
        {medicines.length === 0 ? (
          <p className="text-sm text-muted-foreground">No medicines added yet.</p>
        ) : (
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>Name</TableHead>
                <TableHead>Category</TableHead>
                <TableHead className="text-right">Unit Price</TableHead>
                <TableHead>Status</TableHead>
                <TableHead />
              </TableRow>
            </TableHeader>
            <TableBody>
              {medicines.map((medicine) => (
                <TableRow key={medicine.id}>
                  <TableCell className="font-medium text-foreground">{medicine.name}</TableCell>
                  <TableCell className="capitalize">{medicine.category}</TableCell>
                  <TableCell className="text-right tabular-nums">
                    {money(medicine.unit_price)}
                  </TableCell>
                  <TableCell>
                    <Badge variant={medicine.is_active ? 'success' : 'outline'}>
                      {medicine.is_active ? 'Active' : 'Inactive'}
                    </Badge>
                  </TableCell>
                  <TableCell>
                    <div className="flex justify-end gap-2">
                      <Button size="sm" variant="outline" onClick={() => onEdit(medicine)}>
                        <Pencil className="h-4 w-4" />
                        Edit
                      </Button>
                      <Button
                        size="sm"
                        variant="ghost"
                        onClick={() => handleToggleActive(medicine)}
                        disabled={updateMedicine.isPending}
                      >
                        {medicine.is_active ? (
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

export function MedicineManagement() {
  const { data: medicines, isLoading, isError, error, refetch } = useMedicines();
  const [editing, setEditing] = useState(null);

  return (
    <div className="flex flex-col gap-6">
      <div className="flex flex-col gap-1">
        <h1 className="text-lg font-semibold text-foreground">Medicine Price List</h1>
        <p className="text-sm text-muted-foreground">
          Manage the medicines Reception can bill — no stock/quantity tracking, price only.
        </p>
      </div>

      <MedicineFormPanel editing={editing} onDoneEditing={() => setEditing(null)} />

      {isLoading ? (
        <PageLoader label="Loading medicines" />
      ) : isError ? (
        <PageError error={error} reset={refetch} message="Couldn't load the medicine list." />
      ) : (
        <MedicinesListPanel medicines={medicines ?? []} onEdit={setEditing} />
      )}
    </div>
  );
}
