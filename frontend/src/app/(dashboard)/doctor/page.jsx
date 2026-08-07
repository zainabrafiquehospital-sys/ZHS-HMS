import { DoctorQueueList } from '@/features/consultation/components/DoctorQueueList';

export default function DoctorQueuePage() {
  return (
    <div className="flex flex-col gap-6">
      <div>
        <h1 className="text-lg font-semibold text-foreground">Doctor Queue</h1>
        <p className="text-sm text-muted-foreground">Patients currently waiting for you.</p>
      </div>
      <DoctorQueueList />
    </div>
  );
}
