import { cn } from '@/utils/cn';

/**
 * Generic, feature-agnostic application shell. Feature modules render their
 * own content inside `children` — this component owns layout only, never
 * business content.
 */
export function DashboardShell({ sidebar, header, children, className }) {
  return (
    <div className="flex h-screen w-full overflow-hidden bg-background text-foreground">
      {sidebar ? (
        <aside className="hidden w-64 shrink-0 border-r border-border md:block">{sidebar}</aside>
      ) : null}
      <div className="flex min-w-0 flex-1 flex-col">
        {header ? (
          <header className="flex h-14 shrink-0 items-center border-b border-border px-4">
            {header}
          </header>
        ) : null}
        <main className={cn('flex-1 overflow-y-auto p-6', className)}>{children}</main>
      </div>
    </div>
  );
}
