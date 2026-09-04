"""Full end-to-end HTTP tests for the Consultation module — see
tests/test_patients_endpoints.py's identical module docstring."""

from decimal import Decimal

from app.modules.auth.models import User, UserStatus
from app.modules.auth.password_service import PasswordService
from app.modules.auth.repository import UserRepository
from app.modules.consultation.constants import (
    PERMISSION_CONSULTATION_MANAGE,
    PERMISSION_CONSULTATION_READ,
    PERMISSION_CONSULTATION_START,
)
from app.modules.patients.models import PatientGender
from app.shared.payment_method import PaymentMethod
from tests.conftest import TEST_PATIENT_NAME_PREFIX, make_test_email

_PASSWORD = "Str0ng!Passw0rd#2026"


async def _create_and_login(api_client, real_session, suffix: str) -> tuple[User, str]:
    password_hash = await PasswordService().hash(_PASSWORD)
    email = make_test_email(suffix)
    user = await UserRepository(real_session).add(
        User(
            email=email,
            password_hash=password_hash,
            full_name="Consultation Endpoint Actor",
            status=UserStatus.ACTIVE,
            # See tests/test_user_endpoints.py's _create_and_login for
            # why this must be explicit (must_change_password
            # enforcement, 2026-08-19 audit fix pass).
            must_change_password=False,
        )
    )
    await real_session.commit()
    login_resp = await api_client.post(
        "/api/v1/auth/login", json={"email": email, "password": _PASSWORD}
    )
    access_token = login_resp.json()["data"]["access_token"]
    return user, access_token


def _auth_header(access_token: str) -> dict:
    return {"Authorization": f"Bearer {access_token}"}


async def _make_visit(reception_service, doctor, suffix: str, *, assign_to_doctor: bool = True):
    """Goes through ReceptionService — see
    tests/test_consultation_service.py's identical helper docstring for
    why VisitService.register_visit alone is not enough (no QueueEntry
    would ever be created).

    `assign_to_doctor=False` (2026-08-24 addition) leaves the Visit
    unassigned instead of pre-assigning it to `doctor` — for tests that
    deliberately exercise a doctor who does *not* hold
    `consultation:start` (e.g. test_start_consultation_without_permission_
    is_forbidden): explicit assignment is now validated server-side
    (ReceptionRepository.get_doctor_by_id) and rejects exactly such a
    doctor, which is correct for real registration but wrong for this
    kind of test, whose actual assertion is about the HTTP-layer
    permission check on `POST /consultations`, not about registration."""
    _patient, visit, _entry = await reception_service.register_visit(
        actor=doctor,
        patient_id=None,
        new_patient={
            "full_name": f"{TEST_PATIENT_NAME_PREFIX}ConsultationHttp{suffix}",
            "guardian_name": None,
            "gender": PatientGender.FEMALE,
            "age_years": 33,
            "phone_number": "03001234567",
            "cnic": None,
            "address": None,
        },
        doctor_user_id=doctor.id if assign_to_doctor else None,
        procedures=[(None, "Consultation", Decimal("1500.00"))],
        vitals_required=False,
        initial_payment_amount=Decimal("0.01"),
        initial_payment_method=PaymentMethod.CASH,
    )
    return visit


async def test_start_consultation_requires_authentication(api_client):
    resp = await api_client.post("/api/v1/consultations", json={"visit_id": None})
    assert resp.status_code in (401, 422)


async def test_start_consultation_without_permission_is_forbidden(
    api_client, real_session, reception_service
):
    doctor, access_token = await _create_and_login(api_client, real_session, "no-perm-start")
    visit = await _make_visit(reception_service, doctor, "A", assign_to_doctor=False)

    resp = await api_client.post(
        "/api/v1/consultations",
        json={"visit_id": str(visit.id)},
        headers=_auth_header(access_token),
    )

    assert resp.status_code == 403


