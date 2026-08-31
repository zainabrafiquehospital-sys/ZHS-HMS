"""One-time production-bootstrap seed script.

Run once against a freshly migrated (`alembic upgrade head`) database
to create everything a brand-new deployment needs before anyone can log
in at all — there is no other bootstrap mechanism in this codebase
(Role/Permission rows are otherwise only ever created through the
Users/Roles/Permissions API itself, which nobody can call before a
first admin account exists; see app/modules/auth/role_service.py's
`create_role` docstring: "system role... seeded outside this API").

What it creates (idempotent — see below):
  1. The full Permission catalog (every PERMISSION_* constant defined
     across every module's constants.py) — a fresh database has zero
     Permission rows otherwise.
  2. An `admin` system role holding every permission that exists.
  3. A `Receptionist` system role holding exactly the permissions the
     receptionist-slip-generation launch scope needs (see
     RECEPTIONIST_PERMISSION_CODES below for the exact set and why).
  3b. A `Vitals` system role, matching the pre-existing demo-vitals-demo
      role's grants exactly (see VITALS_PERMISSION_CODES below) — the
      role self-service Vitals-staff signup resolves to on approval.
  4. One initial admin user, with the `admin` role.
  5. One receptionist test/staff account, with the `Receptionist` role.
  5b. One vitals-staff test account, with the `Vitals` role.

Every role here is created with `is_system_role=True` — not because a
receptionist role is special, but because both are being seeded
*outside* the Roles API by design (see role_service.py's docstring for
what that flag actually protects: it only blocks accidental deletion
via the API, nothing else; both roles remain fully editable — e.g.
granting more permissions later — through the normal Roles API).

Idempotent: every step looks up its row by natural key (permission
code / role name / user email) before creating anything, so re-running
this script against a partially-seeded database converges to the same
end state instead of erroring or duplicating rows. Safe to run more
than once.

Usage (from backend/):
    .venv/Scripts/python.exe scripts/seed_launch_bootstrap.py

Passwords are randomly generated and printed to stdout exactly once —
never logged, never stored in plaintext anywhere. Both accounts are
created with `must_change_password=True`; note that as of this build
that flag is not yet enforced anywhere in the login flow (see this
script's own final printout) — change both passwords out-of-band
immediately after the first login regardless.
"""

import asyncio
import secrets

