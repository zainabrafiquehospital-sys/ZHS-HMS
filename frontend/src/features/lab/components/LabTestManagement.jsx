'use client';

import { useEffect, useState } from 'react';
import { useForm } from 'react-hook-form';
import { zodResolver } from '@hookform/resolvers/zod';
import { Pencil, PlusCircle, PowerOff, Power } from 'lucide-react';
import { useLabTests, useCreateLabTest, useUpdateLabTest } from '@/features/lab/hooks/useLab';
import { labTestFormSchema, LAB_TEST_CATEGORIES } from '@/features/lab/schemas/labSchemas';
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

const EMPTY_VALUES = { name: '', category: '', price: '' };

/** Doubles as the "Add Test" and "Edit Test" form — `editing` (a
 * LabTestOut, or null) picks which mode it's in — mirrors
 * MedicineFormPanel (features/pharmacy/components/MedicineManagement.jsx)
 * exactly, `unit_price` renamed `price` to match LabTest's own field
 * name (see app/modules/lab/models.py's LabTest docstring). */
function LabTestFormPanel({ editing, onDoneEditing }) {
  const createTest = useCreateLabTest();
  const updateTest = useUpdateLabTest();
  const [submitError, setSubmitError] = useState(null);
  const {
    register,
    handleSubmit,
    reset,
    formState: { errors, isSubmitting },
  } = useForm({
    resolver: zodResolver(labTestFormSchema),
    defaultValues: EMPTY_VALUES,
  });

  useEffect(() => {
    if (editing) {
      reset({
        name: editing.name,
        category: editing.category,
        price: editing.price,
      });
    } else {
      reset(EMPTY_VALUES);
    }
  }, [editing, reset]);

  async function onSubmit(values) {
    setSubmitError(null);
    try {
      if (editing) {
        await updateTest.mutateAsync({ labTestId: editing.id, payload: values });
        onDoneEditing?.();
      } else {
        await createTest.mutateAsync(values);
        reset(EMPTY_VALUES);
      }
    } catch (error) {
      setSubmitError(error.message || 'Unable to save this lab test.');
    }
  }

  return (
    <Card>
      <CardHeader>
        <CardTitle>{editing ? `Edit ${editing.name}` : 'Add Test'}</CardTitle>
      </CardHeader>
      <CardContent>
        <form
          onSubmit={handleSubmit(onSubmit)}
          className="flex flex-col gap-4 sm:flex-row sm:flex-wrap sm:items-end"
        >
          <div className="flex min-w-[180px] flex-1 flex-col gap-1.5">
            <Label htmlFor="name">Test Name</Label>
            <Input id="name" {...register('name')} />
            {errors.name ? <p className="text-xs text-destructive">{errors.name.message}</p> : null}
          </div>
          <div className="flex flex-col gap-1.5">
            <Label htmlFor="category">Category</Label>
            <Select id="category" {...register('category')}>
              <option value="">Select…</option>
              {LAB_TEST_CATEGORIES.map((category) => (
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
            <Label htmlFor="price">Price (Rs.)</Label>
            <Input id="price" type="number" step="0.01" min="0" {...register('price')} />
            {errors.price ? <p className="text-xs text-destructive">{errors.price.message}</p> : null}
          </div>
          <div className="flex gap-2">
            <Button type="submit" disabled={isSubmitting}>
              <PlusCircle className="h-4 w-4" />
              {isSubmitting ? 'Saving…' : editing ? 'Save Changes' : 'Add Test'}
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

function LabTestsListPanel({ tests, onEdit }) {
  const updateTest = useUpdateLabTest();
  const [toggleError, setToggleError] = useState(null);

  async function handleToggleActive(test) {
    setToggleError(null);
    try {
      await updateTest.mutateAsync({
        labTestId: test.id,
        payload: { is_active: !test.is_active },
      });
    } catch (error) {
      setToggleError(error.message || 'Unable to update this lab test.');
    }
  }

  return (
    <Card>
      <CardHeader>
        <CardTitle>Lab Test Price List</CardTitle>
      </CardHeader>
      <CardContent className="flex flex-col gap-4">
        {tests.length === 0 ? (
          <p className="text-sm text-muted-foreground">No lab tests added yet.</p>
        ) : (
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>Name</TableHead>
                <TableHead>Category</TableHead>
                <TableHead className="text-right">Price</TableHead>
                <TableHead>Status</TableHead>
                <TableHead />
              </TableRow>
            </TableHeader>
            <TableBody>
              {tests.map((test) => (
                <TableRow key={test.id}>
                  <TableCell className="font-medium text-foreground">{test.name}</TableCell>
                  <TableCell className="capitalize">{test.category}</TableCell>
                  <TableCell className="text-right tabular-nums">{money(test.price)}</TableCell>
                  <TableCell>
                    <Badge variant={test.is_active ? 'success' : 'outline'}>
                      {test.is_active ? 'Active' : 'Inactive'}
                    </Badge>
                  </TableCell>
                  <TableCell>
                    <div className="flex justify-end gap-2">
                      <Button size="sm" variant="outline" onClick={() => onEdit(test)}>
                        <Pencil className="h-4 w-4" />
                        Edit
                      </Button>
                      <Button
                        size="sm"
                        variant="ghost"
                        onClick={() => handleToggleActive(test)}
                        disabled={updateTest.isPending}
                      >
                        {test.is_active ? (
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

export function LabTestManagement() {
  const { data: tests, isLoading, isError, error, refetch } = useLabTests();
  const [editing, setEditing] = useState(null);

  return (
    <div className="flex flex-col gap-6">
      <div className="flex flex-col gap-1">
        <h1 className="text-lg font-semibold text-foreground">Lab Test Price List</h1>
        <p className="text-sm text-muted-foreground">
          Manage the lab tests Reception can bill — no stock/quantity tracking, price only.
        </p>
      </div>

      <LabTestFormPanel editing={editing} onDoneEditing={() => setEditing(null)} />

      {isLoading ? (
        <PageLoader label="Loading lab tests" />
      ) : isError ? (
        <PageError error={error} reset={refetch} message="Couldn't load the lab test list." />
      ) : (
        <LabTestsListPanel tests={tests ?? []} onEdit={setEditing} />
      )}
    </div>
  );
}
