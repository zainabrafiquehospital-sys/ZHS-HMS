"""Fixed configuration-as-code for the Visit module: permission codes and
the Queue Token format, mirroring app/modules/patients/constants.py's
conventions exactly."""

PERMISSION_VISITS_CREATE = "visits:create"
PERMISSION_VISITS_READ = "visits:read"

# Procedure catalog (2026-08-21 addition) — mirrors
# app/modules/pharmacy/constants.py's `pharmacy:manage`/`pharmacy:read`
# split exactly: one Admin-only permission for the full catalog CRUD
# (create/update/delete/list-all — a single combined permission,
# deliberately not split the way `pharmacy:update_bill`/
# `pharmacy:delete_bill` are, since that split exists specifically for
# admin-correcting-someone-else's-transaction scenarios; catalog
# management here is 100% admin-only either way, so there is no
# "grant one without the other" scenario worth preserving — confirmed
# design decision, same shape as Medicine's own single `pharmacy:manage`
# permission), and one permission granted to Receptionist too, gating
# only the registration-time search.
PERMISSION_PROCEDURES_MANAGE = "procedures:manage"
PERMISSION_PROCEDURES_READ = "procedures:read"

# Queue Token format (Phase 6 architecture §18): a fixed prefix plus a
# zero-padded sequence value. See VisitRepository.next_queue_token_value
# for the race-safe generation (a real Postgres SEQUENCE, mirroring
# app/modules/patients/constants.py's identical MR-number rationale).
#
# 2026-08-20 addition: this sequence is no longer Visit-exclusive —
# MedicineBillRepository.next_queue_token_value draws from the exact
# same underlying Postgres sequence (same name, same object), so a
# Visit and a MedicineBill created moments apart get truly consecutive,
# interleaved numbers (never two rows of either type sharing a number,
# never an unexplained gap) — see that method's own docstring and
# app/modules/pharmacy/models.py's MedicineBill.queue_token docstring
# for the full mechanism. The sequence's own Postgres name is left
# unchanged (Visit is still historically "first"); only the constant
# below is now imported and reused by Pharmacy too, matching the
# existing one-directional Pharmacy -> Visits dependency
# (PharmacyService already depends on VisitService for visit lookups).
QUEUE_TOKEN_PREFIX = "Token #"
QUEUE_TOKEN_SEQUENCE_NAME = "visit_queue_token_seq"
QUEUE_TOKEN_PAD_WIDTH = 6