async def test_full_consultation_lifecycle_via_http(
    api_client, real_session, grant_permission, reception_service
):
    doctor, access_token = await _create_and_login(api_client, real_session, "full-lifecycle")
    await grant_permission(doctor, PERMISSION_CONSULTATION_START)
    await grant_permission(doctor, PERMISSION_CONSULTATION_MANAGE)
    await grant_permission(doctor, PERMISSION_CONSULTATION_READ)
    visit = await _make_visit(reception_service, doctor, "Full")

    start_resp = await api_client.post(
        "/api/v1/consultations",
        json={"visit_id": str(visit.id)},
        headers=_auth_header(access_token),
    )
    assert start_resp.status_code == 201
    consultation_id = start_resp.json()["data"]["id"]
    assert start_resp.json()["data"]["status"] == "in_progress"

    send_resp = await api_client.post(
        f"/api/v1/consultations/{consultation_id}/send-to-vitals",
        json={"reason": "BP check"},
        headers=_auth_header(access_token),
    )
    assert send_resp.status_code == 200
    assert send_resp.json()["data"]["status"] == "awaiting_vitals"

    complete_while_awaiting = await api_client.post(
        f"/api/v1/consultations/{consultation_id}/complete",
        json={},
        headers=_auth_header(access_token),
    )
    assert complete_while_awaiting.status_code == 422

    active_resp = await api_client.get(
        f"/api/v1/consultations/visits/{visit.id}/active", headers=_auth_header(access_token)
    )
    assert active_resp.status_code == 200
    assert active_resp.json()["data"]["status"] == "awaiting_vitals"


async def test_get_consultation_stats_by_doctor_requires_permission(api_client, real_session):
    _actor, access_token = await _create_and_login(api_client, real_session, "stats-no-perm")

    resp = await api_client.get(
        "/api/v1/consultations/stats/by-doctor", headers=_auth_header(access_token)
    )

    assert resp.status_code == 403


async def test_get_consultation_stats_by_doctor_returns_accurate_counts(
    api_client, real_session, grant_permission, reception_service
):
    doctor, access_token = await _create_and_login(api_client, real_session, "stats-correctness")
    await grant_permission(doctor, PERMISSION_CONSULTATION_START)
    await grant_permission(doctor, PERMISSION_CONSULTATION_MANAGE)
    await grant_permission(doctor, PERMISSION_CONSULTATION_READ)
    visit = await _make_visit(reception_service, doctor, "StatsCorrectness")
    start_resp = await api_client.post(
        "/api/v1/consultations",
        json={"visit_id": str(visit.id)},
        headers=_auth_header(access_token),
    )
    consultation_id = start_resp.json()["data"]["id"]
    complete_resp = await api_client.post(
        f"/api/v1/consultations/{consultation_id}/complete",
        json={"diagnosis": "Healthy", "prescription": "None"},
        headers=_auth_header(access_token),
    )
    assert complete_resp.status_code == 200

    resp = await api_client.get(
        "/api/v1/consultations/stats/by-doctor", headers=_auth_header(access_token)
    )

    assert resp.status_code == 200
    rows = {row["user_id"]: row["count"] for row in resp.json()["data"]}
    assert rows[str(doctor.id)] == 1


async def test_complete_consultation_success_via_http(
    api_client, real_session, grant_permission, reception_service
):
    doctor, access_token = await _create_and_login(api_client, real_session, "complete-http")
    await grant_permission(doctor, PERMISSION_CONSULTATION_START)
    await grant_permission(doctor, PERMISSION_CONSULTATION_MANAGE)
    visit = await _make_visit(reception_service, doctor, "Complete")
    start_resp = await api_client.post(
        "/api/v1/consultations",
        json={"visit_id": str(visit.id)},
        headers=_auth_header(access_token),
    )
    consultation_id = start_resp.json()["data"]["id"]

    resp = await api_client.post(
        f"/api/v1/consultations/{consultation_id}/complete",
        json={"diagnosis": "Healthy", "prescription": "None"},
        headers=_auth_header(access_token),
    )

    assert resp.status_code == 200
    assert resp.json()["data"]["status"] == "completed"


