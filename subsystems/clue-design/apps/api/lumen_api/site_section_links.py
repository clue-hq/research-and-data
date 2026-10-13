"""Short-lived signed links to agent-written Puck section modules (Wave 2 Lane B, Contract 4).

An agent module is code, so it is never served by the public ``/asset-store`` route (the public
read skips ``SOURCE_KEY_SITE_SECTION``). The editor asks for links to the sections a document
places; each link is a token valid for ``LINK_TTL_S`` seconds:

    token = base64url(JSON {"w": workspace, "d": document, "e": expires_at}) "." base64url(HMAC)
    HMAC  = HMAC-SHA256(CLUE_SITE_SECTION_LINK_SECRET, "workspace\\ndocument\\ndigest\\nexpires_at")

The digest is not inside the token: the verifier takes it from the URL and recomputes the HMAC, so a
token minted for one module cannot fetch another. The token is the only statement of tenancy the
module route accepts; the module is read from the token's workspace only.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
from datetime import datetime, timezone
from typing import Any

__all__ = [
    "LINK_TTL_S",
    "NOT_FOUND",
    "NOT_REFERENCED",
    "TOKEN_EXPIRED",
    "TOKEN_INVALID",
    "UNCONFIGURED",
    "SectionLinkRefused",
    "link_secret",
    "mint_section_token",
    "section_links",
    "verify_section_token",
]

LINK_TTL_S = 600
TOKEN_INVALID = "site_section_link.invalid"
TOKEN_EXPIRED = "site_section_link.expired"
UNCONFIGURED = "site_section_links.unconfigured"
NOT_REFERENCED = "site_section.not_referenced"
NOT_FOUND = "site_section.not_found"


class SectionLinkRefused(Exception):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(f"{code}: {message}")
        self.code = code
        self.message = message


def link_secret() -> bytes | None:
    """The configured signing secret, or ``None`` when the environment has none."""

    from clue_config import Secrets

    value = Secrets().site_section_link_secret
    return value.get_secret_value().encode("utf-8") if value is not None and value.get_secret_value() else None


def _b64(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def _unb64(text: str) -> bytes:
    return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))


def _signature(secret: bytes, workspace_id: str, document_id: str, digest: str, expires_at: int) -> bytes:
    message = f"{workspace_id}\n{document_id}\n{digest}\n{expires_at}".encode("utf-8")
    return hmac.new(secret, message, hashlib.sha256).digest()


def mint_section_token(*, secret: bytes, workspace_id: str, document_id: str, digest: str, expires_at: int) -> str:
    claims = json.dumps({"w": workspace_id, "d": document_id, "e": int(expires_at)}, separators=(",", ":"))
    return f"{_b64(claims.encode('utf-8'))}.{_b64(_signature(secret, workspace_id, document_id, digest, int(expires_at)))}"


def verify_section_token(token: str, *, secret: bytes, digest: str, now: int) -> tuple[str, str]:
    """``(workspace_id, document_id)`` the token was minted for, if it is genuine, for ``digest``
    and unexpired; otherwise ``SectionLinkRefused``. The signature is checked before the expiry, so
    a forged token never learns whether its time was right."""

    try:
        claims_part, signature_part = token.split(".")
        claims = json.loads(_unb64(claims_part))
        workspace_id, document_id, expires_at = str(claims["w"]), str(claims["d"]), int(claims["e"])
        signature = _unb64(signature_part)
    except (ValueError, KeyError, TypeError) as error:
        raise SectionLinkRefused(TOKEN_INVALID, "the section link is not valid") from error
    expected = _signature(secret, workspace_id, document_id, digest, expires_at)
    if not hmac.compare_digest(signature, expected):
        raise SectionLinkRefused(TOKEN_INVALID, "the section link is not valid")
    if now >= expires_at:
        raise SectionLinkRefused(TOKEN_EXPIRED, "the section link has expired; ask for a new one")
    return workspace_id, document_id


def _iso(epoch: int) -> str:
    return datetime.fromtimestamp(epoch, tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def section_links(repo: Any, document: dict, digests: list[str] | None, *, secret: bytes, now: int) -> list[dict]:
    """Links to the sections ``document`` places (all of them when ``digests`` is None)."""

    site = document.get("scene") or {}
    names = {str(digest): str(name) for name, digest in (site.get("agent_sections") or {}).items()}
    wanted = list(dict.fromkeys(digests if digests is not None else names))
    for digest in wanted:
        if digest not in names:
            raise SectionLinkRefused(NOT_REFERENCED, f"the document does not place section {digest[:12]}")
    rows = {row["digest"]: row for row in repo.get_site_sections(wanted)}
    expires_at = now + LINK_TTL_S
    links = []
    for digest in wanted:
        row = rows.get(digest)
        if row is None:
            raise SectionLinkRefused(NOT_FOUND, f"this workspace holds no section {digest[:12]}")
        links.append({
            "name": names[digest],
            "digest": digest,
            "token": mint_section_token(
                secret=secret, workspace_id=repo.workspace_id, document_id=str(document["id"]),
                digest=digest, expires_at=expires_at,
            ),
            "expires_at": _iso(expires_at),
            "props_schema": row["props_schema"],
        })
    return links
