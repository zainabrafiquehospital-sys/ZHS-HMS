import { RequirePermission } from '@/features/auth/components/RequirePermission';

// Gated on vitals:record, not vitals:read (2026-08-30 root-cause fix) —
// the entire /vitals route tree (the worklist, the Record Vitals entry
// form at /vitals/[visitId], Record Usage, Raise Restock Request, and
// My Records) is fundamentally an action module for staff who actually
// do vitals work, not a read-only browsing screen. Doctor legitimately
// holds vitals:read (for its own read-only vitals display inline in
// ConsultationPanel — RecordedVitals/VitalsHistoryDialog, neither of
// which lives under this route), but has no business reaching any page
// here: before this fix, a Doctor who found their way to
// /vitals/[visitId] (e.g. via the sidebar link, which shared this same
// too-broad permission) could fill in and submit the entire Record
// Vitals form only to be rejected by the backend's own vitals:record
// check — a confusing, data-entry-then-fail dead end rather than a
// clean, immediate redirect. Every actual Vitals-role account holds
// both vitals:record and vitals:read together (see
// scripts/seed_launch_bootstrap.py's VITALS_PERMISSION_CODES), so this
// tightens nothing for anyone who's supposed to be here.
export default function VitalsLayout({ children }) {
  return <RequirePermission permission="vitals:record">{children}</RequirePermission>;
}