async def _start_consultation_id(api_client, access_token, visit) -> str:
    start_resp = await api_client.post(
        "/api/v1/consultations",
        json={"visit_id": str(visit.id)},
        headers=_auth_header(access_token),
    )
    assert start_resp.status_code == 201
    return start_resp.json()["data"]["id"]


async def test_print_prescription_slip_requires_consultation_read(
    api_client, real_session, grant_permission, reception_service
):
    doctor, access_token = await _create_and_login(api_client, real_session, "rx-slip-no-perm")
    await grant_permission(doctor, PERMISSION_CONSULTATION_START)
    await grant_permission(doctor, PERMISSION_CONSULTATION_MANAGE)
    # deliberately NOT granting PERMISSION_CONSULTATION_READ
    visit = await _make_visit(reception_service, doctor, "RxSlipNoPerm")
    consultation_id = await _start_consultation_id(api_client, access_token, visit)

    resp = await api_client.get(
        f"/api/v1/consultations/{consultation_id}/slip/print",
        headers=_auth_header(access_token),
    )

    assert resp.status_code == 403


async def test_print_prescription_slip_renders_sections_and_patient(
    api_client, real_session, grant_permission, reception_service
):
    doctor, access_token = await _create_and_login(api_client, real_session, "rx-slip-ok")
    await grant_permission(doctor, PERMISSION_CONSULTATION_START)
    await grant_permission(doctor, PERMISSION_CONSULTATION_MANAGE)
    await grant_permission(doctor, PERMISSION_CONSULTATION_READ)
    visit = await _make_visit(reception_service, doctor, "RxSlipOk")
    consultation_id = await _start_consultation_id(api_client, access_token, visit)

    complete_resp = await api_client.post(
        f"/api/v1/consultations/{consultation_id}/complete",
        json={
            "history_of": "Gravida 2 Para 1",
            "complaint_of": "Lower abdominal pain 3 days",
            "advised": "USG pelvis; review in 1 week",
            "diagnosis": "Threatened miscarriage",
            "prescription": (
                "Tab Folic Acid 5mg OD\n" "Tab Progesterone 200mg BD\n" "Inj Anti-D if indicated"
            ),
        },
        headers=_auth_header(access_token),
    )
    assert complete_resp.status_code == 200
    assert complete_resp.json()["data"]["history_of"] == "Gravida 2 Para 1"
    assert complete_resp.json()["data"]["complaint_of"] == "Lower abdominal pain 3 days"
    assert complete_resp.json()["data"]["advised"] == "USG pelvis; review in 1 week"

    resp = await api_client.get(
        f"/api/v1/consultations/{consultation_id}/slip/print",
        headers=_auth_header(access_token),
    )

    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("text/html")
    body = resp.text

    # Section labels are printed verbatim (never the expansions).
    for label in (">H/O<", ">C/O<", ">Adv<", ">Dx<", 'rx-label">Rx<'):
        assert label in body
    assert "Diagnosis" not in body and "Complaint of" not in body

    # Header identifiers.
    assert visit.queue_token in body
    assert "RxSlipOk" in body  # patient full name contains the suffix
    assert "33 yrs" in body  # _make_visit registers age_years=33

    # Section + Dx content.
    assert "Gravida 2 Para 1" in body
    assert "Lower abdominal pain 3 days" in body
    assert "USG pelvis; review in 1 week" in body
    assert "Threatened miscarriage" in body

    # Rx: one <li> per non-empty prescription line.
    assert body.count("<li>") == 3
    assert "<li>Tab Folic Acid 5mg OD</li>" in body
    assert "<li>Inj Anti-D if indicated</li>" in body

    # This layout overprints pre-printed letterhead — it must NOT draw
    # the hospital identity block every other Central Print document does.
    assert "report-header" not in body
    assert 'class="logo"' not in body


