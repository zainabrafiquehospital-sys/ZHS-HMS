from decimal import Decimal

from uuid6 import uuid7

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
from app.modules.consultation.models import ConsultationStatus
from app.modules.patients.models import PatientGender
from app.modules.queue.models import QueueDestination
from app.modules.visits.models import VisitStatus
from app.modules.vitals.models import TemperatureUnit
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
            email=make_test_email(f"vitals-doctor-{suffix}"),
            password_hash="hash",
            full_name="Vitals Test Doctor",
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


async def _register(reception_service, doctor, suffix, vitals_required):
    _patient, visit, entry = await reception_service.register_visit(
        actor=doctor,
        patient_id=None,
        new_patient={
            "full_name": f"{TEST_PATIENT_NAME_PREFIX}Vitals{suffix}",
            "guardian_name": None,
            "gender": PatientGender.FEMALE,
            "age_years": 29,
            "phone_number": "03001234567",
            "cnic": None,
            "address": None,
        },
        doctor_user_id=doctor.id,
        procedures=[(None, "Consultation", Decimal("1500.00"))],
        vitals_required=vitals_required,
        initial_payment_amount=Decimal("0.01"),
        initial_payment_method=PaymentMethod.CASH,
    )
    return visit, entry


async def test_record_vitals_workflow_a_intake_routes_to_doctor(
    real_session, reception_service, visit_service, queue_service, vitals_service
):
    """Reception routed straight to Vitals (no consultation exists yet)
    — completing vitals must move the Visit itself WAITING_VITALS ->
    WAITING_DOCTOR and route the queue to DOCTOR."""
    doctor = await _make_doctor(real_session, "workflow-a")
    visit, _entry = await _register(reception_service, doctor, "A", vitals_required=True)
    assert visit.status == VisitStatus.WAITING_VITALS

    record = await vitals_service.record_vitals(
        actor=doctor,
        visit_id=visit.id,
        systolic_bp=120,
        diastolic_bp=80,
        pulse_rate=72,
        temperature=98.2,
        weight_kg=65.0,
        height_cm=165.0,
        spo2_percent=98,
        notes="Normal",
    )

    assert record.consultation_id is None
    updated_visit = await visit_service.get_visit(visit.id)
    assert updated_visit.status == VisitStatus.WAITING_DOCTOR
    active_entry = await queue_service.get_active_for_visit(visit.id)
    assert active_entry.destination == QueueDestination.DOCTOR


async def test_record_vitals_doctor_detour_resumes_consultation(
    real_session,
    reception_service,
    visit_service,
    queue_service,
    consultation_service,
    vitals_service,
):
    """A doctor-requested mid-consultation detour (§5.2) — completing
    vitals must resume the Consultation and route the queue back to
    DOCTOR, while the Visit itself stays IN_CONSULTATION throughout
    (§4.1) — record_vitals must NOT call VisitService here."""
    doctor = await _make_doctor(real_session, "detour")
    visit, _entry = await _register(reception_service, doctor, "B", vitals_required=False)
    consultation = await consultation_service.start_consultation(actor=doctor, visit_id=visit.id)
    await consultation_service.send_to_vitals(
        actor=doctor, consultation_id=consultation.id, reason="Recheck BP"
    )

    record = await vitals_service.record_vitals(
        actor=doctor,
        visit_id=visit.id,
        systolic_bp=130,
        diastolic_bp=85,
        pulse_rate=None,
        temperature=None,
        weight_kg=None,
        height_cm=None,
        spo2_percent=None,
        notes="Slightly elevated",
    )

    assert record.consultation_id == consultation.id
    # Visit never left IN_CONSULTATION for the detour.
    updated_visit = await visit_service.get_visit(visit.id)
    assert updated_visit.status == VisitStatus.IN_CONSULTATION
    resumed_consultation = await consultation_service.get_consultation(consultation.id)
    assert resumed_consultation.status == ConsultationStatus.IN_PROGRESS
    active_entry = await queue_service.get_active_for_visit(visit.id)
    assert active_entry.destination == QueueDestination.DOCTOR


