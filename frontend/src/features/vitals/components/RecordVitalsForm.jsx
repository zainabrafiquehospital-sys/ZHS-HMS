'use client';

import { useMemo, useState } from 'react';
import { useRouter } from 'next/navigation';
import { useForm } from 'react-hook-form';
import { zodResolver } from '@hookform/resolvers/zod';
import { ClipboardCheck, CheckCircle2, TrendingUp, TrendingDown, Minus } from 'lucide-react';
import { recordVitalsSchema } from '@/features/vitals/schemas/recordVitalsSchema';
import {
  useRecordVitals,
  usePatientsForVisits,
  useVisitsByIds,
  useLatestVitalsForPatient,
} from '@/features/vitals/hooks/useVitals';
import {
  ALL_VITALS_FIELDS,
  VITALS_FIELDS_WITH_SEVERITY,
  VITAL_FIELD_LABELS,
  VITAL_FIELD_UNITS,
  vitalFieldUnit,
  SEVERITY_BADGE_VARIANT,
  SEVERITY_LABEL,
  getVitalSeverity,
  summarizeVitalsSeverity,
  describeSeverityEntry,
  getTrend,
} from '@/features/vitals/utils/vitalsSeverity';
import { Button } from '@/shared/components/ui/Button';
import { Input } from '@/shared/components/ui/Input';
import { Label } from '@/shared/components/ui/Label';
import { Textarea } from '@/shared/components/ui/Textarea';
import { Badge } from '@/shared/components/ui/Badge';
import { Card, CardContent, CardHeader, CardTitle } from '@/shared/components/ui/Card';
import { ConfirmDialog } from '@/shared/components/ui/ConfirmDialog';
import { PageLoader } from '@/shared/components/PageLoader';
import { formatDisplayDate, formatDisplayTime, displayDayKey } from '@/utils/timezone';
import { useToast } from '@/shared/components/toast/ToastProvider';

const FIELD_STEP = {
  systolic_bp: '1',
  diastolic_bp: '1',
  pulse_rate: '1',
  temperature: '0.1',
  weight_kg: '0.1',
  height_cm: '0.1',
  spo2_percent: '1',
};

const DEFAULT_VALUES = {
  systolic_bp: '',
  diastolic_bp: '',
  pulse_rate: '',
  temperature: '',
  weight_kg: '',
  height_cm: '',
  spo2_percent: '',
  notes: '',
};

function toPayload(visitId, values) {
  return {
    visit_id: visitId,
    systolic_bp: values.systolic_bp === undefined ? null : values.systolic_bp,
    diastolic_bp: values.diastolic_bp === undefined ? null : values.diastolic_bp,
    pulse_rate: values.pulse_rate === undefined ? null : values.pulse_rate,
    // Always Fahrenheit — see recordVitalsSchema.js's own comment; the
    // backend stamps temperature_unit itself, never sent from here.
    temperature: values.temperature === undefined ? null : values.temperature,
    weight_kg: values.weight_kg === undefined ? null : values.weight_kg,
    height_cm: values.height_cm === undefined ? null : values.height_cm,
    spo2_percent: values.spo2_percent === undefined ? null : values.spo2_percent,
    notes: values.notes ? values.notes : null,
  };
}

const TREND_ICON = { up: TrendingUp, down: TrendingDown, stable: Minus };

function TrendIndicator({ trend }) {
  if (!trend) return null;
  const Icon = TREND_ICON[trend];
  const label = trend === 'up' ? 'higher than previous' : trend === 'down' ? 'lower than previous' : 'about the same as previous';
  return (
    <span className="inline-flex items-center text-muted-foreground" title={label} aria-label={label}>
      <Icon className="h-3.5 w-3.5" />
    </span>
  );
}

/** One vitals field: label, live severity badge (for the 5 fields with
 * an established reference range), trend vs. the patient's previous
 * reading (for every numeric field), and the input itself. Sized for
 * bedside/tablet use — `h-11` (44px) and `text-base` rather than the
 * shared Input's default `h-9`/`text-sm`, a large-enough tap target
 * for a nurse using a tablet standing at the patient, without changing
 * the shared Input component's default everywhere else it's used. */
