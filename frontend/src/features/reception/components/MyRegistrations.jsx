'use client';

import { useMemo, useState } from 'react';
import { Eraser, Printer, Receipt, Search, Users } from 'lucide-react';
import {
  useClearMyRevenue,
  useMyRegistrations,
  useMyRevenue,
  usePatientsForVisits,
  usePrintRegistrationSlip,
} from '@/features/reception/hooks/useReception';
import { Card, CardContent, CardHeader, CardTitle } from '@/shared/components/ui/Card';
import { Badge } from '@/shared/components/ui/Badge';
import { Button } from '@/shared/components/ui/Button';
import { ConfirmDialog } from '@/shared/components/ui/ConfirmDialog';
import { Input } from '@/shared/components/ui/Input';
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
import { displayDayKey, formatDisplayTime } from '@/utils/timezone';

const DISPLAY_PAGE_SIZE = 10;
// Every registration this receptionist has ever made, fetched in one
// generously-sized page — comfortably above any individual
// receptionist's realistic lifetime volume today (the server-side
// filter itself is unbounded — see visitsService.listForCreator — this
// cap only bounds one screen's single fetch; `meta.total` reveals if it
// is ever actually insufficient, unlike the old hospital-wide "100
// recent" cap this replaces, which could silently miss a receptionist's
// own older slips with no signal at all).
const FETCH_PAGE_SIZE = 100;

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

/** Every visit this receptionist has ever registered — no date or
 * shift restriction, only creator (see useMyRegistrations); this list
 * is never affected by "Clear Revenue" or the 24h auto-window (her
 * full history stays fully visible here regardless — only the summary
 * tiles above it reset/roll over). "My Revenue" breaks out visits vs.
 * medicine bills plus a combined total, always capped to roughly the
 * last 24 hours — reset early by pressing "Clear Revenue", or
 * automatically once a slip turns 24 hours old, whichever is more
 * recent (useMyRevenue, a server-side aggregate hard-scoped to her own
 * id — see that hook's own docstring — never a sum of whatever page
 * happens to be fetched). */
