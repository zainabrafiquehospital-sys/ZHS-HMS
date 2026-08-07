'use client';

import { useState } from 'react';
import { CheckCircle2, Printer } from 'lucide-react';
import { usePrintRegistrationSlip } from '@/features/reception/hooks/useReception';
import { Card, CardContent, CardHeader, CardTitle } from '@/shared/components/ui/Card';
import { Badge } from '@/shared/components/ui/Badge';
import { Button } from '@/shared/components/ui/Button';

export function RegistrationSummary({ result }) {
  const printSlip = usePrintRegistrationSlip();
  const [printError, setPrintError] = useState(null);
  if (!result) return null;
  const { patient, visit, queue_entry: queueEntry } = result;

  async function handlePrint() {
    setPrintError(null);
    try {
      await printSlip.mutateAsync(visit.id);
    } catch (error) {
      // A failed/cancelled print never affects the already-successful
      // registration — the receptionist can just click Print Slip again.
      setPrintError(error.message || 'Unable to print — you can try again.');
    }
  }

  return (
    <Card className="border-emerald-600/40 bg-emerald-600/5">
      <CardHeader>
        <CardTitle className="flex items-center gap-2 text-emerald-700">
          <CheckCircle2 className="h-4 w-4" />
          Visit Registered
        </CardTitle>
      </CardHeader>
      <CardContent className="flex flex-col gap-2 text-sm">
        <div className="flex justify-between">
          <span className="text-muted-foreground">Patient</span>
          <span className="font-medium text-foreground">
            {patient.full_name} ({patient.mr_number})
          </span>
        </div>
        <div className="flex justify-between">
          <span className="text-muted-foreground">Queue Token</span>
          <span className="font-mono font-semibold text-foreground">{visit.queue_token}</span>
        </div>
        <div className="flex justify-between">
          <span className="text-muted-foreground">Routed To</span>
          <Badge variant="secondary" className="capitalize">
            {queueEntry.destination}
          </Badge>
        </div>
        <div className="flex justify-between">
          <span className="text-muted-foreground">Doctor</span>
          {visit.doctor_user_id ? (
            <Badge variant="success">Assigned</Badge>
          ) : (
            <Badge variant="warning">Will be assigned upon availability</Badge>
          )}
        </div>

        {printError ? <p className="text-xs text-destructive">{printError}</p> : null}

        <Button
          type="button"
          onClick={handlePrint}
          disabled={printSlip.isPending}
          className="mt-2 w-full sm:w-auto"
        >
          <Printer className="h-4 w-4" />
          Print Slip
        </Button>
      </CardContent>
    </Card>
  );
}