from app.db import model_registry  # noqa: F401  (registers all models on Base.metadata)
from app.db.session import async_session_factory
from app.modules.auth.constants import (
    PERMISSION_PERMISSIONS_CREATE,
    PERMISSION_PERMISSIONS_DELETE,
    PERMISSION_PERMISSIONS_READ,
    PERMISSION_PERMISSIONS_UPDATE,
    PERMISSION_ROLES_CREATE,
    PERMISSION_ROLES_DELETE,
    PERMISSION_ROLES_MANAGE_PERMISSIONS,
    PERMISSION_ROLES_READ,
    PERMISSION_ROLES_UPDATE,
    PERMISSION_USERS_CREATE,
    PERMISSION_USERS_DELETE,
    PERMISSION_USERS_MANAGE_PASSWORD,
    PERMISSION_USERS_MANAGE_ROLES,
    PERMISSION_USERS_MANAGE_STATUS,
    PERMISSION_USERS_READ,
    PERMISSION_USERS_UPDATE,
)
from app.modules.auth.models import Role, User, UserRole, UserStatus
from app.modules.auth.password_service import PasswordService
from app.modules.auth.repository import (
    PermissionRepository,
    RolePermissionRepository,
    RoleRepository,
    UserRepository,
    UserRoleRepository,
)
from app.modules.auth.validators import derive_permission_group
from app.modules.billing.constants import (
    PERMISSION_BILLING_MANAGE,
    PERMISSION_BILLING_READ,
    PERMISSION_BILLING_SUBMIT_CHARGE,
)
from app.modules.consultation.constants import (
    PERMISSION_CONSULTATION_MANAGE,
    PERMISSION_CONSULTATION_READ,
    PERMISSION_CONSULTATION_START,
)
from app.modules.dashboard.constants import (
    PERMISSION_DASHBOARD_DOCTOR_READ,
    PERMISSION_DASHBOARD_RECEPTION_READ,
    PERMISSION_DASHBOARD_VITALS_READ,
)
from app.modules.inventory.constants import (
    PERMISSION_INVENTORY_MANAGE,
    PERMISSION_INVENTORY_READ,
    PERMISSION_INVENTORY_RECORD_USAGE,
    PERMISSION_INVENTORY_REQUEST_RESTOCK,
)
from app.modules.patients.constants import (
    PERMISSION_PATIENTS_CREATE,
    PERMISSION_PATIENTS_HISTORY_READ,
    PERMISSION_PATIENTS_READ,
    PERMISSION_PATIENTS_UPDATE,
)
from app.modules.pharmacy.constants import (
    PERMISSION_PHARMACY_BILL,
    PERMISSION_PHARMACY_DELETE_BILL,
    PERMISSION_PHARMACY_MANAGE,
    PERMISSION_PHARMACY_READ,
    PERMISSION_PHARMACY_UPDATE_BILL,
)
from app.modules.queue.constants import PERMISSION_QUEUE_MANAGE, PERMISSION_QUEUE_READ
from app.modules.reception.constants import (
    PERMISSION_RECEPTION_CANCEL_VISIT,
    PERMISSION_RECEPTION_CLEAR_OWN_REVENUE,
    PERMISSION_RECEPTION_DELETE_VISIT,
    PERMISSION_RECEPTION_REGISTER_VISIT,
    PERMISSION_RECEPTION_UPDATE_VISIT,
)
from app.modules.search.constants import PERMISSION_SEARCH_READ
from app.modules.visits.constants import (
    PERMISSION_PROCEDURES_MANAGE,
    PERMISSION_PROCEDURES_READ,
    PERMISSION_VISITS_CREATE,
    PERMISSION_VISITS_READ,
)
from app.modules.vitals.constants import PERMISSION_VITALS_READ, PERMISSION_VITALS_RECORD
from app.shared.audit.repository import AuditLogRepository

