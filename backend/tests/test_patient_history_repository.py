"""Repository-level tests for the Patient History unified feed
(`PatientHistoryRepository.search_feed`) — see that module's own
docstring for why a single query is allowed to span Visit/MedicineBill/
LabBill here. Uses `db_session` (transaction-rollback isolated) so
every test gets exact, deterministic control over `created_at`, the
same pattern tests/test_visits_repository.py's own date-range tests
already establish — genuinely necessary here, since the "highest-risk
part" (pagination correctness across a UNION) is meaningless without
precise, known ordering."""

import secrets
from datetime import UTC, datetime
from decimal import Decimal

from uuid6 import uuid7

from app.modules.auth.models import User, UserStatus
from app.modules.auth.repository import UserRepository
from app.modules.lab.models import LabBill
from app.modules.lab.repository import LabBillRepository
from app.modules.patient_history.repository import PatientHistoryRepository
from app.modules.patients.models import Patient, PatientGender
from app.modules.patients.repository import PatientRepository
from app.modules.pharmacy.models import MedicineBill
from app.modules.pharmacy.repository import MedicineBillRepository
from app.modules.visits.models import Visit, VisitStatus
from app.modules.visits.repository import VisitRepository
from tests.conftest import make_test_email


def _unique_token(n: int) -> str:
    return f"Token #{n:06d}"


def _random_token_marker() -> str:
    """A 6-digit numeric marker used both as (part of) a token string
    and as the `token_search` filter matched against it — this dev
    database is shared and heavily used (thousands of pre-existing,
    real Visit/MedicineBill/LabBill rows from unrelated manual testing
    this session), so a short/predictable substring like "900" risks
    colliding with a real, already-existing token elsewhere and
    silently inflating a test's expected count. A random 6-digit
    marker, matched in full, makes an accidental collision
    astronomically unlikely without needing any actual DB-wide
    cleanup — the same reasoning `test_search_filters_by_status` in
    tests/test_visits_repository.py's own known pre-existing flakiness
    already illustrates for an *unscoped* query against this database."""
    return f"{secrets.randbelow(900_000) + 100_000:06d}"


async def _make_patient(db_session) -> Patient:
    return await PatientRepository(db_session).add(
        Patient(
            mr_number=f"MR-{uuid7().hex[-8:]}",
            full_name=f"History Repo Patient {uuid7()}",
            gender=PatientGender.FEMALE,
            age_years=30,
            phone_number="03001234567",
        )
    )


async def _make_doctor(db_session) -> User:
    return await UserRepository(db_session).add(
        User(
            email=make_test_email(f"history-repo-doctor-{uuid7().hex[-6:]}"),
            password_hash="hash",
            full_name="History Repo Doctor",
            status=UserStatus.ACTIVE,
        )
    )


async def _make_visit(
    db_session, *, patient: Patient, doctor: User, token: str, created_at: datetime
) -> Visit:
    visit = Visit(
        patient_id=patient.id,
        doctor_user_id=doctor.id,
        queue_token=token,
        procedure="Consultation",
        amount=Decimal("1500.00"),
        vitals_required=True,
        status=VisitStatus.REGISTERED,
        created_at=created_at,
    )
    return await VisitRepository(db_session).add(visit)


async def _make_medicine_bill(
    db_session,
    *,
    token: str,
    created_at: datetime,
    visit_id=None,
    manual_patient_name: str | None = None,
) -> MedicineBill:
    bill = MedicineBill(
        visit_id=visit_id,
        queue_token=token,
        total_amount=Decimal("300.00"),
        manual_patient_name=manual_patient_name,
        manual_patient_age=40 if manual_patient_name else None,
        manual_patient_phone="03001234567" if manual_patient_name else None,
        created_at=created_at,
    )
    return await MedicineBillRepository(db_session).add(bill)


