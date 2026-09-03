'use client';

import {
  ALL_VITALS_FIELDS,
  VITAL_FIELD_LABELS,
  vitalFieldUnit,
  VITALS_FIELDS_WITH_SEVERITY,
  SEVERITY_BADGE_VARIANT,
  SEVERITY_LABEL,
  getVitalSeverity,
} from '@/features/vitals/utils/vitalsSeverity';
import { Badge } from '@/shared/components/ui/Badge';
import { formatDisplayDate, formatDisplayTime, displayDayKey } from '@/utils/timezone';

/** Read-only render of one-or-more recorded vitals readings for a visit
 * — the single source of truth for this block, shared by
 * ConsultationPanel's `RecordedVitals`, the Vitals cross-visit history
 * dialog (`VitalsHistoryDialog`), and the Doctor dashboard's per-visit
 * detail dialog (`VisitVitalsDetailsDialog`). Extracted 2026-09-03 —
 * these three had drifted into three byte-identical copies of the same
 * markup.
 *
 * Every reading is classified/labelled against its OWN stored
 * `temperature_unit` (never a global assumption) so a Celsius-tagged
 * historical record and a Fahrenheit-tagged new one in the same list
 * are each shown correctly (see vitalsSeverity.js's own docstring). */
export function VitalsRecordList({ records, ageYears, emptyLabel = 'No vitals recorded yet.' }) {
  if (!records || records.length === 0) {
    return <p className="text-sm text-muted-foreground">{emptyLabel}</p>;
  }

  return (
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
                    ageYears,
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
  );
}