# ---------------------------------------------------------------------
# Full permission catalog — (code, display_name, description). Every
# PERMISSION_* constant defined anywhere in the codebase must appear
# here exactly once; the admin role is granted all of them.
# ---------------------------------------------------------------------
PERMISSION_CATALOG: list[tuple[str, str, str]] = [
    (PERMISSION_USERS_CREATE, "Create Users", "Create new user accounts."),
    (PERMISSION_USERS_READ, "View Users", "View user accounts and their details."),
    (PERMISSION_USERS_UPDATE, "Update Users", "Edit user account details."),
    (PERMISSION_USERS_DELETE, "Delete Users", "Soft-delete user accounts."),
    (
        PERMISSION_USERS_MANAGE_STATUS,
        "Manage User Status",
        "Activate, deactivate, lock, or unlock user accounts.",
    ),
    (
        PERMISSION_USERS_MANAGE_PASSWORD,
        "Manage User Passwords",
        "Reset a user's password or force a password change on their behalf.",
    ),
    (
        PERMISSION_USERS_MANAGE_ROLES,
        "Manage User Roles",
        "Assign or remove roles held by a user.",
    ),
    (PERMISSION_ROLES_CREATE, "Create Roles", "Create new roles."),
    (PERMISSION_ROLES_READ, "View Roles", "View roles and their details."),
    (PERMISSION_ROLES_UPDATE, "Update Roles", "Edit role details."),
    (PERMISSION_ROLES_DELETE, "Delete Roles", "Soft-delete roles."),
    (
        PERMISSION_ROLES_MANAGE_PERMISSIONS,
        "Manage Role Permissions",
        "Grant or revoke permissions held by a role.",
    ),
    (PERMISSION_PERMISSIONS_CREATE, "Create Permissions", "Create new permission definitions."),
    (PERMISSION_PERMISSIONS_READ, "View Permissions", "View permission definitions."),
    (PERMISSION_PERMISSIONS_UPDATE, "Update Permissions", "Edit permission definitions."),
    (PERMISSION_PERMISSIONS_DELETE, "Delete Permissions", "Soft-delete permission definitions."),
    (
        PERMISSION_BILLING_SUBMIT_CHARGE,
        "Submit Billing Charge",
        "Submit a pending charge request against a visit.",
    ),
    (PERMISSION_BILLING_READ, "View Billing", "View pending charges and invoices."),
    (
        PERMISSION_BILLING_MANAGE,
        "Manage Billing",
        "Approve/reject charges, generate invoices, record payments.",
    ),
    (PERMISSION_CONSULTATION_READ, "View Consultations", "View consultation records."),
    (
        PERMISSION_CONSULTATION_START,
        "Start Consultation",
        "Claim/start a doctor consultation on a visit.",
    ),
    (
        PERMISSION_CONSULTATION_MANAGE,
        "Manage Consultation",
        "Send a consultation to vitals or complete it.",
    ),
    (
        PERMISSION_DASHBOARD_RECEPTION_READ,
        "View Reception Dashboard",
        "View the reception summary dashboard.",
    ),
    (
        PERMISSION_DASHBOARD_DOCTOR_READ,
        "View Doctor Dashboard",
        "View the doctor summary dashboard.",
    ),
    (
        PERMISSION_DASHBOARD_VITALS_READ,
        "View Vitals Dashboard",
        "View the vitals summary dashboard.",
    ),
    (PERMISSION_PATIENTS_CREATE, "Create Patients", "Register a new patient record."),
    (PERMISSION_PATIENTS_READ, "View Patients", "View patient records."),
    (PERMISSION_PATIENTS_UPDATE, "Update Patients", "Edit patient records."),
    (
        PERMISSION_PATIENTS_HISTORY_READ,
        "View Patient History",
        "View a patient's full aggregated history (visits, vitals, consultations, "
        "billing, lab bills, pharmacy bills) via the cross-module Patient History "
        "search. Each section is further scoped to whichever of those the actor "
        "already holds read access to on their own.",
    ),
    (PERMISSION_QUEUE_READ, "View Queue", "View queue worklists and history."),
    (PERMISSION_QUEUE_MANAGE, "Manage Queue", "Start serving a queue entry."),
    (
        PERMISSION_RECEPTION_REGISTER_VISIT,
        "Register Visit",
        "Register a new visit (patient + visit + queue routing) and print its slip.",
    ),
    (PERMISSION_RECEPTION_CANCEL_VISIT, "Cancel Visit", "Cancel a registered visit."),
    (
        PERMISSION_RECEPTION_UPDATE_VISIT,
        "Update Visit",
        "Admin-only: correct a visit's/slip's details (procedure, amount, and the linked "
        "patient's identity fields) after registration. Not granted to Receptionist.",
    ),
    (
        PERMISSION_RECEPTION_DELETE_VISIT,
        "Delete Visit",
        "Admin-only: soft-delete a mistakenly-registered visit. Blocked if the visit has a "
        "paid or partially-paid invoice. Not granted to Receptionist.",
    ),
    (
        PERMISSION_RECEPTION_CLEAR_OWN_REVENUE,
        "Clear Own Revenue",
        "Reset a receptionist's own 'My Revenue' display to zero going forward. Never "
        "deletes or modifies any visit, invoice, or medicine bill row.",
    ),
    (PERMISSION_SEARCH_READ, "Search", "Cross-module patient/visit search."),
    (
        PERMISSION_VISITS_CREATE,
        "Create Visits",
        "Reserved — Visit creation currently only happens via Reception's "
        "register-visit action; no endpoint grants this independently yet.",
    ),
    (PERMISSION_VISITS_READ, "View Visits", "View visit records."),
    (
        PERMISSION_PROCEDURES_MANAGE,
        "Manage Procedure Catalog",
        "Create, edit, delete, and activate/deactivate entries on the procedure price list.",
    ),
    (
        PERMISSION_PROCEDURES_READ,
        "View Procedure Catalog",
        "Search the procedure catalog when registering a visit.",
    ),
    (PERMISSION_VITALS_READ, "View Vitals", "View recorded vitals."),
    (PERMISSION_VITALS_RECORD, "Record Vitals", "Record a vitals reading for a visit."),
    (
        PERMISSION_PHARMACY_READ,
        "View Pharmacy",
        "Search the medicine price list and view/print medicine bills.",
    ),
    (
        PERMISSION_PHARMACY_BILL,
        "Bill Medicines",
        "Build and finalize a multi-item medicine bill.",
    ),
    (
        PERMISSION_PHARMACY_MANAGE,
        "Manage Medicine Price List",
        "Create, edit, and deactivate entries on the medicine price list.",
    ),
    (
        PERMISSION_PHARMACY_UPDATE_BILL,
        "Update Medicine Bill",
        "Admin-only: correct a medicine bill's manual patient details and/or discount after "
        "creation. Blocked if the bill has a paid or partially-paid balance. Not granted to "
        "Receptionist.",
    ),
    (
        PERMISSION_PHARMACY_DELETE_BILL,
        "Delete Medicine Bill",
        "Admin-only: soft-delete a mistakenly-created medicine bill. Blocked if the bill has "
        "a paid or partially-paid balance. Not granted to Receptionist.",
    ),
    # Ward/Emergency Inventory Management (new module, 2026-08-26) — see
    # app/modules/inventory/constants.py's own docstring for the full
    # read/manage/record_usage/request_restock split rationale. Only
    # Vitals and admin are wired to any of these by this script (see
    # VITALS_PERMISSION_CODES below) — the "Inventory Manager" role
    # itself, and its own inventory:manage grant, are seeded separately
    # alongside that role's self-service-signup rollout, the same
    # two-step shape Doctor's own role/RBAC split already established.
    (
        PERMISSION_INVENTORY_READ,
        "View Inventory",
        "View the inventory catalog, both stock levels, transfer/usage history, and "
        "restock requests.",
    ),
    (
        PERMISSION_INVENTORY_MANAGE,
        "Manage Inventory",
        "Manage the inventory catalog, record Main Stock receipts, transfer stock to "
        "Emergency Stock, and fulfill/reject restock requests.",
    ),
    (
        PERMISSION_INVENTORY_RECORD_USAGE,
        "Record Inventory Usage",
        "Record an Emergency Stock item as used against a patient.",
    ),
    (
        PERMISSION_INVENTORY_REQUEST_RESTOCK,
        "Request Inventory Restock",
        "Raise a restock request against a low/out Emergency Stock item.",
    ),
]

