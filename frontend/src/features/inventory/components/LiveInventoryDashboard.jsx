'use client';

import { useMemo } from 'react';
import Link from 'next/link';
import {
  Bar,
  BarChart,
  CartesianGrid,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts';
import {
  Activity,
  AlertTriangle,
  ArrowDownToLine,
  ArrowRight,
  ArrowRightLeft,
  Boxes,
  Check,
  ChevronRight,
  ClipboardCheck,
  Siren,
  TrendingDown,
  Warehouse,
} from 'lucide-react';
import {
  useEmergencyStockFeed,
  useInventoryItems,
  useInventoryUsageEntries,
} from '@/features/inventory/hooks/useInventory';
import { groupUsageEntries } from '@/features/inventory/utils/groupUsageEntries';
import { summarizeUsageByItem } from '@/features/inventory/utils/summarizeUsageByItem';
import {
  ARRIVAL_SOURCE,
  ARRIVAL_SOURCE_LABEL,
  buildEmergencyArrivalsFeed,
} from '@/features/inventory/utils/emergencyArrivalsFeed';
import { useAuth } from '@/features/auth/hooks/useAuth';
import { ROUTES } from '@/core/constants/routes';
import { PageLoader } from '@/shared/components/PageLoader';
import { PageError } from '@/shared/components/PageError';
import { cn } from '@/utils/cn';
import {
  displayDayKey,
  formatDisplayDate,
  formatDisplayTime,
  todayDisplayDayKey,
} from '@/utils/timezone';

const USAGE_PAGE_SIZE = 100;
const CHART_ITEM_LIMIT = 8;
const ATTENTION_LIMIT = 6;
const ACTIVITY_LIMIT = 8;
const USAGE_LOG_LIMIT = 6;

const UNIT_DISPLAY_ORDER = ['piece', 'bottle', 'box', 'vial', 'ampoule', 'ml'];

// Semantic tone -> fixed Tailwind class strings (never interpolated, so
// the JIT keeps them). `primary`/`destructive` are the app's own brand
// tokens; `emerald`/`amber` are the exact literals Badge.jsx already
// uses for its `success`/`warning` variants — no new colour is invented
// here, this only reuses the app's existing status vocabulary as soft
// tinted badge/pill backgrounds the way the reference dashboard does.
const TONE = {
  primary: { badge: 'bg-primary/10 text-primary', pill: 'bg-primary/10 text-primary' },
  emerald: { badge: 'bg-emerald-500/10 text-emerald-600', pill: 'bg-emerald-500/10 text-emerald-700' },
  amber: { badge: 'bg-amber-500/10 text-amber-600', pill: 'bg-amber-500/10 text-amber-700' },
  rose: { badge: 'bg-destructive/10 text-destructive', pill: 'bg-destructive/10 text-destructive' },
};

function formatQty(value) {
  const num = Number(value);
  if (!Number.isFinite(num)) return String(value ?? '0');
  return Number.isInteger(num) ? String(num) : num.toFixed(2).replace(/\.?0+$/, '');
}

function unitLabel(unit, quantity) {
  if (unit === 'ml') return 'ml';
  return quantity === 1 ? unit : `${unit}s`;
}

function breakdownByUnit(items, pick) {
  const totals = new Map();
  for (const item of items) {
    totals.set(item.unit, (totals.get(item.unit) ?? 0) + (Number(pick(item)) || 0));
  }
  return UNIT_DISPLAY_ORDER.filter((unit) => (totals.get(unit) ?? 0) > 0)
    .map((unit) => `${formatQty(totals.get(unit))} ${unitLabel(unit, totals.get(unit))}`)
    .join(' · ');
}

function truncate(text, max = 14) {
  return text.length > max ? `${text.slice(0, max - 1)}…` : text;
}

// ---------------------------------------------------------------------
// Presentational building blocks — the reference's specific micro-details
// ---------------------------------------------------------------------

/** Rounded-square colour-tinted icon badge (not a bare Lucide icon). */
function IconBadge({ icon: Icon, tone = 'primary', className }) {
  return (
    <div
      className={cn(
        'flex h-11 w-11 shrink-0 items-center justify-center rounded-xl',
        TONE[tone].badge,
        className,
      )}
    >
      <Icon className="h-5 w-5" />
    </div>
  );
}

/** Pill-shaped, colour-coded status badge with a leading icon — the
 * reference's green/red trend pill, but showing a real status word
 * rather than a fabricated percentage (this data has no week-over-week
 * snapshot to trend against). */
function StatusPill({ tone = 'emerald', icon: Icon = Check, children }) {
  return (
    <span
      className={cn(
        'inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-xs font-semibold',
        TONE[tone].pill,
      )}
    >
      <Icon className="h-3 w-3" />
      {children}
    </span>
  );
}

/** Soft, generously-rounded card with a subtle shadow instead of a hard
 * border — the reference's card treatment. */
function DashCard({ className, children }) {
  return (
    <div
      className={cn(
        'rounded-2xl border border-border/60 bg-card p-5 shadow-sm',
        className,
      )}
    >
      {children}
    </div>
  );
}

/** The reference's stat-card anatomy: colour icon badge top-left, an
 * optional "Details" link top-right, a small label, a large bold
 * number, and a status pill below. */
function StatCard({ icon, tone, label, value, sub, pill, detailsHref }) {
  return (
    <DashCard className="flex flex-col gap-3">
      <div className="flex items-start justify-between gap-2">
        <IconBadge icon={icon} tone={tone} />
        {detailsHref ? (
          <Link
            href={detailsHref}
            className="inline-flex items-center gap-0.5 text-xs font-medium text-primary hover:underline"
          >
            Details
            <ChevronRight className="h-3.5 w-3.5" />
          </Link>
        ) : null}
      </div>
      <div className="flex flex-col gap-0.5">
        <span className="text-xs font-medium uppercase tracking-wide text-muted-foreground">
          {label}
        </span>
        <span className="text-2xl font-bold tabular-nums text-foreground">{value}</span>
        {sub ? <span className="text-xs text-muted-foreground">{sub}</span> : null}
      </div>
      {pill}
    </DashCard>
  );
}

// ---------------------------------------------------------------------
// Panels
// ---------------------------------------------------------------------

function UsageChartPanel({ chartData }) {
  return (
    <DashCard className="flex flex-col gap-4">
      <div className="flex items-center gap-2">
        <IconBadge icon={ClipboardCheck} tone="primary" className="h-9 w-9 rounded-lg" />
        <div className="flex flex-col">
          <h2 className="text-sm font-semibold text-foreground">Today&apos;s Usage by Item</h2>
          <p className="text-xs text-muted-foreground">Quantity used across all submissions today</p>
        </div>
      </div>
      {chartData.length === 0 ? (
        <p className="py-16 text-center text-sm text-muted-foreground">
          No inventory usage recorded yet today.
        </p>
      ) : (
        <>
          <ResponsiveContainer width="100%" height={260}>
            <BarChart data={chartData} margin={{ top: 8, right: 8, left: -16, bottom: 4 }}>
              <CartesianGrid vertical={false} strokeDasharray="3 3" stroke="hsl(var(--border))" />
              <XAxis
                dataKey="name"
                tick={{ fontSize: 11, fill: 'hsl(var(--muted-foreground))' }}
                tickLine={false}
                axisLine={false}
                interval={0}
                angle={-18}
                textAnchor="end"
                height={54}
              />
              <YAxis
                tick={{ fontSize: 11, fill: 'hsl(var(--muted-foreground))' }}
                tickLine={false}
                axisLine={false}
                allowDecimals={false}
                width={34}
              />
              <Tooltip
                cursor={{ fill: 'hsl(var(--muted))' }}
                contentStyle={{
                  borderRadius: 12,
                  border: '1px solid hsl(var(--border))',
                  fontSize: 12,
                }}
                formatter={(v, _n, entry) => [`${formatQty(v)} ${entry.payload.unit}`, 'Used today']}
              />
              <Bar
                dataKey="qty"
                radius={[6, 6, 0, 0]}
                fill="hsl(var(--primary))"
                maxBarSize={44}
                isAnimationActive={false}
              />
            </BarChart>
          </ResponsiveContainer>
          {/* Table-view fallback — a plain, always-legible restatement of
              the same numbers (the app's own dataviz accessibility rule,
              see RevenueByActorPieChart.jsx). */}
          <table className="w-full text-sm">
            <caption className="sr-only">Today&apos;s usage by item</caption>
            <tbody className="divide-y divide-border/60">
              {chartData.map((row) => (
                <tr key={row.itemId}>
                  <td className="py-1.5 text-muted-foreground">{row.fullName}</td>
                  <td className="py-1.5 text-right font-medium tabular-nums text-foreground">
                    {formatQty(row.qty)} {row.unit}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </>
      )}
    </DashCard>
  );
}

function AttentionPanel({ rows }) {
  return (
    <DashCard className="flex flex-col gap-4">
      <div className="flex items-center gap-2">
        <IconBadge icon={Siren} tone="amber" className="h-9 w-9 rounded-lg" />
        <div className="flex flex-col">
          <h2 className="text-sm font-semibold text-foreground">Emergency Stock — Needs Attention</h2>
          <p className="text-xs text-muted-foreground">Lowest levels first</p>
        </div>
      </div>
      {rows.length === 0 ? (
        <p className="py-10 text-center text-sm text-muted-foreground">
          No active items in the catalog yet.
        </p>
      ) : (
        <ul className="flex flex-col gap-2">
          {rows.map(({ item, tone }) => (
            <li
              key={item.id}
              className={cn(
                'flex items-center gap-3 rounded-xl px-3 py-2.5',
                TONE[tone].pill,
              )}
            >
              <span className="flex h-8 w-8 shrink-0 items-center justify-center rounded-lg bg-card/70">
                {tone === 'rose' ? (
                  <AlertTriangle className="h-4 w-4 text-destructive" />
                ) : (
                  <Siren className="h-4 w-4 text-amber-600" />
                )}
              </span>
              <span className="flex min-w-0 flex-1 flex-col">
                <span className="truncate text-sm font-semibold text-foreground" title={item.name}>
                  {item.name}
                </span>
                <span className="text-xs text-foreground/70">
                  {tone === 'rose' ? 'Below threshold' : 'Running low'}
                </span>
              </span>
              <span className="shrink-0 text-sm font-bold tabular-nums text-foreground">
                {formatQty(item.emergency_stock_level)}{' '}
                <span className="text-xs font-normal">{item.unit}</span>
              </span>
              <ChevronRight className="h-4 w-4 shrink-0 text-foreground/50" />
            </li>
          ))}
        </ul>
      )}
    </DashCard>
  );
}

const SOURCE_ICON = {
  [ARRIVAL_SOURCE.DIRECT]: ArrowDownToLine,
  [ARRIVAL_SOURCE.TRANSFER]: ArrowRightLeft,
};

function RecentActivityPanel({ feed, itemsById }) {
  return (
    <DashCard className="flex flex-col gap-4">
      <div className="flex items-center gap-2">
        <IconBadge icon={ArrowDownToLine} tone="emerald" className="h-9 w-9 rounded-lg" />
        <div className="flex flex-col">
          <h2 className="text-sm font-semibold text-foreground">Recent Stock Activity</h2>
          <p className="text-xs text-muted-foreground">Arrivals into Emergency Stock</p>
        </div>
      </div>
      {feed.length === 0 ? (
        <p className="py-10 text-center text-sm text-muted-foreground">
          No stock has arrived into Emergency Stock yet.
        </p>
      ) : (
        <table className="w-full text-sm">
          <thead>
            <tr className="text-left text-xs font-medium uppercase tracking-wide text-muted-foreground">
              <th className="pb-2 font-medium">Item</th>
              <th className="pb-2 text-right font-medium">Qty</th>
              <th className="pb-2 font-medium">Added by</th>
              <th className="pb-2 font-medium">When</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-border/60">
            {feed.map((entry) => {
              const item = itemsById.get(entry.item_id);
              const Icon = SOURCE_ICON[entry.source] ?? ArrowDownToLine;
              return (
                <tr key={`${entry.source}-${entry.id}`}>
                  <td className="py-2.5">
                    <span className="flex items-center gap-2">
                      <span className="flex h-7 w-7 shrink-0 items-center justify-center rounded-lg bg-primary/10 text-primary">
                        <Icon className="h-3.5 w-3.5" />
                      </span>
                      <span className="flex min-w-0 flex-col">
                        <span className="truncate font-medium text-foreground">
                          {item?.name ?? 'Unknown item'}
                        </span>
                        <span className="text-[11px] text-muted-foreground">
                          {ARRIVAL_SOURCE_LABEL[entry.source]}
                        </span>
                      </span>
                    </span>
                  </td>
                  <td className="whitespace-nowrap py-2.5 text-right font-semibold tabular-nums text-foreground">
                    {formatQty(entry.quantity)} {item?.unit ?? ''}
                  </td>
                  <td className="max-w-[9rem] truncate py-2.5 text-muted-foreground">
                    {entry.created_by_display_name ?? '—'}
                  </td>
                  <td className="whitespace-nowrap py-2.5 text-muted-foreground">
                    {formatDisplayDate(displayDayKey(entry.created_at))} ·{' '}
                    {formatDisplayTime(entry.created_at)}
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      )}
    </DashCard>
  );
}

function UsageLogPanel({ groups, items, submissionCount, itemCount }) {
  return (
    <DashCard className="flex flex-col gap-4">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div className="flex items-center gap-2">
          <IconBadge icon={ClipboardCheck} tone="primary" className="h-9 w-9 rounded-lg" />
          <div className="flex flex-col">
            <h2 className="text-sm font-semibold text-foreground">Today&apos;s Usage Log</h2>
            <p className="text-xs text-muted-foreground">
              {submissionCount} {submissionCount === 1 ? 'submission' : 'submissions'} ·{' '}
              {itemCount} {itemCount === 1 ? 'item' : 'items'}
            </p>
          </div>
        </div>
        <Link
          href={ROUTES.DAILY_INVENTORY_USAGE}
          className="inline-flex items-center gap-1 text-sm font-medium text-primary hover:underline"
        >
          Full Daily Usage
          <ArrowRight className="h-3.5 w-3.5" />
        </Link>
      </div>
      {groups.length === 0 ? (
        <p className="py-10 text-center text-sm text-muted-foreground">
          No inventory usage recorded yet today.
        </p>
      ) : (
        <ul className="flex flex-col gap-2">
          {groups.slice(0, USAGE_LOG_LIMIT).map((group) => {
            const names = group.lines.map(
              (line) => items?.find((i) => i.id === line.item_id)?.name ?? 'Unknown item',
            );
            const summary =
              names.length === 1 ? names[0] : `${names[0]} + ${names.length - 1} more`;
            const patient = group.patientId
              ? group.patientDisplayName
              : group.manualPatientName || 'Anonymous';
            return (
              <li
                key={group.key}
                className="flex items-center gap-3 rounded-xl border border-border/60 bg-card px-3 py-2.5"
              >
                <span className="flex min-w-0 flex-1 flex-col">
                  <span className="truncate text-sm font-semibold text-foreground">{summary}</span>
                  <span className="truncate text-xs text-muted-foreground">
                    {patient} · {group.createdByDisplayName ?? '—'} ·{' '}
                    {formatDisplayTime(group.createdAt)}
                  </span>
                </span>
                <StatusPill tone="emerald" icon={Check}>
                  Recorded
                </StatusPill>
              </li>
            );
          })}
        </ul>
      )}
    </DashCard>
  );
}

// ---------------------------------------------------------------------
// Page
// ---------------------------------------------------------------------

/** Live Inventory — a read-only, auto-refreshing (15s) command-centre
 * view of both stock tiers and the day's usage, for the three
 * `inventory:read` roles (Inventory Manager, Admin, Vitals). The 2026-09
 * redesign maps a room-management dashboard reference onto this real
 * data: colour icon-badge stat cards with status pills, a usage bar
 * chart (recharts, the lib RevenueByActorPieChart.jsx already uses), a
 * "needs attention" pill list, and clean-row activity/usage tables. All
 * data-fetching/polling and permission gating are unchanged from the
 * first build — this is a visual/layout pass only. "Details" links to
 * /inventory are shown only to `inventory:manage` holders (Vitals can't
 * open that route); everyone gets the /daily-usage link. */
export function LiveInventoryDashboard() {
  const today = todayDisplayDayKey();
  const { hasPermission } = useAuth();
  const canManage = hasPermission('inventory:manage');
  const inventoryHref = canManage ? ROUTES.INVENTORY : undefined;

  const {
    data: items,
    isLoading: itemsLoading,
    isError: itemsError,
    error: itemsErr,
    refetch: refetchItems,
  } = useInventoryItems({ live: true });
  const { data: usageEntries } = useInventoryUsageEntries({
    startDate: today,
    endDate: today,
    pageSize: USAGE_PAGE_SIZE,
    isToday: true,
  });
  const { directReceipts, transfers } = useEmergencyStockFeed();

  const activeItems = useMemo(() => (items ?? []).filter((item) => item.is_active), [items]);
  const itemsById = useMemo(() => new Map((items ?? []).map((item) => [item.id, item])), [items]);

  const lowStockCount = activeItems.filter((item) => item.is_low_stock).length;
  const mainStockedCount = activeItems.filter((item) => Number(item.main_stock_level) > 0).length;
  const emergencyStockedCount = activeItems.filter(
    (item) => Number(item.emergency_stock_level) > 0,
  ).length;
  const mainBreakdown = breakdownByUnit(activeItems, (item) => item.main_stock_level);
  const emergencyBreakdown = breakdownByUnit(activeItems, (item) => item.emergency_stock_level);

  const usageByItem = useMemo(
    () => summarizeUsageByItem(usageEntries ?? [], items),
    [usageEntries, items],
  );
  const chartData = useMemo(
    () =>
      usageByItem.slice(0, CHART_ITEM_LIMIT).map((row) => ({
        itemId: row.itemId,
        name: truncate(row.name),
        fullName: row.name,
        qty: Number(row.total),
        unit: row.unit,
      })),
    [usageByItem],
  );

  const attentionRows = useMemo(() => {
    const sorted = [...activeItems].sort(
      (a, b) =>
        Number(b.is_low_stock) - Number(a.is_low_stock) ||
        Number(a.emergency_stock_level) - Number(b.emergency_stock_level) ||
        a.name.localeCompare(b.name),
    );
    return sorted
      .slice(0, ATTENTION_LIMIT)
      .map((item) => ({ item, tone: item.is_low_stock ? 'rose' : 'amber' }));
  }, [activeItems]);

  const groups = useMemo(() => groupUsageEntries(usageEntries ?? []), [usageEntries]);
  const feed = useMemo(
    () => buildEmergencyArrivalsFeed(directReceipts, transfers, { limit: ACTIVITY_LIMIT }),
    [directReceipts, transfers],
  );

  return (
    <div className="flex flex-col gap-6">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div className="flex flex-col gap-1">
          <h1 className="text-lg font-semibold text-foreground">Live Inventory</h1>
          <p className="text-sm text-muted-foreground">
            Main Stock, Emergency Stock, and today&apos;s usage at a glance.
          </p>
        </div>
        <span className="inline-flex items-center gap-1.5 rounded-full bg-emerald-500/10 px-2.5 py-1 text-xs font-medium text-emerald-700">
          <span className="h-2 w-2 rounded-full bg-emerald-500 animate-pulse" aria-hidden="true" />
          Auto-refreshing every 15s
        </span>
      </div>

      {itemsLoading ? (
        <PageLoader label="Loading inventory" />
      ) : itemsError ? (
        <PageError
          error={itemsErr}
          reset={refetchItems}
          message="Couldn't load the item catalog."
        />
      ) : (
        <>
          <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 xl:grid-cols-4">
            <StatCard
              icon={Boxes}
              tone="primary"
              label="Active Items"
              value={activeItems.length}
              sub={`${items?.length ?? 0} total in catalog`}
              detailsHref={inventoryHref}
              pill={
                <StatusPill tone="emerald" icon={Activity}>
                  Live · 15s
                </StatusPill>
              }
            />
            <StatCard
              icon={Warehouse}
              tone="primary"
              label="Main Stock"
              value={mainStockedCount}
              sub={mainBreakdown || 'None recorded'}
              detailsHref={inventoryHref}
              pill={
                <StatusPill tone="emerald" icon={Check}>
                  {mainStockedCount === 1 ? 'Item' : 'Items'} stocked
                </StatusPill>
              }
            />
            <StatCard
              icon={Siren}
              tone="amber"
              label="Emergency Stock"
              value={emergencyStockedCount}
              sub={emergencyBreakdown || 'None recorded'}
              detailsHref={inventoryHref}
              pill={
                lowStockCount > 0 ? (
                  <StatusPill tone="amber" icon={TrendingDown}>
                    {lowStockCount} running low
                  </StatusPill>
                ) : (
                  <StatusPill tone="emerald" icon={Check}>
                    All above threshold
                  </StatusPill>
                )
              }
            />
            <StatCard
              icon={AlertTriangle}
              tone={lowStockCount > 0 ? 'rose' : 'emerald'}
              label="Low-Stock Items"
              value={lowStockCount}
              sub={lowStockCount > 0 ? 'in Emergency Stock' : 'nothing below threshold'}
              detailsHref={inventoryHref}
              pill={
                lowStockCount > 0 ? (
                  <StatusPill tone="rose" icon={TrendingDown}>
                    Action needed
                  </StatusPill>
                ) : (
                  <StatusPill tone="emerald" icon={Check}>
                    All OK
                  </StatusPill>
                )
              }
            />
          </div>

          <div className="grid grid-cols-1 gap-4 lg:grid-cols-3">
            <div className="lg:col-span-2">
              <UsageChartPanel chartData={chartData} />
            </div>
            <AttentionPanel rows={attentionRows} />
          </div>

          <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
            <RecentActivityPanel feed={feed} itemsById={itemsById} />
            <UsageLogPanel
              groups={groups}
              items={items}
              submissionCount={groups.length}
              itemCount={usageByItem.length}
            />
          </div>
        </>
      )}
    </div>
  );
}
