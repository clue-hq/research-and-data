"""Candidate social handles for a person: PDL for X and Facebook, a same-handle Instagram check.

Every result is a candidate. Whether a handle is this person is the agent's call, from the
account's bio and posts; nothing here decides it. What happened to each lookup is counted in the
returned :class:`~clue_api.footprint.search_tally.Tally` (review I5): a PDL or Instagram lookup
that fails is a failure, never "no handles"; PDL or treg refusing to sell stops it for the job.
"""

from __future__ import annotations

from typing import Any, Literal
from urllib.parse import urlsplit

from pydantic import BaseModel, SecretStr

from clue_api.footprint.pdl_client import pdl_person
from clue_api.footprint.search_tally import Tally
from clue_api.footprint.treg_client import TREG_BASE_URL, treg_call
from clue_spend.calls import ProviderCaller
from clue_spend.errors import ProviderHalted, ProviderTransportError

INSTAGRAM_PROFILE = "scrapecreators.instagram.user.profile"


class HandleCandidate(BaseModel):
    platform: Literal["x", "facebook", "instagram"]
    handle: str
    url: str
    source: Literal["pdl", "same_handle"]
    private: bool | None = None
    bio: str | None = None
    #: PDL's confidence (1 to 10) in the person it matched, for a PDL candidate.
    likelihood: int | None = None


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
    caller: ProviderCaller, token: SecretStr, handle: str, base_url: str, tally: Tally
) -> HandleCandidate | None:
    """The same-handle Instagram account, if there is one. A 404 is an answer (no such account);
    anything else that is not a profile is a failure."""
    try:
        reply = treg_call(caller, token, INSTAGRAM_PROFILE, {"handle": handle}, base_url=base_url)
    except ProviderHalted as halted:
        reason = halted.reason_code.removeprefix("latched:")
        tally.stop(
            "treg", reason, f"Instagram check of @{handle} not sent: treg stopped ({reason})"
        )
        return None
    except ProviderTransportError:
        tally.fail(f"Instagram check of @{handle} failed: treg did not answer")
        return None
    if reply.status == 404:
        tally.answer()
        return None
    body = reply.body if isinstance(reply.body, dict) else {}
    data = body.get("data")
    user = data.get("user") if isinstance(data, dict) else None
    if reply.status >= 400 or not isinstance(user, dict):
        tally.fail(f"Instagram check of @{handle} failed: HTTP {reply.status}")
        return None
    tally.answer()
    return HandleCandidate(
        platform="instagram",
        handle=handle,
        url=f"https://www.instagram.com/{handle}/",
        source="same_handle",
        private=bool(user.get("is_private")),
        bio=bio if isinstance(bio := user.get("biography"), str) and bio else None,
    )


def find_handles(
    caller: ProviderCaller,
    token: SecretStr | None,
    pdl_key: SecretStr | None,
    *,
    name: str,
    company: str | None,
    linkedin_url: str | None,
    base_url: str = TREG_BASE_URL,
) -> tuple[list[HandleCandidate], Tally]:
    found: list[HandleCandidate] = []
    tally = Tally()
    person: dict[str, Any] = {}
    likelihood: int | None = None
    if pdl_key is None:
        tally.note("No People Data Labs key is available: X and Facebook were not looked up.")
    else:
        lookup = pdl_person(caller, pdl_key, name=name, company=company, linkedin_url=linkedin_url)
        if lookup.state == "failed":
            text = f"People Data Labs lookup failed: {lookup.failure}"
            if lookup.stopped:
                tally.stop("pdl", lookup.stopped, text)
            else:
                tally.fail(text)
        else:
            tally.answer()
            person, likelihood = lookup.data, lookup.likelihood
    x = _tail(person.get("twitter_username") or person.get("twitter_url"))
    facebook = _tail(person.get("facebook_username") or person.get("facebook_url"))
    if x:
        found.append(
            HandleCandidate(
                platform="x",
                handle=x,
                url=f"https://x.com/{x}",
                source="pdl",
                likelihood=likelihood,
            )
        )
    if facebook:
        found.append(
            HandleCandidate(
                platform="facebook",
                handle=facebook,
                url=f"https://www.facebook.com/{facebook}",
                source="pdl",
                likelihood=likelihood,
            )
        )
    if token is None:
        tally.note("No treg key is available: Instagram was not checked.")
        return found, tally
    tried: list[str] = []
    for handle in (_linkedin_id(linkedin_url), x, facebook):
        if handle and handle.lower() not in tried:
            tried.append(handle.lower())
            if "treg" in tally.stopped:
                break
            candidate = _instagram(caller, token, handle, base_url, tally)
            if candidate:
                found.append(candidate)
    return found, tally
