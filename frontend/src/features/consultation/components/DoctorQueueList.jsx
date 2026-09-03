'use client';

import { useState } from 'react';
import { useRouter } from 'next/navigation';
import { HeartPulse, Printer, Stethoscope } from 'lucide-react';
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
import {
  getWorstSeverity,
  SEVERITY_BADGE_VARIANT,
  SEVERITY_LABEL,
} from '@/features/vitals/utils/vitalsSeverity';
import {
  deriveVitalsStatus,
  VITALS_STATUS,
  VITALS_STATUS_LABEL,
  VITALS_STATUS_BADGE_VARIANT,
} from '@/features/consultation/utils/vitalsStatus';
import { VisitVitalsDetailsDialog } from '@/features/consultation/components/VisitVitalsDetailsDialog';
import { VisitProcedureDisplay } from '@/features/visits/components/VisitProcedureDisplay';
import { VISIT_STATUS_BADGE_VARIANT } from '@/shared/constants/visitStatus';
import { Card, CardContent, CardHeader, CardTitle } from '@/shared/components/ui/Card';
import { Button } from '@/shared/components/ui/Button';
import { Badge } from '@/shared/components/ui/Badge';
import { PageLoader } from '@/shared/components/PageLoader';

/** The vitals-status badge on every Doctor-dashboard patient card.
 * Three backend-distinguishable states (see
 * features/consultation/utils/vitalsStatus.js):
 *   - "Vitals Collected" — at least one reading on file. Rendered with
 *     the worst-severity chip the nurse saw appended when it's abnormal,
 *     so the triage signal the old severity-only badge carried is not
 *     lost.
 *   - "Vitals Pending" — none on file, visit was flagged vitals-required.
 *   - "Not Required" — none on file, visit was not flagged.
 * The separate mid-consultation "Vitals Pending" detour card
 * (VitalsPendingCard, driven by useVitalsPendingForDoctor) is a
 * different surface and is unaffected. */
function VitalsStatusBadge({ records, vitalsRequired, ageYears, isLoading }) {
  if (isLoading) return <span className="text-sm text-muted-foreground">…</span>;

  const statusValue = deriveVitalsStatus(records, vitalsRequired);

  if (statusValue === VITALS_STATUS.COLLECTED) {
    const level = getWorstSeverity(records[records.length - 1], { ageYears });
    return (
      <span className="inline-flex flex-wrap items-center gap-1.5">
        <Badge variant={VITALS_STATUS_BADGE_VARIANT[VITALS_STATUS.COLLECTED]}>
          {VITALS_STATUS_LABEL[VITALS_STATUS.COLLECTED]}
        </Badge>
        {level && level !== 'normal' ? (
          <Badge variant={SEVERITY_BADGE_VARIANT[level]} className="text-[10px] capitalize">
            {SEVERITY_LABEL[level]}
          </Badge>
        ) : null}
      </span>
    );
  }

  return (
    <Badge variant={VITALS_STATUS_BADGE_VARIANT[statusValue]}>
      {VITALS_STATUS_LABEL[statusValue]}
    </Badge>
  );
}

/** Wraps the card's action buttons so a click on them never also
 * bubbles up to the card-level "open details" handler. */
function CardActions({ children }) {
  return (
    <div
      className="mt-1 flex flex-wrap gap-2"
      onClick={(event) => event.stopPropagation()}
      role="presentation"
    >
      {children}
    </div>
  );
}

const CARD_CLASS =
  'flex cursor-pointer items-start gap-3 rounded-md border border-border bg-card p-4 ' +
  'transition-colors hover:border-primary/40 hover:bg-muted/30 ' +
  'focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring';

function cardKeyActivation(event, onActivate) {
  if (event.key === 'Enter' || event.key === ' ') {
    event.preventDefault();
    onActivate();
  }
}

/** One visit's card in "Waiting for You" / "Unclaimed Visits" (2026-08-28
 * card-layout redesign — a genuinely separate component/file from
 * VitalsWorklist.jsx's own `WorklistCard`, per Step 3 of the Vitals
 * plan, even though it deliberately reuses the exact same shape:
 * icon circle in `bg-primary/10 text-primary`, `border-border`/
 * `bg-card`/`rounded-md`, same padding/radius). Every field/action the
 * old table row carried is still here — queue token, patient, itemized
 * procedure, vitals severity, visit status, and both actions. */
function QueueCard({
  visit,
  patient,
  vitalsRecords,
  isLoadingVitals,
  actionLabel,
  onAction,
  isActionPending,
  onViewSlip,
  viewingSlipVisitId,
  onOpenDetails,
}) {
  const openDetails = () => onOpenDetails(visit);
  return (
    <div
      className={CARD_CLASS}
      role="button"
      tabIndex={0}
      aria-label={`View details for ${patient ? patient.full_name : visit.queue_token}`}
      onClick={openDetails}
      onKeyDown={(event) => cardKeyActivation(event, openDetails)}
    >
      <div className="flex h-10 w-10 shrink-0 items-center justify-center rounded-full bg-primary/10 text-primary">
        <Stethoscope className="h-5 w-5" />
      </div>
      <div className="flex flex-1 flex-col gap-2">
        <div className="flex flex-wrap items-start justify-between gap-x-3 gap-y-1">
          <div className="flex flex-col">
            <span className="font-medium text-foreground">{patient ? patient.full_name : '…'}</span>
            <span className="text-xs text-muted-foreground">
              {patient ? `MR: ${patient.mr_number}` : ''}
            </span>
          </div>
          <span className="whitespace-nowrap font-mono text-xs text-muted-foreground">
            {visit.queue_token}
          </span>
        </div>
        <VisitProcedureDisplay visit={visit} className="text-xs text-muted-foreground" />
        <div className="flex flex-wrap items-center gap-3 text-xs">
          <span className="flex flex-wrap items-center gap-1.5">
            <span className="text-muted-foreground">Vitals:</span>
            <VitalsStatusBadge
              records={vitalsRecords}
              vitalsRequired={visit.vitals_required}
              ageYears={patient?.age_years}
              isLoading={isLoadingVitals}
            />
          </span>
          <Badge variant="outline" className="capitalize">
            {visit.status.replaceAll('_', ' ')}
          </Badge>
        </div>
        <CardActions>
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
        </CardActions>
      </div>
    </div>
  );
}

