'use client';

import { useState } from 'react';
import { Check, UserCheck, X } from 'lucide-react';
import {
  usePendingApprovals,
  useApproveSignup,
  useRejectSignup,
} from '@/features/admin/hooks/usePendingApprovals';
import { Card, CardContent, CardHeader, CardTitle } from '@/shared/components/ui/Card';
import { Badge } from '@/shared/components/ui/Badge';
import { Button } from '@/shared/components/ui/Button';
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
import { displayDayKey, formatDisplayTime } from '@/utils/timezone';
import { useToast } from '@/shared/components/toast/ToastProvider';

// Mirrors backend/app/modules/auth/models.py's SignupRole values —
// human-readable labels for the "Role" column below, since the roles
// this now mixes together (Receptionist and Vitals staff) need to be
// told apart at a glance, not just inferred from context the way a
// single-role list never needed to.
const SIGNUP_ROLE_LABEL = {
  receptionist: 'Receptionist',
  vitals: 'Vitals Staff',
};

/**
 * Every self-service signup currently awaiting an admin decision,
 * across every role that supports self-service signup (Receptionist
 * and Vitals staff — see backend/app/modules/auth/models.py's
 * SignupRole) — see backend/app/modules/auth/user_service.py's
 * approve_signup/reject_signup, which grants whichever role each row's
 * own signup requested, not a single hardcoded one. Read-only list
 * plus the two actions; this is deliberately not user/role management
 * in general (see adminUsersService.js's own docstring) — that's out
 * of scope for this pass.
 */
export function PendingApprovals() {
  const { data, isLoading, isError, error, refetch } = usePendingApprovals();
  const approveSignup = useApproveSignup();
  const rejectSignup = useRejectSignup();
  const [actioningId, setActioningId] = useState(null);
  const { toast } = useToast();

  const pendingUsers = data ?? [];

  async function handleApprove(userId) {
    if (actioningId) return;
    setActioningId(userId);
    const name = pendingUsers.find((u) => u.id === userId)?.full_name ?? 'this account';
    // toast.loading + toast.update rather than dismiss-then-show — a
    // real in-flight indicator (Part 4.2's spinning icon) for the
    // couple hundred ms an approval genuinely takes, that then
    // resolves into the same toast rather than a flicker of two.
    const toastId = toast.loading({ title: `Approving ${name}…` });
    try {
      await approveSignup.mutateAsync(userId);
      toast.update(toastId, 'success', {
        title: 'Account approved',
        description: `${name} can now sign in.`,
      });
    } catch (err) {
      toast.update(toastId, 'error', {
        title: 'Unable to approve this account',
        description: err.message,
        onRetry: () => handleApprove(userId),
      });
    } finally {
      setActioningId(null);
    }
  }

  async function handleReject(userId) {
    if (actioningId) return;
    setActioningId(userId);
    const name = pendingUsers.find((u) => u.id === userId)?.full_name ?? 'this account';
    const toastId = toast.loading({ title: `Rejecting ${name}…` });
    try {
      await rejectSignup.mutateAsync(userId);
      toast.update(toastId, 'success', { title: 'Signup rejected', description: name });
    } catch (err) {
      toast.update(toastId, 'error', {
        title: 'Unable to reject this account',
        description: err.message,
        onRetry: () => handleReject(userId),
      });
    } finally {
      setActioningId(null);
    }
  }

  return (
    <Card>
      <CardHeader className="flex-row items-center gap-2">
        <UserCheck className="h-4 w-4 text-muted-foreground" />
        <CardTitle>Pending Approvals ({pendingUsers.length})</CardTitle>
      </CardHeader>
      <CardContent className="flex flex-col gap-4">
        {isLoading ? (
          <PageLoader label="Loading pending approvals" />
        ) : isError ? (
          <PageError error={error} reset={refetch} message="Couldn't load pending approvals." />
        ) : (
          <>
            {pendingUsers.length === 0 ? (
              <p className="py-6 text-center text-sm text-muted-foreground">
                No signups are currently awaiting approval.
              </p>
            ) : (
              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead>Name</TableHead>
                    <TableHead>Role</TableHead>
                    <TableHead>Email</TableHead>
                    <TableHead>Phone</TableHead>
                    <TableHead>Shift</TableHead>
                    <TableHead>Signed Up</TableHead>
                    <TableHead />
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {pendingUsers.map((user) => {
                    const isActioning = actioningId === user.id;
                    return (
                      <TableRow key={user.id}>
                        <TableCell className="font-medium text-foreground">
                          {user.full_name}
                        </TableCell>
                        <TableCell>
                          <Badge variant="outline">
                            {SIGNUP_ROLE_LABEL[user.signup_role] ?? 'Receptionist'}
                          </Badge>
                        </TableCell>
                        <TableCell className="whitespace-nowrap">{user.email}</TableCell>
                        <TableCell className="whitespace-nowrap">
                          {user.phone_number || '—'}
                        </TableCell>
                        <TableCell>
                          <Badge variant="outline" className="capitalize">
                            {user.shift || '—'}
                          </Badge>
                        </TableCell>
                        <TableCell className="whitespace-nowrap">
                          {displayDayKey(user.created_at)} {formatDisplayTime(user.created_at)}
                        </TableCell>
                        <TableCell>
                          <div className="flex gap-2">
                            <Button
                              size="sm"
                              disabled={Boolean(actioningId)}
                              onClick={() => handleApprove(user.id)}
                            >
                              <Check className="h-3.5 w-3.5" />
                              {isActioning && approveSignup.isPending ? 'Approving…' : 'Approve'}
                            </Button>
                            <Button
                              size="sm"
                              variant="outline"
                              disabled={Boolean(actioningId)}
                              onClick={() => handleReject(user.id)}
                            >
                              <X className="h-3.5 w-3.5" />
                              {isActioning && rejectSignup.isPending ? 'Rejecting…' : 'Reject'}
                            </Button>
                          </div>
                        </TableCell>
                      </TableRow>
                    );
                  })}
                </TableBody>
              </Table>
            )}
          </>
        )}
      </CardContent>
    </Card>
  );
}
