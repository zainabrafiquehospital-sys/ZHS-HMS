from decimal import Decimal

from app.modules.auth.models import User, UserStatus
from app.modules.auth.repository import UserRepository
from app.modules.consultation.models import ConsultationStatus
from app.modules.patients.models import PatientGender
from app.modules.queue.models import QueueDestination
from app.modules.visits.models import VisitStatus
from tests.conftest import TEST_PATIENT_NAME_PREFIX, make_test_email


async def _make_doctor(real_session, suffix: str) -> User:
    doctor = await UserRepository(real_session).add(
        User(
            email=make_test_email(f"vitals-doctor-{suffix}"),
            password_hash="hash",
            full_name="Vitals Test Doctor",
            status=UserStatus.ACTIVE,
        )
    )
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
        procedure="Consultation",
        amount=Decimal("1500.00"),
        vitals_required=vitals_required,
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
        temperature_celsius=36.8,
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
        temperature_celsius=None,
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
        temperature_celsius=36.5,
        weight_kg=60.0,
        height_cm=160.0,
        spo2_percent=99,
        notes=None,
    )

    records = await vitals_service.list_for_visit(visit.id)

    assert len(records) == 1
    assert records[0].systolic_bp == 110
