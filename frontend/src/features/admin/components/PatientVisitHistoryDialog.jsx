'use client';

import { useState } from 'react';
import { Printer, X } from 'lucide-react';
import { usePatientVisitHistory } from '@/features/admin/hooks/usePatientDirectory';
import { usePrintRegistrationSlip } from '@/features/reception/hooks/useReception';
import { VisitProcedureDisplay } from '@/features/visits/components/VisitProcedureDisplay';
import { Card, CardContent, CardHeader, CardTitle } from '@/shared/components/ui/Card';
import { Button } from '@/shared/components/ui/Button';
import { Badge } from '@/shared/components/ui/Badge';
import { PageLoader } from '@/shared/components/PageLoader';
import { PageError } from '@/shared/components/PageError';
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from '@/shared/components/ui/Table';
import { formatDisplayDate, displayDayKey } from '@/utils/timezone';
import { VISIT_STATUS_BADGE_VARIANT } from '@/shared/constants/visitStatus';

const currencyFormatter = new Intl.NumberFormat('en-US', {
  minimumFractionDigits: 2,
  maximumFractionDigits: 2,
});

function formatPkr(amount) {
  return `PKR ${currencyFormatter.format(Number(amount))}`;
}

/** Read-only per-patient visit history + slip reprint — Admin viewing
 * and reprinting records that already exist, never creating or
 * modifying a Visit. Reprinting goes through `usePrintRegistrationSlip`
 * (features/reception/hooks/useReception.js) completely unmodified —
 * the exact same mutation/print pipeline Reception's own "Print Slip"
 * button uses (`receptionService.fetchRegistrationSlipHtml` ->
 * `render_registration_slip` -> `openAndPrintHtml`), so a reprint looks
 * identical to the original. Same fixed-overlay Card pattern
 * `ConfirmDialog` uses, sized for a table rather than a single prompt. */
export function PatientVisitHistoryDialog({ patient, onClose }) {
  const { visits, isLoading, isError, error, refetch } = usePatientVisitHistory(patient?.id);
  const printSlip = usePrintRegistrationSlip();
  const [printingVisitId, setPrintingVisitId] = useState(null);
  const [printError, setPrintError] = useState(null);

  if (!patient) return null;

  async function handlePrint(visitId) {
    if (printingVisitId) return; // one print job in flight at a time
    setPrintError(null);
    setPrintingVisitId(visitId);
    try {
      await printSlip.mutateAsync(visitId);
    } catch (err) {
      setPrintError(err.message || 'Unable to print this slip — you can try again.');
    } finally {
      setPrintingVisitId(null);
    }
  }

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/50 p-4"
      role="dialog"
      aria-modal="true"
      aria-labelledby="visit-history-dialog-title"
    >
      <Card className="flex max-h-[85vh] w-full max-w-3xl flex-col">
        <CardHeader className="flex-row items-center justify-between gap-2">
          <div>
            <CardTitle id="visit-history-dialog-title">{patient.full_name}</CardTitle>
            <p className="text-xs text-muted-foreground">
              {patient.mr_number} · Visit History
            </p>
          </div>
          <Button variant="ghost" size="sm" onClick={onClose} aria-label="Close">
            <X className="h-4 w-4" />
          </Button>
        </CardHeader>
        <CardContent className="flex flex-col gap-4 overflow-y-auto">
          {printError ? <p className="text-sm text-destructive">{printError}</p> : null}
          {isLoading ? (
            <PageLoader label="Loading visit history" />
          ) : isError ? (
            <PageError error={error} reset={refetch} message="Couldn't load visit history." />
          ) : visits.length === 0 ? (
            <p className="py-10 text-center text-sm text-muted-foreground">
              No visits recorded for this patient yet.
            </p>
          ) : (
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>Date</TableHead>
                  <TableHead>Queue Token</TableHead>
                  <TableHead>Procedure</TableHead>
                  <TableHead>Status</TableHead>
                  <TableHead className="text-right">Amount</TableHead>
                  <TableHead />
                </TableRow>
              </TableHeader>
              <TableBody>
                {visits.map((visit) => {
                  const isPrintingThisRow = printingVisitId === visit.id;
                  return (
                    <TableRow key={visit.id}>
                      <TableCell className="whitespace-nowrap">
                        {formatDisplayDate(displayDayKey(visit.created_at))}
                      </TableCell>
                      <TableCell className="whitespace-nowrap font-mono text-xs">
                        {visit.queue_token}
                      </TableCell>
                      <TableCell className="max-w-[160px]">
                        <VisitProcedureDisplay visit={visit} className="truncate" />
                      </TableCell>
                      <TableCell>
                        <Badge
                          variant={VISIT_STATUS_BADGE_VARIANT[visit.status] ?? 'outline'}
                          className="capitalize"
                        >
                          {visit.status.replaceAll('_', ' ')}
                        </Badge>
                      </TableCell>
                      <TableCell className="whitespace-nowrap text-right font-medium tabular-nums">
                        {formatPkr(visit.amount)}
                      </TableCell>
                      <TableCell>
                        <Button
                          size="sm"
                          variant="outline"
                          disabled={Boolean(printingVisitId)}
                          onClick={() => handlePrint(visit.id)}
                        >
                          <Printer className="h-3.5 w-3.5" />
                          {isPrintingThisRow ? 'Printing…' : 'Print Slip'}
                        </Button>
                      </TableCell>
                    </TableRow>
                  );
                })}
              </TableBody>
            </Table>
          )}
        </CardContent>
      </Card>
    </div>
  );
}
