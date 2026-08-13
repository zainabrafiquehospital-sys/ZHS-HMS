'use client';

import { useState } from 'react';
import { Search } from 'lucide-react';
import {
  useEmployeeAccountsList,
  useEmployeeActivityStats,
} from '@/features/admin/hooks/useEmployeeAccounts';
import { computePageCount } from '@/features/admin/utils/pagination';
import { useDebouncedValue } from '@/shared/hooks/useDebouncedValue';
import { displayDayKey, formatDisplayDate } from '@/utils/timezone';
import { Card, CardContent, CardHeader, CardTitle } from '@/shared/components/ui/Card';
import { Button } from '@/shared/components/ui/Button';
import { Input } from '@/shared/components/ui/Input';
import { Select } from '@/shared/components/ui/Select';
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

const PAGE_SIZE = 20;

const SORT_OPTIONS = [
  { value: 'created_at', label: 'Created On' },
  { value: 'full_name', label: 'Name' },
  { value: 'email', label: 'Email' },
  { value: 'status', label: 'Status' },
  { value: 'last_login_at', label: 'Last Login' },
];

const STATUS_BADGE_VARIANT = {
  active: 'success',
  inactive: 'outline',
  suspended: 'destructive',
  locked: 'destructive',
  rejected: 'destructive',
  pending_verification: 'warning',
  pending_email_verification: 'warning',
  pending_admin_approval: 'warning',
};

function money(amount) {
  return `Rs. ${Number(amount).toFixed(2)}`;
}

function dateLabel(isoTimestamp) {
  return isoTimestamp ? formatDisplayDate(displayDayKey(isoTimestamp)) : '—';
}

/** Full, paginated, searchable, sortable listing of every user account
 * — Admin-only, read-only. Real identity/status/role data straight from
 * `GET /users` (via `useEmployeeAccountsList`), plus real per-user
 * activity counts from four new read-only aggregate endpoints (via
 * `useEmployeeActivityStats`) — never a fabricated stat. No attendance/
 * check-in/late/overtime figures: no Attendance module exists yet, so
 * none are shown rather than invented. */
