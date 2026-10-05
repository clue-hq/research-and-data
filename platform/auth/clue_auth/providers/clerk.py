"""Clerk session-token authenticator isolated behind the provider-neutral seam."""

from __future__ import annotations

import asyncio
from collections import OrderedDict
from datetime import UTC, datetime
from typing import Any

import httpx
import jwt
from pydantic import BaseModel, ConfigDict, Field, HttpUrl

from clue_auth.errors import AuthenticationRequired, AuthenticationUnavailable, SessionInvalid
from clue_auth.principal import (
    AuthenticationRequest,
    ExternalSession,
    utc_from_timestamp,
)


class ClerkJwtConfig(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    jwks_url: HttpUrl
    issuer: str
    authorized_parties: tuple[str, ...] = Field(min_length=1)
    # A full minute of slack: Clerk session tokens live ~60s, so a token that expires while a
    # request is in flight (or across small clock drift) must not log the user out.
    clock_skew_seconds: int = Field(default=60, ge=0, le=60)
    jwks_cache_ttl_seconds: int = Field(default=300, ge=1, le=3600)
    jwks_cache_max_keys: int = Field(default=16, ge=1, le=128)


class ClerkAuthenticator:
    provider_key = "clerk"

    def __init__(
        self,
        config: ClerkJwtConfig,
        *,
        http_client: httpx.AsyncClient | None = None,
    ) -> None:
        self._config = config
        self._client = http_client or httpx.AsyncClient(timeout=5.0)
        self._owns_client = http_client is None
        self._keys: OrderedDict[str, tuple[float, Any]] = OrderedDict()
        self._lock = asyncio.Lock()
        self._last_refresh_at: float | None = None
        self._last_refresh_failure_at: float | None = None

    async def aclose(self) -> None:
        if self._owns_client:
            await self._client.aclose()

    @staticmethod
    def _bearer(authorization: str | None) -> str:
        if not authorization:
            raise AuthenticationRequired("bearer session token is required")
        scheme, separator, token = authorization.partition(" ")
        if separator != " " or scheme.casefold() != "bearer" or not token.strip():
            raise AuthenticationRequired("bearer session token is required")
        return token.strip()

    async def _refresh_keys(self) -> None:
        try:
            response = await self._client.get(str(self._config.jwks_url))
            response.raise_for_status()
            payload = response.json()
            keys = payload.get("keys") if isinstance(payload, dict) else None
            if not isinstance(keys, list):
                raise ValueError("JWKS payload has no keys array")
            loaded: list[tuple[str, Any]] = []
            for value in keys:
                if not isinstance(value, dict) or not isinstance(value.get("kid"), str):
                    continue
                if value.get("kty") != "RSA" or value.get("alg") not in (None, "RS256"):
                    continue
                loaded.append((value["kid"], jwt.PyJWK.from_dict(value).key))
            if not loaded:
                raise ValueError("JWKS contains no usable RS256 keys")
        except (httpx.HTTPError, ValueError, jwt.PyJWKError) as exc:
            self._last_refresh_failure_at = asyncio.get_running_loop().time()
            raise AuthenticationUnavailable("session signing keys are unavailable") from exc

        now = asyncio.get_running_loop().time()
        self._last_refresh_at = now
        self._last_refresh_failure_at = None
        # A successful JWKS response is the provider's complete current keyset. Replacing the
        # cache is what makes rotation-out/revocation effective; merging would retain a removed
        # signing key forever.
        self._keys = OrderedDict(
            (kid, (now, key)) for kid, key in loaded[-self._config.jwks_cache_max_keys :]
        )

    async def _key(self, kid: str) -> Any:
        now = asyncio.get_running_loop().time()
        cached = self._keys.get(kid)
        if cached is not None and now - cached[0] <= self._config.jwks_cache_ttl_seconds:
            self._keys.move_to_end(kid)
            return cached[1]
        async with self._lock:
            now = asyncio.get_running_loop().time()
            cached = self._keys.get(kid)
            if cached is not None and now - cached[0] <= self._config.jwks_cache_ttl_seconds:
                self._keys.move_to_end(kid)
                return cached[1]
            # An attacker can choose arbitrary ``kid`` values. Do not turn each one into a JWKS
            # fetch when this process refreshed moments ago and already knows the bounded keyset.
            refresh_floor = min(5, self._config.jwks_cache_ttl_seconds)
            if (
                cached is None
                and self._last_refresh_at is not None
                and now - self._last_refresh_at < refresh_floor
            ):
                raise SessionInvalid("session token references an unknown signing key")
            if (
                self._last_refresh_failure_at is not None
                and now - self._last_refresh_failure_at < refresh_floor
            ):
                raise AuthenticationUnavailable("session signing keys are unavailable")
            await self._refresh_keys()
            refreshed = self._keys.get(kid)
            if refreshed is None:
                raise SessionInvalid("session token references an unknown signing key")
            return refreshed[1]

    async def authenticate(self, request: AuthenticationRequest) -> ExternalSession:
        token = self._bearer(request.authorization)
        try:
            header = jwt.get_unverified_header(token)
        except jwt.PyJWTError as exc:
            raise SessionInvalid("session token header is invalid") from exc
        if header.get("alg") != "RS256":
            raise SessionInvalid("session token uses an unsupported signing algorithm")
        if header.get("typ") not in (None, "JWT"):
            raise SessionInvalid("session token has an unsupported token type")
        kid = header.get("kid")
        if not isinstance(kid, str) or not kid:
            raise SessionInvalid("session token has no signing key id")
        key = await self._key(kid)
        # Session-token-native contract: Clerk's default session token carries `sid` and `azp`
        # but never `aud` (an audience is a JWT-template concept, and template tokens in turn
        # cannot carry the session-bound `sid`/`azp`). Authenticity rests on the RS256 signature,
        # `iss`, and the `azp` allowlist below; no audience claim participates in verification.
        required = ["iss", "sub", "sid", "iat", "nbf", "exp", "azp"]
        try:
            claims = jwt.decode(
                token,
                key=key,
                algorithms=["RS256"],
                issuer=self._config.issuer,
                leeway=self._config.clock_skew_seconds,
                options={
                    "require": required,
                    "verify_aud": False,
                },
            )
        except jwt.PyJWTError as exc:
            raise SessionInvalid("session token verification failed") from exc
        if claims.get("azp") not in self._config.authorized_parties:
            raise SessionInvalid("session token authorized party is not allowed")
        if claims.get("sts") == "pending":
            raise SessionInvalid("session is not active")
        subject = claims.get("sub")
        session_id = claims.get("sid")
        if (
            not isinstance(subject, str)
            or not subject
            or not isinstance(session_id, str)
            or not session_id
        ):
            raise SessionInvalid("session token subject is invalid")
        now = datetime.now(UTC)
        return ExternalSession(
            provider_key=self.provider_key,
            provider_subject=subject,
            provider_session_subject=session_id,
            issued_at=utc_from_timestamp(claims["iat"]),
            expires_at=utc_from_timestamp(claims["exp"]),
            authenticated_at=now,
        )
