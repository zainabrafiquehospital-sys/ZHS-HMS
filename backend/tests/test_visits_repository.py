from datetime import UTC, datetime
from decimal import Decimal

from uuid6 import uuid7

from app.modules.auth.models import User, UserStatus
from app.modules.auth.repository import UserRepository
from app.modules.patients.models import Patient, PatientGender
from app.modules.patients.repository import PatientRepository
from app.modules.visits.models import Visit, VisitStatus
from app.modules.visits.repository import VISIT_SORTABLE_COLUMNS, VisitRepository
from tests.conftest import make_test_email


def _unique_token() -> str:
    """See test_patients_repository.py's _unique_mr_number for why the
    *trailing* hex characters of a uuid7, not the leading ones, are what
    is actually random."""
    return f"GYN-{uuid7().hex[-8:]}"


async def _make_patient(db_session) -> Patient:
    return await PatientRepository(db_session).add(
        Patient(
            mr_number=f"MR-{uuid7().hex[-8:]}",
            full_name=f"Visit Repo Patient {uuid7()}",
            gender=PatientGender.FEMALE,
            age_years=30,
            phone_number="03001234567",
        )
    )


async def _make_doctor(db_session) -> User:
    return await UserRepository(db_session).add(
        User(
            email=make_test_email(f"visit-repo-doctor-{uuid7().hex[-6:]}"),
            password_hash="hash",
            full_name="Visit Repo Doctor",
            status=UserStatus.ACTIVE,
        )
    )


async def _make_visit(
    db_session, *, patient: Patient, doctor: User, status: VisitStatus = VisitStatus.REGISTERED
) -> Visit:
    visit = Visit(
        patient_id=patient.id,
        doctor_user_id=doctor.id,
        queue_token=_unique_token(),
        procedure="Consultation",
        amount=Decimal("1500.00"),
        vitals_required=True,
        status=status,
    )
    return await VisitRepository(db_session).add(visit)


async def test_next_queue_token_value_increments(db_session):
    repo = VisitRepository(db_session)
    first = await repo.next_queue_token_value()
    second = await repo.next_queue_token_value()
    assert second == first + 1


async def test_get_by_queue_token_finds_active_visit(db_session):
    patient = await _make_patient(db_session)
    doctor = await _make_doctor(db_session)
    visit = await _make_visit(db_session, patient=patient, doctor=doctor)

    found = await VisitRepository(db_session).get_by_queue_token(visit.queue_token)

    assert found is not None
    assert found.id == visit.id


async def test_get_by_queue_token_returns_none_when_missing(db_session):
    assert await VisitRepository(db_session).get_by_queue_token("GYN-missing") is None


async def test_search_filters_by_patient_id(db_session):
    patient_a = await _make_patient(db_session)
    patient_b = await _make_patient(db_session)
    doctor = await _make_doctor(db_session)
    target = await _make_visit(db_session, patient=patient_a, doctor=doctor)
    await _make_visit(db_session, patient=patient_b, doctor=doctor)

    visits, total = await VisitRepository(db_session).search(
        patient_id=patient_a.id,
        doctor_user_id=None,
        status=None,
        sort_column=VISIT_SORTABLE_COLUMNS["created_at"],
        sort_desc=True,
        limit=20,
        offset=0,
    )

    assert total == 1
    assert visits[0].id == target.id


async def test_search_filters_by_status(db_session):
    patient = await _make_patient(db_session)
    doctor = await _make_doctor(db_session)
    await _make_visit(db_session, patient=patient, doctor=doctor, status=VisitStatus.REGISTERED)
    target = await _make_visit(
        db_session, patient=patient, doctor=doctor, status=VisitStatus.WAITING_DOCTOR
    )

    visits, total = await VisitRepository(db_session).search(
        patient_id=None,
        doctor_user_id=None,
        status=VisitStatus.WAITING_DOCTOR,
        sort_column=VISIT_SORTABLE_COLUMNS["created_at"],
        sort_desc=True,
        limit=20,
        offset=0,
    )

    assert total == 1
    assert visits[0].id == target.id


