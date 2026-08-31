'use client';

import { X } from 'lucide-react';
import { Button } from '@/shared/components/ui/Button';
import { cn } from '@/utils/cn';

/** A lightweight, non-blocking suggestion list under RegisterVisitForm.jsx's
 * own Patient Name field (New Patient mode) — same dropdown shape/styling
 * SearchSelect.jsx's own results list already uses (`absolute z-10 mt-1
 * w-full rounded-md border border-border bg-card shadow-md`), just fed by
 * that field's own live value instead of an independent input, since the
 * whole point here is suggesting alongside typing a name, not replacing it
 * with a second search box.
 *
 * Deliberately not a dialog: this is a softer, earlier signal than
 * ReturningPatientDialog's own exact-phone-match prompt (which still fires
 * completely independently, later, once/if a phone number is actually
 * typed) — a fuzzy name match is common and often coincidental (two
 * different patients sharing a common name), so it must never block or
 * force a choice, only offer one. The one dismiss action (×) hides it for
 * this exact still-unchanged name; RegisterVisitForm.jsx itself un-hides it
 * again the moment the name changes to a new value (see that component's
 * own `dismissedName` state). */
export function PatientNameSuggestions({ patients, onSelect, onDismiss }) {
  if (!patients || patients.length === 0) return null;

  return (
    <div className="absolute z-10 mt-1 w-full rounded-md border border-border bg-card shadow-md">
      <div className="flex items-center justify-between border-b border-border px-3 py-1.5">
        <span className="text-xs text-muted-foreground">
          Similar name{patients.length === 1 ? '' : 's'} already registered
        </span>
        <Button
          type="button"
          variant="ghost"
          size="sm"
          className="h-6 w-6 p-0"
          onClick={onDismiss}
          aria-label="Dismiss suggestions"
        >
          <X className="h-3.5 w-3.5" />
        </Button>
      </div>
      <ul className="max-h-56 overflow-y-auto py-1">
        {patients.map((patient) => (
          <li key={patient.id}>
            <button
              type="button"
              className={cn(
                'flex w-full flex-col items-start px-3 py-2 text-left text-sm hover:bg-muted',
              )}
              onClick={() => onSelect(patient)}
            >
              <span className="font-medium text-foreground">
                {patient.full_name} · {patient.mr_number} · {patient.phone_number}
              </span>
            </button>
          </li>
        ))}
      </ul>
    </div>
  );
}
