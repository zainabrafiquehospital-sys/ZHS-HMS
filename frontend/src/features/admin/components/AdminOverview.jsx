'use client';

import { useMemo, useState } from 'react';
import { useForm } from 'react-hook-form';
import { zodResolver } from '@hookform/resolvers/zod';
import {
  Bell,
  ClipboardList,
  Pencil,
  Pill,
  Printer,
  Receipt,
  Search,
  Trash2,
  Wallet,
} from 'lucide-react';
import {
  useAdminVisitsForDay,
  useDeleteVisit,
  usePatientsForVisits,
  usePendingRevenue,
  useReceptionistsForVisits,
  useUpdateVisit,
} from '@/features/admin/hooks/useAdminOverview';
import { adminUpdateVisitSchema } from '@/features/reception/schemas/adminUpdateVisitSchema';
import {
  ProcedureItemsEditor,
  procedureItemToRequestPayload,
} from '@/features/visits/components/ProcedureItemsEditor';
import { VisitProcedureDisplay } from '@/features/visits/components/VisitProcedureDisplay';
import {
  useDeleteMedicineBill,
  useMedicineBillDetail,
  useMedicineBillsForDay,
  usePrintMedicineBill,
  useRecordMedicineBillPayment,
  useUpdateMedicineBill,
  useUsersForMedicineBills,
  useVisitsForMedicineBills,
} from '@/features/pharmacy/hooks/usePharmacy';
import {
  adminUpdateMedicineBillSchema,
  recordMedicineBillPaymentSchema,
} from '@/features/pharmacy/schemas/pharmacySchemas';
import { PendingApprovals } from '@/features/admin/components/PendingApprovals';
import { DateNavigator } from '@/features/admin/components/DateNavigator';
import {
  useInventoryItems,
  useInventoryRequests,
} from '@/features/inventory/hooks/useInventory';
import { InventoryHistoryPanel } from '@/features/inventory/components/InventoryHistoryPanel';
import { LeadsSection } from '@/features/admin/components/LeadsSection';
import { RevenueByActorPieChart } from '@/features/admin/components/RevenueByActorPieChart';
import {
  computeCombinedRevenueByActor,
  resolveActorSlices,
} from '@/features/admin/utils/revenueByActor';
import { Card, CardContent, CardHeader, CardTitle } from '@/shared/components/ui/Card';
import { Badge } from '@/shared/components/ui/Badge';
import { Button } from '@/shared/components/ui/Button';
import { ConfirmDialog } from '@/shared/components/ui/ConfirmDialog';
import { Input } from '@/shared/components/ui/Input';
import { Label } from '@/shared/components/ui/Label';
import { Select } from '@/shared/components/ui/Select';
import { Tabs } from '@/shared/components/ui/Tabs';
import { Textarea } from '@/shared/components/ui/Textarea';
import { PageLoader } from '@/shared/components/PageLoader';
import { PageError } from '@/shared/components/PageError';
import { PaymentMethodSelect } from '@/shared/components/PaymentMethodSelect';
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from '@/shared/components/ui/Table';
import { useDebouncedValue } from '@/shared/hooks/useDebouncedValue';
import { formatDisplayDate, formatDisplayTime, todayDisplayDayKey } from '@/utils/timezone';
import { VISIT_STATUS_BADGE_VARIANT } from '@/shared/constants/visitStatus';
import { PAYMENT_METHOD_LABELS } from '@/shared/constants/paymentMethod';

const OVERVIEW_TABS = [
  { value: 'visits', label: 'Visits' },
  { value: 'medicine_bills', label: 'Medicine Bills' },
  { value: 'inventory', label: 'Inventory' },
];

const INVENTORY_SUB_TABS = [
  { value: 'stock_levels', label: 'Stock Levels' },
  { value: 'requests', label: 'Restock Requests' },
  { value: 'history', label: 'History' },
];

const INVENTORY_REQUEST_STATUS_BADGE_VARIANT = {
  pending: 'warning',
  fulfilled: 'success',
  rejected: 'destructive',
};

const PAGE_SIZE = 15;

const currencyFormatter = new Intl.NumberFormat('en-US', {
  minimumFractionDigits: 2,
  maximumFractionDigits: 2,
});

function formatPkr(amount) {
  return `PKR ${currencyFormatter.format(Number(amount))}`;
}

function matchesSearch(patient, term) {
  if (!term) return true;
  const haystack = [patient?.full_name, patient?.mr_number, patient?.phone_number]
    .filter(Boolean)
    .join(' ')
    .toLowerCase();
  return haystack.includes(term.toLowerCase());
}

function SummaryTile({ icon: Icon, label, value }) {
  return (
    <div className="flex items-center gap-3 rounded-md border border-border bg-muted/30 p-4">
      <div className="flex h-9 w-9 shrink-0 items-center justify-center rounded-full bg-primary/10 text-primary">
        <Icon className="h-4 w-4" />
      </div>
      <div className="flex flex-col">
        <span className="text-xs text-muted-foreground">{label}</span>
        <span className="text-xl font-semibold tabular-nums text-foreground">{value}</span>
      </div>
    </div>
  );
}

/** Records an *additional* payment on an already-created medicine
 * bill — the "top up toward what's still Pending" action for a
 * patient returning to pay off a balance, now that the bill's first
 * payment is normally already folded into Finalize & Print at the
 * Pharmacy counter (see MedicineBillingWorkspace.jsx's docstring).
 * Admin Overview's Medicine Bills tab is the one screen that already
 * lists every bill regardless of day-of-creation or visit link, so
 * this lives here rather than in the Pharmacy workspace, which is
 * only ever the point of a *new* sale. Reuses the existing
 * ConfirmDialog primitive rather than a one-off modal. */
