'use client';

import { cn } from '@/utils/cn';

/**
 * A plain, dependency-free tab switcher — not Radix-based. This
 * codebase has no Radix (or any headless-UI) dependency anywhere (every
 * `shared/components/ui/*` primitive here is a plain element styled
 * with `cva`/`cn` — see e.g. Select.jsx's identical "not a Radix-based
 * X" docstring), so this follows suit rather than being the first to
 * introduce one for a control this simple: a small, fixed set of
 * mutually-exclusive views, controlled entirely by the parent.
 */
export function Tabs({ value, onValueChange, tabs, className }) {
  return (
    <div
      role="tablist"
      className={cn(
        'inline-flex items-center gap-1 rounded-md border border-border bg-muted/30 p-1',
        className,
      )}
    >
      {tabs.map((tab) => (
        <button
          key={tab.value}
          type="button"
          role="tab"
          aria-selected={value === tab.value}
          onClick={() => onValueChange(tab.value)}
          className={cn(
            'rounded-sm px-3 py-1.5 text-sm font-medium transition-colors',
            value === tab.value
              ? 'bg-card text-foreground shadow-sm'
              : 'text-muted-foreground hover:text-foreground',
          )}
        >
          {tab.label}
        </button>
      ))}
    </div>
  );
}
