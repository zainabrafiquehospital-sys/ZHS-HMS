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
  usePrintInvoice,
} from '@/features/billing/hooks/useBilling';
import { generateInvoiceSchema, recordPaymentSchema } from '@/features/billing/schemas/billingSchemas';
import { Card, CardContent, CardHeader, CardTitle } from '@/shared/components/ui/Card';
import { Button } from '@/shared/components/ui/Button';
import { Input } from '@/shared/components/ui/Input';
import { Label } from '@/shared/components/ui/Label';
import { Badge } from '@/shared/components/ui/Badge';
import { PageLoader } from '@/shared/components/PageLoader';
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/shared/components/ui/Table';

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
    defaultValues: {
      base_description: visit?.procedure ?? '',
      base_amount: visit?.amount ?? '',
      discount_amount: '',
      discount_reason: '',
      initial_payment_amount: '',
    },
  });

  async function onSubmit(values) {
    setSubmitError(null);
    try {
      await generateInvoice.mutateAsync({ visit_id: visitId, ...values });
      reset({
        base_description: '',
        base_amount: '',
        discount_amount: '',
        discount_reason: '',
        initial_payment_amount: '',
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
  const {
    register,
    handleSubmit,
    reset,
    formState: { errors, isSubmitting, isDirty },
  } = useForm({
    resolver: zodResolver(recordPaymentSchema),
    // Defaults to the full remaining balance (still editable) rather
    // than an always-pays-full button — see the module's Phase 3 note.
    defaultValues: { amount: balanceDueValue },
  });

  // Keeps the field pinned to the current remaining balance as it
  // changes underneath (a partial payment elsewhere, a refetch) —
  // but only while the receptionist hasn't started typing a different
  // amount, so an in-progress edit is never clobbered.
  useEffect(() => {
    if (!isDirty) {
      reset({ amount: balanceDueValue });
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [balanceDueValue]);

  const isOpen = invoice.status === 'pending_payment' || invoice.status === 'partially_paid';

  async function onSubmit(values) {
    setError(null);
    try {
      await recordPayment.mutateAsync({ invoiceId: invoice.id, amount: values.amount });
      reset({ amount: '' });
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
              <span>Procedure: <span className="text-foreground">{visit.procedure}</span></span>
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

      <PendingItemsPanel visitId={visitId} />
      <GenerateInvoiceForm visitId={visitId} visit={visit} />
      <InvoicesPanel visitId={visitId} />
    </div>
  );
}
