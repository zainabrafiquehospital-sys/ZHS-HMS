'use client';

import { useState } from 'react';
import { ArrowLeft, Printer, Search } from 'lucide-react';
import {
  usePatientHistory,
  useHistoryVisitList,
} from '@/features/patients/hooks/usePatientHistory';
import { usePatientsForVisits } from '@/features/patients/hooks/usePatientsForVisits';
import { usePrintRegistrationSlip } from '@/features/reception/hooks/useReception';
import { usePrintInvoice } from '@/features/billing/hooks/useBilling';
import { usePrintLabBill } from '@/features/lab/hooks/useLab';
import { usePrintMedicineBill } from '@/features/pharmacy/hooks/usePharmacy';
import { useAuth } from '@/features/auth/hooks/useAuth';
import {
  ALL_VITALS_FIELDS,
  VITAL_FIELD_LABELS,
  vitalFieldUnit,
  VITALS_FIELDS_WITH_SEVERITY,
  SEVERITY_BADGE_VARIANT,
  SEVERITY_LABEL,
  getVitalSeverity,
} from '@/features/vitals/utils/vitalsSeverity';
import { VisitProcedureDisplay } from '@/features/visits/components/VisitProcedureDisplay';
import { VISIT_STATUS_BADGE_VARIANT } from '@/shared/constants/visitStatus';
import { Card, CardContent, CardHeader, CardTitle } from '@/shared/components/ui/Card';
import { Badge } from '@/shared/components/ui/Badge';
import { Button } from '@/shared/components/ui/Button';
import { Input } from '@/shared/components/ui/Input';
import { Label } from '@/shared/components/ui/Label';
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
import { formatDisplayDate, formatDisplayTime, displayDayKey } from '@/utils/timezone';

// Matches usePatientDirectory's own GET /patients page_size default —
// this list is just as hospital-wide/unbounded, so it gets the exact
// same real server-side pagination treatment, never a client-side
// approximation over a capped fetch.
const LIST_PAGE_SIZE = 20;

const currencyFormatter = new Intl.NumberFormat('en-US', {
  minimumFractionDigits: 2,
  maximumFractionDigits: 2,
});

function money(amount) {
  return `Rs. ${currencyFormatter.format(Number(amount))}`;
}

function dateTime(isoTimestamp) {
  return `${formatDisplayDate(displayDayKey(isoTimestamp))} at ${formatDisplayTime(isoTimestamp)}`;
}

/** Every money-status vocabulary in this app (Invoice/LabBill/
 * MedicineBill) shares the same three practical states this badge
 * cares about — mirrors AdminOverview.jsx's own identical inline
 * paid/partially_paid/else mapping for its Lab/Medicine Bills tabs,
 * reused here a third time rather than introducing a new shared
 * constant for what is still just this one small heuristic. */
function MoneyStatusBadge({ status }) {
  const variant =
    status === 'paid' ? 'success' : status === 'partially_paid' ? 'warning' : 'outline';
  return (
    <Badge variant={variant} className="capitalize">
      {status.replaceAll('_', ' ')}
    </Badge>
  );
}

/** Wraps one of this app's existing `usePrint*` mutations (registration
 * slip / invoice receipt / lab bill / medicine bill — each already
 * fetches its own HTML via the Central Print Service and hands it to
 * `openAndPrintHtml`, completely unmodified here) with the same
 * "one print job in flight at a time, per-row loading state, inline
 * error message" boilerplate every existing print button in this app
 * already repeats individually (MyRegistrations.jsx, MyLabBills.jsx,
 * MyMedicineBills.jsx, PatientVisitHistoryDialog.jsx,
 * BillingWorkspace.jsx) — factored into one local helper only because
 * this one page now hosts four of these side by side, never a new
 * print mechanism of its own. Each section keeps its own independent
 * instance (printing a lab bill never disables the visits table's own
 * buttons), matching how these were always independent on their
 * original, separate pages. */
function usePrintAction(mutateAsync) {
  const [printingId, setPrintingId] = useState(null);
  const [error, setError] = useState(null);

  async function handlePrint(id) {
    if (printingId) return;
    setError(null);
    setPrintingId(id);
    try {
      await mutateAsync(id);
    } catch (err) {
      setError(err.message || 'Unable to print — you can try again.');
    } finally {
      setPrintingId(null);
    }
  }

  return { printingId, error, handlePrint };
}

