'use client';

// The six clinical free-text fields of a consultation, in prescription-
// slip order (History, Complaint, Advised, Diagnosis, Prescription),
// with the general Notes field trailing since it is not on the slip.
export const CONSULTATION_CLINICAL_FIELDS = [
  { name: 'history_of', label: 'History (H/O)' },
  { name: 'complaint_of', label: 'Complaint (C/O)' },
  { name: 'advised', label: 'Advised (Adv)' },
  { name: 'diagnosis', label: 'Diagnosis (Dx)' },
  { name: 'prescription', label: 'Prescription (Rx)' },
  { name: 'notes', label: 'Clinical Notes' },
];

// The five prescription-slip clinical fields as editable textareas, in
// slip order — shared single source of truth for ConsultationPanel's
// in-progress form and the post-completion ConsultationCorrectionForm.
// Lives here (not in ConsultationPanel) so the correction form can
// import it without a circular dependency. `notes` (the sixth, general,
// non-printed field) is rendered by each consumer as its own textarea,
// not part of this list.
export const SLIP_FIELDS = [
  { name: 'history_of', label: 'History (H/O)', rows: 3 },
  { name: 'complaint_of', label: 'Complaint (C/O)', rows: 3 },
  { name: 'advised', label: 'Advised (Adv)', rows: 3 },
  { name: 'diagnosis', label: 'Diagnosis (Dx)', rows: 2 },
  {
    name: 'prescription',
    label: 'Prescription (Rx)',
    rows: 4,
    placeholder: 'One medicine per line',
  },
];

/** Read-only, full (never truncated) render of a consultation's
 * clinical free-text fields — shared by ConsultationPanel's
 * post-Complete view and "My Consultations"' record dialog (2026-09-03
 * extraction, same single-source-of-truth reasoning as VitalsRecordList).
 * Only non-empty fields are shown; an all-empty consultation gets an
 * honest placeholder. */
export function ConsultationClinicalDetails({ consultation }) {
  const filled = CONSULTATION_CLINICAL_FIELDS.filter(
    (field) => consultation?.[field.name] && consultation[field.name].trim() !== '',
  );

  if (filled.length === 0) {
    return (
      <p className="text-sm text-muted-foreground">
        No history, complaint, advice, diagnosis, prescription, or notes were recorded for this
        consultation.
      </p>
    );
  }

  return (
    <div className="flex flex-col gap-3">
      {filled.map((field) => (
        <div key={field.name} className="flex flex-col gap-1">
          <span className="text-xs font-medium uppercase tracking-wide text-muted-foreground">
            {field.label}
          </span>
          <p className="whitespace-pre-wrap text-sm text-foreground">{consultation[field.name]}</p>
        </div>
      ))}
    </div>
  );
}