function VitalField({
  field,
  register,
  errors,
  watchedValue,
  ageYears,
  previousValue,
  previousTemperatureUnit,
}) {
  const label = VITAL_FIELD_LABELS[field];
  // The live input itself is always Fahrenheit for temperature (every
  // new entry is, going forward) — VITAL_FIELD_UNITS.temperature is
  // already that default, correct here without consulting any record.
  const unit = VITAL_FIELD_UNITS[field];
  const hasSeverity = VITALS_FIELDS_WITH_SEVERITY.includes(field);
  const numericValue = watchedValue === '' || watchedValue === undefined ? null : Number(watchedValue);
  const severity = hasSeverity ? getVitalSeverity(field, numericValue, { ageYears }) : { level: null };
  // Suppresses the trend arrow outright when comparing a live
  // Fahrenheit entry against a Celsius-tagged previous record (see
  // getTrend's own docstring) — never a fabricated up/down across
  // mismatched units.
  const trend = getTrend(field, watchedValue, previousValue, { previousTemperatureUnit });
  const fieldError = errors[field];
  // The *previous* reading may be a historical Celsius-tagged record —
  // its own unit, never assumed to match the live field's.
  const previousUnit = field === 'temperature' ? vitalFieldUnit(field, previousTemperatureUnit) : unit;

  return (
    <div className="flex flex-col gap-1.5">
      <div className="flex flex-wrap items-center justify-between gap-x-2 gap-y-1">
        <Label htmlFor={field}>
          {label} <span className="text-muted-foreground">({unit})</span>
        </Label>
        <div className="flex items-center gap-1.5">
          <TrendIndicator trend={trend} />
          {severity.level ? (
            <Badge variant={SEVERITY_BADGE_VARIANT[severity.level]} className="text-[10px]">
              {SEVERITY_LABEL[severity.level]}
            </Badge>
          ) : null}
        </div>
      </div>
      <Input
        id={field}
        type="number"
        step={FIELD_STEP[field]}
        className="h-11 text-base"
        {...register(field)}
      />
      {previousValue !== null && previousValue !== undefined ? (
        <p className="text-xs text-muted-foreground">
          Previous: {previousValue} {previousUnit}
        </p>
      ) : null}
      {fieldError ? <p className="text-xs text-destructive">{fieldError.message}</p> : null}
    </div>
  );
}

/** Static reference card shown above the entry fields — the patient's
 * most recent recorded vitals from an earlier visit (never this one),
 * with the same severity badges the entry fields use, plus when it was
 * recorded. Renders an honest empty state when the patient genuinely
 * has no prior record, rather than showing blank/zero values. */
function PreviousVitalsCard({ isLoading, record, ageYears }) {
  return (
    <Card className="border-dashed">
      <CardHeader className="pb-2">
        <CardTitle className="text-xs font-medium uppercase tracking-wide text-muted-foreground">
          Previous Vitals
        </CardTitle>
      </CardHeader>
      <CardContent className="pt-0">
        {isLoading ? (
          <p className="text-sm text-muted-foreground">Loading previous vitals…</p>
        ) : !record ? (
          <p className="text-sm text-muted-foreground">No previous vitals recorded for this patient.</p>
        ) : (
          <div className="flex flex-col gap-3">
            <p className="text-xs text-muted-foreground">
              Recorded {formatDisplayDate(displayDayKey(record.created_at))} at{' '}
              {formatDisplayTime(record.created_at)}
            </p>
            <div className="flex flex-wrap gap-x-5 gap-y-2">
              {ALL_VITALS_FIELDS.filter((field) => record[field] !== null && record[field] !== undefined).map(
                (field) => {
                  // This record may predate the Fahrenheit change —
                  // always classify/label its own temperature against
                  // its own stored unit, never a global assumption.
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
                },
              )}
            </div>
          </div>
        )}
      </CardContent>
    </Card>
  );
}

