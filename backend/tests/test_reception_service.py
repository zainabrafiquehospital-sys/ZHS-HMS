from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest
from uuid6 import uuid7

from app.modules.auth.models import LoginSession, User, UserStatus
from app.modules.auth.repository import LoginSessionRepository, UserRepository
from app.modules.consultation.constants import PERMISSION_CONSULTATION_START
from app.modules.lab.models import LabBill, LabBillStatus
from app.modules.lab.repository import LabBillRepository
from app.modules.patients.exceptions import PatientNotFoundError
from app.modules.patients.models import PatientGender
from app.modules.pharmacy.models import MedicineCategory
from app.modules.queue.models import QueueDestination, QueueEntryStatus
from app.modules.reception.exceptions import (
    DoctorNotAvailableForAssignmentError,
    VisitHasSettledInvoiceError,
)
from app.modules.visits.exceptions import (
    VisitHasSettledPaymentError,
    VisitNotFoundError,
    VisitNotItemizedError,
)
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


async def _make_legacy_visit(
    real_session, patient_service, actor: User, suffix: str, *, amount=Decimal("1500.00")
) -> Visit:
    """A visit with no `VisitProcedureItem` rows at all — mirrors any
    visit registered before 2026-08-21 (see app/modules/visits/models.py's
    `VisitProcedureItem` docstring) via direct ORM construction, bypassing
    `VisitService.register_visit` (which always itemizes a visit created
    from now on). Used to test that the original flat procedure/amount
    admin-edit path is completely unaffected by the itemized-procedures
    feature for exactly the visits it was never meant to touch."""
    patient = await patient_service.register_patient(
        actor=actor,
        full_name=f"{TEST_PATIENT_NAME_PREFIX}Legacy{suffix}",
        guardian_name=None,
        gender=PatientGender.FEMALE,
        age_years=30,
        phone_number="03001234567",
        cnic=None,
        address=None,
    )
    visit = Visit(
        patient_id=patient.id,
        doctor_user_id=actor.id,
        queue_token=f"GYN-{uuid7().hex[-8:]}",
        procedure="Consultation",
        amount=amount,
        vitals_required=False,
        status=VisitStatus.REGISTERED,
        created_by=actor.id,
        updated_by=actor.id,
    )
    return await VisitRepository(real_session).add(visit)


async def test_register_visit_with_new_patient_routes_to_vitals(real_session, reception_service):
    actor = await _make_actor(real_session, "new-patient-vitals")

    patient, visit, entry = await reception_service.register_visit(
        actor=actor,
        patient_id=None,
        new_patient=_new_patient_payload("A"),
        doctor_user_id=None,
        procedures=[(None, "Consultation", Decimal("1500.00"))],
        vitals_required=True,
        initial_payment_amount=Decimal("0.01"),
        initial_payment_method=PaymentMethod.CASH,
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
        doctor_user_id=None,
        procedures=[(None, "Follow-up", Decimal("1500.00"))],
        vitals_required=False,
        initial_payment_amount=Decimal("0.01"),
        initial_payment_method=PaymentMethod.CASH,
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
        doctor_user_id=None,
        procedures=[(None, "Follow-up", Decimal("1500.00"))],
        vitals_required=False,
        initial_payment_amount=Decimal("0.01"),
        initial_payment_method=PaymentMethod.CASH,
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
            doctor_user_id=None,
            procedures=[(None, "Consultation", Decimal("1500.00"))],
            vitals_required=False,
            initial_payment_amount=Decimal("0.01"),
            initial_payment_method=PaymentMethod.CASH,
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
        procedures=[(None, "Consultation", Decimal("1500.00"))],
        vitals_required=False,
        initial_payment_amount=Decimal("0.01"),
        initial_payment_method=PaymentMethod.CASH,
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
        procedures=[(None, "Consultation", Decimal("1500.00"))],
        vitals_required=False,
        initial_payment_amount=Decimal("0.01"),
        initial_payment_method=PaymentMethod.CASH,
    )

    assert visit.doctor_user_id is None
    assert visit.status == VisitStatus.WAITING_DOCTOR
    assert entry.destination == QueueDestination.DOCTOR


