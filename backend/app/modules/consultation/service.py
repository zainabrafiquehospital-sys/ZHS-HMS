"""Consultation business logic — Phase 6 architecture §5.4's Consultation
Lifecycle State Machine (the subset relevant to this build: In Progress /
Awaiting Vitals / Completed / Cancelled).

Orchestrates VisitService and QueueService the same way
app/modules/reception/service.py does — see that module's docstring for
the identical "sequential orchestration across independently-committing
services, not one cross-aggregate transaction" rationale, which applies
here too.

Ownership split for the doctor <-> vitals detour (§5.2), deliberately
divided so Consultation never depends on the not-yet-built Vitals
module (one-directional dependency graph, §12):
- `send_to_vitals` (here) closes the doctor leg and opens the vitals
  leg via QueueService — Consultation owns *leaving* for vitals.
- `resume_from_vitals` (here) only flips this module's own Consultation
  status back to `IN_PROGRESS` — it does NOT re-route the queue back to
  the doctor. The Vitals module, when built, owns *completing* a vitals
  workup and is responsible for calling both QueueService.route_to(...,
  DOCTOR) and this method — Consultation exposes the hook, Vitals drives
  it, exactly like Reception drives Visit/Queue today."""

from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import PermissionDeniedError
from app.modules.auth.models import User
from app.modules.consultation.exceptions import (
    ConsultationAlreadyActiveError,
    ConsultationNotFoundError,
    InvalidConsultationStatusTransitionError,
    NoActiveConsultationForVisitError,
)
from app.modules.consultation.models import Consultation, ConsultationStatus
from app.modules.consultation.repository import ConsultationRepository
from app.modules.queue.models import QueueDestination
from app.modules.queue.service import QueueService
from app.modules.visits.service import VisitService
from app.shared.audit.repository import AuditLogRepository
from app.shared.db_errors import unique_violation_constraint_name

# The unique-while-active index backing Consultation's single-active-
# per-visit invariant — see app/modules/consultation/models.py. Checked
# against a caught IntegrityError to tell a genuine race-lost double
# `start_consultation` apart from any other integrity failure, the same
# TOCTOU-closing pattern already established throughout this codebase
# (see app/shared/db_errors.py's module docstring).
_CONSULTATION_ACTIVE_CONSTRAINT = "ix_consultation_visit_id_active"