async def _make_lab_bill(
    db_session,
    *,
    token: str,
    created_at: datetime,
    patient_id=None,
    manual_patient_name: str | None = None,
) -> LabBill:
    bill = LabBill(
        patient_id=patient_id,
        queue_token=token,
        total_amount=Decimal("800.00"),
        manual_patient_name=manual_patient_name,
        manual_patient_age=40 if manual_patient_name else None,
        manual_patient_phone="03001234567" if manual_patient_name else None,
        created_at=created_at,
    )
    return await LabBillRepository(db_session).add(bill)


async def test_search_feed_interleaves_all_three_types_by_created_at(db_session):
    """The core "no token number missing" guarantee — a Visit, a
    MedicineBill, and a LabBill created moments apart come back in one
    genuinely interleaved list, newest first, not three separate
    blocks."""
    patient = await _make_patient(db_session)
    doctor = await _make_doctor(db_session)
    base = datetime(2026, 6, 1, 10, 0, 0, tzinfo=UTC)

    visit = await _make_visit(
        db_session, patient=patient, doctor=doctor, token=_unique_token(1), created_at=base
    )
    medicine_bill = await _make_medicine_bill(
        db_session, token=_unique_token(2), created_at=base.replace(minute=1), visit_id=visit.id
    )
    lab_bill = await _make_lab_bill(
        db_session, token=_unique_token(3), created_at=base.replace(minute=2), patient_id=patient.id
    )

    repo = PatientHistoryRepository(db_session)
    rows, total = await repo.search_feed(
        patient_ids=[patient.id],
        token_search=None,
        start_date=None,
        end_date=None,
        include_visits=True,
        include_medicine_bills=True,
        include_lab_bills=True,
        limit=20,
        offset=0,
    )

    assert total == 3
    # Newest first: lab_bill (minute=2), medicine_bill (minute=1), visit (minute=0).
    assert [row.id for row in rows] == [lab_bill.id, medicine_bill.id, visit.id]
    assert [row.record_type for row in rows] == ["lab_bill", "medicine_bill", "visit"]


async def test_search_feed_token_search_finds_row_in_each_table(db_session):
    """A single token substring search matches whichever table that
    Token # actually lives in — Visit, MedicineBill, or LabBill — not
    just Visit."""
    patient = await _make_patient(db_session)
    doctor = await _make_doctor(db_session)
    base = datetime(2026, 6, 2, 10, 0, 0, tzinfo=UTC)

    visit = await _make_visit(
        db_session, patient=patient, doctor=doctor, token="Token #000801", created_at=base
    )
    medicine_bill = await _make_medicine_bill(
        db_session, token="Token #000802", created_at=base.replace(minute=1)
    )
    lab_bill = await _make_lab_bill(
        db_session, token="Token #000803", created_at=base.replace(minute=2)
    )

    repo = PatientHistoryRepository(db_session)

    for token, expected_id, expected_type in (
        ("801", visit.id, "visit"),
        ("802", medicine_bill.id, "medicine_bill"),
        ("803", lab_bill.id, "lab_bill"),
    ):
        rows, total = await repo.search_feed(
            patient_ids=None,
            token_search=token,
            start_date=None,
            end_date=None,
            include_visits=True,
            include_medicine_bills=True,
            include_lab_bills=True,
            limit=20,
            offset=0,
        )
        assert total == 1, f"token {token!r} matched {total} rows, expected 1"
        assert rows[0].id == expected_id
        assert rows[0].record_type == expected_type


async def test_search_feed_standalone_medicine_bill_has_null_patient_id(db_session):
    """The exact real-world shape confirmed against production Token
    #802 — a standalone medicine bill (no visit_id, no manual fields)
    still appears in the feed, with `patient_id` correctly `None`
    (never silently dropped, never a broken join)."""
    marker = _random_token_marker()
    bill = await _make_medicine_bill(
        db_session, token=f"Token #{marker}", created_at=datetime(2026, 6, 3, tzinfo=UTC)
    )

    repo = PatientHistoryRepository(db_session)
    rows, total = await repo.search_feed(
        patient_ids=None,
        token_search=marker,
        start_date=None,
        end_date=None,
        include_visits=True,
        include_medicine_bills=True,
        include_lab_bills=True,
        limit=20,
        offset=0,
    )

    assert total == 1
    assert rows[0].id == bill.id
    assert rows[0].patient_id is None


