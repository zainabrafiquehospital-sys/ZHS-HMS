import pytest
from uuid6 import uuid7

from app.modules.auth.models import User, UserStatus
from app.modules.auth.repository import UserRepository
from app.modules.patients.exceptions import PatientCnicAlreadyExistsError, PatientNotFoundError
from app.modules.patients.models import PatientGender
from tests.conftest import TEST_PATIENT_NAME_PREFIX, make_test_email


async def _make_actor(real_session, suffix: str) -> User:
    actor = await UserRepository(real_session).add(
        User(
            email=make_test_email(f"patient-actor-{suffix}"),
            password_hash="hash",
            full_name="Patient Test Actor",
            status=UserStatus.ACTIVE,
        )
    )
    await real_session.commit()
    return actor


async def test_register_patient_generates_mr_number(real_session, patient_service):
    actor = await _make_actor(real_session, "register")

    patient = await patient_service.register_patient(
        actor=actor,
        full_name=f"{TEST_PATIENT_NAME_PREFIX}Register",
        guardian_name="Father Name",
        gender=PatientGender.FEMALE,
        age_years=30,
        phone_number="03001234567",
        cnic=None,
        address="Test Address",
    )

    assert patient.mr_number.startswith("MR-")
    assert patient.full_name == f"{TEST_PATIENT_NAME_PREFIX}Register"


async def test_register_patient_duplicate_cnic_raises(real_session, patient_service):
    actor = await _make_actor(real_session, "dup-cnic")
    cnic = f"{str(actor.id)[:15]}"
    await patient_service.register_patient(
        actor=actor,
        full_name=f"{TEST_PATIENT_NAME_PREFIX}CnicOne",
        guardian_name=None,
        gender=PatientGender.FEMALE,
        age_years=30,
        phone_number="03001234567",
        cnic=cnic,
        address=None,
    )

    with pytest.raises(PatientCnicAlreadyExistsError):
        await patient_service.register_patient(
            actor=actor,
            full_name=f"{TEST_PATIENT_NAME_PREFIX}CnicTwo",
            guardian_name=None,
            gender=PatientGender.FEMALE,
            age_years=28,
            phone_number="03007654321",
            cnic=cnic,
            address=None,
        )


async def test_get_patient_raises_not_found(patient_service):
    with pytest.raises(PatientNotFoundError):
        await patient_service.get_patient(uuid7())


async def test_update_patient_changes_phone_number(real_session, patient_service):
    actor = await _make_actor(real_session, "update")
    patient = await patient_service.register_patient(
        actor=actor,
        full_name=f"{TEST_PATIENT_NAME_PREFIX}Update",
        guardian_name=None,
        gender=PatientGender.FEMALE,
        age_years=40,
        phone_number="03001234567",
        cnic=None,
        address=None,
    )

    updated = await patient_service.update_patient(
        actor=actor, patient_id=patient.id, updates={"phone_number": "03009999999"}
    )

    assert updated.phone_number == "03009999999"
    assert updated.full_name == f"{TEST_PATIENT_NAME_PREFIX}Update"


async def test_update_patient_no_updates_returns_unchanged(real_session, patient_service):
    actor = await _make_actor(real_session, "no-op")
    patient = await patient_service.register_patient(
        actor=actor,
        full_name=f"{TEST_PATIENT_NAME_PREFIX}NoOp",
        guardian_name=None,
        gender=PatientGender.FEMALE,
        age_years=22,
        phone_number="03001234567",
        cnic=None,
        address=None,
    )

    result = await patient_service.update_patient(actor=actor, patient_id=patient.id, updates={})

    assert result.id == patient.id
