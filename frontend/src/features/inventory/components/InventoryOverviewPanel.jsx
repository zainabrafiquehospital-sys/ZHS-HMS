'use client';

import { useMemo, useState } from 'react';
import { Boxes, Droplet, Pill, Search, Siren, Syringe, Wrench } from 'lucide-react';
import { useInventoryItems } from '@/features/inventory/hooks/useInventory';
import { INVENTORY_CATEGORIES } from '@/features/inventory/schemas/inventorySchemas';
import { Card, CardContent, CardHeader, CardTitle } from '@/shared/components/ui/Card';
import { Badge } from '@/shared/components/ui/Badge';
import { Input } from '@/shared/components/ui/Input';
import { PageLoader } from '@/shared/components/PageLoader';
import { PageError } from '@/shared/components/PageError';
import { useDebouncedValue } from '@/shared/hooks/useDebouncedValue';

// Covers inventorySchemas.js's INVENTORY_CATEGORIES exactly — no
// category icons existed anywhere in this app before this screen
// (Catalog's own category column is plain capitalized text), chosen
// fresh from the lucide-react set this app already uses everywhere else.
const CATEGORY_ICONS = {
  medicine: Pill,
  injection: Syringe,
  drip: Droplet,
  equipment: Wrench,
};

// Mirrors CATEGORY_ALLOWED_UNITS's full set of units, flattened — fixed
// display order so the per-unit breakdown line reads the same way every
// time rather than shuffling with whatever order a Map happens to
// iterate in.
const UNIT_DISPLAY_ORDER = ['piece', 'bottle', 'box', 'vial', 'ampoule', 'ml'];

function formatQuantity(value) {
  const num = Number(value);
  if (!Number.isFinite(num)) return '0';
  return Number.isInteger(num) ? String(num) : num.toFixed(2).replace(/\.?0+$/, '');
}

function unitLabel(unit, quantity) {
  // "ml" has no plural form; every other unit here is a countable noun.
  if (unit === 'ml') return 'ml';
  return quantity === 1 ? unit : `${unit}s`;
}

/** Sums `pick(item)` per distinct `unit` across `items` — the confirmed
 * "Total Inventory"/"Total Emergency Inventory" aggregation approach:
 * the catalog's units are genuinely incompatible (piece/bottle/box/vial/
 * ampoule/ml, and not even uniform within one category — see
 * CATEGORY_ALLOWED_UNITS), so a single raw cross-unit sum would be
 * meaningless. This groups by unit instead, so every number shown is a
 * real, addable quantity. Returns display strings already formatted,
 * e.g. `["180 pieces", "40 bottles"]`; zero-quantity units are omitted. */
function summarizeByUnit(items, pick) {
  const totals = new Map();
  for (const item of items) {
    const amount = Number(pick(item)) || 0;
    totals.set(item.unit, (totals.get(item.unit) ?? 0) + amount);
  }
  return UNIT_DISPLAY_ORDER.filter((unit) => (totals.get(unit) ?? 0) > 0).map((unit) => {
    const quantity = totals.get(unit);
    return `${formatQuantity(quantity)} ${unitLabel(unit, quantity)}`;
  });
}

/** Same visual shape as features/admin/components/AdminOverview.jsx's
 * own `SummaryTile` (icon-in-a-circle + label + bold number) for visual
 * consistency with the rest of the app, extended with an optional
 * secondary per-unit breakdown line beneath the headline number. */
function OverviewStatTile({ icon: Icon, label, value, breakdown }) {
  return (
    <div className="flex items-center gap-3 rounded-md border border-border bg-muted/30 p-4">
      <div className="flex h-9 w-9 shrink-0 items-center justify-center rounded-full bg-primary/10 text-primary">
        <Icon className="h-4 w-4" />
      </div>
      <div className="flex flex-col">
        <span className="text-xs text-muted-foreground">{label}</span>
        <span className="text-xl font-semibold tabular-nums text-foreground">{value}</span>
        {breakdown ? <span className="text-xs text-muted-foreground">{breakdown}</span> : null}
      </div>
    </div>
  );
}

/** Groups `items` by category, fixed in `INVENTORY_CATEGORIES`'s own
 * order (Medicine/Injection/Drip/Equipment) rather than whatever order
 * they happen to arrive in — a category with no active items is simply
 * omitted, never shown as an empty section. */
function groupByCategory(items) {
  const byCategory = new Map(INVENTORY_CATEGORIES.map((category) => [category, []]));
  for (const item of items) {
    if (!byCategory.has(item.category)) byCategory.set(item.category, []);
    byCategory.get(item.category).push(item);
  }
  return INVENTORY_CATEGORIES.map((category) => ({
    category,
    items: byCategory.get(category) ?? [],
  })).filter((group) => group.items.length > 0);
}

