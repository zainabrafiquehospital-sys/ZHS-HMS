"""Fixed configuration-as-code for the Patient module: permission codes
and the MR-number format, mirroring app/modules/auth/constants.py's
`<group>:<action>` convention exactly (see app/modules/auth/models.py's
Permission docstring)."""

PERMISSION_PATIENTS_CREATE = "patients:create"
PERMISSION_PATIENTS_READ = "patients:read"
PERMISSION_PATIENTS_UPDATE = "patients:update"

# The cross-module "Patient History" search (2026-08-31 addition) —
# deliberately its own permission, not a reuse of PERMISSION_PATIENTS_READ:
# that code already grants Doctor/Receptionist/Vitals bulk patient-directory
# browsing (a different, broader capability), and reusing it here would
# mean granting this new aggregated-history surface to any future holder
# of patients:read without a separate decision. See
# app/modules/patient_history/router.py's own docstring for how each
# section of the response is additionally scoped per-actor, using their
# other already-held permissions (consultation:read, billing:read,
# vitals:read, lab:read, pharmacy:read) — this permission only gates
# reaching the screen at all, never which sections it returns.
PERMISSION_PATIENTS_HISTORY_READ = "patients:history:read"

# `mr_number` format: a fixed prefix plus a zero-padded sequence value —
# see PatientRepository.next_mr_number for how the sequence itself is
# generated (a real Postgres SEQUENCE, not a count-then-increment, to
# stay race-safe under concurrent registrations at multiple Reception
# counters — see app/shared/db_errors.py's module docstring for the
# general TOCTOU rationale this project already established).
MR_NUMBER_PREFIX = "MR"
MR_NUMBER_SEQUENCE_NAME = "patient_mr_number_seq"
MR_NUMBER_PAD_WIDTH = 6
