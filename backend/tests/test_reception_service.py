from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest
from uuid6 import uuid7

from app.modules.auth.models import LoginSession, User, UserStatus
from app.modules.auth.repository import LoginSessionRepository, UserRepository
from app.modules.consultation.constants import PERMISSION_CONSULTATION_START
from app.modules.patients.exceptions import PatientNotFoundError
from app.modules.patients.models import PatientGender
from app.modules.pharmacy.models import MedicineCategory
from app.modules.queue.models import QueueDestination, QueueEntryStatus
from app.modules.reception.exceptions import VisitHasSettledInvoiceError
from app.modules.visits.exceptions import VisitNotFoundError
from app.modules.visits.models import Visit, VisitStatus
from app.modules.visits.repository import VisitRepository
from app.shared.audit.models import AuditEntry
from app.shared.audit.repository import AuditLogRepository
from app.shared.payment_method import PaymentMethod
from tests.conftest import TEST_MEDICINE_NAME_PREFIX, TEST_PATIENT_NAME_PREFIX, make_test_email


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


# ---------------------------------------------------------------------
# Admin data correction (2026-08-19 addition) — reception:update_visit /
# reception:delete_visit. RBAC (admin-only, receptionist gets 403) is
# proven at the HTTP layer in tests/test_reception_endpoints.py — these
# are the underlying business-rule tests: ownership doesn't matter (any
# actor may act on any visit at this layer, exactly like every other
# service method here), the invoice-paid safety block, and the queue/
# soft-delete mechanics.
# ---------------------------------------------------------------------


async def _make_visit_waiting_billing(reception_service, consultation_service, doctor, suffix):
    """Same shape as tests/test_billing_service.py's identical helper —
    duplicated locally per this codebase's existing convention of small
    per-file test helpers rather than a shared cross-file import."""
    _patient, visit, _entry = await reception_service.register_visit(
        actor=doctor,
        patient_id=None,
        new_patient=_new_patient_payload(suffix),
        doctor_user_id=doctor.id,
        procedure="Consultation",
        amount=Decimal("1500.00"),
        vitals_required=False,
    )
    consultation = await consultation_service.start_consultation(actor=doctor, visit_id=visit.id)
    await consultation_service.complete_consultation(
        actor=doctor, consultation_id=consultation.id, updates={}
    )
    return visit


async def test_admin_update_visit_updates_patient_and_visit_fields(
    real_session, reception_service, patient_service
):
    admin = await _make_actor(real_session, "update-admin")
    _patient, visit, _entry = await reception_service.register_visit(
        actor=admin,
        patient_id=None,
        new_patient=_new_patient_payload("UpdateTarget"),
        doctor_user_id=admin.id,
        procedure="Consultation",
        amount=Decimal("1500.00"),
        vitals_required=False,
    )

    updated_patient, updated_visit = await reception_service.admin_update_visit(
        actor=admin,
        visit_id=visit.id,
        updates={
            "full_name": f"{TEST_PATIENT_NAME_PREFIX}CorrectedName",
            "procedure": "Ultrasound",
            "amount": Decimal("2500.00"),
        },
    )

    assert updated_patient.full_name == f"{TEST_PATIENT_NAME_PREFIX}CorrectedName"
    assert updated_visit.procedure == "Ultrasound"
    assert updated_visit.amount == Decimal("2500.00")
    # Untouched fields survive a partial update unchanged.
    assert updated_patient.phone_number == "03001234567"


async def test_admin_update_visit_with_no_updates_is_a_noop(real_session, reception_service):
    admin = await _make_actor(real_session, "update-noop-admin")
    _patient, visit, _entry = await reception_service.register_visit(
        actor=admin,
        patient_id=None,
        new_patient=_new_patient_payload("UpdateNoop"),
        doctor_user_id=admin.id,
        procedure="Consultation",
        amount=Decimal("1500.00"),
        vitals_required=False,
    )

    patient, updated_visit = await reception_service.admin_update_visit(
        actor=admin, visit_id=visit.id, updates={}
    )

    assert updated_visit.procedure == "Consultation"
    assert updated_visit.amount == Decimal("1500.00")


