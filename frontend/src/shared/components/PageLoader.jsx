import Image from 'next/image';
import { env } from '@/core/config/env';

/** Branded loading state (Part 3.5) — the hospital logo with a gentle
 * pulse rather than a generic spinner, so even a loading screen reads
 * as this hospital's system rather than a default component-library
 * look. Backs both `app/loading.jsx` and `app/(dashboard)/loading.jsx`
 * (both already just render this one component), so this single
 * change covers every route-level loading state at once. */
export function PageLoader({ label = 'Loading' }) {
  return (
    <div className="flex h-full min-h-[240px] w-full flex-col items-center justify-center gap-4 text-muted-foreground">
      <div className="animate-pulse">
        <Image src="/images/logo.png" alt={env.appName} width={56} height={56} priority />
      </div>
      <p className="text-sm">{label}</p>
    </div>
  );
}
