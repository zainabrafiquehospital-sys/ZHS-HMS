from decimal import Decimal

import pytest
from uuid6 import uuid7

from app.core.exceptions import ValidationError
from app.modules.auth.models import User, UserStatus
from app.modules.auth.repository import UserRepository
from app.modules.patients.models import PatientGender
from app.modules.visits.exceptions import (
    InvalidVisitStatusTransitionError,
    VisitDiscountExceedsAmountError,
    VisitNotFoundError,
)
from app.modules.visits.models import VisitStatus
from tests.conftest import TEST_PATIENT_NAME_PREFIX, make_test_email


async def _make_actor(real_session, suffix: str) -> User:
    actor = await UserRepository(real_session).add(
        User(
            email=make_test_email(f"visit-actor-{suffix}"),
            password_hash="hash",
            full_name="Visit Test Actor",
            status=UserStatus.ACTIVE,
        )
    )
    await real_session.commit()
    return actor


async def _make_patient(real_session, patient_service, actor: User, suffix: str):
    return await patient_service.register_patient(
        actor=actor,
        full_name=f"{TEST_PATIENT_NAME_PREFIX}Visit{suffix}",
        guardian_name=None,
        gender=PatientGender.FEMALE,
        age_years=28,
        phone_number="03001234567",
        cnic=None,
        address=None,
    )


async def test_register_visit_generates_queue_token_and_routes_to_vitals(
    real_session, patient_service, visit_service
):
    actor = await _make_actor(real_session, "register-vitals")
    patient = await _make_patient(real_session, patient_service, actor, "A")

    visit = await visit_service.register_visit(
        actor=actor,
        patient_id=patient.id,
        doctor_user_id=actor.id,
        procedure="Consultation",
        amount=Decimal("1500.00"),
        vitals_required=True,
    )

    assert visit.queue_token.startswith("Token #")
    assert visit.status == VisitStatus.WAITING_VITALS


async def test_register_visit_amount_is_quantized_to_two_decimal_places(
    real_session, patient_service, visit_service
):
    """A caller-supplied amount with fewer than 2 decimal places (e.g.
    the fast-registration form submitting a whole number) must come
    back at the column's actual scale in the *same* response — not only
    on a later, separate fetch — see app/shared/money.py's docstring
    for why this doesn't just happen automatically."""
    actor = await _make_actor(real_session, "amount-quantize")
    patient = await _make_patient(real_session, patient_service, actor, "AmountQuantize")

    visit = await visit_service.register_visit(
        actor=actor,
        patient_id=patient.id,
        doctor_user_id=actor.id,
        procedure="Normal Delivery",
        amount=Decimal("20000"),
        vitals_required=False,
    )

    assert visit.amount == Decimal("20000.00")
    assert str(visit.amount) == "20000.00"


async def test_register_visit_without_discount_has_zero_discount_fields(
    real_session, patient_service, visit_service
):
    """The common, no-discount case must be byte-for-byte the same
    behavior as before this feature — amount stored exactly as entered,
    discount_amount 0.00, discount_reason None."""
    actor = await _make_actor(real_session, "no-discount")
    patient = await _make_patient(real_session, patient_service, actor, "NoDiscount")

    visit = await visit_service.register_visit(
        actor=actor,
        patient_id=patient.id,
        doctor_user_id=actor.id,
        procedure="Consultation",
        amount=Decimal("1500.00"),
        vitals_required=False,
    )

    assert visit.amount == Decimal("1500.00")
    assert visit.discount_amount == Decimal("0.00")
    assert visit.discount_reason is None


async def test_register_visit_with_discount_stores_post_discount_amount(
    real_session, patient_service, visit_service
):
    """The core requirement: `amount` on the stored Visit ends up
    already post-discount — the same column every existing reader
    (Billing's Generate Invoice prefill, every revenue aggregate)
    already treats as "the real amount", so this is what makes the
    discount actually flow through everywhere else in the system."""
    actor = await _make_actor(real_session, "with-discount")
    patient = await _make_patient(real_session, patient_service, actor, "WithDiscount")

    visit = await visit_service.register_visit(
        actor=actor,
        patient_id=patient.id,
        doctor_user_id=actor.id,
        procedure="Consultation",
        amount=Decimal("2000.00"),
        vitals_required=False,
        discount_amount=Decimal("500.00"),
        discount_reason="Referral",
    )

    assert visit.amount == Decimal("1500.00")
    assert visit.discount_amount == Decimal("500.00")
    assert visit.discount_reason == "Referral"


async def test_register_visit_discount_reason_is_optional(
    real_session, patient_service, visit_service
):
    """Deliberate difference from Invoice's discount, which requires a
    reason — a registration-time discount reason may be left blank,
    the same product decision the medicine-bill discount already made."""
    actor = await _make_actor(real_session, "discount-no-reason")
    patient = await _make_patient(real_session, patient_service, actor, "DiscountNoReason")

    visit = await visit_service.register_visit(
        actor=actor,
        patient_id=patient.id,
        doctor_user_id=actor.id,
        procedure="Consultation",
        amount=Decimal("1000.00"),
        vitals_required=False,
        discount_amount=Decimal("100.00"),
    )

    assert visit.amount == Decimal("900.00")
    assert visit.discount_reason is None


async def test_register_visit_discount_exceeding_amount_rejected(
    real_session, patient_service, visit_service
):
    actor = await _make_actor(real_session, "discount-exceeds")
    patient = await _make_patient(real_session, patient_service, actor, "DiscountExceeds")

    with pytest.raises(VisitDiscountExceedsAmountError):
        await visit_service.register_visit(
            actor=actor,
            patient_id=patient.id,
            doctor_user_id=actor.id,
            procedure="Consultation",
            amount=Decimal("500.00"),
            vitals_required=False,
            discount_amount=Decimal("500.01"),
        )


