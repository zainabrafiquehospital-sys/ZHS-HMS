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

from datetime import UTC, date as date_type, datetime
from decimal import Decimal
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import ValidationError
from app.modules.auth.models import User
from app.modules.visits.constants import QUEUE_TOKEN_PAD_WIDTH, QUEUE_TOKEN_PREFIX
from app.modules.visits.exceptions import (
    InvalidVisitStatusTransitionError,
    VisitDiscountExceedsAmountError,
    VisitNotFoundError,
)
from app.modules.visits.models import Visit, VisitStatus
from app.modules.visits.repository import VISIT_SORTABLE_COLUMNS, VisitRepository
from app.shared.audit.repository import AuditLogRepository
from app.shared.money import quantize_money

_ZERO = Decimal("0.00")

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
        # No separator between prefix and digits: QUEUE_TOKEN_PREFIX
        # ("Token #") already ends in "#", which reads as the number
        # marker itself — a trailing "-" would be redundant (e.g.
        # "Token #-000123"). Old GYN-prefixed tokens (which did use a
        # hyphen) are untouched in the DB; this only affects the format
        # of newly generated tokens going forward.
        value = await self._visit_repo.next_queue_token_value()
        return f"{QUEUE_TOKEN_PREFIX}{value:0{QUEUE_TOKEN_PAD_WIDTH}d}"

    async def register_visit(
        self,
        *,
        actor: User,
        patient_id: UUID,
        doctor_user_id: UUID | None,
        procedure: str,
        amount: Decimal,
        vitals_required: bool,
        discount_amount: Decimal = _ZERO,
        discount_reason: str | None = None,
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
        consultation/service.py's `start_consultation`).

        `discount_amount` (optional, defaults to none, 2026-08-19
        addition) is a flat discount off the entered `amount` — same
        shape as `PharmacyService.create_bill`'s identical parameter:
        validated here against `amount` (`VisitDiscountExceedsAmountError`
        if it exceeds it), never against the already-discounted stored
        value. The stored `Visit.amount` ends up already post-discount
        (`amount - discount_amount`) — deliberately the same column,
        same meaning it always had to every existing reader (Billing's
        Generate Invoice prefill, every revenue aggregate), so a
        registration-time discount flows through to what's ultimately
        billed and reported without any of those call sites needing to
        know a discount happened at all. `discount_reason` is always
        optional here, even when `discount_amount > 0` — the same
        product decision the medicine-bill discount already made, not
        Invoice's own required-reason rule. Independent of Billing's own
        separate Invoice-level discount, applied later at Generate
        Invoice time against whatever `Visit.amount` is by then — the
        two stack rather than conflict."""
        discount_amount = quantize_money(discount_amount) if discount_amount else _ZERO
        if discount_amount < _ZERO:
            raise ValidationError("discount_amount cannot be negative.")
        discount_reason = discount_reason.strip() if discount_reason else None
        if discount_amount == _ZERO:
            discount_reason = None
        amount = quantize_money(amount)
        if discount_amount > amount:
            raise VisitDiscountExceedsAmountError(str(amount))
        net_amount = amount - discount_amount

        visit = Visit(
            patient_id=patient_id,
            doctor_user_id=doctor_user_id,
            queue_token=await self._generate_queue_token(),
            procedure=procedure,
            amount=net_amount,
            discount_amount=discount_amount,
            discount_reason=discount_reason,
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
                "discount_amount": str(discount_amount),
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

    async def count_and_revenue_by_creator(self) -> dict[UUID, tuple[int, Decimal]]:
        """Read-only aggregate for the Admin "Employee Accounts & Stats"
        page — see VisitRepository.count_and_revenue_by_creator. Not
        used by Reception's own "My Revenue" tile as of 2026-08-19 (see
        `count_and_revenue_for_creator` below) — that used to look up
        its own row out of this same all-users result, which also
        exposed every other receptionist's revenue to anyone who called
        this endpoint directly."""
        return await self._visit_repo.count_and_revenue_by_creator()

    async def count_and_revenue_for_creator(
        self, user_id: UUID, *, since: datetime | None = None
    ) -> tuple[int, Decimal]:
        """Read-only, single-user aggregate backing Reception's own "My
        Revenue" tile (2026-08-19 addition) — see VisitRepository.
        count_and_revenue_for_creator. `since`, when given, is that
        receptionist's own "Clear Revenue" reset point; never excludes
        or touches any row, only narrows the count."""
        return await self._visit_repo.count_and_revenue_for_creator(user_id, since=since)

    async def list_visits(
        self,
        *,
        patient_id: UUID | None,
        doctor_user_id: UUID | None,
        created_by: UUID | None = None,
        date: date_type | None = None,
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
            created_by=created_by,
            date=date,
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

    # ------------------------------------------------------------------
    # Admin correction (2026-08-19 addition) — fixing/removing a visit
    # registered with wrong data (e.g. garbage test input). Deliberately
    # narrow and orthogonal to the status state machine above: neither
    # method here is a `mark_*` transition, and neither is exposed by
    # this module's own (read-only) router — both are called exclusively
    # from ReceptionService's admin-only composite actions, which is what
    # actually enforces the `reception:update_visit`/`reception:
    # delete_visit` RBAC gate and (for delete) the paid-invoice safety
    # check; VisitService itself stays free of any dependency on Billing
    # or Queue, exactly like every other method in this class.
    # ------------------------------------------------------------------

    async def update_visit_details(self, *, actor: User, visit_id: UUID, updates: dict) -> Visit:
        """Corrects `procedure`/`amount` — the only two fields on Visit
        itself that a mis-typed registration could get wrong (queue_token
        is permanent, status/doctor_user_id have their own dedicated
        transition methods, vitals_required is fixed by the routing
        decision already acted on). Not a generic field-level PATCH: the
        caller (ReceptionService.admin_update_visit) is responsible for
        only ever passing these two keys, mirroring how UserService.
        update_user's docstring reasons about never letting a generic
        update endpoint reach a field that has its own dedicated,
        business-rule-guarded mutation path."""
        visit = await self.get_visit(visit_id)
        if not updates:
            return visit

        for field in ("procedure", "amount"):
            if field in updates:
                value = updates[field]
                setattr(visit, field, quantize_money(value) if field == "amount" else value)

        visit.updated_by = actor.id
        await self._visit_repo.add(visit)
        await self._audit_repo.record(
            module="visits",
            action="visits.updated_by_admin",
            entity_type="visit",
            entity_id=visit.id,
            actor_user_id=actor.id,
            metadata={"fields": sorted(updates.keys())},
        )
        await self._session.commit()
        return await self._visit_repo.get_by_id(visit.id)

    async def delete_visit(self, *, actor: User, visit_id: UUID) -> None:
        """Soft-deletes the Visit (see BaseEntity/BaseRepository.
        soft_delete) — every existing Visit query already filters
        `deleted_at IS NULL`, so this is sufficient by itself to make the
        Visit disappear from every list/search/detail-view with no
        further code changes. Deliberately never a hard `DELETE`: `visit`
        is referenced by `queue_entry`/`consultation`/`vitals_record`/
        `pending_billing_item`/`invoice`, none of which declare an
        `ON DELETE` clause on their `visit_id` FK (confirmed against the
        schema — every one of those tables' rows must be deleted by hand,
        in FK order, before a hard `DELETE FROM visit` could succeed at
        all) — a hard delete would fail outright for virtually every real
        Visit, which always has at least a `queue_entry` from
        registration. Unconditional here by design: whether it is safe to
        call this at all (e.g. no paid invoice exists) is the caller's
        business-rule responsibility, not this method's — the same split
        `cancel_visit` already has with `ReceptionService.cancel_visit`
        (closing the active queue entry first is that caller's job too,
        not this module's)."""
        visit = await self.get_visit(visit_id)
        now = datetime.now(UTC)
        await self._visit_repo.soft_delete(visit, deleted_at=now, deleted_by=actor.id)
        await self._audit_repo.record(
            module="visits",
            action="visits.deleted_by_admin",
            entity_type="visit",
            entity_id=visit.id,
            actor_user_id=actor.id,
            metadata={"queue_token": visit.queue_token, "status": visit.status.value},
        )
        await self._session.commit()