async def test_admin_delete_visit_soft_deletes_and_closes_active_queue_entry(
    real_session, reception_service, visit_service, queue_service
):
    admin = await _make_actor(real_session, "delete-admin")
    _patient, visit, _entry = await reception_service.register_visit(
        actor=admin,
        patient_id=None,
        new_patient=_new_patient_payload("DeleteTarget"),
        doctor_user_id=admin.id,
        procedure="Consultation",
        amount=Decimal("1500.00"),
        vitals_required=False,
    )
    assert await queue_service.get_active_for_visit(visit.id) is not None

    await reception_service.admin_delete_visit(actor=admin, visit_id=visit.id)

    with pytest.raises(VisitNotFoundError):
        await visit_service.get_visit(visit.id)
    assert await queue_service.get_active_for_visit(visit.id) is None


async def test_admin_delete_visit_blocked_when_invoice_paid(
    real_session, reception_service, consultation_service, billing_service
):
    admin = await _make_actor(real_session, "delete-blocked-admin")
    visit = await _make_visit_waiting_billing(
        reception_service, consultation_service, admin, "DeleteBlocked"
    )
    invoice = await billing_service.generate_invoice(
        actor=admin,
        visit_id=visit.id,
        base_description="Consultation",
        base_amount=Decimal("1500.00"),
    )
    await billing_service.record_payment(
        actor=admin,
        invoice_id=invoice.id,
        amount=Decimal("1500.00"),
        payment_method=PaymentMethod.CASH,
    )

    with pytest.raises(VisitHasSettledInvoiceError):
        await reception_service.admin_delete_visit(actor=admin, visit_id=visit.id)


async def test_admin_delete_visit_blocked_when_invoice_partially_paid(
    real_session, reception_service, consultation_service, billing_service
):
    admin = await _make_actor(real_session, "delete-partial-admin")
    visit = await _make_visit_waiting_billing(
        reception_service, consultation_service, admin, "DeletePartial"
    )
    invoice = await billing_service.generate_invoice(
        actor=admin,
        visit_id=visit.id,
        base_description="Consultation",
        base_amount=Decimal("1500.00"),
    )
    await billing_service.record_payment(
        actor=admin,
        invoice_id=invoice.id,
        amount=Decimal("500.00"),
        payment_method=PaymentMethod.CASH,
    )

    with pytest.raises(VisitHasSettledInvoiceError):
        await reception_service.admin_delete_visit(actor=admin, visit_id=visit.id)


async def test_admin_delete_visit_allowed_when_invoice_unpaid(
    real_session, reception_service, consultation_service, billing_service, visit_service
):
    """An invoice with nothing yet collected against it (PENDING_PAYMENT)
    is real paperwork, but no money has changed hands — deliberately not
    a block (see ReceptionService.admin_delete_visit's own docstring)."""
    admin = await _make_actor(real_session, "delete-unpaid-admin")
    visit = await _make_visit_waiting_billing(
        reception_service, consultation_service, admin, "DeleteUnpaid"
    )
    await billing_service.generate_invoice(
        actor=admin,
        visit_id=visit.id,
        base_description="Consultation",
        base_amount=Decimal("1500.00"),
    )

    await reception_service.admin_delete_visit(actor=admin, visit_id=visit.id)

    with pytest.raises(VisitNotFoundError):
        await visit_service.get_visit(visit.id)


# ---------------------------------------------------------------------
# "My Revenue" (2026-08-19 addition) — own-only scoping, medicine bills
# included, and the audit-log-based clear mechanism (see
# ReceptionService.get_own_revenue's own docstring for the full design).
# ---------------------------------------------------------------------


async def _make_medicine(pharmacy_service, actor, suffix: str, price: str = "50.00"):
    return await pharmacy_service.create_medicine(
        actor=actor,
        name=f"{TEST_MEDICINE_NAME_PREFIX}Reception{suffix}",
        category=MedicineCategory.TABLET,
        unit_price=Decimal(price),
    )