/** Same `<Button size="sm" variant="outline">` + `Printer` icon shape
 * every print action in this app already uses — never a new button
 * style for this page specifically. */
function PrintButton({ label, id, printingId, onPrint }) {
  const isPrintingThisRow = printingId === id;
  return (
    <Button size="sm" variant="outline" disabled={Boolean(printingId)} onClick={() => onPrint(id)}>
      <Printer className="h-3.5 w-3.5" />
      {isPrintingThisRow ? 'Printing…' : label}
    </Button>
  );
}

function SectionCard({ title, count, children }) {
  return (
    <Card>
      <CardHeader>
        <CardTitle>
          {title} ({count})
        </CardTitle>
      </CardHeader>
      <CardContent>{children}</CardContent>
    </Card>
  );
}

/** `GET /reception/visits/{id}/slip/print` (the same endpoint
 * MyRegistrations.jsx/PatientVisitHistoryDialog.jsx's own "Print Slip"
 * buttons call) requires `reception:register_visit` OR
 * `reception:view_slip` — see backend/app/modules/reception/router.py's
 * `print_registration_slip`. That's a *different* permission than the
 * `visits:read` this whole section is already gated on server-side
 * (backend/app/modules/patient_history/router.py), so unlike the
 * Invoices/Lab Bills/Pharmacy Bills sections below (whose own print
 * endpoints reuse the exact same read permission that already gates
 * showing the section at all), this button needs its own extra
 * frontend check — Vitals staff, for instance, can see this Visits
 * section (holds visits:read) but holds neither reception permission,
 * so must never see a button that would only 403 if clicked. */
function VisitsSection({ visits }) {
  const { hasPermission } = useAuth();
  const printSlip = usePrintRegistrationSlip();
  const { printingId, error, handlePrint } = usePrintAction((visitId) =>
    printSlip.mutateAsync(visitId),
  );
  const canPrintSlip =
    hasPermission('reception:register_visit') || hasPermission('reception:view_slip');

  if (!visits?.length) return null;
  return (
    <SectionCard title="Visits" count={visits.length}>
      {error ? <p className="mb-3 text-sm text-destructive">{error}</p> : null}
      <Table>
        <TableHeader>
          <TableRow>
            <TableHead>Date</TableHead>
            <TableHead>Queue Token</TableHead>
            <TableHead>Procedure</TableHead>
            <TableHead>Status</TableHead>
            <TableHead className="text-right">Amount</TableHead>
            {canPrintSlip ? <TableHead /> : null}
          </TableRow>
        </TableHeader>
        <TableBody>
          {visits.map((visit) => (
            <TableRow key={visit.id}>
              <TableCell className="whitespace-nowrap">
                {formatDisplayDate(displayDayKey(visit.created_at))}
              </TableCell>
              <TableCell className="whitespace-nowrap font-mono text-xs">
                {visit.queue_token}
              </TableCell>
              <TableCell className="max-w-[200px]">
                <VisitProcedureDisplay visit={visit} className="truncate" />
              </TableCell>
              <TableCell>
                <Badge
                  variant={VISIT_STATUS_BADGE_VARIANT[visit.status] ?? 'outline'}
                  className="capitalize"
                >
                  {visit.status.replaceAll('_', ' ')}
                </Badge>
              </TableCell>
              <TableCell className="whitespace-nowrap text-right font-medium tabular-nums">
                {money(visit.amount)}
              </TableCell>
              {canPrintSlip ? (
                <TableCell>
                  <PrintButton
                    label="Print Slip"
                    id={visit.id}
                    printingId={printingId}
                    onPrint={handlePrint}
                  />
                </TableCell>
              ) : null}
            </TableRow>
          ))}
        </TableBody>
      </Table>
    </SectionCard>
  );
}

