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
    ProcedureInactiveError,
    ProcedureNotFoundError,
    VisitAlreadyItemizedError,
    VisitDiscountExceedsAmountError,
    VisitHasSettledPaymentError,
    VisitNotFoundError,
    VisitNotItemizedError,
    VisitNotPayableError,
    VisitPaymentExceedsBalanceError,
)
from app.modules.visits.models import (
    ITEMIZED_PROCEDURE_PLACEHOLDER,
    Procedure,
    Visit,
    VisitPayment,
    VisitPaymentStatus,
    VisitProcedureItem,
    VisitStatus,
)
from app.modules.visits.repository import (
    PROCEDURE_SORTABLE_COLUMNS,
    VISIT_SORTABLE_COLUMNS,
    ProcedureRepository,
    VisitPaymentRepository,
    VisitProcedureItemRepository,
    VisitRepository,
)
from app.shared.audit.repository import AuditLogRepository
from app.shared.money import quantize_money
from app.shared.payment_method import PaymentMethod

_ZERO = Decimal("0.00")

# One (procedure_id, name, amount) resolved procedure line — `name`/
# `amount` are the already-resolved-and-locked values (catalog-derived
# when `procedure_id` is set, freely-provided when it's None), never
# the raw, not-yet-validated request shape. See `_resolve_procedures`.
ResolvedProcedure = tuple[UUID | None, str, Decimal]

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
        procedure_repository: ProcedureRepository,
        procedure_item_repository: VisitProcedureItemRepository,
        visit_payment_repository: VisitPaymentRepository,
    ) -> None:
        self._session = session
        self._visit_repo = visit_repository
        self._audit_repo = audit_repository
        self._procedure_repo = procedure_repository
        self._procedure_item_repo = procedure_item_repository
        self._visit_payment_repo = visit_payment_repository

    async def _generate_queue_token(self) -> str:
        # No separator between prefix and digits: QUEUE_TOKEN_PREFIX
        # ("Token #") already ends in "#", which reads as the number
        # marker itself — a trailing "-" would be redundant (e.g.
        # "Token #-000123"). Old GYN-prefixed tokens (which did use a
        # hyphen) are untouched in the DB; this only affects the format
        # of newly generated tokens going forward.
        value = await self._visit_repo.next_queue_token_value()
        return f"{QUEUE_TOKEN_PREFIX}{value:0{QUEUE_TOKEN_PAD_WIDTH}d}"

    async def _get_procedure(self, procedure_id: UUID) -> Procedure:
        procedure = await self._procedure_repo.get_by_id(procedure_id)
        if procedure is None:
            raise ProcedureNotFoundError
        return procedure

    async def _resolve_procedures(
        self, procedures: list[tuple[UUID | None, str | None, Decimal | None]]
    ) -> list[ResolvedProcedure]:
        """Turns the caller's raw `(procedure_id, manual_name,
        manual_amount)` request triples into resolved, trustworthy
        `(procedure_id, name, amount)` lines — shared by `register_visit`
        and `admin_replace_procedure_items` so both go through the exact
        same catalog-lookup/price-lock logic.

        A catalog-linked entry (`procedure_id` given) has its `name`/
        `amount` always re-derived from the Procedure row itself, never
        trusted from the caller (mirrors `PharmacyService.create_bill`'s
        identical `medicine_name_snapshot`/`unit_price_snapshot`
        derivation) — `ProcedureInactiveError` if it's been deactivated,
        exactly like a deactivated Medicine can't be billed. A manual
        entry (`procedure_id` is `None`) uses the caller's own
        `manual_name`/`manual_amount` directly, stripped/quantized."""
        resolved: list[ResolvedProcedure] = []
        for procedure_id, manual_name, manual_amount in procedures:
            if procedure_id is not None:
                procedure = await self._get_procedure(procedure_id)
                if not procedure.is_active:
                    raise ProcedureInactiveError(procedure.name)
                resolved.append((procedure_id, procedure.name, procedure.price))
            else:
                resolved.append((None, manual_name.strip(), quantize_money(manual_amount)))
        return resolved

    async def register_visit(
        self,
        *,
        actor: User,
        patient_id: UUID,
        doctor_user_id: UUID | None,
        procedures: list[tuple[UUID | None, str | None, Decimal | None]],
        vitals_required: bool,
        initial_payment_amount: Decimal,
        initial_payment_method: PaymentMethod,
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

        `procedures` (2026-08-21 addition, replacing the old single
        `procedure: str, amount: Decimal` pair) is one or more raw
        `(procedure_id, manual_name, manual_amount)` triples — resolved
        via `_resolve_procedures` into a real `VisitProcedureItem` row
        each, exactly like `PharmacyService.create_bill`'s own line
        items. The subtotal is `sum(item.amount for item in
        procedures)`; `Visit.amount` ends up `subtotal - discount_amount`
        — the exact same post-discount meaning `Visit.amount` has always
        had (see that column's own docstring), just sourced from a real
        item sum instead of one typed number. `Visit.procedure` itself
        is never populated from `procedures` — it is set to
        `ITEMIZED_PROCEDURE_PLACEHOLDER` and must never be displayed;
        see models.py's `VisitProcedureItem` docstring for the full
        "never retrofitted onto an older Visit" rationale, which is also
        why this is a wholly new code path rather than a variation on
        however a pre-2026-08-21 Visit was created.

        `discount_amount` (optional, defaults to none, 2026-08-19
        addition) is a flat discount off the procedures' combined
        subtotal — same shape as `PharmacyService.create_bill`'s
        identical parameter: validated here against that subtotal
        (`VisitDiscountExceedsAmountError` if it exceeds it), never
        against the already-discounted stored value. `discount_reason`
        is always optional here, even when `discount_amount > 0` — the
        same product decision the medicine-bill discount already made,
        not Invoice's own required-reason rule. Independent of Billing's
        own separate Invoice-level discount, applied later at Generate
        Invoice time against whatever `Visit.amount` is by then — the
        two stack rather than conflict.

        `initial_payment_amount`/`initial_payment_method` (2026-08-22
        addition, both required — unlike `PharmacyService.create_bill`'s
        optional equivalents) are this visit's registration-charge
        payment, collected at the same counter in the same call: a real
        payment is always collected at registration, full (the caller's
        UI defaults the amount to the net total) or a genuine partial
        advance — there is no "register unpaid" path here, so
        `initial_payment_amount` must be `> 0`. Validated against
        `net_amount` (the real, post-discount amount owed), never the
        pre-discount subtotal. Applied via the shared `_apply_payment`
        helper `record_payment` below also uses, producing exactly the
        `VisitPayment` row and `amount_paid`/`payment_status`/`paid_at`
        update a separate, immediately-following top-up call would —
        just in the same transaction as the Visit itself, so a visit is
        never left registered with no payment attempt recorded at all."""
        discount_amount = quantize_money(discount_amount) if discount_amount else _ZERO
        if discount_amount < _ZERO:
            raise ValidationError("discount_amount cannot be negative.")
        discount_reason = discount_reason.strip() if discount_reason else None
        if discount_amount == _ZERO:
            discount_reason = None

        resolved_procedures = await self._resolve_procedures(procedures)
        subtotal = sum((amount for _, _, amount in resolved_procedures), _ZERO)
        if discount_amount > subtotal:
            raise VisitDiscountExceedsAmountError(str(subtotal))
        net_amount = subtotal - discount_amount

        if initial_payment_amount <= _ZERO:
            raise ValidationError("initial_payment_amount must be greater than zero.")
        initial_payment_amount = quantize_money(initial_payment_amount)
        if initial_payment_amount > net_amount:
            raise VisitPaymentExceedsBalanceError(str(net_amount))

        visit = Visit(
            patient_id=patient_id,
            doctor_user_id=doctor_user_id,
            queue_token=await self._generate_queue_token(),
            procedure=ITEMIZED_PROCEDURE_PLACEHOLDER,
            amount=net_amount,
            discount_amount=discount_amount,
            discount_reason=discount_reason,
            vitals_required=vitals_required,
            status=VisitStatus.REGISTERED,
            amount_paid=_ZERO,
            payment_status=VisitPaymentStatus.UNPAID,
            created_by=actor.id,
            updated_by=actor.id,
        )
        await self._visit_repo.add(visit)
        for procedure_id, name, item_amount in resolved_procedures:
            await self._procedure_item_repo.add(
                VisitProcedureItem(
                    visit_id=visit.id,
                    procedure_id=procedure_id,
                    name=name,
                    amount=item_amount,
                    created_by=actor.id,
                    updated_by=actor.id,
                )
            )
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
        await self._apply_payment(
            visit=visit,
            actor=actor,
            amount=initial_payment_amount,
            payment_method=initial_payment_method,
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

    async def list_procedure_items(self, visit_id: UUID) -> list[VisitProcedureItem]:
        """Empty for every visit registered before 2026-08-21, by design
        — see models.py's `VisitProcedureItem` docstring. Callers use
        this emptiness as the one signal for whether to render the
        itemized breakdown or the visit's legacy `procedure`/`amount`
        fields."""
        return await self._procedure_item_repo.list_for_visit(visit_id)

    async def list_procedure_items_for_visits(
        self, visit_ids: list[UUID]
    ) -> dict[UUID, list[VisitProcedureItem]]:
        """Batched sibling of `list_procedure_items` — backs `GET
        /visits`'s list response (see VisitProcedureItemRepository.
        list_for_visits's own docstring for the N+1-avoidance shape)."""
        return await self._procedure_item_repo.list_for_visits(visit_ids)

    async def list_by_ids(self, visit_ids: list[UUID]) -> list[Visit]:
        """Thin passthrough to `VisitRepository.list_by_ids` — backs
        the Patient History unified feed's own page-enrichment step
        (app/modules/patient_history/service.py), which resolves a
        page of ids across Visit/MedicineBill/LabBill first, then
        looks up each type's own full rows in one batched call."""
        return await self._visit_repo.list_by_ids(visit_ids)

    # ------------------------------------------------------------------
    # Registration-charge payment tracking (2026-08-22 addition) —
    # mirrors PharmacyService's own "_apply_payment/record_payment"
    # section almost exactly (see that module's own comments for the
    # shared rationale); the one structural difference is that Visit's
    # very first payment is never optional (see `register_visit`'s own
    # docstring), so there is no "freshly created, always UNPAID by
    # construction" caller the way `create_bill`'s optional initial
    # payment has — `register_visit` always calls `_apply_payment` too.
    # ------------------------------------------------------------------

    async def _apply_payment(
        self, *, visit: Visit, actor: User, amount: Decimal, payment_method: PaymentMethod
    ) -> bool:
        """Shared by `register_visit`'s always-present initial payment
        and `record_payment`'s top-up payment below — validates `amount`
        against the remaining balance, mutates `visit.amount_paid`/
        `payment_status`/`paid_at` in memory, stages a new `VisitPayment`
        audit row, and records the audit-log entry. Never commits.
        Returns whether this payment brought the visit's registration
        charge to fully `PAID`.

        Assumes the visit is already known payable — `record_payment`
        checks that itself before calling this; `register_visit`'s visit
        is always freshly created and `UNPAID` by construction, so it
        never needs the check."""
        if amount <= _ZERO:
            raise ValidationError("Payment amount must be greater than zero.")
        amount = quantize_money(amount)

        remaining = visit.amount - visit.amount_paid
        if amount > remaining:
            raise VisitPaymentExceedsBalanceError(str(remaining))

        visit.amount_paid = visit.amount_paid + amount
        visit.updated_by = actor.id
        fully_paid = visit.amount_paid == visit.amount
        if fully_paid:
            visit.payment_status = VisitPaymentStatus.PAID
            visit.paid_at = datetime.now(UTC)
        else:
            visit.payment_status = VisitPaymentStatus.PARTIALLY_PAID
        await self._visit_repo.add(visit)
        await self._visit_payment_repo.add(
            VisitPayment(
                visit_id=visit.id,
                amount=amount,
                payment_method=payment_method,
                created_by=actor.id,
                updated_by=actor.id,
            )
        )
        await self._audit_repo.record(
            module="visits",
            action="visits.payment_recorded",
            entity_type="visit",
            entity_id=visit.id,
            actor_user_id=actor.id,
            metadata={
                "amount": str(amount),
                "payment_method": payment_method.value,
                "fully_paid": fully_paid,
            },
        )
        return fully_paid

    async def record_payment(
        self, *, actor: User, visit_id: UUID, amount: Decimal, payment_method: PaymentMethod
    ) -> Visit:
        """Records an *additional* payment against an already-registered
        visit's registration charge — topping up toward the remaining
        balance on a later visit/call (the C-section example this
        feature was built for), not the primary way a visit gets its
        first payment (see `register_visit`'s always-required initial
        payment for that). Called from Billing's own `billing:manage`-
        gated endpoint (see BillingService.record_visit_payment) rather
        than a Reception one — see this feature's design notes for why:
        the Billing screen is where this action's UI lives, and every
        other mutating action there already requires `billing:manage`.

        Rejects outright against a visit with no payment tracking at all
        (`payment_status IS NULL` — predates this feature, see `Visit.
        payment_status`'s own column docstring) or already fully `PAID`.
        Reads the Visit with `SELECT ... FOR UPDATE`
        (`VisitRepository.get_for_update`), not the plain `get_visit` —
        the identical read-modify-write-on-money-field race-safety
        `InvoiceRepository`/`MedicineBillRepository`'s own
        `get_for_update` protect against."""
        visit = await self._visit_repo.get_for_update(visit_id)
        if visit is None:
            raise VisitNotFoundError
        if visit.payment_status is None or visit.payment_status == VisitPaymentStatus.PAID:
            raise VisitNotPayableError(
                visit.payment_status.value if visit.payment_status is not None else "untracked"
            )

        await self._apply_payment(
            visit=visit, actor=actor, amount=amount, payment_method=payment_method
        )
        await self._session.commit()
        return await self._visit_repo.get_by_id(visit.id)

    async def list_payments(self, visit_id: UUID) -> list[VisitPayment]:
        return await self._visit_payment_repo.list_for_visit(visit_id)

    async def get_pending_revenue(self) -> Decimal:
        """Read-only aggregate for the Admin Overview's "Pending
        Revenue" tile — see VisitRepository.sum_pending_amount's own
        docstring for why this is deliberately all-time, never
        day-scoped."""
        return await self._visit_repo.sum_pending_amount()

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
        start_date: date_type | None = None,
        end_date: date_type | None = None,
        unassigned_only: bool = False,
        status: VisitStatus | None,
        patient_ids: list[UUID] | None = None,
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
            start_date=start_date,
            end_date=end_date,
            unassigned_only=unassigned_only,
            status=status,
            patient_ids=patient_ids,
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
        only ever passing these keys, mirroring how UserService.
        update_user's docstring reasons about never letting a generic
        update endpoint reach a field that has its own dedicated,
        business-rule-guarded mutation path.

        2026-08-21 bifurcation: only applies to a visit registered
        before 2026-08-21 (one with no `VisitProcedureItem` rows at
        all) — `procedure`/`amount` are its only record of what was
        billed, exactly as they have always been, so this method's
        original behavior is completely unchanged for it. A visit with
        procedure items rejects `procedure`/`amount` outright
        (`VisitAlreadyItemizedError`) — its procedures are corrected
        through `admin_replace_procedure_items` instead, never through
        these now-unused flat fields. See models.py's
        `VisitProcedureItem` docstring for why a legacy visit is never
        itemized *by this method* either — that path is deliberately
        out of scope this pass (see `admin_replace_procedure_items`'s
        own docstring).

        2026-08-22 addition: also rejects outright
        (`VisitHasSettledPaymentError`) once a *new-style* visit
        (`payment_status` not `NULL`) has any recorded payment
        (`PARTIALLY_PAID`/`PAID`) — editing `amount` on the same row a
        payment is tracked against would desynchronize `amount_paid`
        from the now-changed total, the same integrity risk
        `MedicineBillHasSettledPaymentError` guards against. Deliberately
        scoped to `not in (None, UNPAID)`, never just `!= UNPAID` — a
        visit with `payment_status IS NULL` (predates payment tracking
        entirely) is structurally exempt, so this is a real behavior
        change only for a visit registered from now on, never for any
        visit that already exists."""
        visit = await self.get_visit(visit_id)
        if not updates:
            return visit
        if "procedure" in updates or "amount" in updates:
            if visit.payment_status not in (None, VisitPaymentStatus.UNPAID):
                raise VisitHasSettledPaymentError
            if await self._procedure_item_repo.list_for_visit(visit_id):
                raise VisitAlreadyItemizedError

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

    async def admin_replace_procedure_items(
        self,
        *,
        actor: User,
        visit_id: UUID,
        procedures: list[tuple[UUID | None, str | None, Decimal | None]],
    ) -> Visit:
        """Replaces a visit's *entire* procedure-item set in one call —
        the itemized-era sibling of `update_visit_details`'s flat
        `procedure`/`amount` edit, for a visit that already has at
        least one `VisitProcedureItem` (2026-08-21 addition). Rejects
        outright (`VisitNotItemizedError`) against a visit with none —
        a pre-2026-08-21 visit's procedures are corrected through
        `update_visit_details`'s original flat fields instead; this
        method deliberately never itemizes a legacy visit for the first
        time (a confirmed, explicit scope decision — see this module's
        own docstring).

        Soft-deletes every existing item, resolves the caller's new set
        through the exact same `_resolve_procedures` catalog-lookup/
        price-lock logic `register_visit` uses, and recomputes
        `Visit.amount` from the new subtotal against the visit's
        EXISTING, untouched `discount_amount` (re-validating
        `VisitDiscountExceedsAmountError` in case the new, possibly
        smaller subtotal no longer covers it) — `discount_amount`/
        `discount_reason` themselves are never read from `updates` or
        modified by this method at all (a separately confirmed, explicit
        scope decision: procedure correction and discount correction
        stay fully independent actions, exactly as `update_visit_details`
        has never touched discount either)."""
        visit = await self.get_visit(visit_id)
        existing_items = await self._procedure_item_repo.list_for_visit(visit_id)
        if not existing_items:
            raise VisitNotItemizedError
        if not procedures:
            raise ValidationError("At least one procedure is required.")

        resolved_procedures = await self._resolve_procedures(procedures)
        subtotal = sum((amount for _, _, amount in resolved_procedures), _ZERO)
        if visit.discount_amount > subtotal:
            raise VisitDiscountExceedsAmountError(str(subtotal))

        now = datetime.now(UTC)
        for item in existing_items:
            await self._procedure_item_repo.soft_delete(item, deleted_at=now, deleted_by=actor.id)
        for procedure_id, name, item_amount in resolved_procedures:
            await self._procedure_item_repo.add(
                VisitProcedureItem(
                    visit_id=visit.id,
                    procedure_id=procedure_id,
                    name=name,
                    amount=item_amount,
                    created_by=actor.id,
                    updated_by=actor.id,
                )
            )

        visit.amount = subtotal - visit.discount_amount
        visit.updated_by = actor.id
        await self._visit_repo.add(visit)
        await self._audit_repo.record(
            module="visits",
            action="visits.procedure_items_replaced_by_admin",
            entity_type="visit",
            entity_id=visit.id,
            actor_user_id=actor.id,
            metadata={"item_count": len(resolved_procedures)},
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

    # ------------------------------------------------------------------
    # Procedure catalog (2026-08-21 addition, Admin-only, procedures:manage)
    # — mirrors PharmacyService's own "Medicine price list" section
    # exactly. Unlike Medicine, this catalog also supports a genuine
    # delete (not only activate/deactivate) — see models.py's
    # `Procedure` docstring for why that's safe: a `VisitProcedureItem`
    # already snapshots its name/price at add-time, so deleting (or
    # deactivating) the catalog entry never affects any visit that
    # already used it, only prevents *future* selection.
    # ------------------------------------------------------------------

    async def create_procedure(self, *, actor: User, name: str, price: Decimal) -> Procedure:
        procedure = Procedure(
            name=name,
            price=quantize_money(price),
            is_active=True,
            created_by=actor.id,
            updated_by=actor.id,
        )
        await self._procedure_repo.add(procedure)
        await self._audit_repo.record(
            module="visits",
            action="visits.procedure_created",
            entity_type="procedure",
            entity_id=procedure.id,
            actor_user_id=actor.id,
            metadata={"name": name},
        )
        await self._session.commit()
        return await self._get_procedure(procedure.id)

    async def get_procedure(self, procedure_id: UUID) -> Procedure:
        return await self._get_procedure(procedure_id)

    async def update_procedure(
        self, *, actor: User, procedure_id: UUID, updates: dict
    ) -> Procedure:
        """Partial update — `updates` comes straight from
        `UpdateProcedureRequest.model_dump(exclude_unset=True)`, same
        `exclude_unset` semantics as `PharmacyService.update_medicine`."""
        procedure = await self._get_procedure(procedure_id)
        if not updates:
            return procedure

        for field in ("name", "price", "is_active"):
            if field in updates:
                value = updates[field]
                if field == "price" and value is not None:
                    value = quantize_money(value)
                setattr(procedure, field, value)

        procedure.updated_by = actor.id
        await self._procedure_repo.add(procedure)
        await self._audit_repo.record(
            module="visits",
            action="visits.procedure_updated",
            entity_type="procedure",
            entity_id=procedure.id,
            actor_user_id=actor.id,
            metadata={"fields": sorted(updates.keys())},
        )
        await self._session.commit()
        return await self._get_procedure(procedure.id)

    async def delete_procedure(self, *, actor: User, procedure_id: UUID) -> None:
        """Soft-deletes a Procedure catalog entry — safe regardless of
        whether it has ever been selected for a visit, see this
        section's own docstring."""
        procedure = await self._get_procedure(procedure_id)
        now = datetime.now(UTC)
        await self._procedure_repo.soft_delete(procedure, deleted_at=now, deleted_by=actor.id)
        await self._audit_repo.record(
            module="visits",
            action="visits.procedure_deleted",
            entity_type="procedure",
            entity_id=procedure_id,
            actor_user_id=actor.id,
            metadata={"name": procedure.name},
        )
        await self._session.commit()

    async def search_procedures(self, *, search: str, limit: int = 20) -> list[Procedure]:
        return await self._procedure_repo.search_active(search=search, limit=limit)

    async def list_procedures(
        self, *, search: str | None, sort_by: str, sort_desc: bool, page: int, page_size: int
    ) -> tuple[list[Procedure], int]:
        sort_column = PROCEDURE_SORTABLE_COLUMNS[sort_by]
        return await self._procedure_repo.list_all(
            search=search,
            sort_column=sort_column,
            sort_desc=sort_desc,
            limit=page_size,
            offset=(page - 1) * page_size,
        )
