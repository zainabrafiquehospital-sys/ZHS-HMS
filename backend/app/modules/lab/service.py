"""Laboratory Billing business logic.

Three independent concerns, the exact same split app/modules/pharmacy/
service.py's `PharmacyService` already established:
- Managing the lab test price list (`create_test`/`update_test`) —
  plain CRUD, Admin-only (`lab:manage`).
- Building and finalizing a `LabBill` in one action (`create_bill`) —
  validates every line's test exists and is active, snapshots its
  name/category/price at billing time, computes the bill's total via
  `quantize_money()`, and persists the bill, every item, and an
  optional initial payment all in one transaction — the same shape as
  `PharmacyService.create_bill`. `manual_patient_name`/`_age`/`_phone`
  (optional, all-or-nothing, mutually exclusive with `patient_id`) let
  Reception put a name/age/contact on the printed slip without an
  existing Patient to link — see models.py's `LabBill` docstring.
  `patient_id` is a direct Patient link (confirmed design), never a
  Visit — this module does not depend on `VisitService` at all.
- Recording a payment against a bill (`record_payment`) — an
  *additional*, later top-up toward the remaining balance, sharing its
  actual validate-and-apply logic with `create_bill`'s initial payment
  via the private `_apply_payment` helper — identical shape and
  concurrency handling (`SELECT ... FOR UPDATE`) to
  `PharmacyService.record_payment`."""

from datetime import UTC, datetime
from decimal import Decimal
from typing import Any
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import ValidationError
from app.modules.auth.models import User
from app.modules.lab.exceptions import (
    LabBillDiscountExceedsSubtotalError,
    LabBillHasSettledPaymentError,
    LabBillManualPatientConflictsWithPatientError,
    LabBillManualPatientFieldsIncompleteError,
    LabBillNotFoundError,
    LabBillNotPayableError,
    LabBillPaymentExceedsBalanceError,
    LabBillPaymentMethodRequiredError,
    LabTestInactiveError,
    LabTestNotFoundError,
)
from app.modules.lab.models import (
    LabBill,
    LabBillItem,
    LabBillPayment,
    LabBillStatus,
    LabTest,
    LabTestCategory,
)
from app.modules.lab.repository import (
    LAB_TEST_SORTABLE_COLUMNS,
    LabBillItemRepository,
    LabBillPaymentRepository,
    LabBillRepository,
    LabTestRepository,
)
from app.modules.patients.service import PatientService
from app.modules.visits.constants import QUEUE_TOKEN_PAD_WIDTH, QUEUE_TOKEN_PREFIX
from app.shared.audit.repository import AuditLogRepository
from app.shared.money import quantize_money
from app.shared.payment_method import PaymentMethod

_ZERO = Decimal("0.00")

# One (lab_test_id, name, category, price) resolved bill line — `name`/
# `category`/`price` are the already-resolved-and-locked values
# (catalog-derived when `lab_test_id` is set, freely-provided/`None`
# category when it's not), never the raw, not-yet-validated request
# shape. Mirrors app/modules/visits/service.py's identical
# `ResolvedProcedure`. See `_resolve_items`.
ResolvedLabItem = tuple[UUID | None, str, LabTestCategory | None, Decimal]


