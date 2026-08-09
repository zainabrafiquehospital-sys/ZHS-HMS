import Image from 'next/image';
import { env } from '@/core/config/env';

/** Shared wrapper for every unauthenticated page (login, signup,
 * forgot-password, verify-email) — the logo lives here once (Part
 * 3.4), not duplicated per page, so it's guaranteed consistent across
 * the whole auth flow. Full logo (not the sidebar's compact chip
 * treatment): this background is light, exactly what the source
 * logo.png was actually designed to sit on (see AppSidebar.jsx's own
 * docstring on the logo's mixed-contrast elements) — no chip needed
 * here. */
export default function AuthLayout({ children }) {
  return (
    <div className="relative flex min-h-screen w-full items-center justify-center overflow-hidden bg-background p-6">
      <div
        className="pointer-events-none absolute inset-0"
        style={{
          background:
            'radial-gradient(ellipse 80% 60% at 50% -10%, hsl(var(--brand-navy) / 0.10), transparent), radial-gradient(ellipse 60% 40% at 100% 100%, hsl(var(--brand-maroon) / 0.06), transparent)',
        }}
        aria-hidden="true"
      />
      <div className="absolute inset-x-0 top-0 h-1.5 bg-gradient-to-r from-brand-navy via-brand-navy-light to-brand-maroon" />

      <div className="relative flex w-full flex-col items-center gap-8">
        <div className="flex flex-col items-center gap-2 text-center">
          <Image src="/images/logo.png" alt={env.appName} width={88} height={88} priority />
          <p className="text-xs font-semibold uppercase tracking-[0.2em] text-brand-navy">
            {env.appName}
          </p>
        </div>
        {children}
      </div>
    </div>
  );
}
