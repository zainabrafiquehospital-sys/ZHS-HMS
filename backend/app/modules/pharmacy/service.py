"""Pharmacy / Medicine Billing business logic.

Three independent concerns:
- Managing the medicine price list (`create_medicine`/`update_medicine`)
  — plain CRUD, Admin-only (`pharmacy:manage`).
- Building and finalizing a `MedicineBill` in one action
  (`create_bill`) — validates every line item's medicine exists and is
  active, snapshots its name/price at billing time (see models.py's
  module docstring on why), computes each line total and the bill's
  grand total via `quantize_money()`, and persists the bill, every
  item, and an optional initial payment all in one transaction — the
  same shape as app/modules/billing/service.py's `generate_invoice`.
  `initial_payment_amount` (optional, defaults to none) is the
  "Advance Received" field on Pharmacy's single merged counter form:
  a bill with no initial payment still starts `UNPAID` with
  `amount_paid=0` exactly as before; one with an initial payment is
  created already `PARTIALLY_PAID`/`PAID`, atomically — never a bill
  that exists with a payment that might fail in a second, separate
  request. `manual_patient_name`/`_age`/`_phone` (optional, all-or-
  nothing, mutually exclusive with `visit_id`) let Reception put a
  name/age/contact on the printed slip without an existing Patient/
  Visit to link — see models.py's `MedicineBill` docstring.
- Recording a payment against a bill (`record_payment`) — an
  *additional*, later top-up toward the remaining balance (not the
  primary way a bill gets paid, now that `create_bill` folds the first
  payment in) — allows any amount up to the remaining balance, derives
  `UNPAID`/`PARTIALLY_PAID`/`PAID` from the running `amount_paid`
  total, and records the payment as its own row
  (`MedicineBillPayment`). Shares its actual validate-and-apply logic
  with `create_bill`'s initial payment via the private `_apply_payment`
  helper — the identical shape and concurrency handling as
  `BillingService.record_payment`; see that method's own docstring for
  the `SELECT ... FOR UPDATE` rationale, which applies here for the
  same reason (a lost update on a money field is a financial-integrity
  bug, not a cosmetic one).

`visit_id` is optional (a medicine bill may be a standalone walk-in
sale); when supplied, `VisitService.get_visit` validates it exists
before anything is written, so an invalid id surfaces as a clean
`VisitNotFoundError` rather than a raw FK `IntegrityError`."""

from datetime import UTC, datetime
from decimal import Decimal
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import ValidationError
from app.modules.auth.models import User
from app.modules.pharmacy.exceptions import (
    MedicineBillManualPatientConflictsWithVisitError,
    MedicineBillManualPatientFieldsIncompleteError,
    MedicineBillNotFoundError,
    MedicineBillNotPayableError,
    MedicineBillPaymentExceedsBalanceError,
    MedicineInactiveError,
    MedicineNotFoundError,
)
from app.modules.pharmacy.models import (
    Medicine,
    MedicineBill,
    MedicineBillItem,
    MedicineBillPayment,
    MedicineBillStatus,
    MedicineCategory,
)
from app.modules.pharmacy.repository import (
    MEDICINE_SORTABLE_COLUMNS,
    MedicineBillItemRepository,
    MedicineBillPaymentRepository,
    MedicineBillRepository,
    MedicineRepository,
)
from app.modules.visits.service import VisitService
from app.shared.audit.repository import AuditLogRepository
from app.shared.money import quantize_money

_ZERO = Decimal("0.00")


