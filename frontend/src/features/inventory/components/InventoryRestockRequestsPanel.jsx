'use client';

import { useState } from 'react';
import { useForm } from 'react-hook-form';
import { zodResolver } from '@hookform/resolvers/zod';
import { Check, X } from 'lucide-react';
import {
  useInventoryItems,
  useInventoryRequests,
  useFulfillRequest,
  useRejectRequest,
} from '@/features/inventory/hooks/useInventory';
import {
  fulfillRequestFormSchema,
  rejectRequestFormSchema,
} from '@/features/inventory/schemas/inventorySchemas';
import { Card, CardContent, CardHeader, CardTitle } from '@/shared/components/ui/Card';
import { Button } from '@/shared/components/ui/Button';
import { Input } from '@/shared/components/ui/Input';
import { Label } from '@/shared/components/ui/Label';
import { Textarea } from '@/shared/components/ui/Textarea';
import { Badge } from '@/shared/components/ui/Badge';
import { ConfirmDialog } from '@/shared/components/ui/ConfirmDialog';
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
import { formatDisplayTime, todayDisplayDayKey } from '@/utils/timezone';

const REQUEST_STATUS_BADGE_VARIANT = {
  pending: 'warning',
  fulfilled: 'success',
  rejected: 'destructive',
};

function itemName(items, itemId) {
  return items.find((item) => item.id === itemId)?.name ?? 'Unknown item';
}

/** Fulfilling a request performs the actual Main -> Emergency transfer
 * (pre-filled item, editable quantity — a manager may send a different
 * amount than originally requested, see backend/app/modules/inventory/
 * service.py's fulfill_request docstring) — same "form fields embedded
 * in a ConfirmDialog" shape as AdminOverview.jsx's
 * RecordBillPaymentDialog. */
function FulfillRequestDialog({ request, items, onClose }) {
  const fulfillRequest = useFulfillRequest();
  const [error, setError] = useState(null);
  const {
    register,
    handleSubmit,
    formState: { errors, isSubmitting },
  } = useForm({
    resolver: zodResolver(fulfillRequestFormSchema),
    defaultValues: {
      transfer_quantity: request.requested_quantity ?? '',
      transferred_on: todayDisplayDayKey(),
    },
  });

  async function onSubmit(values) {
    setError(null);
    try {
      await fulfillRequest.mutateAsync({ requestId: request.id, payload: values });
      onClose();
    } catch (submitError) {
      setError(submitError.message || 'Unable to fulfill this request.');
    }
  }

  return (
    <ConfirmDialog
      open
      title={`Fulfill Request — ${itemName(items, request.item_id)}`}
      confirmLabel={isSubmitting ? 'Transferring…' : 'Transfer & Fulfill'}
      cancelLabel="Cancel"
      onCancel={onClose}
      onConfirm={handleSubmit(onSubmit)}
      description={
        <div className="flex flex-col gap-3">
          <p className="text-sm text-muted-foreground">
            {request.requested_quantity
              ? `Requested quantity: ${request.requested_quantity}.`
              : 'No specific quantity was requested — use your own judgment.'}
            {request.note ? ` Note: "${request.note}"` : ''}
          </p>
          <div className="flex flex-col gap-1.5">
            <Label htmlFor="fulfill-transfer-quantity">Transfer Quantity</Label>
            <Input
              id="fulfill-transfer-quantity"
              type="number"
              step="0.01"
              min="0"
              {...register('transfer_quantity')}
            />
            {errors.transfer_quantity ? (
              <p className="text-xs text-destructive">{errors.transfer_quantity.message}</p>
            ) : null}
          </div>
          <div className="flex flex-col gap-1.5">
            <Label htmlFor="fulfill-transferred-on">Transferred On</Label>
            <Input id="fulfill-transferred-on" type="date" {...register('transferred_on')} />
            {errors.transferred_on ? (
              <p className="text-xs text-destructive">{errors.transferred_on.message}</p>
            ) : null}
          </div>
          {error ? <p className="text-xs text-destructive">{error}</p> : null}
        </div>
      }
    />
  );
}

