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
    InvoiceAlreadyOpenError,
    InvoiceNotFoundError,
    InvoiceNotPayableError,
    PaymentExceedsBalanceError,
    PendingBillingItemNotFoundError,
    PendingBillingItemNotPendingError,
)
from app.modules.billing.models import (
    Invoice,
    InvoiceLineItem,
    InvoiceStatus,
    PendingBillingItem,
    PendingBillingItemStatus,
)
from app.modules.billing.repository import (
    InvoiceLineItemRepository,
    InvoiceRepository,
    PendingBillingItemRepository,
)
from app.modules.visits.service import VisitService
from app.shared.audit.repository import AuditLogRepository
from app.shared.db_errors import unique_violation_constraint_name
from app.shared.money import quantize_money

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
        visit_service: VisitService,
        audit_repository: AuditLogRepository,
    ) -> None:
        self._session = session
        self._pending_repo = pending_billing_item_repository
        self._invoice_repo = invoice_repository
        self._line_item_repo = invoice_line_item_repository
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
        self, *, actor: User, visit_id: UUID, base_description: str, base_amount: Decimal
    ) -> Invoice:
        """Creates the Invoice for a Visit: the base procedure charge
        plus every currently-`APPROVED` Pending Billing Item, each
        marked `BILLED` so it can never be folded into a second Invoice.

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

        approved_items = await self._pending_repo.list_for_visit(
            visit_id, status=PendingBillingItemStatus.APPROVED
        )
        total = base_amount + sum((item.amount for item in approved_items), _ZERO)

        invoice = Invoice(
            visit_id=visit_id,
            status=InvoiceStatus.PENDING_PAYMENT,
            total_amount=total,
            amount_paid=_ZERO,
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
            },
        )
        await self._visit_service.mark_payment_pending(actor=actor, visit_id=visit_id)
        await self._session.commit()
        return await self._invoice_repo.get_by_id(invoice.id)

    async def record_payment(self, *, actor: User, invoice_id: UUID, amount: Decimal) -> Invoice:
        """Paid/cancelled invoices are immutable (§7.4) — enforced here
        by rejecting any payment against an invoice not currently
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

        await self._audit_repo.record(
            module="billing",
            action="billing.payment_recorded",
            entity_type="invoice",
            entity_id=invoice.id,
            actor_user_id=actor.id,
            metadata={
                "visit_id": str(invoice.visit_id),
                "amount": str(amount),
                "fully_paid": fully_paid,
            },
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

    async def get_line_items(self, invoice_id: UUID) -> list[InvoiceLineItem]:
        return await self._line_item_repo.list_for_invoice(invoice_id)

    async def get_today_summary(self) -> tuple[Decimal, int, int]:
        """Read-only aggregate added for the Dashboard module (§22)."""
        return await self._invoice_repo.get_today_summary()
