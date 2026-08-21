'use client';

import { useRouter } from 'next/navigation';
import { useBillingWorklist, usePatientsForVisits } from '@/features/billing/hooks/useBilling';
import { VisitProcedureDisplay } from '@/features/visits/components/VisitProcedureDisplay';
import { Card, CardContent, CardHeader, CardTitle } from '@/shared/components/ui/Card';
import { Button } from '@/shared/components/ui/Button';
import { Badge } from '@/shared/components/ui/Badge';
import { PageLoader } from '@/shared/components/PageLoader';
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/shared/components/ui/Table';

export function BillingWorklist() {
  const router = useRouter();
  const { visits, isLoading } = useBillingWorklist();
  const patientsById = usePatientsForVisits(visits);

  if (isLoading) return <PageLoader label="Loading billing worklist" />;

  return (
    <Card>
      <CardHeader>
        <CardTitle>Waiting for Billing ({visits.length})</CardTitle>
      </CardHeader>
      <CardContent>
        {visits.length === 0 ? (
          <p className="py-6 text-center text-sm text-muted-foreground">
            No visits currently waiting for billing.
          </p>
        ) : (
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>Queue Token</TableHead>
                <TableHead>Patient</TableHead>
                <TableHead>Procedure</TableHead>
                <TableHead>Status</TableHead>
                <TableHead />
              </TableRow>
            </TableHeader>
            <TableBody>
              {visits.map((visit) => {
                const patient = patientsById[visit.patient_id];
                return (
                  <TableRow key={visit.id}>
                    <TableCell className="font-mono">{visit.queue_token}</TableCell>
                    <TableCell>
                      {patient ? `${patient.full_name} (${patient.mr_number})` : '…'}
                    </TableCell>
                    <TableCell>
                      <VisitProcedureDisplay visit={visit} />
                    </TableCell>
                    <TableCell>
                      <Badge
                        variant={visit.status === 'payment_pending' ? 'warning' : 'outline'}
                        className="capitalize"
                      >
                        {visit.status.replaceAll('_', ' ')}
                      </Badge>
                    </TableCell>
                    <TableCell>
                      <Button size="sm" onClick={() => router.push(`/billing/${visit.id}`)}>
                        Bill Visit
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
