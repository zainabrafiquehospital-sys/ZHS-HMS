'use client';

import { useEffect, useRef } from 'react';
import {
  keepPreviousData,
  useQuery,
  useQueries,
  useMutation,
  useQueryClient,
} from '@tanstack/react-query';
import { consultationService } from '@/features/consultation/api/consultationService';
import { visitsService } from '@/features/visits/api/visitsService';
import { useAuth } from '@/features/auth/hooks/useAuth';
import { openAndPrintHtml } from '@/utils/printWindow';

export { usePatientsForVisits } from '@/features/patients/hooks/usePatientsForVisits';
export { useVisitsByIds } from '@/features/vitals/hooks/useVitals';

/** `refetchIntervalInBackground: true` (2026-08-30 addition) — this
 * hook's only consumers are the Doctor Queue page itself
 * (DoctorQueueList.jsx) and useVitalsPendingForDoctor below, both part
 * of the same "vitals staff -> doctor" real-time handoff this fixes;
 * no other page calls useMyQueue, so this is safely scoped without
 * needing a per-call-site flag. Without it, React Query's own default
 * (`refetchIntervalInBackground: false`, unrelated to and independent
 * of this app's global `refetchOnWindowFocus: false` — see
 * core/providers/QueryProvider.jsx, untouched by this fix) silently
 * pauses this 15s poll the instant the Doctor Queue tab isn't the
 * active/visible one, and nothing catches it back up on refocus either
 * — a doctor who has this tab open but backgrounded (checking another
 * window, a second monitor) would see a patient sent to vitals staff
 * sit in "Vitals Pending" indefinitely after vitals staff actually
 * complete it, until a manual reload. Confirmed via direct production
 * database verification that the backend/data side was always correct
 * in this exact incident — the visit's status, queue routing, and
 * vitals_record linkage all transitioned correctly; only the doctor's
 * own already-open browser tab never re-polled to see it. 15s is kept
 * unchanged (not shortened) — it already matches this app's own
 * established "live worklist" convention (useVitalsWorklist and
 * Reception's own equivalent queue view both already poll at 15s); the
 * tighter 5s useConsultationById already uses is deliberately reserved
 * for that hook's narrower "watch this one visit resolve" case, which
 * doesn't generalize to a multi-visit list endpoint the same way. */
export function useMyQueue(doctorUserId, status = 'waiting_doctor') {
  return useQuery({
    queryKey: ['visits', 'doctor', doctorUserId, status],
    queryFn: () => visitsService.listForDoctor({ doctorUserId, status }).then((res) => res.data),
    enabled: Boolean(doctorUserId),
    refetchInterval: 15000,
    refetchIntervalInBackground: true,
  });
}

/** Fast-registration Visits Reception found no online doctor to
 * auto-assign to (see visits/models.py's `doctor_user_id` docstring on
 * the backend) — any doctor may claim one by starting its consultation
 * (useStartConsultation already handles the claim server-side).
 * `refetchIntervalInBackground: true` — same reasoning as useMyQueue's
 * own docstring immediately above (identical bug, identical fix); this
 * hook's only consumers are also entirely within the Doctor Queue
 * page. */
