import { VitalsWorklist } from '@/features/vitals/components/VitalsWorklist';
import { ShiftBadge } from '@/shared/components/ShiftBadge';

export default function VitalsPage() {
  return (
    <div className="flex flex-col gap-6">
      <div className="flex items-start justify-between gap-3">
        <div>
          <h1 className="text-lg font-semibold text-foreground">Vitals</h1>
          <p className="text-sm text-muted-foreground">Patients currently waiting for vitals.</p>
        </div>
        <ShiftBadge />
      </div>
      <VitalsWorklist />
    </div>
  );
}