# ---------------------------------------------------------------------
# Receptionist role — scoped to exactly the receptionist-slip-generation
# launch, not copied from the broader ad hoc demo role already present
# in some dev databases. Every inclusion below is justified against the
# actual code paths the Reception UI (RegisterVisitForm, Today's
# Registrations, print) exercises — see the inline notes.
# ---------------------------------------------------------------------
RECEPTIONIST_PERMISSION_CODES: list[str] = [
    # Strictly required — the reception UI cannot function without these:
    PERMISSION_RECEPTION_REGISTER_VISIT,  # POST /reception/visits AND the slip-print
    #   endpoint (GET /reception/visits/{id}/slip/print) — both are gated by this
    #   same permission, not a separate "print" permission.
    PERMISSION_RECEPTION_CANCEL_VISIT,  # POST /reception/visits/{id}/cancel
    PERMISSION_PATIENTS_READ,  # GET /patients (existing-patient search in
    #   RegisterVisitForm) and GET /patients/{id} (usePatientsForVisits — used by
    #   both Today's Registrations and every other worklist that joins Visit to Patient).
    PERMISSION_VISITS_READ,  # GET /visits — Today's Registrations table.
    # Procedure catalog (2026-08-21 addition) — search the catalog when
    # registering a visit. Deliberately NOT PERMISSION_PROCEDURES_MANAGE:
    # editing the catalog itself is Admin-only (see app/modules/visits/
    # constants.py's module docstring), same split as Pharmacy's own
    # read/manage pair immediately below.
    PERMISSION_PROCEDURES_READ,  # GET /visits/procedures/search
    # Recommended addition beyond the originally proposed list — powers the
    # existing Reception dashboard card on "/" (app/modules/dashboard/router.py);
    # every other pre-existing demo role already includes it. Read-only, no
    # write capability granted.
    PERMISSION_DASHBOARD_RECEPTION_READ,
    # Pharmacy / Medicine Billing (new module) — search the price list and
    # build/print a medicine bill from the reception counter. Deliberately
    # NOT PERMISSION_PHARMACY_MANAGE: editing the price list itself is
    # Admin-only (see app/modules/pharmacy/constants.py's module docstring).
    PERMISSION_PHARMACY_READ,
    PERMISSION_PHARMACY_BILL,
    # "My Revenue" (2026-08-19 addition) — GET /reception/revenue reuses
    # PERMISSION_RECEPTION_REGISTER_VISIT above (no separate read
    # permission was added, see reception/constants.py's own docstring),
    # so only the "Clear Revenue" mutation needs its own grant here.
    PERMISSION_RECEPTION_CLEAR_OWN_REVENUE,  # POST /reception/revenue/clear
    # Patient History search (2026-08-31 addition) — the new sidebar
    # entry/page every one of Reception/Vitals/Doctor/admin gets (see
    # app/modules/patient_history/router.py's own docstring); gates
    # reaching the search itself, not which sections it returns (those
    # are separately scoped per-actor against the permissions already
    # listed above/below).
    PERMISSION_PATIENTS_HISTORY_READ,
]
# Deliberately NOT included, despite being in the originally proposed set —
# not exercised by any reception UI code path as of this build, so excluded
# under least-privilege ("exactly the permissions reception staff need"):
#   - patients:create — Reception creates patients via the composite
#     reception:register_visit action (ReceptionService calls PatientService
#     directly), never through POST /patients, which this permission actually
#     gates.
#   - queue:read — no reception UI screen calls any /queue endpoint; queue
#     worklists belong to Vitals/Doctor.
#   - search:read — RegisterVisitForm's patient lookup calls GET /patients
#     (patients:read), not the generic GET /search endpoint this gates.
#   - reception:update_visit / reception:delete_visit (2026-08-19 addition)
#     — deliberately admin-only by design, not merely unexercised by the
#     current UI. See app/modules/reception/constants.py's own docstring:
#     correcting/removing a mistakenly-entered slip is an admin data-
#     correction tool, never a receptionist capability, regardless of
#     which UI screens exist. Do not add these here.
#   - pharmacy:update_bill / pharmacy:delete_bill (2026-08-20 addition)
#     — the exact same deliberately-admin-only reasoning as
#     reception:update_visit/delete_visit immediately above, see
#     app/modules/pharmacy/constants.py's own docstring: correcting/
#     removing a mistakenly-created medicine bill is an admin data-
#     correction tool, never a receptionist capability. Do not add
#     these here.
# Add any of these back via the Roles API later if a future reception screen
# actually needs them — safer to grant on demonstrated need than up front.

