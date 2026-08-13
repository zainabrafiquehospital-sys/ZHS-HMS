'use client';

import { Cell, Legend, Pie, PieChart, ResponsiveContainer, Tooltip } from 'recharts';

// The same validated 3-slot categorical palette used before (see the
// `dataviz` skill's palette.md — "the first three slots validate
// all-pairs in both modes", the guarantee a pie/donut needs since any
// two slices can end up next to each other, not just neighbors).
// Assigned by each render's own revenue rank (1st/2nd/3rd), not a
// fixed per-receptionist mapping — unlike a stable entity such as a
// product name that's always the same color, there is no fixed roster
// to pre-assign colors to here, and who ranks 1st/2nd/3rd changes day
// to day by design (this is a fresh ranking of a new day's data each
// time, not a filter reshuffling survivors of the same view).
const SLICE_COLOR = ['#2a78d6', '#eb6834', '#1baf7a'];
// "Other" (the folded tail beyond the top 3 — see revenueByActor.js's
// `computeRevenueByActor`) always renders in this chrome/ink muted
// gray, never one of the categorical hues, so it can never be mistaken
// for a named receptionist's own slice.
const OTHER_COLOR = '#898781';

const _currencyFormatter = new Intl.NumberFormat('en-US', {
  minimumFractionDigits: 2,
  maximumFractionDigits: 2,
});

function formatPkr(amount) {
  return `PKR ${_currencyFormatter.format(Number(amount))}`;
}

function _renderSliceLabel({ label, amount, percent }) {
  // A pie/donut is genuinely hard to read when slices are close in
  // size (see the `dataviz` skill's anti-patterns) — direct percentage
  // labels on every slice (safe here: at most 4 series — top 3 +
  // Other — well within the "1-3 direct-label" band, and a legend is
  // shown alongside regardless) mitigate that by making the reader
  // compare numbers, not angles. Slices too thin for their own label
  // (near-zero revenue) are skipped rather than overlapping text.
  if (amount <= 0) return null;
  return `${label} ${(percent * 100).toFixed(0)}%`;
}

/** Per-receptionist revenue share for the selected day, as a donut
 * chart — `data` is `[{ actorId, label, amount, isOther }]`, already
 * resolved to a display name and capped at the top 3 contributors + an
 * "Other" slice for the rest by the caller (see features/admin/utils/
 * revenueByActor.js's `computeRevenueByActor`; label resolution itself
 * lives in the caller, using the existing useReceptionistsForVisits /
 * useUsersForMedicineBills join hooks, so this component stays purely
 * presentational — it does not interpret `actorId`, only uses it as a
 * stable React key, since two receptionists could plausibly share a
 * display name/label but never an id). Direct slice labels + a legend
 * with exact PKR amounts + a hover tooltip, so identity and magnitude
 * are never color-alone (see the `dataviz` skill's accessibility
 * rules). */
export function RevenueByActorPieChart({ data }) {
  const total = data.reduce((sum, entry) => sum + entry.amount, 0);
  const hasRevenue = total > 0;

  function colorFor(entry, index) {
    return entry.isOther ? OTHER_COLOR : SLICE_COLOR[index];
  }

  return (
    <div className="flex flex-col gap-2">
      {hasRevenue ? (
        <ResponsiveContainer width="100%" height={240}>
          <PieChart>
            <Pie
              data={data}
              dataKey="amount"
              nameKey="label"
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
              {data.map((entry, index) => (
                <Cell key={entry.actorId} fill={colorFor(entry, index)} />
              ))}
            </Pie>
            <Tooltip formatter={(value) => formatPkr(value)} />
            <Legend
              formatter={(_value, entry) => (
                <span className="text-sm text-foreground">
                  {entry.payload.label} — {formatPkr(entry.payload.amount)}
                </span>
              )}
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
        <caption className="sr-only">Revenue by receptionist</caption>
        <tbody>
          {data.map((entry, index) => (
            <tr key={entry.actorId} className="border-b border-border last:border-0">
              <td className="flex items-center gap-2 py-1.5 text-muted-foreground">
                <span
                  className="h-2.5 w-2.5 shrink-0 rounded-full"
                  style={{ backgroundColor: colorFor(entry, index) }}
                  aria-hidden="true"
                />
                {entry.label}
              </td>
              <td className="py-1.5 text-right font-medium tabular-nums text-foreground">
                {formatPkr(entry.amount)}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