function VitalsSection({ vitals, ageYears }) {
  if (vitals === null || vitals === undefined || vitals.length === 0) return null;
  return (
    <SectionCard title="Vitals" count={vitals.length}>
      <div className="flex flex-col gap-3">
        {vitals.map((record) => (
          <div key={record.id} className="rounded-md border border-border p-3">
            <p className="mb-2 text-xs text-muted-foreground">
              Recorded {dateTime(record.created_at)}
            </p>
            <div className="flex flex-wrap gap-x-5 gap-y-2">
              {ALL_VITALS_FIELDS.filter(
                (field) => record[field] !== null && record[field] !== undefined,
              ).map((field) => {
                const severity = VITALS_FIELDS_WITH_SEVERITY.includes(field)
                  ? getVitalSeverity(field, record[field], {
                      ageYears,
                      temperatureUnit: record.temperature_unit,
                    })
                  : { level: null };
                return (
                  <div key={field} className="flex items-center gap-1.5 text-sm">
                    <span className="text-muted-foreground">{VITAL_FIELD_LABELS[field]}:</span>
                    <span className="font-medium text-foreground">
                      {record[field]} {vitalFieldUnit(field, record.temperature_unit)}
                    </span>
                    {severity.level && severity.level !== 'normal' ? (
                      <Badge
                        variant={SEVERITY_BADGE_VARIANT[severity.level]}
                        className="text-[10px]"
                      >
                        {SEVERITY_LABEL[severity.level]}
                      </Badge>
                    ) : null}
                  </div>
                );
              })}
            </div>
          </div>
        ))}
      </div>
    </SectionCard>
  );
}

function ConsultationsSection({ consultations }) {
  if (!consultations?.length) return null;
  return (
    <SectionCard title="Consultations" count={consultations.length}>
      <div className="flex flex-col gap-3">
        {consultations.map((consultation) => (
          <div key={consultation.id} className="rounded-md border border-border p-3">
            <div className="mb-2 flex items-center justify-between gap-2">
              <p className="text-xs text-muted-foreground">
                {dateTime(consultation.created_at)}
                {consultation.completed_at
                  ? ` · completed ${dateTime(consultation.completed_at)}`
                  : ''}
              </p>
              <Badge variant="outline" className="capitalize">
                {consultation.status.replaceAll('_', ' ')}
              </Badge>
            </div>
            {consultation.diagnosis ? (
              <p className="text-sm">
                <span className="text-muted-foreground">Diagnosis: </span>
                {consultation.diagnosis}
              </p>
            ) : null}
            {consultation.notes ? (
              <p className="text-sm">
                <span className="text-muted-foreground">Notes: </span>
                {consultation.notes}
              </p>
            ) : null}
            {consultation.prescription ? (
              <p className="text-sm">
                <span className="text-muted-foreground">Prescription: </span>
                {consultation.prescription}
              </p>
            ) : null}
          </div>
        ))}
      </div>
    </SectionCard>
  );
}

/** `GET /billing/invoices/{id}/print` requires `billing:read` — the
 * exact same permission this whole Invoices section is already gated
 * on server-side (backend/app/modules/patient_history/router.py), so
 * unlike Visits above, no extra frontend permission check is needed
 * here: anyone who can see this section at all can already print from
 * it. */
function InvoicesSection({ invoices }) {
  const printInvoice = usePrintInvoice();
  const { printingId, error, handlePrint } = usePrintAction((invoiceId) =>
    printInvoice.mutateAsync(invoiceId),
  );

  if (!invoices?.length) return null;
  return (
    <SectionCard title="Billing" count={invoices.length}>
      {error ? <p className="mb-3 text-sm text-destructive">{error}</p> : null}
      <Table>
        <TableHeader>
          <TableRow>
            <TableHead>Date</TableHead>
            <TableHead>Status</TableHead>
            <TableHead className="text-right">Total</TableHead>
            <TableHead className="text-right">Paid</TableHead>
            <TableHead className="text-right">Discount</TableHead>
            <TableHead />
          </TableRow>
        </TableHeader>
        <TableBody>
          {invoices.map((invoice) => (
            <TableRow key={invoice.id}>
              <TableCell className="whitespace-nowrap">
                {formatDisplayDate(displayDayKey(invoice.created_at))}
              </TableCell>
              <TableCell>
                <MoneyStatusBadge status={invoice.status} />
              </TableCell>
              <TableCell className="whitespace-nowrap text-right tabular-nums">
                {money(invoice.total_amount)}
              </TableCell>
              <TableCell className="whitespace-nowrap text-right tabular-nums">
                {money(invoice.amount_paid)}
              </TableCell>
              <TableCell className="whitespace-nowrap text-right tabular-nums">
                {Number(invoice.discount_amount) > 0 ? money(invoice.discount_amount) : '—'}
              </TableCell>
              <TableCell>
                <PrintButton
                  label="Print Receipt"
                  id={invoice.id}
                  printingId={printingId}
                  onPrint={handlePrint}
                />
              </TableCell>
            </TableRow>
          ))}
        </TableBody>
      </Table>
    </SectionCard>
  );
}