async def test_list_for_visit_returns_recorded_vitals(
    real_session, reception_service, vitals_service
):
    doctor = await _make_doctor(real_session, "list")
    visit, _entry = await _register(reception_service, doctor, "C", vitals_required=True)
    await vitals_service.record_vitals(
        actor=doctor,
        visit_id=visit.id,
        systolic_bp=110,
        diastolic_bp=70,
        pulse_rate=68,
        temperature=97.7,
        weight_kg=60.0,
        height_cm=160.0,
        spo2_percent=99,
        notes=None,
    )

    records = await vitals_service.list_for_visit(visit.id)

    assert len(records) == 1
    assert records[0].systolic_bp == 110


async def test_record_vitals_stamps_temperature_unit_fahrenheit(
    real_session, reception_service, vitals_service
):
    """2026-08-28 change, going-forward only (see VitalsService.
    record_vitals's own docstring): every new record is unambiguously
    Fahrenheit — `temperature_unit` is always server-stamped, never a
    caller-suppliable value at all."""
    doctor = await _make_doctor(real_session, "temp-unit-stamp")
    visit, _entry = await _register(reception_service, doctor, "TempUnit", vitals_required=True)

    record = await vitals_service.record_vitals(
        actor=doctor,
        visit_id=visit.id,
        systolic_bp=None,
        diastolic_bp=None,
        pulse_rate=None,
        temperature=100.4,
        weight_kg=None,
        height_cm=None,
        spo2_percent=None,
        notes=None,
    )

    assert record.temperature == 100.4
    assert record.temperature_unit == TemperatureUnit.FAHRENHEIT


async def test_list_for_patient_returns_records_across_all_visits_newest_first(
    real_session, reception_service, vitals_service
):
    """"Show Details" cross-visit vitals history (2026-08-28 addition)
    — a patient with two separate visits, each with its own vitals
    record, must see both records back from `list_for_patient`, newest
    first, unlike `get_latest_for_patient` which only ever returns one."""
    doctor = await _make_doctor(real_session, "history")
    first_visit, _entry = await _register(reception_service, doctor, "History", vitals_required=True)
    first_record = await vitals_service.record_vitals(
        actor=doctor,
        visit_id=first_visit.id,
        systolic_bp=100,
        diastolic_bp=60,
        pulse_rate=60,
        temperature=97.0,
        weight_kg=None,
        height_cm=None,
        spo2_percent=None,
        notes="First visit",
    )

    second_patient, second_visit, _second_entry = await reception_service.register_visit(
        actor=doctor,
        patient_id=first_visit.patient_id,
        new_patient=None,
        doctor_user_id=doctor.id,
        procedures=[(None, "Follow-up", Decimal("500.00"))],
        vitals_required=True,
        initial_payment_amount=Decimal("0.01"),
        initial_payment_method=PaymentMethod.CASH,
    )
    second_record = await vitals_service.record_vitals(
        actor=doctor,
        visit_id=second_visit.id,
        systolic_bp=140,
        diastolic_bp=90,
        pulse_rate=88,
        temperature=101.0,
        weight_kg=None,
        height_cm=None,
        spo2_percent=None,
        notes="Second visit",
    )

    records = await vitals_service.list_for_patient(patient_id=second_patient.id)

    assert [record.id for record in records] == [second_record.id, first_record.id]


async def test_list_for_patient_returns_empty_list_when_none_recorded(
    real_session, reception_service, vitals_service
):
    doctor = await _make_doctor(real_session, "history-empty")
    visit, _entry = await _register(reception_service, doctor, "HistoryEmpty", vitals_required=False)

    records = await vitals_service.list_for_patient(patient_id=visit.patient_id)

    assert records == []


async def test_record_vitals_no_temperature_leaves_unit_null(
    real_session, reception_service, vitals_service
):
    """The CHECK constraint (`ck_vitals_record_temperature_unit_paired`)
    requires `temperature`/`temperature_unit` to be NULL together — a
    reading that wasn't taken must never get a fabricated unit."""
    doctor = await _make_doctor(real_session, "temp-unit-null")
    visit, _entry = await _register(reception_service, doctor, "TempUnitNull", vitals_required=True)

    record = await vitals_service.record_vitals(
        actor=doctor,
        visit_id=visit.id,
        systolic_bp=118,
        diastolic_bp=76,
        pulse_rate=70,
        temperature=None,
        weight_kg=None,
        height_cm=None,
        spo2_percent=None,
        notes=None,
    )

    assert record.temperature is None
    assert record.temperature_unit is None
