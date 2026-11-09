"""Candidate social handles for a person: PDL for X and Facebook, a same-handle Instagram check.

Every result is a candidate. Whether a handle is this person is the agent's call, from the
account's bio and posts; nothing here decides it.
"""

from __future__ import annotations

from typing import Any, Literal
from urllib.parse import urlsplit

from pydantic import BaseModel, SecretStr

from clue_api.footprint.pdl_client import pdl_person
from clue_api.footprint.treg_client import TREG_BASE_URL, treg_call
from clue_spend.calls import ProviderCaller
from clue_spend.errors import ProviderTransportError

INSTAGRAM_PROFILE = "scrapecreators.instagram.user.profile"


class HandleCandidate(BaseModel):
    platform: Literal["x", "facebook", "instagram"]
    handle: str
    url: str
    source: Literal["pdl", "same_handle"]
    private: bool | None = None
    bio: str | None = None


def _linkedin_id(url: str | None) -> str | None:
    if not url:
        return None
    bits = [b for b in urlsplit(url if "//" in url else f"https://{url}").path.split("/") if b]
    return bits[1] if len(bits) >= 2 and bits[0] == "in" else None


def _tail(value: Any) -> str | None:
    if not isinstance(value, str) or not value.strip():
        return None
    return value.rstrip("/").rsplit("/", 1)[-1].lstrip("@") or None


def _instagram(
    caller: ProviderCaller, token: SecretStr, handle: str, base_url: str
) -> HandleCandidate | None:
    try:
        reply = treg_call(caller, token, INSTAGRAM_PROFILE, {"handle": handle}, base_url=base_url)
    except ProviderTransportError:
        return None
    body = reply.body if isinstance(reply.body, dict) else {}
    user = (body.get("data") or {}).get("user") if isinstance(body.get("data"), dict) else None
    if reply.status >= 400 or not isinstance(user, dict):
        return None
    return HandleCandidate(
        platform="instagram",
        handle=handle,
        url=f"https://www.instagram.com/{handle}/",
        source="same_handle",
        private=bool(user.get("is_private")),
        bio=user.get("biography") or None,
    )


def find_handles(
    caller: ProviderCaller,
    token: SecretStr,
    pdl_key: SecretStr | None,
    *,
    name: str,
    company: str | None,
    linkedin_url: str | None,
    base_url: str = TREG_BASE_URL,
) -> list[HandleCandidate]:
    found: list[HandleCandidate] = []
    person = (
        pdl_person(caller, pdl_key, name=name, company=company, linkedin_url=linkedin_url)
        if pdl_key
        else None
    ) or {}
    x = _tail(person.get("twitter_username") or person.get("twitter_url"))
    facebook = _tail(person.get("facebook_username") or person.get("facebook_url"))
    if x:
        found.append(
            HandleCandidate(platform="x", handle=x, url=f"https://x.com/{x}", source="pdl")
        )
    if facebook:
        found.append(
            HandleCandidate(
                platform="facebook",
                handle=facebook,
                url=f"https://www.facebook.com/{facebook}",
                source="pdl",
            )
        )
    tried: list[str] = []
    for handle in (_linkedin_id(linkedin_url), x, facebook):
        if handle and handle.lower() not in tried:
            tried.append(handle.lower())
            candidate = _instagram(caller, token, handle, base_url)
            if candidate:
                found.append(candidate)
    return found