/** Shared by both Lab Bills and Pharmacy Bills below — same row shape,
 * different underlying bill type, so the print mutation (`usePrintLabBill`
 * or `usePrintMedicineBill`) is threaded in via `printMutateAsync` from
 * each call site rather than picked inside this component; both of
 * those endpoints (`GET /lab/bills/{id}/print`, `GET /pharmacy/bills/
 * {id}/print`) require exactly the same read permission
 * (`lab:read`/`pharmacy:read`) that already gates showing each section
 * at all, so — like Invoices, unlike Visits — no extra frontend
 * permission check is needed here either. */
function BillsSection({ title, bills, printLabel, printMutateAsync }) {
  const { printingId, error, handlePrint } = usePrintAction(printMutateAsync);

  if (!bills?.length) return null;
  return (
    <SectionCard title={title} count={bills.length}>
      {error ? <p className="mb-3 text-sm text-destructive">{error}</p> : null}
      <Table>
        <TableHeader>
          <TableRow>
            <TableHead>Date</TableHead>
            <TableHead>Status</TableHead>
            <TableHead className="text-right">Items</TableHead>
            <TableHead className="text-right">Total</TableHead>
            <TableHead className="text-right">Paid</TableHead>
            <TableHead />
          </TableRow>
        </TableHeader>
        <TableBody>
          {bills.map((bill) => (
            <TableRow key={bill.id}>
              <TableCell className="whitespace-nowrap">
                {formatDisplayDate(displayDayKey(bill.created_at))}
              </TableCell>
              <TableCell>
                <MoneyStatusBadge status={bill.status} />
              </TableCell>
              <TableCell className="text-right tabular-nums">{bill.item_count}</TableCell>
              <TableCell className="whitespace-nowrap text-right tabular-nums">
                {money(bill.total_amount)}
              </TableCell>
              <TableCell className="whitespace-nowrap text-right tabular-nums">
                {money(bill.amount_paid)}
              </TableCell>
              <TableCell>
                <PrintButton
                  label={printLabel}
                  id={bill.id}
                  printingId={printingId}
                  onPrint={handlePrint}
                />
              </TableCell>
            </TableRow>
          ))}
        </TableBody>
      </Table>
    </SectionCard>
  );
}

/** The Patient History page's own always-visible, hospital-wide,
 * newest-first visit list — its default landing state, matching the
 * live-search-as-you-type pattern already used elsewhere in this app
 * (Reception's "My Registrations", Vitals' "My Vitals Records"), never
 * a dead-end "search then pick one" box. Real server-side search
 * (name/MR/phone)/date-range/pagination via `useHistoryVisitList`
 * (never a client-side approximation over a capped fetch — this list
 * is hospital-wide and unbounded, unlike MyRegistrations.jsx's own
 * client-filtered table, which is acceptable only because it's scoped
 * to one receptionist's own bounded lifetime volume). Column set
 * mirrors MyRegistrations.jsx's own table exactly, plus the Print Slip
 * action already established for this page's Visits section (see
 * VisitsSection's own docstring on the extra `reception:*` permission
 * check that action needs). Selecting a row hands its patient id up to
 * the parent, which switches to the existing single-patient drill-down
 * view below.
 *
 * `page`/`searchInput`/`startDate`/`endDate` are all controlled by the
 * parent (`PatientHistorySearch`) rather than local state here — this
 * component fully unmounts while the drill-down view is showing (see
 * that component's own conditional render), so state that lived here
 * instead would silently reset every time "← Back to all records" is
 * pressed, defeating the point of a "back" action returning to
 * wherever the receptionist actually was, filters and page included. */
