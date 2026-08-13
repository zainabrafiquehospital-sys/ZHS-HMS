'use client';

import { useMemo, useState } from 'react';
import { useForm } from 'react-hook-form';
import { zodResolver } from '@hookform/resolvers/zod';
import { ClipboardList, Pill, Printer, Receipt, Search, Wallet } from 'lucide-react';
import {
  useAdminVisitsForDay,
  usePatientsForVisits,
  useReceptionistsForVisits,
} from '@/features/admin/hooks/useAdminOverview';
import {
  useMedicineBillsForDay,
  usePrintMedicineBill,
  useRecordMedicineBillPayment,
  useUsersForMedicineBills,
  useVisitsForMedicineBills,
} from '@/features/pharmacy/hooks/usePharmacy';
import { recordMedicineBillPaymentSchema } from '@/features/pharmacy/schemas/pharmacySchemas';
import { PendingApprovals } from '@/features/admin/components/PendingApprovals';
import { DateNavigator } from '@/features/admin/components/DateNavigator';
import { LeadsSection } from '@/features/admin/components/LeadsSection';
import { RevenueByActorPieChart } from '@/features/admin/components/RevenueByActorPieChart';
import { computeRevenueByActor, resolveActorSlices } from '@/features/admin/utils/revenueByActor';
import { Card, CardContent, CardHeader } from '@/shared/components/ui/Card';
import { Badge } from '@/shared/components/ui/Badge';
import { Button } from '@/shared/components/ui/Button';
import { ConfirmDialog } from '@/shared/components/ui/ConfirmDialog';
import { Input } from '@/shared/components/ui/Input';
import { Label } from '@/shared/components/ui/Label';
import { Tabs } from '@/shared/components/ui/Tabs';
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
import { useDebouncedValue } from '@/shared/hooks/useDebouncedValue';
import { formatDisplayDate, formatDisplayTime, todayDisplayDayKey } from '@/utils/timezone';
import { VISIT_STATUS_BADGE_VARIANT } from '@/shared/constants/visitStatus';

const OVERVIEW_TABS = [
  { value: 'visits', label: 'Visits' },
  { value: 'medicine_bills', label: 'Medicine Bills' },
];

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
    defaultValues: { amount: '' },
  });

  async function onSubmit(values) {
    setError(null);
    try {
      await recordPayment.mutateAsync({ billId: bill.id, amount: values.amount });
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
          {error ? <p className="text-xs text-destructive">{error}</p> : null}
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

  const totalRevenue = useMemo(
    () => (bills ?? []).reduce((sum, bill) => sum + Number(bill.total_amount), 0),
    [bills],
  );
  const revenueByActor = useMemo(
    () => resolveActorSlices(computeRevenueByActor(bills, 'total_amount'), usersById),
    [bills, usersById],
  );

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
      <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
        <SummaryTile icon={Pill} label="Total Bills" value={rows.length} />
        <SummaryTile icon={Receipt} label="Total Revenue" value={formatPkr(totalRevenue)} />
      </div>

      <div>
        <p className="mb-2 text-xs font-medium text-muted-foreground">Revenue by Receptionist</p>
        <RevenueByActorPieChart data={revenueByActor} />
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
    </div>
  );
}

export function AdminOverview() {
  const [selectedDate, setSelectedDate] = useState(todayDisplayDayKey());
  const [searchTerm, setSearchTerm] = useState('');
  const [page, setPage] = useState(1);
  const [activeTab, setActiveTab] = useState('visits');

  const { visits, isLoading, isError, error, refetch } = useAdminVisitsForDay(selectedDate);
  const patientsById = usePatientsForVisits(visits);
  const receptionistsById = useReceptionistsForVisits(visits);
  const debouncedSearch = useDebouncedValue(searchTerm, 200);

  const totalRevenue = useMemo(
    () => visits.reduce((sum, visit) => sum + Number(visit.amount), 0),
    [visits],
  );
  const revenueByActor = useMemo(
    () => resolveActorSlices(computeRevenueByActor(visits, 'amount'), receptionistsById),
    [visits, receptionistsById],
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

      <Card>
        <CardHeader className="flex-col items-start gap-3 sm:flex-row sm:items-center sm:justify-between">
          <Tabs value={activeTab} onValueChange={setActiveTab} tabs={OVERVIEW_TABS} />
          <DateNavigator selectedDate={selectedDate} onChange={handleDateChange} />
        </CardHeader>
        <CardContent className="flex flex-col gap-5">
          {activeTab === 'medicine_bills' ? (
            <MedicineBillsPanel selectedDate={selectedDate} />
          ) : isLoading ? (
            <PageLoader label="Loading visit activity" />
          ) : isError ? (
            <PageError error={error} reset={refetch} message="Couldn't load visit activity." />
          ) : (
            <>
              <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
                <SummaryTile icon={ClipboardList} label="Total Visits" value={visits.length} />
                <SummaryTile icon={Receipt} label="Total Revenue" value={formatPkr(totalRevenue)} />
              </div>

              <div>
                <p className="mb-2 text-xs font-medium text-muted-foreground">
                  Revenue by Receptionist
                </p>
                <RevenueByActorPieChart data={revenueByActor} />
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
                            <TableCell className="max-w-[160px] truncate">
                              {visit.procedure}
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
    </div>
  );
}