# ---------------------------------------------------------------------
# Vitals role — matches the pre-existing ad hoc `demo-vitals-demo` role's
# actual grants exactly (confirmed by inspecting that role's
# role_permission rows directly, not guessed), given a proper system-role
# name so self-service Vitals-staff signup (see
# app/modules/auth/user_service.py's `_SIGNUP_ROLE_TO_ROLE_NAME`) has a
# real role to resolve to instead of the demo one.
# ---------------------------------------------------------------------
VITALS_PERMISSION_CODES: list[str] = [
    PERMISSION_VITALS_RECORD,  # POST /vitals
    PERMISSION_VITALS_READ,  # GET /vitals/visits/{id}, GET /vitals/patients/{id}/latest
    PERMISSION_VISITS_READ,  # GET /visits — the vitals worklist's Visit/Patient join
    PERMISSION_QUEUE_READ,  # GET /queue/worklist — the vitals worklist itself
    PERMISSION_DASHBOARD_VITALS_READ,  # the Vitals dashboard card on "/"
    # Ward/Emergency Inventory Management (2026-08-26 addition) — Vitals
    # records usage against Emergency Stock and raises restock requests,
    # and needs read access to search items and see stock levels while
    # doing either. Deliberately NOT PERMISSION_INVENTORY_MANAGE —
    # catalog/receipt/transfer/request-resolution actions are Inventory
    # Manager-only (see app/modules/inventory/constants.py's docstring).
    PERMISSION_INVENTORY_READ,
    PERMISSION_INVENTORY_RECORD_USAGE,
    PERMISSION_INVENTORY_REQUEST_RESTOCK,
    # Patient History search (2026-08-31 addition) — same grant/reasoning
    # as RECEPTIONIST_PERMISSION_CODES' own identical addition above.
    PERMISSION_PATIENTS_HISTORY_READ,
]