function ItemCard({ item }) {
  const Icon = CATEGORY_ICONS[item.category] ?? Boxes;
  return (
    <div className="flex items-start gap-3 rounded-md border border-border bg-card p-4">
      <div className="flex h-10 w-10 shrink-0 items-center justify-center rounded-full bg-primary/10 text-primary">
        <Icon className="h-5 w-5" />
      </div>
      <div className="flex flex-1 flex-col gap-1.5">
        <div className="flex flex-wrap items-center justify-between gap-2">
          <span className="font-medium text-foreground">{item.name}</span>
          {item.is_low_stock ? <Badge variant="destructive">Low</Badge> : null}
        </div>
        <p className="text-xs capitalize text-muted-foreground">{item.category}</p>
        <div className="flex items-center gap-4 text-sm">
          <span className="text-muted-foreground">
            Main:{' '}
            <span className="font-medium tabular-nums text-foreground">
              {item.main_stock_level}
            </span>{' '}
            {item.unit}
          </span>
          <span className="text-muted-foreground">
            Emergency:{' '}
            <span className="font-medium tabular-nums text-foreground">
              {item.emergency_stock_level}
            </span>{' '}
            {item.unit}
          </span>
        </div>
      </div>
    </div>
  );
}

/** The Inventory Manager's new default landing view (2026-08-27
 * addition) — a live, at-a-glance overview distinct from Catalog's own
 * CRUD/management table. "Total Inventory"/"Total Emergency Inventory"
 * are each an *item count*, not a raw quantity sum (see summarizeByUnit's
 * docstring for why a sum across incompatible units would be
 * meaningless) — a real per-unit quantity breakdown still shows under
 * each tile, so no quantity visibility is lost. Item cards below the two
 * tiles are grouped into a section per category (2026-08-28 addition,
 * groupByCategory) — the two headline tiles stay ungrouped totals across
 * the whole catalog, this grouping is purely about how the cards
 * themselves are laid out. */
export function InventoryOverviewPanel() {
  const { data: items, isLoading, isError, error, refetch } = useInventoryItems();
  const [searchTerm, setSearchTerm] = useState('');
  const debouncedSearch = useDebouncedValue(searchTerm, 200);

  const activeItems = useMemo(() => (items ?? []).filter((item) => item.is_active), [items]);

  // Name/category filter — applies only to the item cards below, never
  // to the two headline tiles (those stay whole-catalog totals by
  // design, see this component's own docstring).
  const visibleItems = useMemo(() => {
    const term = debouncedSearch.trim().toLowerCase();
    if (!term) return activeItems;
    return activeItems.filter(
      (item) =>
        item.name.toLowerCase().includes(term) || item.category.toLowerCase().includes(term),
    );
  }, [activeItems, debouncedSearch]);

  if (isLoading) return <PageLoader label="Loading inventory" />;
  if (isError) {
    return <PageError error={error} reset={refetch} message="Couldn't load the item catalog." />;
  }

  const emergencyStockedItems = activeItems.filter(
    (item) => Number(item.emergency_stock_level) > 0,
  );

  const totalBreakdown = summarizeByUnit(
    activeItems,
    (item) => Number(item.main_stock_level) + Number(item.emergency_stock_level),
  ).join(' · ');
  const emergencyBreakdown = summarizeByUnit(
    activeItems,
    (item) => item.emergency_stock_level,
  ).join(' · ');

  return (
    <div className="flex flex-col gap-6">
      <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
        <OverviewStatTile
          icon={Boxes}
          label="Total Inventory"
          value={`${activeItems.length} Active Item${activeItems.length === 1 ? '' : 's'}`}
          breakdown={totalBreakdown || 'No stock recorded yet.'}
        />
        <OverviewStatTile
          icon={Siren}
          label="Total Emergency Inventory"
          value={`${emergencyStockedItems.length} Item${emergencyStockedItems.length === 1 ? '' : 's'} Stocked`}
          breakdown={emergencyBreakdown || 'No emergency stock recorded yet.'}
        />
      </div>

      <Card>
        <CardHeader>
          <div className="flex flex-col gap-4 sm:flex-row sm:items-center sm:justify-between">
            <CardTitle>Items</CardTitle>
            <div className="relative w-full sm:w-64">
              <Search className="pointer-events-none absolute left-2.5 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground" />
              <Input
                value={searchTerm}
                onChange={(event) => setSearchTerm(event.target.value)}
                placeholder="Search by name or category…"
                className="pl-8"
              />
            </div>
          </div>
        </CardHeader>
        <CardContent className="flex flex-col gap-6">
          {activeItems.length === 0 ? (
            <p className="text-sm text-muted-foreground">
              No active items in the catalog yet — add one under Catalog first.
            </p>
          ) : visibleItems.length === 0 ? (
            <p className="text-sm text-muted-foreground">
              No items match &quot;{debouncedSearch}&quot;.
            </p>
          ) : (
            groupByCategory(visibleItems).map(({ category, items: categoryItems }) => {
              const Icon = CATEGORY_ICONS[category] ?? Boxes;
              return (
                <div key={category} className="flex flex-col gap-3">
                  <div className="flex items-center gap-2 border-b border-border pb-2">
                    <Icon className="h-4 w-4 text-primary" />
                    <h3 className="text-sm font-semibold capitalize text-foreground">{category}</h3>
                    <span className="text-xs text-muted-foreground">({categoryItems.length})</span>
                  </div>
                  <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-3">
                    {categoryItems.map((item) => (
                      <ItemCard key={item.id} item={item} />
                    ))}
                  </div>
                </div>
              );
            })
          )}
        </CardContent>
      </Card>
    </div>
  );
}
