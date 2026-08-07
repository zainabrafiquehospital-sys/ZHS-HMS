import { RecordVitalsForm } from '@/features/vitals/components/RecordVitalsForm';

export default async function RecordVitalsPage({ params }) {
  const { visitId } = await params;
  return (
    <div className="flex flex-col gap-6">
      <div>
        <h1 className="text-lg font-semibold text-foreground">Record Vitals</h1>
        <p className="text-sm text-muted-foreground">
          Recording vitals routes the patient back to the queue automatically.
        </p>
      </div>
      <RecordVitalsForm visitId={visitId} />
    </div>
  );
}
