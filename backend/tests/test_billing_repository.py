from datetime import UTC, datetime
from decimal import Decimal

from uuid6 import uuid7

from app.modules.auth.models import User, UserStatus
from app.modules.auth.repository import UserRepository
from app.modules.billing.models import (
    Invoice,
    InvoiceStatus,
    PendingBillingItem,
    PendingBillingItemStatus,
)
from app.modules.billing.repository import InvoiceRepository, PendingBillingItemRepository
from app.modules.patients.models import Patient, PatientGender
from app.modules.patients.repository import PatientRepository
from app.modules.visits.models import Visit
from app.modules.visits.repository import VisitRepository
from tests.conftest import make_test_email


async def _make_visit(db_session) -> Visit:
    patient = await PatientRepository(db_session).add(
        Patient(
            mr_number=f"MR-{uuid7().hex[-8:]}",
            full_name=f"Billing Repo Patient {uuid7()}",
            gender=PatientGender.FEMALE,
            age_years=30,
            phone_number="03001234567",
        )
    )
    doctor = await UserRepository(db_session).add(
        User(
            email=make_test_email(f"billing-repo-doctor-{uuid7().hex[-6:]}"),
            password_hash="hash",
            full_name="Billing Repo Doctor",
            status=UserStatus.ACTIVE,
        )
    )
    return await VisitRepository(db_session).add(
        Visit(
            patient_id=patient.id,
            doctor_user_id=doctor.id,
            queue_token=f"GYN-{uuid7().hex[-8:]}",
            procedure="Consultation",
            amount=Decimal("1500.00"),
            vitals_required=False,
        )
    )


async def test_pending_item_list_for_visit_filters_by_status(db_session):
    visit = await _make_visit(db_session)
    repo = PendingBillingItemRepository(db_session)
    pending = await repo.add(
        PendingBillingItem(visit_id=visit.id, description="Injection", amount=Decimal("500"))
    )
    approved = await repo.add(
        PendingBillingItem(
            visit_id=visit.id,
            description="Ultrasound",
            amount=Decimal("1500"),
            status=PendingBillingItemStatus.APPROVED,
        )
    )

    all_items = await repo.list_for_visit(visit.id)
    approved_only = await repo.list_for_visit(visit.id, status=PendingBillingItemStatus.APPROVED)

    assert {item.id for item in all_items} == {pending.id, approved.id}
    assert [item.id for item in approved_only] == [approved.id]


async def test_invoice_get_open_for_visit_finds_pending_payment(db_session):
    visit = await _make_visit(db_session)
    invoice = await InvoiceRepository(db_session).add(
        Invoice(
            visit_id=visit.id, status=InvoiceStatus.PENDING_PAYMENT, total_amount=Decimal("100")
        )
    )

    found = await InvoiceRepository(db_session).get_open_for_visit(visit.id)

    assert found is not None
    assert found.id == invoice.id


async def test_invoice_get_open_for_visit_ignores_paid(db_session):
    visit = await _make_visit(db_session)
    await InvoiceRepository(db_session).add(
        Invoice(
            visit_id=visit.id,
            status=InvoiceStatus.PAID,
            total_amount=Decimal("100"),
            amount_paid=Decimal("100"),
        )
    )

    found = await InvoiceRepository(db_session).get_open_for_visit(visit.id)

    assert found is None


async def test_get_today_summary_reflects_paid_invoice_today(db_session):
    """Asserts a delta, not an absolute count — see
    test_visits_repository.py's identical test for why."""
    repo = InvoiceRepository(db_session)
    baseline_revenue, baseline_paid_count, baseline_open_count = await repo.get_today_summary()
    visit = await _make_visit(db_session)
    await repo.add(
        Invoice(
            visit_id=visit.id,
            status=InvoiceStatus.PAID,
            total_amount=Decimal("750.00"),
            amount_paid=Decimal("750.00"),
            paid_at=datetime.now(UTC),
        )
    )
    await repo.add(
        Invoice(
            visit_id=visit.id, status=InvoiceStatus.PENDING_PAYMENT, total_amount=Decimal("200")
        )
    )

    revenue, paid_count, open_count = await repo.get_today_summary()

    assert revenue - baseline_revenue == Decimal("750.00")
    assert paid_count - baseline_paid_count == 1
    assert open_count - baseline_open_count == 1