function RecordBillPaymentDialog({ bill, onClose }) {
  const recordPayment = useRecordMedicineBillPayment();
  const printBill = usePrintMedicineBill();
  const [error, setError] = useState(null);
  const pending = Number(bill.total_amount) - Number(bill.amount_paid);
  const {
    register,
    handleSubmit,
    formState: { errors, isSubmitting },
  } = useForm({
    resolver: zodResolver(recordMedicineBillPaymentSchema),
    defaultValues: { amount: '', payment_method: '' },
  });

  async function onSubmit(values) {
    setError(null);
    try {
      await recordPayment.mutateAsync({
        billId: bill.id,
        amount: values.amount,
        paymentMethod: values.payment_method,
      });
      await printBill.mutateAsync(bill.id);
      onClose();
    } catch (submitError) {
      setError(submitError.message || 'Unable to record payment.');
    }
  }

  return (
    <ConfirmDialog
      open
      title={`Record Payment — Bill ${bill.id.slice(0, 8)}`}
      confirmLabel={isSubmitting ? 'Recording…' : 'Record Payment & Print'}
      cancelLabel="Cancel"
      onCancel={onClose}
      onConfirm={handleSubmit(onSubmit)}
      description={
        <div className="flex flex-col gap-3">
          <p className="text-sm text-muted-foreground">
            An additional payment toward this bill's remaining balance — not the bill's original
            payment. Total {formatPkr(bill.total_amount)} · Received {formatPkr(bill.amount_paid)}{' '}
            · Pending {formatPkr(pending)}.
          </p>
          <div className="flex flex-col gap-1.5">
            <Label htmlFor="admin-bill-payment-amount">Amount (Rs.)</Label>
            <Input id="admin-bill-payment-amount" type="number" step="0.01" {...register('amount')} />
            {errors.amount ? <p className="text-xs text-destructive">{errors.amount.message}</p> : null}
          </div>
          <PaymentMethodSelect
            id="admin-bill-payment-method"
            registration={register('payment_method')}
            error={errors.payment_method}
          />
          {error ? <p className="text-xs text-destructive">{error}</p> : null}
        </div>
      }
    />
  );
}

/** The Patient-identity half of the "Edit Slip" form — shared by both
 * `EditVisitDialogLegacy` and `EditVisitDialogItemized` below (2026-08-21
 * split), since patient-identity correction is completely unaffected by
 * whether the visit itself is itemized. */
function PatientIdentityFields({ register, errors }) {
  return (
    <>
      <div className="flex flex-col gap-1.5">
        <Label htmlFor="admin-edit-full-name">Patient Name</Label>
        <Input id="admin-edit-full-name" {...register('full_name')} />
        {errors.full_name ? (
          <p className="text-xs text-destructive">{errors.full_name.message}</p>
        ) : null}
      </div>
      <div className="grid grid-cols-2 gap-3">
        <div className="flex flex-col gap-1.5">
          <Label htmlFor="admin-edit-age">Age</Label>
          <Input id="admin-edit-age" type="number" {...register('age_years')} />
          {errors.age_years ? (
            <p className="text-xs text-destructive">{errors.age_years.message}</p>
          ) : null}
        </div>
        <div className="flex flex-col gap-1.5">
          <Label htmlFor="admin-edit-gender">Gender</Label>
          <Select id="admin-edit-gender" {...register('gender')}>
            <option value="">—</option>
            <option value="female">Female</option>
            <option value="male">Male</option>
            <option value="other">Other</option>
          </Select>
        </div>
      </div>
      <div className="flex flex-col gap-1.5">
        <Label htmlFor="admin-edit-phone">Phone Number</Label>
        <Input id="admin-edit-phone" {...register('phone_number')} />
        {errors.phone_number ? (
          <p className="text-xs text-destructive">{errors.phone_number.message}</p>
        ) : null}
      </div>
      <div className="flex flex-col gap-1.5">
        <Label htmlFor="admin-edit-guardian">Guardian Name</Label>
        <Input id="admin-edit-guardian" {...register('guardian_name')} />
      </div>
      <div className="flex flex-col gap-1.5">
        <Label htmlFor="admin-edit-cnic">CNIC</Label>
        <Input id="admin-edit-cnic" {...register('cnic')} />
      </div>
      <div className="flex flex-col gap-1.5">
        <Label htmlFor="admin-edit-address">Address</Label>
        <Textarea id="admin-edit-address" rows={2} {...register('address')} />
      </div>
    </>
  );
}

/** Admin-only "Edit Slip" (2026-08-19 addition, `reception:update_visit`
 * — see receptionService.updateVisit's docstring) — corrects a wrongly-
 * entered registration: the linked patient's identity fields and/or the
 * visit's own procedure/amount (or procedure items), in one form/one
 * call. Never rendered for anyone without that permission — the Edit
 * button that opens this is itself gated (see the "Actions" column
 * below); this dialog is not a second authorization boundary, the
 * backend's own `require_permission` check already is.
 *
 * 2026-08-21 bifurcation: which variant renders depends purely on
 * whether this visit already has any `procedure_items` (see
 * backend/app/modules/visits/schemas.py's `VisitOut.procedure_items`
 * docstring) — `GET /visits` already returns this for every row, no
 * extra fetch needed here, unlike the medicine-bill admin-edit dialog's
 * own fetch-on-open step. A visit registered before 2026-08-21 (empty
 * `procedure_items`, forever) gets the original flat Procedure/Amount
 * form, completely unchanged. A visit registered from then on gets the
 * itemized procedure editor instead — see `VisitService.
 * update_visit_details`'s/`admin_replace_procedure_items`'s own
 * docstrings for why a legacy visit is never converted to itemized
 * through this dialog (a confirmed, explicit scope decision). */
function EditVisitDialog({ visit, patient, onClose }) {
  if (visit.procedure_items?.length > 0) {
    return <EditVisitDialogItemized visit={visit} patient={patient} onClose={onClose} />;
  }
  return <EditVisitDialogLegacy visit={visit} patient={patient} onClose={onClose} />;
}

function EditVisitDialogLegacy({ visit, patient, onClose }) {
  const updateVisit = useUpdateVisit();
  const [error, setError] = useState(null);
  const {
    register,
    handleSubmit,
    formState: { errors, isSubmitting },
  } = useForm({
    resolver: zodResolver(adminUpdateVisitSchema),
    defaultValues: {
      full_name: patient?.full_name ?? '',
      guardian_name: patient?.guardian_name ?? '',
      gender: patient?.gender ?? '',
      age_years: patient?.age_years ?? '',
      phone_number: patient?.phone_number ?? '',
      cnic: patient?.cnic ?? '',
      address: patient?.address ?? '',
      procedure: visit.procedure,
      amount: visit.amount,
    },
  });

  async function onSubmit(values) {
    setError(null);
    const updates = { ...values };
    // Blank optional fields mean "leave unchanged" for this form (see
    // adminUpdateVisitSchema's own docstring) — never send an empty
    // string for a field the admin didn't actually clear out.
    for (const key of ['guardian_name', 'gender', 'cnic', 'address']) {
      if (updates[key] === '') delete updates[key];
    }
    try {
      await updateVisit.mutateAsync({ visitId: visit.id, updates });
      onClose();
    } catch (submitError) {
      setError(submitError.message || 'Unable to update this visit.');
    }
  }

  return (
    <ConfirmDialog
      open
      title={`Edit Slip — ${visit.queue_token}`}
      confirmLabel={isSubmitting ? 'Saving…' : 'Save Changes'}
      cancelLabel="Cancel"
      onCancel={onClose}
      onConfirm={handleSubmit(onSubmit)}
      description={
        <div className="flex max-h-[60vh] flex-col gap-3 overflow-y-auto pr-1">
          <PatientIdentityFields register={register} errors={errors} />
          <div className="flex flex-col gap-1.5">
            <Label htmlFor="admin-edit-procedure">Procedure</Label>
            <Input id="admin-edit-procedure" {...register('procedure')} />
            {errors.procedure ? (
              <p className="text-xs text-destructive">{errors.procedure.message}</p>
            ) : null}
          </div>
          <div className="flex flex-col gap-1.5">
            <Label htmlFor="admin-edit-amount">Amount (Rs.)</Label>
            <Input id="admin-edit-amount" type="number" step="0.01" {...register('amount')} />
            {errors.amount ? (
              <p className="text-xs text-destructive">{errors.amount.message}</p>
            ) : null}
          </div>
          {error ? <p className="text-xs text-destructive">{error}</p> : null}
        </div>
      }
    />
  );
}