function VisitListView({
  page,
  setPage,
  searchInput,
  setSearchInput,
  startDate,
  setStartDate,
  endDate,
  setEndDate,
  onSelectPatient,
}) {
  const { hasPermission } = useAuth();
  const debouncedSearch = useDebouncedValue(searchInput, 300);

  const { visits, meta, isLoading, isError, error, refetch } = useHistoryVisitList({
    page,
    pageSize: LIST_PAGE_SIZE,
    search: debouncedSearch || undefined,
    startDate: startDate || undefined,
    endDate: endDate || undefined,
  });
  const patientsById = usePatientsForVisits(visits);
  const printSlip = usePrintRegistrationSlip();
  const { printingId, error: printError, handlePrint } = usePrintAction((visitId) =>
    printSlip.mutateAsync(visitId),
  );
  const canPrintSlip =
    hasPermission('reception:register_visit') || hasPermission('reception:view_slip');

  const pageCount = Math.max(1, Math.ceil((meta?.total ?? 0) / LIST_PAGE_SIZE));

  function handleSearchChange(value) {
    setSearchInput(value);
    setPage(1);
  }

  function handleStartDateChange(value) {
    setStartDate(value);
    setPage(1);
  }

  function handleEndDateChange(value) {
    setEndDate(value);
    setPage(1);
  }

  return (
    <Card>
      <CardHeader className="flex flex-col gap-4">
        <CardTitle>All Patient Records</CardTitle>
        <div className="flex flex-wrap items-end gap-3">
          <div className="relative w-full sm:w-72">
            <Search className="pointer-events-none absolute left-2.5 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground" />
            <Input
              value={searchInput}
              onChange={(event) => handleSearchChange(event.target.value)}
              placeholder="Search by name, MR number, or phone"
              className="pl-8"
            />
          </div>
          <div className="flex flex-col gap-1.5">
            <Label htmlFor="history-list-start">From</Label>
            <Input
              id="history-list-start"
              type="date"
              value={startDate}
              onChange={(event) => handleStartDateChange(event.target.value)}
              className="w-auto"
            />
          </div>
          <div className="flex flex-col gap-1.5">
            <Label htmlFor="history-list-end">To</Label>
            <Input
              id="history-list-end"
              type="date"
              value={endDate}
              onChange={(event) => handleEndDateChange(event.target.value)}
              className="w-auto"
            />
          </div>
        </div>
      </CardHeader>
      <CardContent className="flex flex-col gap-4">
        {printError ? <p className="text-sm text-destructive">{printError}</p> : null}
        {isLoading ? (
          <PageLoader label="Loading patient records" />
        ) : isError ? (
          <PageError error={error} reset={refetch} message="Couldn't load patient records." />
        ) : visits.length === 0 ? (
          <p className="py-10 text-center text-sm text-muted-foreground">
            {debouncedSearch || startDate || endDate
              ? 'No records match this search.'
              : 'No visits recorded yet.'}
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
                  <TableHead className="text-right">Amount</TableHead>
                  {canPrintSlip ? <TableHead /> : null}
                </TableRow>
              </TableHeader>
              <TableBody>
                {visits.map((visit) => {
                  const patient = patientsById[visit.patient_id];
                  return (
                    <TableRow
                      key={visit.id}
                      className="cursor-pointer"
                      onClick={() => patient && onSelectPatient(patient)}
                    >
                      <TableCell className="whitespace-nowrap">
                        {displayDayKey(visit.created_at)} {formatDisplayTime(visit.created_at)}
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
                      <TableCell className="whitespace-nowrap text-right font-medium tabular-nums">
                        {money(visit.amount)}
                      </TableCell>
                      {canPrintSlip ? (
                        // The row itself opens the drill-down (see
                        // TableRow's own onClick above) — stopped here so
                        // clicking Print Slip never also selects the
                        // patient, same guard PatientDirectory.jsx's row-
                        // click + "Visit History" button already uses.
                        <TableCell onClick={(event) => event.stopPropagation()}>
                          <PrintButton
                            label="Print Slip"
                            id={visit.id}
                            printingId={printingId}
                            onPrint={handlePrint}
                          />
                        </TableCell>
                      ) : null}
                    </TableRow>
                  );
                })}
              </TableBody>
            </Table>

            {pageCount > 1 ? (
              <div className="flex items-center justify-between text-sm text-muted-foreground">
                <span>
                  Page {page} of {pageCount} · {meta.total} record{meta.total === 1 ? '' : 's'}
                </span>
                <div className="flex gap-2">
                  <Button
                    size="sm"
                    variant="outline"
                    disabled={page <= 1}
                    onClick={() => setPage((p) => Math.max(1, p - 1))}
                  >
                    Previous
                  </Button>
                  <Button
                    size="sm"
                    variant="outline"
                    disabled={page >= pageCount}
                    onClick={() => setPage((p) => Math.min(pageCount, p + 1))}
                  >
                    Next
                  </Button>
                </div>
              </div>
            ) : null}
          </>
        )}
      </CardContent>
    </Card>
  );
}

