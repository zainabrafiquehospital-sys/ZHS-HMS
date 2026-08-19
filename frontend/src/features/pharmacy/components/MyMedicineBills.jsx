'use client';

import { useMemo, useState } from 'react';
import { Printer, Search } from 'lucide-react';
import {
  useMyMedicineBills,
  usePrintMedicineBill,
  useVisitsForMedicineBills,
} from '@/features/pharmacy/hooks/usePharmacy';
import { usePatientsForVisits } from '@/features/patients/hooks/usePatientsForVisits';
import { Card, CardContent, CardHeader, CardTitle } from '@/shared/components/ui/Card';
import { Badge } from '@/shared/components/ui/Badge';
import { Button } from '@/shared/components/ui/Button';
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
// Every medicine bill this receptionist has ever created, fetched in
// one generously-sized page — same convention and rationale as
// MyRegistrations.jsx's identical FETCH_PAGE_SIZE (the server-side
// filter itself is unbounded; see useMyMedicineBills's own docstring).
const FETCH_PAGE_SIZE = 100;

const currencyFormatter = new Intl.NumberFormat('en-US', {
  minimumFractionDigits: 2,
  maximumFractionDigits: 2,
});

function formatPkr(amount) {
  return `PKR ${currencyFormatter.format(Number(amount))}`;
}

const STATUS_BADGE_VARIANT = {
  paid: 'success',
  partially_paid: 'warning',
  unpaid: 'outline',
};

/** A bill's own display name, resolved the same three-way fallback the
 * printed slip's reference section and Admin's Medicine Bills tab both
 * already use: a linked Visit's real Patient, else the manually-typed
 * name, else a plain walk-in. */
function billPatientName(bill, visitsById, patientsById) {
  if (bill.visit_id) {
    const visit = visitsById[bill.visit_id];
    const patient = visit ? patientsById[visit.patient_id] : null;
    return patient?.full_name ?? '…';
  }
  return bill.manual_patient_name ?? 'Walk-in';
}

function matchesSearch(name, term) {
  if (!term) return true;
  return name.toLowerCase().includes(term.toLowerCase());
}

/** The receptionist's own itemized medicine-bill record — every bill
 * she has personally created, listed individually (2026-08-19
 * addition), the pharmacy sibling of Reception's own "My
 * Registrations" (features/reception/components/MyRegistrations.jsx):
 * same fetch-one-generous-page + client-side search/display-paginate
 * shape, same table-of-individual-rows spirit. Lives on `/pharmacy`
 * (where bills are actually created), below the billing-counter
 * workspace — the same placement relationship "My Registrations" has
 * to `/reception`'s own registration form.
 *
 * Patient-name resolution reuses the exact `useVisitsForMedicineBills`
 * + `usePatientsForVisits` join Admin Overview's Medicine Bills tab
 * already established, rather than inventing a second pattern for the
 * same two-hop lookup. */
