'use client';

import { useState } from 'react';
import { Printer } from 'lucide-react';
import { usePrintPrescriptionSlip } from '@/features/consultation/hooks/useConsultation';
import { useVitalsForVisit } from '@/features/vitals/hooks/useVitals';
import { VitalsRecordList } from '@/features/vitals/components/VitalsRecordList';
import { ConsultationClinicalDetails } from '@/features/consultation/components/ConsultationClinicalDetails';
import { DetailsDialog } from '@/shared/components/ui/DetailsDialog';
import { Button } from '@/shared/components/ui/Button';
import { PageLoader } from '@/shared/components/PageLoader';
import { PageError } from '@/shared/components/PageError';
import { formatDisplayDate, formatDisplayTime, displayDayKey } from '@/utils/timezone';

/** Read-only full record of one past completed consultation (2026-09-03),
 * opened from the Doctor dashboard's "My Consultations" list — reuses
 * the shared DetailsDialog + VitalsRecordList + ConsultationClinicalDetails
 * so nothing here is a bespoke render. "Print Prescription" reuses the
 * exact usePrintPrescriptionSlip / GET /consultations/{id}/slip/print
 * pipeline the post-Complete panel uses, so any past consultation's slip
 * can be reprinted on demand. */
export function ConsultationRecordDialog({ consultation, patient, visit, open, onClose }) {
  const printPrescription = usePrintPrescriptionSlip();
  const [printError, setPrintError] = useState(null);

  const {
    data: records,
    isLoading: isLoadingVitals,
    isError: isVitalsError,
    error: vitalsError,
    refetch: refetchVitals,
  } = useVitalsForVisit(open ? consultation?.visit_id : undefined);

  async function handlePrint() {
    setPrintError(null);
    try {
      await printPrescription.mutateAsync(consultation.id);
    } catch (err) {
      setPrintError(err.message || 'Unable to open the prescription slip.');
    }
  }

  const completedAt = consultation?.completed_at ?? consultation?.created_at;

  return (
    <DetailsDialog
      open={open}
      onClose={onClose}
      title={patient ? patient.full_name : 'Consultation'}
      subtitle={
        visit
          ? `${visit.queue_token}${patient ? ` · MR: ${patient.mr_number}` : ''}`
          : patient
            ? `MR: ${patient.mr_number}`
            : undefined
      }
    >
      <div className="flex flex-col gap-5">
        {completedAt ? (
          <p className="text-xs text-muted-foreground">
            Completed {formatDisplayDate(displayDayKey(completedAt))} at{' '}
            {formatDisplayTime(completedAt)}
          </p>
        ) : null}

        <div className="flex flex-col gap-2">
          <span className="text-xs font-medium uppercase tracking-wide text-muted-foreground">
            Vitals
          </span>
          {isLoadingVitals ? (
            <PageLoader label="Loading vitals" />
          ) : isVitalsError ? (
            <PageError
              error={vitalsError}
              reset={refetchVitals}
              message="Couldn't load vitals for this visit."
            />
          ) : (
            <VitalsRecordList
              records={records}
              ageYears={patient?.age_years}
              emptyLabel="No vitals were recorded for this visit."
            />
          )}
        </div>

        <ConsultationClinicalDetails consultation={consultation} />

        <div className="flex flex-col gap-2 border-t border-border pt-4 sm:flex-row">
          <Button type="button" onClick={handlePrint} disabled={printPrescription.isPending}>
            <Printer className="h-4 w-4" />
            {printPrescription.isPending ? 'Preparing…' : 'Print Prescription'}
          </Button>
        </div>
        {printError ? (
          <p className="rounded-md bg-destructive/10 px-3 py-2 text-sm text-destructive">
            {printError}
          </p>
        ) : null}
      </div>
    </DetailsDialog>
  );
}
