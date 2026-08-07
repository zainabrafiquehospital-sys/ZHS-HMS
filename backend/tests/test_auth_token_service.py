from datetime import UTC, datetime, timedelta
from uuid import uuid4

import jwt as pyjwt
import pytest

from app.modules.auth.constants import TOKEN_TYPE_ACCESS
from app.modules.auth.exceptions import TokenInvalidError


async def test_create_and_decode_access_token_round_trip(token_service):
    user_id = uuid4()
    token, jti = token_service.create_access_token(user_id, ["DOCTOR", "ADMIN"])

    claims = await token_service.decode_access_token(token)

    assert claims["sub"] == str(user_id)
    assert claims["roles"] == ["DOCTOR", "ADMIN"]
    assert claims["jti"] == jti
    assert claims["token_type"] == TOKEN_TYPE_ACCESS


async def test_decode_rejects_tampered_signature(token_service):
    token, _jti = token_service.create_access_token(uuid4(), [])
    tampered = token[:-4] + ("AAAA" if not token.endswith("AAAA") else "BBBB")

    with pytest.raises(TokenInvalidError):
        await token_service.decode_access_token(tampered)


async def test_decode_rejects_malformed_token(token_service):
    with pytest.raises(TokenInvalidError):
        await token_service.decode_access_token("not-a-jwt-at-all")


async def test_decode_rejects_unknown_kid(token_service, jwt_key_registry):
    signing_key = jwt_key_registry.signing_key()
    forged = pyjwt.encode(
        {"sub": str(uuid4()), "jti": "x", "token_type": TOKEN_TYPE_ACCESS},
        signing_key.private_key,
        algorithm="RS256",
        headers={"kid": "some-other-kid"},
    )

    with pytest.raises(TokenInvalidError):
        await token_service.decode_access_token(forged)


async def test_decode_rejects_expired_token(token_service, jwt_key_registry):
    signing_key = jwt_key_registry.signing_key()
    now = datetime.now(UTC)
    expired = pyjwt.encode(
        {
            "sub": str(uuid4()),
            "jti": "x",
            "token_type": TOKEN_TYPE_ACCESS,
            "iat": now - timedelta(hours=1),
            "exp": now - timedelta(minutes=5),
            "iss": "gynecology-hms",
            "aud": "gynecology-hms-api",
        },
        signing_key.private_key,
        algorithm="RS256",
        headers={"kid": signing_key.kid},
    )

    with pytest.raises(TokenInvalidError):
        await token_service.decode_access_token(expired)


async def test_decode_rejects_wrong_token_type(token_service, jwt_key_registry):
    """A token that is otherwise perfectly valid but carries a
    `token_type` other than "access" (e.g. someone tries to use a value
    from a different context as an access token) must still be rejected."""
    signing_key = jwt_key_registry.signing_key()
    now = datetime.now(UTC)
    wrong_type = pyjwt.encode(
        {
            "sub": str(uuid4()),
            "jti": "x",
            "token_type": "not-access",
            "iat": now,
            "exp": now + timedelta(minutes=5),
            "iss": "gynecology-hms",
            "aud": "gynecology-hms-api",
        },
        signing_key.private_key,
        algorithm="RS256",
        headers={"kid": signing_key.kid},
    )

    with pytest.raises(TokenInvalidError):
        await token_service.decode_access_token(wrong_type)


def test_generate_refresh_token_returns_raw_and_matching_hash(token_service):
    raw, hashed = token_service.generate_refresh_token()

    assert len(raw) > 32
    assert hashed == token_service.hash_refresh_token(raw)


def test_generate_refresh_token_is_unique_per_call(token_service):
    raw1, _ = token_service.generate_refresh_token()
    raw2, _ = token_service.generate_refresh_token()

    assert raw1 != raw2


async def test_blacklisted_jti_is_rejected(token_service):
    token, jti = token_service.create_access_token(uuid4(), [])
    assert await token_service.is_blacklisted(jti) is False

    await token_service.blacklist_jti(jti, ttl_seconds=60)

    assert await token_service.is_blacklisted(jti) is True
    with pytest.raises(TokenInvalidError):
        await token_service.decode_access_token(token)


async def test_blacklist_with_zero_ttl_is_a_no_op(token_service):
    """A token whose remaining lifetime has already reached zero has
    nothing left to blacklist against — must not error."""
    _token, jti = token_service.create_access_token(uuid4(), [])

    await token_service.blacklist_jti(jti, ttl_seconds=0)

    assert await token_service.is_blacklisted(jti) is False
