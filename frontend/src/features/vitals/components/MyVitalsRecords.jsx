'use client';

import { useMemo, useState } from 'react';
import { Search } from 'lucide-react';
import {
  useMyVitalsRecords,
  useVisitsByIds,
  usePatientsForVisits,
} from '@/features/vitals/hooks/useVitals';
import { vitalFieldUnit } from '@/features/vitals/utils/vitalsSeverity';
import { Card, CardContent, CardHeader, CardTitle } from '@/shared/components/ui/Card';
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
// Every vitals record this staff member has ever recorded, fetched in
// one generously-sized page — the exact same "one real server-side
// fetch, then client-side search/paginate over it" shape
// MyRegistrations.jsx (Reception) already established for its own
// FETCH_PAGE_SIZE, for the identical reason: comfortably above any
// individual staff member's realistic lifetime volume today, with
// `meta.total` available to reveal if it's ever actually insufficient.
const FETCH_PAGE_SIZE = 100;

function matchesSearch(patient, term) {
  if (!term) return true;
  const haystack = [patient?.full_name, patient?.mr_number, patient?.phone_number]
    .filter(Boolean)
    .join(' ')
    .toLowerCase();
  return haystack.includes(term.toLowerCase());
}

function formatVital(value, unit) {
  return value === null || value === undefined ? '—' : `${value} ${unit}`;
}

/** Every vitals record this Vitals staff member has personally
 * recorded, newest first — the Vitals sibling of Reception's own "My
 * Registrations" (MyRegistrations.jsx), same search bar + scrollable-
 * table shape, minus the parts that don't apply here: no revenue
 * concept exists for Vitals, so there are no summary tiles and no
 * "Clear Revenue"-equivalent action — this screen is purely a read-only
 * record of what was recorded, identity columns (Time/Queue Token/
 * Patient/MR/Age-Gender/Phone) unchanged from that table's own
 * conventions, with Procedure/Doctor/Amount replaced by the vitals
 * values themselves. Each row's Temperature column reads that row's
 * OWN `temperature_unit` via `vitalFieldUnit` (Step 1's per-record-unit
 * discipline) — never a single assumed unit for the whole table, so a
 * historical Celsius reading and a new Fahrenheit one sitting in
 * adjacent rows are each labeled correctly. */
export function MyVitalsRecords() {
  const { records, isLoading, isError, error, refetch } = useMyVitalsRecords({
    page: 1,
    pageSize: FETCH_PAGE_SIZE,
  });
  const visitIds = useMemo(() => records.map((record) => record.visit_id), [records]);
  const { visitsById, isLoading: isLoadingVisits } = useVisitsByIds(visitIds);
  const visits = useMemo(
    () => visitIds.map((id) => visitsById[id]).filter(Boolean),
    [visitIds, visitsById],
  );
  const patientsById = usePatientsForVisits(visits);

  const [searchTerm, setSearchTerm] = useState('');
  const [page, setPage] = useState(1);
  const debouncedSearch = useDebouncedValue(searchTerm, 200);

  const filteredRecords = useMemo(() => {
    if (!debouncedSearch) return records;
    return records.filter((record) => {
      const visit = visitsById[record.visit_id];
      const patient = visit ? patientsById[visit.patient_id] : undefined;
      return matchesSearch(patient, debouncedSearch);
    });
  }, [records, visitsById, patientsById, debouncedSearch]);

  const pageCount = Math.max(1, Math.ceil(filteredRecords.length / DISPLAY_PAGE_SIZE));
  const currentPage = Math.min(page, pageCount);
  const pagedRecords = filteredRecords.slice(
    (currentPage - 1) * DISPLAY_PAGE_SIZE,
    currentPage * DISPLAY_PAGE_SIZE,
  );

  function handleSearchChange(value) {
    setSearchTerm(value);
    setPage(1);
  }

  if (isLoading) return <PageLoader label="Loading your vitals records" />;
  if (isError) {
    return <PageError error={error} reset={refetch} message="Couldn't load your vitals records." />;
  }

  return (
    <Card>
      <CardHeader>
        <CardTitle>My Vitals Records</CardTitle>
      </CardHeader>
      <CardContent className="flex flex-col gap-5">
        <div className="relative sm:max-w-xs">
          <Search className="pointer-events-none absolute left-2.5 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground" />
          <Input
            value={searchTerm}
            onChange={(event) => handleSearchChange(event.target.value)}
            placeholder="Search by name, MR number, or phone"
            className="pl-8"
          />
        </div>

        {records.length === 0 ? (
          <p className="py-10 text-center text-sm text-muted-foreground">
            No vitals recorded by you yet — new recordings will appear here immediately.
          </p>
        ) : filteredRecords.length === 0 ? (
          <p className="py-10 text-center text-sm text-muted-foreground">
            No records match &quot;{debouncedSearch}&quot;.
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
                  <TableHead className="text-right">Systolic BP</TableHead>
                  <TableHead className="text-right">Diastolic BP</TableHead>
                  <TableHead className="text-right">Temperature</TableHead>
                  <TableHead className="text-right">Weight</TableHead>
                  <TableHead className="text-right">SpO2</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {pagedRecords.map((record) => {
                  const visit = visitsById[record.visit_id];
                  const patient = visit ? patientsById[visit.patient_id] : undefined;
                  return (
                    <TableRow key={record.id}>
                      <TableCell className="whitespace-nowrap">
                        {displayDayKey(record.created_at)} {formatDisplayTime(record.created_at)}
                      </TableCell>
                      <TableCell className="whitespace-nowrap font-mono">
                        {visit ? visit.queue_token : isLoadingVisits ? '…' : '—'}
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
                      <TableCell className="whitespace-nowrap text-right tabular-nums">
                        {formatVital(record.systolic_bp, 'mmHg')}
                      </TableCell>
                      <TableCell className="whitespace-nowrap text-right tabular-nums">
                        {formatVital(record.diastolic_bp, 'mmHg')}
                      </TableCell>
                      <TableCell className="whitespace-nowrap text-right tabular-nums">
                        {record.temperature === null || record.temperature === undefined
                          ? '—'
                          : `${record.temperature} ${vitalFieldUnit('temperature', record.temperature_unit)}`}
                      </TableCell>
                      <TableCell className="whitespace-nowrap text-right tabular-nums">
                        {formatVital(record.weight_kg, 'kg')}
                      </TableCell>
                      <TableCell className="whitespace-nowrap text-right tabular-nums">
                        {formatVital(record.spo2_percent, '%')}
                      </TableCell>
                    </TableRow>
                  );
                })}
              </TableBody>
            </Table>

            {pageCount > 1 ? (
              <div className="flex items-center justify-between text-sm text-muted-foreground">
                <span>
                  Page {currentPage} of {pageCount} · {filteredRecords.length} record
                  {filteredRecords.length === 1 ? '' : 's'}
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
