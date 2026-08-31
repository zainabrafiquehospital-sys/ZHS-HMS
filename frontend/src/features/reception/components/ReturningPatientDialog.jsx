'use client';

import { Card, CardContent, CardHeader, CardTitle } from '@/shared/components/ui/Card';
import { Button } from '@/shared/components/ui/Button';

/** Fired when RegisterVisitForm.jsx's phone number field (New Patient
 * mode only) blurs on a number that exactly matches one or more
 * already-registered patients — same fixed-overlay Card shape as
 * ConfirmDialog/PatientVisitHistoryDialog, sized as a short list
 * rather than ConfirmDialog's own fixed two-button shape, since more
 * than one candidate is a real, expected case here (family members
 * sharing a household number), not an edge case to squeeze into a
 * single-item prompt.
 *
 * Every candidate gets its own "Use This Patient" action (there is no
 * single implicit "confirm" — the receptionist must pick exactly which
 * match, even when there's only one, the same explicit-choice
 * requirement a multi-match list would need anyway); "This Is Someone
 * Else" is the one dismiss action, shown once at the bottom regardless
 * of how many candidates are listed. */
export function ReturningPatientDialog({ matches, onUseExisting, onDismiss }) {
  if (!matches || matches.length === 0) return null;

  const isSingle = matches.length === 1;

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/50 p-4"
      role="dialog"
      aria-modal="true"
      aria-labelledby="returning-patient-dialog-title"
    >
      <Card className="w-full max-w-md">
        <CardHeader>
          <CardTitle id="returning-patient-dialog-title">
            {isSingle ? 'Existing patient found' : `${matches.length} existing patients found`}
          </CardTitle>
        </CardHeader>
        <CardContent className="flex flex-col gap-4">
          <p className="text-sm text-muted-foreground">
            {isSingle
              ? 'This phone number already belongs to a registered patient. Use their details instead of creating a new record?'
              : 'This phone number already belongs to more than one registered patient (e.g. family members sharing a number). Pick one to reuse, or continue as a different person.'}
          </p>
          <div className="flex flex-col gap-2">
            {matches.map((patient) => (
              <div
                key={patient.id}
                className="flex items-center justify-between gap-3 rounded-md border border-border p-3"
              >
                <div className="flex flex-col">
                  <span className="text-sm font-medium text-foreground">{patient.full_name}</span>
                  <span className="text-xs text-muted-foreground">
                    {patient.mr_number}
                    {patient.age_years !== null && patient.age_years !== undefined
                      ? ` · ${patient.age_years} yrs`
                      : ''}
                  </span>
                </div>
                <Button size="sm" onClick={() => onUseExisting(patient)}>
                  Use This Patient
                </Button>
              </div>
            ))}
          </div>
          <div className="flex justify-end">
            <Button variant="outline" size="lg" onClick={onDismiss}>
              This Is Someone Else
            </Button>
          </div>
        </CardContent>
      </Card>
    </div>
  );
}
