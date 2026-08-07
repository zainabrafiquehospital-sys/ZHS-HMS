'use client';

import { useState } from 'react';
import { useRouter } from 'next/navigation';
import { useForm } from 'react-hook-form';
import { zodResolver } from '@hookform/resolvers/zod';
import { ClipboardCheck } from 'lucide-react';
import { recordVitalsSchema } from '@/features/vitals/schemas/recordVitalsSchema';
import { useRecordVitals, usePatientsForVisits, useVisitsByIds } from '@/features/vitals/hooks/useVitals';
import { Button } from '@/shared/components/ui/Button';
import { Input } from '@/shared/components/ui/Input';
import { Label } from '@/shared/components/ui/Label';
import { Textarea } from '@/shared/components/ui/Textarea';
import { Card, CardContent, CardHeader, CardTitle } from '@/shared/components/ui/Card';
import { PageLoader } from '@/shared/components/PageLoader';

const DEFAULT_VALUES = {
  systolic_bp: '',
  diastolic_bp: '',
  pulse_rate: '',
  temperature_celsius: '',
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
    temperature_celsius:
      values.temperature_celsius === undefined ? null : values.temperature_celsius,
    weight_kg: values.weight_kg === undefined ? null : values.weight_kg,
    height_cm: values.height_cm === undefined ? null : values.height_cm,
    spo2_percent: values.spo2_percent === undefined ? null : values.spo2_percent,
    notes: values.notes ? values.notes : null,
  };
}

export function RecordVitalsForm({ visitId }) {
  const router = useRouter();
  const [submitError, setSubmitError] = useState(null);
  const { visitsById, isLoading: isLoadingVisit } = useVisitsByIds([visitId]);
  const visit = visitsById[visitId];
  const patientsById = usePatientsForVisits(visit ? [visit] : []);
  const patient = visit ? patientsById[visit.patient_id] : undefined;

  const recordVitals = useRecordVitals();
  const {
    register,
    handleSubmit,
    formState: { errors, isSubmitting },
  } = useForm({
    resolver: zodResolver(recordVitalsSchema),
    defaultValues: DEFAULT_VALUES,
  });

  async function onSubmit(values) {
    setSubmitError(null);
    try {
      await recordVitals.mutateAsync(toPayload(visitId, values));
      router.push('/vitals');
    } catch (error) {
      setSubmitError(error.message || 'Unable to record vitals.');
    }
  }

  if (isLoadingVisit) return <PageLoader label="Loading visit" />;

  return (
    <Card>
      <CardHeader>
        <CardTitle>
          Record Vitals
          {patient ? ` — ${patient.full_name} (${patient.mr_number})` : ''}
        </CardTitle>
      </CardHeader>
      <CardContent>
        <form onSubmit={handleSubmit(onSubmit)} className="flex flex-col gap-5">
          <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-3">
            <div className="flex flex-col gap-1.5">
              <Label htmlFor="systolic_bp">Systolic BP (mmHg)</Label>
              <Input id="systolic_bp" type="number" {...register('systolic_bp')} />
              {errors.systolic_bp ? (
                <p className="text-xs text-destructive">{errors.systolic_bp.message}</p>
              ) : null}
            </div>
            <div className="flex flex-col gap-1.5">
              <Label htmlFor="diastolic_bp">Diastolic BP (mmHg)</Label>
              <Input id="diastolic_bp" type="number" {...register('diastolic_bp')} />
              {errors.diastolic_bp ? (
                <p className="text-xs text-destructive">{errors.diastolic_bp.message}</p>
              ) : null}
            </div>
            <div className="flex flex-col gap-1.5">
              <Label htmlFor="pulse_rate">Pulse Rate (bpm)</Label>
              <Input id="pulse_rate" type="number" {...register('pulse_rate')} />
              {errors.pulse_rate ? (
                <p className="text-xs text-destructive">{errors.pulse_rate.message}</p>
              ) : null}
            </div>
            <div className="flex flex-col gap-1.5">
              <Label htmlFor="temperature_celsius">Temperature (°C)</Label>
              <Input
                id="temperature_celsius"
                type="number"
                step="0.1"
                {...register('temperature_celsius')}
              />
              {errors.temperature_celsius ? (
                <p className="text-xs text-destructive">{errors.temperature_celsius.message}</p>
              ) : null}
            </div>
            <div className="flex flex-col gap-1.5">
              <Label htmlFor="weight_kg">Weight (kg)</Label>
              <Input id="weight_kg" type="number" step="0.1" {...register('weight_kg')} />
              {errors.weight_kg ? (
                <p className="text-xs text-destructive">{errors.weight_kg.message}</p>
              ) : null}
            </div>
            <div className="flex flex-col gap-1.5">
              <Label htmlFor="height_cm">Height (cm)</Label>
              <Input id="height_cm" type="number" step="0.1" {...register('height_cm')} />
              {errors.height_cm ? (
                <p className="text-xs text-destructive">{errors.height_cm.message}</p>
              ) : null}
            </div>
            <div className="flex flex-col gap-1.5">
              <Label htmlFor="spo2_percent">SpO2 (%)</Label>
              <Input id="spo2_percent" type="number" {...register('spo2_percent')} />
              {errors.spo2_percent ? (
                <p className="text-xs text-destructive">{errors.spo2_percent.message}</p>
              ) : null}
            </div>
          </div>

          <div className="flex flex-col gap-1.5">
            <Label htmlFor="notes">Notes</Label>
            <Textarea id="notes" rows={3} {...register('notes')} />
            {errors.notes ? <p className="text-xs text-destructive">{errors.notes.message}</p> : null}
          </div>

          {submitError ? (
            <p className="rounded-md bg-destructive/10 px-3 py-2 text-sm text-destructive">
              {submitError}
            </p>
          ) : null}

          <Button type="submit" disabled={isSubmitting} className="w-full sm:w-auto">
            <ClipboardCheck className="h-4 w-4" />
            {isSubmitting ? 'Saving…' : 'Save Vitals & Return to Queue'}
          </Button>
        </form>
      </CardContent>
    </Card>
  );
}
