from decimal import Decimal

from uuid6 import uuid7

from app.modules.auth.models import User, UserStatus
from app.modules.auth.repository import UserRepository
from app.modules.patients.models import PatientGender
from app.modules.search.service import SearchService
from tests.conftest import TEST_PATIENT_NAME_PREFIX, make_test_email


async def _make_actor(real_session, suffix: str) -> User:
    actor = await UserRepository(real_session).add(
        User(
            email=make_test_email(f"search-actor-{suffix}"),
            password_hash="hash",
            full_name="Search Test Actor",
            status=UserStatus.ACTIVE,
        )
    )
    await real_session.commit()
    return actor


async def test_search_by_patient_name(real_session, patient_service, visit_service):
    actor = await _make_actor(real_session, "by-name")
    unique_name = f"{TEST_PATIENT_NAME_PREFIX}SearchByName{uuid7().hex[:8]}"
    patient = await patient_service.register_patient(
        actor=actor,
        full_name=unique_name,
        guardian_name=None,
        gender=PatientGender.FEMALE,
        age_years=25,
        phone_number="03001234567",
        cnic=None,
        address=None,
    )
    search_service = SearchService(patient_service=patient_service, visit_service=visit_service)

    patients, visit = await search_service.search(unique_name)

    assert [p.id for p in patients] == [patient.id]
    assert visit is None


async def test_search_by_mr_number(real_session, patient_service, visit_service):
    actor = await _make_actor(real_session, "by-mr")
    patient = await patient_service.register_patient(
        actor=actor,
        full_name=f"{TEST_PATIENT_NAME_PREFIX}SearchByMr",
        guardian_name=None,
        gender=PatientGender.FEMALE,
        age_years=25,
        phone_number="03001234567",
        cnic=None,
        address=None,
    )
    search_service = SearchService(patient_service=patient_service, visit_service=visit_service)

    patients, _visit = await search_service.search(patient.mr_number)

    assert [p.id for p in patients] == [patient.id]


async def test_search_by_queue_token_finds_visit(real_session, patient_service, visit_service):
    actor = await _make_actor(real_session, "by-token")
    patient = await patient_service.register_patient(
        actor=actor,
        full_name=f"{TEST_PATIENT_NAME_PREFIX}SearchByToken",
        guardian_name=None,
        gender=PatientGender.FEMALE,
        age_years=25,
        phone_number="03001234567",
        cnic=None,
        address=None,
    )
    visit = await visit_service.register_visit(
        actor=actor,
        patient_id=patient.id,
        doctor_user_id=actor.id,
        procedures=[(None, "Consultation", Decimal("1500.00"))],
        vitals_required=False,
    )
    search_service = SearchService(patient_service=patient_service, visit_service=visit_service)

    _patients, found_visit = await search_service.search(visit.queue_token)

    assert found_visit is not None
    assert found_visit.id == visit.id


async def test_search_by_visit_id_finds_visit(real_session, patient_service, visit_service):
    actor = await _make_actor(real_session, "by-visit-id")
    patient = await patient_service.register_patient(
        actor=actor,
        full_name=f"{TEST_PATIENT_NAME_PREFIX}SearchByVisitId",
        guardian_name=None,
        gender=PatientGender.FEMALE,
        age_years=25,
        phone_number="03001234567",
        cnic=None,
        address=None,
    )
    visit = await visit_service.register_visit(
        actor=actor,
        patient_id=patient.id,
        doctor_user_id=actor.id,
        procedures=[(None, "Consultation", Decimal("1500.00"))],
        vitals_required=False,
    )
    search_service = SearchService(patient_service=patient_service, visit_service=visit_service)

    _patients, found_visit = await search_service.search(str(visit.id))

    assert found_visit is not None
    assert found_visit.id == visit.id


async def test_search_no_match_returns_empty(patient_service, visit_service):
    search_service = SearchService(patient_service=patient_service, visit_service=visit_service)

    patients, visit = await search_service.search("no-such-query-will-ever-match-zz")

    assert patients == []
    assert visit is None


async def test_search_malformed_uuid_does_not_raise(patient_service, visit_service):
    """A search query that looks nothing like a UUID must fail closed
    (no match), not raise — users type free text, not always valid
    UUIDs."""
    search_service = SearchService(patient_service=patient_service, visit_service=visit_service)

    patients, visit = await search_service.search("not-a-uuid-at-all")

    assert patients == []
    assert visit is None
