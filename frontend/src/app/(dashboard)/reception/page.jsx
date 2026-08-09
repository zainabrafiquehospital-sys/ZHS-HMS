'use client';

import { useState } from 'react';
import { RegisterVisitForm } from '@/features/reception/components/RegisterVisitForm';
import { RegistrationSummary } from '@/features/reception/components/RegistrationSummary';
import { TodaysRegistrations } from '@/features/reception/components/TodaysRegistrations';
import { ShiftBadge } from '@/shared/components/ShiftBadge';

export default function ReceptionPage() {
  const [lastResult, setLastResult] = useState(null);

  return (
    <div className="flex flex-col gap-6">
      <div className="flex items-start justify-between gap-3">
        <div>
          <h1 className="text-lg font-semibold text-foreground">Reception</h1>
          <p className="text-sm text-muted-foreground">
            Register a new or returning patient and route them into the queue.
          </p>
        </div>
        <ShiftBadge />
      </div>
      <div className="grid grid-cols-1 gap-6 lg:grid-cols-3">
        <div className="lg:col-span-2">
          <RegisterVisitForm onRegistered={setLastResult} />
        </div>
        <div>
          <RegistrationSummary result={lastResult} />
        </div>
      </div>
      <TodaysRegistrations />
    </div>
  );
}