async def test_count_by_status_reflects_new_visits(db_session):
    """Asserts a *delta*, not an absolute count — the shared test
    database already holds committed visits from other (non-rollback)
    test suites, so an exact global count would be flaky. This is the
    standard, reliable way to test a genuinely global aggregate query
    against a shared database."""
    repo = VisitRepository(db_session)
    baseline = await repo.count_by_status()
    patient = await _make_patient(db_session)
    doctor = await _make_doctor(db_session)
    await _make_visit(db_session, patient=patient, doctor=doctor, status=VisitStatus.WAITING_DOCTOR)
    await _make_visit(db_session, patient=patient, doctor=doctor, status=VisitStatus.WAITING_DOCTOR)

    after = await repo.count_by_status()

    assert after[VisitStatus.WAITING_DOCTOR] - baseline.get(VisitStatus.WAITING_DOCTOR, 0) == 2


async def test_count_and_revenue_by_creator_reflects_new_visits(db_session):
    """Asserts a delta, not an absolute count — same rationale as
    `test_count_by_status_reflects_new_visits` above (the shared test
    database already holds committed visits from other test suites)."""
    repo = VisitRepository(db_session)
    patient = await _make_patient(db_session)
    doctor = await _make_doctor(db_session)
    creator = await _make_doctor(db_session)  # any real user id works as a creator
    baseline = await repo.count_and_revenue_by_creator()
    baseline_count, baseline_revenue = baseline.get(creator.id, (0, Decimal("0")))

    visit = Visit(
        patient_id=patient.id,
        doctor_user_id=doctor.id,
        queue_token=_unique_token(),
        procedure="Consultation",
        amount=Decimal("1500.00"),
        vitals_required=True,
        status=VisitStatus.REGISTERED,
        created_by=creator.id,
    )
    await repo.add(visit)
    another = Visit(
        patient_id=patient.id,
        doctor_user_id=doctor.id,
        queue_token=_unique_token(),
        procedure="Consultation",
        amount=Decimal("250.50"),
        vitals_required=True,
        status=VisitStatus.REGISTERED,
        created_by=creator.id,
    )
    await repo.add(another)

    after_count, after_revenue = (await repo.count_and_revenue_by_creator())[creator.id]

    assert after_count - baseline_count == 2
    assert after_revenue - baseline_revenue == Decimal("1750.50")


async def test_count_and_revenue_by_creator_excludes_null_created_by(db_session):
    repo = VisitRepository(db_session)
    patient = await _make_patient(db_session)
    doctor = await _make_doctor(db_session)
    visit = Visit(
        patient_id=patient.id,
        doctor_user_id=doctor.id,
        queue_token=_unique_token(),
        procedure="Consultation",
        amount=Decimal("1500.00"),
        vitals_required=True,
        status=VisitStatus.REGISTERED,
        created_by=None,
    )
    await repo.add(visit)

    stats = await repo.count_and_revenue_by_creator()

    assert None not in stats


async def test_search_filters_by_created_by(db_session):
    patient = await _make_patient(db_session)
    doctor = await _make_doctor(db_session)
    creator_a = await _make_doctor(db_session)
    creator_b = await _make_doctor(db_session)
    target = Visit(
        patient_id=patient.id,
        doctor_user_id=doctor.id,
        queue_token=_unique_token(),
        procedure="Consultation",
        amount=Decimal("1500.00"),
        vitals_required=True,
        status=VisitStatus.REGISTERED,
        created_by=creator_a.id,
    )
    await VisitRepository(db_session).add(target)
    other = Visit(
        patient_id=patient.id,
        doctor_user_id=doctor.id,
        queue_token=_unique_token(),
        procedure="Consultation",
        amount=Decimal("1500.00"),
        vitals_required=True,
        status=VisitStatus.REGISTERED,
        created_by=creator_b.id,
    )
    await VisitRepository(db_session).add(other)

    visits, total = await VisitRepository(db_session).search(
        patient_id=None,
        doctor_user_id=None,
        created_by=creator_a.id,
        status=None,
        sort_column=VISIT_SORTABLE_COLUMNS["created_at"],
        sort_desc=True,
        limit=20,
        offset=0,
    )

    assert total == 1
    assert visits[0].id == target.id


