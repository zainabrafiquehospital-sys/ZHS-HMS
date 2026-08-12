'use client';

import { Cell, Legend, Pie, PieChart, ResponsiveContainer, Tooltip } from 'recharts';
import { SHIFT_ORDER } from '@/utils/timezone';

// The validated 3-slot categorical palette (see the `dataviz` skill's
// references/palette.md — "the first three slots validate all-pairs in
// both modes", the strongest guarantee that palette offers, which is
// exactly this chart's shape: 3 fixed categories, always shown
// together). Assigned in `SHIFT_ORDER`'s fixed order — never cycled,
// per that skill's own non-negotiable rule. This app has no dark-mode
// implementation anywhere (`darkMode: ['class']` in tailwind.config.js
// is unused shadcn scaffolding — confirmed zero `dark:` usages in the
// whole codebase), so only the light-mode steps are used here; revisit
// if a real dark theme is ever added.
const SHIFT_COLOR = {
  morning: '#2a78d6', // categorical slot 1 (blue)
  evening: '#eb6834', // categorical slot 2 (orange)
  night: '#1baf7a', // categorical slot 3 (aqua)
};

const SHIFT_LABEL = { morning: 'Morning', evening: 'Evening', night: 'Night' };

const _currencyFormatter = new Intl.NumberFormat('en-US', {
  minimumFractionDigits: 2,
  maximumFractionDigits: 2,
});

function formatPkr(amount) {
  return `PKR ${_currencyFormatter.format(Number(amount))}`;
}

function _renderSliceLabel({ shift, amount, percent }) {
  // A pie/donut is genuinely hard to read when slices are close in
  // size (see the `dataviz` skill's anti-patterns) — direct percentage
  // labels on every slice (safe here: only 3 series, well within the
  // "1-3: direct-label" band) mitigate that by making the reader
  // compare numbers, not angles. Slices too thin for their own label
  // (near-zero revenue) are skipped rather than overlapping text.
  if (amount <= 0) return null;
  return `${SHIFT_LABEL[shift]} ${(percent * 100).toFixed(0)}%`;
}

/** Per-shift revenue share, as a donut chart — `data` is
 * `computeShiftRevenueBreakdown`'s output (features/admin/utils/
 * shiftRevenue.js): `[{ shift, amount }]` in `SHIFT_ORDER`. Direct
 * slice labels + a legend with exact PKR amounts + a hover tooltip, so
 * identity and magnitude are never color-alone (see the `dataviz`
 * skill's accessibility rules) — a colorblind or grayscale-print reader
 * can still read this from the labels/legend text alone. */
export function ShiftRevenuePieChart({ data }) {
  const total = data.reduce((sum, entry) => sum + entry.amount, 0);
  const hasRevenue = total > 0;

  return (
    <div className="flex flex-col gap-2">
      {hasRevenue ? (
        <ResponsiveContainer width="100%" height={240}>
          <PieChart>
            <Pie
              data={data}
              dataKey="amount"
              nameKey="shift"
              innerRadius={55}
              outerRadius={85}
              paddingAngle={2}
              label={_renderSliceLabel}
              labelLine={false}
              // This chart re-renders on every date-navigation click in
              // Admin Overview (a new `data` array each time, not just a
              // prop tweak) — Recharts' default enter animation would
              // re-sweep from empty on every single navigation, which
              // reads as sluggish rather than informative for a value
              // that's simply replaced, not building up from zero.
              isAnimationActive={false}
            >
              {data.map((entry) => (
                <Cell key={entry.shift} fill={SHIFT_COLOR[entry.shift]} />
              ))}
            </Pie>
            <Tooltip formatter={(value) => formatPkr(value)} />
            <Legend
              formatter={(_value, entry) => {
                const shiftData = data.find((d) => d.shift === entry.payload.shift);
                return (
                  <span className="text-sm text-foreground">
                    {SHIFT_LABEL[entry.payload.shift]} — {formatPkr(shiftData?.amount ?? 0)}
                  </span>
                );
              }}
            />
          </PieChart>
        </ResponsiveContainer>
      ) : (
        <p className="py-16 text-center text-sm text-muted-foreground">
          No revenue recorded for this day yet.
        </p>
      )}

      {/* A table-view fallback, per the `dataviz` skill's accessibility
          rule ("a table view exists") — also just a plain, always-legible
          restatement of the chart's own numbers. */}
      <table className="w-full text-sm">
        <caption className="sr-only">Revenue by shift</caption>
        <tbody>
          {SHIFT_ORDER.map((shift) => {
            const entry = data.find((d) => d.shift === shift);
            const amount = entry?.amount ?? 0;
            return (
              <tr key={shift} className="border-b border-border last:border-0">
                <td className="flex items-center gap-2 py-1.5 text-muted-foreground">
                  <span
                    className="h-2.5 w-2.5 shrink-0 rounded-full"
                    style={{ backgroundColor: SHIFT_COLOR[shift] }}
                    aria-hidden="true"
                  />
                  {SHIFT_LABEL[shift]}
                </td>
                <td className="py-1.5 text-right font-medium tabular-nums text-foreground">
                  {formatPkr(amount)}
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}