async def test_register_visit_negative_discount_rejected(
    real_session, patient_service, visit_service
):
    actor = await _make_actor(real_session, "discount-negative")
    patient = await _make_patient(real_session, patient_service, actor, "DiscountNegative")

    with pytest.raises(ValidationError):
        await visit_service.register_visit(
            actor=actor,
            patient_id=patient.id,
            doctor_user_id=actor.id,
            procedure="Consultation",
            amount=Decimal("500.00"),
            vitals_required=False,
            discount_amount=Decimal("-10.00"),
        )


async def test_register_visit_routes_directly_to_doctor_when_vitals_not_required(
    real_session, patient_service, visit_service
):
    actor = await _make_actor(real_session, "register-no-vitals")
    patient = await _make_patient(real_session, patient_service, actor, "B")

    visit = await visit_service.register_visit(
        actor=actor,
        patient_id=patient.id,
        doctor_user_id=actor.id,
        procedure="Follow-up",
        amount=Decimal("1500.00"),
        vitals_required=False,
    )

    assert visit.status == VisitStatus.WAITING_DOCTOR


async def test_full_happy_path_transition_sequence(real_session, patient_service, visit_service):
    actor = await _make_actor(real_session, "happy-path")
    patient = await _make_patient(real_session, patient_service, actor, "C")
    visit = await visit_service.register_visit(
        actor=actor,
        patient_id=patient.id,
        doctor_user_id=actor.id,
        procedure="Consultation",
        amount=Decimal("1500.00"),
        vitals_required=True,
    )
    assert visit.status == VisitStatus.WAITING_VITALS

    visit = await visit_service.mark_waiting_doctor(actor=actor, visit_id=visit.id)
    assert visit.status == VisitStatus.WAITING_DOCTOR

    visit = await visit_service.mark_in_consultation(actor=actor, visit_id=visit.id)
    assert visit.status == VisitStatus.IN_CONSULTATION

    visit = await visit_service.mark_waiting_billing(actor=actor, visit_id=visit.id)
    assert visit.status == VisitStatus.WAITING_BILLING

    visit = await visit_service.mark_payment_pending(actor=actor, visit_id=visit.id)
    assert visit.status == VisitStatus.PAYMENT_PENDING

    visit = await visit_service.mark_completed(actor=actor, visit_id=visit.id)
    assert visit.status == VisitStatus.COMPLETED

    # §4.1's reopening transition: a new Outstanding Invoice created after
    # COMPLETED moves the Visit back to PAYMENT_PENDING, never any other
    # status — this is the one and only edge out of COMPLETED.
    visit = await visit_service.mark_payment_pending(actor=actor, visit_id=visit.id)
    assert visit.status == VisitStatus.PAYMENT_PENDING


async def test_invalid_transition_raises(real_session, patient_service, visit_service):
    actor = await _make_actor(real_session, "invalid-transition")
    patient = await _make_patient(real_session, patient_service, actor, "D")
    visit = await visit_service.register_visit(
        actor=actor,
        patient_id=patient.id,
        doctor_user_id=actor.id,
        procedure="Consultation",
        amount=Decimal("1500.00"),
        vitals_required=False,
    )
    assert visit.status == VisitStatus.WAITING_DOCTOR

    # WAITING_DOCTOR -> WAITING_BILLING is not a legal edge (must pass
    # through IN_CONSULTATION first).
    with pytest.raises(InvalidVisitStatusTransitionError):
        await visit_service.mark_waiting_billing(actor=actor, visit_id=visit.id)


async def test_cancel_visit_from_non_terminal_status(real_session, patient_service, visit_service):
    actor = await _make_actor(real_session, "cancel")
    patient = await _make_patient(real_session, patient_service, actor, "E")
    visit = await visit_service.register_visit(
        actor=actor,
        patient_id=patient.id,
        doctor_user_id=actor.id,
        procedure="Consultation",
        amount=Decimal("1500.00"),
        vitals_required=False,
    )

    cancelled = await visit_service.cancel_visit(actor=actor, visit_id=visit.id)

    assert cancelled.status == VisitStatus.CANCELLED
    with pytest.raises(InvalidVisitStatusTransitionError):
        await visit_service.mark_waiting_doctor(actor=actor, visit_id=visit.id)


async def test_get_visit_raises_not_found(visit_service):
    with pytest.raises(VisitNotFoundError):
        await visit_service.get_visit(uuid7())


async def test_get_by_queue_token_finds_visit(real_session, patient_service, visit_service):
    actor = await _make_actor(real_session, "queue-token-lookup")
    patient = await patient_service.register_patient(
        actor=actor,
        full_name=f"{TEST_PATIENT_NAME_PREFIX}QueueTokenLookup",
        guardian_name=None,
        gender=PatientGender.FEMALE,
        age_years=24,
        phone_number="03001234567",
        cnic=None,
        address=None,
    )
    visit = await visit_service.register_visit(
        actor=actor,
        patient_id=patient.id,
        doctor_user_id=actor.id,
        procedure="Consultation",
        amount=Decimal("1500.00"),
        vitals_required=False,
    )

    found = await visit_service.get_by_queue_token(visit.queue_token)

    assert found is not None
    assert found.id == visit.id


async def test_get_by_queue_token_returns_none_when_missing(visit_service):
    assert await visit_service.get_by_queue_token("GYN-does-not-exist") is None