# ---------------------------------------------------------------------
# Explicit doctor selection (2026-08-24 addition) — RegisterVisitForm.jsx's
# optional "Assign to Doctor" dropdown. See ReceptionRepository.
# get_doctor_by_id's own docstring for why an explicit selection is
# validated rather than trusted as-is.
# ---------------------------------------------------------------------


async def test_register_visit_with_explicit_doctor_selection_bypasses_auto_assign(
    real_session, reception_service, grant_permission
):
    """An explicit `doctor_user_id` wins even when a *different*,
    genuinely-online least-busy doctor also exists — proving this is a
    real bypass of auto-assignment, not merely a value that happens to
    coincide with what auto-assign would have picked anyway. The
    explicitly-selected doctor is deliberately offline (no active
    LoginSession) — Reception must be able to route to a doctor who
    isn't currently online, not only among whoever is logged in."""
    receptionist = await _make_actor(real_session, "explicit-select-receptionist")
    online_doctor = await _make_actor(real_session, "explicit-select-online-doctor")
    await grant_permission(online_doctor, PERMISSION_CONSULTATION_START)
    await LoginSessionRepository(real_session).add(LoginSession(user_id=online_doctor.id))
    offline_doctor = await _make_actor(real_session, "explicit-select-offline-doctor")
    await grant_permission(offline_doctor, PERMISSION_CONSULTATION_START)
    await real_session.commit()

    _patient, visit, _entry = await reception_service.register_visit(
        actor=receptionist,
        patient_id=None,
        new_patient=_new_patient_payload("ExplicitSelect"),
        doctor_user_id=offline_doctor.id,
        procedures=[(None, "Consultation", Decimal("1500.00"))],
        vitals_required=False,
        initial_payment_amount=Decimal("0.01"),
        initial_payment_method=PaymentMethod.CASH,
    )

    assert visit.doctor_user_id == offline_doctor.id


async def test_register_visit_rejects_an_unknown_explicit_doctor_id(
    real_session, reception_service
):
    """A `doctor_user_id` that doesn't correspond to any real user at
    all (a typo, a stale id) is rejected, never silently treated as
    "fall back to auto-assign"."""
    receptionist = await _make_actor(real_session, "unknown-doctor-receptionist")

    with pytest.raises(DoctorNotAvailableForAssignmentError):
        await reception_service.register_visit(
            actor=receptionist,
            patient_id=None,
            new_patient=_new_patient_payload("UnknownDoctor"),
            doctor_user_id=uuid7(),
            procedures=[(None, "Consultation", Decimal("1500.00"))],
            vitals_required=False,
            initial_payment_amount=Decimal("0.01"),
            initial_payment_method=PaymentMethod.CASH,
        )


async def test_register_visit_rejects_an_explicit_doctor_id_lacking_consultation_permission(
    real_session, reception_service
):
    """A real, ACTIVE user who simply isn't a doctor (holds no role
    granting `consultation:start`) — e.g. another receptionist's own id
    — must be rejected, not assigned. Confirms the validation actually
    checks doctor *eligibility*, not merely "does this id exist"."""
    receptionist = await _make_actor(real_session, "non-doctor-receptionist")
    not_a_doctor = await _make_actor(real_session, "non-doctor-target")

    with pytest.raises(DoctorNotAvailableForAssignmentError):
        await reception_service.register_visit(
            actor=receptionist,
            patient_id=None,
            new_patient=_new_patient_payload("NonDoctor"),
            doctor_user_id=not_a_doctor.id,
            procedures=[(None, "Consultation", Decimal("1500.00"))],
            vitals_required=False,
            initial_payment_amount=Decimal("0.01"),
            initial_payment_method=PaymentMethod.CASH,
        )


