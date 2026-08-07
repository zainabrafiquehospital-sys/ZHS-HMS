import { BillingWorklist } from '@/features/billing/components/BillingWorklist';

export default function BillingPage() {
  return (
    <div className="flex flex-col gap-6">
      <div>
        <h1 className="text-lg font-semibold text-foreground">Billing</h1>
        <p className="text-sm text-muted-foreground">Visits currently waiting for billing.</p>
      </div>
      <BillingWorklist />
    </div>
  );
}