export function MyMedicineBills() {
  const { bills, isLoading, isError, error, refetch } = useMyMedicineBills({
    page: 1,
    pageSize: FETCH_PAGE_SIZE,
  });
  const visitsById = useVisitsForMedicineBills(bills);
  const patientsById = usePatientsForVisits(Object.values(visitsById).filter(Boolean));
  const printBill = usePrintMedicineBill();

  const [searchTerm, setSearchTerm] = useState('');
  const [page, setPage] = useState(1);
  const [printingBillId, setPrintingBillId] = useState(null);
  const [printError, setPrintError] = useState(null);

  const debouncedSearch = useDebouncedValue(searchTerm, 200);

  const billsWithNames = useMemo(
    () =>
      bills.map((bill) => ({
        ...bill,
        _patientName: billPatientName(bill, visitsById, patientsById),
      })),
    [bills, visitsById, patientsById],
  );

  const filteredBills = useMemo(() => {
    if (!debouncedSearch) return billsWithNames;
    return billsWithNames.filter((bill) => matchesSearch(bill._patientName, debouncedSearch));
  }, [billsWithNames, debouncedSearch]);

  const pageCount = Math.max(1, Math.ceil(filteredBills.length / DISPLAY_PAGE_SIZE));
  const currentPage = Math.min(page, pageCount);
  const pagedBills = filteredBills.slice(
    (currentPage - 1) * DISPLAY_PAGE_SIZE,
    currentPage * DISPLAY_PAGE_SIZE,
  );

  function handleSearchChange(value) {
    setSearchTerm(value);
    setPage(1);
  }

  async function handlePrint(billId) {
    if (printingBillId) return; // one print job in flight at a time
    setPrintError(null);
    setPrintingBillId(billId);
    try {
      await printBill.mutateAsync(billId);
    } catch (err) {
      setPrintError(err.message || 'Unable to print this bill — you can try again.');
    } finally {
      setPrintingBillId(null);
    }
  }

  if (isLoading) return <PageLoader label="Loading your medicine bills" />;
  if (isError) {
    return <PageError error={error} reset={refetch} message="Couldn't load your medicine bills." />;
  }

  return (
    <Card>
      <CardHeader className="flex-row items-center justify-between gap-2">
        <CardTitle>My Medicine Bills</CardTitle>
      </CardHeader>
      <CardContent className="flex flex-col gap-5">
        <div className="relative sm:max-w-xs">
          <Search className="pointer-events-none absolute left-2.5 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground" />
          <Input
            value={searchTerm}
            onChange={(event) => handleSearchChange(event.target.value)}
            placeholder="Search by patient name"
            className="pl-8"
          />
        </div>

        {printError ? (
          <p className="rounded-md bg-destructive/10 px-3 py-2 text-sm text-destructive">
            {printError}
          </p>
        ) : null}

        {bills.length === 0 ? (
          <p className="py-10 text-center text-sm text-muted-foreground">
            No medicine bills created by you yet — new bills will appear here immediately.
          </p>
        ) : filteredBills.length === 0 ? (
          <p className="py-10 text-center text-sm text-muted-foreground">
            No bills match &quot;{debouncedSearch}&quot;.
          </p>
        ) : (
          <>
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>Time</TableHead>
                  <TableHead>Patient</TableHead>
                  <TableHead className="text-right">Items</TableHead>
                  <TableHead className="text-right">Total</TableHead>
                  <TableHead className="text-right">Discount</TableHead>
                  <TableHead>Status</TableHead>
                  <TableHead />
                </TableRow>
              </TableHeader>
              <TableBody>
                {pagedBills.map((bill) => {
                  const isPrintingThisRow = printingBillId === bill.id;
                  return (
                    <TableRow key={bill.id}>
                      <TableCell className="whitespace-nowrap">
                        {displayDayKey(bill.created_at)} {formatDisplayTime(bill.created_at)}
                      </TableCell>
                      <TableCell className="max-w-[160px] truncate font-medium text-foreground">
                        {bill._patientName}
                      </TableCell>
                      <TableCell className="text-right tabular-nums">{bill.item_count}</TableCell>
                      <TableCell className="whitespace-nowrap text-right font-medium tabular-nums">
                        {formatPkr(bill.total_amount)}
                      </TableCell>
                      <TableCell className="whitespace-nowrap text-right tabular-nums text-muted-foreground">
                        {Number(bill.discount_amount) > 0 ? formatPkr(bill.discount_amount) : '—'}
                      </TableCell>
                      <TableCell>
                        <Badge
                          variant={STATUS_BADGE_VARIANT[bill.status] ?? 'outline'}
                          className="capitalize"
                        >
                          {bill.status.replaceAll('_', ' ')}
                        </Badge>
                      </TableCell>
                      <TableCell>
                        <Button
                          size="sm"
                          variant="outline"
                          disabled={Boolean(printingBillId)}
                          onClick={() => handlePrint(bill.id)}
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
                  Page {currentPage} of {pageCount} · {filteredBills.length} bill
                  {filteredBills.length === 1 ? '' : 's'}
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
    </Card>
  );
}
