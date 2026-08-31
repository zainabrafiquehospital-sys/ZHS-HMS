"""Billing business logic — Phase 6 architecture §7's "Reception as Sole
Financial Authority" pipeline: a doctor can only ever create a
`PendingBillingItem` (§7.1); every actual Invoice mutation — approval,
generation, payment — happens here, called only from Reception-held
endpoints (see constants.py's module docstring on the permission split).

Orchestrates VisitService the same way app/modules/reception/service.py
does — see that module's docstring for the identical "sequential
orchestration across independently-committing services" rationale.

Scope simplification for this build: §7.4's `Draft` status is not
modeled as a separate, editable stage — `generate_invoice` computes the
full line-item set and moves straight to `Pending Payment` in one
action, since the OPD flow this build targets has Reception generate
and immediately present the invoice as a single step. Nothing about
this forecloses adding an editable Draft stage later; it is a scope
decision, not a structural limitation."""

from datetime import UTC, datetime
from decimal import Decimal
from uuid import UUID

from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import ValidationError
from app.modules.auth.models import User
from app.modules.billing.exceptions import (
    DiscountExceedsSubtotalError,
    DiscountReasonRequiredError,
    InvoiceAlreadyOpenError,
    InvoiceNotFoundError,
    InvoiceNotPayableError,
    PaymentExceedsBalanceError,
    PaymentMethodRequiredError,
    PendingBillingItemNotFoundError,
    PendingBillingItemNotPendingError,
)
from app.modules.billing.models import (
    Invoice,
    InvoiceLineItem,
    InvoicePayment,
    InvoiceStatus,
    PendingBillingItem,
    PendingBillingItemStatus,
)
from app.modules.billing.repository import (
    InvoiceLineItemRepository,
    InvoicePaymentRepository,
    InvoiceRepository,
    PendingBillingItemRepository,
)
from app.modules.visits.models import Visit
from app.modules.visits.service import VisitService
from app.shared.audit.repository import AuditLogRepository
from app.shared.db_errors import unique_violation_constraint_name
from app.shared.money import quantize_money
from app.shared.payment_method import PaymentMethod

_ZERO = Decimal("0.00")

# The unique-while-open index backing "at most one open Invoice per
# Visit" — see app/modules/billing/models.py. Checked against a caught
# IntegrityError the same way app/modules/consultation/service.py's
# _CONSULTATION_ACTIVE_CONSTRAINT is, to tell a genuine race-lost double
# `generate_invoice` apart from any other integrity failure.
_INVOICE_OPEN_CONSTRAINT = "ix_invoice_visit_id_open_active"


