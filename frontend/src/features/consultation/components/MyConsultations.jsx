'use client';

import { useMemo, useState } from 'react';
import { Eye, Search } from 'lucide-react';
import {
  useMyConsultations,
  useVisitsByIds,
  usePatientsForVisits,
} from '@/features/consultation/hooks/useConsultation';
import { ConsultationRecordDialog } from '@/features/consultation/components/ConsultationRecordDialog';
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
// One generously-sized server-side page, then client-side search +
// display-pagination over it — the exact same shape MyVitalsRecords.jsx
// (Vitals) and MyRegistrations.jsx (Reception) already use, for the
// same reason: comfortably above any individual doctor's realistic
// lifetime completed-consultation volume today, with `meta.total`
// available to reveal if it ever isn't.
const FETCH_PAGE_SIZE = 100;

function matchesSearch(patient, visit, term) {
  if (!term) return true;
  const haystack = [
    patient?.full_name,
    patient?.mr_number,
    patient?.phone_number,
    visit?.queue_token,
  ]
    .filter(Boolean)
    .join(' ')
    .toLowerCase();
  return haystack.includes(term.toLowerCase());
}

/** The Doctor sibling of Reception's "My Registrations" and Vitals'
 * "My Vitals Records" — every consultation this doctor has personally
 * completed, newest first, searchable by patient name / MR / queue
 * token, with a read-only full-record dialog per row (and a reprint of
 * that consultation's prescription slip from inside it). */
export function MyConsultations() {
  const { consultations, meta, isLoading, isError, error, refetch } = useMyConsultations({
    page: 1,
    pageSize: FETCH_PAGE_SIZE,
  });

  const visitIds = useMemo(
    () => consultations.map((consultation) => consultation.visit_id),
    [consultations],
  );
  const { visitsById, isLoading: isLoadingVisits } = useVisitsByIds(visitIds);
  const visits = useMemo(
    () => visitIds.map((id) => visitsById[id]).filter(Boolean),
    [visitIds, visitsById],
  );
  const patientsById = usePatientsForVisits(visits);

  const [searchTerm, setSearchTerm] = useState('');
  const [page, setPage] = useState(1);
  const debouncedSearch = useDebouncedValue(searchTerm, 200);
  const [selected, setSelected] = useState(null);

  const filtered = useMemo(() => {
    if (!debouncedSearch) return consultations;
    return consultations.filter((consultation) => {
      const visit = visitsById[consultation.visit_id];
      const patient = visit ? patientsById[visit.patient_id] : undefined;
      return matchesSearch(patient, visit, debouncedSearch);
    });
  }, [consultations, visitsById, patientsById, debouncedSearch]);

  const pageCount = Math.max(1, Math.ceil(filtered.length / DISPLAY_PAGE_SIZE));
  const currentPage = Math.min(page, pageCount);
  const paged = filtered.slice(
    (currentPage - 1) * DISPLAY_PAGE_SIZE,
    currentPage * DISPLAY_PAGE_SIZE,
  );

  function handleSearchChange(value) {
    setSearchTerm(value);
    setPage(1);
  }

  if (isLoading) return <PageLoader label="Loading your consultations" />;
  if (isError) {
    return <PageError error={error} reset={refetch} message="Couldn't load your consultations." />;
  }

  const selectedVisit = selected ? visitsById[selected.visit_id] : undefined;
  const selectedPatient = selectedVisit ? patientsById[selectedVisit.patient_id] : undefined;

  return (
    <Card>
      <CardHeader>
        <CardTitle>My Consultations</CardTitle>
      </CardHeader>
      <CardContent className="flex flex-col gap-5">
        <div className="relative sm:max-w-xs">
          <Search className="pointer-events-none absolute left-2.5 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground" />
          <Input
            value={searchTerm}
            onChange={(event) => handleSearchChange(event.target.value)}
            placeholder="Search by patient name, MR number, or token"
            className="pl-8"
          />
        </div>

        {consultations.length === 0 ? (
          <p className="py-10 text-center text-sm text-muted-foreground">
            No completed consultations yet — they will appear here after you complete one.
          </p>
        ) : filtered.length === 0 ? (
          <p className="py-10 text-center text-sm text-muted-foreground">
            No consultations match &quot;{debouncedSearch}&quot;.
          </p>
        ) : (
          <>
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>Completed</TableHead>
                  <TableHead>Queue Token</TableHead>
                  <TableHead>Patient</TableHead>
                  <TableHead>MR #</TableHead>
                  <TableHead />
                </TableRow>
              </TableHeader>
              <TableBody>
                {paged.map((consultation) => {
                  const visit = visitsById[consultation.visit_id];
                  const patient = visit ? patientsById[visit.patient_id] : undefined;
                  const completedAt = consultation.completed_at ?? consultation.created_at;
                  return (
                    <TableRow key={consultation.id}>
                      <TableCell className="whitespace-nowrap">
                        {displayDayKey(completedAt)} {formatDisplayTime(completedAt)}
                      </TableCell>
                      <TableCell className="whitespace-nowrap font-mono">
                        {visit ? visit.queue_token : isLoadingVisits ? '…' : '—'}
                      </TableCell>
                      <TableCell className="max-w-[200px] truncate font-medium text-foreground">
                        {patient ? patient.full_name : '…'}
                      </TableCell>
                      <TableCell className="whitespace-nowrap font-mono text-xs">
                        {patient ? patient.mr_number : '…'}
                      </TableCell>
                      <TableCell>
                        <Button
                          size="sm"
                          variant="outline"
                          onClick={() => setSelected(consultation)}
                        >
                          <Eye className="h-3.5 w-3.5" />
                          View
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
                  Page {currentPage} of {pageCount} · {filtered.length} consultation
                  {filtered.length === 1 ? '' : 's'}
                  {meta && meta.total > consultations.length
                    ? ` (showing the most recent ${consultations.length} of ${meta.total})`
                    : ''}
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

      <ConsultationRecordDialog
        consultation={selected}
        visit={selectedVisit}
        patient={selectedPatient}
        open={Boolean(selected)}
        onClose={() => setSelected(null)}
      />
    </Card>
  );
}
