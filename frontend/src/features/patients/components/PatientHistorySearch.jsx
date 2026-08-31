'use client';

import { useState } from 'react';
import { Printer } from 'lucide-react';
import { patientsService } from '@/features/patients/api/patientsService';
import { usePatientHistory } from '@/features/patients/hooks/usePatientHistory';
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
import { SearchSelect } from '@/shared/components/SearchSelect';
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
import { formatDisplayDate, formatDisplayTime, displayDayKey } from '@/utils/timezone';

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

/** The four-role shared "Patient History" search — a single search bar
 * (name/MR number/phone, the exact same `patientsService.search` +
 * `SearchSelect` pair RegisterVisitForm.jsx's own "Existing Patient"
 * picker already uses) that, once a patient is picked, shows their
 * full aggregated cross-module history from `usePatientHistory`.
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
  const [searchLabel, setSearchLabel] = useState('');
  const { history, isLoading, isError, error, refetch } = usePatientHistory(selectedPatient?.id);
  const printLabBill = usePrintLabBill();
  const printMedicineBill = usePrintMedicineBill();

  return (
    <div className="flex flex-col gap-6">
      <div className="flex flex-col gap-1">
        <h1 className="text-lg font-semibold text-foreground">Patient History</h1>
        <p className="text-sm text-muted-foreground">
          Search for a patient to see their full history across every module.
        </p>
      </div>

      <Card>
        <CardContent className="pt-6">
          <div className="relative w-full sm:w-96">
            <SearchSelect
              queryKey={['patients', 'search']}
              queryFn={(term) => patientsService.search(term).then((res) => res.data)}
              getLabel={(patient) => patient.full_name}
              getDescription={(patient) => `MR: ${patient.mr_number} · ${patient.phone_number}`}
              placeholder="Search by name, MR number, or phone"
              selectedLabel={searchLabel}
              onSelect={(patient) => {
                setSelectedPatient(patient);
                setSearchLabel(`${patient.full_name} (${patient.mr_number})`);
              }}
            />
          </div>
        </CardContent>
      </Card>

      {!selectedPatient ? null : isLoading ? (
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