async def test_register_visit_rejects_an_inactive_explicit_doctor_id(
    real_session, reception_service, grant_permission
):
    """A doctor who genuinely holds `consultation:start` but whose
    account is no longer ACTIVE (deactivated, suspended, locked) must
    still be rejected — permission on a role is not by itself
    sufficient, matching find_least_busy_available_doctor's own
    `User.status == UserStatus.ACTIVE` requirement for auto-assignment."""
    receptionist = await _make_actor(real_session, "inactive-doctor-receptionist")
    inactive_doctor = await UserRepository(real_session).add(
        User(
            email=make_test_email("reception-inactive-doctor"),
            password_hash="hash",
            full_name="Inactive Doctor",
            status=UserStatus.INACTIVE,
        )
    )
    await grant_permission(inactive_doctor, PERMISSION_CONSULTATION_START)
    await real_session.commit()

    with pytest.raises(DoctorNotAvailableForAssignmentError):
        await reception_service.register_visit(
            actor=receptionist,
            patient_id=None,
            new_patient=_new_patient_payload("InactiveDoctor"),
            doctor_user_id=inactive_doctor.id,
            procedures=[(None, "Consultation", Decimal("1500.00"))],
            vitals_required=False,
            initial_payment_amount=Decimal("0.01"),
            initial_payment_method=PaymentMethod.CASH,
        )


