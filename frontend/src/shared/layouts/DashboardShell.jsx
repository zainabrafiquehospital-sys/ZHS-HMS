'use client';

import { useEffect, useState } from 'react';
import { usePathname } from 'next/navigation';
import { Menu, X } from 'lucide-react';
import { cn } from '@/utils/cn';

/**
 * Generic, feature-agnostic application shell. Feature modules render their
 * own content inside `children` — this component owns layout only, never
 * business content.
 *
 * Mobile navigation (Part 3.2): below `md`, the static sidebar this
 * shell rendered before is completely absent — there was no mobile
 * nav at all, not a broken one (confirmed against the actual
 * previous markup: `hidden ... md:block`, no fallback). The hamburger
 * drawer built here reuses the *same* `sidebar` element passed in —
 * one AppSidebar render target, shown either as the static desktop
 * rail or inside the slide-in drawer, never a second parallel nav
 * definition to keep in sync. Manually transform/opacity-driven
 * (`translate-x`, no Radix/portal dependency) rather than
 * `tailwindcss-animate`'s data-state utilities, which need a
 * Radix-style `data-state` attribute this plain `useState` toggle
 * doesn't produce — a directly-toggled class is simpler here and
 * needs no new dependency.
 */
export function DashboardShell({ sidebar, header, children, className }) {
  const [isMobileNavOpen, setIsMobileNavOpen] = useState(false);
  const pathname = usePathname();

  // Close the drawer on navigation — without this, tapping a nav link
  // on mobile would navigate but leave the drawer open over the new
  // page until manually dismissed.
  useEffect(() => {
    setIsMobileNavOpen(false);
  }, [pathname]);

  // Prevent the page behind the drawer from scrolling while it's open.
  useEffect(() => {
    if (!isMobileNavOpen) return undefined;
    const previousOverflow = document.body.style.overflow;
    document.body.style.overflow = 'hidden';
    return () => {
      document.body.style.overflow = previousOverflow;
    };
  }, [isMobileNavOpen]);

  return (
    <div className="flex h-screen w-full overflow-hidden bg-background text-foreground">
      {sidebar ? <aside className="hidden w-64 shrink-0 md:block">{sidebar}</aside> : null}

      {sidebar ? (
        <>
          <div
            className={cn(
              'fixed inset-0 z-40 bg-black/50 transition-opacity duration-300 md:hidden',
              isMobileNavOpen ? 'opacity-100' : 'pointer-events-none opacity-0',
            )}
            onClick={() => setIsMobileNavOpen(false)}
            aria-hidden="true"
          />
          <aside
            className={cn(
              'fixed inset-y-0 left-0 z-50 w-72 max-w-[85vw] transform transition-transform duration-300 ease-in-out md:hidden',
              isMobileNavOpen ? 'translate-x-0' : '-translate-x-full',
            )}
            aria-hidden={!isMobileNavOpen}
          >
            {sidebar}
          </aside>
        </>
      ) : null}

      <div className="flex min-w-0 flex-1 flex-col">
        {header || sidebar ? (
          <header className="flex h-14 shrink-0 items-center gap-3 border-b border-border px-4">
            {sidebar ? (
              <button
                type="button"
                className="-ml-1 flex h-9 w-9 shrink-0 items-center justify-center rounded-md text-foreground transition-colors hover:bg-muted md:hidden"
                onClick={() => setIsMobileNavOpen((open) => !open)}
                aria-label={isMobileNavOpen ? 'Close navigation menu' : 'Open navigation menu'}
                aria-expanded={isMobileNavOpen}
              >
                {isMobileNavOpen ? <X className="h-5 w-5" /> : <Menu className="h-5 w-5" />}
              </button>
            ) : null}
            <div className="min-w-0 flex-1">{header}</div>
          </header>
        ) : null}
        <main className={cn('flex-1 overflow-y-auto p-4 sm:p-6', className)}>{children}</main>
      </div>
    </div>
  );
}
