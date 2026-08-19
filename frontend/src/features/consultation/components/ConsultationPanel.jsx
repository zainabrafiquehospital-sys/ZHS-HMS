'use client';

import { useState } from 'react';
import { useForm } from 'react-hook-form';
import { zodResolver } from '@hookform/resolvers/zod';
import { useRouter } from 'next/navigation';
import { HeartPulse, CheckCircle2, ReceiptText } from 'lucide-react';
import {
  useActiveConsultation,
  useConsultationById,
  useSendToVitals,
  useCompleteConsultation,
  usePatientsForVisits,
} from '@/features/consultation/hooks/useConsultation';
import { useVisitsByIds, useVitalsForVisit } from '@/features/vitals/hooks/useVitals';
import {
  ALL_VITALS_FIELDS,
  VITAL_FIELD_LABELS,
  VITAL_FIELD_UNITS,
  VITALS_FIELDS_WITH_SEVERITY,
  SEVERITY_BADGE_VARIANT,
  SEVERITY_LABEL,
  getVitalSeverity,
} from '@/features/vitals/utils/vitalsSeverity';
import { useSubmitPendingItem } from '@/features/billing/hooks/useBilling';
import { submitPendingItemSchema } from '@/features/billing/schemas/billingSchemas';
import { useAuth } from '@/features/auth/hooks/useAuth';
import { Card, CardContent, CardHeader, CardTitle } from '@/shared/components/ui/Card';
import { Button } from '@/shared/components/ui/Button';
import { Input } from '@/shared/components/ui/Input';
import { Label } from '@/shared/components/ui/Label';
import { Textarea } from '@/shared/components/ui/Textarea';
import { Badge } from '@/shared/components/ui/Badge';
import { PageLoader } from '@/shared/components/PageLoader';
import { formatDisplayDate, formatDisplayTime, displayDayKey } from '@/utils/timezone';

/** Read-only display of everything recorded for this visit — the same
 * severity badges the nurse saw while recording (see
 * RecordVitalsForm.jsx's `VitalField`), so the doctor gets the exact
 * same signal, not a re-derived or simplified one. Shows every
 * recorded reading (not just the latest) since a doctor-requested
 * detour (see VitalsService.record_vitals' docstring on the
 * "doctor-requested detour" scope) can add a second, later reading to
 * the same visit — both are clinically relevant, not just the last. */