function QueueCardGrid({
  visits,
  patientsById,
  vitalsByVisitId,
  isLoadingVitals,
  actionLabel,
  onAction,
  isActionPending,
  onViewSlip,
  viewingSlipVisitId,
  onOpenDetails,
}) {
  return (
    <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-3">
      {visits.map((visit) => (
        <QueueCard
          key={visit.id}
          visit={visit}
          patient={patientsById[visit.patient_id]}
          vitalsRecords={vitalsByVisitId[visit.id]}
          isLoadingVitals={isLoadingVitals}
          actionLabel={actionLabel}
          onAction={onAction}
          isActionPending={isActionPending}
          onViewSlip={onViewSlip}
          viewingSlipVisitId={viewingSlipVisitId}
          onOpenDetails={onOpenDetails}
        />
      ))}
    </div>
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
 * patient who isn't back yet) — this card exists purely so they can
 * see who's coming next and who's still with the nurse, not
 * disappearing from view entirely (Part 3's own framing). */
function VitalsPendingCard({ visit, reason, patient, onOpenDetails }) {
  const openDetails = () => onOpenDetails(visit);
  return (
    <div
      className={CARD_CLASS}
      role="button"
      tabIndex={0}
      aria-label={`View details for ${patient ? patient.full_name : visit.queue_token}`}
      onClick={openDetails}
      onKeyDown={(event) => cardKeyActivation(event, openDetails)}
    >
      <div className="flex h-10 w-10 shrink-0 items-center justify-center rounded-full bg-primary/10 text-primary">
        <HeartPulse className="h-5 w-5" />
      </div>
      <div className="flex flex-1 flex-col gap-2">
        <div className="flex flex-wrap items-start justify-between gap-x-3 gap-y-1">
          <div className="flex flex-col">
            <span className="font-medium text-foreground">{patient ? patient.full_name : '…'}</span>
            <span className="text-xs text-muted-foreground">
              {patient ? `MR: ${patient.mr_number}` : ''}
            </span>
          </div>
          <span className="whitespace-nowrap font-mono text-xs text-muted-foreground">
            {visit.queue_token}
          </span>
        </div>
        <VisitProcedureDisplay visit={visit} className="text-xs text-muted-foreground" />
        <p className="text-xs text-muted-foreground">{VITALS_PENDING_REASON_LABEL[reason]}</p>
        <div>
          <Badge variant={VISIT_STATUS_BADGE_VARIANT.waiting_vitals} className="gap-1">
            <HeartPulse className="h-3 w-3" />
            Vitals Pending
          </Badge>
        </div>
      </div>
    </div>
  );
}

function VitalsPendingCardGrid({ entries, patientsById, onOpenDetails }) {
  return (
    <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-3">
      {entries.map(({ visit, reason }) => (
        <VitalsPendingCard
          key={visit.id}
          visit={visit}
          reason={reason}
          patient={patientsById[visit.patient_id]}
          onOpenDetails={onOpenDetails}
        />
      ))}
    </div>
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
  // Tracks which single card's slip is currently opening, mirroring
  // MyRegistrations.jsx's identical `printingVisitId` one-in-flight
  // pattern — disables only that card's button, not every "View Slip"
  // button on the screen.
  const [viewingSlipVisitId, setViewingSlipVisitId] = useState(null);
  // Read-only "browse this card before starting" detail — never starts
  // or claims the consultation (see VisitVitalsDetailsDialog).
  const [detailsVisit, setDetailsVisit] = useState(null);

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
            <QueueCardGrid
              visits={myQueue}
              patientsById={patientsById}
              vitalsByVisitId={vitalsByVisitId}
              isLoadingVitals={isLoadingVitals}
              actionLabel="Start Consultation"
              onAction={handleStart}
              isActionPending={startConsultation.isPending}
              onViewSlip={handleViewSlip}
              viewingSlipVisitId={viewingSlipVisitId}
              onOpenDetails={setDetailsVisit}
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
              <VitalsPendingCardGrid
                entries={vitalsPending}
                patientsById={patientsById}
                onOpenDetails={setDetailsVisit}
              />
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
              <QueueCardGrid
                visits={unassigned}
                patientsById={patientsById}
                vitalsByVisitId={vitalsByVisitId}
                isLoadingVitals={isLoadingVitals}
                actionLabel="Claim & Start"
                onAction={handleStart}
                isActionPending={startConsultation.isPending}
                onViewSlip={handleViewSlip}
                viewingSlipVisitId={viewingSlipVisitId}
                onOpenDetails={setDetailsVisit}
              />
            )}
          </CardContent>
        </Card>
      ) : null}

      <VisitVitalsDetailsDialog
        visit={detailsVisit}
        patient={detailsVisit ? patientsById[detailsVisit.patient_id] : undefined}
        open={Boolean(detailsVisit)}
        onClose={() => setDetailsVisit(null)}
      />
    </div>
  );
}