async def test_search_filters_by_created_by_has_no_date_restriction(db_session):
    """The exact property Reception's "My Registrations" now depends on
    — a creator's visit from any point in time is included, not just
    "today"."""
    patient = await _make_patient(db_session)
    doctor = await _make_doctor(db_session)
    creator = await _make_doctor(db_session)
    old_visit = Visit(
        patient_id=patient.id,
        doctor_user_id=doctor.id,
        queue_token=_unique_token(),
        procedure="Consultation",
        amount=Decimal("1500.00"),
        vitals_required=True,
        status=VisitStatus.REGISTERED,
        created_by=creator.id,
        created_at=datetime(2020, 1, 1, tzinfo=UTC),
    )
    await VisitRepository(db_session).add(old_visit)

    visits, total = await VisitRepository(db_session).search(
        patient_id=None,
        doctor_user_id=None,
        created_by=creator.id,
        status=None,
        sort_column=VISIT_SORTABLE_COLUMNS["created_at"],
        sort_desc=True,
        limit=20,
        offset=0,
    )

    assert total == 1
    assert visits[0].id == old_visit.id


async def test_search_filters_by_date(db_session):
    patient = await _make_patient(db_session)
    doctor = await _make_doctor(db_session)
    in_range = Visit(
        patient_id=patient.id,
        doctor_user_id=doctor.id,
        queue_token=_unique_token(),
        procedure="Consultation",
        amount=Decimal("1500.00"),
        vitals_required=True,
        status=VisitStatus.REGISTERED,
        created_at=datetime(2026, 3, 15, 10, 0, tzinfo=UTC),
    )
    await VisitRepository(db_session).add(in_range)
    day_before = Visit(
        patient_id=patient.id,
        doctor_user_id=doctor.id,
        queue_token=_unique_token(),
        procedure="Consultation",
        amount=Decimal("1500.00"),
        vitals_required=True,
        status=VisitStatus.REGISTERED,
        created_at=datetime(2026, 3, 14, 23, 59, tzinfo=UTC),
    )
    await VisitRepository(db_session).add(day_before)
    day_after = Visit(
        patient_id=patient.id,
        doctor_user_id=doctor.id,
        queue_token=_unique_token(),
        procedure="Consultation",
        amount=Decimal("1500.00"),
        vitals_required=True,
        status=VisitStatus.REGISTERED,
        created_at=datetime(2026, 3, 16, 0, 0, tzinfo=UTC),
    )
    await VisitRepository(db_session).add(day_after)

    from datetime import date as date_type

    visits, total = await VisitRepository(db_session).search(
        patient_id=None,
        doctor_user_id=None,
        date=date_type(2026, 3, 15),
        status=None,
        sort_column=VISIT_SORTABLE_COLUMNS["created_at"],
        sort_desc=True,
        limit=20,
        offset=0,
    )

    assert total == 1
    assert visits[0].id == in_range.id


async def test_search_filters_by_patient_ids(db_session):
    """Backs the Patient History list's own search-by-name/MR/phone —
    a plain `IN` filter against Visit's own `patient_id` column, the
    id list itself always resolved by the caller (see this method's
    own docstring on why the Visits module never joins Patient
    directly)."""
    matching_patient = await _make_patient(db_session)
    other_patient = await _make_patient(db_session)
    doctor = await _make_doctor(db_session)
    target = await _make_visit(db_session, patient=matching_patient, doctor=doctor)
    await _make_visit(db_session, patient=other_patient, doctor=doctor)

    visits, total = await VisitRepository(db_session).search(
        patient_id=None,
        doctor_user_id=None,
        patient_ids=[matching_patient.id],
        status=None,
        sort_column=VISIT_SORTABLE_COLUMNS["created_at"],
        sort_desc=True,
        limit=20,
        offset=0,
    )

    assert total == 1
    assert visits[0].id == target.id


