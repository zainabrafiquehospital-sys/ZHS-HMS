'use client';

import { useQuery, useQueries, useMutation, useQueryClient } from '@tanstack/react-query';
import { consultationService } from '@/features/consultation/api/consultationService';
import { visitsService } from '@/features/visits/api/visitsService';
import { openAndPrintHtml } from '@/utils/printWindow';

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

/** Same cached-lookup-per-unique-id join pattern as usePatientsForVisits/
 * useVitalsForVisits, for a set of visits at once — used by
 * useVitalsPendingForDoctor below to find which of a doctor's own
 * `IN_CONSULTATION` visits currently have an `AWAITING_VITALS`
 * consultation (the doctor-requested mid-consult vitals detour — see
 * ConsultationService.send_to_vitals' docstring: the Visit's own status
 * deliberately never changes for this case, only the Consultation's
 * does, so this is the only way to detect it). Shares its query key
 * with `useActiveConsultation` so both hooks read/populate the same
 * cache entry per visit. */
function useActiveConsultationsForVisits(visits) {
  const uniqueVisitIds = [...new Set((visits ?? []).map((visit) => visit.id))];
  const results = useQueries({
    queries: uniqueVisitIds.map((visitId) => ({
      queryKey: ['consultations', 'active', visitId],
      queryFn: () => consultationService.getActiveForVisit(visitId).then((res) => res.data),
      enabled: Boolean(visitId),
    })),
  });
  const byId = {};
  uniqueVisitIds.forEach((id, index) => {
    byId[id] = results[index]?.data;
  });
  const isLoading = results.some((result) => result.isLoading);
  return { consultationsByVisitId: byId, isLoading };
}

/** Every visit currently "with the vitals nurse" that a doctor should
 * still be able to see — not silently absent from their queue just
 * because it isn't `WAITING_DOCTOR` right now. Covers both cases:
 *   - Workflow-A intake: Visit.status === WAITING_VITALS (Reception
 *     routed straight to vitals before any doctor touch) — both the
 *     doctor's own assigned ones and unclaimed ones, same "mine +
 *     unassigned" split `waiting_doctor` already gets.
 *   - The mid-consultation detour: Visit.status stays IN_CONSULTATION
 *     (see ConsultationService.send_to_vitals), only the active
 *     Consultation's own status flips to AWAITING_VITALS — these are
 *     always already assigned to this doctor (a consultation must have
 *     been started for the detour to exist at all), so only "mine" is
 *     relevant here, never "unassigned".
 * Merges both into one list, each tagged with `reason` so the caller
 * can label them appropriately without re-deriving which case a given
 * visit is. */
export function useVitalsPendingForDoctor(doctorUserId) {
  const { data: myWaitingVitals, isLoading: isLoadingMyWaitingVitals } = useMyQueue(
    doctorUserId,
    'waiting_vitals',
  );
  const { data: unassignedWaitingVitals, isLoading: isLoadingUnassignedWaitingVitals } =
    useUnassignedQueue('waiting_vitals');
  const { data: myInConsultation, isLoading: isLoadingMyInConsultation } = useMyQueue(
    doctorUserId,
    'in_consultation',
  );
  const { consultationsByVisitId, isLoading: isLoadingConsultations } =
    useActiveConsultationsForVisits(myInConsultation ?? []);

  const detourVisits = (myInConsultation ?? []).filter(
    (visit) => consultationsByVisitId[visit.id]?.status === 'awaiting_vitals',
  );

  const visits = [
    ...(myWaitingVitals ?? []).map((visit) => ({ visit, reason: 'intake' })),
    ...(unassignedWaitingVitals ?? []).map((visit) => ({ visit, reason: 'intake' })),
    ...detourVisits.map((visit) => ({ visit, reason: 'detour' })),
  ];

  return {
    visits,
    isLoading:
      isLoadingMyWaitingVitals ||
      isLoadingUnassignedWaitingVitals ||
      isLoadingMyInConsultation ||
      // Only meaningful once myInConsultation has resolved — before
      // that, useActiveConsultationsForVisits has nothing to query yet
      // and would otherwise report a misleadingly-settled isLoading.
      (Boolean(myInConsultation?.length) && isLoadingConsultations),
  };
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
      // The Visit's own status never changes for this detour (see
      // ConsultationService.send_to_vitals' docstring), so the
      // `['visits', 'doctor', ...]` query backing `useVitalsPendingForDoctor`
      // wouldn't otherwise know to re-check this visit's now-AWAITING_VITALS
      // consultation until its next 15s poll — invalidate eagerly so the
      // doctor's queue view picks up the "Vitals Pending" badge immediately.
      queryClient.invalidateQueries({ queryKey: ['visits', 'doctor'] });
      queryClient.invalidateQueries({ queryKey: ['consultations', 'active'] });
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

/** "View Slip" (2026-08-25 addition) — DoctorQueueList.jsx's own button,
 * mirroring Reception's usePrintRegistrationSlip exactly (same fetch +
 * openAndPrintHtml pipeline, same hidden-iframe print mechanism,
 * untouched) so a doctor can see exactly what was registered
 * (procedures, discount, payment status) before or without starting
 * the consultation. */
export function useViewRegistrationSlip() {
  return useMutation({
    mutationFn: async (visitId) => {
      const html = await consultationService.fetchRegistrationSlipHtml(visitId);
      await openAndPrintHtml(html);
    },
  });
}
