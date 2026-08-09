'use client';

import { useMemo, useState } from 'react';
import { Printer, Users } from 'lucide-react';
import { useAdminVisitsForDay, usePatientsForVisits } from '@/features/admin/hooks/useAdminOverview';
import { DateNavigator } from '@/features/admin/components/DateNavigator';
import { printLeadsSheet } from '@/features/admin/utils/printLeadsSheet';
import { Card, CardContent, CardHeader, CardTitle } from '@/shared/components/ui/Card';
import { Button } from '@/shared/components/ui/Button';
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
import { formatDisplayDate, todayDisplayDayKey } from '@/utils/timezone';

/** Admin "Leads" card: one row per patient registered on a given day
 * (deduplicated — a patient with two visits the same day still
 * contributes only one row), for building a physical follow-up/call
 * list. Deliberately reuses `useAdminVisitsForDay` +
 * `usePatientsForVisits` — the exact same GET /visits + per-patient
 * join Admin Overview's "Visit Activity" table already fetches for
 * this day — rather than a new endpoint; deduplication is purely a
 * client-side reduction over data already on hand. Uses `phone_number`
 * (the only contact-number field that exists today) as the leads
 * list's contact number — see this feature's own scoping note: a
 * dedicated `whatsapp_number` field is deferred to a later,
 * WhatsApp-sending build, not part of this pass.
 *
 * Has its own `selectedDate` state, independent of the Visit Activity
 * card above it — a self-contained section with its own date-scoped
 * fetch (via `useAdminVisitsForDay`, itself backed by one shared
 * `useAdminRecentVisits` query cached across every consumer on this
 * page), so browsing a different day for leads doesn't disturb what's
 * currently shown in Visit Activity. */
export function LeadsSection() {
  const [selectedDate, setSelectedDate] = useState(todayDisplayDayKey());
  const { visits, isLoading, isError, error, refetch } = useAdminVisitsForDay(selectedDate);
  const patientsById = usePatientsForVisits(visits);

  const leads = useMemo(() => {
    const seen = new Set();
    const list = [];
    for (const visit of visits) {
      if (seen.has(visit.patient_id)) continue;
      seen.add(visit.patient_id);
      const patient = patientsById[visit.patient_id];
      list.push({
        patientId: visit.patient_id,
        fullName: patient?.full_name ?? null,
        phoneNumber: patient?.phone_number ?? null,
      });
    }
    return list;
  }, [visits, patientsById]);

  const dateLabel = formatDisplayDate(selectedDate);
  const canPrint = !isLoading && !isError && leads.length > 0;

  async function handlePrint() {
    await printLeadsSheet({
      dateLabel,
      leads: leads.map((lead) => ({
        fullName: lead.fullName ?? '—',
        phoneNumber: lead.phoneNumber ?? '—',
      })),
    });
  }

  return (
    <Card>
      <CardHeader className="flex-col items-start gap-3 sm:flex-row sm:items-center sm:justify-between">
        <CardTitle>Leads</CardTitle>
        <div className="flex flex-wrap items-center gap-2">
          <DateNavigator selectedDate={selectedDate} onChange={setSelectedDate} />
          <Button size="sm" variant="outline" disabled={!canPrint} onClick={handlePrint}>
            <Printer className="h-3.5 w-3.5" />
            Print
          </Button>
        </div>
      </CardHeader>
      <CardContent className="flex flex-col gap-4">
        {isLoading ? (
          <PageLoader label="Loading leads" />
        ) : isError ? (
          <PageError error={error} reset={refetch} message="Couldn't load leads." />
        ) : leads.length === 0 ? (
          <p className="py-10 text-center text-sm text-muted-foreground">
            No patients were registered on {dateLabel}.
          </p>
        ) : (
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>Patient Name</TableHead>
                <TableHead>Phone Number</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {leads.map((lead) => (
                <TableRow key={lead.patientId}>
                  <TableCell className="font-medium text-foreground">
                    {lead.fullName ?? '…'}
                  </TableCell>
                  <TableCell>{lead.phoneNumber ?? '…'}</TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        )}
        {!isLoading && !isError ? (
          <p className="flex items-center gap-1.5 text-xs text-muted-foreground">
            <Users className="h-3.5 w-3.5" />
            {leads.length} patient{leads.length === 1 ? '' : 's'} on {dateLabel}
          </p>
        ) : null}
      </CardContent>
    </Card>
  );
}
