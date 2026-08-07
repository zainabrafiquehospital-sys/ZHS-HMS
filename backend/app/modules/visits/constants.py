"""Fixed configuration-as-code for the Visit module: permission codes and
the Queue Token format, mirroring app/modules/patients/constants.py's
conventions exactly."""

PERMISSION_VISITS_CREATE = "visits:create"
PERMISSION_VISITS_READ = "visits:read"

# Queue Token format (Phase 6 architecture §18): a fixed prefix plus a
# zero-padded sequence value. See VisitRepository.next_queue_token_value
# for the race-safe generation (a real Postgres SEQUENCE, mirroring
# app/modules/patients/constants.py's identical MR-number rationale).
QUEUE_TOKEN_PREFIX = "GYN"
QUEUE_TOKEN_SEQUENCE_NAME = "visit_queue_token_seq"
QUEUE_TOKEN_PAD_WIDTH = 6
