'use client';

import { useState } from 'react';
import { useForm } from 'react-hook-form';
import { zodResolver } from '@hookform/resolvers/zod';
import { useRouter } from 'next/navigation';
import { HeartPulse, CheckCircle2, ReceiptText, History, Printer, Pencil } from 'lucide-react';
import {
  useActiveConsultation,
  useConsultationById,
  useSendToVitals,
  useCompleteConsultation,
  usePrintPrescriptionSlip,
  usePatientsForVisits,
} from '@/features/consultation/hooks/useConsultation';
import { useVisitsByIds, useVitalsForVisit } from '@/features/vitals/hooks/useVitals';
import { VitalsHistoryDialog } from '@/features/vitals/components/VitalsHistoryDialog';
import { VitalsRecordList } from '@/features/vitals/components/VitalsRecordList';
import {
  ConsultationClinicalDetails,
  SLIP_FIELDS,
} from '@/features/consultation/components/ConsultationClinicalDetails';
import { ConsultationCorrectionForm } from '@/features/consultation/components/ConsultationCorrectionForm';
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

/** Read-only display of everything recorded for this visit — the same
 * severity badges the nurse saw while recording, via the shared
 * `VitalsRecordList` (extracted 2026-09-03; ConsultationPanel, the
 * cross-visit history dialog, and the Doctor dashboard's detail dialog
 * all render it now). Shows every recorded reading, not just the latest
 * — a doctor-requested detour can add a second, later reading to the
 * same visit and both are clinically relevant. */