/** The itemized-visit sibling of `EditVisitDialogLegacy` (2026-08-21
 * addition) — same patient-identity half, but replaces the flat
 * Procedure/Amount fields with `ProcedureItemsEditor`, pre-filled from
 * `visit.procedure_items` and submitted as a full replacement of the
 * visit's entire procedure-item set (see VisitService.
 * admin_replace_procedure_items's own docstring). Discount is
 * deliberately untouched by this dialog, exactly as it always has been
 * — a separately confirmed, explicit scope decision. */
function EditVisitDialogItemized({ visit, patient, onClose }) {
  const updateVisit = useUpdateVisit();
  const [error, setError] = useState(null);
  const [procedureItems, setProcedureItems] = useState(() =>
    visit.procedure_items.map((item) => ({
      key: item.id,
      procedure_id: item.procedure_id,
      name: item.name,
      amount: item.amount,
    })),
  );
  const [procedureItemsError, setProcedureItemsError] = useState(null);
  const {
    register,
    handleSubmit,
    formState: { errors, isSubmitting },
  } = useForm({
    resolver: zodResolver(adminUpdateVisitSchema),
    defaultValues: {
      full_name: patient?.full_name ?? '',
      guardian_name: patient?.guardian_name ?? '',
      gender: patient?.gender ?? '',
      age_years: patient?.age_years ?? '',
      phone_number: patient?.phone_number ?? '',
      cnic: patient?.cnic ?? '',
      address: patient?.address ?? '',
    },
  });

  async function onSubmit(values) {
    setError(null);
    setProcedureItemsError(null);
    if (procedureItems.length === 0) {
      setProcedureItemsError('At least one procedure is required.');
      return;
    }
    const updates = { ...values, procedures: procedureItems.map(procedureItemToRequestPayload) };
    for (const key of ['guardian_name', 'gender', 'cnic', 'address']) {
      if (updates[key] === '') delete updates[key];
    }
    try {
      await updateVisit.mutateAsync({ visitId: visit.id, updates });
      onClose();
    } catch (submitError) {
      setError(submitError.message || 'Unable to update this visit.');
    }
  }

  return (
    <ConfirmDialog
      open
      title={`Edit Slip — ${visit.queue_token}`}
      confirmLabel={isSubmitting ? 'Saving…' : 'Save Changes'}
      cancelLabel="Cancel"
      onCancel={onClose}
      onConfirm={handleSubmit(onSubmit)}
      description={
        <div className="flex max-h-[70vh] flex-col gap-3 overflow-y-auto pr-1">
          <PatientIdentityFields register={register} errors={errors} />
          <div className="flex flex-col gap-1.5">
            <Label>Procedures</Label>
            <ProcedureItemsEditor items={procedureItems} onChange={setProcedureItems} />
            {procedureItemsError ? (
              <p className="text-xs text-destructive">{procedureItemsError}</p>
            ) : null}
          </div>
          {error ? <p className="text-xs text-destructive">{error}</p> : null}
        </div>
      }
    />
  );
}

/** Admin-only visit deletion (2026-08-19 addition,
 * `reception:delete_visit`) — a real, destructive-feeling action
 * (never available to Receptionist, see backend/app/modules/reception/
 * constants.py's own docstring), so this is a full ConfirmDialog with
 * an explicit description, never a single-click button — same
 * discipline as EmployeeAccounts.jsx's deactivate/delete confirmations.
 * The backend's own paid-invoice block (VISIT_HAS_SETTLED_INVOICE, see
 * ReceptionService.admin_delete_visit) surfaces here as a plain error
 * message, not a separate UI state — the confirm button simply fails
 * with a clear reason if that block applies. */
function DeleteVisitDialog({ visit, onClose }) {
  const deleteVisit = useDeleteVisit();
  const [error, setError] = useState(null);

  async function handleConfirm() {
    setError(null);
    try {
      await deleteVisit.mutateAsync(visit.id);
      onClose();
    } catch (deleteError) {
      setError(deleteError.message || 'Unable to delete this visit.');
    }
  }

  return (
    <ConfirmDialog
      open
      variant="destructive"
      title={`Delete Visit — ${visit.queue_token}?`}
      confirmLabel={deleteVisit.isPending ? 'Deleting…' : 'Delete Visit'}
      cancelLabel="Cancel"
      onCancel={onClose}
      onConfirm={handleConfirm}
      description={
        <div className="flex flex-col gap-2">
          <p>
            This permanently removes this visit/slip from every list — it will no longer be
            reachable or reprintable. The patient record itself is not affected, and this cannot
            be undone through the app.
          </p>
          {error ? <p className="text-destructive">{error}</p> : null}
        </div>
      }
    />
  );
}

/** Admin-only "Edit Bill" (2026-08-20 addition, `pharmacy:update_bill`
 * — see pharmacyService.updateBill's docstring) — the medicine-bill
 * sibling of `EditVisitDialog` above. Unlike that dialog, `bill` here
 * is only the lighter `MedicineBillSummaryOut` row the table already
 * has (no `manual_patient_age`/`_phone`/`discount_reason` — see that
 * schema's own docstring), so this fetches the full bill detail itself
 * (`useMedicineBillDetail`) before rendering the actual form, rather
 * than assuming the caller already has every field. Manual patient
 * fields are only shown/submitted when the bill has no linked
 * `visit_id` — a visit-linked bill's identity is corrected through
 * that Visit's own existing "Edit Slip" action instead (see
 * PharmacyService.admin_update_bill's docstring for the exact
 * server-side rejection this mirrors). The backend's own settled-
 * payment block (MEDICINE_BILL_HAS_SETTLED_PAYMENT) surfaces here as a
 * plain error message, not a separate UI state — same discipline as
 * `DeleteVisitDialog`'s own paid-invoice block. */
