'use client';

import { usePatientVitalsHistory } from '@/features/vitals/hooks/useVitals';
import {
  ALL_VITALS_FIELDS,
  VITAL_FIELD_LABELS,
  vitalFieldUnit,
  VITALS_FIELDS_WITH_SEVERITY,
  SEVERITY_BADGE_VARIANT,
  SEVERITY_LABEL,
  getVitalSeverity,
} from '@/features/vitals/utils/vitalsSeverity';
import { DetailsDialog } from '@/shared/components/ui/DetailsDialog';
import { Badge } from '@/shared/components/ui/Badge';
import { PageLoader } from '@/shared/components/PageLoader';
import { PageError } from '@/shared/components/PageError';
import { formatDisplayDate, formatDisplayTime, displayDayKey } from '@/utils/timezone';

/** "Show Details" cross-visit vitals history (2026-08-28 addition) —
 * a patient's full vitals history across every one of their visits,
 * newest first, opened from both the Vitals Worklist (before recording
 * a new reading) and ConsultationPanel (a doctor reviewing everything
 * on file, not just this visit's own readings — see RecordedVitals'
 * own docstring, which already covers "everything recorded for THIS
 * visit"; this is the patient-wide superset).
 *
 * Every record renders using its own stored `temperature_unit` — never
 * a global assumption — the exact same `getVitalSeverity`/
 * `vitalFieldUnit` machinery ConsultationPanel's `RecordedVitals` and
 * RecordVitalsForm's `PreviousVitalsCard` already use, so a Celsius-
 * tagged historical record and a Fahrenheit-tagged new one sitting side
 * by side in the same list are each classified and labeled correctly,
 * never misread as the other (Step 1's own "no reinterpretation"
 * requirement, still enforced here). */
export function VitalsHistoryDialog({ patient, open, onClose }) {
  const { data: records, isLoading, isError, error, refetch } = usePatientVitalsHistory(
    open ? patient?.id : undefined,
  );

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
      ) : !records || records.length === 0 ? (
        <p className="py-10 text-center text-sm text-muted-foreground">
          No vitals recorded for this patient yet.
        </p>
      ) : (
        <div className="flex flex-col gap-3">
          {records.map((record) => (
            <div key={record.id} className="rounded-md border border-border p-3">
              <p className="mb-2 text-xs text-muted-foreground">
                Recorded {formatDisplayDate(displayDayKey(record.created_at))} at{' '}
                {formatDisplayTime(record.created_at)}
              </p>
              <div className="flex flex-wrap gap-x-5 gap-y-2">
                {ALL_VITALS_FIELDS.filter(
                  (field) => record[field] !== null && record[field] !== undefined,
                ).map((field) => {
                  const severity = VITALS_FIELDS_WITH_SEVERITY.includes(field)
                    ? getVitalSeverity(field, record[field], {
                        ageYears: patient?.age_years,
                        temperatureUnit: record.temperature_unit,
                      })
                    : { level: null };
                  return (
                    <div key={field} className="flex items-center gap-1.5 text-sm">
                      <span className="text-muted-foreground">{VITAL_FIELD_LABELS[field]}:</span>
                      <span className="font-medium text-foreground">
                        {record[field]} {vitalFieldUnit(field, record.temperature_unit)}
                      </span>
                      {severity.level && severity.level !== 'normal' ? (
                        <Badge variant={SEVERITY_BADGE_VARIANT[severity.level]} className="text-[10px]">
                          {SEVERITY_LABEL[severity.level]}
                        </Badge>
                      ) : null}
                    </div>
                  );
                })}
              </div>
              {record.notes ? (
                <p className="mt-2 text-sm text-muted-foreground">Notes: {record.notes}</p>
              ) : null}
            </div>
          ))}
        </div>
      )}
    </DetailsDialog>
  );
}