export function RecordVitalsForm({ visitId }) {
  const router = useRouter();
  const { toast } = useToast();
  const [pendingPayload, setPendingPayload] = useState(null);
  const { visitsById, isLoading: isLoadingVisit } = useVisitsByIds([visitId]);
  const visit = visitsById[visitId];
  const patientsById = usePatientsForVisits(visit ? [visit] : []);
  const patient = visit ? patientsById[visit.patient_id] : undefined;
  const ageYears = patient?.age_years;

  const { data: previousVitals, isLoading: isLoadingPrevious } = useLatestVitalsForPatient(
    patient?.id,
    visitId,
  );

  const recordVitals = useRecordVitals();
  const {
    register,
    handleSubmit,
    watch,
    formState: { errors, isSubmitting },
  } = useForm({
    resolver: zodResolver(recordVitalsSchema),
    defaultValues: DEFAULT_VALUES,
  });

  const watchedValues = watch();
  const severitySummary = useMemo(
    () => summarizeVitalsSeverity(watchedValues, { ageYears }),
    [watchedValues, ageYears],
  );

  async function submitPayload(payload, { wasCritical } = {}) {
    try {
      await recordVitals.mutateAsync(payload);
      toast.success({
        title: wasCritical ? 'Critical vitals recorded and flagged' : 'Vitals recorded',
        description: wasCritical
          ? 'The doctor has been flagged for immediate attention.'
          : 'Saved and routed back to the queue.',
      });
      router.push('/vitals');
    } catch (error) {
      toast.error({
        title: 'Unable to record vitals',
        description: error.message,
        onRetry: () => submitPayload(payload, { wasCritical }),
      });
    }
  }

  async function onSubmit(values) {
    const payload = toPayload(visitId, values);
    const summary = summarizeVitalsSeverity(values, { ageYears });
    if (summary.hasCritical) {
      // Real patient-safety moment, not a cosmetic badge — block on an
      // explicit confirmation naming exactly which entered value(s)
      // are critical, built from the real values the nurse just typed.
      setPendingPayload(payload);
      return;
    }
    await submitPayload(payload);
  }

  async function handleConfirmCritical() {
    const payload = pendingPayload;
    setPendingPayload(null);
    if (payload) await submitPayload(payload, { wasCritical: true });
  }

  if (isLoadingVisit) return <PageLoader label="Loading visit" />;

  const criticalDescription = severitySummary.criticalEntries
    .map((entry) => `${describeSeverityEntry(entry)}.`)
    .join('\n');

  return (
    <>
      <Card>
        <CardHeader>
          <CardTitle>
            Record Vitals
            {patient ? ` — ${patient.full_name} (${patient.mr_number})` : ''}
          </CardTitle>
          {patient ? (
            <p className="text-sm text-muted-foreground">
              {patient.age_years} years
              {patient.gender ? ` · ${patient.gender[0].toUpperCase()}${patient.gender.slice(1)}` : ''}
            </p>
          ) : null}
        </CardHeader>
        <CardContent className="flex flex-col gap-5">
          <PreviousVitalsCard isLoading={isLoadingPrevious} record={previousVitals} ageYears={ageYears} />

          <form onSubmit={handleSubmit(onSubmit)} className="flex flex-col gap-5">
            <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-3">
              {ALL_VITALS_FIELDS.map((field) => (
                <VitalField
                  key={field}
                  field={field}
                  register={register}
                  errors={errors}
                  watchedValue={watchedValues[field]}
                  ageYears={ageYears}
                  previousValue={previousVitals ? previousVitals[field] : undefined}
                  previousTemperatureUnit={previousVitals ? previousVitals.temperature_unit : undefined}
                />
              ))}
            </div>

            <div className="flex flex-col gap-1.5">
              <Label htmlFor="notes">Notes</Label>
              <Textarea id="notes" rows={3} className="text-base" {...register('notes')} />
              {errors.notes ? <p className="text-xs text-destructive">{errors.notes.message}</p> : null}
            </div>

            {severitySummary.allNormal ? (
              <p className="flex items-center gap-2 rounded-md bg-emerald-600/10 px-3 py-2 text-sm text-emerald-700">
                <CheckCircle2 className="h-4 w-4 shrink-0" />
                All entered values are within normal range.
              </p>
            ) : null}

            <Button
              type="submit"
              disabled={isSubmitting}
              size="lg"
              className="h-12 w-full text-base sm:w-auto"
              variant={severitySummary.hasCritical ? 'destructive' : 'default'}
            >
              <ClipboardCheck className="h-4 w-4" />
              {isSubmitting
                ? 'Saving…'
                : severitySummary.allNormal
                  ? 'Confirm Normal & Save Vitals'
                  : 'Save Vitals & Return to Queue'}
            </Button>
          </form>
        </CardContent>
      </Card>

      <ConfirmDialog
        open={pendingPayload !== null}
        variant="destructive"
        title="Critical vitals entered"
        description={`${criticalDescription}\n\nConfirm these values are correct and flag this patient for immediate doctor attention?`}
        confirmLabel="Confirm & Flag for Doctor"
        cancelLabel="Go Back and Review"
        onConfirm={handleConfirmCritical}
        onCancel={() => setPendingPayload(null)}
      />
    </>
  );
}
