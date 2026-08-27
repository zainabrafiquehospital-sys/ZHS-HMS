import { LabBillingWorkspace } from '@/features/lab/components/LabBillingWorkspace';
import { MyLabBills } from '@/features/lab/components/MyLabBills';

export default function LaboratoryPage() {
  return (
    <div className="flex flex-col gap-6">
      <LabBillingWorkspace />
      <MyLabBills />
    </div>
  );
}
