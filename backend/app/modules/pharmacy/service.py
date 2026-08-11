"""Pharmacy / Medicine Billing business logic.

Two independent concerns:
- Managing the medicine price list (`create_medicine`/`update_medicine`)
  — plain CRUD, Admin-only (`pharmacy:manage`).
- Building and finalizing a `MedicineBill` in one action
  (`create_bill`) — validates every line item's medicine exists and is
  active, snapshots its name/price at billing time (see models.py's
  module docstring on why), computes each line total and the bill's
  grand total via `quantize_money()`, and persists the bill and every
  item in one transaction — the same shape as
  app/modules/billing/service.py's `generate_invoice`.

`visit_id` is optional (a medicine bill may be a standalone walk-in
sale); when supplied, `VisitService.get_visit` validates it exists
before anything is written, so an invalid id surfaces as a clean
`VisitNotFoundError` rather than a raw FK `IntegrityError`."""

from datetime import datetime
from decimal import Decimal
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.auth.models import User
from app.modules.pharmacy.exceptions import (
    MedicineBillNotFoundError,
    MedicineInactiveError,
    MedicineNotFoundError,
)
from app.modules.pharmacy.models import Medicine, MedicineBill, MedicineBillItem, MedicineCategory
from app.modules.pharmacy.repository import (
    MEDICINE_SORTABLE_COLUMNS,
    MedicineBillItemRepository,
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
        visit_service: VisitService,
        audit_repository: AuditLogRepository,
    ) -> None:
        self._session = session
        self._medicine_repo = medicine_repository
        self._bill_repo = medicine_bill_repository
        self._item_repo = medicine_bill_item_repository
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
    ) -> MedicineBill:
        """`items` is a list of `(medicine_id, quantity)` pairs, already
        validated non-empty by `CreateMedicineBillRequest`. Every
        medicine referenced must exist and be active — checked up front,
        before anything is written, so a bad line item never leaves a
        partially-built bill behind."""
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
            },
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

    async def list_bill_summaries_for_day(self, day: datetime) -> list[tuple[MedicineBill, int]]:
        """`(bill, item_count)` pairs for every medicine bill created on
        `day` — a single line-item count query for the whole day (see
        repository.py's `count_items_for_bills`), not one per bill."""
        bills = await self._bill_repo.list_for_day(day)
        counts = await self._item_repo.count_items_for_bills([bill.id for bill in bills])
        return [(bill, counts.get(bill.id, 0)) for bill in bills]
