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
            email=make_test_email(f"dashboard-doctor-{suffix}"),
            password_hash="hash",
            full_name="Dashboard Test Doctor",
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
    _patient, visit, _entry = await reception_service.register_visit(
        actor=doctor,
        patient_id=None,
        new_patient={
            "full_name": f"{TEST_PATIENT_NAME_PREFIX}Dashboard{suffix}",
            "guardian_name": None,
            "gender": PatientGender.FEMALE,
            "age_years": 28,
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
    return visit


async def test_reception_summary_reflects_new_visit(
    real_session, reception_service, dashboard_service
):
    """Asserts a delta, not an absolute count — see
    test_visits_repository.py's identical test for why."""
    doctor = await _make_doctor(real_session, "reception-summary")
    (
        before,
        _q_before,
        _rev_before,
        _paid_before,
        _open_before,
    ) = await dashboard_service.get_reception_summary()
    await _register(reception_service, doctor, "A", vitals_required=False)

    (
        after,
        _q_after,
        _rev_after,
        _paid_after,
        _open_after,
    ) = await dashboard_service.get_reception_summary()

    before_count = before.get(VisitStatus.WAITING_DOCTOR, 0)
    after_count = after.get(VisitStatus.WAITING_DOCTOR, 0)
    assert after_count - before_count == 1


async def test_reception_summary_includes_todays_revenue(
    real_session, reception_service, consultation_service, billing_service, dashboard_service
):
    doctor = await _make_doctor(real_session, "reception-revenue")
    (
        _q1,
        _q2,
        revenue_before,
        paid_before,
        _open_before,
    ) = await dashboard_service.get_reception_summary()
    visit = await _register(reception_service, doctor, "B", vitals_required=False)
    consultation = await consultation_service.start_consultation(actor=doctor, visit_id=visit.id)
    await consultation_service.complete_consultation(
        actor=doctor, consultation_id=consultation.id, updates={}
    )
    invoice = await billing_service.generate_invoice(
        actor=doctor, visit_id=visit.id, base_description="Fee", base_amount=Decimal("800.00")
    )
    await billing_service.record_payment(
        actor=doctor,
        invoice_id=invoice.id,
        amount=Decimal("800.00"),
        payment_method=PaymentMethod.CASH,
    )

    (
        _q1,
        _q2,
        revenue_after,
        paid_after,
        _open_after,
    ) = await dashboard_service.get_reception_summary()

    assert revenue_after - revenue_before == Decimal("800.00")
    assert paid_after - paid_before == 1


async def test_doctor_summary_scoped_to_doctor(real_session, reception_service, dashboard_service):
    """A fresh test doctor has zero pre-existing visits, so this can
    assert an exact count rather than a delta."""
    doctor_a = await _make_doctor(real_session, "scoped-a")
    doctor_b = await _make_doctor(real_session, "scoped-b")
    await _register(reception_service, doctor_a, "C", vitals_required=False)
    await _register(reception_service, doctor_a, "D", vitals_required=False)
    await _register(reception_service, doctor_b, "E", vitals_required=False)

    waiting_a, in_consultation_a = await dashboard_service.get_doctor_summary(doctor_a.id)
    waiting_b, _in_consultation_b = await dashboard_service.get_doctor_summary(doctor_b.id)

    assert waiting_a == 2
    assert in_consultation_a == 0
    assert waiting_b == 1


async def test_vitals_summary_reflects_new_entry(
    real_session, reception_service, dashboard_service, queue_service
):
    doctor = await _make_doctor(real_session, "vitals-summary")
    before = await dashboard_service.get_vitals_summary()
    visit = await _register(reception_service, doctor, "F", vitals_required=True)

    after = await dashboard_service.get_vitals_summary()

    assert after - before == 1
    active_entry = await queue_service.get_active_for_visit(visit.id)
    assert active_entry.destination == QueueDestination.VITALS
