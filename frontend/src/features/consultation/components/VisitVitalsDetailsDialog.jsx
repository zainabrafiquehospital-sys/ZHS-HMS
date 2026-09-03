'use client';

import { useVitalsForVisit } from '@/features/vitals/hooks/useVitals';
import { VitalsRecordList } from '@/features/vitals/components/VitalsRecordList';
import { DetailsDialog } from '@/shared/components/ui/DetailsDialog';
import { PageLoader } from '@/shared/components/PageLoader';
import { PageError } from '@/shared/components/PageError';

function DetailField({ label, value }) {
  return (
    <div className="flex flex-col gap-0.5">
      <span className="text-xs uppercase tracking-wide text-muted-foreground">{label}</span>
      <span className="font-medium text-foreground">{value ?? '—'}</span>
    </div>
  );
}

/** Read-only "browse before you start" detail for one Doctor-dashboard
 * patient card (2026-09-03) — Token Number, Patient Name, Age, and every
 * vitals reading actually recorded for this visit. Opening it is pure
 * browsing: it never starts the consultation and never claims the
 * visit. Vitals come from `useVitalsForVisit`, whose cache key is
 * shared with the dashboard's own per-card `useVitalsForVisits`, so
 * opening this dialog is a cache hit, not a new request. */
export function VisitVitalsDetailsDialog({ visit, patient, open, onClose }) {
  const {
    data: records,
    isLoading,
    isError,
    error,
    refetch,
  } = useVitalsForVisit(open ? visit?.id : undefined);

  const emptyLabel = visit?.vitals_required
    ? 'Vitals were required for this visit, but none have been recorded yet.'
    : 'Vitals were not required for this visit.';

  return (
    <DetailsDialog
      open={open}
      onClose={onClose}
      title={patient ? patient.full_name : 'Visit Details'}
      subtitle={
        visit ? `${visit.queue_token}${patient ? ` · MR: ${patient.mr_number}` : ''}` : undefined
      }
    >
      <div className="flex flex-col gap-5">
        <div className="grid grid-cols-1 gap-3 sm:grid-cols-3">
          <DetailField label="Token Number" value={visit?.queue_token} />
          <DetailField label="Patient Name" value={patient?.full_name} />
          <DetailField
            label="Age"
            value={
              patient?.age_years !== null && patient?.age_years !== undefined
                ? `${patient.age_years} years`
                : undefined
            }
          />
        </div>

        <div className="flex flex-col gap-2">
          <span className="text-xs font-medium uppercase tracking-wide text-muted-foreground">
            Recorded Vitals
          </span>
          {isLoading ? (
            <PageLoader label="Loading vitals" />
          ) : isError ? (
            <PageError
              error={error}
              reset={refetch}
              message="Couldn't load vitals for this visit."
            />
          ) : (
            <VitalsRecordList
              records={records}
              ageYears={patient?.age_years}
              emptyLabel={emptyLabel}
            />
          )}
        </div>
      </div>
    </DetailsDialog>
  );
}