export function EmployeeAccounts() {
  const [page, setPage] = useState(1);
  const [searchInput, setSearchInput] = useState('');
  const [sortBy, setSortBy] = useState('created_at');
  const [sortOrder, setSortOrder] = useState('desc');
  const debouncedSearch = useDebouncedValue(searchInput, 300);

  const { users, meta, isLoading, isError, error, refetch } = useEmployeeAccountsList({
    page,
    pageSize: PAGE_SIZE,
    search: debouncedSearch || undefined,
    sortBy,
    sortOrder,
  });
  const stats = useEmployeeActivityStats();

  const pageCount = computePageCount(meta?.total, PAGE_SIZE);

  function handleSearchChange(value) {
    setSearchInput(value);
    setPage(1);
  }

  function handleSortByChange(value) {
    setSortBy(value);
    setPage(1);
  }

  function handleSortOrderChange(value) {
    setSortOrder(value);
    setPage(1);
  }

  return (
    <div className="flex flex-col gap-6">
      <div className="flex flex-col gap-1">
        <h1 className="text-lg font-semibold text-foreground">Employee Accounts &amp; Stats</h1>
        <p className="text-sm text-muted-foreground">
          Every user account, its status, and real activity counts — visits registered, medicine
          bills billed, consultations completed, vitals recorded.
        </p>
      </div>

      <Card>
        <CardHeader>
          <div className="flex flex-col gap-4 sm:flex-row sm:items-end sm:justify-between">
            <CardTitle>Employees</CardTitle>
            <div className="flex flex-col gap-3 sm:flex-row sm:items-end">
              <div className="relative w-full sm:w-64">
                <Search className="pointer-events-none absolute left-2.5 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground" />
                <Input
                  value={searchInput}
                  onChange={(event) => handleSearchChange(event.target.value)}
                  placeholder="Search by name or email…"
                  className="pl-8"
                />
              </div>
              <div className="flex gap-2">
                <Select
                  value={sortBy}
                  onChange={(event) => handleSortByChange(event.target.value)}
                  className="w-40"
                >
                  {SORT_OPTIONS.map((option) => (
                    <option key={option.value} value={option.value}>
                      {option.label}
                    </option>
                  ))}
                </Select>
                <Select
                  value={sortOrder}
                  onChange={(event) => handleSortOrderChange(event.target.value)}
                  className="w-28"
                >
                  <option value="desc">Newest</option>
                  <option value="asc">Oldest</option>
                </Select>
              </div>
            </div>
          </div>
        </CardHeader>
        <CardContent className="flex flex-col gap-4">
          {isLoading ? (
            <PageLoader label="Loading employee accounts" />
          ) : isError ? (
            <PageError error={error} reset={refetch} message="Couldn't load employee accounts." />
          ) : users.length === 0 ? (
            <p className="text-sm text-muted-foreground">
              {debouncedSearch ? 'No employees match this search.' : 'No user accounts yet.'}
            </p>
          ) : (
            <>
              {stats.isError ? (
                <p className="text-sm text-destructive">
                  Activity stats couldn't be loaded — showing account details only.
                </p>
              ) : null}
              <div className="overflow-x-auto">
                <Table>
                  <TableHeader>
                    <TableRow>
                      <TableHead>Name</TableHead>
                      <TableHead>Email</TableHead>
                      <TableHead>Role(s)</TableHead>
                      <TableHead>Status</TableHead>
                      <TableHead>Last Login</TableHead>
                      <TableHead>Created On</TableHead>
                      <TableHead className="text-right">Visits</TableHead>
                      <TableHead className="text-right">Bills</TableHead>
                      <TableHead className="text-right">Revenue Billed</TableHead>
                      <TableHead className="text-right">Consultations</TableHead>
                      <TableHead className="text-right">Vitals</TableHead>
                    </TableRow>
                  </TableHeader>
                  <TableBody>
                    {users.map((user) => {
                      const userStats = stats.isLoading ? null : stats.statsFor(user.id);
                      return (
                        <TableRow key={user.id}>
                          <TableCell className="font-medium text-foreground">
                            {user.full_name}
                          </TableCell>
                          <TableCell>{user.email}</TableCell>
                          <TableCell>
                            <div className="flex flex-wrap gap-1">
                              {user.roles.length === 0 ? (
                                <span className="text-muted-foreground">—</span>
                              ) : (
                                user.roles.map((role) => (
                                  <Badge key={role.id} variant="secondary">
                                    {role.name}
                                  </Badge>
                                ))
                              )}
                            </div>
                          </TableCell>
                          <TableCell>
                            <Badge
                              variant={STATUS_BADGE_VARIANT[user.status] ?? 'outline'}
                              className="capitalize"
                            >
                              {user.status.replaceAll('_', ' ')}
                            </Badge>
                          </TableCell>
                          <TableCell className="whitespace-nowrap text-muted-foreground">
                            {dateLabel(user.last_login_at)}
                          </TableCell>
                          <TableCell className="whitespace-nowrap text-muted-foreground">
                            {dateLabel(user.created_at)}
                          </TableCell>
                          <TableCell className="text-right tabular-nums">
                            {userStats ? userStats.visits : '…'}
                          </TableCell>
                          <TableCell className="text-right tabular-nums">
                            {userStats ? userStats.bills : '…'}
                          </TableCell>
                          <TableCell className="text-right tabular-nums">
                            {userStats ? money(userStats.revenue) : '…'}
                          </TableCell>
                          <TableCell className="text-right tabular-nums">
                            {userStats ? userStats.consultations : '…'}
                          </TableCell>
                          <TableCell className="text-right tabular-nums">
                            {userStats ? userStats.vitals : '…'}
                          </TableCell>
                        </TableRow>
                      );
                    })}
                  </TableBody>
                </Table>
              </div>

              {pageCount > 1 ? (
                <div className="flex items-center justify-between text-sm text-muted-foreground">
                  <span>
                    Page {page} of {pageCount} · {meta.total} employee{meta.total === 1 ? '' : 's'}
                  </span>
                  <div className="flex gap-2">
                    <Button
                      size="sm"
                      variant="outline"
                      disabled={page <= 1}
                      onClick={() => setPage((p) => Math.max(1, p - 1))}
                    >
                      Previous
                    </Button>
                    <Button
                      size="sm"
                      variant="outline"
                      disabled={page >= pageCount}
                      onClick={() => setPage((p) => Math.min(pageCount, p + 1))}
                    >
                      Next
                    </Button>
                  </div>
                </div>
              ) : null}
            </>
          )}
        </CardContent>
      </Card>
    </div>
  );
}
