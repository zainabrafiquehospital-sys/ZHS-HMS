'use client';

import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { consultationService } from '@/features/consultation/api/consultationService';
import { visitsService } from '@/features/visits/api/visitsService';

export { usePatientsForVisits } from '@/features/patients/hooks/usePatientsForVisits';

export function useMyQueue(doctorUserId, status = 'waiting_doctor') {
  return useQuery({
    queryKey: ['visits', 'doctor', doctorUserId, status],
    queryFn: () => visitsService.listForDoctor({ doctorUserId, status }).then((res) => res.data),
    enabled: Boolean(doctorUserId),
    refetchInterval: 15000,
  });
}

/** Fast-registration Visits Reception found no online doctor to
 * auto-assign to (see visits/models.py's `doctor_user_id` docstring on
 * the backend) — any doctor may claim one by starting its consultation
 * (useStartConsultation already handles the claim server-side). */
export function useUnassignedQueue(status = 'waiting_doctor') {
  return useQuery({
    queryKey: ['visits', 'unassigned', status],
    queryFn: () =>
      visitsService.list({ status, unassignedOnly: true }).then((res) => res.data),
    refetchInterval: 15000,
  });
}

export function useActiveConsultation(visitId) {
  return useQuery({
    queryKey: ['consultations', 'active', visitId],
    queryFn: () => consultationService.getActiveForVisit(visitId).then((res) => res.data),
    enabled: Boolean(visitId),
  });
}

export function useConsultationById(consultationId) {
  return useQuery({
    queryKey: ['consultations', consultationId],
    queryFn: () => consultationService.getById(consultationId).then((res) => res.data),
    enabled: Boolean(consultationId),
    refetchInterval: (query) => (query.state.data?.status === 'awaiting_vitals' ? 5000 : false),
  });
}

export function useStartConsultation() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (visitId) => consultationService.start(visitId),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['visits', 'doctor'] });
      queryClient.invalidateQueries({ queryKey: ['visits', 'unassigned'] });
    },
  });
}

export function useSendToVitals() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({ consultationId, reason }) =>
      consultationService.sendToVitals(consultationId, reason),
    onSuccess: (_data, variables) => {
      queryClient.invalidateQueries({ queryKey: ['consultations', variables.consultationId] });
    },
  });
}

export function useCompleteConsultation() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({ consultationId, updates }) =>
      consultationService.complete(consultationId, updates),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['visits', 'doctor'] });
      queryClient.invalidateQueries({ queryKey: ['dashboard'] });
    },
  });
}
