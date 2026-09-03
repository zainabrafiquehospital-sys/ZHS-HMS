'use client';

import { usePatientVitalsHistory } from '@/features/vitals/hooks/useVitals';
import { VitalsRecordList } from '@/features/vitals/components/VitalsRecordList';
import { DetailsDialog } from '@/shared/components/ui/DetailsDialog';
import { PageLoader } from '@/shared/components/PageLoader';
import { PageError } from '@/shared/components/PageError';

/** "Show Details" cross-visit vitals history (2026-08-28 addition) —
 * a patient's full vitals history across every one of their visits,
 * newest first, opened from both the Vitals Worklist (before recording
 * a new reading) and ConsultationPanel (a doctor reviewing everything
 * on file, not just this visit's own readings).
 *
 * The per-record rendering lives in the shared `VitalsRecordList`
 * (extracted 2026-09-03) — same component ConsultationPanel's
 * `RecordedVitals` and the Doctor dashboard's `VisitVitalsDetailsDialog`
 * use, so a Celsius-tagged historical record and a Fahrenheit-tagged
 * new one are each classified/labelled against their own stored unit,
 * never misread as the other. */
export function VitalsHistoryDialog({ patient, open, onClose }) {
  const {
    data: records,
    isLoading,
    isError,
    error,
    refetch,
  } = usePatientVitalsHistory(open ? patient?.id : undefined);

  return (
    <DetailsDialog
      open={open}
      onClose={onClose}
      title={patient ? patient.full_name : 'Vitals History'}
      subtitle={patient ? `${patient.mr_number} · Vitals History (all visits)` : undefined}
    >
      {isLoading ? (
        <PageLoader label="Loading vitals history" />
      ) : isError ? (
        <PageError error={error} reset={refetch} message="Couldn't load vitals history." />
      ) : (
        <VitalsRecordList
          records={records}
          ageYears={patient?.age_years}
          emptyLabel="No vitals recorded for this patient yet."
        />
      )}
    </DetailsDialog>
  );
}
