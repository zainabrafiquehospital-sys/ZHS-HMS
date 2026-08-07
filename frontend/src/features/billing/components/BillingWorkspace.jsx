'use client';

import { useState } from 'react';
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
    defaultValues: {
      base_description: visit?.procedure ?? '',
      base_amount: visit?.amount ?? '',
    },
  });

  async function onSubmit(values) {
    setSubmitError(null);
    try {
      await generateInvoice.mutateAsync({ visit_id: visitId, ...values });
      reset({ base_description: '', base_amount: '' });
    } catch (error) {
      setSubmitError(error.message || 'Unable to generate invoice.');
    }
  }

  return (
    <Card>
      <CardHeader>
        <CardTitle>Generate Invoice</CardTitle>
      </CardHeader>
      <CardContent>
        <form onSubmit={handleSubmit(onSubmit)} className="flex flex-col gap-4 sm:flex-row sm:items-end">
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
          <Button type="submit" disabled={isSubmitting}>
            <ReceiptText className="h-4 w-4" />
            {isSubmitting ? 'Generating…' : 'Generate Invoice'}
          </Button>
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

function RecordPaymentRow({ invoice, visitId }) {
  const recordPayment = useRecordPayment(visitId);
  const printInvoice = usePrintInvoice();
  const [error, setError] = useState(null);
  const {
    register,
    handleSubmit,
    reset,
    formState: { errors, isSubmitting },
  } = useForm({
    resolver: zodResolver(recordPaymentSchema),
    defaultValues: { amount: '' },
  });

  const balanceDue = Number(invoice.total_amount) - Number(invoice.amount_paid);
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
            Invoice {invoice.id.slice(0, 8)} — {money(invoice.total_amount)} total,{' '}
            {money(invoice.amount_paid)} paid
          </p>
          <p className="text-xs text-muted-foreground">
            {invoice.line_items?.length ?? 0} line item(s) · Balance due: {money(balanceDue)}
          </p>
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
        <form onSubmit={handleSubmit(onSubmit)} className="flex items-end gap-3">
          <div className="flex flex-col gap-1.5">
            <Label htmlFor={`amount-${invoice.id}`}>Record Payment (Rs.)</Label>
            <Input
              id={`amount-${invoice.id}`}
              type="number"
              step="0.01"
              {...register('amount')}
            />
            {errors.amount ? <p className="text-xs text-destructive">{errors.amount.message}</p> : null}
          </div>
          <Button type="submit" size="sm" disabled={isSubmitting}>
            <Wallet className="h-4 w-4" />
            {isSubmitting ? 'Recording…' : 'Record Payment'}
          </Button>
        </form>
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