async def test_cancel_visit_closes_active_queue_entry_and_cancels_visit(
    real_session, reception_service, queue_service
):
    actor = await _make_actor(real_session, "cancel")
    _patient, visit, entry = await reception_service.register_visit(
        actor=actor,
        patient_id=None,
        new_patient=_new_patient_payload("C"),
        doctor_user_id=None,
        procedures=[(None, "Consultation", Decimal("1500.00"))],
        vitals_required=False,
        initial_payment_amount=Decimal("0.01"),
        initial_payment_method=PaymentMethod.CASH,
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


async def _make_visit_waiting_billing(real_session, patient_service, visit_service, doctor, suffix):
    """A visit reaching `WAITING_BILLING` via direct `VisitService`
    status transitions, not `ReceptionService.register_visit`
    (2026-08-22 revision — the three admin_delete_visit tests below
    exist specifically to test Billing's *Invoice*-based deletion block
    in isolation; `register_visit` now always collects a real
    registration-charge payment too, which would confound that
    isolation by *also* tripping the separate, new
    `VisitHasSettledPaymentError` guard regardless of the Invoice's own
    state — exactly the interaction `_make_legacy_visit` above already
    sidesteps for the itemization tests). Uses `_make_legacy_visit`'s
    same bypass shape, then drives the Visit's status forward directly
    (no real Consultation record — nothing these tests check depends
    on one existing)."""
    visit = await _make_legacy_visit(real_session, patient_service, doctor, suffix)
    await visit_service.mark_waiting_doctor(actor=doctor, visit_id=visit.id)
    await visit_service.mark_in_consultation(actor=doctor, visit_id=visit.id)
    return await visit_service.mark_waiting_billing(actor=doctor, visit_id=visit.id)


async def test_admin_update_visit_updates_patient_and_visit_fields(
    real_session, reception_service, patient_service
):
    """Uses a legacy (non-itemized) visit — this is exactly the flat
    procedure/amount edit path's original, still-fully-supported case
    (see `_make_legacy_visit`'s own docstring); the itemized-visit
    sibling of this same admin action is covered by
    `test_admin_replace_procedure_items_*` below."""
    admin = await _make_actor(real_session, "update-admin")
    visit = await _make_legacy_visit(real_session, patient_service, admin, "UpdateTarget")

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


async def test_admin_update_visit_with_no_updates_is_a_noop(
    real_session, reception_service, patient_service
):
    admin = await _make_actor(real_session, "update-noop-admin")
    visit = await _make_legacy_visit(real_session, patient_service, admin, "UpdateNoop")

    patient, updated_visit = await reception_service.admin_update_visit(
        actor=admin, visit_id=visit.id, updates={}
    )

    assert updated_visit.procedure == "Consultation"
    assert updated_visit.amount == Decimal("1500.00")


async def test_admin_update_visit_rejects_flat_fields_against_an_itemized_visit(
    real_session, reception_service
):
    """The inverse of the legacy-visit tests above — a visit registered
    from 2026-08-21 onward always has procedure items, so its flat
    (unused) procedure/amount fields are rejected outright rather than
    silently accepted (see VisitService.update_visit_details's own
    docstring). 2026-08-22 revision: `VisitService.register_visit` now
    also always collects a real registration-charge payment, so a real
    visit built this way is *also* always `VisitHasSettledPaymentError`-
    blocked — checked first (see that method's own docstring on the
    deliberate ordering) — which is the exception actually raised here,
    not `VisitAlreadyItemizedError`. The itemization-rejection path in
    isolation (a payment-untracked-but-itemized visit can never occur
    through any real flow from now on) is no longer independently
    testable this way; this test now documents the actual, current
    behavior for a real post-2026-08-22 itemized visit instead."""
    admin = await _make_actor(real_session, "update-itemized-admin")
    _patient, visit, _entry = await reception_service.register_visit(
        actor=admin,
        patient_id=None,
        new_patient=_new_patient_payload("UpdateItemizedReject"),
        doctor_user_id=None,
        procedures=[(None, "Consultation", Decimal("1500.00"))],
        vitals_required=False,
        initial_payment_amount=Decimal("0.01"),
        initial_payment_method=PaymentMethod.CASH,
    )

    with pytest.raises(VisitHasSettledPaymentError):
        await reception_service.admin_update_visit(
            actor=admin, visit_id=visit.id, updates={"procedure": "Ultrasound"}
        )


async def test_admin_replace_procedure_items_replaces_the_whole_set(
    real_session, reception_service, visit_service
):
    """The itemized-visit sibling of the legacy flat-field edit above —
    replaces the entire procedure-item set in one call and recomputes
    `Visit.amount` from the new subtotal against the visit's existing,
    untouched `discount_amount` (see VisitService.
    admin_replace_procedure_items's own docstring)."""
    admin = await _make_actor(real_session, "replace-items-admin")
    _patient, visit, _entry = await reception_service.register_visit(
        actor=admin,
        patient_id=None,
        new_patient=_new_patient_payload("ReplaceItems"),
        doctor_user_id=None,
        procedures=[(None, "Checkup", Decimal("800.00")), (None, "Scan", Decimal("700.00"))],
        vitals_required=False,
        initial_payment_amount=Decimal("0.01"),
        initial_payment_method=PaymentMethod.CASH,
        discount_amount=Decimal("200.00"),
    )
    assert visit.amount == Decimal("1300.00")  # 1500 subtotal - 200 discount

    _patient, updated_visit = await reception_service.admin_update_visit(
        actor=admin,
        visit_id=visit.id,
        updates={},
        procedures=[(None, "Ultrasound", Decimal("2000.00"))],
    )

    items = await visit_service.list_procedure_items(visit.id)
    assert len(items) == 1
    assert items[0].name == "Ultrasound"
    assert items[0].amount == Decimal("2000.00")
    # Discount is untouched by this action (a separately confirmed,
    # explicit scope decision) — recomputed against the SAME 200.00
    # discount against the NEW 2000.00 subtotal.
    assert updated_visit.discount_amount == Decimal("200.00")
    assert updated_visit.amount == Decimal("1800.00")


async def test_admin_replace_procedure_items_rejects_against_a_legacy_visit(
    real_session, reception_service, patient_service
):
    """The inverse of the itemized-visit test above — a visit registered
    before 2026-08-21 has no procedure items to replace at all (see
    VisitService.admin_replace_procedure_items's own docstring for the
    `VisitNotItemizedError` this raises)."""
    admin = await _make_actor(real_session, "replace-items-legacy-admin")
    visit = await _make_legacy_visit(real_session, patient_service, admin, "ReplaceItemsLegacy")

    with pytest.raises(VisitNotItemizedError):
        await reception_service.admin_update_visit(
            actor=admin,
            visit_id=visit.id,
            updates={},
            procedures=[(None, "Ultrasound", Decimal("2000.00"))],
        )


async def test_admin_delete_visit_soft_deletes_and_closes_active_queue_entry(
    real_session, reception_service, patient_service, visit_service, queue_service
):
    """A legacy-shaped visit (`_make_legacy_visit`, no registration-
    charge payment tracking — see that helper's own docstring) with a
    queue entry created directly, mirroring what `ReceptionService.
    register_visit` itself does — this test is specifically about the
    queue-entry-closing behavior, deliberately isolated from the (also
    confirmed, tested separately) registration-payment block."""
    admin = await _make_actor(real_session, "delete-admin")
    visit = await _make_legacy_visit(real_session, patient_service, admin, "DeleteTarget")
    await queue_service.route_to(
        actor=admin, visit_id=visit.id, destination=QueueDestination.DOCTOR, reason="test_setup"
    )
    assert await queue_service.get_active_for_visit(visit.id) is not None

    await reception_service.admin_delete_visit(actor=admin, visit_id=visit.id)

    with pytest.raises(VisitNotFoundError):
        await visit_service.get_visit(visit.id)
    assert await queue_service.get_active_for_visit(visit.id) is None


async def test_admin_delete_visit_blocked_when_invoice_paid(
    real_session, reception_service, patient_service, visit_service, billing_service
):
    admin = await _make_actor(real_session, "delete-blocked-admin")
    visit = await _make_visit_waiting_billing(
        real_session, patient_service, visit_service, admin, "DeleteBlocked"
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
    real_session, reception_service, patient_service, visit_service, billing_service
):
    admin = await _make_actor(real_session, "delete-partial-admin")
    visit = await _make_visit_waiting_billing(
        real_session, patient_service, visit_service, admin, "DeletePartial"
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
    real_session, reception_service, patient_service, visit_service, billing_service
):
    """An invoice with nothing yet collected against it (PENDING_PAYMENT)
    is real paperwork, but no money has changed hands — deliberately not
    a block (see ReceptionService.admin_delete_visit's own docstring).
    Uses a visit with no registration-charge payment tracking either
    (see `_make_visit_waiting_billing`'s own docstring) — this test is
    specifically about the Invoice-based block being independent of the
    (different, also confirmed) registration-payment block, in
    isolation."""
    admin = await _make_actor(real_session, "delete-unpaid-admin")
    visit = await _make_visit_waiting_billing(
        real_session, patient_service, visit_service, admin, "DeleteUnpaid"
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
# Registration-charge payment tracking's admin edit guard (2026-08-22
# addition, 2026-08-23 revision) — VisitHasSettledPaymentError now
# applies only to `update_visit_details`'s legacy flat-field path, never
# to `admin_delete_visit` — see that exception's own docstring for why
# a soft-delete's much lower integrity risk (it never touches
# `amount_paid`/`amount` at all) doesn't warrant the same block, which
# would otherwise make every visit registered from now on permanently
# undeletable through this tool (payment is always mandatory at
# registration).
# ---------------------------------------------------------------------


async def test_admin_delete_visit_succeeds_despite_a_partially_paid_registration_charge(
    real_session, reception_service, visit_service
):
    """2026-08-23 revision — a recorded registration payment (partial
    or full) no longer blocks deletion at all; only a settled Billing
    Invoice does (see the sibling tests above). The soft-delete leaves
    the visit's `VisitPayment` rows orphaned-but-intact, the same
    accepted outcome already applied to an unpaid Invoice/Consultation/
    VitalsRecord."""
    admin = await _make_actor(real_session, "delete-despite-partial-payment")
    _patient, visit, _entry = await reception_service.register_visit(
        actor=admin,
        patient_id=None,
        new_patient=_new_patient_payload("DeleteDespitePartialPayment"),
        doctor_user_id=None,
        procedures=[(None, "C-Section", Decimal("50000.00"))],
        vitals_required=False,
        initial_payment_amount=Decimal("20000.00"),
        initial_payment_method=PaymentMethod.CASH,
    )

    await reception_service.admin_delete_visit(actor=admin, visit_id=visit.id)

    with pytest.raises(VisitNotFoundError):
        await visit_service.get_visit(visit.id)


async def test_admin_delete_visit_succeeds_despite_a_fully_paid_registration_charge(
    real_session, reception_service, visit_service
):
    admin = await _make_actor(real_session, "delete-despite-full-payment")
    _patient, visit, _entry = await reception_service.register_visit(
        actor=admin,
        patient_id=None,
        new_patient=_new_patient_payload("DeleteDespiteFullPayment"),
        doctor_user_id=None,
        procedures=[(None, "Consultation", Decimal("1500.00"))],
        vitals_required=False,
        initial_payment_amount=Decimal("1500.00"),
        initial_payment_method=PaymentMethod.CASH,
    )

    await reception_service.admin_delete_visit(actor=admin, visit_id=visit.id)

    with pytest.raises(VisitNotFoundError):
        await visit_service.get_visit(visit.id)


async def test_admin_delete_visit_allowed_for_legacy_visit_with_no_payment_tracking(
    real_session, reception_service, patient_service, visit_service
):
    """A visit that predates payment tracking (`payment_status IS
    NULL`) deletes exactly as it always has, zero regression — kept
    alongside the two tests above to cover all three `payment_status`
    shapes (`None`/`partially_paid`/`paid`) now uniformly deletable."""
    admin = await _make_actor(real_session, "delete-legacy-no-payment")
    visit = await _make_legacy_visit(real_session, patient_service, admin, "DeleteLegacyNoPayment")

    await reception_service.admin_delete_visit(actor=admin, visit_id=visit.id)

    with pytest.raises(VisitNotFoundError):
        await visit_service.get_visit(visit.id)


async def test_update_visit_details_blocked_when_visit_has_settled_payment(
    real_session, reception_service, visit_service
):
    """The legacy flat procedure/amount edit path rejects outright
    against any visit with a real recorded payment — checked before the
    (also-true, for any post-2026-08-21 visit) itemization rejection, so
    this is the exception actually raised."""
    admin = await _make_actor(real_session, "update-blocked-settled-payment")
    _patient, visit, _entry = await reception_service.register_visit(
        actor=admin,
        patient_id=None,
        new_patient=_new_patient_payload("UpdateBlockedSettledPayment"),
        doctor_user_id=None,
        procedures=[(None, "Consultation", Decimal("1500.00"))],
        vitals_required=False,
        initial_payment_amount=Decimal("1500.00"),
        initial_payment_method=PaymentMethod.CASH,
    )

    with pytest.raises(VisitHasSettledPaymentError):
        await visit_service.update_visit_details(
            actor=admin, visit_id=visit.id, updates={"amount": Decimal("2000.00")}
        )


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


async def _make_lab_bill(real_session, *, creator_id, amount: Decimal) -> LabBill:
    """A direct-insert LabBill (no LabService fixture exists in this
    file, unlike pharmacy_service above) — same "construct the row
    directly via its repository" shape as `_make_backdated_visit`
    further below, standing in as a standalone walk-in sale
    (patient_id/manual_patient_* all None, allowed by LabBill's own
    mutual-exclusivity CHECK constraints)."""
    bill = LabBill(
        queue_token=_unique_token(),
        total_amount=amount,
        amount_paid=Decimal("0.00"),
        status=LabBillStatus.UNPAID,
        created_by=creator_id,
    )
    return await LabBillRepository(real_session).add(bill)


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
        doctor_user_id=None,
        procedures=[(None, "Consultation", Decimal("1500.00"))],
        vitals_required=False,
        initial_payment_amount=Decimal("0.01"),
        initial_payment_method=PaymentMethod.CASH,
    )
    await reception_service.register_visit(
        actor=receptionist_b,
        patient_id=None,
        new_patient=_new_patient_payload("RevenueOwnB"),
        doctor_user_id=None,
        procedures=[(None, "Consultation", Decimal("9999.00"))],
        vitals_required=False,
        initial_payment_amount=Decimal("0.01"),
        initial_payment_method=PaymentMethod.CASH,
    )

    (
        visits_count,
        visits_revenue,
        _med_count,
        _med_revenue,
        _lab_count,
        _lab_revenue,
        window_since,
    ) = await reception_service.get_own_revenue(actor=receptionist_a)

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
        doctor_user_id=None,
        procedures=[(None, "Consultation", Decimal("1500.00"))],
        vitals_required=False,
        initial_payment_amount=Decimal("0.01"),
        initial_payment_method=PaymentMethod.CASH,
    )
    await pharmacy_service.create_bill(actor=receptionist, visit_id=None, items=[(medicine.id, 2)])

    (
        visits_count,
        visits_revenue,
        med_count,
        med_revenue,
        _lab_count,
        _lab_revenue,
        _cleared_at,
    ) = await reception_service.get_own_revenue(actor=receptionist)

    assert visits_count == 1
    assert visits_revenue == Decimal("1500.00")
    assert med_count == 1
    assert med_revenue == Decimal("200.00")  # 2 x 100.00


