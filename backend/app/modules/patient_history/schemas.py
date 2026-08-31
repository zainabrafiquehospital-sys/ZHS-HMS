"""Response schema for the Patient History aggregation module.

`PatientHistoryOut` re-uses every other module's own existing response
shape wherever one already exists (VisitOut, VitalsRecordOut,
ConsultationOut, LabBillSummaryOut, MedicineBillSummaryOut) rather than
redefining the same fields a second time — the one exception is
invoices, where `InvoiceOut`'s own shape includes `line_items`/
`payments` (a per-invoice fetch this module deliberately doesn't do, to
stay a small, fixed number of batched queries regardless of how many
invoices a patient has — see service.py's own docstring), so
`PatientHistoryInvoiceOut` below is a narrower, bill-level-only
projection instead.

Every list field is `None` — not `[]` — when the requesting actor
lacks the other permission that section is gated on (see router.py's
own docstring for exactly which permission gates which section); `[]`
is reserved for "the actor has access, and this patient genuinely has
no records of this type." The frontend must tell these apart (a section
the actor cannot see at all vs. one they can see that is just empty)."""

from datetime import datetime
from decimal import Decimal
from uuid import UUID

from pydantic import BaseModel, ConfigDict

from app.modules.billing.models import Invoice, InvoiceStatus
from app.modules.consultation.schemas import ConsultationOut
from app.modules.lab.schemas import LabBillSummaryOut
from app.modules.patients.schemas import PatientOut
from app.modules.pharmacy.schemas import MedicineBillSummaryOut
from app.modules.visits.schemas import VisitOut
from app.modules.vitals.schemas import VitalsRecordOut


class PatientHistoryInvoiceOut(BaseModel):
    """A bill-level-only projection of Invoice — see this module's own
    docstring for why line items/payments aren't included here."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    visit_id: UUID
    status: InvoiceStatus
    total_amount: Decimal
    amount_paid: Decimal
    discount_amount: Decimal
    discount_reason: str | None
    paid_at: datetime | None
    created_at: datetime

    @classmethod
    def from_invoice(cls, invoice: Invoice) -> "PatientHistoryInvoiceOut":
        return cls(
            id=invoice.id,
            visit_id=invoice.visit_id,
            status=invoice.status,
            total_amount=invoice.total_amount,
            amount_paid=invoice.amount_paid,
            discount_amount=invoice.discount_amount,
            discount_reason=invoice.discount_reason,
            paid_at=invoice.paid_at,
            created_at=invoice.created_at,
        )


class PatientHistoryOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    patient: PatientOut
    # Gated on `visits:read` like every other section — every current
    # holder of `patients:history:read` (Receptionist/Vitals/Doctor/
    # admin) already holds it too (confirmed directly against the RBAC
    # tables, not assumed), so this is populated in practice for every
    # real caller today, but the check stays explicit rather than
    # hardcoded so a future role holding `patients:history:read` alone
    # can never see visit data it wasn't otherwise granted.
    visits: list[VisitOut] | None = None
    vitals: list[VitalsRecordOut] | None = None
    consultations: list[ConsultationOut] | None = None
    invoices: list[PatientHistoryInvoiceOut] | None = None
    lab_bills: list[LabBillSummaryOut] | None = None
    pharmacy_bills: list[MedicineBillSummaryOut] | None = None
