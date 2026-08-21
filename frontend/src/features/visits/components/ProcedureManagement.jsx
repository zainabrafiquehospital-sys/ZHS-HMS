'use client';

import { useEffect, useState } from 'react';
import { useForm } from 'react-hook-form';
import { zodResolver } from '@hookform/resolvers/zod';
import { Pencil, PlusCircle, PowerOff, Power, Trash2 } from 'lucide-react';
import {
  useProcedures,
  useCreateProcedure,
  useUpdateProcedure,
  useDeleteProcedure,
} from '@/features/visits/hooks/useProcedures';
import { procedureFormSchema } from '@/features/visits/schemas/procedureSchemas';
import { Card, CardContent, CardHeader, CardTitle } from '@/shared/components/ui/Card';
import { Button } from '@/shared/components/ui/Button';
import { Input } from '@/shared/components/ui/Input';
import { Label } from '@/shared/components/ui/Label';
import { Badge } from '@/shared/components/ui/Badge';
import { ConfirmDialog } from '@/shared/components/ui/ConfirmDialog';
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

const EMPTY_VALUES = { name: '', price: '' };

/** Doubles as the "Add Procedure" and "Edit Procedure" form — `editing`
 * (a ProcedureOut, or null) picks which mode it's in — mirrors
 * features/pharmacy/components/MedicineManagement.jsx's identical
 * `MedicineFormPanel` shape exactly, minus category. */