async def test_get_own_revenue_includes_lab_bills_in_breakdown(real_session, reception_service):
    """The lab-bill sibling of
    test_get_own_revenue_includes_medicine_bills_in_breakdown above —
    same shape, own-scoped, added alongside visits/medicines rather
    than replacing either (Step 4 addition)."""
    receptionist = await _make_actor(real_session, "revenue-lab")

    await reception_service.register_visit(
        actor=receptionist,
        patient_id=None,
        new_patient=_new_patient_payload("RevenueLabVisit"),
        doctor_user_id=None,
        procedures=[(None, "Consultation", Decimal("1500.00"))],
        vitals_required=False,
        initial_payment_amount=Decimal("0.01"),
        initial_payment_method=PaymentMethod.CASH,
    )
    await _make_lab_bill(real_session, creator_id=receptionist.id, amount=Decimal("600.00"))
    await _make_lab_bill(real_session, creator_id=receptionist.id, amount=Decimal("300.00"))

    (
        visits_count,
        visits_revenue,
        _med_count,
        _med_revenue,
        lab_count,
        lab_revenue,
        _cleared_at,
    ) = await reception_service.get_own_revenue(actor=receptionist)

    assert visits_count == 1
    assert visits_revenue == Decimal("1500.00")
    assert lab_count == 2
    assert lab_revenue == Decimal("900.00")  # 600.00 + 300.00


