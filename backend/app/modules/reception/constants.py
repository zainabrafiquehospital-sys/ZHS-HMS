"""Permission codes for the Reception module. Deliberately its own
composite codes — `reception:register_visit`/`reception:cancel_visit` —
rather than requiring an actor to separately hold `patients:create`,
`visits:create`, and `queue:manage`: Reception owns the composite
registration action end to end (Phase 6 architecture §6), and RBAC is
enforced once, at this module's router (the actual HTTP entry point) —
the underlying PatientService/VisitService/QueueService calls
ReceptionService makes are direct in-process method calls, not a second
HTTP round-trip, so they are correctly not re-gated by their own
routers' permission checks (those only apply at the HTTP boundary)."""

PERMISSION_RECEPTION_REGISTER_VISIT = "reception:register_visit"
PERMISSION_RECEPTION_CANCEL_VISIT = "reception:cancel_visit"
