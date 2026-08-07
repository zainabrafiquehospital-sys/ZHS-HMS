'use client';

import { useQueries } from '@tanstack/react-query';
import { patientsService } from '@/features/patients/api/patientsService';

/** Enriches a list of Visits with their Patient's name/MR number — the
 * Visit API deliberately doesn't embed Patient data (Phase 6 §12's
 * one-directional module graph), so the frontend joins the two itself
 * with one cached lookup per unique patient. Shared across Doctor Queue
 * and Vitals worklist, which both need this identical join. */
export function usePatientsForVisits(visits) {
  const uniquePatientIds = [...new Set((visits ?? []).map((visit) => visit.patient_id))];
  const results = useQueries({
    queries: uniquePatientIds.map((patientId) => ({
      queryKey: ['patients', patientId],
      queryFn: () => patientsService.getById(patientId).then((res) => res.data),
      enabled: Boolean(patientId),
    })),
  });
  const byId = {};
  uniquePatientIds.forEach((id, index) => {
    byId[id] = results[index]?.data;
  });
  return byId;
}