/** The four-role shared "Patient History" page. Defaults to
 * `VisitListView` — an always-visible, hospital-wide, live-search-as-
 * you-type list of every visit (see that component's own docstring),
 * never a dead-end search box — and switches to this single patient's
 * full aggregated cross-module history (from `usePatientHistory`) once
 * a row is selected, via "← Back to all records" to return.
 *
 * Each section below only renders when its own array is genuinely
 * non-empty — a `null` section (the signed-in role doesn't hold that
 * section's own other permission, e.g. Reception never sees Vitals/
 * Consultations here, Doctor never sees Billing/Lab/Pharmacy — see
 * backend/app/modules/patient_history/router.py's own docstring) and
 * an empty-but-visible `[]` section both simply don't render, exactly
 * the same "don't show an empty shell" behavior every other list view
 * in this app already follows (PatientVisitHistoryDialog, VitalsWorklist,
 * etc.) — there is no separate "you don't have access to this" message,
 * since a role that can't see a section has no way to tell that apart
 * from "this patient has none" regardless, by design. */
export function PatientHistorySearch() {
  const [selectedPatient, setSelectedPatient] = useState(null);
  // Lives here, not inside VisitListView, so it survives that
  // component unmounting while the drill-down view is showing — see
  // VisitListView's own docstring.
  const [page, setPage] = useState(1);
  const [searchInput, setSearchInput] = useState('');
  const [startDate, setStartDate] = useState('');
  const [endDate, setEndDate] = useState('');
  const { history, isLoading, isError, error, refetch } = usePatientHistory(selectedPatient?.id);
  const printLabBill = usePrintLabBill();
  const printMedicineBill = usePrintMedicineBill();

  if (!selectedPatient) {
    return (
      <div className="flex flex-col gap-6">
        <div className="flex flex-col gap-1">
          <h1 className="text-lg font-semibold text-foreground">Patient History</h1>
          <p className="text-sm text-muted-foreground">
            Every patient visit, hospital-wide. Search or select a row to see a patient's full
            cross-module history.
          </p>
        </div>

        <VisitListView
          page={page}
          setPage={setPage}
          searchInput={searchInput}
          setSearchInput={setSearchInput}
          startDate={startDate}
          setStartDate={setStartDate}
          endDate={endDate}
          setEndDate={setEndDate}
          onSelectPatient={setSelectedPatient}
        />
      </div>
    );
  }

  return (
    <div className="flex flex-col gap-6">
      <div>
        <Button
          size="sm"
          variant="outline"
          onClick={() => setSelectedPatient(null)}
          className="mb-4"
        >
          <ArrowLeft className="h-3.5 w-3.5" />
          Back to all records
        </Button>
        <h1 className="text-lg font-semibold text-foreground">Patient History</h1>
      </div>

      {isLoading ? (
        <PageLoader label="Loading patient history" />
      ) : isError ? (
        <PageError error={error} reset={refetch} message="Couldn't load this patient's history." />
      ) : history ? (
        <div className="flex flex-col gap-6">
          <Card>
            <CardHeader>
              <CardTitle>{history.patient.full_name}</CardTitle>
              <p className="text-sm text-muted-foreground">
                {history.patient.mr_number} · {history.patient.phone_number}
                {history.patient.age_years !== null && history.patient.age_years !== undefined
                  ? ` · ${history.patient.age_years} yrs`
                  : ''}
              </p>
            </CardHeader>
          </Card>

          <VisitsSection visits={history.visits} />
          <VitalsSection vitals={history.vitals} ageYears={history.patient.age_years} />
          <ConsultationsSection consultations={history.consultations} />
          <InvoicesSection invoices={history.invoices} />
          <BillsSection
            title="Lab Bills"
            bills={history.lab_bills}
            printLabel="Print Slip"
            printMutateAsync={printLabBill.mutateAsync}
          />
          <BillsSection
            title="Pharmacy Bills"
            bills={history.pharmacy_bills}
            printLabel="Print Slip"
            printMutateAsync={printMedicineBill.mutateAsync}
          />
        </div>
      ) : null}
    </div>
  );
}
