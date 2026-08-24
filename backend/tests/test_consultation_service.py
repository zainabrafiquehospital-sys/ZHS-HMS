from decimal import Decimal

import pytest
from uuid6 import uuid7

from app.core.exceptions import PermissionDeniedError
from app.modules.auth.models import Permission, Role, RolePermission, User, UserRole, UserStatus
from app.modules.auth.repository import (
    PermissionRepository,
    RolePermissionRepository,
    RoleRepository,
    UserRepository,
    UserRoleRepository,
)
from app.modules.auth.validators import derive_permission_group
from app.modules.consultation.constants import PERMISSION_CONSULTATION_START
from app.modules.consultation.exceptions import (
    ConsultationAlreadyActiveError,
    ConsultationNotFoundError,
    InvalidConsultationStatusTransitionError,
    NoActiveConsultationForVisitError,
)
from app.modules.consultation.models import ConsultationStatus
from app.modules.patients.models import PatientGender
from app.modules.queue.models import QueueDestination
from app.modules.visits.models import VisitStatus
from app.shared.payment_method import PaymentMethod
from tests.conftest import TEST_PATIENT_NAME_PREFIX, TEST_ROLE_PREFIX, make_test_email


async def _make_doctor(real_session, suffix: str) -> User:
    # 2026-08-24: grants `consultation:start` directly (not via the
    # `grant_permission` fixture, to avoid threading it through every
    # one of this file's own `_make_doctor` call sites) — an explicit
    # `doctor_user_id` at registration is now validated server-side
    # (ReceptionRepository.get_doctor_by_id) against exactly this
    # permission, so a "doctor" created without it is no longer a valid
    # one to register a Visit against or to drive through
    # start_consultation's own ownership checks.
    doctor = await UserRepository(real_session).add(
        User(
            email=make_test_email(f"consultation-doctor-{suffix}"),
            password_hash="hash",
            full_name="Consultation Test Doctor",
            status=UserStatus.ACTIVE,
        )
    )
    await real_session.commit()

    permission_repo = PermissionRepository(real_session)
    permission = await permission_repo.get_by_code(PERMISSION_CONSULTATION_START)
    if permission is None:
        permission = await permission_repo.add(
            Permission(
                code=PERMISSION_CONSULTATION_START,
                group=derive_permission_group(PERMISSION_CONSULTATION_START),
                display_name=PERMISSION_CONSULTATION_START,
            )
        )
    role = await RoleRepository(real_session).add(
        Role(name=f"{TEST_ROLE_PREFIX}{uuid7()}", is_active=True)
    )
    await RolePermissionRepository(real_session).add(
        RolePermission(role_id=role.id, permission_id=permission.id)
    )
    await UserRoleRepository(real_session).add(UserRole(user_id=doctor.id, role_id=role.id))
    await real_session.commit()
    return doctor


async def _make_visit_waiting_doctor(reception_service, doctor, suffix):
    """Goes through ReceptionService, not VisitService directly — a real
    Visit is never routable without a QueueEntry, and only Reception
    creates one (see app/modules/reception/service.py). Calling
    VisitService.register_visit alone would leave the Visit with no
    active queue entry, which is not a state a real Visit can ever be
    in — an earlier version of this helper did exactly that and caused
    every downstream `start_serving`/`complete_current` call in these
    tests to fail with `NoActiveQueueEntryError`."""
    _patient, visit, _entry = await reception_service.register_visit(
        actor=doctor,
        patient_id=None,
        new_patient={
            "full_name": f"{TEST_PATIENT_NAME_PREFIX}Consultation{suffix}",
            "guardian_name": None,
            "gender": PatientGender.FEMALE,
            "age_years": 27,
            "phone_number": "03001234567",
            "cnic": None,
            "address": None,
        },
        doctor_user_id=doctor.id,
        procedures=[(None, "Consultation", Decimal("1500.00"))],
        vitals_required=False,
        initial_payment_amount=Decimal("0.01"),
        initial_payment_method=PaymentMethod.CASH,
    )
    return visit


async def _make_unassigned_visit_waiting_doctor(reception_service, receptionist, suffix):
    """Same as `_make_visit_waiting_doctor`, but simulates Reception's
    fast-registration path finding no online doctor — `doctor_user_id`
    stays `None` until a doctor claims it via `start_consultation`."""
    _patient, visit, _entry = await reception_service.register_visit(
        actor=receptionist,
        patient_id=None,
        new_patient={
            "full_name": f"{TEST_PATIENT_NAME_PREFIX}ConsultationUnassigned{suffix}",
            "guardian_name": None,
            "gender": PatientGender.FEMALE,
            "age_years": 29,
            "phone_number": "03001234567",
            "cnic": None,
            "address": None,
        },
        doctor_user_id=None,
        procedures=[(None, "Consultation", Decimal("1500.00"))],
        vitals_required=False,
        initial_payment_amount=Decimal("0.01"),
        initial_payment_method=PaymentMethod.CASH,
    )
    return visit


async def test_start_consultation_claims_unassigned_visit(
    real_session, reception_service, visit_service, consultation_service
):
    """Phase 6 fast-registration: a Visit Reception couldn't
    auto-assign a doctor to (`doctor_user_id=None`) is claimed by
    whichever doctor starts its consultation first — both the
    Consultation and the Visit's own `doctor_user_id` end up pointing
    at that doctor."""
    receptionist = await _make_doctor(real_session, "claim-receptionist")
    doctor = await _make_doctor(real_session, "claim-doctor")
    visit = await _make_unassigned_visit_waiting_doctor(reception_service, receptionist, "A")
    assert visit.doctor_user_id is None

    consultation = await consultation_service.start_consultation(actor=doctor, visit_id=visit.id)

    assert consultation.doctor_user_id == doctor.id
    updated_visit = await visit_service.get_visit(visit.id)
    assert updated_visit.doctor_user_id == doctor.id
    assert updated_visit.status == VisitStatus.IN_CONSULTATION


