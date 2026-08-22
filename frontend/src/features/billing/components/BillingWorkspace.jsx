'use client';

import { useEffect, useState } from 'react';
import { useForm } from 'react-hook-form';
import { zodResolver } from '@hookform/resolvers/zod';
import { Printer, CheckCircle2, XCircle, ReceiptText, Wallet } from 'lucide-react';
import {
  useVisit,
  usePendingItems,
  useInvoicesForVisit,
  usePatientsForVisits,
  useApprovePendingItem,
  useRejectPendingItem,
  useGenerateInvoice,
  useRecordPayment,
  useRecordVisitPayment,
  usePrintInvoice,
} from '@/features/billing/hooks/useBilling';
import { generateInvoiceSchema, recordPaymentSchema } from '@/features/billing/schemas/billingSchemas';
import { VisitProcedureDisplay } from '@/features/visits/components/VisitProcedureDisplay';
import { Card, CardContent, CardHeader, CardTitle } from '@/shared/components/ui/Card';
import { Button } from '@/shared/components/ui/Button';
import { Input } from '@/shared/components/ui/Input';
import { Label } from '@/shared/components/ui/Label';
import { Badge } from '@/shared/components/ui/Badge';
import { PageLoader } from '@/shared/components/PageLoader';
import { PaymentMethodSelect } from '@/shared/components/PaymentMethodSelect';
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/shared/components/ui/Table';
import { PAYMENT_METHOD_LABELS } from '@/shared/constants/paymentMethod';

function money(amount) {
  return `Rs. ${Number(amount).toFixed(2)}`;
}

