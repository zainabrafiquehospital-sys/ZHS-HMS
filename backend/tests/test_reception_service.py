from decimal import Decimal

import pytest
from uuid6 import uuid7

from app.modules.auth.models import LoginSession, User, UserStatus
from app.modules.auth.repository import LoginSessionRepository, UserRepository
from app.modules.consultation.constants import PERMISSION_CONSULTATION_START
from app.modules.patients.exceptions import PatientNotFoundError
from app.modules.patients.models import PatientGender
from app.modules.queue.models import QueueDestination, QueueEntryStatus
from app.modules.visits.models import VisitStatus
from tests.conftest import TEST_PATIENT_NAME_PREFIX, make_test_email


async def _make_actor(real_session, suffix: str) -> User:
    actor = await UserRepository(real_session).add(
        User(
            email=make_test_email(f"reception-actor-{suffix}"),
            password_hash="hash",
            full_name="Reception Test Actor",
            status=UserStatus.ACTIVE,
        )
    )
    await real_session.commit()
    return actor


def _new_patient_payload(suffix: str) -> dict:
    return {
        "full_name": f"{TEST_PATIENT_NAME_PREFIX}Reception{suffix}",
        "guardian_name": None,
        "gender": PatientGender.FEMALE,
        "age_years": 26,
        "phone_number": "03001234567",
        "cnic": None,
        "address": None,
    }


async def test_register_visit_with_new_patient_routes_to_vitals(real_session, reception_service):
    actor = await _make_actor(real_session, "new-patient-vitals")

    patient, visit, entry = await reception_service.register_visit(
        actor=actor,
        patient_id=None,
        new_patient=_new_patient_payload("A"),
        doctor_user_id=actor.id,
        procedure="Consultation",
        amount=Decimal("1500.00"),
        vitals_required=True,
    )

    assert patient.mr_number.startswith("MR-")
    assert visit.status == VisitStatus.WAITING_VITALS
    assert entry.destination == QueueDestination.VITALS
    assert entry.status == QueueEntryStatus.WAITING


async def test_register_visit_with_new_patient_routes_to_doctor(real_session, reception_service):
    actor = await _make_actor(real_session, "new-patient-doctor")

    patient, visit, entry = await reception_service.register_visit(
        actor=actor,
        patient_id=None,
        new_patient=_new_patient_payload("B"),
        doctor_user_id=actor.id,
        procedure="Follow-up",
        amount=Decimal("1500.00"),
        vitals_required=False,
    )

    assert visit.status == VisitStatus.WAITING_DOCTOR
    assert entry.destination == QueueDestination.DOCTOR


async def test_register_visit_with_existing_patient_reuses_same_patient(
    real_session, reception_service, patient_service
):
    actor = await _make_actor(real_session, "existing-patient")
    existing = await patient_service.register_patient(
        actor=actor,
        full_name=f"{TEST_PATIENT_NAME_PREFIX}ReceptionExisting",
        guardian_name=None,
        gender=PatientGender.FEMALE,
        age_years=40,
        phone_number="03001234567",
        cnic=None,
        address=None,
    )

    patient, visit, _entry = await reception_service.register_visit(
        actor=actor,
        patient_id=existing.id,
        new_patient=None,
        doctor_user_id=actor.id,
        procedure="Follow-up",
        amount=Decimal("1500.00"),
        vitals_required=False,
    )

    assert patient.id == existing.id
    assert visit.patient_id == existing.id


async def test_register_visit_with_unknown_patient_id_raises(real_session, reception_service):
    actor = await _make_actor(real_session, "unknown-patient")

    with pytest.raises(PatientNotFoundError):
        await reception_service.register_visit(
            actor=actor,
            patient_id=uuid7(),
            new_patient=None,
            doctor_user_id=actor.id,
            procedure="Consultation",
            amount=Decimal("1500.00"),
            vitals_required=False,
        )


async def test_register_visit_auto_assigns_least_busy_online_doctor(
    real_session, reception_service, grant_permission
):
    """Phase 6 fast-registration §4: doctor_user_id=None must
    auto-assign the online, least-busy eligible doctor rather than
    leaving the Visit unassigned when one genuinely exists."""
    receptionist = await _make_actor(real_session, "auto-assign-receptionist")
    doctor = await _make_actor(real_session, "auto-assign-doctor")
    await grant_permission(doctor, PERMISSION_CONSULTATION_START)
    await LoginSessionRepository(real_session).add(LoginSession(user_id=doctor.id))
    await real_session.commit()

    _patient, visit, _entry = await reception_service.register_visit(
        actor=receptionist,
        patient_id=None,
        new_patient=_new_patient_payload("AutoAssign"),
        doctor_user_id=None,
        procedure="Consultation",
        amount=Decimal("1500.00"),
        vitals_required=False,
    )

    assert visit.doctor_user_id == doctor.id


async def test_register_visit_proceeds_unassigned_when_no_doctor_online(
    real_session, reception_service
):
    """Phase 6 fast-registration §4: registration must never block on
    doctor availability — with no eligible online doctor, the Visit is
    created with `doctor_user_id=None` rather than raising."""
    receptionist = await _make_actor(real_session, "no-doctor-receptionist")

    _patient, visit, entry = await reception_service.register_visit(
        actor=receptionist,
        patient_id=None,
        new_patient=_new_patient_payload("NoDoctor"),
        doctor_user_id=None,
        procedure="Consultation",
        amount=Decimal("1500.00"),
        vitals_required=False,
    )

    assert visit.doctor_user_id is None
    assert visit.status == VisitStatus.WAITING_DOCTOR
    assert entry.destination == QueueDestination.DOCTOR


async def test_cancel_visit_closes_active_queue_entry_and_cancels_visit(
    real_session, reception_service, queue_service
):
    actor = await _make_actor(real_session, "cancel")
    _patient, visit, entry = await reception_service.register_visit(
        actor=actor,
        patient_id=None,
        new_patient=_new_patient_payload("C"),
        doctor_user_id=actor.id,
        procedure="Consultation",
        amount=Decimal("1500.00"),
        vitals_required=False,
    )

    cancelled = await reception_service.cancel_visit(
        actor=actor, visit_id=visit.id, reason="Patient left"
    )

    assert cancelled.status == VisitStatus.CANCELLED
    assert await queue_service.get_active_for_visit(visit.id) is None