class ConsultationService:
    def __init__(
        self,
        session: AsyncSession,
        consultation_repository: ConsultationRepository,
        visit_service: VisitService,
        queue_service: QueueService,
        audit_repository: AuditLogRepository,
    ) -> None:
        self._session = session
        self._consultation_repo = consultation_repository
        self._visit_service = visit_service
        self._queue_service = queue_service
        self._audit_repo = audit_repository

    async def start_consultation(self, *, actor: User, visit_id: UUID) -> Consultation:
        """Opens a Consultation for a Visit currently `WAITING_DOCTOR`.
        `VisitService.mark_in_consultation` itself enforces that
        precondition (raises `InvalidVisitStatusTransitionError`
        otherwise) — this method does not duplicate that check.

        The acting doctor is never client-supplied — it is always
        `actor.id`, checked against the Visit's own `doctor_user_id`
        (§5.2's "always the same doctor" guarantee starts here: a doctor
        can only ever open *their own* assigned Visit, never one
        assigned to a colleague).

        `doctor_user_id is None` means Reception's fast-registration
        flow found no online doctor to auto-assign (see
        visits/models.py's docstring) — the first doctor to call this
        for that Visit claims it via `VisitService.assign_doctor`'s
        conditional `WHERE doctor_user_id IS NULL` update, which is
        race-safe under Postgres's row-locking regardless of commit
        ordering elsewhere. If a concurrent claim wins that race, this
        request re-checks and is rejected exactly like any other
        already-assigned Visit."""
        if await self._consultation_repo.get_active_for_visit(visit_id) is not None:
            raise ConsultationAlreadyActiveError

        visit = await self._visit_service.get_visit(visit_id)
        if visit.doctor_user_id is None:
            claimed = await self._visit_service.assign_doctor(
                actor=actor, visit_id=visit_id, doctor_user_id=actor.id
            )
            if not claimed:
                visit = await self._visit_service.get_visit(visit_id)
        if visit.doctor_user_id != actor.id:
            raise PermissionDeniedError("This visit is not assigned to you.")

        await self._visit_service.mark_in_consultation(actor=actor, visit_id=visit_id)

        consultation = Consultation(
            visit_id=visit_id,
            doctor_user_id=actor.id,
            status=ConsultationStatus.IN_PROGRESS,
            created_by=actor.id,
            updated_by=actor.id,
        )
        try:
            await self._consultation_repo.add(consultation)
        except IntegrityError as exc:
            await self._session.rollback()
            if unique_violation_constraint_name(exc) == _CONSULTATION_ACTIVE_CONSTRAINT:
                # Lost the race to a concurrent `start_consultation` for
                # the same Visit — `mark_in_consultation` above already
                # committed *this* request's own copy of the same target
                # status (`IN_CONSULTATION`), which is harmless: the
                # winner's transition set the identical value, so the
                # Visit's final status is correct either way, and
                # exactly one Consultation row exists. Only the loser's
                # own duplicate Consultation insert is rejected.
                raise ConsultationAlreadyActiveError from exc
            raise

        active_entry = await self._queue_service.get_active_for_visit(visit_id)
        if active_entry is not None:
            await self._queue_service.start_serving(actor=actor, entry_id=active_entry.id)

        await self._audit_repo.record(
            module="consultation",
            action="consultation.started",
            entity_type="consultation",
            entity_id=consultation.id,
            actor_user_id=actor.id,
            metadata={"visit_id": str(visit_id)},
        )
        await self._session.commit()
        return await self._consultation_repo.get_by_id(consultation.id)

    async def send_to_vitals(
        self, *, actor: User, consultation_id: UUID, reason: str | None
    ) -> Consultation:
        """The doctor-initiated vitals detour (§5.2) — the Visit itself
        stays `IN_CONSULTATION` throughout (§4.1 is explicit this is a
        Queue-routing change, not a Visit-status change), so there is no
        `VisitService` call here at all, only the Consultation's own
        status and the Queue re-route."""
        consultation = await self.get_consultation(consultation_id)
        if consultation.doctor_user_id != actor.id:
            raise PermissionDeniedError("This consultation is not assigned to you.")
        if consultation.status != ConsultationStatus.IN_PROGRESS:
            raise InvalidConsultationStatusTransitionError(
                consultation.status.value, ConsultationStatus.AWAITING_VITALS.value
            )

        consultation.status = ConsultationStatus.AWAITING_VITALS
        consultation.updated_by = actor.id
        await self._consultation_repo.add(consultation)

        await self._queue_service.route_to(
            actor=actor,
            visit_id=consultation.visit_id,
            destination=QueueDestination.VITALS,
            reason=reason or "doctor_requested_vitals",
        )

        await self._audit_repo.record(
            module="consultation",
            action="consultation.sent_to_vitals",
            entity_type="consultation",
            entity_id=consultation.id,
            actor_user_id=actor.id,
            metadata={"visit_id": str(consultation.visit_id), "reason": reason},
        )
        await self._session.commit()
        return await self._consultation_repo.get_by_id(consultation.id)

    async def resume_from_vitals(self, *, actor: User, visit_id: UUID) -> Consultation:
        """Called by the Vitals module once a targeted or full workup
        completes — see this module's docstring for the ownership split.
        Queue re-routing back to the doctor is the caller's
        responsibility, not this method's."""
        consultation = await self._consultation_repo.get_active_for_visit(visit_id)
        if consultation is None:
            raise NoActiveConsultationForVisitError
        if consultation.status != ConsultationStatus.AWAITING_VITALS:
            raise InvalidConsultationStatusTransitionError(
                consultation.status.value, ConsultationStatus.IN_PROGRESS.value
            )

        consultation.status = ConsultationStatus.IN_PROGRESS
        consultation.updated_by = actor.id
        await self._consultation_repo.add(consultation)
        await self._audit_repo.record(
            module="consultation",
            action="consultation.resumed_from_vitals",
            entity_type="consultation",
            entity_id=consultation.id,
            actor_user_id=actor.id,
            metadata={"visit_id": str(visit_id)},
        )
        await self._session.commit()
        return await self._consultation_repo.get_by_id(consultation.id)

    async def complete_consultation(
        self,
        *,
        actor: User,
        consultation_id: UUID,
        updates: dict[str, Any],
    ) -> Consultation:
        """Completes a Consultation that is `IN_PROGRESS` (not
        `AWAITING_VITALS` — a doctor cannot complete while vitals are
        still pending; `resume_from_vitals` must happen first). Moves
        the Visit to `WAITING_BILLING` (§7) and closes the Visit's
        active queue leg with no successor — Billing (not yet built) has
        no queue destination of its own, matching
        `QueueService.complete_current`'s documented purpose."""
        consultation = await self.get_consultation(consultation_id)
        if consultation.doctor_user_id != actor.id:
            raise PermissionDeniedError("This consultation is not assigned to you.")
        if consultation.status != ConsultationStatus.IN_PROGRESS:
            raise InvalidConsultationStatusTransitionError(
                consultation.status.value, ConsultationStatus.COMPLETED.value
            )

        for field in ("notes", "diagnosis", "prescription"):
            if field in updates:
                setattr(consultation, field, updates[field])

        consultation.status = ConsultationStatus.COMPLETED
        consultation.completed_at = datetime.now(UTC)
        consultation.updated_by = actor.id
        await self._consultation_repo.add(consultation)

        await self._visit_service.mark_waiting_billing(actor=actor, visit_id=consultation.visit_id)
        await self._queue_service.complete_current(actor=actor, visit_id=consultation.visit_id)

        await self._audit_repo.record(
            module="consultation",
            action="consultation.completed",
            entity_type="consultation",
            entity_id=consultation.id,
            actor_user_id=actor.id,
            metadata={"visit_id": str(consultation.visit_id)},
        )
        await self._session.commit()
        return await self._consultation_repo.get_by_id(consultation.id)

    async def get_consultation(self, consultation_id: UUID) -> Consultation:
        consultation = await self._consultation_repo.get_by_id(consultation_id)
        if consultation is None:
            raise ConsultationNotFoundError
        return consultation

    async def get_active_for_visit(self, visit_id: UUID) -> Consultation | None:
        return await self._consultation_repo.get_active_for_visit(visit_id)

    async def count_completed_by_doctor(self) -> dict[UUID, int]:
        """Read-only aggregate added for the Admin "Employee Accounts &
        Stats" page — see ConsultationRepository.count_completed_by_doctor."""
        return await self._consultation_repo.count_completed_by_doctor()