async def test_search_feed_medicine_bill_resolves_patient_via_visit_join(db_session):
    """A medicine bill linked to a Visit resolves `patient_id` through
    that Visit — MedicineBill has no `patient_id` column of its own."""
    patient = await _make_patient(db_session)
    doctor = await _make_doctor(db_session)
    visit = await _make_visit(
        db_session,
        patient=patient,
        doctor=doctor,
        token="Token #000910",
        created_at=datetime(2026, 6, 4, tzinfo=UTC),
    )
    bill = await _make_medicine_bill(
        db_session,
        token="Token #000911",
        created_at=datetime(2026, 6, 4, 0, 1, tzinfo=UTC),
        visit_id=visit.id,
    )

    repo = PatientHistoryRepository(db_session)
    rows, _total = await repo.search_feed(
        patient_ids=None,
        token_search="911",
        start_date=None,
        end_date=None,
        include_visits=True,
        include_medicine_bills=True,
        include_lab_bills=True,
        limit=20,
        offset=0,
    )

    assert len(rows) == 1
    assert rows[0].id == bill.id
    assert rows[0].patient_id == patient.id


async def test_search_feed_patient_ids_empty_list_still_allows_token_match(db_session):
    """`patient_ids=[]` (a search term matched zero patients) must not
    suppress an independent token match combined via OR — the whole
    point of a single search box serving both purposes at once."""
    bill = await _make_medicine_bill(
        db_session, token="Token #000920", created_at=datetime(2026, 6, 5, tzinfo=UTC)
    )

    repo = PatientHistoryRepository(db_session)
    rows, total = await repo.search_feed(
        patient_ids=[],  # a name search that matched nobody
        token_search="920",
        start_date=None,
        end_date=None,
        include_visits=True,
        include_medicine_bills=True,
        include_lab_bills=True,
        limit=20,
        offset=0,
    )

    assert total == 1
    assert rows[0].id == bill.id


async def test_search_feed_respects_include_flags_per_record_type(db_session):
    """The router's own per-actor permission decision (visits:read/
    pharmacy:read/lab:read) is what `include_visits`/
    `include_medicine_bills`/`include_lab_bills` encode — a branch the
    actor can't see is dropped entirely, not fetched-then-filtered."""
    patient = await _make_patient(db_session)
    doctor = await _make_doctor(db_session)
    base = datetime(2026, 6, 6, tzinfo=UTC)
    marker = _random_token_marker()
    await _make_visit(db_session, patient=patient, doctor=doctor, token=f"Token #{marker}", created_at=base)
    await _make_medicine_bill(db_session, token=f"Token #{marker}", created_at=base.replace(minute=1))
    await _make_lab_bill(db_session, token=f"Token #{marker}", created_at=base.replace(minute=2))

    repo = PatientHistoryRepository(db_session)

    # Scoped down to just this test's 3 rows via the shared random
    # marker (see _random_token_marker's own docstring on why an
    # unscoped query can't get an exact count against this shared,
    # heavily-used dev database) — the `include_*` flags are what's
    # actually under test here, layered on top of that scoping.
    visits_only, total = await repo.search_feed(
        patient_ids=None, token_search=marker, start_date=None, end_date=None,
        include_visits=True, include_medicine_bills=False, include_lab_bills=False,
        limit=20, offset=0,
    )
    assert total == 1
    assert visits_only[0].record_type == "visit"

    all_three, total_all = await repo.search_feed(
        patient_ids=None, token_search=marker, start_date=None, end_date=None,
        include_visits=True, include_medicine_bills=True, include_lab_bills=True,
        limit=20, offset=0,
    )
    assert total_all == 3
    assert {row.record_type for row in all_three} == {"visit", "medicine_bill", "lab_bill"}

    none_included, total_none = await repo.search_feed(
        patient_ids=None, token_search=marker, start_date=None, end_date=None,
        include_visits=False, include_medicine_bills=False, include_lab_bills=False,
        limit=20, offset=0,
    )
    assert total_none == 0
    assert none_included == []