function EditMedicineBillDialog({ bill, onClose }) {
  const { data: fullBill, isLoading } = useMedicineBillDetail(bill.id);

  if (isLoading || !fullBill) {
    return (
      <ConfirmDialog
        open
        title="Edit Medicine Bill"
        confirmLabel="Loading…"
        cancelLabel="Cancel"
        onCancel={onClose}
        onConfirm={() => {}}
        description={<p className="text-sm text-muted-foreground">Loading bill details…</p>}
      />
    );
  }

  return <EditMedicineBillForm bill={fullBill} onClose={onClose} />;
}

function EditMedicineBillForm({ bill, onClose }) {
  const updateBill = useUpdateMedicineBill();
  const [error, setError] = useState(null);
  const isWalkIn = bill.visit_id == null;
  const {
    register,
    handleSubmit,
    formState: { errors, isSubmitting },
  } = useForm({
    resolver: zodResolver(adminUpdateMedicineBillSchema),
    defaultValues: {
      manual_patient_name: bill.manual_patient_name ?? '',
      manual_patient_age: bill.manual_patient_age ?? '',
      manual_patient_phone: bill.manual_patient_phone ?? '',
      discount_amount: bill.discount_amount,
      discount_reason: bill.discount_reason ?? '',
    },
  });

  async function onSubmit(values) {
    setError(null);
    const updates = { ...values };
    // Blank optional fields mean "leave unchanged" (see
    // adminUpdateMedicineBillSchema's own docstring) — never send an
    // empty string for a field the admin didn't actually clear out.
    for (const key of ['manual_patient_name', 'manual_patient_phone', 'discount_reason']) {
      if (updates[key] === '') delete updates[key];
    }
    // A visit-linked bill has no manual patient fields to submit at
    // all — sending them (even unchanged) would trip the backend's own
    // MEDICINE_BILL_MANUAL_PATIENT_CONFLICTS_WITH_VISIT rejection.
    if (!isWalkIn) {
      delete updates.manual_patient_name;
      delete updates.manual_patient_age;
      delete updates.manual_patient_phone;
    }
    try {
      await updateBill.mutateAsync({ billId: bill.id, updates });
      onClose();
    } catch (submitError) {
      setError(submitError.message || 'Unable to update this medicine bill.');
    }
  }

  return (
    <ConfirmDialog
      open
      title={`Edit Medicine Bill — ${bill.queue_token ?? bill.id.slice(0, 8)}`}
      confirmLabel={isSubmitting ? 'Saving…' : 'Save Changes'}
      cancelLabel="Cancel"
      onCancel={onClose}
      onConfirm={handleSubmit(onSubmit)}
      description={
        <div className="flex max-h-[60vh] flex-col gap-3 overflow-y-auto pr-1">
          {isWalkIn ? (
            <>
              <div className="flex flex-col gap-1.5">
                <Label htmlFor="admin-bill-edit-name">Patient Name</Label>
                <Input id="admin-bill-edit-name" {...register('manual_patient_name')} />
                {errors.manual_patient_name ? (
                  <p className="text-xs text-destructive">{errors.manual_patient_name.message}</p>
                ) : null}
              </div>
              <div className="grid grid-cols-2 gap-3">
                <div className="flex flex-col gap-1.5">
                  <Label htmlFor="admin-bill-edit-age">Age</Label>
                  <Input id="admin-bill-edit-age" type="number" {...register('manual_patient_age')} />
                  {errors.manual_patient_age ? (
                    <p className="text-xs text-destructive">{errors.manual_patient_age.message}</p>
                  ) : null}
                </div>
                <div className="flex flex-col gap-1.5">
                  <Label htmlFor="admin-bill-edit-phone">Contact Number</Label>
                  <Input id="admin-bill-edit-phone" {...register('manual_patient_phone')} />
                  {errors.manual_patient_phone ? (
                    <p className="text-xs text-destructive">{errors.manual_patient_phone.message}</p>
                  ) : null}
                </div>
              </div>
            </>
          ) : (
            <p className="text-xs text-muted-foreground">
              This bill is linked to a visit — its patient details are corrected through that
              visit's own "Edit Slip" action on the Visits tab, not here.
            </p>
          )}
          <div className="grid grid-cols-2 gap-3">
            <div className="flex flex-col gap-1.5">
              <Label htmlFor="admin-bill-edit-discount-amount">Discount (Rs.)</Label>
              <Input
                id="admin-bill-edit-discount-amount"
                type="number"
                step="0.01"
                {...register('discount_amount')}
              />
              {errors.discount_amount ? (
                <p className="text-xs text-destructive">{errors.discount_amount.message}</p>
              ) : null}
            </div>
            <div className="flex flex-col gap-1.5">
              <Label htmlFor="admin-bill-edit-discount-reason">Discount Reason</Label>
              <Input id="admin-bill-edit-discount-reason" {...register('discount_reason')} />
            </div>
          </div>
          {error ? <p className="text-xs text-destructive">{error}</p> : null}
        </div>
      }
    />
  );
}

/** Admin-only medicine bill deletion (2026-08-20 addition,
 * `pharmacy:delete_bill`) — the medicine-bill sibling of
 * `DeleteVisitDialog` above; same full-ConfirmDialog-with-explicit-
 * description discipline, never a single-click button. The backend's
 * own settled-payment block (MEDICINE_BILL_HAS_SETTLED_PAYMENT, see
 * PharmacyService.admin_delete_bill) surfaces here as a plain error
 * message, not a separate UI state. */
function DeleteMedicineBillDialog({ bill, onClose }) {
  const deleteBill = useDeleteMedicineBill();
  const [error, setError] = useState(null);

  async function handleConfirm() {
    setError(null);
    try {
      await deleteBill.mutateAsync(bill.id);
      onClose();
    } catch (deleteError) {
      setError(deleteError.message || 'Unable to delete this medicine bill.');
    }
  }

  return (
    <ConfirmDialog
      open
      variant="destructive"
      title={`Delete Medicine Bill — ${bill.queue_token ?? bill.id.slice(0, 8)}?`}
      confirmLabel={deleteBill.isPending ? 'Deleting…' : 'Delete Bill'}
      cancelLabel="Cancel"
      onCancel={onClose}
      onConfirm={handleConfirm}
      description={
        <div className="flex flex-col gap-2">
          <p>
            This permanently removes this medicine bill from every list — it will no longer be
            reachable or reprintable. Any linked visit is not affected, and this cannot be undone
            through the app.
          </p>
          {error ? <p className="text-destructive">{error}</p> : null}
        </div>
      }
    />
  );
}

/** The Medicine Bills tab — mirrors the Visits tab's own day-scoped,
 * read-only shape (same `selectedDate`, same "view/reprint" action
 * pattern as Billing's own `usePrintInvoice`), but reads `GET
 * /pharmacy/bills?date=` directly rather than reusing `GET /visits`
 * (see app/modules/pharmacy/router.py's `list_bills_for_day`) — a
 * medicine bill is its own entity, not a Visit. */
