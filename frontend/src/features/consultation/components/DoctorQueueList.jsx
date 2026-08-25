'use client';

import { useState } from 'react';
import { useRouter } from 'next/navigation';
import { HeartPulse, Printer } from 'lucide-react';
import { useAuth } from '@/features/auth/hooks/useAuth';
import {
  useMyQueue,
  useUnassignedQueue,
  usePatientsForVisits,
  useStartConsultation,
  useVitalsPendingForDoctor,
  useViewRegistrationSlip,
} from '@/features/consultation/hooks/useConsultation';
import { useToast } from '@/shared/components/toast/ToastProvider';
import { useVitalsForVisits } from '@/features/vitals/hooks/useVitals';
import { getWorstSeverity, SEVERITY_BADGE_VARIANT, SEVERITY_LABEL } from '@/features/vitals/utils/vitalsSeverity';
import { VisitProcedureDisplay } from '@/features/visits/components/VisitProcedureDisplay';
import { VISIT_STATUS_BADGE_VARIANT } from '@/shared/constants/visitStatus';
import { Card, CardContent, CardHeader, CardTitle } from '@/shared/components/ui/Card';
import { Button } from '@/shared/components/ui/Button';
import { Badge } from '@/shared/components/ui/Badge';
import { PageLoader } from '@/shared/components/PageLoader';
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/shared/components/ui/Table';

/** Worst severity found in a visit's most recently recorded vitals —
 * `null` (rendered as "—") when the visit has no vitals recorded at
 * all, which is a legitimate state (Reception can route straight to
 * doctor without vitals; see RegisterVisitRequest.vitals_required),
 * not an error. Same severity signal the nurse saw while recording it
 * (see RecordVitalsForm.jsx) — a triage cue for which patient to see
 * next, not a new one-off indicator. */
function VitalsBadge({ records, ageYears, isLoading }) {
  if (isLoading) return <span className="text-sm text-muted-foreground">…</span>;
  const latest = records && records.length > 0 ? records[records.length - 1] : null;
  const level = getWorstSeverity(latest, { ageYears });
  if (!level) return <span className="text-sm text-muted-foreground">—</span>;
  return (
    <Badge variant={SEVERITY_BADGE_VARIANT[level]} className="capitalize">
      {SEVERITY_LABEL[level]}
    </Badge>
  );
}

function QueueTable({
  visits,
  patientsById,
  vitalsByVisitId,
  isLoadingVitals,
  actionLabel,
  onAction,
  isActionPending,
  onViewSlip,
  viewingSlipVisitId,
}) {
  return (
    <Table>
      <TableHeader>
        <TableRow>
          <TableHead>Queue Token</TableHead>
          <TableHead>Patient</TableHead>
          <TableHead>Procedure</TableHead>
          <TableHead>Vitals</TableHead>
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
                <VitalsBadge
                  records={vitalsByVisitId[visit.id]}
                  ageYears={patient?.age_years}
                  isLoading={isLoadingVitals}
                />
              </TableCell>
              <TableCell>
                <Badge variant="outline" className="capitalize">
                  {visit.status.replaceAll('_', ' ')}
                </Badge>
              </TableCell>
              <TableCell>
                <div className="flex gap-2">
                  <Button size="sm" onClick={() => onAction(visit.id)} disabled={isActionPending}>
                    {actionLabel}
                  </Button>
                  <Button
                    size="sm"
                    variant="outline"
                    onClick={() => onViewSlip(visit.id)}
                    disabled={viewingSlipVisitId === visit.id}
                  >
                    <Printer className="h-3.5 w-3.5" />
                    {viewingSlipVisitId === visit.id ? 'Opening…' : 'View Slip'}
                  </Button>
                </div>
              </TableCell>
            </TableRow>
          );
        })}
      </TableBody>
    </Table>
  );
}

const VITALS_PENDING_REASON_LABEL = {
  intake: 'Awaiting initial vitals',
  detour: 'Sent back to vitals mid-consultation',
};

