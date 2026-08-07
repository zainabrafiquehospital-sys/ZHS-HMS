'use client';

import { LayoutDashboard, Stethoscope, HeartPulse } from 'lucide-react';
import {
  useReceptionDashboard,
  useDoctorDashboard,
  useVitalsDashboard,
} from '@/features/dashboard/hooks/useDashboard';
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

function VitalsDashboardCard({ query }) {
  const { data, isLoading, isForbidden, isError } = query;
  if (isForbidden || isError) return null;

  return (
    <Card>
      <CardHeader className="flex-row items-center gap-2">
        <HeartPulse className="h-4 w-4 text-muted-foreground" />
        <CardTitle>Vitals</CardTitle>
      </CardHeader>
      <CardContent>
        {isLoading ? (
          <PageLoader label="Loading vitals summary" />
        ) : (
          <div className="grid grid-cols-2 gap-3">
            <StatTile label="Waiting for Vitals" value={data.waiting_count} />
          </div>
        )}
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
