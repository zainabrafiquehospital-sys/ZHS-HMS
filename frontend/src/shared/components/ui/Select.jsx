import { cn } from '@/utils/cn';

/**
 * A plain native `<select>` styled to match the rest of the design
 * system — not a Radix-based combobox. Sufficient for this build's
 * fixed, short option lists (gender, destination, status filters); a
 * searchable combobox is a future upgrade, not a structural gap.
 */
export function Select({ className, children, ...props }) {
  return (
    <select
      className={cn(
        'flex h-9 w-full rounded-md border border-input bg-background px-3 py-1 text-sm shadow-sm transition-colors focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring disabled:cursor-not-allowed disabled:opacity-50',
        className,
      )}
      {...props}
    >
      {children}
    </select>
  );
}
