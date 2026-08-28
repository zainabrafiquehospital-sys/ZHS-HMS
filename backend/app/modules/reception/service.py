"""Reception business logic — the composite "register a visit" action
(Phase 6 architecture §6). Reception owns no table of its own (see
app/modules/reception/__init__.py and the architecture's module-
ownership table, §3): this service purely orchestrates calls into
PatientService, VisitService, and QueueService, each of which already
owns and commits its own unit of work.

Atomicity note: this orchestration is *not* a single database
transaction spanning Patient + Visit + QueueEntry — each of the three
services this composes commits internally (the same established pattern
already used throughout this codebase; see PatientService/VisitService/
QueueService's own module docstrings), and Patient, Visit, and
QueueEntry are three separate aggregates, not one. A failure partway
through (e.g. Visit creation succeeds but the QueueEntry insert fails on
an infrastructure error) can in principle leave a Visit without an
active queue entry — there is no plausible *business-rule* rejection
that would cause this for a brand-new Visit (a fresh QueueEntry has no
prior active leg to close and cannot violate the one-active-entry
constraint), so the realistic failure mode is limited to genuine
infrastructure faults, not validation failures. No compensating-
transaction/saga logic is implemented for that narrow case — an
explicit, documented scope decision for this build, not an oversight."""

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.auth.models import User
from app.modules.billing.models import InvoiceStatus
from app.modules.billing.repository import InvoiceRepository
from app.modules.lab.repository import LabBillRepository
from app.modules.patients.models import Patient
from app.modules.patients.service import PatientService
from app.modules.pharmacy.repository import MedicineBillRepository
from app.modules.queue.models import QueueDestination, QueueEntry
from app.modules.queue.service import QueueService
from app.modules.reception.exceptions import (
    DoctorNotAvailableForAssignmentError,
    VisitHasSettledInvoiceError,
)
from app.modules.reception.repository import ReceptionRepository
from app.modules.visits.models import Visit
from app.modules.visits.service import VisitService
from app.shared.audit.repository import AuditLogRepository
from app.shared.payment_method import PaymentMethod

# Invoice statuses that represent money genuinely collected — see
# ReceptionService.admin_delete_visit and VisitHasSettledInvoiceError's
# own docstring for the full reasoning behind blocking on exactly these
# two and no others.
_SETTLED_INVOICE_STATUSES = (InvoiceStatus.PAID, InvoiceStatus.PARTIALLY_PAID)

# The generic audit_log `(entity_type, entity_id, action)` this module's
# "Clear Revenue" feature (2026-08-19) reuses as a receptionist's own
# revenue-counter reset point — see ReceptionService.get_own_revenue's
# own docstring for the full mechanism.
_REVENUE_CLEARED_ENTITY_TYPE = "user"
_REVENUE_CLEARED_ACTION = "reception.revenue_cleared"

# The rolling window "My Revenue" now always caps itself to (2026-08-19
# fix) — see get_own_revenue's own docstring for why this replaced the
# original "since last clear, or all-time if never cleared" behavior.
_REVENUE_AUTO_WINDOW = timedelta(hours=24)