function RecordedVitals({ visitId, ageYears }) {
  const { data: records, isLoading } = useVitalsForVisit(visitId);

  if (isLoading) return <p className="text-sm text-muted-foreground">Loading vitals…</p>;

  return (
    <VitalsRecordList
      records={records}
      ageYears={ageYears}
      emptyLabel="No vitals recorded for this visit yet."
    />
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
        Sends a request to Reception to add a charge to this visit&apos;s bill — Reception reviews
        and approves it before it&apos;s billed.
      </p>
      <form
        onSubmit={handleSubmit(onSubmit)}
        className="flex flex-col gap-2 sm:flex-row sm:items-start"
      >
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
          {errors.amount ? (
            <p className="text-xs text-destructive">{errors.amount.message}</p>
          ) : null}
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

// SLIP_FIELDS (the five printed clinical fields, in slip order) is
// imported from ConsultationClinicalDetails — shared with the
// post-completion ConsultationCorrectionForm. `notes` is the sixth,
// general, NOT-printed field, rendered here as its own textarea below.

const EMPTY_CONSULTATION_FORM = {
  history_of: '',
  complaint_of: '',
  advised: '',
  diagnosis: '',
  prescription: '',
  notes: '',
};

/** Shown in place of the editable form once the consultation is
 * completed (2026-09-03) — the panel no longer navigates straight back
 * to the queue on Complete, so the doctor can print the prescription
 * slip (which reads the just-persisted consultation) and, if they spot
 * a mistake, correct it (2026-09-04) before leaving. */
function CompletedConsultationView({
  consultation,
  visitId,
  ageYears,
  onPrint,
  isPrinting,
  onEdit,
  onBack,
}) {
  return (
    <Card>
      <CardHeader className="flex-row items-center justify-between">
        <CardTitle>Consultation</CardTitle>
        <Badge variant="success" className="capitalize">
          completed
        </Badge>
      </CardHeader>
      <CardContent className="flex flex-col gap-5">
        <div className="flex items-center gap-2 rounded-md bg-emerald-600/10 px-3 py-2 text-sm text-emerald-700">
          <CheckCircle2 className="h-4 w-4 shrink-0" />
          Consultation completed. Print the prescription slip below, or correct a mistake, then
          return to your queue.
        </div>

        <div className="flex flex-col gap-2">
          <span className="text-xs font-medium uppercase tracking-wide text-muted-foreground">
            Vitals
          </span>
          <RecordedVitals visitId={visitId} ageYears={ageYears} />
        </div>

        <ConsultationClinicalDetails consultation={consultation} />

        <div className="flex flex-col gap-2 border-t border-border pt-4 sm:flex-row">
          <Button type="button" onClick={onPrint} disabled={isPrinting}>
            <Printer className="h-4 w-4" />
            {isPrinting ? 'Preparing…' : 'Print Prescription'}
          </Button>
          <Button type="button" variant="outline" onClick={onEdit}>
            <Pencil className="h-4 w-4" />
            Edit / Correct
          </Button>
          <Button type="button" variant="ghost" onClick={onBack}>
            Back to Queue
          </Button>
        </div>
      </CardContent>
    </Card>
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
  const printPrescription = usePrintPrescriptionSlip();
  const [actionError, setActionError] = useState(null);
  const [showHistory, setShowHistory] = useState(false);
  // The freshly-completed ConsultationOut (from the complete mutation's
  // own response) — set once Complete succeeds so the panel can show
  // the print-and-leave view without another fetch or a redirect.
  const [completedConsultation, setCompletedConsultation] = useState(null);
  const [isCorrecting, setIsCorrecting] = useState(false);

  const { register, getValues } = useForm({ defaultValues: EMPTY_CONSULTATION_FORM });

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
      const response = await completeConsultation.mutateAsync({
        consultationId,
        updates: getValues(),
      });
      setCompletedConsultation(response.data);
    } catch (error) {
      setActionError(error.message);
    }
  }

  async function handlePrintPrescription() {
    setActionError(null);
    try {
      await printPrescription.mutateAsync(completedConsultation.id);
    } catch (error) {
      setActionError(error.message || 'Unable to open the prescription slip.');
    }
  }

  if (completedConsultation) {
    return (
      <>
        {isCorrecting ? (
          <Card>
            <CardHeader className="flex-row items-center justify-between">
              <CardTitle>Correct Consultation</CardTitle>
              <Badge variant="success" className="capitalize">
                completed
              </Badge>
            </CardHeader>
            <CardContent>
              <ConsultationCorrectionForm
                consultation={completedConsultation}
                onSaved={(updated) => {
                  setCompletedConsultation(updated);
                  setIsCorrecting(false);
                }}
                onCancel={() => setIsCorrecting(false)}
              />
            </CardContent>
          </Card>
        ) : (
          <CompletedConsultationView
            consultation={completedConsultation}
            visitId={visitId}
            ageYears={patient?.age_years}
            onPrint={handlePrintPrescription}
            isPrinting={printPrescription.isPending}
            onEdit={() => setIsCorrecting(true)}
            onBack={() => router.push('/doctor')}
          />
        )}
        {actionError ? (
          <p className="mt-3 rounded-md bg-destructive/10 px-3 py-2 text-sm text-destructive">
            {actionError}
          </p>
        ) : null}
      </>
    );
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
        <Badge
          variant={status === 'awaiting_vitals' ? 'warning' : 'secondary'}
          className="capitalize"
        >
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
          <div className="flex items-center justify-between gap-2">
            <Label className="text-xs font-medium uppercase tracking-wide text-muted-foreground">
              Vitals
            </Label>
            <Button
              type="button"
              size="sm"
              variant="outline"
              onClick={() => setShowHistory(true)}
              disabled={!patient}
            >
              <History className="h-3.5 w-3.5" />
              Show Details
            </Button>
          </div>
          <RecordedVitals visitId={visitId} ageYears={patient?.age_years} />
        </div>
        <VitalsHistoryDialog
          patient={patient}
          open={showHistory}
          onClose={() => setShowHistory(false)}
        />

        {SLIP_FIELDS.map((field) => (
          <div key={field.name} className="flex flex-col gap-1.5">
            <Label htmlFor={field.name}>{field.label}</Label>
            <Textarea
              id={field.name}
              rows={field.rows}
              placeholder={field.placeholder}
              {...register(field.name)}
              disabled={status !== 'in_progress'}
            />
          </div>
        ))}
        <div className="flex flex-col gap-1.5">
          <Label htmlFor="notes">Clinical Notes</Label>
          <Textarea
            id="notes"
            rows={3}
            {...register('notes')}
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