function PendingItemsPanel({ visitId }) {
  const { data: items, isLoading } = usePendingItems(visitId);
  const approve = useApprovePendingItem(visitId);
  const reject = useRejectPendingItem(visitId);
  const [actionError, setActionError] = useState(null);

  async function handle(action, itemId) {
    setActionError(null);
    try {
      await action.mutateAsync(itemId);
    } catch (error) {
      setActionError(error.message || 'Unable to update this item.');
    }
  }

  const pendingOnly = (items ?? []).filter((item) => item.status === 'pending');
  const decided = (items ?? []).filter((item) => item.status !== 'pending');

  if (isLoading) return <PageLoader label="Loading pending charges" />;

  return (
    <Card>
      <CardHeader>
        <CardTitle>Doctor-Requested Charges</CardTitle>
      </CardHeader>
      <CardContent className="flex flex-col gap-4">
        {(items ?? []).length === 0 ? (
          <p className="text-sm text-muted-foreground">No additional charges submitted.</p>
        ) : (
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>Description</TableHead>
                <TableHead>Amount</TableHead>
                <TableHead>Status</TableHead>
                <TableHead />
              </TableRow>
            </TableHeader>
            <TableBody>
              {[...pendingOnly, ...decided].map((item) => (
                <TableRow key={item.id}>
                  <TableCell>{item.description}</TableCell>
                  <TableCell>{money(item.amount)}</TableCell>
                  <TableCell>
                    <Badge
                      variant={
                        item.status === 'approved' || item.status === 'billed'
                          ? 'success'
                          : item.status === 'rejected'
                            ? 'destructive'
                            : 'outline'
                      }
                      className="capitalize"
                    >
                      {item.status}
                    </Badge>
                  </TableCell>
                  <TableCell>
                    {item.status === 'pending' ? (
                      <div className="flex gap-2">
                        <Button
                          size="sm"
                          variant="outline"
                          onClick={() => handle(approve, item.id)}
                          disabled={approve.isPending || reject.isPending}
                        >
                          <CheckCircle2 className="h-4 w-4" />
                          Approve
                        </Button>
                        <Button
                          size="sm"
                          variant="ghost"
                          onClick={() => handle(reject, item.id)}
                          disabled={approve.isPending || reject.isPending}
                        >
                          <XCircle className="h-4 w-4" />
                          Reject
                        </Button>
                      </div>
                    ) : null}
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        )}
        {actionError ? <p className="text-sm text-destructive">{actionError}</p> : null}
      </CardContent>
    </Card>
  );
}

function GenerateInvoiceForm({ visitId, visit }) {
  const generateInvoice = useGenerateInvoice(visitId);
  const [submitError, setSubmitError] = useState(null);
  const {
    register,
    handleSubmit,
    reset,
    formState: { errors, isSubmitting },
  } = useForm({
    resolver: zodResolver(generateInvoiceSchema),
    // Pre-filled from the amount Reception already entered at
    // registration — Reception typed it once, Billing never asks
    // again (still editable/overridable here if it needs adjusting).
    // discount_amount/initial_payment_amount both start blank — blank
    // always means "not applicable", never a hidden "pay in full" or
    // "no discount" shortcut (see generateInvoiceSchema's comment).
    //
    // `base_description` (2026-08-21 revision): for an itemized visit,
    // a comma-joined suggestion of its procedure names — this is a
    // one-time, freely-editable *prefill* for the Invoice's own
    // separate description field, not a display of the visit's
    // procedures (that's `visit.procedure_items` below, rendered
    // itemized) — so joining names here for a starting-point suggestion
    // the receptionist can retype before submitting is a different
    // concern from the "never a joined summary string" display rule.
    defaultValues: {
      base_description:
        visit?.procedure_items?.length > 0
          ? visit.procedure_items.map((item) => item.name).join(', ')
          : (visit?.procedure ?? ''),
      base_amount: visit?.amount ?? '',
      discount_amount: '',
      discount_reason: '',
      initial_payment_amount: '',
      initial_payment_method: '',
    },
  });

  async function onSubmit(values) {
    setSubmitError(null);
    try {
      await generateInvoice.mutateAsync({
        visit_id: visitId,
        ...values,
        // The backend's initial_payment_method is a strict enum
        // (PaymentMethod | None) — unlike discount_reason's plain
        // string field, an empty string is not a valid value, so a
        // blank/untouched select must become null, never "".
        initial_payment_method: values.initial_payment_method || null,
      });
      reset({
        base_description: '',
        base_amount: '',
        discount_amount: '',
        discount_reason: '',
        initial_payment_amount: '',
        initial_payment_method: '',
      });
    } catch (error) {
      setSubmitError(error.message || 'Unable to generate invoice.');
    }
  }

  return (
    <Card>
      <CardHeader>
        <CardTitle>Generate Invoice</CardTitle>
      </CardHeader>
      <CardContent className="flex flex-col gap-4">
        <form onSubmit={handleSubmit(onSubmit)} className="flex flex-col gap-4">
          <div className="flex flex-col gap-4 sm:flex-row sm:items-end">
            <div className="flex flex-1 flex-col gap-1.5">
              <Label htmlFor="base_description">Description</Label>
              <Input
                id="base_description"
                placeholder="e.g. Consultation Fee"
                {...register('base_description')}
              />
              {errors.base_description ? (
                <p className="text-xs text-destructive">{errors.base_description.message}</p>
              ) : null}
            </div>
            <div className="flex flex-col gap-1.5">
              <Label htmlFor="base_amount">Amount (Rs.)</Label>
              <Input id="base_amount" type="number" step="0.01" {...register('base_amount')} />
              {errors.base_amount ? (
                <p className="text-xs text-destructive">{errors.base_amount.message}</p>
              ) : null}
            </div>
          </div>
          {/* Optional flat discount, applied once at generation time —
              a reason is required as soon as an amount is entered (see
              generateInvoiceSchema's cross-field refine). */}
          <div className="flex flex-col gap-4 sm:flex-row sm:items-end">
            <div className="flex flex-col gap-1.5">
              <Label htmlFor="discount_amount">Discount (Rs.)</Label>
              <Input
                id="discount_amount"
                type="number"
                step="0.01"
                placeholder="0.00"
                className="sm:w-32"
                {...register('discount_amount')}
              />
              {errors.discount_amount ? (
                <p className="text-xs text-destructive">{errors.discount_amount.message}</p>
              ) : null}
            </div>
            <div className="flex flex-1 flex-col gap-1.5">
              <Label htmlFor="discount_reason">Discount Reason</Label>
              <Input
                id="discount_reason"
                placeholder="Required when a discount is applied"
                {...register('discount_reason')}
              />
              {errors.discount_reason ? (
                <p className="text-xs text-destructive">{errors.discount_reason.message}</p>
              ) : null}
            </div>
          </div>
          {/* Optional payment collected in the same step as generation
              — leave blank to create the invoice unpaid, as before;
              typing the same amount as the total records it as paid
              in full immediately. Recorded atomically with the invoice
              itself (see BillingService.generate_invoice's docstring)
              — never a separate, possibly-failing second request. */}
          <div className="flex flex-col gap-4 sm:flex-row sm:items-end">
            <div className="flex flex-col gap-1.5">
              <Label htmlFor="initial_payment_amount">Advance Received (Rs.)</Label>
              <Input
                id="initial_payment_amount"
                type="number"
                step="0.01"
                placeholder="0.00"
                className="sm:w-40"
                {...register('initial_payment_amount')}
              />
              {errors.initial_payment_amount ? (
                <p className="text-xs text-destructive">{errors.initial_payment_amount.message}</p>
              ) : null}
            </div>
            <div className="sm:w-44">
              <PaymentMethodSelect
                id="initial_payment_method"
                registration={register('initial_payment_method')}
                error={errors.initial_payment_method}
              />
            </div>
            <Button type="submit" disabled={isSubmitting} className="sm:self-end">
              <ReceiptText className="h-4 w-4" />
              {isSubmitting ? 'Generating…' : 'Generate Invoice'}
            </Button>
          </div>
        </form>
        {submitError ? (
          <p className="rounded-md bg-destructive/10 px-3 py-2 text-sm text-destructive">
            {submitError}
          </p>
        ) : null}
      </CardContent>
    </Card>
  );
}

function RecordPaymentRow({ invoice, visitId }) {
  const recordPayment = useRecordPayment(visitId);
  const printInvoice = usePrintInvoice();
  const [error, setError] = useState(null);
  // Same Total Amount / Received / Pending framing as the print
  // receipt (shared/printing/service.py's render_invoice_receipt) —
  // Total Amount is the pre-discount subtotal, recovered the same way
  // (total_amount is already post-discount on the stored Invoice).
  const totalAmount = Number(invoice.total_amount) + Number(invoice.discount_amount);
  const pending = Number(invoice.total_amount) - Number(invoice.amount_paid);
  const balanceDueValue = pending > 0 ? pending.toFixed(2) : '';
  // Distinct payment methods used so far, in first-payment order — same
  // "Paid via" summary the print receipt shows (2026-08-19 addition).
  const paidViaMethods = [...new Set((invoice.payments ?? []).map((p) => p.payment_method))];
  const {
    register,
    handleSubmit,
    reset,
    setValue,
    formState: { errors, isSubmitting, isDirty },
  } = useForm({
    resolver: zodResolver(recordPaymentSchema),
    // Defaults to the full remaining balance (still editable) rather
    // than an always-pays-full button — see the module's Phase 3 note.
    defaultValues: { amount: balanceDueValue, payment_method: '' },
  });

  // Keeps the amount field pinned to the current remaining balance as
  // it changes underneath (a partial payment elsewhere, a refetch) —
  // but only while the receptionist hasn't started typing a different
  // amount, so an in-progress edit is never clobbered. `setValue`
  // rather than `reset` — a full reset would also wipe out whatever
  // payment_method the receptionist already picked.
  useEffect(() => {
    if (!isDirty) {
      setValue('amount', balanceDueValue);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [balanceDueValue]);

  const isOpen = invoice.status === 'pending_payment' || invoice.status === 'partially_paid';

  async function onSubmit(values) {
    setError(null);
    try {
      await recordPayment.mutateAsync({
        invoiceId: invoice.id,
        amount: values.amount,
        paymentMethod: values.payment_method,
      });
      reset({ amount: '', payment_method: '' });
    } catch (submitError) {
      setError(submitError.message || 'Unable to record payment.');
    }
  }

  async function handlePrint() {
    setError(null);
    try {
      await printInvoice.mutateAsync(invoice.id);
    } catch (printError) {
      setError(printError.message || 'Unable to print invoice.');
    }
  }

  return (
    <div className="flex flex-col gap-3 border-b border-border pb-4 last:border-b-0 last:pb-0">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div>
          <p className="text-sm font-medium text-foreground">
            Invoice {invoice.id.slice(0, 8)} — Total Amount {money(totalAmount)}
          </p>
          <p className="text-xs text-muted-foreground">
            {invoice.line_items?.length ?? 0} line item(s) · Received: {money(invoice.amount_paid)}{' '}
            · Pending: {money(pending)}
            {paidViaMethods.length > 0
              ? ` · Paid via: ${paidViaMethods.map((m) => PAYMENT_METHOD_LABELS[m] ?? m).join(', ')}`
              : ''}
          </p>
          {Number(invoice.discount_amount) > 0 ? (
            <p className="text-xs text-muted-foreground">
              Discount applied: {money(invoice.discount_amount)}
              {invoice.discount_reason ? ` — ${invoice.discount_reason}` : ''}
            </p>
          ) : null}
        </div>
        <div className="flex items-center gap-2">
          <Badge
            variant={
              invoice.status === 'paid'
                ? 'success'
                : invoice.status === 'partially_paid'
                  ? 'warning'
                  : invoice.status === 'cancelled'
                    ? 'destructive'
                    : 'outline'
            }
            className="capitalize"
          >
            {invoice.status.replaceAll('_', ' ')}
          </Badge>
          <Button
            type="button"
            size="sm"
            variant="outline"
            onClick={handlePrint}
            disabled={printInvoice.isPending}
          >
            <Printer className="h-4 w-4" />
            Print Receipt
          </Button>
        </div>
      </div>

      {isOpen ? (
        <div className="flex flex-col gap-2">
          {/* This is a later top-up toward what's still Pending — the
              invoice's first payment is normally already recorded via
              Generate Invoice's own "Advance Received" field; this row
              is for a patient coming back to pay the rest. */}
          <p className="text-xs text-muted-foreground">
            Record an additional payment toward the remaining balance.
          </p>
          <form onSubmit={handleSubmit(onSubmit)} className="flex items-end gap-3">
            <div className="flex flex-col gap-1.5">
              <Label htmlFor={`amount-${invoice.id}`}>Additional Payment (Rs.)</Label>
              <Input
                id={`amount-${invoice.id}`}
                type="number"
                step="0.01"
                {...register('amount')}
              />
              {errors.amount ? (
                <p className="text-xs text-destructive">{errors.amount.message}</p>
              ) : null}
            </div>
            <div className="w-40">
              <PaymentMethodSelect
                id={`payment-method-${invoice.id}`}
                registration={register('payment_method')}
                error={errors.payment_method}
              />
            </div>
            <Button type="submit" size="sm" disabled={isSubmitting}>
              <Wallet className="h-4 w-4" />
              {isSubmitting ? 'Recording…' : 'Record Additional Payment'}
            </Button>
          </form>
        </div>
      ) : null}

      {error ? <p className="text-xs text-destructive">{error}</p> : null}
    </div>
  );
}

function InvoicesPanel({ visitId }) {
  const { data: invoices, isLoading } = useInvoicesForVisit(visitId);

  if (isLoading) return <PageLoader label="Loading invoices" />;

  return (
    <Card>
      <CardHeader>
        <CardTitle>Invoices</CardTitle>
      </CardHeader>
      <CardContent className="flex flex-col gap-4">
        {(invoices ?? []).length === 0 ? (
          <p className="text-sm text-muted-foreground">No invoices generated yet for this visit.</p>
        ) : (
          invoices.map((invoice) => (
            <RecordPaymentRow key={invoice.id} invoice={invoice} visitId={visitId} />
          ))
        )}
      </CardContent>
    </Card>
  );
}

/** The Visit's own registration-charge payment ledger (2026-08-22
 * addition) — entirely separate from the Generate Invoice/Invoices
 * panels below (which track a different, later financial event: a
 * post-consultation Invoice for additional doctor-requested charges).
 * Renders nothing at all for a visit that predates payment tracking
 * (`payment_status` is `None` — see backend/app/modules/visits/models.
 * py's `Visit.payment_status` docstring), the same "legacy visit,
 * behave exactly as before" branching this whole feature area uses
 * everywhere else (print, the admin edit/delete guard). */
function RegistrationPaymentPanel({ visitId, visit }) {
  const recordPayment = useRecordVisitPayment(visitId);
  const [error, setError] = useState(null);
  const pending = Number(visit.amount) - Number(visit.amount_paid);
  const balanceDueValue = pending > 0 ? pending.toFixed(2) : '';
  const paidViaMethods = [...new Set((visit.payments ?? []).map((p) => p.payment_method))];
  const {
    register,
    handleSubmit,
    reset,
    setValue,
    formState: { errors, isSubmitting, isDirty },
  } = useForm({
    resolver: zodResolver(recordPaymentSchema),
    defaultValues: { amount: balanceDueValue, payment_method: '' },
  });

  // Same "pin the amount field to the current remaining balance until
  // the receptionist starts typing something else" behavior
  // RecordPaymentRow (below) already has, for the identical reason.
  useEffect(() => {
    if (!isDirty) {
      setValue('amount', balanceDueValue);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [balanceDueValue]);

  const isPartiallyPaid = visit.payment_status === 'partially_paid';

  async function onSubmit(values) {
    setError(null);
    try {
      await recordPayment.mutateAsync({
        amount: values.amount,
        paymentMethod: values.payment_method,
      });
      reset({ amount: '', payment_method: '' });
    } catch (submitError) {
      setError(submitError.message || 'Unable to record payment.');
    }
  }

  return (
    <Card>
      <CardHeader>
        <CardTitle>Registration Payment</CardTitle>
      </CardHeader>
      <CardContent className="flex flex-col gap-4">
        <div className="flex flex-wrap items-center justify-between gap-2">
          <div>
            <p className="text-sm font-medium text-foreground">
              Total {money(visit.amount)} · Received {money(visit.amount_paid)} · Pending{' '}
              {money(pending)}
            </p>
            {paidViaMethods.length > 0 ? (
              <p className="text-xs text-muted-foreground">
                Paid via: {paidViaMethods.map((m) => PAYMENT_METHOD_LABELS[m] ?? m).join(', ')}
              </p>
            ) : null}
          </div>
          <Badge
            variant={visit.payment_status === 'paid' ? 'success' : 'warning'}
            className="capitalize"
          >
            {visit.payment_status.replaceAll('_', ' ')}
          </Badge>
        </div>

        {isPartiallyPaid ? (
          <div className="flex flex-col gap-2">
            <p className="text-xs text-muted-foreground">
              Record an additional payment toward the remaining registration balance (e.g. the
              rest of a C-section advance, collected on a later visit).
            </p>
            <form onSubmit={handleSubmit(onSubmit)} className="flex items-end gap-3">
              <div className="flex flex-col gap-1.5">
                <Label htmlFor="visit-payment-amount">Additional Payment (Rs.)</Label>
                <Input id="visit-payment-amount" type="number" step="0.01" {...register('amount')} />
                {errors.amount ? (
                  <p className="text-xs text-destructive">{errors.amount.message}</p>
                ) : null}
              </div>
              <div className="w-40">
                <PaymentMethodSelect
                  id="visit-payment-method"
                  registration={register('payment_method')}
                  error={errors.payment_method}
                />
              </div>
              <Button type="submit" size="sm" disabled={isSubmitting}>
                <Wallet className="h-4 w-4" />
                {isSubmitting ? 'Recording…' : 'Record Additional Payment'}
              </Button>
            </form>
          </div>
        ) : null}

        {error ? <p className="text-xs text-destructive">{error}</p> : null}
      </CardContent>
    </Card>
  );
}

export function BillingWorkspace({ visitId }) {
  const { data: visit, isLoading: isLoadingVisit } = useVisit(visitId);
  const patientsById = usePatientsForVisits(visit ? [visit] : []);
  const patient = visit ? patientsById[visit.patient_id] : undefined;

  if (isLoadingVisit) return <PageLoader label="Loading visit" />;

  return (
    <div className="flex flex-col gap-6">
      <Card>
        <CardHeader>
          <CardTitle>
            Billing
            {patient ? ` — ${patient.full_name} (${patient.mr_number})` : ''}
          </CardTitle>
        </CardHeader>
        <CardContent className="flex flex-wrap gap-4 text-sm text-muted-foreground">
          {visit ? (
            <>
              <span>Queue Token: <span className="font-mono text-foreground">{visit.queue_token}</span></span>
              <span>
                Procedure: <VisitProcedureDisplay visit={visit} className="inline text-foreground" />
              </span>
              <span>
                Status:{' '}
                <Badge variant="outline" className="capitalize">
                  {visit.status.replaceAll('_', ' ')}
                </Badge>
              </span>
            </>
          ) : null}
        </CardContent>
      </Card>

      {visit?.payment_status ? (
        <RegistrationPaymentPanel visitId={visitId} visit={visit} />
      ) : null}
      <PendingItemsPanel visitId={visitId} />
      <GenerateInvoiceForm visitId={visitId} visit={visit} />
      <InvoicesPanel visitId={visitId} />
    </div>
  );
}
