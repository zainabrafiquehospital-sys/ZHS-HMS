'use client';

import { useMemo } from 'react';
import { ArrowDownToLine, ArrowRightLeft, Siren } from 'lucide-react';
import {
  useEmergencyStockFeed,
  useInventoryItems,
} from '@/features/inventory/hooks/useInventory';
import {
  ARRIVAL_SOURCE,
  ARRIVAL_SOURCE_LABEL,
  buildEmergencyArrivalsFeed,
  DEFAULT_FEED_LIMIT,
} from '@/features/inventory/utils/emergencyArrivalsFeed';
import { Card, CardContent, CardHeader, CardTitle } from '@/shared/components/ui/Card';
import { Badge } from '@/shared/components/ui/Badge';
import { PageLoader } from '@/shared/components/PageLoader';
import { PageError } from '@/shared/components/PageError';
import {
  displayDayKey,
  formatDisplayDate,
  formatDisplayTime,
  todayDisplayDayKey,
} from '@/utils/timezone';

// Trailing-zero trim, same presentation as InventoryOverviewPanel's own
// formatQuantity (kept local — that one isn't exported, and this is a
// one-liner).
function formatQty(value) {
  const num = Number(value);
  if (!Number.isFinite(num)) return String(value ?? '0');
  return Number.isInteger(num) ? String(num) : num.toFixed(2).replace(/\.?0+$/, '');
}

const SOURCE_ICON = {
  [ARRIVAL_SOURCE.DIRECT]: ArrowDownToLine,
  [ARRIVAL_SOURCE.TRANSFER]: ArrowRightLeft,
};

const SOURCE_BADGE_VARIANT = {
  [ARRIVAL_SOURCE.DIRECT]: 'secondary',
  [ARRIVAL_SOURCE.TRANSFER]: 'outline',
};

function FeedRow({ entry, itemsById }) {
  const item = itemsById.get(entry.item_id);
  const Icon = SOURCE_ICON[entry.source] ?? ArrowDownToLine;
  return (
    <li className="flex items-start gap-3 rounded-md border border-border bg-card p-4">
      <div className="flex h-9 w-9 shrink-0 items-center justify-center rounded-full bg-primary/10 text-primary">
        <Icon className="h-4 w-4" />
      </div>
      <div className="flex flex-1 flex-col gap-1">
        <div className="flex flex-wrap items-center justify-between gap-2">
          <span className="font-medium text-foreground">
            <span className="tabular-nums">{formatQty(entry.quantity)}</span>{' '}
            {item?.unit ?? ''} · {item?.name ?? 'Unknown item'}
          </span>
          <Badge variant={SOURCE_BADGE_VARIANT[entry.source] ?? 'outline'} className="shrink-0">
            {ARRIVAL_SOURCE_LABEL[entry.source]}
          </Badge>
        </div>
        <p className="text-xs text-muted-foreground">
          Added by {entry.created_by_display_name ?? '—'} ·{' '}
          {formatDisplayDate(displayDayKey(entry.created_at))} at{' '}
          {formatDisplayTime(entry.created_at)}
          {entry.source === ARRIVAL_SOURCE.TRANSFER && entry.carried_by_name
            ? ` · carried by ${entry.carried_by_name}`
            : ''}
        </p>
      </div>
    </li>
  );
}

/** Emergency Stock — Live Feed: a single chronological activity feed of
 * every item arriving into Emergency Stock, from BOTH the one-step
 * direct-to-Emergency receipt path and Main-Stock -> Emergency
 * transfers, most recent first. Its own dedicated Inventory tab (and a
 * matching Admin Overview sub-tab), additive alongside — never a
 * replacement for — InventoryHistoryPanel's searchable/printable
 * per-type history.
 *
 * Auto-refreshes on the app's established 15s + `refetchIntervalInBackground`
 * convention (see `useEmergencyStockFeed`). The two ledgers are merged,
 * source-tagged, and sorted client-side by `buildEmergencyArrivalsFeed`;
 * "who added it" is `created_by_display_name`, resolved server-side the
 * same way the Daily Usage view already resolves its "Recorded By"
 * column (an `inventory:read` holder like the Inventory Manager has no
 * `users:read` to resolve it itself). Visual language — Card / Badge /
 * icon-in-a-circle / bordered rows — matches InventoryOverviewPanel. */
export function InventoryEmergencyFeedPanel() {
  const { data: items } = useInventoryItems();
  const { directReceipts, transfers, isLoading, isError, error, refetch } = useEmergencyStockFeed({
    pageSize: DEFAULT_FEED_LIMIT,
  });

  const itemsById = useMemo(
    () => new Map((items ?? []).map((item) => [item.id, item])),
    [items],
  );

  const feed = useMemo(
    () => buildEmergencyArrivalsFeed(directReceipts, transfers, { limit: DEFAULT_FEED_LIMIT }),
    [directReceipts, transfers],
  );

  const todayKey = todayDisplayDayKey();
  const addedTodayCount = feed.filter((entry) => displayDayKey(entry.created_at) === todayKey).length;

  return (
    <Card>
      <CardHeader className="flex flex-col gap-2">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <CardTitle className="flex items-center gap-2">
            <Siren className="h-4 w-4 text-primary" />
            Emergency Stock — Live Feed
          </CardTitle>
          <span className="inline-flex items-center gap-1.5 text-xs text-muted-foreground">
            <span className="h-2 w-2 rounded-full bg-emerald-500 animate-pulse" aria-hidden="true" />
            Auto-refreshing every 15s
          </span>
        </div>
        <p className="text-sm text-muted-foreground">
          Every item arriving into Emergency Stock — direct receipts and transfers from Main Stock,
          newest first.
          {feed.length > 0 ? (
            <>
              {' '}
              <span className="font-medium text-foreground">
                {addedTodayCount} arrival{addedTodayCount === 1 ? '' : 's'} today
              </span>
              .
            </>
          ) : null}
        </p>
      </CardHeader>
      <CardContent>
        {isLoading ? (
          <PageLoader label="Loading Emergency Stock activity" />
        ) : isError ? (
          <PageError
            error={error}
            reset={refetch}
            message="Couldn't load the Emergency Stock feed."
          />
        ) : feed.length === 0 ? (
          <p className="py-10 text-center text-sm text-muted-foreground">
            No stock has arrived into Emergency Stock yet.
          </p>
        ) : (
          <ul className="flex flex-col gap-3">
            {feed.map((entry) => (
              <FeedRow key={`${entry.source}-${entry.id}`} entry={entry} itemsById={itemsById} />
            ))}
          </ul>
        )}
      </CardContent>
    </Card>
  );
}
