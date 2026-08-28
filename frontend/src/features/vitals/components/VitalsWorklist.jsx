'use client';

import { useRouter } from 'next/navigation';
import { HeartPulse } from 'lucide-react';
import { useVitalsWorklist, useVisitsByIds, usePatientsForVisits } from '@/features/vitals/hooks/useVitals';
import { Card, CardContent, CardHeader, CardTitle } from '@/shared/components/ui/Card';
import { Button } from '@/shared/components/ui/Button';
import { Badge } from '@/shared/components/ui/Badge';
import { PageLoader } from '@/shared/components/PageLoader';

/** One patient's card in the "Waiting for Vitals" worklist (2026-08-28
 * card-layout redesign, scoped to this screen only — see this file's
 * own git history for the plain-table shape this replaces). Reuses the
 * exact card shape InventoryOverviewPanel.jsx's own `ItemCard` already
 * established for this app (icon circle in `bg-primary/10 text-primary`,
 * `border-border`/`bg-card`, same padding/radius) rather than inventing
 * a new visual language — every field/action the old table row carried
 * is still here, just laid out as a card instead of a row. */
function WorklistCard({ entry, visit, patient, isLoadingVisits, onRecordVitals }) {
  return (
    <div className="flex items-start gap-3 rounded-md border border-border bg-card p-4">
      <div className="flex h-10 w-10 shrink-0 items-center justify-center rounded-full bg-primary/10 text-primary">
        <HeartPulse className="h-5 w-5" />
      </div>
      <div className="flex flex-1 flex-col gap-2">
        <div className="flex flex-wrap items-start justify-between gap-x-3 gap-y-1">
          <div className="flex flex-col">
            <span className="font-medium text-foreground">
              {patient ? patient.full_name : '…'}
            </span>
            <span className="text-xs text-muted-foreground">
              {patient ? `MR: ${patient.mr_number}` : ''}
            </span>
          </div>
          <span className="whitespace-nowrap font-mono text-xs text-muted-foreground">
            {visit ? visit.queue_token : isLoadingVisits ? '…' : '—'}
          </span>
        </div>
        {entry.reason ? (
          <p className="text-xs text-muted-foreground">{entry.reason}</p>
        ) : (
          <div>
            <Badge variant="outline">Intake</Badge>
          </div>
        )}
        <Button size="sm" onClick={onRecordVitals} className="mt-1 w-full sm:w-auto">
          Record Vitals
        </Button>
      </div>
    </div>
  );
}

export function VitalsWorklist() {
  const router = useRouter();
  const { data: entries, isLoading: isLoadingWorklist } = useVitalsWorklist();
  const visitIds = (entries ?? []).map((entry) => entry.visit_id);
  const { visitsById, isLoading: isLoadingVisits } = useVisitsByIds(visitIds);
  const visits = visitIds.map((id) => visitsById[id]).filter(Boolean);
  const patientsById = usePatientsForVisits(visits);

  if (isLoadingWorklist) return <PageLoader label="Loading vitals worklist" />;

  return (
    <Card>
      <CardHeader>
        <CardTitle>Waiting for Vitals ({(entries ?? []).length})</CardTitle>
      </CardHeader>
      <CardContent>
        {(entries ?? []).length === 0 ? (
          <p className="py-6 text-center text-sm text-muted-foreground">
            No patients currently waiting for vitals.
          </p>
        ) : (
          <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-3">
            {entries.map((entry) => {
              const visit = visitsById[entry.visit_id];
              const patient = visit ? patientsById[visit.patient_id] : undefined;
              return (
                <WorklistCard
                  key={entry.id}
                  entry={entry}
                  visit={visit}
                  patient={patient}
                  isLoadingVisits={isLoadingVisits}
                  onRecordVitals={() => router.push(`/vitals/${entry.visit_id}`)}
                />
              );
            })}
          </div>
        )}
      </CardContent>
    </Card>
  );
}
