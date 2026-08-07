'use client';

import { useRouter } from 'next/navigation';
import { useVitalsWorklist, useVisitsByIds, usePatientsForVisits } from '@/features/vitals/hooks/useVitals';
import { Card, CardContent, CardHeader, CardTitle } from '@/shared/components/ui/Card';
import { Button } from '@/shared/components/ui/Button';
import { Badge } from '@/shared/components/ui/Badge';
import { PageLoader } from '@/shared/components/PageLoader';
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/shared/components/ui/Table';

export function VitalsWorklist() {
  const router = useRouter();
  const { data: entries, isLoading: isLoadingWorklist } = useVitalsWorklist();
  const visitIds = (entries ?? []).map((entry) => entry.visit_id);
  const { visitsById, isLoading: isLoadingVisits } = useVisitsByIds(visitIds);
  const visits = visitIds.map((id) => visitsById[id]).filter(Boolean);
  const patientsById = usePatientsForVisits(visits);

  if (isLoadingWorklist) return <PageLoader label="Loading vitals worklist" />;

  return (
    <Card>
      <CardHeader>
        <CardTitle>Waiting for Vitals ({(entries ?? []).length})</CardTitle>
      </CardHeader>
      <CardContent>
        {(entries ?? []).length === 0 ? (
          <p className="py-6 text-center text-sm text-muted-foreground">
            No patients currently waiting for vitals.
          </p>
        ) : (
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>Queue Token</TableHead>
                <TableHead>Patient</TableHead>
                <TableHead>Reason</TableHead>
                <TableHead />
              </TableRow>
            </TableHeader>
            <TableBody>
              {entries.map((entry) => {
                const visit = visitsById[entry.visit_id];
                const patient = visit ? patientsById[visit.patient_id] : undefined;
                return (
                  <TableRow key={entry.id}>
                    <TableCell className="font-mono">
                      {visit ? visit.queue_token : isLoadingVisits ? '…' : '—'}
                    </TableCell>
                    <TableCell>
                      {patient ? `${patient.full_name} (${patient.mr_number})` : '…'}
                    </TableCell>
                    <TableCell>
                      {entry.reason ? (
                        entry.reason
                      ) : (
                        <Badge variant="outline">Intake</Badge>
                      )}
                    </TableCell>
                    <TableCell>
                      <Button size="sm" onClick={() => router.push(`/vitals/${entry.visit_id}`)}>
                        Record Vitals
                      </Button>
                    </TableCell>
                  </TableRow>
                );
              })}
            </TableBody>
          </Table>
        )}
      </CardContent>
    </Card>
  );
}