async def test_get_own_revenue_is_scoped_to_the_caller_only(
    real_session, reception_service, pharmacy_service
):
    """The core requirement: receptionist A's own-revenue figure must
    never include receptionist B's visits/medicine bills, even though
    both are registered in the same database at the same time."""
    receptionist_a = await _make_actor(real_session, "revenue-a")
    receptionist_b = await _make_actor(real_session, "revenue-b")

    await reception_service.register_visit(
        actor=receptionist_a,
        patient_id=None,
        new_patient=_new_patient_payload("RevenueOwnA"),
        doctor_user_id=receptionist_a.id,
        procedure="Consultation",
        amount=Decimal("1500.00"),
        vitals_required=False,
    )
    await reception_service.register_visit(
        actor=receptionist_b,
        patient_id=None,
        new_patient=_new_patient_payload("RevenueOwnB"),
        doctor_user_id=receptionist_b.id,
        procedure="Consultation",
        amount=Decimal("9999.00"),
        vitals_required=False,
    )

    visits_count, visits_revenue, _med_count, _med_revenue, window_since = (
        await reception_service.get_own_revenue(actor=receptionist_a)
    )

    assert visits_count == 1
    assert visits_revenue == Decimal("1500.00")
    # Never cleared, so the window falls back to the 24h auto-window
    # alone — a real, recent timestamp, never None/all-time (2026-08-19
    # fix). Sanity-check it's roughly "now - 24h", not some other value.
    assert datetime.now(UTC) - timedelta(hours=24, minutes=1) < window_since < datetime.now(UTC)


async def test_get_own_revenue_includes_medicine_bills_in_breakdown(
    real_session, reception_service, pharmacy_service
):
    receptionist = await _make_actor(real_session, "revenue-medicine")
    medicine = await _make_medicine(pharmacy_service, receptionist, "Breakdown", price="100.00")

    await reception_service.register_visit(
        actor=receptionist,
        patient_id=None,
        new_patient=_new_patient_payload("RevenueMedVisit"),
        doctor_user_id=receptionist.id,
        procedure="Consultation",
        amount=Decimal("1500.00"),
        vitals_required=False,
    )
    await pharmacy_service.create_bill(
        actor=receptionist, visit_id=None, items=[(medicine.id, 2)]
    )

    visits_count, visits_revenue, med_count, med_revenue, _cleared_at = (
        await reception_service.get_own_revenue(actor=receptionist)
    )

    assert visits_count == 1
    assert visits_revenue == Decimal("1500.00")
    assert med_count == 1
    assert med_revenue == Decimal("200.00")  # 2 x 100.00


async def test_clear_own_revenue_resets_display_but_leaves_data_intact(
    real_session, reception_service, visit_service
):
    receptionist = await _make_actor(real_session, "revenue-clear")
    _patient, visit, _entry = await reception_service.register_visit(
        actor=receptionist,
        patient_id=None,
        new_patient=_new_patient_payload("RevenueClear"),
        doctor_user_id=receptionist.id,
        procedure="Consultation",
        amount=Decimal("1500.00"),
        vitals_required=False,
    )

    before_count, before_revenue, _mc, _mr, _ca = await reception_service.get_own_revenue(
        actor=receptionist
    )
    assert before_count == 1
    assert before_revenue == Decimal("1500.00")

    cleared_at = await reception_service.clear_own_revenue(actor=receptionist)
    assert cleared_at is not None

    after_count, after_revenue, _mc2, _mr2, reported_cleared_at = (
        await reception_service.get_own_revenue(actor=receptionist)
    )
    assert after_count == 0
    assert after_revenue == Decimal("0.00")
    assert reported_cleared_at is not None

    # The non-negotiable part: the underlying Visit row is completely
    # untouched — same id, same amount, not soft-deleted, still fully
    # visible — "clearing" only narrowed what counts toward this one
    # receptionist's own forward-looking display.
    still_there = await visit_service.get_visit(visit.id)
    assert still_there.id == visit.id
    assert still_there.amount == Decimal("1500.00")
    assert still_there.deleted_at is None


async def test_clear_own_revenue_does_not_affect_admins_alltime_view(
    real_session, reception_service, visit_service
):
    """Admin's own all-time aggregate (Employee Accounts & Stats, and
    Admin Overview's revenue-by-receptionist chart) must keep showing
    the true, complete history regardless of any receptionist's own
    clear — this is what makes "clear" a display-scope operation, not a
    data-deletion one."""
    receptionist = await _make_actor(real_session, "revenue-admin-view")
    await reception_service.register_visit(
        actor=receptionist,
        patient_id=None,
        new_patient=_new_patient_payload("RevenueAdminView"),
        doctor_user_id=receptionist.id,
        procedure="Consultation",
        amount=Decimal("1500.00"),
        vitals_required=False,
    )

    await reception_service.clear_own_revenue(actor=receptionist)

    all_time = await visit_service.count_and_revenue_by_creator()
    assert all_time[receptionist.id] == (1, Decimal("1500.00"))


