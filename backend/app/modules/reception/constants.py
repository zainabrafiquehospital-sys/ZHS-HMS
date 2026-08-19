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

# Admin-only data-correction actions (2026-08-19 addition) — deliberately
# two separate, atomic permission codes rather than one combined
# "manage" code, matching this module's existing register/cancel split:
# a future admin could grant update without delete (or vice versa)
# through the Roles/Permissions API without any code change. Neither is
# ever granted to the Receptionist role (see scripts/
# seed_launch_bootstrap.py's RECEPTIONIST_PERMISSION_CODES, which
# explicitly does not include these) — receptionists keep exactly the
# register/cancel capability they had before; only `cancel_visit`
# (a status transition, not a correction/removal tool) remains theirs.
PERMISSION_RECEPTION_UPDATE_VISIT = "reception:update_visit"
PERMISSION_RECEPTION_DELETE_VISIT = "reception:delete_visit"
