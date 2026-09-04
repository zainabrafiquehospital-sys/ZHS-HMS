'use client';

import { useEffect, useState } from 'react';
import { Pencil, Printer } from 'lucide-react';
import { usePrintPrescriptionSlip } from '@/features/consultation/hooks/useConsultation';
import { useVitalsForVisit } from '@/features/vitals/hooks/useVitals';
import { VitalsRecordList } from '@/features/vitals/components/VitalsRecordList';
import { ConsultationClinicalDetails } from '@/features/consultation/components/ConsultationClinicalDetails';
import { ConsultationCorrectionForm } from '@/features/consultation/components/ConsultationCorrectionForm';
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
  const [isCorrecting, setIsCorrecting] = useState(false);
  // A correction saved from inside this dialog — shown in place of the
  // `consultation` prop until the dialog closes (the parent list is
  // invalidated separately and will have the fresh row on next open).
  const [corrected, setCorrected] = useState(null);

  // Reset the local edit/correction state whenever a different record
  // is opened or the dialog is closed.
  useEffect(() => {
    if (!open) {
      setIsCorrecting(false);
      setCorrected(null);
      setPrintError(null);
    }
  }, [open, consultation?.id]);

  const record = corrected ?? consultation;

  const {
    data: records,
    isLoading: isLoadingVitals,
    isError: isVitalsError,
    error: vitalsError,
    refetch: refetchVitals,
  } = useVitalsForVisit(open ? record?.visit_id : undefined);

  async function handlePrint() {
    setPrintError(null);
    try {
      await printPrescription.mutateAsync(record.id);
    } catch (err) {
      setPrintError(err.message || 'Unable to open the prescription slip.');
    }
  }

  const completedAt = record?.completed_at ?? record?.created_at;

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

        {isCorrecting ? (
          <ConsultationCorrectionForm
            consultation={record}
            onSaved={(updated) => {
              setCorrected(updated);
              setIsCorrecting(false);
            }}
            onCancel={() => setIsCorrecting(false)}
          />
        ) : (
          <>
            <ConsultationClinicalDetails consultation={record} />

            <div className="flex flex-col gap-2 border-t border-border pt-4 sm:flex-row">
              <Button type="button" onClick={handlePrint} disabled={printPrescription.isPending}>
                <Printer className="h-4 w-4" />
                {printPrescription.isPending ? 'Preparing…' : 'Print Prescription'}
              </Button>
              <Button type="button" variant="outline" onClick={() => setIsCorrecting(true)}>
                <Pencil className="h-4 w-4" />
                Edit / Correct
              </Button>
            </div>
            {printError ? (
              <p className="rounded-md bg-destructive/10 px-3 py-2 text-sm text-destructive">
                {printError}
              </p>
            ) : null}
          </>
        )}
      </div>
    </DetailsDialog>
  );
}
