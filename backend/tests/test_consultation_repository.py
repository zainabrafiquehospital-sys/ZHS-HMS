from datetime import UTC, datetime
from decimal import Decimal

from uuid6 import uuid7

from app.modules.auth.models import User, UserStatus
from app.modules.auth.repository import UserRepository
from app.modules.consultation.models import Consultation, ConsultationStatus
from app.modules.consultation.repository import ConsultationRepository
from app.modules.patients.models import Patient, PatientGender
from app.modules.patients.repository import PatientRepository
from app.modules.visits.models import Visit
from app.modules.visits.repository import VisitRepository
from tests.conftest import make_test_email


async def _make_visit(db_session) -> Visit:
    patient = await PatientRepository(db_session).add(
        Patient(
            mr_number=f"MR-{uuid7().hex[-8:]}",
            full_name=f"Consultation Repo Patient {uuid7()}",
            gender=PatientGender.FEMALE,
            age_years=30,
            phone_number="03001234567",
        )
    )
    doctor = await UserRepository(db_session).add(
        User(
            email=make_test_email(f"consultation-repo-doctor-{uuid7().hex[-6:]}"),
            password_hash="hash",
            full_name="Consultation Repo Doctor",
            status=UserStatus.ACTIVE,
        )
    )
    return (
        await VisitRepository(db_session).add(
            Visit(
                patient_id=patient.id,
                doctor_user_id=doctor.id,
                queue_token=f"GYN-{uuid7().hex[-8:]}",
                procedure="Consultation",
                amount=Decimal("1500.00"),
                vitals_required=False,
            )
        ),
        doctor,
    )


async def test_get_active_for_visit_finds_in_progress(db_session):
    visit, doctor = await _make_visit(db_session)
    consultation = await ConsultationRepository(db_session).add(
        Consultation(
            visit_id=visit.id,
            doctor_user_id=doctor.id,
            status=ConsultationStatus.IN_PROGRESS,
        )
    )

    found = await ConsultationRepository(db_session).get_active_for_visit(visit.id)

    assert found is not None
    assert found.id == consultation.id


async def test_get_active_for_visit_finds_awaiting_vitals(db_session):
    visit, doctor = await _make_visit(db_session)
    consultation = await ConsultationRepository(db_session).add(
        Consultation(
            visit_id=visit.id,
            doctor_user_id=doctor.id,
            status=ConsultationStatus.AWAITING_VITALS,
        )
    )

    found = await ConsultationRepository(db_session).get_active_for_visit(visit.id)

    assert found is not None
    assert found.id == consultation.id


async def test_count_completed_by_doctor_only_counts_completed(db_session):
    """Asserts a delta, not an absolute count — same rationale as
    app/modules/visits' `test_count_by_status_reflects_new_visits`
    (the shared test database already holds committed consultations
    from other test suites)."""
    repo = ConsultationRepository(db_session)
    visit_a, doctor = await _make_visit(db_session)
    visit_b, _other_doctor = await _make_visit(db_session)
    baseline = await repo.count_completed_by_doctor()

    await repo.add(
        Consultation(
            visit_id=visit_a.id,
            doctor_user_id=doctor.id,
            status=ConsultationStatus.COMPLETED,
            completed_at=datetime.now(UTC),
        )
    )
    await repo.add(
        Consultation(
            visit_id=visit_b.id,
            doctor_user_id=doctor.id,
            status=ConsultationStatus.IN_PROGRESS,
        )
    )

    after = await repo.count_completed_by_doctor()

    assert after[doctor.id] - baseline.get(doctor.id, 0) == 1


async def test_get_active_for_visit_ignores_completed(db_session):
    visit, doctor = await _make_visit(db_session)
    await ConsultationRepository(db_session).add(
        Consultation(
            visit_id=visit.id,
            doctor_user_id=doctor.id,
            status=ConsultationStatus.COMPLETED,
            completed_at=datetime.now(UTC),
        )
    )

    found = await ConsultationRepository(db_session).get_active_for_visit(visit.id)

    assert found is None