function MedicineBillsPanel({ selectedDate }) {
  const { data: bills, isLoading, isError, error, refetch } = useMedicineBillsForDay(selectedDate);
  const visitsById = useVisitsForMedicineBills(bills);
  const patientsById = usePatientsForVisits(Object.values(visitsById).filter(Boolean));
  const usersById = useUsersForMedicineBills(bills);
  const printBill = usePrintMedicineBill();
  const [printError, setPrintError] = useState(null);
  const [payingBill, setPayingBill] = useState(null);
  // Admin-only Edit/Delete (2026-08-20 addition) — at most one dialog
  // open at a time, keyed by the specific bill it targets, same shape
  // as the Visits tab's editingVisit/deletingVisit state.
  const [editingBill, setEditingBill] = useState(null);
  const [deletingBill, setDeletingBill] = useState(null);

  async function handlePrint(billId) {
    setPrintError(null);
    try {
      await printBill.mutateAsync(billId);
    } catch (err) {
      setPrintError(err.message || 'Unable to print this bill.');
    }
  }

  if (isLoading) return <PageLoader label="Loading medicine bills" />;
  if (isError) {
    return <PageError error={error} reset={refetch} message="Couldn't load medicine bills." />;
  }

  const rows = bills ?? [];

  return (
    <div className="flex flex-col gap-5">
      {/* "Total Revenue" tile (2026-08-20) and the "Revenue by
          Receptionist" pie chart (2026-08-20 update) are both gone from
          here — the tile is covered by the always-visible combined
          revenue row above the tabs, and the chart itself is now one
          single combined instance in that same always-visible area
          (see AdminOverview's own render) rather than a separate,
          Medicine-Bill-only chart that under-reported a receptionist
          who also does Visit revenue. */}
      <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
        <SummaryTile icon={Pill} label="Total Bills" value={rows.length} />
      </div>

      {rows.length === 0 ? (
        <p className="py-10 text-center text-sm text-muted-foreground">
          No medicine bills were created on {formatDisplayDate(selectedDate)}.
        </p>
      ) : (
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead>Time</TableHead>
              <TableHead>Patient</TableHead>
              <TableHead>Billed By</TableHead>
              <TableHead className="text-right">Items</TableHead>
              <TableHead className="text-right">Total</TableHead>
              <TableHead>Status</TableHead>
              <TableHead>Payment Method</TableHead>
              <TableHead />
            </TableRow>
          </TableHeader>
          <TableBody>
            {rows.map((bill) => {
              const visit = bill.visit_id ? visitsById[bill.visit_id] : null;
              const patient = visit ? patientsById[visit.patient_id] : null;
              const billedBy = bill.created_by ? usersById[bill.created_by] : null;
              return (
                <TableRow key={bill.id}>
                  <TableCell className="whitespace-nowrap">
                    {formatDisplayTime(bill.created_at)}
                  </TableCell>
                  <TableCell className="max-w-[160px] truncate font-medium text-foreground">
                    {/* Same three-way fallback the print slip's own
                        patient/visit reference block uses (see
                        app/modules/pharmacy/router.py's `print_bill`):
                        a linked visit's real Patient, else the
                        manually-typed name, else a plain walk-in. */}
                    {bill.visit_id
                      ? (patient?.full_name ?? '…')
                      : (bill.manual_patient_name ?? 'Walk-in')}
                  </TableCell>
                  <TableCell className="max-w-[140px] truncate">
                    {bill.created_by ? billedBy?.full_name || '…' : '—'}
                  </TableCell>
                  <TableCell className="text-right tabular-nums">{bill.item_count}</TableCell>
                  <TableCell className="whitespace-nowrap text-right font-medium tabular-nums">
                    {formatPkr(bill.total_amount)}
                  </TableCell>
                  <TableCell>
                    <Badge
                      variant={
                        bill.status === 'paid'
                          ? 'success'
                          : bill.status === 'partially_paid'
                            ? 'warning'
                            : 'outline'
                      }
                      className="capitalize"
                    >
                      {bill.status.replaceAll('_', ' ')}
                    </Badge>
                  </TableCell>
                  <TableCell className="max-w-[160px] truncate text-xs text-muted-foreground">
                    {/* Distinct methods across this bill's payments, in
                        first-payment order (2026-08-19 addition) — see
                        MedicineBillSummaryOut.payment_methods's own
                        docstring. Never "cash" by default: an unpaid
                        bill simply shows a dash. */}
                    {bill.payment_methods?.length > 0
                      ? bill.payment_methods
                          .map((method) => PAYMENT_METHOD_LABELS[method] ?? method)
                          .join(', ')
                      : '—'}
                  </TableCell>
                  <TableCell>
                    <div className="flex gap-2">
                      {bill.status !== 'paid' ? (
                        <Button size="sm" variant="outline" onClick={() => setPayingBill(bill)}>
                          <Wallet className="h-4 w-4" />
                          Record Payment
                        </Button>
                      ) : null}
                      <Button
                        size="sm"
                        variant="outline"
                        onClick={() => handlePrint(bill.id)}
                        disabled={printBill.isPending}
                      >
                        <Printer className="h-4 w-4" />
                        Reprint
                      </Button>
                      <Button
                        size="sm"
                        variant="outline"
                        onClick={() => setEditingBill(bill)}
                        title="Correct this bill's details"
                      >
                        <Pencil className="h-3.5 w-3.5" />
                      </Button>
                      <Button
                        size="sm"
                        variant="outline"
                        onClick={() => setDeletingBill(bill)}
                        title="Delete this medicine bill"
                      >
                        <Trash2 className="h-3.5 w-3.5" />
                      </Button>
                    </div>
                  </TableCell>
                </TableRow>
              );
            })}
          </TableBody>
        </Table>
      )}
      {printError ? <p className="text-sm text-destructive">{printError}</p> : null}
      {payingBill ? (
        <RecordBillPaymentDialog bill={payingBill} onClose={() => setPayingBill(null)} />
      ) : null}
      {editingBill ? (
        <EditMedicineBillDialog bill={editingBill} onClose={() => setEditingBill(null)} />
      ) : null}
      {deletingBill ? (
        <DeleteMedicineBillDialog bill={deletingBill} onClose={() => setDeletingBill(null)} />
      ) : null}
    </div>
  );
}

