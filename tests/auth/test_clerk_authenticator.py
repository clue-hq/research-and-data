"""B2 Clerk adapter: complete JWT verification and bounded JWKS behavior."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

import httpx
import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa

from clue_auth import (
    AuthenticationRequest,
    AuthenticationRequired,
    AuthenticationUnavailable,
    SessionInvalid,
)
from clue_auth.providers import ClerkAuthenticator, ClerkJwtConfig

from .conftest import run_async

ISSUER = "https://clerk.example.test"
AZP = "https://app.example.test"
KID = "test-key"


def _keys(kid: str = KID) -> tuple[Any, dict[str, Any]]:
    private = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    jwk = jwt.algorithms.RSAAlgorithm.to_jwk(private.public_key(), as_dict=True)
    jwk.update({"kid": kid, "alg": "RS256", "use": "sig"})
    return private, jwk


def _token(private: Any, *, kid: str = KID, **overrides: Any) -> str:
    # Mirrors Clerk's *default session token* shape: `sid`/`azp` present, no `aud` claim
    # (an audience is a JWT-template concept; template tokens cannot carry `sid`/`azp`).
    now = datetime.now(UTC)
    claims: dict[str, Any] = {
        "iss": ISSUER,
        "sub": "user_provider_123",
        "sid": "session_123",
        "iat": int((now - timedelta(seconds=1)).timestamp()),
        "nbf": int((now - timedelta(seconds=1)).timestamp()),
        "exp": int((now + timedelta(minutes=5)).timestamp()),
        "azp": AZP,
        "sts": "active",
    }
    claims.update(overrides)
    claims = {k: v for k, v in claims.items() if v is not None}
    return jwt.encode(claims, private, algorithm="RS256", headers={"kid": kid, "typ": "JWT"})


def _authenticator(private: Any, jwk: dict[str, Any]) -> tuple[ClerkAuthenticator, list[int]]:
    del private
    calls: list[int] = []

    def handler(_request: httpx.Request) -> httpx.Response:
        calls.append(1)
        return httpx.Response(200, json={"keys": [jwk]})

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    config = ClerkJwtConfig(
        jwks_url=f"{ISSUER}/.well-known/jwks.json",
        issuer=ISSUER,
        authorized_parties=(AZP,),
    )
    return ClerkAuthenticator(config, http_client=client), calls


def test_valid_session_maps_only_to_transient_external_session_and_reuses_jwks() -> None:
    async def scenario() -> None:
        private, jwk = _keys()
        authenticator, calls = _authenticator(private, jwk)
        request = AuthenticationRequest(authorization=f"Bearer {_token(private)}")

        first = await authenticator.authenticate(request)
        second = await authenticator.authenticate(request)

        assert first.provider_key == "clerk"
        assert first.provider_subject == "user_provider_123"
        assert first.provider_session_subject == "session_123"
        assert second.provider_subject == first.provider_subject
        assert len(calls) == 1

    run_async(scenario())


def test_jwks_outage_is_retryable_and_throttled_without_forcing_signout() -> None:
    async def scenario() -> None:
        private, _jwk = _keys()
        calls: list[int] = []

        def handler(_request: httpx.Request) -> httpx.Response:
            calls.append(1)
            return httpx.Response(503)

        authenticator = ClerkAuthenticator(
            ClerkJwtConfig(
                jwks_url=f"{ISSUER}/.well-known/jwks.json",
                issuer=ISSUER,
                authorized_parties=(AZP,),
            ),
            http_client=httpx.AsyncClient(transport=httpx.MockTransport(handler)),
        )
        request = AuthenticationRequest(authorization=f"Bearer {_token(private)}")
        with pytest.raises(AuthenticationUnavailable):
            await authenticator.authenticate(request)
        with pytest.raises(AuthenticationUnavailable):
            await authenticator.authenticate(request)
        assert len(calls) == 1

    run_async(scenario())


def test_missing_or_malformed_bearer_is_authentication_required() -> None:
    async def scenario() -> None:
        private, jwk = _keys()
        authenticator, _ = _authenticator(private, jwk)
        for authorization in (None, "", "Basic abc", "Bearer"):
            with pytest.raises(AuthenticationRequired):
                await authenticator.authenticate(AuthenticationRequest(authorization=authorization))

    run_async(scenario())


@pytest.mark.parametrize(
    ("overrides", "reason"),
    [
        ({"iss": "https://attacker.example"}, "issuer"),
        ({"azp": "https://attacker.example"}, "authorized party"),
        ({"azp": None}, "missing authorized party"),
        ({"sid": None}, "missing session id"),
        ({"exp": 1}, "expired"),
        (
            {"nbf": int((datetime.now(UTC) + timedelta(hours=1)).timestamp())},
            "not yet valid",
        ),
        ({"sts": "pending"}, "pending"),
    ],
)
def test_invalid_session_claims_fail_closed(overrides: dict[str, Any], reason: str) -> None:
    async def scenario() -> None:
        private, jwk = _keys()
        authenticator, _ = _authenticator(private, jwk)
        with pytest.raises(SessionInvalid):
            await authenticator.authenticate(
                AuthenticationRequest(authorization=f"Bearer {_token(private, **overrides)}")
            )

    run_async(scenario())
    assert reason


def test_token_that_expired_in_flight_is_accepted_within_one_minute() -> None:
    """A ~60s session token can expire between the Next server reading it and the API
    checking it; the default leeway must not turn that into a logout."""

    async def scenario() -> None:
        private, jwk = _keys()
        authenticator, _ = _authenticator(private, jwk)
        expired_30s_ago = int((datetime.now(UTC) - timedelta(seconds=30)).timestamp())
        session = await authenticator.authenticate(
            AuthenticationRequest(authorization=f"Bearer {_token(private, exp=expired_30s_ago)}")
        )
        assert session.provider_subject == "user_provider_123"

        expired_2m_ago = int((datetime.now(UTC) - timedelta(minutes=2)).timestamp())
        with pytest.raises(SessionInvalid):
            await authenticator.authenticate(
                AuthenticationRequest(authorization=f"Bearer {_token(private, exp=expired_2m_ago)}")
            )

    run_async(scenario())


def test_audience_claim_does_not_participate_in_verification() -> None:
    """Session-token-native contract: a default session token has no ``aud``; one that happens
    to carry any ``aud`` (a customized session token) must verify identically."""

    async def scenario() -> None:
        private, jwk = _keys()
        authenticator, _ = _authenticator(private, jwk)
        for overrides in ({}, {"aud": "some-api"}, {"aud": ["a", "b"]}):
            session = await authenticator.authenticate(
                AuthenticationRequest(authorization=f"Bearer {_token(private, **overrides)}")
            )
            assert session.provider_session_subject == "session_123"

    run_async(scenario())


def test_unknown_key_and_tampered_signature_fail_closed() -> None:
    async def scenario() -> None:
        private, jwk = _keys()
        other_private, _ = _keys()
        authenticator, calls = _authenticator(private, jwk)
        unknown_kid = jwt.encode(
            jwt.decode(_token(private), options={"verify_signature": False}),
            private,
            algorithm="RS256",
            headers={"kid": "unknown"},
        )
        with pytest.raises(SessionInvalid):
            await authenticator.authenticate(
                AuthenticationRequest(authorization=f"Bearer {unknown_kid}")
            )
        with pytest.raises(SessionInvalid):
            await authenticator.authenticate(
                AuthenticationRequest(authorization=f"Bearer {_token(other_private)}")
            )

        assert len(calls) == 1

    run_async(scenario())


def test_refresh_replaces_jwks_so_rotated_out_key_is_rejected() -> None:
    async def scenario() -> None:
        old_private, old_jwk = _keys("old-key")
        _new_private, new_jwk = _keys("new-key")
        responses = iter((old_jwk, new_jwk))

        def handler(_request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, json={"keys": [next(responses)]})

        client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
        authenticator = ClerkAuthenticator(
            ClerkJwtConfig(
                jwks_url=f"{ISSUER}/.well-known/jwks.json",
                issuer=ISSUER,
                authorized_parties=(AZP,),
                jwks_cache_ttl_seconds=1,
            ),
            http_client=client,
        )
        token = _token(old_private, kid="old-key")
        await authenticator.authenticate(AuthenticationRequest(authorization=f"Bearer {token}"))

        # Expire the old entry without a wall-clock sleep, then make Clerk's next complete JWKS
        # omit it. A merge cache would still accept this token after the refresh.
        cached_at, key = authenticator._keys["old-key"]
        authenticator._keys["old-key"] = (cached_at - 2, key)
        with pytest.raises(SessionInvalid, match="unknown signing key"):
            await authenticator.authenticate(AuthenticationRequest(authorization=f"Bearer {token}"))

    run_async(scenario())