async def test_search_filters_by_patient_ids_empty_list_matches_nothing(db_session):
    """An empty `patient_ids` list (as opposed to `None`, meaning "no
    filter at all") is a real, deliberate "match zero patients" case —
    e.g. a Patient History search term that matched no one — and must
    correctly yield zero visits via `IN ()`, not silently fall back to
    every visit."""
    patient = await _make_patient(db_session)
    doctor = await _make_doctor(db_session)
    await _make_visit(db_session, patient=patient, doctor=doctor)

    visits, total = await VisitRepository(db_session).search(
        patient_id=None,
        doctor_user_id=None,
        patient_ids=[],
        status=None,
        sort_column=VISIT_SORTABLE_COLUMNS["created_at"],
        sort_desc=True,
        limit=20,
        offset=0,
    )

    assert total == 0
    assert visits == []


async def test_search_filters_by_date_range(db_session):
    """`start_date`/`end_date` — the Patient History list's own
    From/To filter — is an inclusive UTC calendar-day range independent
    of the existing single-day `date` filter above, mirroring
    InventoryReceiptRepository's identical naming/semantics."""
    patient = await _make_patient(db_session)
    doctor = await _make_doctor(db_session)
    in_range = Visit(
        patient_id=patient.id,
        doctor_user_id=doctor.id,
        queue_token=_unique_token(),
        procedure="Consultation",
        amount=Decimal("1500.00"),
        vitals_required=True,
        status=VisitStatus.REGISTERED,
        created_at=datetime(2026, 3, 15, 10, 0, tzinfo=UTC),
    )
    await VisitRepository(db_session).add(in_range)
    range_start_boundary = Visit(
        patient_id=patient.id,
        doctor_user_id=doctor.id,
        queue_token=_unique_token(),
        procedure="Consultation",
        amount=Decimal("1500.00"),
        vitals_required=True,
        status=VisitStatus.REGISTERED,
        created_at=datetime(2026, 3, 14, 0, 0, tzinfo=UTC),
    )
    await VisitRepository(db_session).add(range_start_boundary)
    before_range = Visit(
        patient_id=patient.id,
        doctor_user_id=doctor.id,
        queue_token=_unique_token(),
        procedure="Consultation",
        amount=Decimal("1500.00"),
        vitals_required=True,
        status=VisitStatus.REGISTERED,
        created_at=datetime(2026, 3, 13, 23, 59, tzinfo=UTC),
    )
    await VisitRepository(db_session).add(before_range)
    after_range = Visit(
        patient_id=patient.id,
        doctor_user_id=doctor.id,
        queue_token=_unique_token(),
        procedure="Consultation",
        amount=Decimal("1500.00"),
        vitals_required=True,
        status=VisitStatus.REGISTERED,
        created_at=datetime(2026, 3, 16, 0, 0, tzinfo=UTC),
    )
    await VisitRepository(db_session).add(after_range)

    from datetime import date as date_type

    visits, total = await VisitRepository(db_session).search(
        patient_id=None,
        doctor_user_id=None,
        start_date=date_type(2026, 3, 14),
        end_date=date_type(2026, 3, 15),
        status=None,
        sort_column=VISIT_SORTABLE_COLUMNS["created_at"],
        sort_desc=True,
        limit=20,
        offset=0,
    )

    assert total == 2
    assert {visit.id for visit in visits} == {in_range.id, range_start_boundary.id}


async def test_search_excludes_soft_deleted_visits(db_session):
    patient = await _make_patient(db_session)
    doctor = await _make_doctor(db_session)
    visit = await _make_visit(db_session, patient=patient, doctor=doctor)
    repo = VisitRepository(db_session)
    await repo.soft_delete(visit, deleted_at=datetime.now(UTC))

    visits, total = await repo.search(
        patient_id=patient.id,
        doctor_user_id=None,
        status=None,
        sort_column=VISIT_SORTABLE_COLUMNS["created_at"],
        sort_desc=True,
        limit=20,
        offset=0,
    )

    assert total == 0
    assert visits == []
