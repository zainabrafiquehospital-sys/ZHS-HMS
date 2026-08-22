from decimal import Decimal

import pytest
from sqlalchemy.exc import IntegrityError
from uuid6 import uuid7

from app.modules.auth.models import User, UserStatus
from app.modules.auth.repository import UserRepository
from app.modules.patients.models import PatientGender
from app.modules.queue.exceptions import NoActiveQueueEntryError, QueueEntryNotFoundError
from app.modules.queue.models import QueueDestination, QueueEntry, QueueEntryStatus
from app.modules.queue.repository import QueueEntryRepository
from app.shared.payment_method import PaymentMethod
from tests.conftest import TEST_PATIENT_NAME_PREFIX, make_test_email


async def _make_actor(real_session, suffix: str) -> User:
    actor = await UserRepository(real_session).add(
        User(
            email=make_test_email(f"queue-actor-{suffix}"),
            password_hash="hash",
            full_name="Queue Test Actor",
            status=UserStatus.ACTIVE,
        )
    )
    await real_session.commit()
    return actor


async def _make_visit(real_session, patient_service, visit_service, actor, suffix: str):
    patient = await patient_service.register_patient(
        actor=actor,
        full_name=f"{TEST_PATIENT_NAME_PREFIX}Queue{suffix}",
        guardian_name=None,
        gender=PatientGender.FEMALE,
        age_years=27,
        phone_number="03001234567",
        cnic=None,
        address=None,
    )
    return await visit_service.register_visit(
        actor=actor,
        patient_id=patient.id,
        doctor_user_id=actor.id,
        procedures=[(None, "Consultation", Decimal("1500.00"))],
        vitals_required=True,
        initial_payment_amount=Decimal("0.01"),
        initial_payment_method=PaymentMethod.CASH,
    )


async def test_route_to_creates_first_entry(
    real_session, patient_service, visit_service, queue_service
):
    actor = await _make_actor(real_session, "first-entry")
    visit = await _make_visit(real_session, patient_service, visit_service, actor, "A")

    entry = await queue_service.route_to(
        actor=actor, visit_id=visit.id, destination=QueueDestination.VITALS
    )

    assert entry.destination == QueueDestination.VITALS
    assert entry.status == QueueEntryStatus.WAITING
    assert entry.left_at is None


async def test_route_to_closes_previous_entry(
    real_session, patient_service, visit_service, queue_service
):
    actor = await _make_actor(real_session, "close-previous")
    visit = await _make_visit(real_session, patient_service, visit_service, actor, "B")
    first = await queue_service.route_to(
        actor=actor, visit_id=visit.id, destination=QueueDestination.VITALS
    )

    second = await queue_service.route_to(
        actor=actor, visit_id=visit.id, destination=QueueDestination.DOCTOR
    )

    refreshed_first = await QueueEntryRepository(real_session).get_by_id(first.id)
    assert refreshed_first.status == QueueEntryStatus.COMPLETED
    assert refreshed_first.left_at is not None
    assert second.status == QueueEntryStatus.WAITING
    active = await queue_service.get_active_for_visit(visit.id)
    assert active.id == second.id


async def test_route_to_and_back_preserves_full_history(
    real_session, patient_service, visit_service, queue_service
):
    """Mirrors the Doctor -> Vitals -> Doctor detour (§5.2) — three legs,
    all preserved, only the last one active."""
    actor = await _make_actor(real_session, "detour-history")
    visit = await _make_visit(real_session, patient_service, visit_service, actor, "C")
    await queue_service.route_to(
        actor=actor, visit_id=visit.id, destination=QueueDestination.DOCTOR
    )
    await queue_service.route_to(
        actor=actor, visit_id=visit.id, destination=QueueDestination.VITALS
    )
    await queue_service.route_to(
        actor=actor, visit_id=visit.id, destination=QueueDestination.DOCTOR
    )

    history = await queue_service.get_history_for_visit(visit.id)

    assert [entry.destination for entry in history] == [
        QueueDestination.DOCTOR,
        QueueDestination.VITALS,
        QueueDestination.DOCTOR,
    ]
    assert history[0].status == QueueEntryStatus.COMPLETED
    assert history[1].status == QueueEntryStatus.COMPLETED
    assert history[2].status == QueueEntryStatus.WAITING


async def test_start_serving_transitions_to_in_progress(
    real_session, patient_service, visit_service, queue_service
):
    actor = await _make_actor(real_session, "start-serving")
    visit = await _make_visit(real_session, patient_service, visit_service, actor, "D")
    entry = await queue_service.route_to(
        actor=actor, visit_id=visit.id, destination=QueueDestination.DOCTOR
    )

    started = await queue_service.start_serving(actor=actor, entry_id=entry.id)

    assert started.status == QueueEntryStatus.IN_PROGRESS


async def test_start_serving_unknown_entry_raises(real_session, queue_service):
    actor = await _make_actor(real_session, "start-serving-404")
    with pytest.raises(QueueEntryNotFoundError):
        await queue_service.start_serving(actor=actor, entry_id=uuid7())


async def test_complete_current_closes_with_no_successor(
    real_session, patient_service, visit_service, queue_service
):
    actor = await _make_actor(real_session, "complete-current")
    visit = await _make_visit(real_session, patient_service, visit_service, actor, "E")
    await queue_service.route_to(
        actor=actor, visit_id=visit.id, destination=QueueDestination.DOCTOR
    )

    closed = await queue_service.complete_current(actor=actor, visit_id=visit.id)

    assert closed.status == QueueEntryStatus.COMPLETED
    assert await queue_service.get_active_for_visit(visit.id) is None


async def test_complete_current_with_no_active_entry_raises(
    real_session, patient_service, visit_service, queue_service
):
    actor = await _make_actor(real_session, "complete-current-404")
    visit = await _make_visit(real_session, patient_service, visit_service, actor, "F")

    with pytest.raises(NoActiveQueueEntryError):
        await queue_service.complete_current(actor=actor, visit_id=visit.id)


async def test_cancel_current_closes_as_cancelled(
    real_session, patient_service, visit_service, queue_service
):
    actor = await _make_actor(real_session, "cancel-current")
    visit = await _make_visit(real_session, patient_service, visit_service, actor, "G")
    await queue_service.route_to(
        actor=actor, visit_id=visit.id, destination=QueueDestination.DOCTOR
    )

    cancelled = await queue_service.cancel_current(actor=actor, visit_id=visit.id)

    assert cancelled.status == QueueEntryStatus.CANCELLED


async def test_database_rejects_two_simultaneously_active_entries(
    real_session, patient_service, visit_service
):
    """Proves the invariant is enforced at the database level (models.py's
    partial unique index), not only by QueueService's own logic —
    inserting a second open leg directly, bypassing the service, must
    still fail."""
    actor = await _make_actor(real_session, "db-constraint")
    visit = await _make_visit(real_session, patient_service, visit_service, actor, "H")
    repo = QueueEntryRepository(real_session)
    await repo.add(QueueEntry(visit_id=visit.id, destination=QueueDestination.DOCTOR))
    await real_session.commit()

    with pytest.raises(IntegrityError):
        await repo.add(QueueEntry(visit_id=visit.id, destination=QueueDestination.VITALS))
        await real_session.commit()
    await real_session.rollback()
