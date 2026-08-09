'use client';

import { useEffect, useState } from 'react';
import { CheckCircle2, AlertTriangle, Info, Loader2, X } from 'lucide-react';
import { cn } from '@/utils/cn';

// Brand colors from Part 2 — success stays the existing green Badge
// already uses elsewhere (bg-emerald-600, untouched — nothing to fix
// there), error/info are the hospital's actual maroon/navy, not a
// generic red/blue.
const VARIANT_CONFIG = {
  success: { Icon: CheckCircle2, iconClass: 'text-emerald-600', barClass: 'bg-emerald-600' },
  error: { Icon: AlertTriangle, iconClass: 'text-brand-maroon', barClass: 'bg-brand-maroon' },
  info: { Icon: Info, iconClass: 'text-brand-navy', barClass: 'bg-brand-navy' },
  loading: { Icon: Loader2, iconClass: 'text-brand-navy', barClass: 'bg-brand-navy' },
};

/** The bottom-edge line that shrinks over `duration` so the user can
 * see how long an auto-dismissing toast has left (Part 4.3) — a CSS
 * transform transition triggered one tick after mount (starting at
 * `scaleX(1)` and immediately requesting the transition to
 * `scaleX(0)` in the same frame wouldn't animate; the browser needs a
 * layout pass with the starting value committed first). */
function AutoDismissBar({ duration, colorClass }) {
  const [shrink, setShrink] = useState(false);
  useEffect(() => {
    const id = requestAnimationFrame(() => setShrink(true));
    return () => cancelAnimationFrame(id);
  }, []);
  return (
    <div className="h-1 w-full bg-black/5">
      <div
        className={cn('h-full origin-left ease-linear', colorClass)}
        style={{
          transform: shrink ? 'scaleX(0)' : 'scaleX(1)',
          transitionProperty: 'transform',
          transitionDuration: `${duration}ms`,
        }}
      />
    </div>
  );
}

export function Toast({ toast, onDismiss }) {
  const { id, variant, title, description, onRetry, spinner, duration, exiting } = toast;
  const { Icon, iconClass, barClass } = VARIANT_CONFIG[variant] ?? VARIANT_CONFIG.info;

  return (
    <div
      role={variant === 'error' ? 'alert' : 'status'}
      className={cn(
        'pointer-events-auto w-full overflow-hidden rounded-lg border border-border bg-card shadow-lg',
        'animate-in fade-in slide-in-from-bottom-4 duration-300 md:slide-in-from-right-8 md:slide-in-from-bottom-0',
        exiting && 'animate-out fade-out slide-out-to-right-8 duration-200',
      )}
    >
      <div className="flex items-start gap-3 p-4">
        <Icon className={cn('mt-0.5 h-5 w-5 shrink-0', iconClass, spinner && 'animate-spin')} />
        <div className="min-w-0 flex-1">
          {title ? <p className="text-sm font-semibold text-foreground">{title}</p> : null}
          {description ? (
            <p className="mt-0.5 text-sm text-muted-foreground">{description}</p>
          ) : null}
          {variant === 'error' ? (
            <div className="mt-2 flex gap-4">
              {onRetry ? (
                <button
                  type="button"
                  onClick={() => {
                    onDismiss(id);
                    onRetry();
                  }}
                  className="text-xs font-semibold text-brand-navy hover:underline"
                >
                  Retry
                </button>
              ) : null}
              <button
                type="button"
                onClick={() => onDismiss(id)}
                className="text-xs font-medium text-muted-foreground hover:underline"
              >
                Dismiss
              </button>
            </div>
          ) : null}
        </div>
        <button
          type="button"
          onClick={() => onDismiss(id)}
          aria-label="Close notification"
          className="shrink-0 rounded-md p-0.5 text-muted-foreground transition-colors hover:bg-muted hover:text-foreground"
        >
          <X className="h-4 w-4" />
        </button>
      </div>
      {duration ? <AutoDismissBar duration={duration} colorClass={barClass} /> : null}
    </div>
  );
}
