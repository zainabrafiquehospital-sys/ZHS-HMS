'use client';

import { useState } from 'react';
import { useForm } from 'react-hook-form';
import { useRouter } from 'next/navigation';
import { HeartPulse, CheckCircle2 } from 'lucide-react';
import {
  useActiveConsultation,
  useConsultationById,
  useSendToVitals,
  useCompleteConsultation,
} from '@/features/consultation/hooks/useConsultation';
import { Card, CardContent, CardHeader, CardTitle } from '@/shared/components/ui/Card';
import { Button } from '@/shared/components/ui/Button';
import { Input } from '@/shared/components/ui/Input';
import { Label } from '@/shared/components/ui/Label';
import { Textarea } from '@/shared/components/ui/Textarea';
import { Badge } from '@/shared/components/ui/Badge';
import { PageLoader } from '@/shared/components/PageLoader';

export function ConsultationPanel({ visitId }) {
  const router = useRouter();
  const { data: activeSummary, isLoading: isLoadingActive } = useActiveConsultation(visitId);
  const consultationId = activeSummary?.id;
  const { data: consultation } = useConsultationById(consultationId);

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