async def _get_or_create_permission(
    permission_repo: PermissionRepository, code: str, display_name: str, description: str
):
    existing = await permission_repo.get_by_code(code)
    if existing is not None:
        return existing, False
    from app.modules.auth.models import Permission

    permission = Permission(
        code=code,
        group=derive_permission_group(code),
        display_name=display_name,
        description=description,
    )
    await permission_repo.add(permission)
    return permission, True


async def _get_or_create_role(
    role_repo: RoleRepository, name: str, description: str
) -> tuple[Role, bool]:
    existing = await role_repo.get_by_name(name)
    if existing is not None:
        return existing, False
    role = Role(name=name, description=description, is_system_role=True, is_active=True)
    await role_repo.add(role)
    return role, True


async def _ensure_role_has_permission(
    role_permission_repo: RolePermissionRepository, role: Role, permission_id
) -> bool:
    from sqlalchemy import select

    from app.modules.auth.models import RolePermission

    stmt = select(RolePermission).where(
        RolePermission.role_id == role.id,
        RolePermission.permission_id == permission_id,
        RolePermission.deleted_at.is_(None),
    )
    result = await role_permission_repo.session.execute(stmt)
    if result.scalar_one_or_none() is not None:
        return False
    await role_permission_repo.add(RolePermission(role_id=role.id, permission_id=permission_id))
    return True


async def _get_or_create_user(
    user_repo: UserRepository,
    password_service: PasswordService,
    *,
    email: str,
    full_name: str,
) -> tuple[User, str | None]:
    """Returns (user, generated_password) — generated_password is None if
    the user already existed (its password is never touched by a re-run)."""
    existing = await user_repo.get_by_email(email)
    if existing is not None:
        return existing, None

    password = secrets.token_urlsafe(18)  # ~24 chars, cryptographically random
    user = User(
        email=email,
        full_name=full_name,
        password_hash=await password_service.hash(password),
        status=UserStatus.ACTIVE,
        is_email_verified=True,
        must_change_password=True,
    )
    await user_repo.add(user)
    return user, password


async def _ensure_user_has_role(user_role_repo: UserRoleRepository, user: User, role: Role) -> bool:
    from sqlalchemy import select

    stmt = select(UserRole).where(
        UserRole.user_id == user.id,
        UserRole.role_id == role.id,
        UserRole.deleted_at.is_(None),
    )
    result = await user_role_repo.session.execute(stmt)
    if result.scalar_one_or_none() is not None:
        return False
    await user_role_repo.add(UserRole(user_id=user.id, role_id=role.id))
    return True