async def test_print_prescription_slip_empty_fields_still_renders_sections(
    api_client, real_session, grant_permission, reception_service
):
    doctor, access_token = await _create_and_login(api_client, real_session, "rx-slip-empty")
    await grant_permission(doctor, PERMISSION_CONSULTATION_START)
    await grant_permission(doctor, PERMISSION_CONSULTATION_MANAGE)
    await grant_permission(doctor, PERMISSION_CONSULTATION_READ)
    visit = await _make_visit(reception_service, doctor, "RxSlipEmpty")
    consultation_id = await _start_consultation_id(api_client, access_token, visit)

    complete_resp = await api_client.post(
        f"/api/v1/consultations/{consultation_id}/complete",
        json={},
        headers=_auth_header(access_token),
    )
    assert complete_resp.status_code == 200

    resp = await api_client.get(
        f"/api/v1/consultations/{consultation_id}/slip/print",
        headers=_auth_header(access_token),
    )

    assert resp.status_code == 200
    body = resp.text
    for label in (">H/O<", ">C/O<", ">Adv<", ">Dx<", 'rx-label">Rx<'):
        assert label in body
    assert "<li>" not in body  # empty Rx -> em-dash placeholder, no list items
    assert "rx-empty" in body


async def _complete_consultation(
    api_client, access_token, reception_service, doctor, suffix, **fields
):
    visit = await _make_visit(reception_service, doctor, suffix)
    consultation_id = await _start_consultation_id(api_client, access_token, visit)
    complete_resp = await api_client.post(
        f"/api/v1/consultations/{consultation_id}/complete",
        json=fields,
        headers=_auth_header(access_token),
    )
    assert complete_resp.status_code == 200, complete_resp.text
    return consultation_id, visit


async def test_list_my_consultations_requires_consultation_read(
    api_client, real_session, grant_permission
):
    actor, access_token = await _create_and_login(api_client, real_session, "mycons-no-perm")
    # no consultation:read granted
    resp = await api_client.get("/api/v1/consultations/mine", headers=_auth_header(access_token))
    assert resp.status_code == 403


async def test_list_my_consultations_returns_only_own(
    api_client, real_session, grant_permission, reception_service
):
    """Doctor A's "My Consultations" must never include Doctor B's,
    even though both completed consultations in the same database — the
    Consultation sibling of test_list_my_vitals_records_returns_only_own_records."""
    doctor_a, token_a = await _create_and_login(api_client, real_session, "mycons-a")
    doctor_b, token_b = await _create_and_login(api_client, real_session, "mycons-b")
    for actor in (doctor_a, doctor_b):
        await grant_permission(actor, PERMISSION_CONSULTATION_START)
        await grant_permission(actor, PERMISSION_CONSULTATION_MANAGE)
        await grant_permission(actor, PERMISSION_CONSULTATION_READ)

    id_a, _ = await _complete_consultation(
        api_client, token_a, reception_service, doctor_a, "MyConsA", diagnosis="A dx"
    )
    id_b, _ = await _complete_consultation(
        api_client, token_b, reception_service, doctor_b, "MyConsB", diagnosis="B dx"
    )

    resp_a = await api_client.get("/api/v1/consultations/mine", headers=_auth_header(token_a))
    assert resp_a.status_code == 200
    ids_a = [row["id"] for row in resp_a.json()["data"]]
    assert id_a in ids_a
    assert id_b not in ids_a

    resp_b = await api_client.get("/api/v1/consultations/mine", headers=_auth_header(token_b))
    assert resp_b.status_code == 200
    ids_b = [row["id"] for row in resp_b.json()["data"]]
    assert id_b in ids_b
    assert id_a not in ids_b


