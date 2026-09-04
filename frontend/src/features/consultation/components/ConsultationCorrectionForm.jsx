'use client';

import { useState } from 'react';
import { useForm } from 'react-hook-form';
import { Save, X } from 'lucide-react';
import { useCorrectConsultation } from '@/features/consultation/hooks/useConsultation';
import { SLIP_FIELDS } from '@/features/consultation/components/ConsultationClinicalDetails';
import { Button } from '@/shared/components/ui/Button';
import { Label } from '@/shared/components/ui/Label';
import { Textarea } from '@/shared/components/ui/Textarea';

// The same field list ConsultationPanel's in-progress form uses (the
// five slip fields) plus the general, non-printed `notes` field.
const EDIT_FIELDS = [...SLIP_FIELDS, { name: 'notes', label: 'Clinical Notes', rows: 3 }];

/** Post-completion clinical-content correction form (2026-09-04) — a
 * doctor fixing a data-entry mistake in their own already-completed
 * consultation. Prefilled from the consultation, saved via
 * `PATCH /consultations/{id}` (`useCorrectConsultation`). Reachable from
 * two places, both rendering this same component: the post-Complete
 * panel view (ConsultationPanel) and the "My Consultations" record
 * dialog (ConsultationRecordDialog). Ownership + "only when completed"
 * are enforced server-side, so this form does no gating of its own —
 * `onSaved` receives the updated ConsultationOut. */
export function ConsultationCorrectionForm({ consultation, onSaved, onCancel }) {
  const correct = useCorrectConsultation();
  const [error, setError] = useState(null);

  const {
    register,
    handleSubmit,
    formState: { isSubmitting },
  } = useForm({
    defaultValues: Object.fromEntries(
      EDIT_FIELDS.map((field) => [field.name, consultation?.[field.name] ?? '']),
    ),
  });

  async function onSubmit(values) {
    setError(null);
    try {
      const response = await correct.mutateAsync({
        consultationId: consultation.id,
        updates: values,
      });
      onSaved(response.data);
    } catch (err) {
      setError(err.message || 'Unable to save this correction.');
    }
  }

  return (
    <form onSubmit={handleSubmit(onSubmit)} className="flex flex-col gap-4">
      <p className="text-xs text-muted-foreground">
        Correcting a completed consultation. Every change is recorded in the audit trail.
      </p>
      {EDIT_FIELDS.map((field) => (
        <div key={field.name} className="flex flex-col gap-1.5">
          <Label htmlFor={`correct-${field.name}`}>{field.label}</Label>
          <Textarea
            id={`correct-${field.name}`}
            rows={field.rows}
            placeholder={field.placeholder}
            {...register(field.name)}
          />
        </div>
      ))}
      {error ? (
        <p className="rounded-md bg-destructive/10 px-3 py-2 text-sm text-destructive">{error}</p>
      ) : null}
      <div className="flex gap-2 border-t border-border pt-4">
        <Button type="submit" disabled={isSubmitting}>
          <Save className="h-4 w-4" />
          {isSubmitting ? 'Saving…' : 'Save Correction'}
        </Button>
        <Button type="button" variant="outline" onClick={onCancel} disabled={isSubmitting}>
          <X className="h-4 w-4" />
          Cancel
        </Button>
      </div>
    </form>
  );
}