function RejectRequestDialog({ request, items, onClose }) {
  const rejectRequest = useRejectRequest();
  const [error, setError] = useState(null);
  const {
    register,
    handleSubmit,
    formState: { isSubmitting },
  } = useForm({
    resolver: zodResolver(rejectRequestFormSchema),
    defaultValues: { rejection_reason: '' },
  });

  async function onSubmit(values) {
    setError(null);
    try {
      await rejectRequest.mutateAsync({ requestId: request.id, payload: values });
      onClose();
    } catch (submitError) {
      setError(submitError.message || 'Unable to reject this request.');
    }
  }

  return (
    <ConfirmDialog
      open
      variant="destructive"
      title={`Reject Request — ${itemName(items, request.item_id)}`}
      confirmLabel={isSubmitting ? 'Rejecting…' : 'Reject Request'}
      cancelLabel="Cancel"
      onCancel={onClose}
      onConfirm={handleSubmit(onSubmit)}
      description={
        <div className="flex flex-col gap-3">
          <div className="flex flex-col gap-1.5">
            <Label htmlFor="reject-reason">Reason (optional)</Label>
            <Textarea id="reject-reason" {...register('rejection_reason')} />
          </div>
          {error ? <p className="text-xs text-destructive">{error}</p> : null}
        </div>
      }
    />
  );
}

function RequestsTable({ requests, items, showActions, onFulfill, onReject }) {
  if (requests.length === 0) {
    return <p className="text-sm text-muted-foreground">No requests here.</p>;
  }
  return (
    <Table>
      <TableHeader>
        <TableRow>
          <TableHead>Item</TableHead>
          <TableHead className="text-right">Requested Qty</TableHead>
          <TableHead>Note</TableHead>
          <TableHead>Status</TableHead>
          <TableHead>Raised</TableHead>
          {showActions ? <TableHead /> : null}
        </TableRow>
      </TableHeader>
      <TableBody>
        {requests.map((request) => (
          <TableRow key={request.id}>
            <TableCell className="font-medium text-foreground">
              {itemName(items, request.item_id)}
            </TableCell>
            <TableCell className="text-right tabular-nums">
              {request.requested_quantity ?? '—'}
            </TableCell>
            <TableCell className="max-w-[220px] truncate text-muted-foreground">
              {request.note ?? '—'}
            </TableCell>
            <TableCell>
              <Badge variant={REQUEST_STATUS_BADGE_VARIANT[request.status]} className="capitalize">
                {request.status}
              </Badge>
            </TableCell>
            <TableCell className="text-muted-foreground">
              {formatDisplayTime(request.created_at)}
            </TableCell>
            {showActions ? (
              <TableCell>
                <div className="flex justify-end gap-2">
                  <Button size="sm" onClick={() => onFulfill(request)}>
                    <Check className="h-4 w-4" />
                    Fulfill
                  </Button>
                  <Button size="sm" variant="ghost" onClick={() => onReject(request)}>
                    <X className="h-4 w-4" />
                    Reject
                  </Button>
                </div>
              </TableCell>
            ) : null}
          </TableRow>
        ))}
      </TableBody>
    </Table>
  );
}

export function InventoryRestockRequestsPanel() {
  const { data: items } = useInventoryItems();
  const {
    data: pendingRequests,
    isLoading: pendingLoading,
    isError: pendingIsError,
    error: pendingError,
    refetch: refetchPending,
  } = useInventoryRequests({ status: 'pending' });
  const { data: allRequests, isLoading: historyLoading } = useInventoryRequests({});
  const [fulfilling, setFulfilling] = useState(null);
  const [rejecting, setRejecting] = useState(null);

  const resolvedRequests = (allRequests ?? []).filter((request) => request.status !== 'pending');

  return (
    <div className="flex flex-col gap-6">
      <Card>
        <CardHeader>
          <CardTitle>Pending Requests</CardTitle>
        </CardHeader>
        <CardContent>
          {pendingLoading ? (
            <PageLoader label="Loading pending requests" />
          ) : pendingIsError ? (
            <PageError
              error={pendingError}
              reset={refetchPending}
              message="Couldn't load pending requests."
            />
          ) : (
            <RequestsTable
              requests={pendingRequests ?? []}
              items={items ?? []}
              showActions
              onFulfill={setFulfilling}
              onReject={setRejecting}
            />
          )}
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle>Resolved History</CardTitle>
        </CardHeader>
        <CardContent>
          {historyLoading ? (
            <PageLoader label="Loading history" />
          ) : (
            <RequestsTable requests={resolvedRequests} items={items ?? []} showActions={false} />
          )}
        </CardContent>
      </Card>

      {fulfilling ? (
        <FulfillRequestDialog
          request={fulfilling}
          items={items ?? []}
          onClose={() => setFulfilling(null)}
        />
      ) : null}
      {rejecting ? (
        <RejectRequestDialog
          request={rejecting}
          items={items ?? []}
          onClose={() => setRejecting(null)}
        />
      ) : null}
    </div>
  );
}