async def test_list_my_consultations_completed_only_newest_first(
    api_client, real_session, grant_permission, reception_service
):
    doctor, access_token = await _create_and_login(api_client, real_session, "mycons-order")
    await grant_permission(doctor, PERMISSION_CONSULTATION_START)
    await grant_permission(doctor, PERMISSION_CONSULTATION_MANAGE)
    await grant_permission(doctor, PERMISSION_CONSULTATION_READ)

    first_id, _ = await _complete_consultation(
        api_client, access_token, reception_service, doctor, "Order1", diagnosis="first"
    )
    second_id, _ = await _complete_consultation(
        api_client, access_token, reception_service, doctor, "Order2", diagnosis="second"
    )

    # A third consultation that is started but NOT completed — must not appear.
    open_visit = await _make_visit(reception_service, doctor, "OrderOpen")
    open_id = await _start_consultation_id(api_client, access_token, open_visit)

    resp = await api_client.get("/api/v1/consultations/mine", headers=_auth_header(access_token))
    assert resp.status_code == 200
    payload = resp.json()
    rows = payload["data"]
    returned_ids = [row["id"] for row in rows]

    assert open_id not in returned_ids  # in-progress is not a browsable record
    assert first_id in returned_ids and second_id in returned_ids
    # Newest completed first.
    assert returned_ids.index(second_id) < returned_ids.index(first_id)
    for row in rows:
        assert row["status"] == "completed"
    assert payload["meta"]["total"] >= 2


async def test_list_my_consultations_pagination(
    api_client, real_session, grant_permission, reception_service
):
    doctor, access_token = await _create_and_login(api_client, real_session, "mycons-page")
    await grant_permission(doctor, PERMISSION_CONSULTATION_START)
    await grant_permission(doctor, PERMISSION_CONSULTATION_MANAGE)
    await grant_permission(doctor, PERMISSION_CONSULTATION_READ)

    completed_ids = []
    for i in range(3):
        cid, _ = await _complete_consultation(
            api_client, access_token, reception_service, doctor, f"Page{i}", diagnosis=f"dx {i}"
        )
        completed_ids.append(cid)

    page1 = await api_client.get(
        "/api/v1/consultations/mine",
        params={"page": 1, "page_size": 1},
        headers=_auth_header(access_token),
    )
    assert page1.status_code == 200
    p1 = page1.json()
    assert len(p1["data"]) == 1
    assert p1["meta"]["total"] >= 3
    assert p1["meta"]["page"] == 1 and p1["meta"]["page_size"] == 1

    page2 = await api_client.get(
        "/api/v1/consultations/mine",
        params={"page": 2, "page_size": 1},
        headers=_auth_header(access_token),
    )
    assert page2.status_code == 200
    p2 = page2.json()
    assert len(p2["data"]) == 1
    assert p2["data"][0]["id"] != p1["data"][0]["id"]


async def test_prescription_slip_reprintable_for_older_completed_consultation(
    api_client, real_session, grant_permission, reception_service
):
    """The slip endpoint reads persisted fields via get_consultation(id) —
    it must work for any completed consultation, not only one 'just
    completed in this session'. Here a second consultation is completed
    after the first, then the FIRST one's slip is re-fetched."""
    doctor, access_token = await _create_and_login(api_client, real_session, "mycons-reprint")
    await grant_permission(doctor, PERMISSION_CONSULTATION_START)
    await grant_permission(doctor, PERMISSION_CONSULTATION_MANAGE)
    await grant_permission(doctor, PERMISSION_CONSULTATION_READ)

    old_id, _ = await _complete_consultation(
        api_client,
        access_token,
        reception_service,
        doctor,
        "Reprint1",
        history_of="Old H/O",
        diagnosis="Old diagnosis",
        prescription="Tab Old 1mg OD",
    )
    # A newer, unrelated completed consultation.
    await _complete_consultation(
        api_client, access_token, reception_service, doctor, "Reprint2", diagnosis="Newer"
    )

    resp = await api_client.get(
        f"/api/v1/consultations/{old_id}/slip/print", headers=_auth_header(access_token)
    )
    assert resp.status_code == 200
    body = resp.text
    assert "Old H/O" in body
    assert "Old diagnosis" in body
    assert "<li>Tab Old 1mg OD</li>" in body


# ---------------------------------------------------------------------
# Post-completion clinical-content correction — PATCH /consultations/{id}
# ---------------------------------------------------------------------