class PharmacyService:
    def __init__(
        self,
        session: AsyncSession,
        medicine_repository: MedicineRepository,
        medicine_bill_repository: MedicineBillRepository,
        medicine_bill_item_repository: MedicineBillItemRepository,
        medicine_bill_payment_repository: MedicineBillPaymentRepository,
        visit_service: VisitService,
        audit_repository: AuditLogRepository,
    ) -> None:
        self._session = session
        self._medicine_repo = medicine_repository
        self._bill_repo = medicine_bill_repository
        self._item_repo = medicine_bill_item_repository
        self._payment_repo = medicine_bill_payment_repository
        self._visit_service = visit_service
        self._audit_repo = audit_repository

    # ------------------------------------------------------------------
    # Medicine price list (Admin-only, pharmacy:manage)
    # ------------------------------------------------------------------

    async def create_medicine(
        self, *, actor: User, name: str, category: MedicineCategory, unit_price: Decimal
    ) -> Medicine:
        medicine = Medicine(
            name=name,
            category=category,
            unit_price=quantize_money(unit_price),
            is_active=True,
            created_by=actor.id,
            updated_by=actor.id,
        )
        await self._medicine_repo.add(medicine)
        await self._audit_repo.record(
            module="pharmacy",
            action="pharmacy.medicine_created",
            entity_type="medicine",
            entity_id=medicine.id,
            actor_user_id=actor.id,
            metadata={"name": name},
        )
        await self._session.commit()
        return await self._get_medicine(medicine.id)

    async def _get_medicine(self, medicine_id: UUID) -> Medicine:
        medicine = await self._medicine_repo.get_by_id(medicine_id)
        if medicine is None:
            raise MedicineNotFoundError
        return medicine

    async def get_medicine(self, medicine_id: UUID) -> Medicine:
        return await self._get_medicine(medicine_id)

    async def update_medicine(self, *, actor: User, medicine_id: UUID, updates: dict) -> Medicine:
        """Partial update — `updates` comes straight from
        `UpdateMedicineRequest.model_dump(exclude_unset=True)`, same
        `exclude_unset` semantics as `PatientService.update_patient`."""
        medicine = await self._get_medicine(medicine_id)
        if not updates:
            return medicine

        for field in ("name", "category", "unit_price", "is_active"):
            if field in updates:
                value = updates[field]
                if field == "unit_price" and value is not None:
                    value = quantize_money(value)
                setattr(medicine, field, value)

        medicine.updated_by = actor.id
        await self._medicine_repo.add(medicine)
        await self._audit_repo.record(
            module="pharmacy",
            action="pharmacy.medicine_updated",
            entity_type="medicine",
            entity_id=medicine.id,
            actor_user_id=actor.id,
            metadata={"fields": sorted(updates.keys())},
        )
        await self._session.commit()
        return await self._get_medicine(medicine.id)

    async def search_medicines(self, *, search: str, limit: int = 20) -> list[Medicine]:
        return await self._medicine_repo.search_active(search=search, limit=limit)

    async def list_medicines(
        self, *, search: str | None, sort_by: str, sort_desc: bool, page: int, page_size: int
    ) -> tuple[list[Medicine], int]:
        sort_column = MEDICINE_SORTABLE_COLUMNS[sort_by]
        return await self._medicine_repo.list_all(
            search=search,
            sort_column=sort_column,
            sort_desc=sort_desc,
            limit=page_size,
            offset=(page - 1) * page_size,
        )

    # ------------------------------------------------------------------
    # Medicine bills (Receptionist + Admin, pharmacy:bill / pharmacy:read)
    # ------------------------------------------------------------------

    async def create_bill(
        self,
        *,
        actor: User,
        visit_id: UUID | None,
        items: list[tuple[UUID, int]],
        initial_payment_amount: Decimal = _ZERO,
        manual_patient_name: str | None = None,
        manual_patient_age: int | None = None,
        manual_patient_phone: str | None = None,
    ) -> MedicineBill:
        """`items` is a list of `(medicine_id, quantity)` pairs, already
        validated non-empty by `CreateMedicineBillRequest`. Every
        medicine referenced must exist and be active — checked up front,
        before anything is written, so a bad line item never leaves a
        partially-built bill behind.

        `initial_payment_amount` (optional, defaults to none) folds
        collecting whatever the patient is paying right now into this
        same call and the same commit, via the shared `_apply_payment`
        helper also used by `record_payment` below — the identical
        merge `BillingService.generate_invoice` does for Invoices, see
        that method's docstring for the full rationale. Recording no
        payment at all (the default) still works exactly as before: a
        bill with no `initial_payment_amount` is created `UNPAID`, same
        as ever.

        `manual_patient_name`/`manual_patient_age`/`manual_patient_phone`
        (all optional, default None) are purely display information for
        the printed slip when no registered Patient/Visit is being
        linked — see models.py's `MedicineBill` docstring for the full
        rationale and the DB-level CHECK constraints that also enforce
        the two rules validated here: mutually exclusive with
        `visit_id`, and all-or-nothing (never a partial manual entry)."""
        manual_fields = (manual_patient_name, manual_patient_age, manual_patient_phone)
        any_manual_field = any(field is not None for field in manual_fields)
        all_manual_fields = all(field is not None for field in manual_fields)
        if any_manual_field and not all_manual_fields:
            raise MedicineBillManualPatientFieldsIncompleteError
        if any_manual_field and visit_id is not None:
            raise MedicineBillManualPatientConflictsWithVisitError
        if manual_patient_name is not None:
            manual_patient_name = manual_patient_name.strip()
        if manual_patient_phone is not None:
            manual_patient_phone = manual_patient_phone.strip()

        if visit_id is not None:
            await self._visit_service.get_visit(visit_id)

        resolved: list[tuple[Medicine, int]] = []
        for medicine_id, quantity in items:
            medicine = await self._get_medicine(medicine_id)
            if not medicine.is_active:
                raise MedicineInactiveError(medicine.name)
            resolved.append((medicine, quantity))

        total = sum(
            (quantize_money(medicine.unit_price * quantity) for medicine, quantity in resolved),
            _ZERO,
        )

        bill = MedicineBill(
            visit_id=visit_id,
            total_amount=total,
            amount_paid=_ZERO,
            status=MedicineBillStatus.UNPAID,
            manual_patient_name=manual_patient_name,
            manual_patient_age=manual_patient_age,
            manual_patient_phone=manual_patient_phone,
            created_by=actor.id,
            updated_by=actor.id,
        )
        await self._bill_repo.add(bill)

        for medicine, quantity in resolved:
            line_total = quantize_money(medicine.unit_price * quantity)
            await self._item_repo.add(
                MedicineBillItem(
                    medicine_bill_id=bill.id,
                    medicine_id=medicine.id,
                    medicine_name_snapshot=medicine.name,
                    category_snapshot=medicine.category,
                    unit_price_snapshot=medicine.unit_price,
                    quantity=quantity,
                    line_total=line_total,
                    created_by=actor.id,
                    updated_by=actor.id,
                )
            )

        await self._audit_repo.record(
            module="pharmacy",
            action="pharmacy.bill_created",
            entity_type="medicine_bill",
            entity_id=bill.id,
            actor_user_id=actor.id,
            metadata={
                "visit_id": str(visit_id) if visit_id else None,
                "total_amount": str(total),
                "line_item_count": len(resolved),
                "manual_patient_name": manual_patient_name,
            },
        )

        initial_payment_amount = (
            quantize_money(initial_payment_amount) if initial_payment_amount else _ZERO
        )
        if initial_payment_amount < _ZERO:
            raise ValidationError("initial_payment_amount cannot be negative.")
        if initial_payment_amount > _ZERO:
            await self._apply_payment(bill=bill, actor=actor, amount=initial_payment_amount)

        await self._session.commit()
        return await self._get_bill(bill.id)

    async def _get_bill(self, bill_id: UUID) -> MedicineBill:
        bill = await self._bill_repo.get_by_id(bill_id)
        if bill is None:
            raise MedicineBillNotFoundError
        return bill

    async def get_bill(self, bill_id: UUID) -> MedicineBill:
        return await self._get_bill(bill_id)

    async def get_bill_items(self, bill_id: UUID) -> list[MedicineBillItem]:
        return await self._item_repo.list_for_bill(bill_id)

    async def get_bill_payments(self, bill_id: UUID) -> list[MedicineBillPayment]:
        return await self._payment_repo.list_for_bill(bill_id)

    async def _apply_payment(self, *, bill: MedicineBill, actor: User, amount: Decimal) -> bool:
        """Shared by `create_bill`'s optional initial payment above and
        `record_payment`'s top-up payment below — validates `amount`
        against the remaining balance, mutates `bill.amount_paid`/
        `status`/`paid_at` in memory, stages a new `MedicineBillPayment`
        audit row, and records the audit-log entry. Never commits.
        Returns whether this payment brought the bill to fully `PAID`.

        Assumes the bill is already known payable (not `PAID`) —
        `record_payment` checks that itself before calling this;
        `create_bill`'s bill is always freshly created and `UNPAID` by
        construction, so it never needs the check."""
        if amount <= _ZERO:
            raise ValidationError("Payment amount must be greater than zero.")
        amount = quantize_money(amount)

        remaining = bill.total_amount - bill.amount_paid
        if amount > remaining:
            raise MedicineBillPaymentExceedsBalanceError(str(remaining))

        bill.amount_paid = bill.amount_paid + amount
        bill.updated_by = actor.id
        fully_paid = bill.amount_paid == bill.total_amount
        if fully_paid:
            bill.status = MedicineBillStatus.PAID
            bill.paid_at = datetime.now(UTC)
        else:
            bill.status = MedicineBillStatus.PARTIALLY_PAID
        await self._bill_repo.add(bill)
        await self._payment_repo.add(
            MedicineBillPayment(
                medicine_bill_id=bill.id,
                amount=amount,
                created_by=actor.id,
                updated_by=actor.id,
            )
        )
        await self._audit_repo.record(
            module="pharmacy",
            action="pharmacy.payment_recorded",
            entity_type="medicine_bill",
            entity_id=bill.id,
            actor_user_id=actor.id,
            metadata={"amount": str(amount), "fully_paid": fully_paid},
        )
        return fully_paid

    async def record_payment(self, *, actor: User, bill_id: UUID, amount: Decimal) -> MedicineBill:
        """Records an *additional* payment against an already-created
        bill — topping up toward the remaining balance later, not the
        primary way a bill gets its first payment (see `create_bill`'s
        `initial_payment_amount` for that). Same shape as
        `BillingService.record_payment` — see that method's docstring
        for the full `SELECT ... FOR UPDATE` rationale (identical here:
        a read-modify-write on a money field). A fully `PAID` bill is
        immutable, matching `Invoice`'s `PAID`/`CANCELLED` immutability;
        `MedicineBill` has no `CANCELLED` equivalent, so `PAID` is the
        only terminal state to guard against here."""
        bill = await self._bill_repo.get_for_update(bill_id)
        if bill is None:
            raise MedicineBillNotFoundError
        if bill.status == MedicineBillStatus.PAID:
            raise MedicineBillNotPayableError(bill.status.value)

        await self._apply_payment(bill=bill, actor=actor, amount=amount)
        await self._session.commit()
        return await self._get_bill(bill.id)

    async def list_bill_summaries_for_day(self, day: datetime) -> list[tuple[MedicineBill, int]]:
        """`(bill, item_count)` pairs for every medicine bill created on
        `day` — a single line-item count query for the whole day (see
        repository.py's `count_items_for_bills`), not one per bill."""
        bills = await self._bill_repo.list_for_day(day)
        counts = await self._item_repo.count_items_for_bills([bill.id for bill in bills])
        return [(bill, counts.get(bill.id, 0)) for bill in bills]

    async def count_and_revenue_by_creator(self) -> dict[UUID, tuple[int, Decimal]]:
        """Read-only aggregate added for the Admin "Employee Accounts &
        Stats" page — see MedicineBillRepository.count_and_revenue_by_creator."""
        return await self._bill_repo.count_and_revenue_by_creator()