export function useUnassignedQueue(status = 'waiting_doctor') {
  return useQuery({
    queryKey: ['visits', 'unassigned', status],
    queryFn: () => visitsService.list({ status, unassignedOnly: true }).then((res) => res.data),
    refetchInterval: 15000,
    refetchIntervalInBackground: true,
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

/** `refetchInterval` above is already the one mechanism that detects an
 * `awaiting_vitals` consultation resuming on a doctor's own already-open
 * screen — it polls every 5s for exactly as long as that status holds,
 * which is how the "Waiting for vitals to be recorded" banner
 * (ConsultationPanel.jsx) clears itself without a manual reload. That
 * resume happens in the *vitals staff's own browser session*
 * (ConsultationService.resume_from_vitals, triggered by their
 * `record_vitals` call) — nothing in the doctor's separate session would
 * otherwise know the new vitals reading exists, since `useVitalsForVisit`
 * (features/vitals/hooks/useVitals.js) only ever fetches once on mount
 * and this app deliberately runs no background polling/refetch-on-focus
 * globally (see core/providers/QueryProvider.jsx). Piggybacking on this
 * exact same transition-detection point — rather than adding polling to
 * `useVitalsForVisit` itself, or changing any global default — is the
 * targeted fix: the instant this poll observes the status leave
 * `awaiting_vitals`, invalidate the vitals query for that same visit so
 * `RecordedVitals` refetches itself in step, still gated by the doctor's
 * own already-open screen actually detecting the transition, not a new
 * independent poll of its own. */
export function useConsultationById(consultationId) {
  const queryClient = useQueryClient();
  const query = useQuery({
    queryKey: ['consultations', consultationId],
    queryFn: () => consultationService.getById(consultationId).then((res) => res.data),
    enabled: Boolean(consultationId),
    refetchInterval: (q) => (q.state.data?.status === 'awaiting_vitals' ? 5000 : false),
  });

  // Keyed by consultationId so a stale previous-status from a different
  // consultation can never leak into this one's own transition check
  // (the hook is always called with a stable id per mount in practice,
  // but this keeps the check correct even if that ever changes).
  const previousStatusRef = useRef({ consultationId, status: query.data?.status });
  useEffect(() => {
    const currentStatus = query.data?.status;
    const sameConsultation = previousStatusRef.current.consultationId === consultationId;
    const previousStatus = sameConsultation ? previousStatusRef.current.status : undefined;
    if (
      previousStatus === 'awaiting_vitals' &&
      currentStatus &&
      currentStatus !== 'awaiting_vitals'
    ) {
      queryClient.invalidateQueries({ queryKey: ['vitals', 'visits', query.data.visit_id] });
    }
    previousStatusRef.current = { consultationId, status: currentStatus };
  }, [consultationId, query.data?.status, query.data?.visit_id, queryClient]);

  return query;
}

/** "My Consultations" — every consultation the calling doctor has
 * completed, newest first, real server-side pagination (2026-09-03).
 * The Doctor sibling of useMyVitalsRecords / useMyMedicineBills: same
 * `keepPreviousData` + `{ consultations, meta }` shape. `queryKey` is
 * scoped to `user.id` so one doctor's cache never bleeds into another's
 * on the same browser. */
export function useMyConsultations({ page, pageSize }) {
  const { user } = useAuth();
  const query = useQuery({
    queryKey: ['consultations', 'mine', user?.id, { page, pageSize }],
    queryFn: () =>
      consultationService
        .listMine({ page, pageSize })
        .then((res) => ({ consultations: res.data, meta: res.meta })),
    enabled: Boolean(user?.id),
    placeholderData: keepPreviousData,
  });
  return {
    ...query,
    consultations: query.data?.consultations ?? [],
    meta: query.data?.meta ?? null,
  };
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

/** Post-completion clinical-content correction (2026-09-04) — a doctor
 * amending a mistake in their own completed consultation. Invalidates
 * every surface that renders a consultation's clinical fields so a
 * correction shows immediately: the single-consultation cache, "My
 * Consultations", and Patient History's Consultations section. The
 * prescription-slip print endpoint re-reads persisted fields live, so
 * it needs no invalidation. */
export function useCorrectConsultation() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({ consultationId, updates }) =>
      consultationService.correct(consultationId, updates),
    onSuccess: (_data, variables) => {
      queryClient.invalidateQueries({ queryKey: ['consultations', variables.consultationId] });
      queryClient.invalidateQueries({ queryKey: ['consultations', 'mine'] });
      queryClient.invalidateQueries({ queryKey: ['patients', 'history'] });
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

/** "Print Prescription" (2026-09-03) — ConsultationPanel's own button,
 * available once the consultation is completed (the slip reads the
 * persisted consultation). Same fetch-HTML-then-openAndPrintHtml
 * pipeline / hidden-iframe print mechanism as useViewRegistrationSlip
 * above, just against the Consultation module's own slip endpoint. */
export function usePrintPrescriptionSlip() {
  return useMutation({
    mutationFn: async (consultationId) => {
      const html = await consultationService.fetchPrescriptionSlipHtml(consultationId);
      await openAndPrintHtml(html);
    },
  });
}
