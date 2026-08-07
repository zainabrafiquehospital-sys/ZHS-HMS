import { BillingWorkspace } from '@/features/billing/components/BillingWorkspace';

export default async function BillingWorkspacePage({ params }) {
  const { visitId } = await params;
  return <BillingWorkspace visitId={visitId} />;
}