export function MyRegistrations() {
  const { visits, isLoading, isError, error, refetch } = useMyRegistrations({
    page: 1,
    pageSize: FETCH_PAGE_SIZE,
  });
  const revenue = useMyRevenue();
  const clearRevenue = useClearMyRevenue();
  const patientsById = usePatientsForVisits(visits);
  const printSlip = usePrintRegistrationSlip();

  const [searchTerm, setSearchTerm] = useState('');
  const [page, setPage] = useState(1);
  const [printingVisitId, setPrintingVisitId] = useState(null);
  const [printError, setPrintError] = useState(null);
  const [confirmingClear, setConfirmingClear] = useState(false);
  const [clearError, setClearError] = useState(null);

  const debouncedSearch = useDebouncedValue(searchTerm, 200);

  const filteredVisits = useMemo(() => {
    if (!debouncedSearch) return visits;
    return visits.filter((visit) => matchesSearch(patientsById[visit.patient_id], debouncedSearch));
  }, [visits, patientsById, debouncedSearch]);

  const pageCount = Math.max(1, Math.ceil(filteredVisits.length / DISPLAY_PAGE_SIZE));
  const currentPage = Math.min(page, pageCount);
  const pagedVisits = filteredVisits.slice(
    (currentPage - 1) * DISPLAY_PAGE_SIZE,
    currentPage * DISPLAY_PAGE_SIZE,
  );

  function handleSearchChange(value) {
    setSearchTerm(value);
    setPage(1);
  }

  async function handlePrint(visitId) {
    if (printingVisitId) return; // one print job in flight at a time
    setPrintError(null);
    setPrintingVisitId(visitId);
    try {
      await printSlip.mutateAsync(visitId);
    } catch (err) {
      setPrintError(err.message || 'Unable to print this slip — you can try again.');
    } finally {
      setPrintingVisitId(null);
    }
  }

  async function handleConfirmClear() {
    setClearError(null);
    try {
      await clearRevenue.mutateAsync();
      setConfirmingClear(false);
    } catch (err) {
      setClearError(err.message || 'Unable to clear your revenue — you can try again.');
    }
  }

  if (isLoading) return <PageLoader label="Loading your registrations" />;
  if (isError) {
    return <PageError error={error} reset={refetch} message="Couldn't load your registrations." />;
  }

  return (
    <Card>
      <CardHeader className="flex-row items-center justify-between gap-2">
        <CardTitle>My Registrations</CardTitle>
      </CardHeader>
      <CardContent className="flex flex-col gap-5">
        <div className="flex flex-col gap-3">
          <div className="grid grid-cols-1 gap-3 sm:grid-cols-3">
            <SummaryTile icon={Receipt} label="Visits Revenue" value={formatPkr(revenue.visitsRevenue)} />
            <SummaryTile
              icon={Receipt}
              label="Medicines Revenue"
              value={formatPkr(revenue.medicineRevenue)}
            />
            <SummaryTile icon={Receipt} label="Total Revenue" value={formatPkr(revenue.totalRevenue)} />
          </div>
          <div className="flex flex-wrap items-center justify-between gap-3 rounded-md border border-dashed border-border p-3">
            <div className="flex items-center gap-2 text-xs text-muted-foreground">
              <Users className="h-3.5 w-3.5" />
              <span>
                {revenue.visitsCount} slip{revenue.visitsCount === 1 ? '' : 's'}
                {revenue.clearedAt
                  ? ` · since ${displayDayKey(revenue.clearedAt)} ${formatDisplayTime(revenue.clearedAt)} (auto-resets every 24h)`
                  : ''}
              </span>
            </div>
            <Button size="sm" variant="outline" onClick={() => setConfirmingClear(true)}>
              <Eraser className="h-3.5 w-3.5" />
              Clear Revenue
            </Button>
          </div>
        </div>

        <div className="relative sm:max-w-xs">
          <Search className="pointer-events-none absolute left-2.5 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground" />
          <Input
            value={searchTerm}
            onChange={(event) => handleSearchChange(event.target.value)}
            placeholder="Search by name, MR number, or phone"
            className="pl-8"
          />
        </div>

        {printError ? (
          <p className="rounded-md bg-destructive/10 px-3 py-2 text-sm text-destructive">
            {printError}
          </p>
        ) : null}

        {visits.length === 0 ? (
          <p className="py-10 text-center text-sm text-muted-foreground">
            No visits registered by you yet — new registrations will appear here immediately.
          </p>
        ) : filteredVisits.length === 0 ? (
          <p className="py-10 text-center text-sm text-muted-foreground">
            No registrations match &quot;{debouncedSearch}&quot;.
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
                  {/* <TableHead>Guardian</TableHead>
                  <TableHead>CNIC</TableHead> */}
                  <TableHead>Address</TableHead>
                  <TableHead>Procedure</TableHead>
                  <TableHead>Doctor</TableHead>
                  <TableHead>Vitals</TableHead>
                  <TableHead className="text-right">Amount</TableHead>
                  <TableHead />
                </TableRow>
              </TableHeader>
              <TableBody>
                {pagedVisits.map((visit) => {
                  const patient = patientsById[visit.patient_id];
                  const isPrintingThisRow = printingVisitId === visit.id;
                  return (
                    <TableRow key={visit.id}>
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
                      <TableCell
                        className="max-w-[160px] truncate"
                        title={patient?.address || undefined}
                      >
                        {patient?.address || '—'}
                      </TableCell>
                      <TableCell className="max-w-[160px] truncate">{visit.procedure}</TableCell>
                      <TableCell>
                        {visit.doctor_user_id ? (
                          <Badge variant="success">Assigned</Badge>
                        ) : (
                          <Badge variant="warning">Unassigned</Badge>
                        )}
                      </TableCell>
                      <TableCell>
                        <Badge variant={visit.vitals_required ? 'secondary' : 'outline'}>
                          {visit.vitals_required ? 'Yes' : 'No'}
                        </Badge>
                      </TableCell>
                      <TableCell className="whitespace-nowrap text-right font-medium tabular-nums">
                        {formatPkr(visit.amount)}
                      </TableCell>
                      <TableCell>
                        <Button
                          size="sm"
                          variant="outline"
                          disabled={Boolean(printingVisitId)}
                          onClick={() => handlePrint(visit.id)}
                        >
                          <Printer className="h-3.5 w-3.5" />
                          {isPrintingThisRow ? 'Printing…' : 'Print Slip'}
                        </Button>
                      </TableCell>
                    </TableRow>
                  );
                })}
              </TableBody>
            </Table>

            {pageCount > 1 ? (
              <div className="flex items-center justify-between text-sm text-muted-foreground">
                <span>
                  Page {currentPage} of {pageCount} · {filteredVisits.length} registration
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
      </CardContent>

      <ConfirmDialog
        open={confirmingClear}
        variant="destructive"
        title="Clear your revenue?"
        confirmLabel={clearRevenue.isPending ? 'Clearing…' : 'Clear Revenue'}
        cancelLabel="Cancel"
        onCancel={() => {
          setConfirmingClear(false);
          setClearError(null);
        }}
        onConfirm={handleConfirmClear}
        description={
          <div className="flex flex-col gap-2">
            <p>
              Your Visits Revenue, Medicines Revenue, and Total Revenue figures above will reset to
              PKR 0.00 going forward. This does not delete or change anything — every visit,
              invoice, and medicine bill you&apos;ve ever created stays exactly as it is, still
              fully visible in your registrations list below and in Admin&apos;s records. These
              figures already roll over automatically every 24 hours on their own — use this only
              if you want to reset them sooner. This cannot be undone from here.
            </p>
            {clearError ? <p className="text-destructive">{clearError}</p> : null}
          </div>
        }
      />
    </Card>
  );
}
