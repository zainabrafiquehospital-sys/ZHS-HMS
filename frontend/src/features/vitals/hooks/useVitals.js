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

/** Backs the entry form's previous-reading/trend panel. `enabled`
 * requires both IDs since the backend endpoint needs the patient to
 * scope the search and the current visit to exclude from it (see
 * vitalsService.latestForPatient). Returns `data: null` for a genuine
 * "no prior vitals" outcome, distinguishable from `isLoading` — the
 * form must render an honest empty state for the former, not confuse
 * it with the latter. */
export function useLatestVitalsForPatient(patientId, excludeVisitId) {
  return useQuery({
    queryKey: ['vitals', 'patients', patientId, 'latest', excludeVisitId],
    queryFn: () =>
      vitalsService.latestForPatient(patientId, excludeVisitId).then((res) => res.data),
    enabled: Boolean(patientId) && Boolean(excludeVisitId),
  });
}

/** All vitals recorded so far for one visit, ordered oldest-first by
 * the backend (see VitalsRecordRepository.list_for_visit). Used by the
 * doctor's Consultation view to display what was actually recorded,
 * not just that a "Send to Vitals" action exists. */
export function useVitalsForVisit(visitId) {
  return useQuery({
    queryKey: ['vitals', 'visits', visitId],
    queryFn: () => vitalsService.listForVisit(visitId).then((res) => res.data),
    enabled: Boolean(visitId),
  });
}

/** Same shape as usePatientsForVisits/useReceptionistsForVisits' join
 * pattern, for the doctor's queue and consultation view — both need
 * "does this visit have a flagged vital?" without an extra endpoint.
 * Shares its query key with `useVitalsForVisit` so both hooks read
 * from (and populate) the same cache entry per visit. */
export function useVitalsForVisits(visits) {
  const uniqueVisitIds = [...new Set((visits ?? []).map((visit) => visit.id))];
  const results = useQueries({
    queries: uniqueVisitIds.map((visitId) => ({
      queryKey: ['vitals', 'visits', visitId],
      queryFn: () => vitalsService.listForVisit(visitId).then((res) => res.data),
      enabled: Boolean(visitId),
    })),
  });
  const byId = {};
  uniqueVisitIds.forEach((id, index) => {
    byId[id] = results[index]?.data;
  });
  const isLoading = results.some((result) => result.isLoading);
  return { vitalsByVisitId: byId, isLoading };
}

/** Backs the "Show Details" cross-visit vitals history dialog — every
 * vitals record ever recorded for this patient, across every visit,
 * newest first (already sorted server-side, see
 * VitalsRecordRepository.list_for_visit_ids). `enabled` only requires
 * the patient id (unlike useLatestVitalsForPatient, there is no
 * "current visit to exclude" here — this is an explicit "show me
 * everything" view). */
export function usePatientVitalsHistory(patientId) {
  return useQuery({
    queryKey: ['vitals', 'patients', patientId, 'history'],
    queryFn: () => vitalsService.historyForPatient(patientId).then((res) => res.data),
    enabled: Boolean(patientId),
  });
}

export function useRecordVitals() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (payload) => vitalsService.record(payload),
    onSuccess: (_data, payload) => {
      queryClient.invalidateQueries({ queryKey: ['queue', 'worklist', 'vitals'] });
      queryClient.invalidateQueries({ queryKey: ['visits', 'doctor'] });
      queryClient.invalidateQueries({ queryKey: ['visits', 'unassigned'] });
      queryClient.invalidateQueries({ queryKey: ['dashboard'] });
      queryClient.invalidateQueries({ queryKey: ['vitals', 'visits', payload.visit_id] });
      // Covers the mid-consultation detour case: recording vitals here
      // flips the visit's active Consultation back from AWAITING_VITALS
      // to IN_PROGRESS server-side (ConsultationService.resume_from_vitals)
      // — invalidate so the doctor's "Vitals Pending" badge
      // (useVitalsPendingForDoctor) clears immediately rather than
      // waiting on the next poll.
      queryClient.invalidateQueries({ queryKey: ['consultations', 'active'] });
    },
  });
}