async def test_clear_own_revenue_only_affects_the_caller(real_session, reception_service):
    """Receptionist B clearing her own revenue must never touch
    receptionist A's — each has an independent reset point."""
    receptionist_a = await _make_actor(real_session, "revenue-independent-a")
    receptionist_b = await _make_actor(real_session, "revenue-independent-b")
    await reception_service.register_visit(
        actor=receptionist_a,
        patient_id=None,
        new_patient=_new_patient_payload("RevenueIndepA"),
        doctor_user_id=receptionist_a.id,
        procedure="Consultation",
        amount=Decimal("1500.00"),
        vitals_required=False,
    )

    await reception_service.clear_own_revenue(actor=receptionist_b)

    a_count, a_revenue, _mc, _mr, a_window_since = await reception_service.get_own_revenue(
        actor=receptionist_a
    )
    assert a_count == 1
    assert a_revenue == Decimal("1500.00")
    # A never cleared, so her window is still just the 24h auto-window —
    # unaffected by B's own clear (2026-08-19 fix).
    assert datetime.now(UTC) - timedelta(hours=24, minutes=1) < a_window_since < datetime.now(UTC)


# ---------------------------------------------------------------------
# 24h auto-window fix (2026-08-19) — "My Revenue" no longer shows an
# ever-growing all-time cumulative total for receptionists who never
# press "Clear Revenue" day to day (see ReceptionService.get_own_revenue's
# own docstring for the full `since = max(last_manual_clear, now - 24h)`
# mechanism). Backdated rows are constructed directly with an explicit
# `created_at` at insert time — the same pattern
# test_visits_repository.py already uses — rather than mutating a row's
# `created_at` after the fact: this codebase has a documented
# MissingGreenlet hazard reading a server-generated timestamp column
# back after add()/flush() without an explicit refresh (see
# ReceptionService.clear_own_revenue's own docstring for why it returns
# a Python-computed `now` instead of reading `entry.created_at` back),
# and no code path in this app can otherwise produce a >24h-old row for
# a still-logged-in actor.
# ---------------------------------------------------------------------


def _unique_token() -> str:
    return f"GYN-{uuid7().hex[-8:]}"


async def _make_backdated_visit(
    real_session, *, patient_id, creator_id, amount: Decimal, hours_ago: float
) -> Visit:
    visit = Visit(
        patient_id=patient_id,
        doctor_user_id=creator_id,
        queue_token=_unique_token(),
        procedure="Consultation",
        amount=amount,
        vitals_required=False,
        status=VisitStatus.REGISTERED,
        created_by=creator_id,
        created_at=datetime.now(UTC) - timedelta(hours=hours_ago),
    )
    return await VisitRepository(real_session).add(visit)


async def _make_backdated_clear_marker(real_session, *, receptionist_id, hours_ago: float) -> AuditEntry:
    entry = AuditEntry(
        module="reception",
        action="reception.revenue_cleared",
        entity_type="user",
        entity_id=receptionist_id,
        actor_user_id=receptionist_id,
        created_at=datetime.now(UTC) - timedelta(hours=hours_ago),
    )
    return await AuditLogRepository(real_session).add(entry)


async def test_get_own_revenue_excludes_visits_older_than_24h_even_without_manual_clear(
    real_session, reception_service
):
    """The core bug fix: a receptionist who has never pressed "Clear
    Revenue" must still only see roughly the last 24h, never a
    cumulative all-time total."""
    receptionist = await _make_actor(real_session, "revenue-24h-old")
    patient, _visit, _entry = await reception_service.register_visit(
        actor=receptionist,
        patient_id=None,
        new_patient=_new_patient_payload("Revenue24hOld"),
        doctor_user_id=receptionist.id,
        procedure="Consultation",
        amount=Decimal("100.00"),
        vitals_required=False,
    )
    old_visit = await _make_backdated_visit(
        real_session,
        patient_id=patient.id,
        creator_id=receptionist.id,
        amount=Decimal("5000.00"),
        hours_ago=25,
    )
    recent_visit = await _make_backdated_visit(
        real_session,
        patient_id=patient.id,
        creator_id=receptionist.id,
        amount=Decimal("750.00"),
        hours_ago=1,
    )

    visits_count, visits_revenue, _mc, _mr, window_since = await reception_service.get_own_revenue(
        actor=receptionist
    )

    # 100.00 (fresh, from register_visit) + 750.00 (backdated 1h) — the
    # 5000.00 backdated 25h is excluded.
    assert visits_count == 2
    assert visits_revenue == Decimal("850.00")
    assert window_since > old_visit.created_at
    assert window_since < recent_visit.created_at


