'use client';

import { useState } from 'react';
import { History, Printer, Search } from 'lucide-react';
import { usePatientDirectory } from '@/features/admin/hooks/usePatientDirectory';
import { PatientVisitHistoryDialog } from '@/features/admin/components/PatientVisitHistoryDialog';
import { printPatientDirectory } from '@/features/admin/utils/printPatientDirectory';
import { computePageCount } from '@/features/admin/utils/pagination';
import { patientsService } from '@/features/patients/api/patientsService';
import { useDebouncedValue } from '@/shared/hooks/useDebouncedValue';
import { displayDayKey, formatDisplayDate } from '@/utils/timezone';
import { Card, CardContent, CardHeader, CardTitle } from '@/shared/components/ui/Card';
import { Button } from '@/shared/components/ui/Button';
import { Input } from '@/shared/components/ui/Input';
import { Select } from '@/shared/components/ui/Select';
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

const PAGE_SIZE = 20;
// Every real patient this directory needs to print at once — comfortably
// above current volume (29 patients as of this build); the print button
// re-fetches unpaginated up to this cap rather than reusing the on-screen
// page, so "Print" always covers the full current search, not just the
// visible 20 rows.
const PRINT_FETCH_CAP = 500;

const SORT_OPTIONS = [
  { value: 'created_at', label: 'Registered On' },
  { value: 'full_name', label: 'Name' },
  { value: 'mr_number', label: 'MR Number' },
];

function registeredOnLabel(isoTimestamp) {
  return formatDisplayDate(displayDayKey(isoTimestamp));
}

/** Full, paginated, searchable, sortable listing of every registered
 * patient — Admin-only, read-only (no create/edit here; that stays
 * Reception's registration flow). Backed by `GET /patients`'s real
 * server-side pagination via `usePatientDirectory`, never a "fetch N +
 * filter client-side" shortcut. */
export function PatientDirectory() {
  const [page, setPage] = useState(1);
  const [searchInput, setSearchInput] = useState('');
  const [sortBy, setSortBy] = useState('created_at');
  const [sortOrder, setSortOrder] = useState('desc');
  const [printError, setPrintError] = useState(null);
  const [isPrinting, setIsPrinting] = useState(false);
  const [historyPatient, setHistoryPatient] = useState(null);
  const debouncedSearch = useDebouncedValue(searchInput, 300);

  const { patients, meta, isLoading, isError, error, refetch } = usePatientDirectory({
    page,
    pageSize: PAGE_SIZE,
    search: debouncedSearch || undefined,
    sortBy,
    sortOrder,
  });

  const pageCount = computePageCount(meta?.total, PAGE_SIZE);

  function handleSearchChange(value) {
    setSearchInput(value);
    setPage(1);
  }

  function handleSortByChange(value) {
    setSortBy(value);
    setPage(1);
  }

  function handleSortOrderChange(value) {
    setSortOrder(value);
    setPage(1);
  }

  async function handlePrint() {
    setPrintError(null);
    setIsPrinting(true);
    try {
      const res = await patientsService.list({
        page: 1,
        pageSize: PRINT_FETCH_CAP,
        search: debouncedSearch || undefined,
        sortBy,
        sortOrder,
      });
      await printPatientDirectory({
        searchLabel: debouncedSearch ? `Search: "${debouncedSearch}"` : 'All Patients',
        patients: res.data,
      });
    } catch (err) {
      setPrintError(err.message || 'Unable to print the patient directory.');
    } finally {
      setIsPrinting(false);
    }
  }

  return (
    <div className="flex flex-col gap-6">
      <div className="flex flex-col gap-1">
        <h1 className="text-lg font-semibold text-foreground">Patient Directory</h1>
        <p className="text-sm text-muted-foreground">
          Every registered patient, searchable by MR number, name, or phone.
        </p>
      </div>

      <Card>
        <CardHeader>
          <div className="flex flex-col gap-4 sm:flex-row sm:items-end sm:justify-between">
            <CardTitle>Patients</CardTitle>
            <div className="flex flex-col gap-3 sm:flex-row sm:items-end">
              <div className="relative w-full sm:w-64">
                <Search className="pointer-events-none absolute left-2.5 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground" />
                <Input
                  value={searchInput}
                  onChange={(event) => handleSearchChange(event.target.value)}
                  placeholder="Search by MR number, name, phone…"
                  className="pl-8"
                />
              </div>
              <div className="flex gap-2">
                <Select
                  value={sortBy}
                  onChange={(event) => handleSortByChange(event.target.value)}
                  className="w-40"
                >
                  {SORT_OPTIONS.map((option) => (
                    <option key={option.value} value={option.value}>
                      {option.label}
                    </option>
                  ))}
                </Select>
                <Select
                  value={sortOrder}
                  onChange={(event) => handleSortOrderChange(event.target.value)}
                  className="w-28"
                >
                  <option value="desc">Newest</option>
                  <option value="asc">Oldest</option>
                </Select>
              </div>
              <Button
                type="button"
                variant="outline"
                onClick={handlePrint}
                disabled={isPrinting || isLoading}
              >
                <Printer className="h-4 w-4" />
                {isPrinting ? 'Preparing…' : 'Print'}
              </Button>
            </div>
          </div>
        </CardHeader>
        <CardContent className="flex flex-col gap-4">
          {printError ? <p className="text-sm text-destructive">{printError}</p> : null}
          {isLoading ? (
            <PageLoader label="Loading patients" />
          ) : isError ? (
            <PageError error={error} reset={refetch} message="Couldn't load the patient directory." />
          ) : patients.length === 0 ? (
            <p className="text-sm text-muted-foreground">
              {debouncedSearch ? 'No patients match this search.' : 'No patients registered yet.'}
            </p>
          ) : (
            <>
              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead>MR Number</TableHead>
                    <TableHead>Name</TableHead>
                    <TableHead className="text-right">Age</TableHead>
                    <TableHead>Phone</TableHead>
                    <TableHead>Registered On</TableHead>
                    <TableHead />
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {patients.map((patient) => (
                    <TableRow
                      key={patient.id}
                      className="cursor-pointer"
                      onClick={() => setHistoryPatient(patient)}
                    >
                      <TableCell className="font-medium text-foreground">
                        {patient.mr_number}
                      </TableCell>
                      <TableCell>{patient.full_name}</TableCell>
                      <TableCell className="text-right tabular-nums">
                        {patient.age_years ?? '—'}
                      </TableCell>
                      <TableCell>{patient.phone_number}</TableCell>
                      <TableCell className="whitespace-nowrap text-muted-foreground">
                        {registeredOnLabel(patient.created_at)}
                      </TableCell>
                      <TableCell>
                        <Button
                          size="sm"
                          variant="outline"
                          onClick={(event) => {
                            event.stopPropagation(); // the row itself opens the same dialog
                            setHistoryPatient(patient);
                          }}
                        >
                          <History className="h-3.5 w-3.5" />
                          Visit History
                        </Button>
                      </TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>

              {pageCount > 1 ? (
                <div className="flex items-center justify-between text-sm text-muted-foreground">
                  <span>
                    Page {page} of {pageCount} · {meta.total} patient{meta.total === 1 ? '' : 's'}
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

      {historyPatient ? (
        <PatientVisitHistoryDialog
          patient={historyPatient}
          onClose={() => setHistoryPatient(null)}
        />
      ) : null}
    </div>
  );
}
