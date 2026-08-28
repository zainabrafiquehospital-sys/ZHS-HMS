'use client';

import { X } from 'lucide-react';
import { Card, CardContent, CardHeader, CardTitle } from '@/shared/components/ui/Card';
import { Button } from '@/shared/components/ui/Button';

/** A wide, scrollable "here's everything" modal — sibling to
 * ConfirmDialog (2026-08-28 addition), same fixed-overlay Card shell
 * PatientVisitHistoryDialog.jsx already established for this exact
 * shape, pulled out as a genuine shared primitive since Vitals'
 * cross-visit history dialog needed the identical structure: a single
 * Close button, never confirm/cancel — this is a read-only "view
 * details" surface, not a prompt awaiting a decision. Content is
 * entirely caller-supplied via `children`, same as Card/CardContent
 * would be composed directly, just wrapped with the overlay/header/
 * scroll-region boilerplate so every "show details" dialog in the app
 * doesn't re-implement it. */
export function DetailsDialog({ open, title, subtitle, onClose, children }) {
  if (!open) return null;

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/50 p-4"
      role="dialog"
      aria-modal="true"
      aria-labelledby="details-dialog-title"
    >
      <Card className="flex max-h-[85vh] w-full max-w-3xl flex-col">
        <CardHeader className="flex-row items-center justify-between gap-2">
          <div>
            <CardTitle id="details-dialog-title">{title}</CardTitle>
            {subtitle ? <p className="text-xs text-muted-foreground">{subtitle}</p> : null}
          </div>
          <Button variant="ghost" size="sm" onClick={onClose} aria-label="Close">
            <X className="h-4 w-4" />
          </Button>
        </CardHeader>
        <CardContent className="flex flex-col gap-4 overflow-y-auto">{children}</CardContent>
      </Card>
    </div>
  );
}
