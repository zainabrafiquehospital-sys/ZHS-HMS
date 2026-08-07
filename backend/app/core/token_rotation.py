"""Refresh-token reuse classification with a grace window for legitimate
concurrent rotation races (e.g. two browser tabs, or a retried request,
rotating the same refresh token within milliseconds of each other).

This module is intentionally storage-agnostic — it has no dependency on any
ORM model, database session, or specific token table, because none exists
yet. It answers exactly one question: given a refresh token that has
*already* been rotated (something else — a future RefreshTokenRepository
performing an atomic, race-safe "claim this rotation" write, e.g. a
conditional `UPDATE ... WHERE revoked_at IS NULL` — already decided that),
is this repeat presentation a benign replay of a race the caller lost, or a
genuine reuse attack?

Two callers racing to rotate the same token will always have exactly one
winner (whoever's atomic claim commits first) and one or more losers, who
each independently query the now-rotated token and call `classify_reuse`
here. Every loser sees the same `revoked_at`, so every loser reaches the
same verdict — this module has no shared mutable state and introduces no
race condition of its own.
"""

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from enum import Enum, auto
from uuid import UUID

from app.core.config import get_settings


class ReuseVerdict(Enum):
    """What a repository/service should do about a repeat presentation of
    an already-rotated refresh token."""

    BENIGN_REPLAY = auto()  # re-deliver `replaced_by_id`; do not revoke anything
    REUSE_ATTACK = auto()  # revoke the entire token family; force re-login


@dataclass(frozen=True)
class RotatedTokenState:
    """The minimal facts about an already-rotated refresh token needed to
    classify a reuse attempt. Populated by the repository from whatever
    columns the future `refresh_token` table defines (`revoked_at`,
    `replaced_by_id`) — this dataclass carries no ORM coupling itself."""

    revoked_at: datetime
    replaced_by_id: UUID


def default_grace_window() -> timedelta:
    return timedelta(seconds=get_settings().refresh_reuse_grace_window_seconds)


def classify_reuse(
    state: RotatedTokenState,
    *,
    now: datetime | None = None,
    grace_window: timedelta | None = None,
) -> ReuseVerdict:
    """Classifies a repeat presentation of an already-rotated refresh token.

    Returns `BENIGN_REPLAY` if the token was rotated within `grace_window`
    of `now` — the presenter almost certainly lost a legitimate concurrent
    rotation race and should simply receive `state.replaced_by_id`, the
    token that already replaced theirs, instead of triggering a
    family-wide revocation. Outside the grace window, returns
    `REUSE_ATTACK`.

    `grace_window` defaults to `default_grace_window()` (the configured
    `REFRESH_REUSE_GRACE_WINDOW_SECONDS` setting) when omitted. This is
    resolved lazily, inside the function body rather than as a parameter
    default, so importing this module never requires `Settings` to be
    loadable — only actually calling it without an explicit `grace_window`
    does.

    Only apply grace-window leniency to a token's *immediate* successor in
    its rotation chain — i.e. call this only for the single most-recently-
    superseded token in a family. Walking further back and granting the
    same leniency to older, already-superseded tokens would let a stolen
    token be replayed for the full grace window on every past rotation, not
    just the latest one, materially widening the theft-detection blind spot
    this mitigation is meant to keep narrow.

    A negative elapsed time (`state.revoked_at` in the future relative to
    `now`, from clock skew between processes) is clamped to zero rather
    than ever counted against the caller — clock skew must never be able
    to trigger a mass forced logout.

    `state.revoked_at` and `now` must both be timezone-aware; comparing a
    naive and an aware datetime raises `TypeError` rather than silently
    producing a wrong classification.
    """
    if now is None:
        now = datetime.now(UTC)
    if grace_window is None:
        grace_window = default_grace_window()

    elapsed = max(now - state.revoked_at, timedelta(0))

    if elapsed <= grace_window:
        return ReuseVerdict.BENIGN_REPLAY
    return ReuseVerdict.REUSE_ATTACK