async def test_get_own_revenue_manual_clear_within_24h_still_narrows_the_window(
    real_session, reception_service
):
    """A manual clear that happened recently (well within the last 24h)
    must still take effect exactly as before — the 24h auto-window is a
    ceiling on how far back "My Revenue" ever looks, not a replacement
    for the manual clear."""
    receptionist = await _make_actor(real_session, "revenue-24h-manual-recent")
    await reception_service.register_visit(
        actor=receptionist,
        patient_id=None,
        new_patient=_new_patient_payload("Revenue24hBeforeClear"),
        doctor_user_id=receptionist.id,
        procedure="Consultation",
        amount=Decimal("1000.00"),
        vitals_required=False,
    )

    await reception_service.clear_own_revenue(actor=receptionist)

    await reception_service.register_visit(
        actor=receptionist,
        patient_id=None,
        new_patient=_new_patient_payload("Revenue24hAfterClear"),
        doctor_user_id=receptionist.id,
        procedure="Consultation",
        amount=Decimal("500.00"),
        vitals_required=False,
    )

    visits_count, visits_revenue, _mc, _mr, _ws = await reception_service.get_own_revenue(
        actor=receptionist
    )

    assert visits_count == 1
    assert visits_revenue == Decimal("500.00")


async def test_get_own_revenue_manual_clear_older_than_24h_is_superseded_by_auto_window(
    real_session, reception_service
):
    """A manual clear the receptionist made more than 24h ago is no
    longer doing anything useful — the 24h auto-window has already
    moved past it on its own, so a visit from 20h ago must still show
    up even though it predates that stale clear marker."""
    receptionist = await _make_actor(real_session, "revenue-24h-stale-clear")
    stale_clear = await _make_backdated_clear_marker(
        real_session, receptionist_id=receptionist.id, hours_ago=30
    )

    patient, _visit, _entry = await reception_service.register_visit(
        actor=receptionist,
        patient_id=None,
        new_patient=_new_patient_payload("Revenue24hStaleClearSeed"),
        doctor_user_id=receptionist.id,
        procedure="Consultation",
        amount=Decimal("0.01"),
        vitals_required=False,
    )
    visit = await _make_backdated_visit(
        real_session,
        patient_id=patient.id,
        creator_id=receptionist.id,
        amount=Decimal("1200.00"),
        hours_ago=20,
    )

    visits_count, visits_revenue, _mc, _mr, window_since = await reception_service.get_own_revenue(
        actor=receptionist
    )

    # 0.01 (fresh seed visit, unaffected — it postdates the auto window
    # too) + 1200.00 (backdated 20h, inside the 24h auto-window despite
    # predating the 30h-old stale clear).
    assert visits_count == 2
    assert visits_revenue == Decimal("1200.01")
    # The effective window is the 24h auto-window, not the 30h-old clear.
    assert window_since > stale_clear.created_at
    assert window_since < visit.created_at


async def test_get_own_revenue_24h_window_does_not_affect_admins_alltime_view(
    real_session, reception_service, visit_service
):
    """Even a visit the 24h auto-window has already excluded from a
    receptionist's own display must still count in Admin's all-time
    aggregate — the fix changes nothing about what Admin sees."""
    receptionist = await _make_actor(real_session, "revenue-24h-admin-view")
    patient, _visit, _entry = await reception_service.register_visit(
        actor=receptionist,
        patient_id=None,
        new_patient=_new_patient_payload("Revenue24hAdminViewSeed"),
        doctor_user_id=receptionist.id,
        procedure="Consultation",
        amount=Decimal("0.01"),
        vitals_required=False,
    )
    await _make_backdated_visit(
        real_session,
        patient_id=patient.id,
        creator_id=receptionist.id,
        amount=Decimal("2500.00"),
        hours_ago=48,
    )

    visits_count, visits_revenue, _mc, _mr, _ws = await reception_service.get_own_revenue(
        actor=receptionist
    )
    assert visits_count == 1  # only the fresh 0.01 seed visit
    assert visits_revenue == Decimal("0.01")

    all_time = await visit_service.count_and_revenue_by_creator()
    assert all_time[receptionist.id] == (2, Decimal("2500.01"))
