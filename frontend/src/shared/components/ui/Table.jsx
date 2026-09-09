import { cn } from '@/utils/cn';

export function Table({ className, ...props }) {
  return (
    // `overflow-y-hidden` is explicit and load-bearing: a block with
    // `overflow-x: auto` and `overflow-y: visible` (the initial value)
    // has its `overflow-y` promoted to `auto` by the CSS Overflow spec
    // ("if one axis is `visible` and the other is not, `visible`
    // computes to `auto`"). A `<table>` child then renders a hair taller
    // than this wrapper's content box (table box-height rounding), so
    // Chrome paints a phantom vertical scrollbar here — the second
    // scrollbar seen next to the page's own (`<main>` in
    // DashboardShell). Pinning `overflow-y` to `hidden` keeps the
    // horizontal scroll for wide tables while never scrolling
    // vertically (the page owns that).
    <div className="w-full overflow-x-auto overflow-y-hidden">
      <table className={cn('w-full caption-bottom text-sm', className)} {...props} />
    </div>
  );
}

export function TableHeader({ className, ...props }) {
  return <thead className={cn('border-b border-border', className)} {...props} />;
}

export function TableBody({ className, ...props }) {
  return <tbody className={cn('[&_tr:last-child]:border-0', className)} {...props} />;
}

export function TableRow({ className, ...props }) {
  return (
    <tr
      className={cn('border-b border-border transition-colors hover:bg-muted/50', className)}
      {...props}
    />
  );
}

export function TableHead({ className, ...props }) {
  return (
    <th
      className={cn(
        'h-10 px-3 text-left align-middle text-xs font-medium uppercase tracking-wide text-muted-foreground',
        className,
      )}
      {...props}
    />
  );
}

export function TableCell({ className, ...props }) {
  return <td className={cn('p-3 align-middle', className)} {...props} />;
}
