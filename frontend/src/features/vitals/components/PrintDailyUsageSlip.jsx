'use client';

import { useState } from 'react';
import { Printer } from 'lucide-react';
import { usePrintDailyUsageSlip } from '@/features/inventory/hooks/useInventory';
import { Card, CardContent, CardHeader, CardTitle } from '@/shared/components/ui/Card';
import { Button } from '@/shared/components/ui/Button';
import { Input } from '@/shared/components/ui/Input';
import { Label } from '@/shared/components/ui/Label';
import { todayDisplayDayKey } from '@/utils/timezone';

/** "A daily usage slip/audit for Vitals — printable summary of
 * everything used that day and which patient it went to" (confirmed
 * design) — always the calling Vitals staff member's own day (see
 * backend/app/modules/inventory/router.py's print_my_daily_usage_slip
 * docstring: the exact same hard actor-scoping `GET /inventory/usage/
 * mine` already established), defaulting to today but pickable, for
 * printing yesterday's slip the next morning. */
export function PrintDailyUsageSlip() {
  const [date, setDate] = useState(todayDisplayDayKey());
  const printSlip = usePrintDailyUsageSlip();
  const [error, setError] = useState(null);

  async function handlePrint() {
    setError(null);
    try {
      await printSlip.mutateAsync(date);
    } catch (err) {
      setError(err.message || 'Unable to print this usage slip.');
    }
  }

  return (
    <Card>
      <CardHeader>
        <CardTitle>Daily Usage Slip</CardTitle>
      </CardHeader>
      <CardContent className="flex flex-wrap items-end gap-3">
        <div className="flex flex-col gap-1.5">
          <Label htmlFor="daily-usage-slip-date">Date</Label>
          <Input
            id="daily-usage-slip-date"
            type="date"
            max={todayDisplayDayKey()}
            value={date}
            onChange={(event) => setDate(event.target.value)}
            className="w-auto"
          />
        </div>
        <Button variant="outline" onClick={handlePrint} disabled={printSlip.isPending}>
          <Printer className="h-4 w-4" />
          {printSlip.isPending ? 'Preparing…' : 'Print Daily Usage Slip'}
        </Button>
        {error ? <p className="w-full text-sm text-destructive">{error}</p> : null}
      </CardContent>
    </Card>
  );
}
