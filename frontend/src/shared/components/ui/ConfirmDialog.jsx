'use client';

import { Card, CardContent, CardHeader, CardTitle } from '@/shared/components/ui/Card';
import { Button } from '@/shared/components/ui/Button';
import { cn } from '@/utils/cn';

/** A blocking confirmation modal — reuses Card/Button rather than a
 * one-off styled overlay, and `variant` reuses Button's own variant
 * tokens (e.g. `destructive` for a critical-value confirmation) so a
 * "this is serious" prompt looks like every other destructive/serious
 * action in the app, not a new one-off color. No animation/portal
 * library dependency: a fixed-position overlay is enough for a
 * confirm-or-cancel prompt and keeps this genuinely reusable without
 * pulling in new dependencies for one component. */
export function ConfirmDialog({
  open,
  title,
  description,
  confirmLabel = 'Confirm',
  cancelLabel = 'Cancel',
  onConfirm,
  onCancel,
  variant = 'default',
}) {
  if (!open) return null;

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/50 p-4"
      role="dialog"
      aria-modal="true"
      aria-labelledby="confirm-dialog-title"
    >
      <Card className="w-full max-w-md">
        <CardHeader>
          <CardTitle id="confirm-dialog-title" className={cn(variant === 'destructive' && 'text-destructive')}>
            {title}
          </CardTitle>
        </CardHeader>
        <CardContent className="flex flex-col gap-5">
          {typeof description === 'string' ? (
            <p className="whitespace-pre-line text-sm text-muted-foreground">{description}</p>
          ) : (
            description
          )}
          <div className="flex flex-col-reverse gap-2 sm:flex-row sm:justify-end">
            <Button variant="outline" size="lg" onClick={onCancel} className="sm:w-auto">
              {cancelLabel}
            </Button>
            <Button variant={variant} size="lg" onClick={onConfirm} className="sm:w-auto">
              {confirmLabel}
            </Button>
          </div>
        </CardContent>
      </Card>
    </div>
  );
}
