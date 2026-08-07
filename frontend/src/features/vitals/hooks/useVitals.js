'use client';

import { useQuery, useQueries, useMutation, useQueryClient } from '@tanstack/react-query';
import { queueService, vitalsService } from '@/features/vitals/api/vitalsService';
import { visitsService } from '@/features/visits/api/visitsService';

export { usePatientsForVisits } from '@/features/patients/hooks/usePatientsForVisits';

/** The Vitals worklist is a Queue view (destination=vitals, status=waiting), not
 * a Visit view — each QueueEntry only carries visit_id, so callers still need
 * to join against Visits (and then Patients) themselves. */
export function useVitalsWorklist() {
  return useQuery({
    queryKey: ['queue', 'worklist', 'vitals', 'waiting'],
    queryFn: () =>
      queueService.worklist({ destination: 'vitals', status: 'waiting' }).then((res) => res.data),
    refetchInterval: 15000,
  });
}

/** One cached lookup per unique visit_id, mirroring usePatientsForVisits'
 * join pattern — the worklist only carries visit_id, not the visit itself. */
export function useVisitsByIds(visitIds) {
  const uniqueIds = [...new Set(visitIds ?? [])];
  const results = useQueries({
    queries: uniqueIds.map((visitId) => ({
      queryKey: ['visits', visitId],
      queryFn: () => visitsService.getById(visitId).then((res) => res.data),
      enabled: Boolean(visitId),
    })),
  });
  const byId = {};
  uniqueIds.forEach((id, index) => {
    byId[id] = results[index]?.data;
  });
  const isLoading = results.some((result) => result.isLoading);
  return { visitsById: byId, isLoading };
}

export function useRecordVitals() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (payload) => vitalsService.record(payload),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['queue', 'worklist', 'vitals'] });
      queryClient.invalidateQueries({ queryKey: ['visits', 'doctor'] });
      queryClient.invalidateQueries({ queryKey: ['dashboard'] });
    },
  });
}
