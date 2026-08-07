from datetime import UTC, datetime

from app.modules.auth.models import User, UserStatus
from app.modules.auth.repository import USER_SORTABLE_COLUMNS, UserRepository
from tests.conftest import make_test_email


async def _make_user(
    db_session, suffix: str, *, full_name: str = "Repo Test User", status: UserStatus | None = None
) -> User:
    user = User(
        email=make_test_email(suffix),
        password_hash="hash",
        full_name=full_name,
        status=status or UserStatus.ACTIVE,
    )
    return await UserRepository(db_session).add(user)


async def test_get_by_phone_number_finds_active_user(db_session):
    user = User(
        email=make_test_email("phone-lookup"),
        password_hash="hash",
        full_name="Phone Lookup",
        phone_number="+1 555 0100",
    )
    await UserRepository(db_session).add(user)

    found = await UserRepository(db_session).get_by_phone_number("+1 555 0100")

    assert found is not None
    assert found.id == user.id


async def test_get_by_phone_number_returns_none_when_missing(db_session):
    assert await UserRepository(db_session).get_by_phone_number("+1 555 9999") is None


async def test_search_filters_by_text_across_email_and_full_name(db_session):
    repo = UserRepository(db_session)
    target = await _make_user(db_session, "search-alpha-zz", full_name="Zebra Alpha")
    await _make_user(db_session, "search-beta-zz", full_name="Beta User")

    users, total = await repo.search(
        search="zebra",
        status=None,
        role_id=None,
        sort_column=USER_SORTABLE_COLUMNS["created_at"],
        sort_desc=True,
        limit=20,
        offset=0,
    )

    assert total == 1
    assert users[0].id == target.id


async def test_search_filters_by_status(db_session):
    repo = UserRepository(db_session)
    await _make_user(db_session, "search-status-active", status=UserStatus.ACTIVE)
    inactive = await _make_user(db_session, "search-status-inactive", status=UserStatus.INACTIVE)

    users, total = await repo.search(
        search="search-status-inactive",
        status=UserStatus.INACTIVE,
        role_id=None,
        sort_column=USER_SORTABLE_COLUMNS["created_at"],
        sort_desc=True,
        limit=20,
        offset=0,
    )

    assert total == 1
    assert users[0].id == inactive.id


async def test_search_excludes_soft_deleted_users(db_session):
    repo = UserRepository(db_session)
    user = await _make_user(db_session, "search-deleted")
    await repo.soft_delete(user, deleted_at=datetime.now(UTC))

    users, total = await repo.search(
        search="search-deleted",
        status=None,
        role_id=None,
        sort_column=USER_SORTABLE_COLUMNS["created_at"],
        sort_desc=True,
        limit=20,
        offset=0,
    )

    assert total == 0
    assert users == []


async def test_search_sorts_and_paginates(db_session):
    repo = UserRepository(db_session)
    await _make_user(db_session, "search-sort-a", full_name="AAA Sort")
    await _make_user(db_session, "search-sort-b", full_name="BBB Sort")
    await _make_user(db_session, "search-sort-c", full_name="CCC Sort")

    first_page, total = await repo.search(
        search="Sort",
        status=None,
        role_id=None,
        sort_column=USER_SORTABLE_COLUMNS["full_name"],
        sort_desc=False,
        limit=2,
        offset=0,
    )
    second_page, _ = await repo.search(
        search="Sort",
        status=None,
        role_id=None,
        sort_column=USER_SORTABLE_COLUMNS["full_name"],
        sort_desc=False,
        limit=2,
        offset=2,
    )

    assert total == 3
    assert [u.full_name for u in first_page] == ["AAA Sort", "BBB Sort"]
    assert [u.full_name for u in second_page] == ["CCC Sort"]


async def test_soft_delete_excludes_from_get_by_id_by_default(db_session):
    repo = UserRepository(db_session)
    user = await _make_user(db_session, "soft-delete-basic")

    deleted = await repo.soft_delete(user, deleted_at=datetime.now(UTC))

    assert deleted.deleted_at is not None
    assert await repo.get_by_id(user.id) is None
    assert (await repo.get_by_id(user.id, include_deleted=True)) is not None


async def test_soft_delete_records_deleted_by(db_session):
    repo = UserRepository(db_session)
    actor = await _make_user(db_session, "soft-delete-actor")
    user = await _make_user(db_session, "soft-delete-target")

    deleted = await repo.soft_delete(user, deleted_at=datetime.now(UTC), deleted_by=actor.id)

    assert deleted.updated_by == actor.id