async def test_correct_consultation_requires_consultation_manage(
    api_client, real_session, grant_permission, reception_service
):
    doctor, doctor_token = await _create_and_login(api_client, real_session, "corr-perm-doc")
    for code in (
        PERMISSION_CONSULTATION_START,
        PERMISSION_CONSULTATION_MANAGE,
        PERMISSION_CONSULTATION_READ,
    ):
        await grant_permission(doctor, code)
    consultation_id, _ = await _complete_consultation(
        api_client, doctor_token, reception_service, doctor, "CorrPerm", diagnosis="dx"
    )

    # A different actor holding only consultation:read — no manage.
    _other, other_token = await _create_and_login(api_client, real_session, "corr-perm-reader")
    await grant_permission(_other, PERMISSION_CONSULTATION_READ)

    resp = await api_client.patch(
        f"/api/v1/consultations/{consultation_id}",
        json={"diagnosis": "hijacked"},
        headers=_auth_header(other_token),
    )
    assert resp.status_code == 403


async def test_correct_consultation_ownership_enforced(
    api_client, real_session, grant_permission, reception_service
):
    """Doctor B (who DOES hold consultation:manage) still cannot correct
    Doctor A's consultation — same same-doctor ownership rule
    start/send-to-vitals/complete enforce."""
    doctor_a, token_a = await _create_and_login(api_client, real_session, "corr-own-a")
    doctor_b, token_b = await _create_and_login(api_client, real_session, "corr-own-b")
    for actor in (doctor_a, doctor_b):
        for code in (
            PERMISSION_CONSULTATION_START,
            PERMISSION_CONSULTATION_MANAGE,
            PERMISSION_CONSULTATION_READ,
        ):
            await grant_permission(actor, code)

    consultation_id, _ = await _complete_consultation(
        api_client, token_a, reception_service, doctor_a, "CorrOwnA", diagnosis="A original dx"
    )

    resp = await api_client.patch(
        f"/api/v1/consultations/{consultation_id}",
        json={"diagnosis": "B tampered"},
        headers=_auth_header(token_b),
    )
    assert resp.status_code == 403

    # A's record is untouched.
    check = await api_client.get(
        f"/api/v1/consultations/{consultation_id}", headers=_auth_header(token_a)
    )
    assert check.json()["data"]["diagnosis"] == "A original dx"


async def test_correct_consultation_updates_fields_and_writes_audit(
    api_client, real_session, grant_permission, reception_service
):
    from sqlalchemy import select

    from app.shared.audit.models import AuditEntry

    doctor, token = await _create_and_login(api_client, real_session, "corr-audit")
    for code in (
        PERMISSION_CONSULTATION_START,
        PERMISSION_CONSULTATION_MANAGE,
        PERMISSION_CONSULTATION_READ,
    ):
        await grant_permission(doctor, code)
    consultation_id, visit = await _complete_consultation(
        api_client,
        token,
        reception_service,
        doctor,
        "CorrAudit",
        history_of="orig H/O",
        diagnosis="orig dx",
        prescription="Tab Orig 1mg OD",
        notes="orig notes",
    )

    resp = await api_client.patch(
        f"/api/v1/consultations/{consultation_id}",
        json={
            "diagnosis": "corrected dx",
            "prescription": "Tab Corrected 2mg BD",
            "notes": "corrected notes",
            # re-submitted unchanged — must NOT be logged as a change
            "history_of": "orig H/O",
        },
        headers=_auth_header(token),
    )
    assert resp.status_code == 200
    data = resp.json()["data"]
    assert data["diagnosis"] == "corrected dx"
    assert data["prescription"] == "Tab Corrected 2mg BD"
    assert data["notes"] == "corrected notes"
    assert data["history_of"] == "orig H/O"

    # persisted
    fresh = await api_client.get(
        f"/api/v1/consultations/{consultation_id}", headers=_auth_header(token)
    )
    assert fresh.json()["data"]["diagnosis"] == "corrected dx"

    rows = (
        (
            await real_session.execute(
                select(AuditEntry).where(
                    AuditEntry.action == "consultation.corrected",
                    AuditEntry.entity_id == consultation_id,
                )
            )
        )
        .scalars()
        .all()
    )
    assert len(rows) == 1
    entry = rows[0]
    assert entry.actor_user_id == doctor.id
    assert entry.entity_type == "consultation"
    assert entry.metadata_["visit_id"] == str(visit.id)
    # only the three fields whose value actually changed
    assert entry.metadata_["fields"] == ["diagnosis", "notes", "prescription"]


