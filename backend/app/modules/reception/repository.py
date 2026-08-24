"""Read-only queries Reception needs against other modules' tables that
don't belong in any of those modules' own repositories, because the
query itself is Reception's own business concern (auto-assigning a
doctor at fast-registration time), not a generic capability those
modules would otherwise expose. See this module's service.py's
docstring for why Reception itself owns no table.

Querying Auth's tables (User/Role/Permission/UserRole/RolePermission/
LoginSession) directly, read-only, is not a modification of frozen
Phase 5 — nothing here writes to an Auth table or changes Auth's own
behavior; it only reads the same effective-permission/session data
`require_permission()` already computes for every authenticated
request."""

from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.auth.models import (
    LoginSession,
    Permission,
    Role,
    RolePermission,
    User,
    UserRole,
    UserStatus,
)
from app.modules.consultation.constants import PERMISSION_CONSULTATION_START
from app.modules.visits.models import Visit, VisitStatus

# A doctor is "busy" for load-balancing purposes while they have a Visit
# actively waiting for or in consultation — WAITING_BILLING and later
# statuses no longer occupy the doctor's attention.
_BUSY_VISIT_STATUSES = (VisitStatus.WAITING_DOCTOR, VisitStatus.IN_CONSULTATION)


class ReceptionRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def find_least_busy_available_doctor(self) -> User | None:
        """ "Available" = an ACTIVE user holding a role granted
        `consultation:start`, with at least one currently active login
        session (Phase 6 fast-registration's "On Duty / Online doctor" —
        see reception/service.py's `register_visit` docstring for why a
        live login session, not a separate duty-roster field, is the
        chosen signal: it requires no new schema and is trivially always
        correct — a doctor who isn't logged in cannot possibly be
        treated as available). Ties broken by fewest currently
        WAITING_DOCTOR/IN_CONSULTATION visits (load balancing), then by
        `id` for determinism. Returns `None` if no such doctor exists —
        the caller must treat that as "leave unassigned", never as an
        error (Phase 6 fast-registration §4: registration must never
        block on doctor availability)."""
        busy_counts = (
            select(Visit.doctor_user_id.label("doctor_user_id"), func.count().label("busy_count"))
            .where(
                Visit.deleted_at.is_(None),
                Visit.doctor_user_id.is_not(None),
                Visit.status.in_(_BUSY_VISIT_STATUSES),
            )
            .group_by(Visit.doctor_user_id)
            .subquery()
        )

        stmt = (
            select(User)
            .join(UserRole, UserRole.user_id == User.id)
            .join(Role, Role.id == UserRole.role_id)
            .join(RolePermission, RolePermission.role_id == Role.id)
            .join(Permission, Permission.id == RolePermission.permission_id)
            .join(LoginSession, LoginSession.user_id == User.id)
            .outerjoin(busy_counts, busy_counts.c.doctor_user_id == User.id)
            .where(
                User.deleted_at.is_(None),
                User.status == UserStatus.ACTIVE,
                UserRole.deleted_at.is_(None),
                Role.deleted_at.is_(None),
                Role.is_active.is_(True),
                RolePermission.deleted_at.is_(None),
                Permission.deleted_at.is_(None),
                Permission.code == PERMISSION_CONSULTATION_START,
                LoginSession.is_active.is_(True),
            )
            # No `.distinct()`: a User can legitimately match more than
            # once (multiple roles each granting consultation:start,
            # multiple active login sessions) — every duplicate row
            # still carries the same busy_count/id, so they sort
            # identically and `.limit(1)` below still returns exactly
            # one correct row. Postgres also forbids `SELECT DISTINCT`
            # combined with an ORDER BY expression that isn't itself in
            # the select list, which `busy_count` isn't.
            .order_by(func.coalesce(busy_counts.c.busy_count, 0).asc(), User.id.asc())
            .limit(1)
        )
        result = await self.session.execute(stmt)
        return result.scalars().first()

    async def list_doctors_for_selection(self) -> list[tuple[User, bool]]:
        """Every ACTIVE user eligible to be assigned a Visit — the same
        consultation:start-granting-role eligibility
        `find_least_busy_available_doctor` requires — paired with
        whether they currently have an active login session ("online",
        the identical signal/definition that method uses; see its own
        docstring). Powers Reception's doctor-selection dropdown
        (RegisterVisitForm.jsx): unlike `find_least_busy_available_
        doctor`, this returns *every* eligible doctor, not just one —
        Reception must be able to route to a specific doctor even while
        they're offline, not only auto-pick among whoever is currently
        logged in. Ordered online-first, then alphabetically by name,
        so the common case (picking an online doctor) never requires
        scrolling past the offline ones."""
        is_online = (
            select(func.count())
            .select_from(LoginSession)
            .where(LoginSession.user_id == User.id, LoginSession.is_active.is_(True))
            .correlate(User)
            .scalar_subquery()
            > 0
        ).label("is_online")

        stmt = (
            select(User, is_online)
            .join(UserRole, UserRole.user_id == User.id)
            .join(Role, Role.id == UserRole.role_id)
            .join(RolePermission, RolePermission.role_id == Role.id)
            .join(Permission, Permission.id == RolePermission.permission_id)
            .where(
                User.deleted_at.is_(None),
                User.status == UserStatus.ACTIVE,
                UserRole.deleted_at.is_(None),
                Role.deleted_at.is_(None),
                Role.is_active.is_(True),
                RolePermission.deleted_at.is_(None),
                Permission.deleted_at.is_(None),
                Permission.code == PERMISSION_CONSULTATION_START,
            )
            # Safe here (unlike find_least_busy_available_doctor's own
            # comment on the same subject) because `is_online` — the
            # only non-User expression in the ORDER BY — is itself in
            # the select list, satisfying Postgres's DISTINCT+ORDER BY
            # rule; a duplicate match (multiple roles/sessions) always
            # carries the same is_online value for a given user, so
            # collapsing to one row per user never loses information.
            .distinct()
            .order_by(is_online.desc(), User.full_name.asc())
        )
        result = await self.session.execute(stmt)
        return [(row[0], row[1]) for row in result.all()]

    async def get_doctor_by_id(self, doctor_user_id: UUID) -> User | None:
        """Validates that `doctor_user_id` — an explicit doctor
        selection from Reception's RegisterVisitForm, bypassing
        auto-assignment — actually resolves to a real, ACTIVE,
        consultation:start-granting user. Same eligibility
        `find_least_busy_available_doctor`/`list_doctors_for_selection`
        both require, deliberately minus the online requirement: the
        entire point of an explicit selection is reaching a doctor who
        is currently offline, not just confirming they're logged in.
        Returns `None` if the id doesn't resolve — the caller
        (ReceptionService.register_visit) must treat that as a
        rejection, never as "fall back to auto-assign": a caller-
        supplied id that doesn't check out could be a stale id, a typo,
        or a non-doctor user just as easily as a real mistake, and
        silently substituting a different doctor than the one Reception
        explicitly picked would be worse than a clear error either
        way."""
        stmt = (
            select(User)
            .join(UserRole, UserRole.user_id == User.id)
            .join(Role, Role.id == UserRole.role_id)
            .join(RolePermission, RolePermission.role_id == Role.id)
            .join(Permission, Permission.id == RolePermission.permission_id)
            .where(
                User.id == doctor_user_id,
                User.deleted_at.is_(None),
                User.status == UserStatus.ACTIVE,
                UserRole.deleted_at.is_(None),
                Role.deleted_at.is_(None),
                Role.is_active.is_(True),
                RolePermission.deleted_at.is_(None),
                Permission.deleted_at.is_(None),
                Permission.code == PERMISSION_CONSULTATION_START,
            )
            .limit(1)
        )
        result = await self.session.execute(stmt)
        return result.scalars().first()