async def test_start_consultation_success(
    real_session, reception_service, visit_service, consultation_service
):
    doctor = await _make_doctor(real_session, "start-success")
    visit = await _make_visit_waiting_doctor(reception_service, doctor, "A")

    consultation = await consultation_service.start_consultation(actor=doctor, visit_id=visit.id)

    assert consultation.status == ConsultationStatus.IN_PROGRESS
    assert consultation.doctor_user_id == doctor.id
    updated_visit = await visit_service.get_visit(visit.id)
    assert updated_visit.status == VisitStatus.IN_CONSULTATION


async def test_start_consultation_wrong_doctor_forbidden(
    real_session, reception_service, consultation_service
):
    doctor = await _make_doctor(real_session, "wrong-doctor-owner")
    other_doctor = await _make_doctor(real_session, "wrong-doctor-actor")
    visit = await _make_visit_waiting_doctor(reception_service, doctor, "B")

    with pytest.raises(PermissionDeniedError):
        await consultation_service.start_consultation(actor=other_doctor, visit_id=visit.id)


async def test_start_consultation_twice_raises_already_active(
    real_session, reception_service, consultation_service
):
    doctor = await _make_doctor(real_session, "start-twice")
    visit = await _make_visit_waiting_doctor(reception_service, doctor, "C")
    await consultation_service.start_consultation(actor=doctor, visit_id=visit.id)

    with pytest.raises(ConsultationAlreadyActiveError):
        await consultation_service.start_consultation(actor=doctor, visit_id=visit.id)


async def test_send_to_vitals_and_resume_full_cycle(
    real_session, reception_service, visit_service, queue_service, consultation_service
):
    doctor = await _make_doctor(real_session, "vitals-cycle")
    visit = await _make_visit_waiting_doctor(reception_service, doctor, "D")
    consultation = await consultation_service.start_consultation(actor=doctor, visit_id=visit.id)

    sent = await consultation_service.send_to_vitals(
        actor=doctor, consultation_id=consultation.id, reason="BP check"
    )
    assert sent.status == ConsultationStatus.AWAITING_VITALS
    # §4.1: the Visit itself never leaves IN_CONSULTATION for a
    # doctor-initiated detour — only Queue routing changes.
    visit_during_detour = await visit_service.get_visit(visit.id)
    assert visit_during_detour.status == VisitStatus.IN_CONSULTATION
    active_entry = await queue_service.get_active_for_visit(visit.id)
    assert active_entry.destination == QueueDestination.VITALS

    # Vitals module (not yet built) would now call route_to(..., DOCTOR)
    # and resume_from_vitals — simulate both here.
    await queue_service.route_to(
        actor=doctor, visit_id=visit.id, destination=QueueDestination.DOCTOR
    )
    resumed = await consultation_service.resume_from_vitals(actor=doctor, visit_id=visit.id)
    assert resumed.status == ConsultationStatus.IN_PROGRESS


async def test_resume_from_vitals_without_active_consultation_raises(
    real_session, reception_service, consultation_service
):
    doctor = await _make_doctor(real_session, "resume-no-active")
    visit = await _make_visit_waiting_doctor(reception_service, doctor, "E")

    with pytest.raises(NoActiveConsultationForVisitError):
        await consultation_service.resume_from_vitals(actor=doctor, visit_id=visit.id)


async def test_complete_consultation_success(
    real_session, reception_service, visit_service, queue_service, consultation_service
):
    doctor = await _make_doctor(real_session, "complete-success")
    visit = await _make_visit_waiting_doctor(reception_service, doctor, "F")
    consultation = await consultation_service.start_consultation(actor=doctor, visit_id=visit.id)

    completed = await consultation_service.complete_consultation(
        actor=doctor,
        consultation_id=consultation.id,
        updates={"diagnosis": "Routine checkup", "prescription": "None"},
    )

    assert completed.status == ConsultationStatus.COMPLETED
    assert completed.completed_at is not None
    assert completed.diagnosis == "Routine checkup"
    updated_visit = await visit_service.get_visit(visit.id)
    assert updated_visit.status == VisitStatus.WAITING_BILLING
    assert await queue_service.get_active_for_visit(visit.id) is None


async def test_complete_consultation_while_awaiting_vitals_raises(
    real_session, reception_service, consultation_service
):
    doctor = await _make_doctor(real_session, "complete-awaiting-vitals")
    visit = await _make_visit_waiting_doctor(reception_service, doctor, "G")
    consultation = await consultation_service.start_consultation(actor=doctor, visit_id=visit.id)
    await consultation_service.send_to_vitals(
        actor=doctor, consultation_id=consultation.id, reason=None
    )

    with pytest.raises(InvalidConsultationStatusTransitionError):
        await consultation_service.complete_consultation(
            actor=doctor, consultation_id=consultation.id, updates={}
        )


async def test_get_consultation_raises_not_found(consultation_service):
    with pytest.raises(ConsultationNotFoundError):
        await consultation_service.get_consultation(uuid7())