async def test_correct_consultation_only_when_completed(
    api_client, real_session, grant_permission, reception_service
):
    doctor, token = await _create_and_login(api_client, real_session, "corr-notdone")
    for code in (PERMISSION_CONSULTATION_START, PERMISSION_CONSULTATION_MANAGE):
        await grant_permission(doctor, code)
    visit = await _make_visit(reception_service, doctor, "CorrNotDone")
    consultation_id = await _start_consultation_id(api_client, token, visit)  # IN_PROGRESS

    resp = await api_client.patch(
        f"/api/v1/consultations/{consultation_id}",
        json={"diagnosis": "too soon"},
        headers=_auth_header(token),
    )
    assert resp.status_code == 422


async def test_correct_consultation_ignores_structural_fields(
    api_client, real_session, grant_permission, reception_service
):
    doctor, token = await _create_and_login(api_client, real_session, "corr-struct")
    for code in (
        PERMISSION_CONSULTATION_START,
        PERMISSION_CONSULTATION_MANAGE,
        PERMISSION_CONSULTATION_READ,
    ):
        await grant_permission(doctor, code)
    consultation_id, _ = await _complete_consultation(
        api_client, token, reception_service, doctor, "CorrStruct", diagnosis="orig"
    )
    before = (
        await api_client.get(
            f"/api/v1/consultations/{consultation_id}", headers=_auth_header(token)
        )
    ).json()["data"]

    resp = await api_client.patch(
        f"/api/v1/consultations/{consultation_id}",
        json={
            "diagnosis": "new dx",
            "status": "cancelled",
            "doctor_user_id": "00000000-0000-0000-0000-000000000000",
            "visit_id": "00000000-0000-0000-0000-000000000000",
            "completed_at": "2020-01-01T00:00:00Z",
        },
        headers=_auth_header(token),
    )
    assert resp.status_code == 200
    data = resp.json()["data"]
    assert data["diagnosis"] == "new dx"
    assert data["status"] == "completed"
    assert data["doctor_user_id"] == before["doctor_user_id"] == str(doctor.id)
    assert data["visit_id"] == before["visit_id"]
    assert data["completed_at"] == before["completed_at"]


async def test_prescription_slip_reflects_correction(
    api_client, real_session, grant_permission, reception_service
):
    doctor, token = await _create_and_login(api_client, real_session, "corr-slip")
    for code in (
        PERMISSION_CONSULTATION_START,
        PERMISSION_CONSULTATION_MANAGE,
        PERMISSION_CONSULTATION_READ,
    ):
        await grant_permission(doctor, code)
    consultation_id, _ = await _complete_consultation(
        api_client,
        token,
        reception_service,
        doctor,
        "CorrSlip",
        diagnosis="Original diagnosis text",
        prescription="Tab Wrong 1mg OD",
    )

    first = await api_client.get(
        f"/api/v1/consultations/{consultation_id}/slip/print", headers=_auth_header(token)
    )
    assert "Original diagnosis text" in first.text
    assert "<li>Tab Wrong 1mg OD</li>" in first.text

    patch = await api_client.patch(
        f"/api/v1/consultations/{consultation_id}",
        json={"diagnosis": "Amended diagnosis text", "prescription": "Tab Right 2mg BD"},
        headers=_auth_header(token),
    )
    assert patch.status_code == 200

    second = await api_client.get(
        f"/api/v1/consultations/{consultation_id}/slip/print", headers=_auth_header(token)
    )
    assert "Amended diagnosis text" in second.text
    assert "Original diagnosis text" not in second.text
    assert "<li>Tab Right 2mg BD</li>" in second.text
    assert "Tab Wrong 1mg OD" not in second.text