class BillingService:
    def __init__(
        self,
        session: AsyncSession,
        pending_billing_item_repository: PendingBillingItemRepository,
        invoice_repository: InvoiceRepository,
        invoice_line_item_repository: InvoiceLineItemRepository,
        invoice_payment_repository: InvoicePaymentRepository,
        visit_service: VisitService,
        audit_repository: AuditLogRepository,
    ) -> None:
        self._session = session
        self._pending_repo = pending_billing_item_repository
        self._invoice_repo = invoice_repository
        self._line_item_repo = invoice_line_item_repository
        self._payment_repo = invoice_payment_repository
        self._visit_service = visit_service
        self._audit_repo = audit_repository

    # ------------------------------------------------------------------
    # Pending Billing Items (§7.1) — doctor submits, Reception decides
    # ------------------------------------------------------------------

    async def submit_pending_item(
        self, *, actor: User, visit_id: UUID, description: str, amount: Decimal
    ) -> PendingBillingItem:
        """A doctor's "submit an additional charge request" — a clinical
        fact, not a financial transaction (§7.1). No Invoice is touched
        here."""
        item = PendingBillingItem(
            visit_id=visit_id,
            description=description,
            amount=quantize_money(amount),
            status=PendingBillingItemStatus.PENDING,
            created_by=actor.id,
            updated_by=actor.id,
        )
        await self._pending_repo.add(item)
        await self._audit_repo.record(
            module="billing",
            action="billing.pending_item_submitted",
            entity_type="pending_billing_item",
            entity_id=item.id,
            actor_user_id=actor.id,
            metadata={"visit_id": str(visit_id), "amount": str(amount)},
        )
        await self._session.commit()
        return await self._pending_repo.get_by_id(item.id)

    async def list_pending_items(
        self, visit_id: UUID, *, status: PendingBillingItemStatus | None = None
    ) -> list[PendingBillingItem]:
        return await self._pending_repo.list_for_visit(visit_id, status=status)

    async def _get_pending_item(self, item_id: UUID) -> PendingBillingItem:
        item = await self._pending_repo.get_by_id(item_id)
        if item is None:
            raise PendingBillingItemNotFoundError
        return item

    async def approve_pending_item(self, *, actor: User, item_id: UUID) -> PendingBillingItem:
        item = await self._get_pending_item(item_id)
        if item.status != PendingBillingItemStatus.PENDING:
            raise PendingBillingItemNotPendingError
        item.status = PendingBillingItemStatus.APPROVED
        item.updated_by = actor.id
        await self._pending_repo.add(item)
        await self._audit_repo.record(
            module="billing",
            action="billing.pending_item_approved",
            entity_type="pending_billing_item",
            entity_id=item.id,
            actor_user_id=actor.id,
            metadata={"visit_id": str(item.visit_id)},
        )
        await self._session.commit()
        return await self._pending_repo.get_by_id(item.id)

    async def reject_pending_item(self, *, actor: User, item_id: UUID) -> PendingBillingItem:
        item = await self._get_pending_item(item_id)
        if item.status != PendingBillingItemStatus.PENDING:
            raise PendingBillingItemNotPendingError
        item.status = PendingBillingItemStatus.REJECTED
        item.updated_by = actor.id
        await self._pending_repo.add(item)
        await self._audit_repo.record(
            module="billing",
            action="billing.pending_item_rejected",
            entity_type="pending_billing_item",
            entity_id=item.id,
            actor_user_id=actor.id,
            metadata={"visit_id": str(item.visit_id)},
        )
        await self._session.commit()
        return await self._pending_repo.get_by_id(item.id)

    # ------------------------------------------------------------------
    # Invoice generation and payment (§7.2, §7.4)
    # ------------------------------------------------------------------

    async def generate_invoice(
        self,
        *,
        actor: User,
        visit_id: UUID,
        base_description: str,
        base_amount: Decimal,
        discount_amount: Decimal = _ZERO,
        discount_reason: str | None = None,
        initial_payment_amount: Decimal = _ZERO,
        initial_payment_method: PaymentMethod | None = None,
    ) -> Invoice:
        """Creates the Invoice for a Visit: the base procedure charge
        plus every currently-`APPROVED` Pending Billing Item, each
        marked `BILLED` so it can never be folded into a second Invoice.

        `discount_amount` (optional, defaults to none) is a flat
        reduction applied once, here, against the subtotal — there is
        no separate "apply a discount to an already-generated invoice"
        endpoint; Reception decides the discount at the same moment it
        decides the rest of the bill, matching this method's existing
        "compute the full line-item set in one action" design. A
        non-zero discount always requires `discount_reason` (a real cut
        to hospital revenue needs a documented reason); `total_amount`
        stored on the Invoice is already post-discount, and the
        pre-discount subtotal is always cheaply recoverable as
        `total_amount + discount_amount` rather than stored separately.

        `initial_payment_amount` (optional, defaults to none) folds
        Reception's single most common next action — collecting
        whatever the patient is paying right now — into this same call
        and the same commit, via the shared `_apply_payment` helper
        also used by `record_payment` below. This is a UX/API-shape
        merge, not a new payment concept: it produces exactly the
        `InvoicePayment` audit row and `amount_paid`/`status` update a
        separate, immediately-following `record_payment` call would
        have, just without the two-request round trip that could leave
        an invoice created-but-never-paid if a second call failed
        independently. Recording no payment at all (the default) still
        works exactly as before — creating an Invoice has never
        required an immediate payment, and still doesn't.
        `initial_payment_method` (2026-08-19 addition) is required
        whenever `initial_payment_amount > 0` — `PaymentMethodRequiredError`
        otherwise — but is simply ignored when no payment is being
        recorded at all, mirroring `discount_reason`'s identical
        "only meaningful when its companion amount is non-zero" shape.

        Callable whether the Visit is fresh out of Consultation
        (`WAITING_BILLING`) or already `COMPLETED` with a prior `Paid`
        Invoice — `VisitService.mark_payment_pending` accepts both
        source statuses (§4.1/§7.4's "new Outstanding Invoice" rule);
        this method never mutates a previous invoice, it only ever
        creates a new one, and `InvoiceAlreadyOpenError` below is what
        actually enforces "never two open invoices for one visit"."""
        if await self._invoice_repo.get_open_for_visit(visit_id) is not None:
            raise InvoiceAlreadyOpenError
        if base_amount <= _ZERO:
            raise ValidationError("base_amount must be greater than zero.")
        base_amount = quantize_money(base_amount)

        discount_amount = quantize_money(discount_amount) if discount_amount else _ZERO
        if discount_amount < _ZERO:
            raise ValidationError("discount_amount cannot be negative.")
        discount_reason = discount_reason.strip() if discount_reason else None
        if discount_amount > _ZERO and not discount_reason:
            raise DiscountReasonRequiredError
        if discount_amount == _ZERO:
            discount_reason = None

        approved_items = await self._pending_repo.list_for_visit(
            visit_id, status=PendingBillingItemStatus.APPROVED
        )
        subtotal = base_amount + sum((item.amount for item in approved_items), _ZERO)
        if discount_amount > subtotal:
            raise DiscountExceedsSubtotalError(str(subtotal))
        total = subtotal - discount_amount

        invoice = Invoice(
            visit_id=visit_id,
            status=InvoiceStatus.PENDING_PAYMENT,
            total_amount=total,
            amount_paid=_ZERO,
            discount_amount=discount_amount,
            discount_reason=discount_reason,
            created_by=actor.id,
            updated_by=actor.id,
        )
        try:
            await self._invoice_repo.add(invoice)
        except IntegrityError as exc:
            await self._session.rollback()
            if unique_violation_constraint_name(exc) == _INVOICE_OPEN_CONSTRAINT:
                # Lost the race to a concurrent `generate_invoice` call
                # for the same Visit — the `get_open_for_visit` check
                # above is not by itself race-safe (same TOCTOU shape as
                # every other "check, then insert" flow in this
                # codebase; see app/shared/db_errors.py), this is what
                # actually closes the window.
                raise InvoiceAlreadyOpenError from exc
            raise

        await self._line_item_repo.add(
            InvoiceLineItem(
                invoice_id=invoice.id,
                pending_billing_item_id=None,
                description=base_description,
                amount=base_amount,
            )
        )
        for item in approved_items:
            await self._line_item_repo.add(
                InvoiceLineItem(
                    invoice_id=invoice.id,
                    pending_billing_item_id=item.id,
                    description=item.description,
                    amount=item.amount,
                )
            )
            item.status = PendingBillingItemStatus.BILLED
            item.updated_by = actor.id
            await self._pending_repo.add(item)

        await self._audit_repo.record(
            module="billing",
            action="billing.invoice_generated",
            entity_type="invoice",
            entity_id=invoice.id,
            actor_user_id=actor.id,
            metadata={
                "visit_id": str(visit_id),
                "total_amount": str(total),
                "line_item_count": 1 + len(approved_items),
                "discount_amount": str(discount_amount),
                "discount_reason": discount_reason,
            },
        )

        initial_payment_amount = (
            quantize_money(initial_payment_amount) if initial_payment_amount else _ZERO
        )
        if initial_payment_amount < _ZERO:
            raise ValidationError("initial_payment_amount cannot be negative.")
        fully_paid = False
        if initial_payment_amount > _ZERO:
            if initial_payment_method is None:
                raise PaymentMethodRequiredError
            fully_paid = await self._apply_payment(
                invoice=invoice,
                actor=actor,
                amount=initial_payment_amount,
                payment_method=initial_payment_method,
            )

        # Always Pending Payment first, even when the initial payment
        # already pays it off in full — same two-hop path a separate
        # generate_invoice-then-record_payment call would have taken
        # (WAITING_BILLING/COMPLETED -> PAYMENT_PENDING -> COMPLETED);
        # COMPLETED has no direct self-transition (see visits/service.py's
        # VALID_TRANSITIONS), so this is the one sequencing that is
        # always valid regardless of the Visit's status beforehand.
        await self._visit_service.mark_payment_pending(actor=actor, visit_id=visit_id)
        if fully_paid:
            await self._visit_service.mark_completed(actor=actor, visit_id=visit_id)
        await self._session.commit()
        return await self._invoice_repo.get_by_id(invoice.id)

    async def _apply_payment(
        self, *, invoice: Invoice, actor: User, amount: Decimal, payment_method: PaymentMethod
    ) -> bool:
        """Shared by `generate_invoice`'s optional initial payment and
        `record_payment`'s top-up payment below — validates `amount`
        against the remaining balance, mutates `invoice.amount_paid`/
        `status`/`paid_at` in memory, stages a new `InvoicePayment`
        audit row, and records the audit-log entry. Never commits and
        never touches `VisitService`: the two call sites need different
        Visit-transition sequencing around it (a freshly-generated
        invoice's Visit isn't in Payment Pending yet; an existing
        invoice being topped up already is), so each caller sequences
        that itself. Returns whether this payment brought the invoice
        to fully Paid.

        Assumes the invoice is already known payable (status Pending
        Payment/Partially Paid) — `record_payment` checks that itself
        before calling this; `generate_invoice`'s invoice is always
        freshly created and Pending Payment by construction, so it
        never needs the check.

        `payment_method` (2026-08-19 addition) is required by both
        callers — a real payment being recorded always has a known
        method (cash, bank transfer, JazzCash, EasyPaisa, or card);
        see app/shared/payment_method.py's module docstring. Stored on
        this individual `InvoicePayment` row only — never on the
        Invoice itself — so a partial cash payment now and a bank
        transfer later are correctly two separate, independently
        attributed rows."""
        if amount <= _ZERO:
            raise ValidationError("Payment amount must be greater than zero.")
        amount = quantize_money(amount)

        remaining = invoice.total_amount - invoice.amount_paid
        if amount > remaining:
            raise PaymentExceedsBalanceError(str(remaining))

        invoice.amount_paid = invoice.amount_paid + amount
        invoice.updated_by = actor.id
        fully_paid = invoice.amount_paid == invoice.total_amount
        if fully_paid:
            invoice.status = InvoiceStatus.PAID
            invoice.paid_at = datetime.now(UTC)
        else:
            invoice.status = InvoiceStatus.PARTIALLY_PAID
        await self._invoice_repo.add(invoice)
        await self._payment_repo.add(
            InvoicePayment(
                invoice_id=invoice.id,
                amount=amount,
                payment_method=payment_method,
                created_by=actor.id,
                updated_by=actor.id,
            )
        )
        await self._audit_repo.record(
            module="billing",
            action="billing.payment_recorded",
            entity_type="invoice",
            entity_id=invoice.id,
            actor_user_id=actor.id,
            metadata={
                "visit_id": str(invoice.visit_id),
                "amount": str(amount),
                "payment_method": payment_method.value,
                "fully_paid": fully_paid,
            },
        )
        return fully_paid

    async def record_payment(
        self, *, actor: User, invoice_id: UUID, amount: Decimal, payment_method: PaymentMethod
    ) -> Invoice:
        """Records an *additional* payment against an already-created
        Invoice — topping up toward the remaining balance on a later
        visit/call, not the primary way an Invoice gets its first
        payment (see `generate_invoice`'s `initial_payment_amount` for
        that). Paid/cancelled invoices are immutable (§7.4) — enforced
        here by rejecting any payment against an invoice not currently
        `Pending Payment`/`Partially Paid`, and by never allowing a
        payment to exceed the remaining balance (which would otherwise
        silently overpay past `total_amount`).

        Reads the Invoice with `SELECT ... FOR UPDATE`
        (`InvoiceRepository.get_for_update`), not the plain `get_invoice`
        — this is a read-modify-write on a money field, and two
        concurrent payment requests against the same Invoice must never
        both compute their "amount paid so far" from the same stale
        snapshot (a lost update on money is a financial-integrity bug,
        not a cosmetic one). The row lock makes the second concurrent
        request's read wait for the first's commit, then correctly see
        the already-updated balance — surfacing as a clean
        `InvoiceNotPayableError`/`PaymentExceedsBalanceError` for the
        loser instead of a silent double-payment."""
        invoice = await self._invoice_repo.get_for_update(invoice_id)
        if invoice is None:
            raise InvoiceNotFoundError
        if invoice.status not in (InvoiceStatus.PENDING_PAYMENT, InvoiceStatus.PARTIALLY_PAID):
            raise InvoiceNotPayableError(invoice.status.value)

        fully_paid = await self._apply_payment(
            invoice=invoice, actor=actor, amount=amount, payment_method=payment_method
        )
        if fully_paid:
            await self._visit_service.mark_completed(actor=actor, visit_id=invoice.visit_id)
        await self._session.commit()
        return await self._invoice_repo.get_by_id(invoice.id)

    async def get_invoice(self, invoice_id: UUID) -> Invoice:
        invoice = await self._invoice_repo.get_by_id(invoice_id)
        if invoice is None:
            raise InvoiceNotFoundError
        return invoice

    async def list_invoices_for_visit(self, visit_id: UUID) -> list[Invoice]:
        return await self._invoice_repo.list_for_visit(visit_id)

    async def list_invoices_for_visits(self, visit_ids: list[UUID]) -> list[Invoice]:
        """Thin passthrough to InvoiceRepository.list_for_visit_ids —
        see that method's own docstring."""
        return await self._invoice_repo.list_for_visit_ids(visit_ids)

    async def get_line_items(self, invoice_id: UUID) -> list[InvoiceLineItem]:
        return await self._line_item_repo.list_for_invoice(invoice_id)

    async def get_payments(self, invoice_id: UUID) -> list[InvoicePayment]:
        return await self._payment_repo.list_for_invoice(invoice_id)

    async def get_today_summary(self) -> tuple[Decimal, int, int]:
        """Read-only aggregate added for the Dashboard module (§22)."""
        return await self._invoice_repo.get_today_summary()

    # ------------------------------------------------------------------
    # Visit registration-charge payment top-up (2026-08-22 addition) —
    # a one-line pass-through to VisitService.record_payment, exposed
    # from Billing (not Reception) because that's where this action's UI
    # lives (the Billing screen's own top-up panel) and every other
    # mutating action there already requires `billing:manage` — see
    # VisitService.record_payment's own docstring for the full mechanism
    # and why this is a ledger independent of Invoice/InvoicePayment
    # above (it never touches either).
    # ------------------------------------------------------------------

    async def record_visit_payment(
        self, *, actor: User, visit_id: UUID, amount: Decimal, payment_method: PaymentMethod
    ) -> Visit:
        return await self._visit_service.record_payment(
            actor=actor, visit_id=visit_id, amount=amount, payment_method=payment_method
        )