async def test_clear_own_revenue_resets_display_but_leaves_data_intact(
    real_session, reception_service, visit_service
):
    receptionist = await _make_actor(real_session, "revenue-clear")
    _patient, visit, _entry = await reception_service.register_visit(
        actor=receptionist,
        patient_id=None,
        new_patient=_new_patient_payload("RevenueClear"),
        doctor_user_id=None,
        procedures=[(None, "Consultation", Decimal("1500.00"))],
        vitals_required=False,
        initial_payment_amount=Decimal("0.01"),
        initial_payment_method=PaymentMethod.CASH,
    )

    before_count, before_revenue, _mc, _mr, _lc, _lr, _ca = await reception_service.get_own_revenue(
        actor=receptionist
    )
    assert before_count == 1
    assert before_revenue == Decimal("1500.00")

    cleared_at = await reception_service.clear_own_revenue(actor=receptionist)
    assert cleared_at is not None

    (
        after_count,
        after_revenue,
        _mc2,
        _mr2,
        _lc2,
        _lr2,
        reported_cleared_at,
    ) = await reception_service.get_own_revenue(actor=receptionist)
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
        doctor_user_id=None,
        procedures=[(None, "Consultation", Decimal("1500.00"))],
        vitals_required=False,
        initial_payment_amount=Decimal("0.01"),
        initial_payment_method=PaymentMethod.CASH,
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
        doctor_user_id=None,
        procedures=[(None, "Consultation", Decimal("1500.00"))],
        vitals_required=False,
        initial_payment_amount=Decimal("0.01"),
        initial_payment_method=PaymentMethod.CASH,
    )

    await reception_service.clear_own_revenue(actor=receptionist_b)

    (
        a_count,
        a_revenue,
        _mc,
        _mr,
        _lc,
        _lr,
        a_window_since,
    ) = await reception_service.get_own_revenue(actor=receptionist_a)
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


