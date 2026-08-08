"""B2 Clerk adapter: complete JWT verification and bounded JWKS behavior."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

import httpx
import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa

from clue_auth import AuthenticationRequest, AuthenticationRequired, SessionInvalid
from clue_auth.providers import ClerkAuthenticator, ClerkJwtConfig

from .conftest import run_async

ISSUER = "https://clerk.example.test"
AUDIENCE = "clue-api"
AZP = "https://app.example.test"
KID = "test-key"


def _keys() -> tuple[Any, dict[str, Any]]:
    private = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    jwk = jwt.algorithms.RSAAlgorithm.to_jwk(private.public_key(), as_dict=True)
    jwk.update({"kid": KID, "alg": "RS256", "use": "sig"})
    return private, jwk


def _token(private: Any, **overrides: Any) -> str:
    now = datetime.now(UTC)
    claims: dict[str, Any] = {
        "iss": ISSUER,
        "sub": "user_provider_123",
        "sid": "session_123",
        "iat": int((now - timedelta(seconds=1)).timestamp()),
        "nbf": int((now - timedelta(seconds=1)).timestamp()),
        "exp": int((now + timedelta(minutes=5)).timestamp()),
        "aud": AUDIENCE,
        "azp": AZP,
        "sts": "active",
    }
    claims.update(overrides)
    return jwt.encode(claims, private, algorithm="RS256", headers={"kid": KID, "typ": "JWT"})


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
        audience=AUDIENCE,
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
        assert first.session_id == "session_123"
        assert second.provider_subject == first.provider_subject
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
        ({"aud": "some-other-api"}, "audience"),
        ({"azp": "https://attacker.example"}, "authorized party"),
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