async def test_search_feed_excludes_soft_deleted_rows(db_session):
    patient = await _make_patient(db_session)
    doctor = await _make_doctor(db_session)
    marker = _random_token_marker()
    visit = await _make_visit(
        db_session, patient=patient, doctor=doctor, token=f"Token #{marker}",
        created_at=datetime(2026, 6, 7, tzinfo=UTC),
    )
    await VisitRepository(db_session).soft_delete(visit, deleted_at=datetime.now(UTC))

    repo = PatientHistoryRepository(db_session)
    rows, total = await repo.search_feed(
        patient_ids=None, token_search=marker, start_date=None, end_date=None,
        include_visits=True, include_medicine_bills=True, include_lab_bills=True,
        limit=20, offset=0,
    )

    assert total == 0
    assert rows == []


async def test_search_feed_pagination_correctness_across_union(db_session):
    """The highest-risk part: 25 rows spread across all three tables,
    fetched 10-at-a-time across 3 pages — every id must appear exactly
    once, in the correct newest-first order, with no row skipped or
    duplicated at a page boundary. A `fetch each table's own page then
    merge` shortcut would fail this exact test (each table's own page
    boundary doesn't align with the true merged order); only a real
    `ORDER BY ... LIMIT/OFFSET` over the whole `UNION ALL` can pass it."""
    patient = await _make_patient(db_session)
    doctor = await _make_doctor(db_session)
    base = datetime(2026, 6, 10, 0, 0, 0, tzinfo=UTC)

    # Every one of the 25 rows below resolves to this same patient
    # (Visit/LabBill directly, MedicineBill via whichever Visit content
    # row was created first — `i=0` is always a visit, per `i % 3`, so
    # it exists before any medicine_bill row needs it) — filtering by
    # `patient_ids=[patient.id]` (exact equality, not a substring
    # match) is what actually isolates this test's 25 rows from the
    # thousands of unrelated real rows already in this shared dev
    # database, with zero collision risk — see `_random_token_marker`'s
    # own docstring for why a token-ILIKE substring alone isn't
    # reliable enough for a set this size.
    first_visit_id = None
    expected_ids_newest_first = []
    for i in range(25):
        created_at = base.replace(minute=i)
        token = _unique_token(1000 + i)
        record_type = i % 3
        if record_type == 0:
            row = await _make_visit(
                db_session, patient=patient, doctor=doctor, token=token, created_at=created_at
            )
            if first_visit_id is None:
                first_visit_id = row.id
        elif record_type == 1:
            row = await _make_medicine_bill(
                db_session, token=token, created_at=created_at, visit_id=first_visit_id
            )
        else:
            row = await _make_lab_bill(
                db_session, token=token, created_at=created_at, patient_id=patient.id
            )
        expected_ids_newest_first.append(row.id)
    expected_ids_newest_first.reverse()  # minute=24 is newest

    repo = PatientHistoryRepository(db_session)
    collected_ids = []
    page_size = 10
    for page_offset in (0, 10, 20):
        rows, total = await repo.search_feed(
            patient_ids=[patient.id], token_search=None, start_date=None, end_date=None,
            include_visits=True, include_medicine_bills=True, include_lab_bills=True,
            limit=page_size, offset=page_offset,
        )
        assert total == 25
        collected_ids.extend(row.id for row in rows)

    # Page sizes: 10 + 10 + 5 = 25, exactly the full set once each.
    assert len(collected_ids) == 25
    assert len(set(collected_ids)) == 25, "a row was duplicated across pages"
    assert collected_ids == expected_ids_newest_first, "merged page order does not match true sort order"
