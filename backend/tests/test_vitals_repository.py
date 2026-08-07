from datetime import UTC, datetime
from decimal import Decimal

from uuid6 import uuid7

from app.modules.auth.models import User, UserStatus
from app.modules.auth.repository import UserRepository
from app.modules.patients.models import Patient, PatientGender
from app.modules.patients.repository import PatientRepository
from app.modules.visits.models import Visit
from app.modules.visits.repository import VisitRepository
from app.modules.vitals.models import VitalsRecord
from app.modules.vitals.repository import VitalsRecordRepository
from tests.conftest import make_test_email


async def _make_visit(db_session) -> Visit:
    patient = await PatientRepository(db_session).add(
        Patient(
            mr_number=f"MR-{uuid7().hex[-8:]}",
            full_name=f"Vitals Repo Patient {uuid7()}",
            gender=PatientGender.FEMALE,
            age_years=30,
            phone_number="03001234567",
        )
    )
    doctor = await UserRepository(db_session).add(
        User(
            email=make_test_email(f"vitals-repo-doctor-{uuid7().hex[-6:]}"),
            password_hash="hash",
            full_name="Vitals Repo Doctor",
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
            vitals_required=True,
        )
    )


async def test_list_for_visit_returns_chronological_order(db_session):
    visit = await _make_visit(db_session)
    repo = VitalsRecordRepository(db_session)
    first = await repo.add(VitalsRecord(visit_id=visit.id, systolic_bp=120, diastolic_bp=80))
    second = await repo.add(VitalsRecord(visit_id=visit.id, systolic_bp=118, diastolic_bp=76))

    records = await repo.list_for_visit(visit.id)

    assert [record.id for record in records] == [first.id, second.id]


async def test_list_for_visit_excludes_soft_deleted(db_session):
    visit = await _make_visit(db_session)
    repo = VitalsRecordRepository(db_session)
    record = await repo.add(VitalsRecord(visit_id=visit.id, systolic_bp=120, diastolic_bp=80))
    await repo.soft_delete(record, deleted_at=datetime.now(UTC))

    records = await repo.list_for_visit(visit.id)

    assert records == []
