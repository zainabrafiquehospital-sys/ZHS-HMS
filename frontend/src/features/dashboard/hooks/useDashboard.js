'use client';

import { useQuery } from '@tanstack/react-query';
import { dashboardService } from '@/features/dashboard/api/dashboardService';

// Which dashboards a signed-in user can see is a backend RBAC decision
// (Phase 6 §22 — one permission per view), not something the frontend
// infers from role name. Each hook below is tried independently and a
// 403 (`status === 403`) is treated as "this view isn't part of my
// role" rather than a real error — the component simply omits that
// card instead of showing an error banner.
function useDashboardSummary(key, queryFn) {
  const query = useQuery({
    queryKey: ['dashboard', key],
    queryFn: () => queryFn().then((res) => res.data),
    refetchInterval: 20000,
    retry: false,
  });
  const isForbidden = query.error?.status === 403;
  return { ...query, isForbidden };
}

export function useReceptionDashboard() {
  return useDashboardSummary('reception', dashboardService.getReceptionSummary);
}

export function useDoctorDashboard() {
  return useDashboardSummary('doctor', dashboardService.getDoctorSummary);
}

export function useVitalsDashboard() {
  return useDashboardSummary('vitals', dashboardService.getVitalsSummary);
}
