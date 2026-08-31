"""Persistence-only repositories for the Billing module — see
app/modules/patients/repository.py's identical module docstring."""

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from uuid import UUID

from sqlalchemy import func, select

from app.modules.billing.models import (
    Invoice,
    InvoiceLineItem,
    InvoicePayment,
    InvoiceStatus,
    PendingBillingItem,
    PendingBillingItemStatus,
)
from app.shared.money import quantize_money
from app.shared.repository.base_repository import BaseRepository

_OPEN_INVOICE_STATUSES = (InvoiceStatus.PENDING_PAYMENT, InvoiceStatus.PARTIALLY_PAID)


class PendingBillingItemRepository(BaseRepository[PendingBillingItem]):
    model = PendingBillingItem

    async def list_for_visit(
        self, visit_id: UUID, *, status: PendingBillingItemStatus | None = None
    ) -> list[PendingBillingItem]:
        conditions = [
            PendingBillingItem.deleted_at.is_(None),
            PendingBillingItem.visit_id == visit_id,
        ]
        if status is not None:
            conditions.append(PendingBillingItem.status == status)
        stmt = (
            select(PendingBillingItem)
            .where(*conditions)
            .order_by(PendingBillingItem.created_at.asc())
        )
        result = await self.session.execute(stmt)
        return list(result.scalars().all())


class InvoiceRepository(BaseRepository[Invoice]):
    model = Invoice

    async def get_open_for_visit(self, visit_id: UUID) -> Invoice | None:
        stmt = self._exclude_soft_deleted(
            select(Invoice).where(
                Invoice.visit_id == visit_id, Invoice.status.in_(_OPEN_INVOICE_STATUSES)
            ),
            include_deleted=False,
        )
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def get_for_update(self, invoice_id: UUID) -> Invoice | None:
        """Row-locking variant of `get_by_id`, for `BillingService.
        record_payment`'s read-modify-write specifically. Without this,
        two concurrent payment requests against the same Invoice both
        read the same `amount_paid`/`status` "before" state, both
        compute their own "after" state from it, and both write —
        classic lost update, and on a money field that is a real
        financial-integrity bug, not a theoretical one (see
        `SELECT ... FOR UPDATE`'s standard purpose). `SELECT ... FOR
        UPDATE` makes the second concurrent transaction's SELECT block
        until the first commits, so it re-reads the *already-updated*
        row (not the stale one) before deciding anything — turning the
        race into a normal, sequential, and correct read-then-write."""
        stmt = self._exclude_soft_deleted(
            select(Invoice).where(Invoice.id == invoice_id), include_deleted=False
        ).with_for_update()
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def list_for_visit(self, visit_id: UUID) -> list[Invoice]:
        stmt = self._exclude_soft_deleted(
            select(Invoice).where(Invoice.visit_id == visit_id).order_by(Invoice.created_at.asc()),
            include_deleted=False,
        )
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def list_for_visit_ids(self, visit_ids: list[UUID]) -> list[Invoice]:
        """Batched sibling of `list_for_visit` — every Invoice across the
        given visits, oldest first. Used by the Patient History
        aggregation module (app/modules/patient_history/service.py) to
        avoid one query per visit — same N+1-avoidance shape as
        app/modules/vitals/repository.py's `list_for_visit_ids`."""
        if not visit_ids:
            return []
        stmt = self._exclude_soft_deleted(
            select(Invoice)
            .where(Invoice.visit_id.in_(visit_ids))
            .order_by(Invoice.created_at.asc()),
            include_deleted=False,
        )
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def get_today_summary(self) -> tuple[Decimal, int, int]:
        """Backs the Reception/Billing Dashboard (§22): (revenue
        collected today, invoices paid today, currently-open invoices).
        "Today" is the current UTC calendar day — a documented
        simplification, not a hidden bug: a hospital deployment outside
        UTC would want this computed against local time, which requires
        a configured deployment timezone this build does not introduce.
        Three aggregate queries, not one per invoice — no N+1."""
        now = datetime.now(UTC)
        start_of_day = datetime(now.year, now.month, now.day, tzinfo=UTC)
        end_of_day = start_of_day + timedelta(days=1)
        paid_today_conditions = (
            Invoice.deleted_at.is_(None),
            Invoice.status == InvoiceStatus.PAID,
            Invoice.paid_at >= start_of_day,
            Invoice.paid_at < end_of_day,
        )

        revenue_today = (
            await self.session.execute(
                select(func.coalesce(func.sum(Invoice.amount_paid), 0)).where(
                    *paid_today_conditions
                )
            )
        ).scalar_one()
        paid_count_today = (
            await self.session.execute(select(func.count()).where(*paid_today_conditions))
        ).scalar_one()
        open_count = (
            await self.session.execute(
                select(func.count()).where(
                    Invoice.deleted_at.is_(None), Invoice.status.in_(_OPEN_INVOICE_STATUSES)
                )
            )
        ).scalar_one()

        return quantize_money(Decimal(revenue_today)), paid_count_today, open_count


class InvoiceLineItemRepository(BaseRepository[InvoiceLineItem]):
    model = InvoiceLineItem

    async def list_for_invoice(self, invoice_id: UUID) -> list[InvoiceLineItem]:
        stmt = self._exclude_soft_deleted(
            select(InvoiceLineItem)
            .where(InvoiceLineItem.invoice_id == invoice_id)
            .order_by(InvoiceLineItem.created_at.asc()),
            include_deleted=False,
        )
        result = await self.session.execute(stmt)
        return list(result.scalars().all())


class InvoicePaymentRepository(BaseRepository[InvoicePayment]):
    model = InvoicePayment

    async def list_for_invoice(self, invoice_id: UUID) -> list[InvoicePayment]:
        stmt = self._exclude_soft_deleted(
            select(InvoicePayment)
            .where(InvoicePayment.invoice_id == invoice_id)
            .order_by(InvoicePayment.created_at.asc()),
            include_deleted=False,
        )
        result = await self.session.execute(stmt)
        return list(result.scalars().all())
