"""Visit Management business logic — see
app/modules/patients/service.py's identical module docstring for why
this doesn't subclass the shared `BaseService`.

This is the one place Phase 6 architecture §4.1's Visit Lifecycle State
Machine is enforced. Every other module (Reception, Vitals, Consultation,
Billing) that needs to move a Visit forward calls one of this service's
`mark_*` methods rather than writing `visit.status` directly — that is
what makes "no module may write a Visit status that isn't a valid
transition from its current status" (§4.1) an enforced invariant instead
of a convention every caller has to remember on its own."""

from decimal import Decimal
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.auth.models import User
from app.modules.visits.constants import QUEUE_TOKEN_PAD_WIDTH, QUEUE_TOKEN_PREFIX
from app.modules.visits.exceptions import InvalidVisitStatusTransitionError, VisitNotFoundError
from app.modules.visits.models import Visit, VisitStatus
from app.modules.visits.repository import VISIT_SORTABLE_COLUMNS, VisitRepository
from app.shared.audit.repository import AuditLogRepository
from app.shared.money import quantize_money

# Phase 6 architecture §4.1's Visit Lifecycle State Machine, plus the
# `COMPLETED -> PAYMENT_PENDING` reopening transition added by the
# architecture's own final self-review (§26) to close the gap between
# §4.1 and §7.4 (a new Outstanding Invoice created after a Visit already
# reached COMPLETED needs a status to move back to). §4.1 is explicit
# that a doctor-initiated vitals detour mid-consultation (§5.2) does NOT
# move the Visit out of IN_CONSULTATION — only Queue routing changes —
# so there is deliberately no IN_CONSULTATION -> WAITING_VITALS edge
# here; that transition belongs to the not-yet-built Queue module, on
# the Queue Entry, never on the Visit itself.
VALID_TRANSITIONS: dict[VisitStatus, frozenset[VisitStatus]] = {
    VisitStatus.REGISTERED: frozenset(
        {VisitStatus.WAITING_VITALS, VisitStatus.WAITING_DOCTOR, VisitStatus.CANCELLED}
    ),
    VisitStatus.WAITING_VITALS: frozenset({VisitStatus.WAITING_DOCTOR, VisitStatus.CANCELLED}),
    VisitStatus.WAITING_DOCTOR: frozenset({VisitStatus.IN_CONSULTATION, VisitStatus.CANCELLED}),
    VisitStatus.IN_CONSULTATION: frozenset({VisitStatus.WAITING_BILLING, VisitStatus.CANCELLED}),
    VisitStatus.WAITING_BILLING: frozenset(
        {VisitStatus.PAYMENT_PENDING, VisitStatus.COMPLETED, VisitStatus.CANCELLED}
    ),
    VisitStatus.PAYMENT_PENDING: frozenset({VisitStatus.COMPLETED, VisitStatus.CANCELLED}),
    VisitStatus.COMPLETED: frozenset({VisitStatus.PAYMENT_PENDING}),
    VisitStatus.CANCELLED: frozenset(),
}


