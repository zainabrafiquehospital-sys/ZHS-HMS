"""SQLAlchemy models for the Pharmacy / Medicine Billing module.

Three entities:
- `Medicine` — the admin-managed price list. Deliberately carries no
  stock/quantity column: this build tracks price only, never inventory
  (out of scope — see the module's design notes). `is_active` is a soft
  "no longer sold" flag distinct from `deleted_at` (see below); the
  price list is read via `search`/`list_active` by Reception's
  autocomplete (active only) and `list_all` by the admin CRUD screen
  (active + inactive, so a deactivated medicine remains visible/
  re-activatable there).
- `MedicineBill` — one receptionist-built, multi-item medicine sale.
  `visit_id` is nullable (`ForeignKey("visit.id")`, a plain column, never
  a `relationship()` — see app/modules/billing/models.py's identical
  cross-module-reference convention): a medicine bill may be tied to a
  registered visit or stand alone as a walk-in sale. Who billed it is
  the inherited `created_by` (BaseEntity) — mirroring `Invoice`'s
  identical choice not to add a redundant actor column (see that
  model's module docstring); there is deliberately no separate
  `receptionist_id` column here either.
- `MedicineBillItem` — one line on a MedicineBill. Snapshots the
  medicine's name and unit price at billing time
  (`medicine_name_snapshot`/`unit_price_snapshot`) so a later edit to
  the price list (or deactivation) never rewrites the historical amount
  a patient was actually charged — the same "billed record is
  immutable, even if its source changes later" principle
  `InvoiceLineItem` already follows for `PendingBillingItem`.

Money fields use `Numeric`, never `Float` — see
app/modules/billing/models.py's module docstring for why."""

from decimal import Decimal
from enum import Enum as PyEnum
from uuid import UUID

from sqlalchemy import Boolean, CheckConstraint, Enum, ForeignKey, Index, Integer, Numeric, String
from sqlalchemy.orm import Mapped, mapped_column

from app.shared.base_entity import BaseEntity

_MONEY = Numeric(10, 2)


class MedicineCategory(PyEnum):
    SACHET = "sachet"
    DROPS = "drops"
    TABLET = "tablet"
    INJECTION = "injection"


class Medicine(BaseEntity):
    __tablename__ = "medicine"
    __table_args__ = (
        Index("ix_medicine_name", "name"),
        Index("ix_medicine_is_active", "is_active"),
        CheckConstraint("unit_price > 0", name="ck_medicine_unit_price_positive"),
    )

    name: Mapped[str] = mapped_column(String(150), nullable=False)
    category: Mapped[MedicineCategory] = mapped_column(
        Enum(
            MedicineCategory,
            name="medicine_category",
            native_enum=False,
            length=20,
            values_callable=lambda enum_cls: [member.value for member in enum_cls],
            create_constraint=True,
        ),
        nullable=False,
    )
    unit_price: Mapped[Decimal] = mapped_column(_MONEY, nullable=False)
    # "No longer sold" — distinct from `deleted_at` (a hard mistake/undo),
    # this is the normal, expected end state of a medicine the pharmacy
    # stops carrying. Deactivated medicines are excluded from the
    # receptionist-facing search/autocomplete but remain visible (and
    # re-activatable) on the admin management screen, and every bill
    # that already line-itemed one keeps its snapshot regardless.
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)


class MedicineBill(BaseEntity):
    __tablename__ = "medicine_bill"
    __table_args__ = (
        Index("ix_medicine_bill_visit_id", "visit_id"),
        CheckConstraint("total_amount >= 0", name="ck_medicine_bill_total_amount_non_negative"),
    )

    # Nullable: a medicine bill may stand alone as a walk-in sale with no
    # registered Visit — see this module's docstring.
    visit_id: Mapped[UUID | None] = mapped_column(ForeignKey("visit.id"))
    total_amount: Mapped[Decimal] = mapped_column(_MONEY, nullable=False)


class MedicineBillItem(BaseEntity):
    __tablename__ = "medicine_bill_item"
    __table_args__ = (
        Index("ix_medicine_bill_item_medicine_bill_id", "medicine_bill_id"),
        CheckConstraint("quantity > 0", name="ck_medicine_bill_item_quantity_positive"),
        CheckConstraint("line_total >= 0", name="ck_medicine_bill_item_line_total_non_negative"),
    )

    medicine_bill_id: Mapped[UUID] = mapped_column(ForeignKey("medicine_bill.id"), nullable=False)
    medicine_id: Mapped[UUID] = mapped_column(ForeignKey("medicine.id"), nullable=False)
    medicine_name_snapshot: Mapped[str] = mapped_column(String(150), nullable=False)
    # Snapshotted alongside name/price for the identical reason (see this
    # module's docstring) — the printed slip's category column must never
    # change retroactively if the medicine's own category is later edited.
    category_snapshot: Mapped[MedicineCategory] = mapped_column(
        Enum(
            MedicineCategory,
            name="medicine_bill_item_category_snapshot",
            native_enum=False,
            length=20,
            values_callable=lambda enum_cls: [member.value for member in enum_cls],
            create_constraint=True,
        ),
        nullable=False,
    )
    unit_price_snapshot: Mapped[Decimal] = mapped_column(_MONEY, nullable=False)
    quantity: Mapped[int] = mapped_column(Integer, nullable=False)
    line_total: Mapped[Decimal] = mapped_column(_MONEY, nullable=False)