/** The always-visible "count indicator" for pending Ward/Emergency
 * Inventory restock requests — same visual shape as `PendingApprovals`
 * above (a small Card, icon + live count in the title), positioned
 * right alongside it rather than gated behind the Inventory tab below,
 * per the confirmed design's own "mirroring how PendingApprovals' own
 * count already surfaces there" instruction. Deliberately just a count
 * plus a compact list, not a duplicate of the Inventory tab's own full
 * pending-and-resolved requests table (see `InventoryRequestsPanel`
 * below) — this is a glanceable indicator, not a second place to browse
 * the same data twice. No Fulfill/Reject actions here or anywhere in
 * this file: those are Inventory-Manager-only operational actions (see
 * backend/app/modules/inventory/constants.py's own read/manage split);
 * Admin Overview's own role throughout this file is oversight/
 * correction (Edit/Delete on Visits and Medicine Bills), never the
 * primary way an action gets performed, and Inventory has no admin
 * data-correction endpoint built at all — this stays pure visibility. */
function PendingInventoryRequestsCard() {
  const { data: items } = useInventoryItems();
  const { data: pendingRequests, isLoading, isError, error, refetch } = useInventoryRequests({
    status: 'pending',
  });

  const rows = pendingRequests ?? [];

  return (
    <Card>
      <CardHeader className="flex-row items-center gap-2">
        <Bell className="h-4 w-4 text-muted-foreground" />
        <CardTitle>Pending Inventory Requests ({rows.length})</CardTitle>
      </CardHeader>
      <CardContent>
        {isLoading ? (
          <PageLoader label="Loading pending inventory requests" />
        ) : isError ? (
          <PageError
            error={error}
            reset={refetch}
            message="Couldn't load pending inventory requests."
          />
        ) : rows.length === 0 ? (
          <p className="text-sm text-muted-foreground">
            No restock requests are currently awaiting the Inventory Manager.
          </p>
        ) : (
          <ul className="flex flex-col gap-1.5 text-sm">
            {rows.map((request) => {
              const item = (items ?? []).find((candidate) => candidate.id === request.item_id);
              return (
                <li key={request.id} className="flex items-center justify-between gap-2">
                  <span className="text-foreground">{item?.name ?? 'Unknown item'}</span>
                  <span className="text-muted-foreground">
                    {request.requested_quantity ?? 'unspecified quantity'}
                    {request.note ? ` — "${request.note}"` : ''}
                  </span>
                </li>
              );
            })}
          </ul>
        )}
      </CardContent>
    </Card>
  );
}

/** Read-only "both stock levels" table — Admin sees the exact same
 * `InventoryItemOut` rows the Inventory Manager's own Catalog tab does,
 * minus every write action (no Edit, no Activate/Deactivate): this is
 * oversight, not a second inventory-management surface. */
function InventoryStockLevelsTable() {
  const { data: items, isLoading, isError, error, refetch } = useInventoryItems();

  if (isLoading) return <PageLoader label="Loading inventory catalog" />;
  if (isError) {
    return <PageError error={error} reset={refetch} message="Couldn't load the item catalog." />;
  }

  const rows = items ?? [];
  if (rows.length === 0) {
    return <p className="text-sm text-muted-foreground">No inventory items have been added yet.</p>;
  }

  return (
    <Table>
      <TableHeader>
        <TableRow>
          <TableHead>Name</TableHead>
          <TableHead>Category</TableHead>
          <TableHead>Unit</TableHead>
          <TableHead className="text-right">Main Stock</TableHead>
          <TableHead className="text-right">Emergency Stock</TableHead>
          <TableHead>Status</TableHead>
        </TableRow>
      </TableHeader>
      <TableBody>
        {rows.map((item) => (
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
          </TableRow>
        ))}
      </TableBody>
    </Table>
  );
}

/** Read-only "all restock requests (pending and resolved)" table — the
 * Inventory tab's own copy of the same data `PendingInventoryRequestsCard`
 * above only summarizes; no status filter, so a resolved request never
 * disappears from Admin's view the way it does from the Inventory
 * Manager's own worklist-shaped Restock Requests tab. */
function InventoryRequestsPanel() {
  const { data: items } = useInventoryItems();
  const { data: requests, isLoading, isError, error, refetch } = useInventoryRequests({});

  if (isLoading) return <PageLoader label="Loading restock requests" />;
  if (isError) {
    return <PageError error={error} reset={refetch} message="Couldn't load restock requests." />;
  }

  const rows = requests ?? [];
  if (rows.length === 0) {
    return <p className="text-sm text-muted-foreground">No restock requests have been raised yet.</p>;
  }

  return (
    <Table>
      <TableHeader>
        <TableRow>
          <TableHead>Item</TableHead>
          <TableHead className="text-right">Requested Qty</TableHead>
          <TableHead>Note</TableHead>
          <TableHead>Status</TableHead>
          <TableHead>Raised</TableHead>
        </TableRow>
      </TableHeader>
      <TableBody>
        {rows.map((request) => {
          const item = (items ?? []).find((candidate) => candidate.id === request.item_id);
          return (
            <TableRow key={request.id}>
              <TableCell className="font-medium text-foreground">
                {item?.name ?? 'Unknown item'}
              </TableCell>
              <TableCell className="text-right tabular-nums">
                {request.requested_quantity ?? '—'}
              </TableCell>
              <TableCell className="max-w-[220px] truncate text-muted-foreground">
                {request.note ?? '—'}
              </TableCell>
              <TableCell>
                <Badge
                  variant={INVENTORY_REQUEST_STATUS_BADGE_VARIANT[request.status]}
                  className="capitalize"
                >
                  {request.status}
                </Badge>
              </TableCell>
              <TableCell className="text-muted-foreground">
                {formatDisplayTime(request.created_at)}
              </TableCell>
            </TableRow>
          );
        })}
      </TableBody>
    </Table>
  );
}

/** Ward/Emergency Inventory Management's own Admin Overview tab —
 * "Admin sees both stock levels, full transfer history, full usage
 * history (patient-linked or manual), and all restock requests (pending
 * and resolved)" (confirmed design). Not day-scoped like the Visits/
 * Medicine Bills tabs (no `selectedDate` prop) — inventory state is a
 * live, cumulative position, the same "all-time, not scoped to today"
 * framing `usePendingRevenue` already established for Pending Revenue.
 * "History" reuses `InventoryHistoryPanel` wholesale, the exact same
 * component the Inventory Manager's own History tab uses — it was
 * already fully read-only (no action buttons anywhere in it), so
 * reusing it here is a real cross-feature reuse, not a coincidence;
 * it also covers Receipts alongside Transfers/Usage, a superset of what
 * was asked for at no extra cost. */
function InventoryPanel() {
  const [subTab, setSubTab] = useState('stock_levels');

  return (
    <div className="flex flex-col gap-5">
      <Tabs value={subTab} onValueChange={setSubTab} tabs={INVENTORY_SUB_TABS} />
      {subTab === 'stock_levels' ? (
        <InventoryStockLevelsTable />
      ) : subTab === 'requests' ? (
        <InventoryRequestsPanel />
      ) : (
        <InventoryHistoryPanel />
      )}
    </div>
  );
}