class ReceptionService:
    def __init__(
        self,
        session: AsyncSession,
        patient_service: PatientService,
        visit_service: VisitService,
        queue_service: QueueService,
        audit_repository: AuditLogRepository,
        reception_repository: ReceptionRepository,
        invoice_repository: InvoiceRepository,
        medicine_bill_repository: MedicineBillRepository,
        lab_bill_repository: LabBillRepository,
    ) -> None:
        """`session` here must be the exact same `AsyncSession` instance
        `audit_repository` was built with (see dependencies.py) — this
        service only ever uses it to commit its own audit-log write; the
        Patient/Visit/Queue writes above are already durably committed
        by the services that made them by the time this service ever
        touches `session` (see this module's docstring for why that's a
        deliberate, documented scope decision rather than a single
        cross-aggregate transaction).

        `invoice_repository` (2026-08-19 addition) is a narrow, strictly
        read-only exception to this module's usual "orchestrate Patient/
        Visit/Queue only" shape — added solely so `admin_delete_visit`
        can check for a settled Invoice before deleting a Visit.
        Reception reading Billing here is the same kind of deliberate,
        justified, read-only cross-module check as ReceptionRepository.
        find_least_busy_available_doctor already makes into Auth's own
        tables — it never writes to an Invoice, and it changes nothing
        about how Billing itself works.

        `medicine_bill_repository` (2026-08-19 addition, same shape as
        `invoice_repository` above) — narrow, strictly read-only,
        added solely so `get_own_revenue` can include the "Medicines"
        half of a receptionist's own revenue tile alongside visits.

        `lab_bill_repository` (Step 4 addition, same shape as
        `medicine_bill_repository` above) — narrow, strictly read-only,
        added solely so `get_own_revenue` can include the "Lab" third
        of a receptionist's own revenue tile alongside visits and
        medicines."""
        self._session = session
        self._patient_service = patient_service
        self._visit_service = visit_service
        self._queue_service = queue_service
        self._audit_repo = audit_repository
        self._reception_repo = reception_repository
        self._invoice_repo = invoice_repository
        self._medicine_bill_repo = medicine_bill_repository
        self._lab_bill_repo = lab_bill_repository

    async def register_visit(
        self,
        *,
        actor: User,
        patient_id: UUID | None,
        new_patient: dict[str, Any] | None,
        doctor_user_id: UUID | None,
        procedures: list[tuple[UUID | None, str | None, Decimal | None]],
        vitals_required: bool,
        initial_payment_amount: Decimal,
        initial_payment_method: PaymentMethod,
        discount_amount: Decimal = Decimal("0.00"),
        discount_reason: str | None = None,
    ) -> tuple[Patient, Visit, QueueEntry]:
        """`patient_id` XOR `new_patient` is enforced at the schema layer
        (RegisterVisitRequest) before this is ever called — this method
        trusts that precondition rather than re-validating it, matching
        this codebase's convention that request-shape validation belongs
        at the API boundary, not duplicated in the service layer.

        `doctor_user_id=None` (the default, and still the common case)
        means staff left the doctor field blank — this method
        auto-assigns the least-busy currently-online doctor (see
        ReceptionRepository.find_least_busy_available_doctor's
        docstring for what "online" means) when one exists; if none is
        available, registration proceeds with the Visit unassigned
        rather than blocking (Phase 6 fast-registration §4) — any doctor
        claims it the moment they start its consultation (see
        consultation/service.py's `start_consultation`). An explicit
        `doctor_user_id` (2026-08-24 addition — Reception's doctor-
        selection dropdown, RegisterVisitForm.jsx) skips auto-assignment
        entirely and is validated instead via
        ReceptionRepository.get_doctor_by_id, raising
        DoctorNotAvailableForAssignmentError if it doesn't resolve to a
        real, active, consultation-capable user — deliberately not
        required to be online, so Reception can still route to a
        specific doctor who's temporarily offline.

        `procedures` (2026-08-21 addition, replacing the old single
        `procedure`/`amount` pair) passes straight through to
        VisitService.register_visit, which owns the actual catalog-
        lookup/price-lock/subtotal logic — see that method's own
        docstring.

        `discount_amount`/`discount_reason` (both optional, 2026-08-19
        addition) pass straight through too, which owns the actual
        validation and the amount/discount arithmetic — see that
        method's own docstring for the full mechanism and why it makes a
        registration-time discount actually flow through to Billing and
        every revenue read.

        `initial_payment_amount`/`initial_payment_method` (both
        required, 2026-08-22 addition) pass straight through as well —
        VisitService.register_visit owns the actual payment application;
        see that method's own docstring for why this is never optional
        the way Pharmacy's/Billing's equivalent parameters are."""
        if patient_id is not None:
            patient = await self._patient_service.get_patient(patient_id)
        else:
            patient = await self._patient_service.register_patient(actor=actor, **new_patient)

        if doctor_user_id is None:
            available_doctor = await self._reception_repo.find_least_busy_available_doctor()
            doctor_user_id = available_doctor.id if available_doctor is not None else None
        else:
            # An explicit selection (2026-08-24 addition — Reception's
            # doctor-selection dropdown, RegisterVisitForm.jsx)
            # bypasses least-busy auto-assignment entirely, but is
            # never trusted blindly: it must still resolve to a real,
            # ACTIVE, consultation:start-granting user, online or not
            # (see get_doctor_by_id's own docstring for why "online" is
            # deliberately not required here, unlike the auto-assign
            # path above).
            selected_doctor = await self._reception_repo.get_doctor_by_id(doctor_user_id)
            if selected_doctor is None:
                raise DoctorNotAvailableForAssignmentError

        visit = await self._visit_service.register_visit(
            actor=actor,
            patient_id=patient.id,
            doctor_user_id=doctor_user_id,
            procedures=procedures,
            vitals_required=vitals_required,
            initial_payment_amount=initial_payment_amount,
            initial_payment_method=initial_payment_method,
            discount_amount=discount_amount,
            discount_reason=discount_reason,
        )

        destination = QueueDestination.VITALS if vitals_required else QueueDestination.DOCTOR
        queue_entry = await self._queue_service.route_to(
            actor=actor, visit_id=visit.id, destination=destination, reason="initial_registration"
        )

        await self._audit_repo.record(
            module="reception",
            action="reception.visit_registered",
            entity_type="visit",
            entity_id=visit.id,
            actor_user_id=actor.id,
            metadata={
                "patient_id": str(patient.id),
                "queue_token": visit.queue_token,
                "destination": destination.value,
            },
        )
        await self._session.commit()
        return patient, visit, queue_entry

    async def list_doctors_for_selection(self) -> list[tuple[User, bool]]:
        """Backs `GET /reception/doctors` (2026-08-24 addition) —
        Reception's doctor-selection dropdown in RegisterVisitForm.jsx.
        Thin pass-through to ReceptionRepository.list_doctors_for_
        selection; see that method's own docstring for the eligibility/
        online-status definition. No permission check of its own beyond
        the router's `reception:register_visit` gate (the same
        permission every receptionist already needs to reach this
        screen at all — see reception/constants.py's own docstring on
        why "My Revenue" reuses this same permission rather than a
        dedicated read permission)."""
        return await self._reception_repo.list_doctors_for_selection()

    async def cancel_visit(self, *, actor: User, visit_id: UUID, reason: str | None) -> Visit:
        """Reception may cancel a Visit at any non-terminal point (Phase
        6 §4.1 — `CANCELLED` is reachable from every non-terminal
        status). Closes the active queue entry, if any, before
        cancelling the Visit itself — a cancelled Visit should never be
        left appearing active in a worklist."""
        active_entry = await self._queue_service.get_active_for_visit(visit_id)
        if active_entry is not None:
            await self._queue_service.cancel_current(actor=actor, visit_id=visit_id)

        visit = await self._visit_service.cancel_visit(actor=actor, visit_id=visit_id)
        await self._audit_repo.record(
            module="reception",
            action="reception.visit_cancelled",
            entity_type="visit",
            entity_id=visit.id,
            actor_user_id=actor.id,
            metadata={"reason": reason},
        )
        await self._session.commit()
        return visit

    # ------------------------------------------------------------------
    # Admin data correction (2026-08-19 addition, gated on `reception:
    # update_visit`/`reception:delete_visit` — never on register/cancel,
    # and never granted to Receptionist, see constants.py). Ownership
    # never matters here: an admin acts on any receptionist's slip, not
    # just their own — the permission check alone is what authorizes
    # this, exactly like every other RBAC-gated action in this codebase.
    # ------------------------------------------------------------------

    async def admin_update_visit(
        self,
        *,
        actor: User,
        visit_id: UUID,
        updates: dict[str, Any],
        procedures: list[tuple[UUID | None, str | None, Decimal | None]] | None = None,
    ) -> tuple[Patient, Visit]:
        """Splits the caller's already-validated flat `updates` dict
        (see AdminUpdateVisitRequest's own docstring for why the schema
        is flat with no field-name collisions) between the three
        already-existing, already-tested update paths this reuses rather
        than reimplements — `PatientService.update_patient` for identity
        fields, `VisitService.update_visit_details` for the legacy flat
        `procedure`/`amount`, `VisitService.admin_replace_procedure_items`
        for `procedures` (2026-08-21 addition, kept as its own parameter
        rather than folded into `updates` since it's a list of already-
        parsed `VisitProcedureItemRequest`s, not a flat scalar — the
        router does that one extra split for the same "request-shape
        knowledge stays at the API boundary" reason it already splits
        `updates` itself). Only one of `procedure`/`amount` vs.
        `procedures` is ever meaningful for a given visit — see
        `VisitService.update_visit_details`'s/
        `admin_replace_procedure_items`'s own docstrings for the exact
        rejection if both are attempted against the wrong kind of visit;
        this method just passes each bucket to its own path unchanged."""
        visit = await self._visit_service.get_visit(visit_id)
        patient = await self._patient_service.get_patient(visit.patient_id)

        visit_updates = {k: v for k, v in updates.items() if k in ("procedure", "amount")}
        patient_updates = {k: v for k, v in updates.items() if k not in ("procedure", "amount")}

        if patient_updates:
            patient = await self._patient_service.update_patient(
                actor=actor, patient_id=patient.id, updates=patient_updates
            )
        if visit_updates:
            visit = await self._visit_service.update_visit_details(
                actor=actor, visit_id=visit_id, updates=visit_updates
            )
        if procedures is not None:
            visit = await self._visit_service.admin_replace_procedure_items(
                actor=actor, visit_id=visit_id, procedures=procedures
            )

        await self._audit_repo.record(
            module="reception",
            action="reception.visit_updated_by_admin",
            entity_type="visit",
            entity_id=visit.id,
            actor_user_id=actor.id,
            metadata={
                "patient_fields": sorted(patient_updates.keys()),
                "visit_fields": sorted(visit_updates.keys()),
                "procedures_replaced": procedures is not None,
            },
        )
        await self._session.commit()
        return patient, visit

    async def admin_delete_visit(self, *, actor: User, visit_id: UUID) -> None:
        """Soft-deletes a Visit an admin has decided was a mistake (Phase
        6 §... — see VisitService.delete_visit's own docstring for why
        this is a soft delete, and why closing the active queue entry
        first, exactly like `cancel_visit` above, is this orchestrating
        method's job rather than VisitService's).

        Blocked outright — before anything is touched — if the Visit has
        a settled Billing Invoice against it (see
        VisitHasSettledInvoiceError and _SETTLED_INVOICE_STATUSES's own
        docstrings for that boundary/reasoning). Deliberately does NOT
        block on an unpaid (`PENDING_PAYMENT`) invoice, a
        PendingBillingItem, a Consultation, or a VitalsRecord — none of
        those are destroyed by this (they simply become unreachable
        through the deleted Visit's own now-404ing endpoints, the same
        "orphaned but never corrupted, never actually deleted" outcome
        `cancel_visit` already leaves them in today), so leaving them
        untouched keeps this action's blast radius identical to the
        already-trusted cancel flow, widened only by the one hard
        financial-integrity line explicitly required.

        2026-08-23 revision: deliberately does NOT also block on this
        Visit's own registration-charge payment tracking
        (`VisitHasSettledPaymentError`, still enforced on
        `VisitService.update_visit_details`'s legacy flat-field edit
        path — see that guard's own docstring). A real payment is now
        mandatory at every registration, so scoping this same guard to
        delete too would make every visit registered from now on
        permanently, unconditionally undeletable through this tool from
        the moment it's created — far more sweeping than "block once
        real money is at stake" once payment can never be zero. Unlike
        editing (where changing `amount`/`procedure` after a payment was
        recorded against it desynchronizes that payment from a since-
        changed total), a soft-delete never touches the payment rows or
        the visit's own `amount`/`discount_amount` fields — orphaning
        `VisitPayment` rows under a soft-deleted Visit is the same
        accepted "orphaned but never corrupted" outcome already applied
        to an unpaid Invoice, a Consultation, or a VitalsRecord above."""
        invoices = await self._invoice_repo.list_for_visit(visit_id)
        if any(invoice.status in _SETTLED_INVOICE_STATUSES for invoice in invoices):
            raise VisitHasSettledInvoiceError

        active_entry = await self._queue_service.get_active_for_visit(visit_id)
        if active_entry is not None:
            await self._queue_service.cancel_current(actor=actor, visit_id=visit_id)

        visit = await self._visit_service.get_visit(visit_id)
        await self._visit_service.delete_visit(actor=actor, visit_id=visit_id)
        await self._audit_repo.record(
            module="reception",
            action="reception.visit_deleted_by_admin",
            entity_type="visit",
            entity_id=visit_id,
            actor_user_id=actor.id,
            metadata={"queue_token": visit.queue_token},
        )
        await self._session.commit()

    # ------------------------------------------------------------------
    # "My Revenue" (2026-08-19 addition) — always `actor.id`, never a
    # request-suppliable target user id, the same hard-scoping shape
    # DashboardService.get_doctor_summary already uses for the Doctor
    # dashboard. There is structurally no way to ask for someone else's
    # revenue through either method below.
    # ------------------------------------------------------------------

    async def get_own_revenue(
        self, *, actor: User
    ) -> tuple[int, Decimal, int, Decimal, int, Decimal, datetime]:
        """This receptionist's own revenue — visits, medicine bills, and
        (Step 4 addition) lab bills counted separately, always capped to
        roughly the last 24 hours. Returns `(visits_count,
        visits_revenue, medicine_bill_count, medicine_revenue,
        lab_bill_count, lab_revenue, window_since)`; the router adds the
        three revenue figures together for `total_revenue` rather than
        this method doing it itself.

        Mechanism (2026-08-19 fix): the effective cutoff is
        `since = max(last_manual_clear_at, now - 24h)`, computed fresh
        on every call — never a stored value, so it self-corrects
        without a background job. This replaces the original
        "since her last Clear Revenue action, or all-time if she's
        never cleared" behavior, which in practice meant most
        receptionists (who never press Clear Revenue day to day) saw
        an ever-growing cumulative total since account creation rather
        than anything resembling "today's revenue". Manual "Clear
        Revenue" (see `clear_own_revenue` below) still works exactly as
        before and still writes one `reception.revenue_cleared` entry
        to the generic `audit_log` table (`shared/audit` — chosen
        originally because `User` lives in the permanently-frozen
        `auth` module, so a new column there was never an option); the
        *most recent* such entry, if more recent than `now - 24h`, is
        what actually moves the window forward — a clear a receptionist
        made 30 hours ago is no longer doing anything useful, since the
        24h auto-window has already moved past it on its own. No new
        table, column, or scheduled job: both revenue queries below add
        `created_at > since` as an extra filter — no visit, invoice, or
        medicine_bill row is ever touched, modified, or excluded from
        anything other than this one receptionist's own forward-looking
        total. Admin's own all-time views
        (VisitService.count_and_revenue_by_creator,
        MedicineBillRepository.count_and_revenue_by_creator) never
        apply this filter and are completely unaffected by either the
        24h auto-window or any receptionist's own manual clear."""
        cleared_entry = await self._audit_repo.get_latest_for_entity(
            entity_type=_REVENUE_CLEARED_ENTITY_TYPE,
            entity_id=actor.id,
            action=_REVENUE_CLEARED_ACTION,
        )
        auto_window_start = datetime.now(UTC) - _REVENUE_AUTO_WINDOW
        since = (
            max(cleared_entry.created_at, auto_window_start)
            if cleared_entry is not None
            else auto_window_start
        )

        visits_count, visits_revenue = await self._visit_service.count_and_revenue_for_creator(
            actor.id, since=since
        )
        medicine_count, medicine_revenue = await self._medicine_bill_repo.count_and_revenue_for_creator(
            actor.id, since=since
        )
        lab_count, lab_revenue = await self._lab_bill_repo.count_and_revenue_for_creator(
            actor.id, since=since
        )
        return (
            visits_count,
            visits_revenue,
            medicine_count,
            medicine_revenue,
            lab_count,
            lab_revenue,
            since,
        )

    async def clear_own_revenue(self, *, actor: User) -> datetime:
        """Resets this receptionist's own "My Revenue" display to zero
        going forward — see `get_own_revenue`'s own docstring for the
        full mechanism. Deletes, modifies, or soft-deletes nothing:
        every visit, invoice, payment, and medicine bill she has ever
        created remains fully intact, unchanged, and fully visible in
        Admin's own all-time history/audit views exactly as before —
        this only ever adds one new, permanent audit_log row recording
        that the clear happened and when."""
        now = datetime.now(UTC)
        await self._audit_repo.record(
            module="reception",
            action=_REVENUE_CLEARED_ACTION,
            entity_type=_REVENUE_CLEARED_ENTITY_TYPE,
            entity_id=actor.id,
            actor_user_id=actor.id,
        )
        await self._session.commit()
        return now
