from datetime import UTC, datetime
from decimal import Decimal

from uuid6 import uuid7

from app.modules.auth.models import User, UserStatus
from app.modules.auth.repository import UserRepository
from app.modules.patients.models import Patient, PatientGender
from app.modules.patients.repository import PatientRepository
from app.modules.queue.models import QueueDestination, QueueEntry, QueueEntryStatus
from app.modules.queue.repository import QUEUE_ENTRY_SORTABLE_COLUMNS, QueueEntryRepository
from app.modules.visits.models import Visit
from app.modules.visits.repository import VisitRepository
from tests.conftest import make_test_email


async def _make_visit(db_session) -> Visit:
    patient = await PatientRepository(db_session).add(
        Patient(
            mr_number=f"MR-{uuid7().hex[-8:]}",
            full_name=f"Queue Repo Patient {uuid7()}",
            gender=PatientGender.FEMALE,
            age_years=30,
            phone_number="03001234567",
        )
    )
    doctor = await UserRepository(db_session).add(
        User(
            email=make_test_email(f"queue-repo-doctor-{uuid7().hex[-6:]}"),
            password_hash="hash",
            full_name="Queue Repo Doctor",
            status=UserStatus.ACTIVE,
        )
    )
    return await VisitRepository(db_session).add(
        Visit(
            patient_id=patient.id,
            doctor_user_id=doctor.id,
            queue_token=f"GYN-{uuid7().hex[-8:]}",
            procedure="Consultation",
            amount=Decimal("1500.00"),
            vitals_required=True,
        )
    )


async def _make_entry(
    db_session,
    *,
    visit: Visit,
    destination: QueueDestination = QueueDestination.RECEPTION,
    status: QueueEntryStatus = QueueEntryStatus.WAITING,
    left_at=None,
) -> QueueEntry:
    entry = QueueEntry(visit_id=visit.id, destination=destination, status=status, left_at=left_at)
    return await QueueEntryRepository(db_session).add(entry)


async def test_get_active_for_visit_finds_open_entry(db_session):
    visit = await _make_visit(db_session)
    entry = await _make_entry(db_session, visit=visit)

    found = await QueueEntryRepository(db_session).get_active_for_visit(visit.id)

    assert found is not None
    assert found.id == entry.id


async def test_get_active_for_visit_ignores_closed_entries(db_session):
    visit = await _make_visit(db_session)
    await _make_entry(db_session, visit=visit, left_at=datetime.now(UTC))

    found = await QueueEntryRepository(db_session).get_active_for_visit(visit.id)

    assert found is None


async def test_list_history_for_visit_returns_chronological_order(db_session):
    visit = await _make_visit(db_session)
    first = await _make_entry(
        db_session,
        visit=visit,
        destination=QueueDestination.RECEPTION,
        left_at=datetime.now(UTC),
    )
    second = await _make_entry(db_session, visit=visit, destination=QueueDestination.VITALS)

    history = await QueueEntryRepository(db_session).list_history_for_visit(visit.id)

    assert [entry.id for entry in history] == [first.id, second.id]


async def test_worklist_filters_by_destination_and_status(db_session):
    visit_a = await _make_visit(db_session)
    visit_b = await _make_visit(db_session)
    target = await _make_entry(db_session, visit=visit_a, destination=QueueDestination.DOCTOR)
    await _make_entry(db_session, visit=visit_b, destination=QueueDestination.VITALS)

    entries, total = await QueueEntryRepository(db_session).worklist(
        destination=QueueDestination.DOCTOR,
        status=QueueEntryStatus.WAITING,
        sort_column=QUEUE_ENTRY_SORTABLE_COLUMNS["created_at"],
        limit=20,
        offset=0,
    )

    assert total == 1
    assert entries[0].id == target.id


async def test_worklist_excludes_soft_deleted_entries(db_session):
    visit = await _make_visit(db_session)
    entry = await _make_entry(db_session, visit=visit, destination=QueueDestination.DOCTOR)
    repo = QueueEntryRepository(db_session)
    await repo.soft_delete(entry, deleted_at=datetime.now(UTC))

    entries, total = await repo.worklist(
        destination=QueueDestination.DOCTOR,
        status=None,
        sort_column=QUEUE_ENTRY_SORTABLE_COLUMNS["created_at"],
        limit=20,
        offset=0,
    )

    assert total == 0
    assert entries == []


async def test_count_waiting_by_destination_reflects_new_entries(db_session):
    """Asserts a delta, not an absolute count — see
    test_visits_repository.py's identical test for why."""
    repo = QueueEntryRepository(db_session)
    baseline = await repo.count_waiting_by_destination()
    visit_a = await _make_visit(db_session)
    visit_b = await _make_visit(db_session)
    await _make_entry(db_session, visit=visit_a, destination=QueueDestination.VITALS)
    await _make_entry(db_session, visit=visit_b, destination=QueueDestination.VITALS)

    after = await repo.count_waiting_by_destination()

    assert after[QueueDestination.VITALS] - baseline.get(QueueDestination.VITALS, 0) == 2


async def test_count_waiting_by_destination_excludes_non_waiting(db_session):
    repo = QueueEntryRepository(db_session)
    baseline = await repo.count_waiting_by_destination()
    visit = await _make_visit(db_session)
    await _make_entry(
        db_session,
        visit=visit,
        destination=QueueDestination.DOCTOR,
        status=QueueEntryStatus.IN_PROGRESS,
    )

    after = await repo.count_waiting_by_destination()

    assert after.get(QueueDestination.DOCTOR, 0) == baseline.get(QueueDestination.DOCTOR, 0)