async def _make_backdated_clear_marker(
    real_session, *, receptionist_id, hours_ago: float
) -> AuditEntry:
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
        doctor_user_id=None,
        procedures=[(None, "Consultation", Decimal("100.00"))],
        vitals_required=False,
        initial_payment_amount=Decimal("0.01"),
        initial_payment_method=PaymentMethod.CASH,
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

    (
        visits_count,
        visits_revenue,
        _mc,
        _mr,
        _lc,
        _lr,
        window_since,
    ) = await reception_service.get_own_revenue(actor=receptionist)

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
        doctor_user_id=None,
        procedures=[(None, "Consultation", Decimal("1000.00"))],
        vitals_required=False,
        initial_payment_amount=Decimal("0.01"),
        initial_payment_method=PaymentMethod.CASH,
    )

    await reception_service.clear_own_revenue(actor=receptionist)

    await reception_service.register_visit(
        actor=receptionist,
        patient_id=None,
        new_patient=_new_patient_payload("Revenue24hAfterClear"),
        doctor_user_id=None,
        procedures=[(None, "Consultation", Decimal("500.00"))],
        vitals_required=False,
        initial_payment_amount=Decimal("0.01"),
        initial_payment_method=PaymentMethod.CASH,
    )

    (
        visits_count,
        visits_revenue,
        _mc,
        _mr,
        _lc,
        _lr,
        _ws,
    ) = await reception_service.get_own_revenue(actor=receptionist)

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
        doctor_user_id=None,
        procedures=[(None, "Consultation", Decimal("0.01"))],
        vitals_required=False,
        initial_payment_amount=Decimal("0.01"),
        initial_payment_method=PaymentMethod.CASH,
    )
    visit = await _make_backdated_visit(
        real_session,
        patient_id=patient.id,
        creator_id=receptionist.id,
        amount=Decimal("1200.00"),
        hours_ago=20,
    )

    (
        visits_count,
        visits_revenue,
        _mc,
        _mr,
        _lc,
        _lr,
        window_since,
    ) = await reception_service.get_own_revenue(actor=receptionist)

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
        doctor_user_id=None,
        procedures=[(None, "Consultation", Decimal("0.01"))],
        vitals_required=False,
        initial_payment_amount=Decimal("0.01"),
        initial_payment_method=PaymentMethod.CASH,
    )
    await _make_backdated_visit(
        real_session,
        patient_id=patient.id,
        creator_id=receptionist.id,
        amount=Decimal("2500.00"),
        hours_ago=48,
    )

    (
        visits_count,
        visits_revenue,
        _mc,
        _mr,
        _lc,
        _lr,
        _ws,
    ) = await reception_service.get_own_revenue(actor=receptionist)
    assert visits_count == 1  # only the fresh 0.01 seed visit
    assert visits_revenue == Decimal("0.01")

    all_time = await visit_service.count_and_revenue_by_creator()
    assert all_time[receptionist.id] == (2, Decimal("2500.01"))


async def test_list_doctors_for_selection_reports_online_status_correctly(
    real_session, reception_service, grant_permission
):
    """Backs GET /reception/doctors (RegisterVisitForm.jsx's dropdown).
    Deliberately does not assert on the *exact* returned list/order —
    this suite runs against a shared dev database that may already
    hold other eligible doctor accounts (see tests/conftest.py's own
    documented shared-DB caveats) — only that this test's own two
    doctors both appear, each with the correct `is_online` flag."""
    online_doctor = await _make_actor(real_session, "list-selection-online-doctor")
    await grant_permission(online_doctor, PERMISSION_CONSULTATION_START)
    await LoginSessionRepository(real_session).add(LoginSession(user_id=online_doctor.id))
    offline_doctor = await _make_actor(real_session, "list-selection-offline-doctor")
    await grant_permission(offline_doctor, PERMISSION_CONSULTATION_START)
    await real_session.commit()

    doctors = await reception_service.list_doctors_for_selection()
    by_id = {user.id: is_online for user, is_online in doctors}

    assert by_id.get(online_doctor.id) is True
    assert by_id.get(offline_doctor.id) is False
