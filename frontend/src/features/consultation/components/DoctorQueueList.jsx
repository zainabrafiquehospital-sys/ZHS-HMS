'use client';

import { useRouter } from 'next/navigation';
import { useAuth } from '@/features/auth/hooks/useAuth';
import {
  useMyQueue,
  useUnassignedQueue,
  usePatientsForVisits,
  useStartConsultation,
} from '@/features/consultation/hooks/useConsultation';
import { Card, CardContent, CardHeader, CardTitle } from '@/shared/components/ui/Card';
import { Button } from '@/shared/components/ui/Button';
import { Badge } from '@/shared/components/ui/Badge';
import { PageLoader } from '@/shared/components/PageLoader';
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/shared/components/ui/Table';

function QueueTable({ visits, patientsById, actionLabel, onAction, isActionPending }) {
  return (
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
              <TableCell>{visit.procedure}</TableCell>
              <TableCell>
                <Badge variant="outline" className="capitalize">
                  {visit.status.replaceAll('_', ' ')}
                </Badge>
              </TableCell>
              <TableCell>
                <Button size="sm" onClick={() => onAction(visit.id)} disabled={isActionPending}>
                  {actionLabel}
                </Button>
              </TableCell>
            </TableRow>
          );
        })}
      </TableBody>
    </Table>
  );
}

export function DoctorQueueList() {
  const { user } = useAuth();
  const router = useRouter();
  const { data: myQueueData, isLoading: isLoadingMyQueue } = useMyQueue(user?.id);
  const { data: unassignedData, isLoading: isLoadingUnassigned } = useUnassignedQueue();
  const myQueue = myQueueData ?? [];
  const unassigned = unassignedData ?? [];
  const patientsById = usePatientsForVisits([...myQueue, ...unassigned]);
  const startConsultation = useStartConsultation();

  async function handleStart(visitId) {
    await startConsultation.mutateAsync(visitId);
    router.push(`/doctor/consultation/${visitId}`);
  }

  if (isLoadingMyQueue) return <PageLoader label="Loading your queue" />;

  return (
    <div className="flex flex-col gap-6">
      <Card>
        <CardHeader>
          <CardTitle>Waiting for You ({myQueue.length})</CardTitle>
        </CardHeader>
        <CardContent>
          {myQueue.length === 0 ? (
            <p className="py-6 text-center text-sm text-muted-foreground">
              No patients currently waiting.
            </p>
          ) : (
            <QueueTable
              visits={myQueue}
              patientsById={patientsById}
              actionLabel="Start Consultation"
              onAction={handleStart}
              isActionPending={startConsultation.isPending}
            />
          )}
        </CardContent>
      </Card>

      {/* Fast-registration Visits Reception found no online doctor to
          auto-assign — any doctor may claim one here. Hidden entirely
          when empty so it never distracts from "my queue" during
          normal, fully-staffed operation. */}
      {isLoadingUnassigned || unassigned.length > 0 ? (
        <Card>
          <CardHeader>
            <CardTitle>Unclaimed Visits ({unassigned.length})</CardTitle>
          </CardHeader>
          <CardContent>
            {isLoadingUnassigned ? (
              <PageLoader label="Loading unclaimed visits" />
            ) : (
              <QueueTable
                visits={unassigned}
                patientsById={patientsById}
                actionLabel="Claim & Start"
                onAction={handleStart}
                isActionPending={startConsultation.isPending}
              />
            )}
          </CardContent>
        </Card>
      ) : null}
    </div>
  );
}
