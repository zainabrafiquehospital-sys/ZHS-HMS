from datetime import UTC, datetime

from uuid6 import uuid7

from app.modules.patients.models import Patient, PatientGender
from app.modules.patients.repository import PATIENT_SORTABLE_COLUMNS, PatientRepository


def _unique_mr_number() -> str:
    """uuid7's *leading* hex characters are a millisecond timestamp, not
    random data — truncating there (e.g. `.hex[:6]`) produces near-
    identical prefixes for values generated milliseconds apart, which is
    exactly what these tests do. The *trailing* characters come from
    uuid7's random tail (`rand_b`), which is what actually needs to be
    unique here."""
    return f"MR-{uuid7().hex[-8:]}"


async def _make_patient(
    db_session,
    *,
    mr_number: str | None = None,
    full_name: str | None = None,
    phone_number: str = "03001234567",
    cnic: str | None = None,
) -> Patient:
    patient = Patient(
        mr_number=mr_number or _unique_mr_number(),
        full_name=full_name or f"Patient {uuid7()}",
        gender=PatientGender.FEMALE,
        age_years=30,
        phone_number=phone_number,
        cnic=cnic,
    )
    return await PatientRepository(db_session).add(patient)


async def test_next_mr_number_value_increments(db_session):
    repo = PatientRepository(db_session)
    first = await repo.next_mr_number_value()
    second = await repo.next_mr_number_value()
    assert second == first + 1


async def test_get_by_mr_number_finds_active_patient(db_session):
    patient = await _make_patient(db_session, mr_number=f"MR-lookup-{uuid7().hex[:6]}")

    found = await PatientRepository(db_session).get_by_mr_number(patient.mr_number)

    assert found is not None
    assert found.id == patient.id


async def test_get_by_mr_number_returns_none_when_missing(db_session):
    assert await PatientRepository(db_session).get_by_mr_number("MR-does-not-exist") is None


async def test_get_by_cnic_finds_active_patient(db_session):
    cnic = f"cnic-{uuid7().hex[:10]}"
    patient = await _make_patient(db_session, cnic=cnic)

    found = await PatientRepository(db_session).get_by_cnic(cnic)

    assert found is not None
    assert found.id == patient.id


async def test_search_filters_by_text_across_name_mr_phone_cnic(db_session):
    repo = PatientRepository(db_session)
    unique = f"zebra-search-{uuid7().hex[:8]}"
    target = await _make_patient(db_session, full_name=unique)
    await _make_patient(db_session, full_name="unrelated patient")

    patients, total = await repo.search(
        search=unique,
        sort_column=PATIENT_SORTABLE_COLUMNS["created_at"],
        sort_desc=True,
        limit=20,
        offset=0,
    )

    assert total == 1
    assert patients[0].id == target.id


async def test_search_excludes_soft_deleted_patients(db_session):
    repo = PatientRepository(db_session)
    unique = f"soft-deleted-{uuid7().hex[:8]}"
    patient = await _make_patient(db_session, full_name=unique)
    await repo.soft_delete(patient, deleted_at=datetime.now(UTC))

    patients, total = await repo.search(
        search=unique,
        sort_column=PATIENT_SORTABLE_COLUMNS["created_at"],
        sort_desc=True,
        limit=20,
        offset=0,
    )

    assert total == 0
    assert patients == []


async def test_search_sorts_and_paginates(db_session):
    repo = PatientRepository(db_session)
    unique = str(uuid7())[:8]
    await _make_patient(db_session, full_name=f"patient-a-{unique}")
    await _make_patient(db_session, full_name=f"patient-b-{unique}")
    await _make_patient(db_session, full_name=f"patient-c-{unique}")

    first_page, total = await repo.search(
        search=unique,
        sort_column=PATIENT_SORTABLE_COLUMNS["full_name"],
        sort_desc=False,
        limit=2,
        offset=0,
    )
    second_page, _ = await repo.search(
        search=unique,
        sort_column=PATIENT_SORTABLE_COLUMNS["full_name"],
        sort_desc=False,
        limit=2,
        offset=2,
    )

    assert total == 3
    assert [p.full_name for p in first_page] == [f"patient-a-{unique}", f"patient-b-{unique}"]
    assert [p.full_name for p in second_page] == [f"patient-c-{unique}"]
