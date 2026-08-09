'use client';

import { useMediaQuery } from '@/shared/hooks/useMediaQuery';
import { Toast } from '@/shared/components/toast/Toast';
import { cn } from '@/utils/cn';

/** Positioning only — Part 4.4: a top-right stack works fine on a
 * desktop viewport but is genuinely unusable on a phone (too narrow
 * to read comfortably, too far from the thumb) — reuses this
 * codebase's existing `useMediaQuery` hook (already used nowhere else
 * yet before the Vitals form check, per this task's own Part 1
 * investigation — not a new responsive approach) rather than doing
 * this with CSS alone, since the two layouts need genuinely different
 * flex-direction/alignment, not just a width change. */
export function ToastViewport({ toasts, onDismiss }) {
  const isDesktop = useMediaQuery('(min-width: 640px)');

  if (toasts.length === 0) return null;

  return (
    <div
      className={cn(
        'pointer-events-none fixed z-[100] flex w-full gap-2',
        isDesktop
          ? 'right-4 top-4 max-w-sm flex-col'
          : 'inset-x-0 bottom-0 flex-col-reverse p-3 pb-[max(0.75rem,env(safe-area-inset-bottom))]',
      )}
    >
      {toasts.map((toast) => (
        <Toast key={toast.id} toast={toast} onDismiss={onDismiss} />
      ))}
    </div>
  );
}
