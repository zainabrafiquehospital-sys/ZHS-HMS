'use client';

import { useState } from 'react';
import { Printer } from 'lucide-react';
import { usePrintDailySummary } from '@/features/vitals/hooks/useVitals';
import { Card, CardContent, CardHeader, CardTitle } from '@/shared/components/ui/Card';
import { Button } from '@/shared/components/ui/Button';
import { Input } from '@/shared/components/ui/Input';
import { Label } from '@/shared/components/ui/Label';
import { todayDisplayDayKey } from '@/utils/timezone';

/** Step 5's combined daily PDF — Inventory Items Used + Vitals
 * Recorded, one document, always the calling Vitals staff member's own
 * day — same date-picker/print-button shape and actor-scoping
 * PrintDailyUsageSlip.jsx already established, rendered alongside it
 * (not replacing it): that one stays the Inventory-only slip; this one
 * is the additive combined view. */
export function PrintDailySummary() {
  const [date, setDate] = useState(todayDisplayDayKey());
  const printSummary = usePrintDailySummary();
  const [error, setError] = useState(null);

  async function handlePrint() {
    setError(null);
    try {
      await printSummary.mutateAsync(date);
    } catch (err) {
      setError(err.message || 'Unable to print this daily summary.');
    }
  }

  return (
    <Card>
      <CardHeader>
        <CardTitle>Daily Summary (Usage + Vitals)</CardTitle>
      </CardHeader>
      <CardContent className="flex flex-wrap items-end gap-3">
        <div className="flex flex-col gap-1.5">
          <Label htmlFor="daily-summary-date">Date</Label>
          <Input
            id="daily-summary-date"
            type="date"
            max={todayDisplayDayKey()}
            value={date}
            onChange={(event) => setDate(event.target.value)}
            className="w-auto"
          />
        </div>
        <Button variant="outline" onClick={handlePrint} disabled={printSummary.isPending}>
          <Printer className="h-4 w-4" />
          {printSummary.isPending ? 'Preparing…' : 'Print Daily Summary'}
        </Button>
        {error ? <p className="w-full text-sm text-destructive">{error}</p> : null}
      </CardContent>
    </Card>
  );
}
