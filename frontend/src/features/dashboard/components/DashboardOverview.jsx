'use client';

import { LayoutDashboard, Stethoscope, HeartPulse } from 'lucide-react';
import {
  useReceptionDashboard,
  useDoctorDashboard,
  useVitalsDashboard,
} from '@/features/dashboard/hooks/useDashboard';
import { useInventoryItems } from '@/features/inventory/hooks/useInventory';
import { Card, CardContent, CardHeader, CardTitle } from '@/shared/components/ui/Card';
import { Badge } from '@/shared/components/ui/Badge';
import { PageLoader } from '@/shared/components/PageLoader';

function StatTile({ label, value }) {
  return (
    <div className="flex flex-col gap-1 rounded-md border border-border p-4">
      <span className="text-xs text-muted-foreground">{label}</span>
      <span className="text-2xl font-semibold text-foreground">{value}</span>
    </div>
  );
}

function ReceptionDashboardCard({ query }) {
  const { data, isLoading, isForbidden, isError } = query;
  if (isForbidden || isError) return null;

  return (
    <Card>
      <CardHeader className="flex-row items-center gap-2">
        <LayoutDashboard className="h-4 w-4 text-muted-foreground" />
        <CardTitle>Reception</CardTitle>
      </CardHeader>
      <CardContent>
        {isLoading ? (
          <PageLoader label="Loading reception summary" />
        ) : (
          <div className="flex flex-col gap-5">
            <div className="grid grid-cols-2 gap-3 sm:grid-cols-3">
              <StatTile label="Revenue Today" value={`Rs. ${Number(data.revenue_collected_today).toFixed(2)}`} />
              <StatTile label="Invoices Paid Today" value={data.invoices_paid_today} />
              <StatTile label="Open Invoices" value={data.open_invoices} />
            </div>
            <div>
              <p className="mb-2 text-xs font-medium text-muted-foreground">Visits by Status</p>
              <div className="flex flex-wrap gap-2">
                {Object.entries(data.visits_by_status).map(([status, count]) => (
                  <Badge key={status} variant="outline" className="capitalize">
                    {status.replaceAll('_', ' ')}: {count}
                  </Badge>
                ))}
              </div>
            </div>
            <div>
              <p className="mb-2 text-xs font-medium text-muted-foreground">Queue Waiting by Destination</p>
              <div className="flex flex-wrap gap-2">
                {Object.entries(data.queue_waiting_by_destination).map(([destination, count]) => (
                  <Badge key={destination} variant="secondary" className="capitalize">
                    {destination}: {count}
                  </Badge>
                ))}
              </div>
            </div>
          </div>
        )}
      </CardContent>
    </Card>
  );
}

function DoctorDashboardCard({ query }) {
  const { data, isLoading, isForbidden, isError } = query;
  if (isForbidden || isError) return null;

  return (
    <Card>
      <CardHeader className="flex-row items-center gap-2">
        <Stethoscope className="h-4 w-4 text-muted-foreground" />
        <CardTitle>My Queue</CardTitle>
      </CardHeader>
      <CardContent>
        {isLoading ? (
          <PageLoader label="Loading doctor summary" />
        ) : (
          <div className="grid grid-cols-2 gap-3">
            <StatTile label="Waiting for Me" value={data.waiting_count} />
            <StatTile label="In Consultation" value={data.in_consultation_count} />
          </div>
        )}
      </CardContent>
    </Card>
  );
}

// Deliberately minimal — name + live emergency_stock_level + unit only
// (confirmed design: no main stock, no thresholds, no actions), a
// smaller purpose-built card rather than reusing
// InventoryOverviewPanel.jsx's own `ItemCard` (which shows both stock
// levels plus a low-stock badge and category icon — more than this
// glanceable "what's available right now" tile needs). Same bordered-
// card visual language as that panel's cards, just denser, since each
// card here is only two short lines.
function EmergencyStockCard({ item }) {
  return (
    <div className="flex flex-col gap-0.5 rounded-md border border-border bg-card px-3 py-2">
      <span className="truncate text-xs font-medium text-foreground" title={item.name}>
        {item.name}
      </span>
      <span className="text-sm font-semibold tabular-nums text-foreground">
        {item.emergency_stock_level}{' '}
        <span className="text-xs font-normal text-muted-foreground">{item.unit}</span>
      </span>
    </div>
  );
}

/** A live, glanceable Emergency Stock overview (2026-09 addition) — one
 * small card per active InventoryItem, reusing the exact same
 * `inventory:read` permission Vitals already holds (see
 * app/modules/inventory/constants.py's own docstring) and the already-
 * cached `useInventoryItems()` query (no new backend endpoint). Quietly
 * hidden (not an error block) if the actor can't read inventory or the
 * fetch fails — the "Waiting for Vitals" stat above still shows either
 * way, since that's a separate, independent query. */
function EmergencyStockGrid() {
  // `useInventoryItems` is a plain query (no `isForbidden` derivation
  // the way this file's own dashboard-summary hooks have — see
  // useDashboard.js) — a 403 still lands as `isError` regardless, so
  // "hide the section" behavior is unaffected either way.
  const { data: items, isLoading, isError } = useInventoryItems();
  if (isError) return null;

  const activeItems = (items ?? []).filter((item) => item.is_active);

  return (
    <div className="flex flex-col gap-3 border-t border-border pt-4">
      <p className="text-xs font-medium text-muted-foreground">Emergency Stock</p>
      {isLoading ? (
        <PageLoader label="Loading emergency stock" />
      ) : activeItems.length === 0 ? (
        <p className="text-sm text-muted-foreground">No active items in the catalog yet.</p>
      ) : (
        <div className="grid grid-cols-2 gap-2 sm:grid-cols-3 lg:grid-cols-4">
          {activeItems.map((item) => (
            <EmergencyStockCard key={item.id} item={item} />
          ))}
        </div>
      )}
    </div>
  );
}

function VitalsDashboardCard({ query }) {
  const { data, isLoading, isForbidden, isError } = query;
  if (isForbidden || isError) return null;

  return (
    <Card>
      <CardHeader className="flex-row items-center gap-2">
        <HeartPulse className="h-4 w-4 text-muted-foreground" />
        <CardTitle>Vitals</CardTitle>
      </CardHeader>
      <CardContent className="flex flex-col gap-4">
        {isLoading ? (
          <PageLoader label="Loading vitals summary" />
        ) : (
          <div className="grid grid-cols-2 gap-3">
            <StatTile label="Waiting for Vitals" value={data.waiting_count} />
          </div>
        )}
        <EmergencyStockGrid />
      </CardContent>
    </Card>
  );
}

export function DashboardOverview() {
  const receptionQuery = useReceptionDashboard();
  const doctorQuery = useDoctorDashboard();
  const vitalsQuery = useVitalsDashboard();

  const nothingVisible = [receptionQuery, doctorQuery, vitalsQuery].every(
    (query) => (query.isForbidden || query.isError) && !query.isLoading,
  );

  if (nothingVisible) {
    return (
      <Card>
        <CardContent className="py-10 text-center text-sm text-muted-foreground">
          No dashboards are available for your role.
        </CardContent>
      </Card>
    );
  }

  return (
    <div className="grid grid-cols-1 gap-6 xl:grid-cols-2">
      <div className="xl:col-span-2">
        <ReceptionDashboardCard query={receptionQuery} />
      </div>
      <DoctorDashboardCard query={doctorQuery} />
      <VitalsDashboardCard query={vitalsQuery} />
    </div>
  );
}