async def main() -> None:
    async with async_session_factory() as session:
        permission_repo = PermissionRepository(session)
        role_repo = RoleRepository(session)
        role_permission_repo = RolePermissionRepository(session)
        user_repo = UserRepository(session)
        user_role_repo = UserRoleRepository(session)
        audit_repo = AuditLogRepository(session)
        password_service = PasswordService()

        print("== 1. Permission catalog ==")
        permissions_by_code = {}
        created_count = 0
        for code, display_name, description in PERMISSION_CATALOG:
            permission, created = await _get_or_create_permission(
                permission_repo, code, display_name, description
            )
            permissions_by_code[code] = permission
            created_count += created
        await session.commit()
        print(f"  {len(PERMISSION_CATALOG)} permissions in catalog, {created_count} newly created.")

        print("== 2. admin role ==")
        admin_role, admin_role_created = await _get_or_create_role(
            role_repo, "admin", "Full system access — created by the launch bootstrap seed script."
        )
        await session.commit()
        granted = 0
        for permission in permissions_by_code.values():
            if await _ensure_role_has_permission(role_permission_repo, admin_role, permission.id):
                granted += 1
        await session.commit()
        status = "created" if admin_role_created else "already existed"
        print(f"  role {status}; granted {granted} new permission(s).")

        print("== 3. Receptionist role ==")
        receptionist_role, receptionist_role_created = await _get_or_create_role(
            role_repo,
            "Receptionist",
            "Front-desk visit registration and slip printing — created by the "
            "launch bootstrap seed script, scoped to the slip-generation launch.",
        )
        await session.commit()
        granted = 0
        for code in RECEPTIONIST_PERMISSION_CODES:
            if await _ensure_role_has_permission(
                role_permission_repo, receptionist_role, permissions_by_code[code].id
            ):
                granted += 1
        await session.commit()
        print(
            f"  role {'created' if receptionist_role_created else 'already existed'}; "
            f"granted {granted} new permission(s): {', '.join(RECEPTIONIST_PERMISSION_CODES)}"
        )

        print("== 3b. Vitals role ==")
        vitals_role, vitals_role_created = await _get_or_create_role(
            role_repo,
            "Vitals",
            "Vitals recording and the vitals worklist — created by the launch "
            "bootstrap seed script, granted the same permission set the "
            "pre-existing demo-vitals-demo role already held.",
        )
        await session.commit()
        granted = 0
        for code in VITALS_PERMISSION_CODES:
            if await _ensure_role_has_permission(
                role_permission_repo, vitals_role, permissions_by_code[code].id
            ):
                granted += 1
        await session.commit()
        print(
            f"  role {'created' if vitals_role_created else 'already existed'}; "
            f"granted {granted} new permission(s): {', '.join(VITALS_PERMISSION_CODES)}"
        )

        print("== 4. Initial admin user ==")
        admin_user, admin_password = await _get_or_create_user(
            user_repo,
            password_service,
            # NOT .local — that's an IANA/RFC 6762-reserved mDNS TLD that
            # Pydantic's EmailStr (via email-validator) rejects outright as
            # "a special-use or reserved name that cannot be used with
            # email" (confirmed live: POST /auth/login 422s on it before
            # password verification ever runs). Use the hospital's real
            # domain in an actual deployment; this is a valid placeholder,
            # not a reserved one.
            email="admin@zrh-hospital.com",
            full_name="System Administrator",
        )
        await session.commit()
        if await _ensure_user_has_role(user_role_repo, admin_user, admin_role):
            await session.commit()
        print(f"  {admin_user.email} - {'created' if admin_password else 'already existed'}")

        print("== 5. Receptionist test account ==")
        reception_user, reception_password = await _get_or_create_user(
            user_repo,
            password_service,
            email="receptionist@zrh-hospital.com",  # see admin_user's identical note above
            full_name="Front Desk",
        )
        await session.commit()
        if await _ensure_user_has_role(user_role_repo, reception_user, receptionist_role):
            await session.commit()
        print(
            f"  {reception_user.email} - {'created' if reception_password else 'already existed'}"
        )

        print("== 5b. Vitals test account ==")
        vitals_user, vitals_password = await _get_or_create_user(
            user_repo,
            password_service,
            email="vitals@zrh-hospital.com",  # see admin_user's identical note above
            full_name="Vitals Staff",
        )
        await session.commit()
        if await _ensure_user_has_role(user_role_repo, vitals_user, vitals_role):
            await session.commit()
        print(f"  {vitals_user.email} - {'created' if vitals_password else 'already existed'}")

        await audit_repo.record(
            module="auth",
            action="auth.launch_bootstrap_seeded",
            entity_type="user",
            entity_id=admin_user.id,
            actor_user_id=None,
            metadata={
                "admin_email": admin_user.email,
                "receptionist_email": reception_user.email,
                "vitals_email": vitals_user.email,
            },
        )
        await session.commit()

        print("\n" + "=" * 70)
        print("CREDENTIALS - shown once, never stored anywhere in plaintext.")
        print("Both accounts have must_change_password=True (see this script's")
        print("module docstring: that flag is not yet enforced by the login")
        print("flow itself - change both passwords out-of-band regardless).")
        print("=" * 70)
        if admin_password:
            print(f"  admin:        {admin_user.email}  /  {admin_password}")
        else:
            print(f"  admin:        {admin_user.email}  (already existed - password unchanged)")
        if reception_password:
            print(f"  receptionist: {reception_user.email}  /  {reception_password}")
        else:
            print(f"  receptionist: {reception_user.email}  (already existed - password unchanged)")
        if vitals_password:
            print(f"  vitals staff: {vitals_user.email}  /  {vitals_password}")
        else:
            print(f"  vitals staff: {vitals_user.email}  (already existed - password unchanged)")
        print("=" * 70)


if __name__ == "__main__":
    asyncio.run(main())
