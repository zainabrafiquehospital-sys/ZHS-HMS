'use client';

import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { proceduresService } from '@/features/visits/api/proceduresService';

/** Admin management listing — every procedure, active and inactive
 * alike (see proceduresService.listProcedures's docstring). Mirrors
 * features/pharmacy/hooks/usePharmacy.js's `useMedicines` exactly. */
export function useProcedures() {
  return useQuery({
    queryKey: ['visits', 'procedures', 'admin'],
    queryFn: () => proceduresService.listProcedures().then((res) => res.data),
  });
}

function invalidateProcedures(queryClient) {
  queryClient.invalidateQueries({ queryKey: ['visits', 'procedures'] });
}

export function useCreateProcedure() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (payload) => proceduresService.createProcedure(payload),
    onSuccess: () => invalidateProcedures(queryClient),
  });
}

export function useUpdateProcedure() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({ procedureId, payload }) =>
      proceduresService.updateProcedure(procedureId, payload),
    onSuccess: () => invalidateProcedures(queryClient),
  });
}

/** Unlike Medicine (activate/deactivate only), the procedure catalog
 * also supports a genuine delete — see backend/app/modules/visits/
 * models.py's `Procedure` docstring for why that's safe regardless of
 * whether the procedure has ever been selected for a visit. */
export function useDeleteProcedure() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (procedureId) => proceduresService.deleteProcedure(procedureId),
    onSuccess: () => invalidateProcedures(queryClient),
  });
}