class VisitService:
    def __init__(
        self,
        session: AsyncSession,
        visit_repository: VisitRepository,
        audit_repository: AuditLogRepository,
    ) -> None:
        self._session = session
        self._visit_repo = visit_repository
        self._audit_repo = audit_repository

    async def _generate_queue_token(self) -> str:
        value = await self._visit_repo.next_queue_token_value()
        return f"{QUEUE_TOKEN_PREFIX}-{value:0{QUEUE_TOKEN_PAD_WIDTH}d}"

    async def register_visit(
        self,
        *,
        actor: User,
        patient_id: UUID,
        doctor_user_id: UUID | None,
        procedure: str,
        amount: Decimal,
        vitals_required: bool,
    ) -> Visit:
        """Creates a new Visit in `REGISTERED` status. Called by the
        Reception module's registration flow (§6) — Reception's own
        service is responsible for having already created/looked up the
        Patient and decided `vitals_required`; this method only persists
        the Visit itself and immediately advances it to its initial
        routing status (`WAITING_VITALS` or `WAITING_DOCTOR`) per §5.1,
        since a freshly `REGISTERED` Visit with no queue destination is
        never a state Reception actually wants to leave a patient in.

        `doctor_user_id=None` means Reception found no online doctor to
        auto-assign — registration proceeds anyway (never blocked on
        doctor availability); the Visit is claimed by whichever doctor
        starts its consultation first (see
        consultation/service.py's `start_consultation`)."""
        visit = Visit(
            patient_id=patient_id,
            doctor_user_id=doctor_user_id,
            queue_token=await self._generate_queue_token(),
            procedure=procedure,
            amount=quantize_money(amount),
            vitals_required=vitals_required,
            status=VisitStatus.REGISTERED,
            created_by=actor.id,
            updated_by=actor.id,
        )
        await self._visit_repo.add(visit)
        await self._audit_repo.record(
            module="visits",
            action="visits.registered",
            entity_type="visit",
            entity_id=visit.id,
            actor_user_id=actor.id,
            metadata={
                "queue_token": visit.queue_token,
                "patient_id": str(patient_id),
                "doctor_user_id": str(doctor_user_id) if doctor_user_id else None,
                "vitals_required": vitals_required,
            },
        )
        target = VisitStatus.WAITING_VITALS if vitals_required else VisitStatus.WAITING_DOCTOR
        await self._transition(actor=actor, visit=visit, target=target)
        await self._session.commit()
        return await self._visit_repo.get_by_id(visit.id)

    async def get_visit(self, visit_id: UUID) -> Visit:
        visit = await self._visit_repo.get_by_id(visit_id)
        if visit is None:
            raise VisitNotFoundError
        return visit

    async def get_by_queue_token(self, queue_token: str) -> Visit | None:
        """Read-only lookup added for the Search module (Phase 6 §21) —
        a receptionist looking up a patient by the token printed on
        their slip. Returns `None` rather than raising when no Visit
        matches, unlike `get_visit`: a search miss is an expected,
        routine outcome here, not an error condition."""
        return await self._visit_repo.get_by_queue_token(queue_token)

    async def count_by_status(self) -> dict[VisitStatus, int]:
        """Read-only aggregate added for the Dashboard module (§22)."""
        return await self._visit_repo.count_by_status()

    async def list_visits(
        self,
        *,
        patient_id: UUID | None,
        doctor_user_id: UUID | None,
        unassigned_only: bool = False,
        status: VisitStatus | None,
        sort_by: str,
        sort_desc: bool,
        page: int,
        page_size: int,
    ) -> tuple[list[Visit], int]:
        sort_column = VISIT_SORTABLE_COLUMNS[sort_by]
        return await self._visit_repo.search(
            patient_id=patient_id,
            doctor_user_id=doctor_user_id,
            unassigned_only=unassigned_only,
            status=status,
            sort_column=sort_column,
            sort_desc=sort_desc,
            limit=page_size,
            offset=(page - 1) * page_size,
        )

    async def assign_doctor(self, *, actor: User, visit_id: UUID, doctor_user_id: UUID) -> bool:
        """Claims an unassigned Visit for `doctor_user_id` — a no-op
        (returns `False`) if the Visit was already assigned (to anyone,
        including `doctor_user_id` itself) by the time this runs. Called
        by Consultation's `start_consultation` before it opens a
        Consultation, never exposed as its own public endpoint (see
        this module's schemas.py docstring: no generic Visit-mutating
        endpoint exists)."""
        claimed = await self._visit_repo.assign_doctor_if_unassigned(
            visit_id=visit_id, doctor_user_id=doctor_user_id
        )
        if claimed:
            await self._audit_repo.record(
                module="visits",
                action="visits.doctor_claimed",
                entity_type="visit",
                entity_id=visit_id,
                actor_user_id=actor.id,
                metadata={"doctor_user_id": str(doctor_user_id)},
            )
        return claimed

    async def _transition(self, *, actor: User, visit: Visit, target: VisitStatus) -> Visit:
        """The single choke point every `mark_*` method below funnels
        through — see this module's docstring. Not exposed publicly:
        callers use the named `mark_*` methods so a caller can never
        request an arbitrary target status a specific business action
        doesn't actually correspond to."""
        allowed = VALID_TRANSITIONS[visit.status]
        if target not in allowed:
            raise InvalidVisitStatusTransitionError(visit.status.value, target.value)
        previous = visit.status
        visit.status = target
        visit.updated_by = actor.id
        await self._visit_repo.add(visit)
        await self._audit_repo.record(
            module="visits",
            action="visits.status_changed",
            entity_type="visit",
            entity_id=visit.id,
            actor_user_id=actor.id,
            metadata={"from": previous.value, "to": target.value},
        )
        return visit

    async def mark_waiting_doctor(self, *, actor: User, visit_id: UUID) -> Visit:
        """Called by the Vitals module once a full or targeted vitals
        workup completes (§5.1/§5.2) — Vitals never writes `visit.status`
        directly, it calls this."""
        visit = await self.get_visit(visit_id)
        await self._transition(actor=actor, visit=visit, target=VisitStatus.WAITING_DOCTOR)
        await self._session.commit()
        return await self._visit_repo.get_by_id(visit.id)

    async def mark_in_consultation(self, *, actor: User, visit_id: UUID) -> Visit:
        """Called by the Consultation module when a doctor opens the
        Visit (§5)."""
        visit = await self.get_visit(visit_id)
        await self._transition(actor=actor, visit=visit, target=VisitStatus.IN_CONSULTATION)
        await self._session.commit()
        return await self._visit_repo.get_by_id(visit.id)

    async def mark_waiting_billing(self, *, actor: User, visit_id: UUID) -> Visit:
        """Called by the Consultation module when a doctor completes a
        Consultation with billable items pending Reception review (§7)."""
        visit = await self.get_visit(visit_id)
        await self._transition(actor=actor, visit=visit, target=VisitStatus.WAITING_BILLING)
        await self._session.commit()
        return await self._visit_repo.get_by_id(visit.id)

    async def mark_payment_pending(self, *, actor: User, visit_id: UUID) -> Visit:
        """Called by the Billing module once Reception has an Invoice in
        `Pending Payment`/`Partially Paid` state against this Visit
        (§7.4) — including the `COMPLETED -> PAYMENT_PENDING` reopening
        transition when a new Outstanding Invoice is created after the
        Visit already completed."""
        visit = await self.get_visit(visit_id)
        await self._transition(actor=actor, visit=visit, target=VisitStatus.PAYMENT_PENDING)
        await self._session.commit()
        return await self._visit_repo.get_by_id(visit.id)

    async def mark_completed(self, *, actor: User, visit_id: UUID) -> Visit:
        """Called by the Billing module once the Visit's Invoice reaches
        `Paid` (or Reception closes a Visit that required no payment)."""
        visit = await self.get_visit(visit_id)
        await self._transition(actor=actor, visit=visit, target=VisitStatus.COMPLETED)
        await self._session.commit()
        return await self._visit_repo.get_by_id(visit.id)

    async def cancel_visit(self, *, actor: User, visit_id: UUID) -> Visit:
        """Callable by Reception at any point before completion (§4.1) —
        `CANCELLED` is reachable from every non-terminal status."""
        visit = await self.get_visit(visit_id)
        await self._transition(actor=actor, visit=visit, target=VisitStatus.CANCELLED)
        await self._session.commit()
        return await self._visit_repo.get_by_id(visit.id)
