import { MedicineBillingWorkspace } from '@/features/pharmacy/components/MedicineBillingWorkspace';
import { MyMedicineBills } from '@/features/pharmacy/components/MyMedicineBills';

export default function PharmacyPage() {
  return (
    <div className="flex flex-col gap-6">
      <MedicineBillingWorkspace />
      <MyMedicineBills />
    </div>
  );
}