function ProcedureFormPanel({ editing, onDoneEditing }) {
  const createProcedure = useCreateProcedure();
  const updateProcedure = useUpdateProcedure();
  const [submitError, setSubmitError] = useState(null);
  const {
    register,
    handleSubmit,
    reset,
    formState: { errors, isSubmitting },
  } = useForm({
    resolver: zodResolver(procedureFormSchema),
    defaultValues: EMPTY_VALUES,
  });

  useEffect(() => {
    if (editing) {
      reset({ name: editing.name, price: editing.price });
    } else {
      reset(EMPTY_VALUES);
    }
  }, [editing, reset]);

  async function onSubmit(values) {
    setSubmitError(null);
    try {
      if (editing) {
        await updateProcedure.mutateAsync({ procedureId: editing.id, payload: values });
        onDoneEditing?.();
      } else {
        await createProcedure.mutateAsync(values);
        reset(EMPTY_VALUES);
      }
    } catch (error) {
      setSubmitError(error.message || 'Unable to save this procedure.');
    }
  }

  return (
    <Card>
      <CardHeader>
        <CardTitle>{editing ? `Edit ${editing.name}` : 'Add Procedure'}</CardTitle>
      </CardHeader>
      <CardContent>
        <form
          onSubmit={handleSubmit(onSubmit)}
          className="flex flex-col gap-4 sm:flex-row sm:flex-wrap sm:items-end"
        >
          <div className="flex min-w-[220px] flex-1 flex-col gap-1.5">
            <Label htmlFor="name">Procedure Name</Label>
            <Input id="name" {...register('name')} />
            {errors.name ? <p className="text-xs text-destructive">{errors.name.message}</p> : null}
          </div>
          <div className="flex flex-col gap-1.5">
            <Label htmlFor="price">Price (Rs.)</Label>
            <Input id="price" type="number" step="0.01" min="0" {...register('price')} />
            {errors.price ? (
              <p className="text-xs text-destructive">{errors.price.message}</p>
            ) : null}
          </div>
          <div className="flex gap-2">
            <Button type="submit" disabled={isSubmitting}>
              <PlusCircle className="h-4 w-4" />
              {isSubmitting ? 'Saving…' : editing ? 'Save Changes' : 'Add Procedure'}
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

/** Admin-only delete (2026-08-21 addition) — a real, destructive-
 * feeling action Medicine's own catalog doesn't have (activate/
 * deactivate only there), so this is a full ConfirmDialog with an
 * explicit description, never a single-click button — same discipline
 * as every other destructive confirm in this codebase (e.g.
 * AdminOverview.jsx's DeleteVisitDialog). Safe regardless of whether
 * this procedure has ever been selected for a visit — see
 * backend/app/modules/visits/models.py's `Procedure` docstring. */
function DeleteProcedureDialog({ procedure, onClose }) {
  const deleteProcedure = useDeleteProcedure();
  const [error, setError] = useState(null);

  async function handleConfirm() {
    setError(null);
    try {
      await deleteProcedure.mutateAsync(procedure.id);
      onClose();
    } catch (deleteError) {
      setError(deleteError.message || 'Unable to delete this procedure.');
    }
  }

  return (
    <ConfirmDialog
      open
      variant="destructive"
      title={`Delete ${procedure.name}?`}
      confirmLabel={deleteProcedure.isPending ? 'Deleting…' : 'Delete Procedure'}
      cancelLabel="Cancel"
      onCancel={onClose}
      onConfirm={handleConfirm}
      description={
        <div className="flex flex-col gap-2">
          <p>
            This removes {procedure.name} from the catalog entirely — it will no longer be
            selectable when registering a new visit. Any visit that already used it keeps its own
            record of the name and price exactly as billed, unaffected by this.
          </p>
          {error ? <p className="text-destructive">{error}</p> : null}
        </div>
      }
    />
  );
}

function ProceduresListPanel({ procedures, onEdit, onDelete }) {
  const updateProcedure = useUpdateProcedure();
  const [toggleError, setToggleError] = useState(null);

  async function handleToggleActive(procedure) {
    setToggleError(null);
    try {
      await updateProcedure.mutateAsync({
        procedureId: procedure.id,
        payload: { is_active: !procedure.is_active },
      });
    } catch (error) {
      setToggleError(error.message || 'Unable to update this procedure.');
    }
  }

  return (
    <Card>
      <CardHeader>
        <CardTitle>Procedure Catalog</CardTitle>
      </CardHeader>
      <CardContent className="flex flex-col gap-4">
        {procedures.length === 0 ? (
          <p className="text-sm text-muted-foreground">No procedures added yet.</p>
        ) : (
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>Name</TableHead>
                <TableHead className="text-right">Price</TableHead>
                <TableHead>Status</TableHead>
                <TableHead />
              </TableRow>
            </TableHeader>
            <TableBody>
              {procedures.map((procedure) => (
                <TableRow key={procedure.id}>
                  <TableCell className="font-medium text-foreground">{procedure.name}</TableCell>
                  <TableCell className="text-right tabular-nums">
                    {money(procedure.price)}
                  </TableCell>
                  <TableCell>
                    <Badge variant={procedure.is_active ? 'success' : 'outline'}>
                      {procedure.is_active ? 'Active' : 'Inactive'}
                    </Badge>
                  </TableCell>
                  <TableCell>
                    <div className="flex justify-end gap-2">
                      <Button size="sm" variant="outline" onClick={() => onEdit(procedure)}>
                        <Pencil className="h-4 w-4" />
                        Edit
                      </Button>
                      <Button
                        size="sm"
                        variant="ghost"
                        onClick={() => handleToggleActive(procedure)}
                        disabled={updateProcedure.isPending}
                      >
                        {procedure.is_active ? (
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
                      <Button size="sm" variant="ghost" onClick={() => onDelete(procedure)}>
                        <Trash2 className="h-4 w-4" />
                        Delete
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

export function ProcedureManagement() {
  const { data: procedures, isLoading, isError, error, refetch } = useProcedures();
  const [editing, setEditing] = useState(null);
  const [deleting, setDeleting] = useState(null);

  return (
    <div className="flex flex-col gap-6">
      <div className="flex flex-col gap-1">
        <h1 className="text-lg font-semibold text-foreground">Procedure Catalog</h1>
        <p className="text-sm text-muted-foreground">
          Manage the procedures Reception can select when registering a visit.
        </p>
      </div>

      <ProcedureFormPanel editing={editing} onDoneEditing={() => setEditing(null)} />

      {isLoading ? (
        <PageLoader label="Loading procedures" />
      ) : isError ? (
        <PageError error={error} reset={refetch} message="Couldn't load the procedure catalog." />
      ) : (
        <ProceduresListPanel
          procedures={procedures ?? []}
          onEdit={setEditing}
          onDelete={setDeleting}
        />
      )}

      {deleting ? (
        <DeleteProcedureDialog procedure={deleting} onClose={() => setDeleting(null)} />
      ) : null}
    </div>
  );
}
