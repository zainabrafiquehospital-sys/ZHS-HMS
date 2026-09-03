'use client';

import { useState } from 'react';
import { DoctorQueueList } from '@/features/consultation/components/DoctorQueueList';
import { MyConsultations } from '@/features/consultation/components/MyConsultations';
import { Tabs } from '@/shared/components/ui/Tabs';

const DOCTOR_TABS = [
  { value: 'queue', label: 'Queue' },
  { value: 'my_consultations', label: 'My Consultations' },
];

/** The Doctor's landing screen, extended (2026-09-03) with a "My
 * Consultations" tab — a searchable, paginated record of every
 * consultation this doctor has completed, with a read-only full-record
 * dialog and on-demand prescription reprint. "Queue" stays the default/
 * first tab so nothing changes for the existing patient-queue flow.
 * Same top-level Tabs shape as features/vitals' own page. */
export default function DoctorPage() {
  const [activeTab, setActiveTab] = useState('queue');

  return (
    <div className="flex flex-col gap-6">
      <div>
        <h1 className="text-lg font-semibold text-foreground">Doctor</h1>
        <p className="text-sm text-muted-foreground">
          {activeTab === 'queue'
            ? 'Patients currently waiting for you.'
            : 'Every consultation you have completed.'}
        </p>
      </div>

      <Tabs value={activeTab} onValueChange={setActiveTab} tabs={DOCTOR_TABS} />

      {activeTab === 'queue' ? <DoctorQueueList /> : <MyConsultations />}
    </div>
  );
}
