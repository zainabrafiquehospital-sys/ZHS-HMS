import { DashboardOverview } from '@/features/dashboard/components/DashboardOverview';

export default function DashboardHomePage() {
  return (
    <div className="flex flex-col gap-6">
      <div>
        <h1 className="text-lg font-semibold text-foreground">Dashboard</h1>
        <p className="text-sm text-muted-foreground">A live snapshot of today&apos;s OPD activity.</p>
      </div>
      <DashboardOverview />
    </div>
  );
}