/** Visits currently "with the vitals nurse" — see
 * useVitalsPendingForDoctor's own docstring for the two cases this
 * covers. Deliberately no action button: there is nothing for the
 * doctor to do here (they can't start/resume a consultation on a
 * patient who isn't back yet) — this table exists purely so they can
 * see who's coming next and who's still with the nurse, not
 * disappearing from view entirely (Part 3's own framing). */
function VitalsPendingTable({ entries, patientsById }) {
  return (
    <Table>
      <TableHeader>
        <TableRow>
          <TableHead>Queue Token</TableHead>
          <TableHead>Patient</TableHead>
          <TableHead>Procedure</TableHead>
          <TableHead>Reason</TableHead>
          <TableHead>Status</TableHead>
        </TableRow>
      </TableHeader>
      <TableBody>
        {entries.map(({ visit, reason }) => {
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
              <TableCell className="text-muted-foreground">
                {VITALS_PENDING_REASON_LABEL[reason]}
              </TableCell>
              <TableCell>
                <Badge variant={VISIT_STATUS_BADGE_VARIANT.waiting_vitals} className="gap-1">
                  <HeartPulse className="h-3 w-3" />
                  Vitals Pending
                </Badge>
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
  const { visits: vitalsPending, isLoading: isLoadingVitalsPending } = useVitalsPendingForDoctor(
    user?.id,
  );
  const myQueue = myQueueData ?? [];
  const unassigned = unassignedData ?? [];
  const allVisits = [...myQueue, ...unassigned];
  const patientsById = usePatientsForVisits([
    ...allVisits,
    ...vitalsPending.map((entry) => entry.visit),
  ]);
  const { vitalsByVisitId, isLoading: isLoadingVitals } = useVitalsForVisits(allVisits);
  const startConsultation = useStartConsultation();
  const viewSlip = useViewRegistrationSlip();
  const { toast } = useToast();
  // Tracks which single row's slip is currently opening, mirroring
  // MyRegistrations.jsx's identical `printingVisitId` one-in-flight
  // pattern — disables only that row's button, not every "View Slip"
  // button on the screen.
  const [viewingSlipVisitId, setViewingSlipVisitId] = useState(null);

  async function handleStart(visitId) {
    await startConsultation.mutateAsync(visitId);
    router.push(`/doctor/consultation/${visitId}`);
  }

  async function handleViewSlip(visitId) {
    if (viewingSlipVisitId) return;
    setViewingSlipVisitId(visitId);
    try {
      await viewSlip.mutateAsync(visitId);
    } catch (error) {
      toast.error({
        title: 'Unable to open this registration slip',
        description: error.message,
        onRetry: () => handleViewSlip(visitId),
      });
    } finally {
      setViewingSlipVisitId(null);
    }
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
              vitalsByVisitId={vitalsByVisitId}
              isLoadingVitals={isLoadingVitals}
              actionLabel="Start Consultation"
              onAction={handleStart}
              isActionPending={startConsultation.isPending}
              onViewSlip={handleViewSlip}
              viewingSlipVisitId={viewingSlipVisitId}
            />
          )}
        </CardContent>
      </Card>

      {/* Patients currently with the vitals nurse — either not yet seen
          today (intake) or sent back mid-consultation (detour). Hidden
          entirely when empty, same "don't distract from the normal
          case" reasoning as Unclaimed Visits below. */}
      {isLoadingVitalsPending || vitalsPending.length > 0 ? (
        <Card>
          <CardHeader>
            <CardTitle>Vitals Pending ({vitalsPending.length})</CardTitle>
          </CardHeader>
          <CardContent>
            {isLoadingVitalsPending ? (
              <PageLoader label="Loading vitals-pending patients" />
            ) : (
              <VitalsPendingTable entries={vitalsPending} patientsById={patientsById} />
            )}
          </CardContent>
        </Card>
      ) : null}

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
                vitalsByVisitId={vitalsByVisitId}
                isLoadingVitals={isLoadingVitals}
                actionLabel="Claim & Start"
                onAction={handleStart}
                isActionPending={startConsultation.isPending}
                onViewSlip={handleViewSlip}
                viewingSlipVisitId={viewingSlipVisitId}
              />
            )}
          </CardContent>
        </Card>
      ) : null}
    </div>
  );
}
