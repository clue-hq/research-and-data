"""Clerk's mail/verified-address adapter. Clue retains membership authority."""

from __future__ import annotations

import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any
from urllib.parse import quote

import httpx


class ClerkApiError(RuntimeError):
    """A classified provider failure; never expose provider bodies or bearer tokens."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


@dataclass(frozen=True)
class VerifiedClerkProfile:
    email: str
    first_name: str | None
    last_name: str | None


class ClerkApi:
    def __init__(
        self,
        secret: str,
        *,
        transport: httpx.AsyncBaseTransport | None = None,
        observe: Callable[..., Awaitable[None]] | None = None,
    ) -> None:
        self._secret = secret
        self._transport = transport
        # Every answer is reported to the spend layer so a refusal opens a provider incident
        # (design 2026-10-31); the client keeps its own transport and error codes.
        self._observe = observe

    async def _request(
        self, method: str, path: str, *, body: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        started = time.monotonic()
        try:
            async with httpx.AsyncClient(
                base_url="https://api.clerk.com/v1/",
                headers={"Authorization": f"Bearer {self._secret}"},
                timeout=15,
                transport=self._transport,
            ) as client:
                response = await client.request(method, path, json=body)
        except httpx.HTTPError:
            raise ClerkApiError("unavailable", "Invitation service is unavailable.") from None
        await self._report(method, path, response, started)
        if response.status_code == 429:
            raise ClerkApiError("rate_limited", "Invitation limit reached. Try again later.")
        try:
            payload = response.json()
        except ValueError:
            raise ClerkApiError(
                "unavailable", "Invitation service returned an invalid response."
            ) from None
        if not response.is_success:
            errors = payload.get("errors") if isinstance(payload, dict) else None
            codes = (
                {
                    error["code"]
                    for error in errors
                    if isinstance(error, dict) and isinstance(error.get("code"), str)
                }
                if isinstance(errors, list)
                else set()
            )
            if codes & {"form_identifier_exists", "email_address_exists"}:
                raise ClerkApiError("existing_account", "This address already has an account.")
            raise ClerkApiError("unavailable", "Invitation service could not complete the request.")
        if not isinstance(payload, dict):
            raise ClerkApiError("unavailable", "Invitation service returned an invalid response.")
        return payload

    async def _report(
        self, method: str, path: str, response: httpx.Response, started: float
    ) -> None:
        if self._observe is None:
            return
        segment = path.strip("/").split("/", 1)[0] or "root"
        try:
            await self._observe(
                operation=f"auth.clerk.{method.lower()}_{segment}",
                label=f"clerk:{method} {segment}",
                status=response.status_code,
                body=response.content,
                latency_ms=int((time.monotonic() - started) * 1000),
            )
        except Exception:  # noqa: BLE001 - reporting must never break the call it observes
            return

    async def create_invitation(self, *, email: str, redirect_url: str, invitation_id: str) -> str:
        payload = await self._request(
            "POST",
            "invitations",
            body={
                "email_address": email,
                "redirect_url": redirect_url,
                "public_metadata": {"clue_invitation_id": invitation_id},
                "expires_in_days": 30,
            },
        )
        provider_id = payload.get("id")
        if not isinstance(provider_id, str) or not provider_id:
            raise ClerkApiError("unavailable", "Invitation service returned no invitation id.")
        return provider_id

    async def revoke_invitation(self, invitation_id: str) -> None:
        await self._request("POST", f"invitations/{quote(invitation_id, safe='')}/revoke")

    async def primary_email(self, user_id: str) -> str | None:
        profile = await self.primary_profile(user_id)
        return profile.email if profile else None

    async def primary_profile(self, user_id: str) -> VerifiedClerkProfile | None:
        """One provider read for verified email and optional initial signup names."""
        payload = await self._request("GET", f"users/{quote(user_id, safe='')}")
        primary_id = payload.get("primary_email_address_id")
        if not isinstance(primary_id, str) or not primary_id:
            return None
        addresses = payload.get("email_addresses")
        if not isinstance(addresses, list):
            return None
        for address in addresses:
            if not isinstance(address, dict):
                continue
            verification = address.get("verification")
            if (
                address.get("id") == primary_id
                and isinstance(verification, dict)
                and verification.get("status") == "verified"
            ):
                email = address.get("email_address")
                if not isinstance(email, str) or not email.strip():
                    return None

                def name(key: str) -> str | None:
                    value = payload.get(key)
                    return value.strip()[:200] or None if isinstance(value, str) else None

                return VerifiedClerkProfile(
                    email.strip().casefold(), name("first_name"), name("last_name")
                )
        return None
