'use client';

import { useState } from 'react';
import { VitalsWorklist } from '@/features/vitals/components/VitalsWorklist';
import { RecordInventoryUsageForm } from '@/features/vitals/components/RecordInventoryUsageForm';
import { RaiseRestockRequestForm } from '@/features/vitals/components/RaiseRestockRequestForm';
import { PrintDailyUsageSlip } from '@/features/vitals/components/PrintDailyUsageSlip';
import { PrintDailySummary } from '@/features/vitals/components/PrintDailySummary';
import { ShiftBadge } from '@/shared/components/ShiftBadge';
import { Tabs } from '@/shared/components/ui/Tabs';

const VITALS_TABS = [
  { value: 'worklist', label: 'Worklist' },
  { value: 'record_usage', label: 'Record Usage' },
  { value: 'raise_restock_request', label: 'Raise Restock Request' },
];

/** Vitals' existing worklist screen, extended (step 4) with two new
 * tabs for its own two Ward/Emergency Inventory actions — recording a
 * usage entry against Emergency Stock and raising a restock request.
 * "Worklist" stays the default/first tab so nothing about the existing
 * vitals-recording flow changes for anyone who never touches the new
 * tabs. */
export default function VitalsPage() {
  const [activeTab, setActiveTab] = useState('worklist');

  return (
    <div className="flex flex-col gap-6">
      <div className="flex items-start justify-between gap-3">
        <div>
          <h1 className="text-lg font-semibold text-foreground">Vitals</h1>
          <p className="text-sm text-muted-foreground">Patients currently waiting for vitals.</p>
        </div>
        <ShiftBadge />
      </div>

      <Tabs value={activeTab} onValueChange={setActiveTab} tabs={VITALS_TABS} />

      {activeTab === 'worklist' ? (
        <VitalsWorklist />
      ) : activeTab === 'record_usage' ? (
        <div className="flex flex-col gap-6">
          <PrintDailyUsageSlip />
          <PrintDailySummary />
          <RecordInventoryUsageForm />
        </div>
      ) : (
        <RaiseRestockRequestForm />
      )}
    </div>
  );
}
