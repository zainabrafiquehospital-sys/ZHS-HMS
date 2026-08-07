'use client';

import { AlertTriangle } from 'lucide-react';

export function PageError({ error, reset, message = 'Something went wrong.' }) {
  return (
    <div className="flex h-full min-h-[240px] w-full flex-col items-center justify-center gap-3 text-center">
      <AlertTriangle className="h-6 w-6 text-destructive" />
      <p className="text-sm text-foreground">{message}</p>
      {error?.message ? (
        <p className="max-w-md text-xs text-muted-foreground">{error.message}</p>
      ) : null}
      {reset ? (
        <button
          type="button"
          onClick={reset}
          className="rounded-md border border-border bg-background px-3 py-1.5 text-sm hover:bg-muted"
        >
          Try again
        </button>
      ) : null}
    </div>
  );
}
