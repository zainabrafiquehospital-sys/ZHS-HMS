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
from typing import Any
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import ValidationError
from app.modules.auth.models import User
from app.modules.pharmacy.exceptions import (
    MedicineBillDiscountExceedsSubtotalError,
    MedicineBillHasSettledPaymentError,
    MedicineBillManualPatientConflictsWithVisitError,
    MedicineBillManualPatientFieldsIncompleteError,
    MedicineBillNotFoundError,
    MedicineBillNotPayableError,
    MedicineBillPaymentExceedsBalanceError,
    MedicineBillPaymentMethodRequiredError,
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
from app.modules.visits.constants import QUEUE_TOKEN_PAD_WIDTH, QUEUE_TOKEN_PREFIX
from app.modules.visits.service import VisitService
from app.shared.audit.repository import AuditLogRepository
from app.shared.money import quantize_money
from app.shared.payment_method import PaymentMethod

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

    async def _generate_queue_token(self) -> str:
        """Mirrors `VisitService._generate_queue_token` exactly — same
        prefix/pad-width formatting, and (2026-08-20 addition) the same
        underlying Postgres sequence, drawn via
        `MedicineBillRepository.next_queue_token_value`. This is what
        makes a Visit and a MedicineBill created moments apart get
        truly consecutive, interleaved numbers."""
        value = await self._bill_repo.next_queue_token_value()
        return f"{QUEUE_TOKEN_PREFIX}{value:0{QUEUE_TOKEN_PAD_WIDTH}d}"

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
        initial_payment_method: PaymentMethod | None = None,
        manual_patient_name: str | None = None,
        manual_patient_age: int | None = None,
        manual_patient_phone: str | None = None,
        discount_amount: Decimal = _ZERO,
        discount_reason: str | None = None,
    ) -> MedicineBill:
        """`items` is a list of `(medicine_id, quantity)` pairs, already
        validated non-empty by `CreateMedicineBillRequest`. Every
        medicine referenced must exist and be active — checked up front,
        before anything is written, so a bad line item never leaves a
        partially-built bill behind.

        Every new bill draws its own `queue_token` (2026-08-20 addition)
        from the exact same unified Postgres sequence Visit uses (see
        `_generate_queue_token`'s own docstring) — this is a fresh draw
        every time, never the linked Visit's own token, so a bill
        created between two visit registrations still gets the next
        number in true chronological order across both entity types.

        `initial_payment_amount` (optional, defaults to none) folds
        collecting whatever the patient is paying right now into this
        same call and the same commit, via the shared `_apply_payment`
        helper also used by `record_payment` below — the identical
        merge `BillingService.generate_invoice` does for Invoices, see
        that method's docstring for the full rationale. Recording no
        payment at all (the default) still works exactly as before: a
        bill with no `initial_payment_amount` is created `UNPAID`, same
        as ever. `initial_payment_method` (2026-08-19 addition) is
        required whenever `initial_payment_amount > 0` —
        `MedicineBillPaymentMethodRequiredError` otherwise — and simply
        ignored when no payment is being recorded at all.

        `manual_patient_name`/`manual_patient_age`/`manual_patient_phone`
        (all optional, default None) are purely display information for
        the printed slip when no registered Patient/Visit is being
        linked — see models.py's `MedicineBill` docstring for the full
        rationale and the DB-level CHECK constraints that also enforce
        the two rules validated here: mutually exclusive with
        `visit_id`, and all-or-nothing (never a partial manual entry).

        `discount_amount` (optional, defaults to none, 2026-08-19
        addition) is a flat discount off the sum of line items — same
        shape as `BillingService.generate_invoice`'s identical
        parameter: validated here against the subtotal (never against
        `total_amount`, which does not exist until this same
        computation), and `total_amount` is stored already
        post-discount, never separately. Unlike Invoice's discount,
        `discount_reason` is always optional here, even when
        `discount_amount > 0` — a deliberate product decision for this
        feature, so there is no reason-required check to mirror."""
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

        subtotal = sum(
            (quantize_money(medicine.unit_price * quantity) for medicine, quantity in resolved),
            _ZERO,
        )

        discount_amount = quantize_money(discount_amount) if discount_amount else _ZERO
        if discount_amount < _ZERO:
            raise ValidationError("discount_amount cannot be negative.")
        discount_reason = discount_reason.strip() if discount_reason else None
        if discount_amount == _ZERO:
            discount_reason = None
        if discount_amount > subtotal:
            raise MedicineBillDiscountExceedsSubtotalError(str(subtotal))
        total = subtotal - discount_amount

        bill = MedicineBill(
            visit_id=visit_id,
            queue_token=await self._generate_queue_token(),
            total_amount=total,
            amount_paid=_ZERO,
            status=MedicineBillStatus.UNPAID,
            manual_patient_name=manual_patient_name,
            manual_patient_age=manual_patient_age,
            manual_patient_phone=manual_patient_phone,
            discount_amount=discount_amount,
            discount_reason=discount_reason,
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
                raise MedicineBillPaymentMethodRequiredError
            await self._apply_payment(
                bill=bill,
                actor=actor,
                amount=initial_payment_amount,
                payment_method=initial_payment_method,
            )

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

    async def _apply_payment(
        self, *, bill: MedicineBill, actor: User, amount: Decimal, payment_method: PaymentMethod
    ) -> bool:
        """Shared by `create_bill`'s optional initial payment above and
        `record_payment`'s top-up payment below — validates `amount`
        against the remaining balance, mutates `bill.amount_paid`/
        `status`/`paid_at` in memory, stages a new `MedicineBillPayment`
        audit row, and records the audit-log entry. Never commits.
        Returns whether this payment brought the bill to fully `PAID`.

        Assumes the bill is already known payable (not `PAID`) —
        `record_payment` checks that itself before calling this;
        `create_bill`'s bill is always freshly created and `UNPAID` by
        construction, so it never needs the check.

        `payment_method` (2026-08-19 addition) mirrors
        `BillingService._apply_payment`'s identical parameter — required
        by both callers, stored on this individual `MedicineBillPayment`
        row only (never on the bill itself), so a partial cash payment
        now and a bank transfer later are correctly two separate,
        independently attributed rows."""
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
                payment_method=payment_method,
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
            metadata={
                "amount": str(amount),
                "payment_method": payment_method.value,
                "fully_paid": fully_paid,
            },
        )
        return fully_paid

    async def record_payment(
        self, *, actor: User, bill_id: UUID, amount: Decimal, payment_method: PaymentMethod
    ) -> MedicineBill:
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

        await self._apply_payment(
            bill=bill, actor=actor, amount=amount, payment_method=payment_method
        )
        await self._session.commit()
        return await self._get_bill(bill.id)

    # ------------------------------------------------------------------
    # Admin data correction (2026-08-20 addition) — the medicine-bill
    # sibling of ReceptionService.admin_update_visit/admin_delete_visit,
    # gated on pharmacy:update_bill/pharmacy:delete_bill at the router
    # (never on pharmacy:bill), never granted to Receptionist (see
    # constants.py). Both actions are blocked outright, before anything
    # is touched, once the bill has any recorded payment — see
    # MedicineBillHasSettledPaymentError's own docstring for why this
    # applies to *edit* here too, unlike Visit's own admin-update (which
    # has no equivalent block): a MedicineBill's `discount_amount`
    # directly determines this same row's `total_amount`, unlike
    # Visit's decoupled Invoice.
    # ------------------------------------------------------------------

    async def admin_update_bill(
        self, *, actor: User, bill_id: UUID, updates: dict[str, Any]
    ) -> MedicineBill:
        """Corrects a mistakenly-entered medicine bill's manual patient
        details and/or its discount, in one call (`updates` is already-
        validated PATCH-style, `AdminUpdateMedicineBillRequest.
        model_dump(exclude_unset=True)`).

        `manual_patient_name`/`_age`/`_phone` are only accepted when the
        bill has no linked `visit_id` — raises
        `MedicineBillManualPatientConflictsWithVisitError`, the exact
        same exception `create_bill` raises for the identical rule,
        otherwise. A visit-linked bill's patient identity belongs to
        that Visit's own Patient record, corrected through Reception's
        existing "Edit Slip" action instead — never duplicated here.

        `discount_amount` (when present) is revalidated against the
        bill's current line-item subtotal exactly as `create_bill`
        validates a fresh one, and `total_amount` is recomputed from
        it. `amount_paid` is always 0 at this point — guaranteed by the
        UNPAID-only block above — so no payment/status recomputation is
        ever needed, unlike a hypothetical edit on a partially-paid
        bill."""
        bill = await self._get_bill(bill_id)
        if not updates:
            return bill
        if bill.status != MedicineBillStatus.UNPAID:
            raise MedicineBillHasSettledPaymentError

        manual_fields = ("manual_patient_name", "manual_patient_age", "manual_patient_phone")
        manual_updates = {k: v for k, v in updates.items() if k in manual_fields}
        if manual_updates and bill.visit_id is not None:
            raise MedicineBillManualPatientConflictsWithVisitError
        for field in manual_fields:
            if field in updates:
                value = updates[field]
                if field in ("manual_patient_name", "manual_patient_phone") and value is not None:
                    value = value.strip()
                setattr(bill, field, value)

        if "discount_amount" in updates or "discount_reason" in updates:
            items = await self._item_repo.list_for_bill(bill.id)
            subtotal = sum((item.line_total for item in items), _ZERO)

            requested_discount = updates.get("discount_amount")
            new_discount_amount = (
                quantize_money(requested_discount)
                if requested_discount is not None
                else bill.discount_amount
            )
            if new_discount_amount < _ZERO:
                raise ValidationError("discount_amount cannot be negative.")
            if new_discount_amount > subtotal:
                raise MedicineBillDiscountExceedsSubtotalError(str(subtotal))

            new_discount_reason = (
                updates["discount_reason"]
                if "discount_reason" in updates
                else bill.discount_reason
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
            module="pharmacy",
            action="pharmacy.bill_updated_by_admin",
            entity_type="medicine_bill",
            entity_id=bill.id,
            actor_user_id=actor.id,
            metadata={"fields": sorted(updates.keys())},
        )
        await self._session.commit()
        return await self._get_bill(bill.id)

    async def admin_delete_bill(self, *, actor: User, bill_id: UUID) -> None:
        """Soft-deletes a MedicineBill an admin has decided was a
        mistake — the medicine-bill sibling of VisitService.
        delete_visit/ReceptionService.admin_delete_visit. Never a hard
        `DELETE`: every existing bill query already filters `deleted_at
        IS NULL` (`BaseRepository.soft_delete`), so this alone is
        sufficient to make the bill disappear from every list/search/
        detail view. The bill's `MedicineBillItem` rows (and any
        `MedicineBillPayment` rows — none exist here by construction,
        since the block above only lets an UNPAID bill reach this
        point) are left untouched, the same "orphaned but never
        corrupted" outcome `VisitService.delete_visit`'s own docstring
        documents for Visit's own child rows."""
        bill = await self._get_bill(bill_id)
        if bill.status != MedicineBillStatus.UNPAID:
            raise MedicineBillHasSettledPaymentError

        now = datetime.now(UTC)
        await self._bill_repo.soft_delete(bill, deleted_at=now, deleted_by=actor.id)
        await self._audit_repo.record(
            module="pharmacy",
            action="pharmacy.bill_deleted_by_admin",
            entity_type="medicine_bill",
            entity_id=bill_id,
            actor_user_id=actor.id,
            metadata={"queue_token": bill.queue_token},
        )
        await self._session.commit()

    async def list_bill_summaries_for_day(
        self, day: datetime
    ) -> list[tuple[MedicineBill, int, list[str]]]:
        """`(bill, item_count, payment_methods)` triples for every
        medicine bill created on `day` — a single line-item count query
        and a single payment-methods query for the whole day (see
        repository.py's `count_items_for_bills`/
        `list_distinct_payment_methods_for_bills`), not one per bill.
        `payment_methods` (2026-08-19 addition) backs Admin Overview's
        Medicine Bills tab "Payment Method" column."""
        bills = await self._bill_repo.list_for_day(day)
        bill_ids = [bill.id for bill in bills]
        counts = await self._item_repo.count_items_for_bills(bill_ids)
        methods = await self._payment_repo.list_distinct_payment_methods_for_bills(bill_ids)
        return [(bill, counts.get(bill.id, 0), methods.get(bill.id, [])) for bill in bills]

    async def list_bills_for_creator(
        self, user_id: UUID, *, page: int, page_size: int
    ) -> tuple[list[tuple[MedicineBill, int, list[str]]], int]:
        """`(bill, item_count, payment_methods)` triples for every
        medicine bill `user_id` has personally created, newest first,
        real server-side pagination — the medicine-bill sibling of
        Reception's own "My Registrations" (`VisitRepository.search`'s
        `created_by` filter), added (2026-08-19) so a receptionist can
        see an itemized record of her own medicine bills, not just the
        "My Revenue" total. `user_id` always comes from the caller's
        own `actor.id` at the router layer, never a request-suppliable
        parameter — the same hard server-side scoping
        `ReceptionService.get_own_revenue` already established, so
        there is structurally no way to ask for someone else's bills
        through this method."""
        bills, total = await self._bill_repo.list_for_creator(
            user_id, page=page, page_size=page_size
        )
        bill_ids = [bill.id for bill in bills]
        counts = await self._item_repo.count_items_for_bills(bill_ids)
        methods = await self._payment_repo.list_distinct_payment_methods_for_bills(bill_ids)
        return [(bill, counts.get(bill.id, 0), methods.get(bill.id, [])) for bill in bills], total

    async def count_and_revenue_by_creator(self) -> dict[UUID, tuple[int, Decimal]]:
        """Read-only aggregate added for the Admin "Employee Accounts &
        Stats" page — see MedicineBillRepository.count_and_revenue_by_creator."""
        return await self._bill_repo.count_and_revenue_by_creator()

    async def list_bills_for_visits(
        self, visit_ids: list[UUID]
    ) -> list[tuple[MedicineBill, int, list[str]]]:
        """`(bill, item_count, payment_methods)` triples for every
        medicine bill linked to one of the given Visits, oldest first —
        identical shape to `list_bill_summaries_for_day`/
        `list_bills_for_creator` above, backing the Patient History
        aggregation module (app/modules/patient_history/service.py)."""
        bills = await self._bill_repo.list_for_visit_ids(visit_ids)
        bill_ids = [bill.id for bill in bills]
        counts = await self._item_repo.count_items_for_bills(bill_ids)
        methods = await self._payment_repo.list_distinct_payment_methods_for_bills(bill_ids)
        return [(bill, counts.get(bill.id, 0), methods.get(bill.id, [])) for bill in bills]