class LabService:
    def __init__(
        self,
        session: AsyncSession,
        lab_test_repository: LabTestRepository,
        lab_bill_repository: LabBillRepository,
        lab_bill_item_repository: LabBillItemRepository,
        lab_bill_payment_repository: LabBillPaymentRepository,
        patient_service: PatientService,
        audit_repository: AuditLogRepository,
    ) -> None:
        self._session = session
        self._test_repo = lab_test_repository
        self._bill_repo = lab_bill_repository
        self._item_repo = lab_bill_item_repository
        self._payment_repo = lab_bill_payment_repository
        self._patient_service = patient_service
        self._audit_repo = audit_repository

    async def _generate_queue_token(self) -> str:
        """Mirrors `PharmacyService._generate_queue_token` exactly —
        same prefix/pad-width formatting, and the same underlying
        Postgres sequence, drawn via `LabBillRepository.
        next_queue_token_value`."""
        value = await self._bill_repo.next_queue_token_value()
        return f"{QUEUE_TOKEN_PREFIX}{value:0{QUEUE_TOKEN_PAD_WIDTH}d}"

    # ------------------------------------------------------------------
    # Lab test price list (Admin-only, lab:manage)
    # ------------------------------------------------------------------

    async def create_test(
        self, *, actor: User, name: str, category: LabTestCategory, price: Decimal
    ) -> LabTest:
        test = LabTest(
            name=name,
            category=category,
            price=quantize_money(price),
            is_active=True,
            created_by=actor.id,
            updated_by=actor.id,
        )
        await self._test_repo.add(test)
        await self._audit_repo.record(
            module="lab",
            action="lab.test_created",
            entity_type="lab_test",
            entity_id=test.id,
            actor_user_id=actor.id,
            metadata={"name": name},
        )
        await self._session.commit()
        return await self._get_test(test.id)

    async def _get_test(self, lab_test_id: UUID) -> LabTest:
        test = await self._test_repo.get_by_id(lab_test_id)
        if test is None:
            raise LabTestNotFoundError
        return test

    async def get_test(self, lab_test_id: UUID) -> LabTest:
        return await self._get_test(lab_test_id)

    async def update_test(self, *, actor: User, lab_test_id: UUID, updates: dict) -> LabTest:
        """Partial update — `updates` comes straight from
        `UpdateLabTestRequest.model_dump(exclude_unset=True)`, same
        `exclude_unset` semantics as `PharmacyService.update_medicine`."""
        test = await self._get_test(lab_test_id)
        if not updates:
            return test

        for field in ("name", "category", "price", "is_active"):
            if field in updates:
                value = updates[field]
                if field == "price" and value is not None:
                    value = quantize_money(value)
                setattr(test, field, value)

        test.updated_by = actor.id
        await self._test_repo.add(test)
        await self._audit_repo.record(
            module="lab",
            action="lab.test_updated",
            entity_type="lab_test",
            entity_id=test.id,
            actor_user_id=actor.id,
            metadata={"fields": sorted(updates.keys())},
        )
        await self._session.commit()
        return await self._get_test(test.id)

    async def search_tests(self, *, search: str, limit: int = 20) -> list[LabTest]:
        return await self._test_repo.search_active(search=search, limit=limit)

    async def list_tests(
        self, *, search: str | None, sort_by: str, sort_desc: bool, page: int, page_size: int
    ) -> tuple[list[LabTest], int]:
        sort_column = LAB_TEST_SORTABLE_COLUMNS[sort_by]
        return await self._test_repo.list_all(
            search=search,
            sort_column=sort_column,
            sort_desc=sort_desc,
            limit=page_size,
            offset=(page - 1) * page_size,
        )

    # ------------------------------------------------------------------
    # Lab bills (Receptionist + Admin, lab:bill / lab:read)
    # ------------------------------------------------------------------

    async def _resolve_items(
        self, items: list[tuple[UUID | None, str | None, Decimal | None]]
    ) -> list[ResolvedLabItem]:
        """Turns the caller's raw `(lab_test_id, manual_name,
        manual_price)` request triples into resolved, trustworthy
        `(lab_test_id, name, category, price)` lines — the lab-bill
        sibling of app/modules/visits/service.py's identical
        `_resolve_procedures`, mirrored as closely as the two modules'
        shapes allow.

        A catalog-linked entry (`lab_test_id` given) has its `name`/
        `category`/`price` always re-derived from the LabTest row
        itself, never trusted from the caller (mirrors this class's own
        `medicine_name_snapshot`-style price-integrity rule) —
        `LabTestInactiveError` if it's been deactivated, exactly like a
        deactivated Medicine can't be billed. A manual entry
        (`lab_test_id` is `None`) uses the caller's own `manual_name`/
        `manual_price` directly, stripped/quantized, with `category`
        always `None` — a manual line has no catalog category to
        snapshot."""
        resolved: list[ResolvedLabItem] = []
        for lab_test_id, manual_name, manual_price in items:
            if lab_test_id is not None:
                test = await self._get_test(lab_test_id)
                if not test.is_active:
                    raise LabTestInactiveError(test.name)
                resolved.append((lab_test_id, test.name, test.category, test.price))
            else:
                resolved.append((None, manual_name.strip(), None, quantize_money(manual_price)))
        return resolved

    async def create_bill(
        self,
        *,
        actor: User,
        patient_id: UUID | None,
        items: list[tuple[UUID | None, str | None, Decimal | None]],
        initial_payment_amount: Decimal = _ZERO,
        initial_payment_method: PaymentMethod | None = None,
        manual_patient_name: str | None = None,
        manual_patient_age: int | None = None,
        manual_patient_phone: str | None = None,
        discount_amount: Decimal = _ZERO,
        discount_reason: str | None = None,
    ) -> LabBill:
        """`items` is a list of raw `(lab_test_id, manual_name,
        manual_price)` triples, already validated non-empty by
        `CreateLabBillRequest` and resolved here via `_resolve_items`
        (2026-08-28 addition — previously catalog-only, a plain list of
        `lab_test_id`s) — no quantity per line either way (see
        models.py's `LabBillItem` docstring): the same test id (or the
        same manual name) appearing twice in this list simply becomes
        two independent line rows. Every catalog test referenced must
        exist and be active — checked up front, before anything is
        written, so a bad line item never leaves a partially-built bill
        behind.

        Every new bill draws its own `queue_token` from the exact same
        unified Postgres sequence Visit/MedicineBill both use (see
        `_generate_queue_token`'s own docstring).

        `initial_payment_amount`/`initial_payment_method` fold
        collecting whatever the patient is paying right now into this
        same call and the same commit, via the shared `_apply_payment`
        helper also used by `record_payment` below — identical to
        `PharmacyService.create_bill`'s own mechanism.

        `patient_id` is a direct Patient link (confirmed design,
        deliberately never a Visit) — mutually exclusive with
        `manual_patient_name`/`_age`/`_phone` (all-or-nothing when
        used) — see models.py's `LabBill` docstring for the full
        rationale and the DB-level CHECK constraints that also enforce
        these two rules.

        `discount_amount` is a flat discount off the sum of line items
        — validated here against the subtotal (never against
        `total_amount`, which does not exist until this same
        computation), and `total_amount` is stored already
        post-discount, never separately. `discount_reason` is always
        optional, even when `discount_amount > 0` — the same product
        decision `PharmacyService.create_bill` already makes for its
        own identical field."""
        manual_fields = (manual_patient_name, manual_patient_age, manual_patient_phone)
        any_manual_field = any(field is not None for field in manual_fields)
        all_manual_fields = all(field is not None for field in manual_fields)
        if any_manual_field and not all_manual_fields:
            raise LabBillManualPatientFieldsIncompleteError
        if any_manual_field and patient_id is not None:
            raise LabBillManualPatientConflictsWithPatientError
        if manual_patient_name is not None:
            manual_patient_name = manual_patient_name.strip()
        if manual_patient_phone is not None:
            manual_patient_phone = manual_patient_phone.strip()

        if patient_id is not None:
            await self._patient_service.get_patient(patient_id)

        resolved = await self._resolve_items(items)

        subtotal = sum((price for _, _, _, price in resolved), _ZERO)

        discount_amount = quantize_money(discount_amount) if discount_amount else _ZERO
        if discount_amount < _ZERO:
            raise ValidationError("discount_amount cannot be negative.")
        discount_reason = discount_reason.strip() if discount_reason else None
        if discount_amount == _ZERO:
            discount_reason = None
        if discount_amount > subtotal:
            raise LabBillDiscountExceedsSubtotalError(str(subtotal))
        total = subtotal - discount_amount

        bill = LabBill(
            patient_id=patient_id,
            queue_token=await self._generate_queue_token(),
            total_amount=total,
            amount_paid=_ZERO,
            status=LabBillStatus.UNPAID,
            manual_patient_name=manual_patient_name,
            manual_patient_age=manual_patient_age,
            manual_patient_phone=manual_patient_phone,
            discount_amount=discount_amount,
            discount_reason=discount_reason,
            created_by=actor.id,
            updated_by=actor.id,
        )
        await self._bill_repo.add(bill)

        for lab_test_id, name, category, price in resolved:
            await self._item_repo.add(
                LabBillItem(
                    lab_bill_id=bill.id,
                    lab_test_id=lab_test_id,
                    lab_test_name_snapshot=name,
                    category_snapshot=category,
                    unit_price_snapshot=price,
                    created_by=actor.id,
                    updated_by=actor.id,
                )
            )

        await self._audit_repo.record(
            module="lab",
            action="lab.bill_created",
            entity_type="lab_bill",
            entity_id=bill.id,
            actor_user_id=actor.id,
            metadata={
                "patient_id": str(patient_id) if patient_id else None,
                "total_amount": str(total),
                "line_item_count": len(resolved),
                "manual_patient_name": manual_patient_name,
                "discount_amount": str(discount_amount),
            },
        )

        initial_payment_amount = (
            quantize_money(initial_payment_amount) if initial_payment_amount else _ZERO
        )
        if initial_payment_amount < _ZERO:
            raise ValidationError("initial_payment_amount cannot be negative.")
        if initial_payment_amount > _ZERO:
            if initial_payment_method is None:
                raise LabBillPaymentMethodRequiredError
            await self._apply_payment(
                bill=bill,
                actor=actor,
                amount=initial_payment_amount,
                payment_method=initial_payment_method,
            )

        await self._session.commit()
        return await self._get_bill(bill.id)

    async def _get_bill(self, bill_id: UUID) -> LabBill:
        bill = await self._bill_repo.get_by_id(bill_id)
        if bill is None:
            raise LabBillNotFoundError
        return bill

    async def get_bill(self, bill_id: UUID) -> LabBill:
        return await self._get_bill(bill_id)

    async def get_bill_items(self, bill_id: UUID) -> list[LabBillItem]:
        return await self._item_repo.list_for_bill(bill_id)

    async def get_bill_payments(self, bill_id: UUID) -> list[LabBillPayment]:
        return await self._payment_repo.list_for_bill(bill_id)

    async def _apply_payment(
        self, *, bill: LabBill, actor: User, amount: Decimal, payment_method: PaymentMethod
    ) -> bool:
        """Shared by `create_bill`'s optional initial payment above and
        `record_payment`'s top-up payment below — identical mechanism
        to `PharmacyService._apply_payment`. Never commits. Returns
        whether this payment brought the bill to fully `PAID`."""
        if amount <= _ZERO:
            raise ValidationError("Payment amount must be greater than zero.")
        amount = quantize_money(amount)

        remaining = bill.total_amount - bill.amount_paid
        if amount > remaining:
            raise LabBillPaymentExceedsBalanceError(str(remaining))

        bill.amount_paid = bill.amount_paid + amount
        bill.updated_by = actor.id
        fully_paid = bill.amount_paid == bill.total_amount
        if fully_paid:
            bill.status = LabBillStatus.PAID
            bill.paid_at = datetime.now(UTC)
        else:
            bill.status = LabBillStatus.PARTIALLY_PAID
        await self._bill_repo.add(bill)
        await self._payment_repo.add(
            LabBillPayment(
                lab_bill_id=bill.id,
                amount=amount,
                payment_method=payment_method,
                created_by=actor.id,
                updated_by=actor.id,
            )
        )
        await self._audit_repo.record(
            module="lab",
            action="lab.payment_recorded",
            entity_type="lab_bill",
            entity_id=bill.id,
            actor_user_id=actor.id,
            metadata={
                "amount": str(amount),
                "payment_method": payment_method.value,
                "fully_paid": fully_paid,
            },
        )
        return fully_paid

    async def record_payment(
        self, *, actor: User, bill_id: UUID, amount: Decimal, payment_method: PaymentMethod
    ) -> LabBill:
        """Records an *additional* payment against an already-created
        bill — same shape as `PharmacyService.record_payment`. A fully
        `PAID` bill is immutable, the only terminal state to guard
        against here."""
        bill = await self._bill_repo.get_for_update(bill_id)
        if bill is None:
            raise LabBillNotFoundError
        if bill.status == LabBillStatus.PAID:
            raise LabBillNotPayableError(bill.status.value)

        await self._apply_payment(
            bill=bill, actor=actor, amount=amount, payment_method=payment_method
        )
        await self._session.commit()
        return await self._get_bill(bill.id)

    # ------------------------------------------------------------------
    # Admin data correction — the lab-bill sibling of
    # PharmacyService.admin_update_bill/admin_delete_bill, gated on
    # lab:update_bill/lab:delete_bill at the router (never on lab:bill),
    # never granted to Receptionist. Both actions are blocked outright
    # once the bill has any recorded payment.
    # ------------------------------------------------------------------

    async def admin_update_bill(
        self, *, actor: User, bill_id: UUID, updates: dict[str, Any]
    ) -> LabBill:
        """Corrects a mistakenly-entered lab bill's manual patient
        details and/or its discount, in one call — identical shape to
        `PharmacyService.admin_update_bill`.

        `manual_patient_name`/`_age`/`_phone` are only accepted when
        the bill has no linked `patient_id` — raises
        `LabBillManualPatientConflictsWithPatientError` otherwise.
        `discount_amount` (when present) is revalidated against the
        bill's current line-item subtotal, and `total_amount` is
        recomputed from it. `amount_paid` is always 0 at this point —
        guaranteed by the UNPAID-only block below."""
        bill = await self._get_bill(bill_id)
        if not updates:
            return bill
        if bill.status != LabBillStatus.UNPAID:
            raise LabBillHasSettledPaymentError

        manual_fields = ("manual_patient_name", "manual_patient_age", "manual_patient_phone")
        manual_updates = {k: v for k, v in updates.items() if k in manual_fields}
        if manual_updates and bill.patient_id is not None:
            raise LabBillManualPatientConflictsWithPatientError
        for field in manual_fields:
            if field in updates:
                value = updates[field]
                if field in ("manual_patient_name", "manual_patient_phone") and value is not None:
                    value = value.strip()
                setattr(bill, field, value)

        if "discount_amount" in updates or "discount_reason" in updates:
            items = await self._item_repo.list_for_bill(bill.id)
            subtotal = sum((item.unit_price_snapshot for item in items), _ZERO)

            requested_discount = updates.get("discount_amount")
            new_discount_amount = (
                quantize_money(requested_discount)
                if requested_discount is not None
                else bill.discount_amount
            )
            if new_discount_amount < _ZERO:
                raise ValidationError("discount_amount cannot be negative.")
            if new_discount_amount > subtotal:
                raise LabBillDiscountExceedsSubtotalError(str(subtotal))

            new_discount_reason = (
                updates["discount_reason"] if "discount_reason" in updates else bill.discount_reason
            )
            new_discount_reason = new_discount_reason.strip() if new_discount_reason else None
            if new_discount_amount == _ZERO:
                new_discount_reason = None

            bill.discount_amount = new_discount_amount
            bill.discount_reason = new_discount_reason
            bill.total_amount = subtotal - new_discount_amount

        bill.updated_by = actor.id
        await self._bill_repo.add(bill)
        await self._audit_repo.record(
            module="lab",
            action="lab.bill_updated_by_admin",
            entity_type="lab_bill",
            entity_id=bill.id,
            actor_user_id=actor.id,
            metadata={"fields": sorted(updates.keys())},
        )
        await self._session.commit()
        return await self._get_bill(bill.id)

    async def admin_delete_bill(self, *, actor: User, bill_id: UUID) -> None:
        """Soft-deletes a LabBill an admin has decided was a mistake —
        identical shape to `PharmacyService.admin_delete_bill`. Never a
        hard `DELETE`. The bill's own `LabBillItem` rows (and any
        `LabBillPayment` rows — none exist here by construction, since
        the block above only lets an UNPAID bill reach this point) are
        left untouched."""
        bill = await self._get_bill(bill_id)
        if bill.status != LabBillStatus.UNPAID:
            raise LabBillHasSettledPaymentError

        now = datetime.now(UTC)
        await self._bill_repo.soft_delete(bill, deleted_at=now, deleted_by=actor.id)
        await self._audit_repo.record(
            module="lab",
            action="lab.bill_deleted_by_admin",
            entity_type="lab_bill",
            entity_id=bill_id,
            actor_user_id=actor.id,
            metadata={"queue_token": bill.queue_token},
        )
        await self._session.commit()

    async def list_bill_summaries_for_day(
        self, day: datetime
    ) -> list[tuple[LabBill, int, list[str]]]:
        """`(bill, item_count, payment_methods)` triples for every lab
        bill created on `day` — identical shape to `PharmacyService.
        list_bill_summaries_for_day`, backing Admin Overview's Lab
        Bills tab."""
        bills = await self._bill_repo.list_for_day(day)
        bill_ids = [bill.id for bill in bills]
        counts = await self._item_repo.count_items_for_bills(bill_ids)
        methods = await self._payment_repo.list_distinct_payment_methods_for_bills(bill_ids)
        return [(bill, counts.get(bill.id, 0), methods.get(bill.id, [])) for bill in bills]

    async def list_bills_for_creator(
        self, user_id: UUID, *, page: int, page_size: int
    ) -> tuple[list[tuple[LabBill, int, list[str]]], int]:
        """`(bill, item_count, payment_methods)` triples for every lab
        bill `user_id` has personally created, newest first, real
        server-side pagination — backs the receptionist's own "My Lab
        Bills" list, identical shape to `PharmacyService.
        list_bills_for_creator`."""
        bills, total = await self._bill_repo.list_for_creator(
            user_id, page=page, page_size=page_size
        )
        bill_ids = [bill.id for bill in bills]
        counts = await self._item_repo.count_items_for_bills(bill_ids)
        methods = await self._payment_repo.list_distinct_payment_methods_for_bills(bill_ids)
        return [(bill, counts.get(bill.id, 0), methods.get(bill.id, [])) for bill in bills], total

    async def list_bills_for_patient(
        self, patient_id: UUID
    ) -> list[tuple[LabBill, int, list[str]]]:
        """`(bill, item_count, payment_methods)` triples for every lab
        bill actually linked to this Patient, oldest first — identical
        shape to `list_bill_summaries_for_day`/`list_bills_for_creator`
        above, backing the Patient History aggregation module
        (app/modules/patient_history/service.py)."""
        bills = await self._bill_repo.list_for_patient(patient_id)
        bill_ids = [bill.id for bill in bills]
        counts = await self._item_repo.count_items_for_bills(bill_ids)
        methods = await self._payment_repo.list_distinct_payment_methods_for_bills(bill_ids)
        return [(bill, counts.get(bill.id, 0), methods.get(bill.id, [])) for bill in bills]

    async def count_and_revenue_by_creator(self) -> dict[UUID, tuple[int, Decimal]]:
        """Read-only aggregate for the Admin "Employee Accounts &
        Stats" page — see LabBillRepository.count_and_revenue_by_creator."""
        return await self._bill_repo.count_and_revenue_by_creator()