export function AdminOverview() {
  const [selectedDate, setSelectedDate] = useState(todayDisplayDayKey());
  const [searchTerm, setSearchTerm] = useState('');
  const [page, setPage] = useState(1);
  const [activeTab, setActiveTab] = useState('visits');
  // Admin-only Edit/Delete (2026-08-19 addition) — at most one dialog
  // open at a time, keyed by the specific visit it targets.
  const [editingVisit, setEditingVisit] = useState(null);
  const [deletingVisit, setDeletingVisit] = useState(null);

  const { visits, isLoading, isError, error, refetch } = useAdminVisitsForDay(selectedDate);
  const patientsById = usePatientsForVisits(visits);
  const receptionistsById = useReceptionistsForVisits(visits);
  const debouncedSearch = useDebouncedValue(searchTerm, 200);
  // Fetched here too (2026-08-20 addition), not only inside
  // MedicineBillsPanel below — the combined revenue row (and, as of this
  // fix, the combined revenue-by-receptionist chart) must be visible
  // regardless of which tab is active, and TanStack Query dedupes both
  // of these against MedicineBillsPanel's own identical queries (same
  // query keys — `['pharmacy', 'bills', 'day', selectedDate]` and
  // `['admin', 'users', userId]` respectively — same cache entries)
  // rather than doubling any network request.
  const { data: medicineBills } = useMedicineBillsForDay(selectedDate);
  const medicineBillActorsById = useUsersForMedicineBills(medicineBills);
  // All-time, never day-scoped (2026-08-22 addition) — see
  // usePendingRevenue's own docstring for why this tile deliberately
  // doesn't follow the other three's `selectedDate` scoping.
  const pendingRevenue = usePendingRevenue();

  const totalRevenue = useMemo(
    () => visits.reduce((sum, visit) => sum + Number(visit.amount), 0),
    [visits],
  );
  const medicineRevenue = useMemo(
    () => (medicineBills ?? []).reduce((sum, bill) => sum + Number(bill.total_amount), 0),
    [medicineBills],
  );
  // 2026-08-20 fix: this used to be Visit revenue only (`computeRevenueByActor(visits, 'amount')`),
  // so a receptionist's Medicine Bill revenue never counted toward their
  // slice — under-reporting their true combined contribution (e.g. PKR
  // 6,350 shown when the real combined total was PKR 7,550). Now one
  // combined chart for both entity types, matching the combined revenue
  // tiles above it; the previous separate per-tab charts are gone (see
  // MedicineBillsPanel's own comment).
  const revenueByActor = useMemo(
    () =>
      resolveActorSlices(
        computeCombinedRevenueByActor([
          { records: visits, amountKey: 'amount' },
          { records: medicineBills, amountKey: 'total_amount' },
        ]),
        { ...receptionistsById, ...medicineBillActorsById },
      ),
    [visits, medicineBills, receptionistsById, medicineBillActorsById],
  );

  const statusCounts = useMemo(() => {
    const counts = {};
    for (const visit of visits) {
      counts[visit.status] = (counts[visit.status] ?? 0) + 1;
    }
    return counts;
  }, [visits]);

  const filteredVisits = useMemo(() => {
    if (!debouncedSearch) return visits;
    return visits.filter((visit) => matchesSearch(patientsById[visit.patient_id], debouncedSearch));
  }, [visits, patientsById, debouncedSearch]);

  const pageCount = Math.max(1, Math.ceil(filteredVisits.length / PAGE_SIZE));
  const currentPage = Math.min(page, pageCount);
  const pagedVisits = filteredVisits.slice((currentPage - 1) * PAGE_SIZE, currentPage * PAGE_SIZE);

  function handleDateChange(nextDate) {
    setSelectedDate(nextDate);
    setSearchTerm('');
    setPage(1);
  }

  function handleSearchChange(value) {
    setSearchTerm(value);
    setPage(1);
  }

  return (
    <div className="flex flex-col gap-6">
      <div className="flex flex-col gap-1">
        <h1 className="text-lg font-semibold text-foreground">Admin Overview</h1>
        <p className="text-sm text-muted-foreground">
          Hospital-wide patient and visit activity, read-only — not scoped to any one receptionist.
        </p>
      </div>

      <PendingApprovals />
      <PendingInventoryRequestsCard />

      {/* Combined revenue row (2026-08-20 addition) — visible regardless
          of which tab is active below, same three-way breakdown as the
          receptionist's own "My Revenue" view (MyRegistrations.jsx):
          Visit Revenue, Medicine Revenue, and their sum. Previously
          Admin Overview only ever showed Visit revenue (the Visits tab's
          own "Total Revenue" tile), with Medicine revenue nowhere in
          view unless the Medicine Bills tab happened to be open.
          "Pending Revenue" (2026-08-22 addition) is the one tile here
          that is NOT scoped to `selectedDate` like the other three —
          see usePendingRevenue's own docstring for why an all-time
          outstanding balance is the only correct framing. */}
      <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-4">
        <SummaryTile icon={Receipt} label="Visit Revenue" value={formatPkr(totalRevenue)} />
        <SummaryTile icon={Receipt} label="Medicine Revenue" value={formatPkr(medicineRevenue)} />
        <SummaryTile
          icon={Receipt}
          label="Total Revenue"
          value={formatPkr(totalRevenue + medicineRevenue)}
        />
        <SummaryTile icon={Wallet} label="Pending Revenue" value={formatPkr(pendingRevenue)} />
      </div>

      {/* Combined "Revenue by Receptionist" chart (2026-08-20 fix) — one
          instance, visible regardless of which tab is active, reflecting
          each receptionist's Visit + Medicine Bill revenue together
          (see the `revenueByActor` memo above). Replaces the two
          separate per-tab charts this used to be (Visits-only and
          Medicine-Bills-only), which each under-reported a receptionist
          who earned revenue from both. */}
      <div>
        <p className="mb-2 text-xs font-medium text-muted-foreground">Revenue by Receptionist</p>
        <RevenueByActorPieChart data={revenueByActor} />
      </div>

      <Card>
        <CardHeader className="flex-col items-start gap-3 sm:flex-row sm:items-center sm:justify-between">
          <Tabs value={activeTab} onValueChange={setActiveTab} tabs={OVERVIEW_TABS} />
          {/* Hidden on the Inventory tab — inventory state is a live,
              cumulative position, not scoped to `selectedDate` the way
              Visits/Medicine Bills are (see InventoryPanel's own
              docstring); showing a date picker that visibly filters
              nothing would be misleading. */}
          {activeTab === 'inventory' ? null : (
            <DateNavigator selectedDate={selectedDate} onChange={handleDateChange} />
          )}
        </CardHeader>
        <CardContent className="flex flex-col gap-5">
          {activeTab === 'inventory' ? (
            <InventoryPanel />
          ) : activeTab === 'medicine_bills' ? (
            <MedicineBillsPanel selectedDate={selectedDate} />
          ) : isLoading ? (
            <PageLoader label="Loading visit activity" />
          ) : isError ? (
            <PageError error={error} reset={refetch} message="Couldn't load visit activity." />
          ) : (
            <>
              {/* "Total Revenue" tile and the "Revenue by Receptionist"
                  chart are both gone from here (2026-08-20) — see the
                  always-visible combined revenue row and combined chart
                  above the tabs. */}
              <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
                <SummaryTile icon={ClipboardList} label="Total Visits" value={visits.length} />
              </div>

              {Object.keys(statusCounts).length > 0 ? (
                <div>
                  <p className="mb-2 text-xs font-medium text-muted-foreground">By Status</p>
                  <div className="flex flex-wrap gap-2">
                    {Object.entries(statusCounts).map(([status, count]) => (
                      <Badge
                        key={status}
                        variant={VISIT_STATUS_BADGE_VARIANT[status] ?? 'outline'}
                        className="capitalize"
                      >
                        {status.replaceAll('_', ' ')}: {count}
                      </Badge>
                    ))}
                  </div>
                </div>
              ) : null}

              <div className="relative sm:max-w-xs">
                <Search className="pointer-events-none absolute left-2.5 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground" />
                <Input
                  value={searchTerm}
                  onChange={(event) => handleSearchChange(event.target.value)}
                  placeholder="Search by name, MR number, or phone"
                  className="pl-8"
                />
              </div>

              {visits.length === 0 ? (
                <p className="py-10 text-center text-sm text-muted-foreground">
                  No visits were registered on {formatDisplayDate(selectedDate)}.
                </p>
              ) : filteredVisits.length === 0 ? (
                <p className="py-10 text-center text-sm text-muted-foreground">
                  No visits match &quot;{debouncedSearch}&quot;.
                </p>
              ) : (
                <>
                  <Table>
                    <TableHeader>
                      <TableRow>
                        <TableHead>Time</TableHead>
                        <TableHead>Queue Token</TableHead>
                        <TableHead>Patient</TableHead>
                        <TableHead>MR #</TableHead>
                        <TableHead>Age / Gender</TableHead>
                        <TableHead>Phone</TableHead>
                        <TableHead>Procedure</TableHead>
                        <TableHead>Doctor</TableHead>
                        <TableHead>Status</TableHead>
                        <TableHead>Booked By</TableHead>
                        <TableHead className="text-right">Amount</TableHead>
                        <TableHead />
                      </TableRow>
                    </TableHeader>
                    <TableBody>
                      {pagedVisits.map((visit) => {
                        const patient = patientsById[visit.patient_id];
                        const receptionist = visit.created_by
                          ? receptionistsById[visit.created_by]
                          : null;
                        return (
                          <TableRow key={visit.id}>
                            <TableCell className="whitespace-nowrap">
                              {formatDisplayTime(visit.created_at)}
                            </TableCell>
                            <TableCell className="whitespace-nowrap font-mono">
                              {visit.queue_token}
                            </TableCell>
                            <TableCell className="max-w-[160px] truncate font-medium text-foreground">
                              {patient ? patient.full_name : '…'}
                            </TableCell>
                            <TableCell className="whitespace-nowrap font-mono text-xs">
                              {patient ? patient.mr_number : '…'}
                            </TableCell>
                            <TableCell className="whitespace-nowrap">
                              {patient
                                ? `${patient.age_years} / ${
                                    patient.gender
                                      ? patient.gender[0].toUpperCase() + patient.gender.slice(1)
                                      : '—'
                                  }`
                                : '…'}
                            </TableCell>
                            <TableCell className="whitespace-nowrap">
                              {patient?.phone_number || '—'}
                            </TableCell>
                            <TableCell className="max-w-[160px]">
                              <VisitProcedureDisplay visit={visit} className="truncate" />
                            </TableCell>
                            <TableCell>
                              {visit.doctor_user_id ? (
                                <Badge variant="success">Assigned</Badge>
                              ) : (
                                <Badge variant="warning">Unassigned</Badge>
                              )}
                            </TableCell>
                            <TableCell>
                              <Badge
                                variant={VISIT_STATUS_BADGE_VARIANT[visit.status] ?? 'outline'}
                                className="capitalize"
                              >
                                {visit.status.replaceAll('_', ' ')}
                              </Badge>
                            </TableCell>
                            <TableCell className="max-w-[140px] truncate">
                              {visit.created_by ? receptionist?.full_name || '…' : '—'}
                            </TableCell>
                            <TableCell className="whitespace-nowrap text-right font-medium tabular-nums">
                              {formatPkr(visit.amount)}
                            </TableCell>
                            <TableCell>
                              <div className="flex justify-end gap-2">
                                <Button
                                  size="sm"
                                  variant="outline"
                                  onClick={() => setEditingVisit(visit)}
                                  disabled={!patient}
                                  title="Correct this slip's details"
                                >
                                  <Pencil className="h-3.5 w-3.5" />
                                </Button>
                                <Button
                                  size="sm"
                                  variant="outline"
                                  onClick={() => setDeletingVisit(visit)}
                                  title="Delete this visit"
                                >
                                  <Trash2 className="h-3.5 w-3.5" />
                                </Button>
                              </div>
                            </TableCell>
                          </TableRow>
                        );
                      })}
                    </TableBody>
                  </Table>

                  {pageCount > 1 ? (
                    <div className="flex items-center justify-between text-sm text-muted-foreground">
                      <span>
                        Page {currentPage} of {pageCount} · {filteredVisits.length} visit
                        {filteredVisits.length === 1 ? '' : 's'}
                      </span>
                      <div className="flex gap-2">
                        <Button
                          size="sm"
                          variant="outline"
                          disabled={currentPage <= 1}
                          onClick={() => setPage((p) => Math.max(1, p - 1))}
                        >
                          Previous
                        </Button>
                        <Button
                          size="sm"
                          variant="outline"
                          disabled={currentPage >= pageCount}
                          onClick={() => setPage((p) => Math.min(pageCount, p + 1))}
                        >
                          Next
                        </Button>
                      </div>
                    </div>
                  ) : null}
                </>
              )}
            </>
          )}
        </CardContent>
      </Card>

      <LeadsSection />

      {editingVisit ? (
        <EditVisitDialog
          visit={editingVisit}
          patient={patientsById[editingVisit.patient_id]}
          onClose={() => setEditingVisit(null)}
        />
      ) : null}
      {deletingVisit ? (
        <DeleteVisitDialog visit={deletingVisit} onClose={() => setDeletingVisit(null)} />
      ) : null}
    </div>
  );
}