function RecordedVitals({ visitId, ageYears }) {
  const { data: records, isLoading } = useVitalsForVisit(visitId);

  if (isLoading) return <p className="text-sm text-muted-foreground">Loading vitals…</p>;
  if (!records || records.length === 0) {
    return <p className="text-sm text-muted-foreground">No vitals recorded for this visit yet.</p>;
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
                ? getVitalSeverity(field, record[field], { ageYears })
                : { level: null };
              return (
                <div key={field} className="flex items-center gap-1.5 text-sm">
                  <span className="text-muted-foreground">{VITAL_FIELD_LABELS[field]}:</span>
                  <span className="font-medium text-foreground">
                    {record[field]} {VITAL_FIELD_UNITS[field]}
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

/** Doctor's "submit an additional charge request" (Phase 6 §7.1) —
 * added in the 2026-08-19 audit fix pass. The backend endpoint
 * (`billing:submit_charge`) and Reception's own approve/reject screen
 * (`BillingWorkspace.jsx`'s `PendingItemsPanel`) already existed; this
 * was the missing piece — nothing in the doctor-facing UI could ever
 * call it. A clinical fact, never a financial transaction on its own
 * (see backend/app/modules/billing/models.py's `PendingBillingItem`
 * docstring) — Reception still reviews, approves/rejects, and is the
 * only one who ever touches an actual Invoice; this form only creates
 * the request. Submittable multiple times per consultation (e.g. a
 * doctor requesting two separate additional procedures), so — unlike
 * Send-to-Vitals, which navigates the whole panel into a waiting state
 * — this resets and stays in place after each successful submission. */
function SubmitChargeRequestForm({ visitId, disabled }) {
  const submitPendingItem = useSubmitPendingItem(visitId);
  const [submitError, setSubmitError] = useState(null);
  const [justSubmitted, setJustSubmitted] = useState(false);

  const {
    register,
    handleSubmit,
    reset,
    formState: { errors, isSubmitting },
  } = useForm({
    resolver: zodResolver(submitPendingItemSchema),
    defaultValues: { description: '', amount: '' },
  });

  async function onSubmit(values) {
    setSubmitError(null);
    setJustSubmitted(false);
    try {
      await submitPendingItem.mutateAsync(values);
      reset();
      setJustSubmitted(true);
    } catch (error) {
      setSubmitError(error.message || 'Unable to submit this charge request.');
    }
  }

  return (
    <div className="flex flex-col gap-2 border-t border-border pt-4">
      <Label className="text-xs font-medium uppercase tracking-wide text-muted-foreground">
        Request Additional Charge
      </Label>
      <p className="text-xs text-muted-foreground">
        Sends a request to Reception to add a charge to this visit&apos;s bill — Reception
        reviews and approves it before it&apos;s billed.
      </p>
      <form onSubmit={handleSubmit(onSubmit)} className="flex flex-col gap-2 sm:flex-row sm:items-start">
        <div className="flex flex-1 flex-col gap-1.5">
          <Input
            aria-label="Charge description"
            placeholder="e.g. Ultrasound"
            disabled={disabled}
            {...register('description')}
          />
          {errors.description ? (
            <p className="text-xs text-destructive">{errors.description.message}</p>
          ) : null}
        </div>
        <div className="flex w-full flex-col gap-1.5 sm:w-32">
          <Input
            aria-label="Charge amount"
            type="number"
            step="0.01"
            placeholder="Amount"
            disabled={disabled}
            {...register('amount')}
          />
          {errors.amount ? <p className="text-xs text-destructive">{errors.amount.message}</p> : null}
        </div>
        <Button type="submit" variant="outline" disabled={disabled || isSubmitting}>
          <ReceiptText className="h-4 w-4" />
          {isSubmitting ? 'Submitting…' : 'Submit Request'}
        </Button>
      </form>
      {justSubmitted ? (
        <p className="text-xs text-emerald-700">Charge request sent to Reception.</p>
      ) : null}
      {submitError ? <p className="text-xs text-destructive">{submitError}</p> : null}
    </div>
  );
}

export function ConsultationPanel({ visitId }) {
  const router = useRouter();
  const { hasPermission } = useAuth();
  const canSubmitCharge = hasPermission('billing:submit_charge');
  const { data: activeSummary, isLoading: isLoadingActive } = useActiveConsultation(visitId);
  const consultationId = activeSummary?.id;
  const { data: consultation } = useConsultationById(consultationId);
  const { visitsById } = useVisitsByIds([visitId]);
  const visit = visitsById[visitId];
  const patientsById = usePatientsForVisits(visit ? [visit] : []);
  const patient = visit ? patientsById[visit.patient_id] : undefined;

  const [vitalsReason, setVitalsReason] = useState('');
  const sendToVitals = useSendToVitals();
  const completeConsultation = useCompleteConsultation();
  const [actionError, setActionError] = useState(null);

  const { register, getValues } = useForm({
    defaultValues: { notes: '', diagnosis: '', prescription: '' },
  });

  const status = consultation?.status ?? activeSummary?.status;

  async function handleSendToVitals() {
    setActionError(null);
    try {
      await sendToVitals.mutateAsync({ consultationId, reason: vitalsReason });
      setVitalsReason('');
    } catch (error) {
      setActionError(error.message);
    }
  }

  async function handleComplete() {
    setActionError(null);
    try {
      await completeConsultation.mutateAsync({ consultationId, updates: getValues() });
      router.push('/doctor');
    } catch (error) {
      setActionError(error.message);
    }
  }

  if (isLoadingActive) return <PageLoader label="Loading consultation" />;

  if (!activeSummary) {
    return (
      <Card>
        <CardContent className="py-10 text-center text-sm text-muted-foreground">
          No active consultation for this visit. It may have already been completed.
        </CardContent>
      </Card>
    );
  }

  return (
    <Card>
      <CardHeader className="flex-row items-center justify-between">
        <CardTitle>Consultation</CardTitle>
        <Badge variant={status === 'awaiting_vitals' ? 'warning' : 'secondary'} className="capitalize">
          {status?.replaceAll('_', ' ')}
        </Badge>
      </CardHeader>
      <CardContent className="flex flex-col gap-5">
        {status === 'awaiting_vitals' ? (
          <div className="flex items-center gap-2 rounded-md bg-amber-500/10 px-3 py-2 text-sm text-amber-700">
            <HeartPulse className="h-4 w-4" />
            Waiting for vitals to be recorded — this will resume automatically once vitals staff
            complete the request.
          </div>
        ) : null}

        <div className="flex flex-col gap-2">
          <Label className="text-xs font-medium uppercase tracking-wide text-muted-foreground">
            Vitals
          </Label>
          <RecordedVitals visitId={visitId} ageYears={patient?.age_years} />
        </div>

        <div className="flex flex-col gap-1.5">
          <Label htmlFor="notes">Clinical Notes</Label>
          <Textarea id="notes" rows={4} {...register('notes')} disabled={status !== 'in_progress'} />
        </div>
        <div className="flex flex-col gap-1.5">
          <Label htmlFor="diagnosis">Diagnosis</Label>
          <Textarea
            id="diagnosis"
            rows={2}
            {...register('diagnosis')}
            disabled={status !== 'in_progress'}
          />
        </div>
        <div className="flex flex-col gap-1.5">
          <Label htmlFor="prescription">Prescription</Label>
          <Textarea
            id="prescription"
            rows={3}
            {...register('prescription')}
            disabled={status !== 'in_progress'}
          />
        </div>

        <div className="flex flex-col gap-2 border-t border-border pt-4 sm:flex-row sm:items-end">
          <div className="flex flex-1 flex-col gap-1.5">
            <Label htmlFor="vitalsReason">Send to Vitals (reason)</Label>
            <Input
              id="vitalsReason"
              placeholder="e.g. Recheck BP"
              value={vitalsReason}
              onChange={(event) => setVitalsReason(event.target.value)}
              disabled={status !== 'in_progress'}
            />
          </div>
          <Button
            type="button"
            variant="outline"
            onClick={handleSendToVitals}
            disabled={status !== 'in_progress' || sendToVitals.isPending}
          >
            <HeartPulse className="h-4 w-4" />
            Send to Vitals
          </Button>
        </div>

        {canSubmitCharge ? (
          <SubmitChargeRequestForm visitId={visitId} disabled={status !== 'in_progress'} />
        ) : null}

        {actionError ? (
          <p className="rounded-md bg-destructive/10 px-3 py-2 text-sm text-destructive">
            {actionError}
          </p>
        ) : null}

        <Button
          type="button"
          onClick={handleComplete}
          disabled={status !== 'in_progress' || completeConsultation.isPending}
        >
          <CheckCircle2 className="h-4 w-4" />
          Complete Consultation
        </Button>
      </CardContent>
    </Card>
  );
}
