'use client';

import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { adminUsersService } from '@/features/admin/api/adminUsersService';

const QUERY_KEY = ['admin', 'pending-approvals'];

export function usePendingApprovals() {
  return useQuery({
    queryKey: QUERY_KEY,
    queryFn: () => adminUsersService.listPendingApprovals().then((res) => res.data),
    refetchInterval: 20000,
  });
}

export function useApproveSignup() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (userId) => adminUsersService.approveSignup(userId),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: QUERY_KEY }),
  });
}

export function useRejectSignup() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (userId) => adminUsersService.rejectSignup(userId),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: QUERY_KEY }),
  });
}
