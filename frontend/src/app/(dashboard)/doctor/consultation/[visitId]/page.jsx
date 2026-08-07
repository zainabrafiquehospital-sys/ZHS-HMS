import { ConsultationPanel } from '@/features/consultation/components/ConsultationPanel';

export default async function ConsultationPage({ params }) {
  const { visitId } = await params;
  return (
    <div className="mx-auto flex max-w-2xl flex-col gap-6">
      <div>
        <h1 className="text-lg font-semibold text-foreground">Consultation</h1>
      </div>
      <ConsultationPanel visitId={visitId} />
    </div>
  );
}
