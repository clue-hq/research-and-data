"""Safe, claim-mapped evidence for the FI-2 Account and Contact read models.

The claim store is the authority for provenance.  This module only projects the subset a browser
may inspect:

* the exact claim and field the evidence supports;
* a public ``http(s)`` URL only after the shared C7 URL-safety predicate accepts it;
* the evidence span only after the caller has already passed the applicable display gate;
* an opaque boolean saying a retained artifact can be requested through the authenticated FI-2
  route.  The storage key and any signed URL never cross the wire.

``source_title`` is deliberately conservative.  The claim substrate does not store fetched-page
titles, so the registered source key is used as the stable source title and the exact public URL is
rendered separately.  Inventing a page headline from a URL would recreate LF-RESEARCH-001 in a new
field.
"""

from __future__ import annotations

from collections.abc import Iterable
from datetime import datetime
from urllib.parse import urlsplit

from fastapi import Response
from sqlalchemy import bindparam, text
from sqlalchemy.ext.asyncio import AsyncConnection

from clue_api.frontend_read.accounts_list import WireModel
from clue_api.research_view_governance import safe_public_url
from clue_core import Claim, FreshnessState, reference_time
from clue_storage import StorageBackend, StorageError, artifact_key, content_address


class EvidenceReference(WireModel):
    """One inspectable evidence record mapped to the exact claim and field it supports."""

    claim_id: str
    field_key: str
    source_title: str | None = None
    provider: str | None = None
    source_url: str | None = None
    evidence_span: str | None = None
    confidence: float
    freshness: FreshnessState | None = None
    observed_at: datetime
    protected_artifact_available: bool = False


def _source_title(claim: Claim) -> str | None:
    """Return only a title the substrate actually knows.

    ``source_key`` is a registered source identity and therefore safe to title the source family.
    When a legacy claim has no key, the public hostname is a truthful, less-specific fallback.  A
    document/page title is not inferred from the path.
    """

    if claim.source_key:
        return claim.source_key
    if safe_public_url(claim.source_url):
        return urlsplit(claim.source_url or "").hostname
    return None


async def live_artifact_claim_ids(
    conn: AsyncConnection,
    *,
    claims: Iterable[Claim],
    workspace_id: str,
) -> set[str]:
    """Claim ids whose referenced artifact is live and in the caller's storage scope.

    Physical-byte integrity is intentionally re-checked at redemption time.  This bounded batch
    only decides whether an action may be advertised without exposing the key.
    """

    by_key: dict[str, set[str]] = {}
    for claim in claims:
        if claim.artifact_key:
            by_key.setdefault(claim.artifact_key, set()).add(str(claim.id))
    if not by_key:
        return set()
    rows = await conn.execute(
        text(
            """
            SELECT storage_key
            FROM artifact
            WHERE storage_key IN :artifact_keys
              AND erased_at IS NULL
              AND purged_at IS NULL
              AND (workspace_id IS NULL OR workspace_id = :workspace_id)
            """
        ).bindparams(bindparam("artifact_keys", expanding=True)),
        {"artifact_keys": list(by_key), "workspace_id": workspace_id},
    )
    return {claim_id for key in rows.scalars() for claim_id in by_key.get(str(key), set())}


def evidence_reference(
    claim: Claim,
    *,
    freshness: FreshnessState | None,
    artifact_available: bool,
) -> EvidenceReference:
    """Project a claim after its owning read model has approved display."""

    public_url = claim.source_url if safe_public_url(claim.source_url) else None
    return EvidenceReference(
        claim_id=str(claim.id),
        field_key=str(claim.field_key),
        source_title=_source_title(claim),
        provider=claim.source_key,
        source_url=public_url,
        evidence_span=claim.evidence_span,
        confidence=float(claim.confidence),
        freshness=freshness,
        observed_at=reference_time(claim),
        protected_artifact_available=artifact_available,
    )


class EvidenceArtifact(WireModel):
    """Bytes and safe media metadata returned only after request-time authorization."""

    body: bytes
    media_type: str


async def read_live_artifact(
    conn: AsyncConnection,
    *,
    claim: Claim,
    workspace_id: str,
    storage: StorageBackend,
) -> EvidenceArtifact | None:
    """Resolve one claim's retained artifact without presigning or exposing its storage key."""

    if claim.artifact_key is None:
        return None
    row = (
        (
            await conn.execute(
                text(
                    """
                    SELECT storage_key, workspace_id, content_sha256, media_type, size_bytes
                    FROM artifact
                    WHERE storage_key = :storage_key
                      AND erased_at IS NULL
                      AND purged_at IS NULL
                      AND (workspace_id IS NULL OR workspace_id = :workspace_id)
                    """
                ),
                {"storage_key": claim.artifact_key, "workspace_id": workspace_id},
            )
        )
        .mappings()
        .first()
    )
    if row is None:
        return None

    try:
        body = await storage.get(claim.artifact_key)
    except StorageError:
        return None

    digest = content_address(body)
    expected_key = artifact_key(row["workspace_id"], digest)
    if (
        str(row["storage_key"]) != expected_key
        or str(row["content_sha256"]) != digest
        or int(row["size_bytes"]) != len(body)
    ):
        return None

    media_type = str(row["media_type"]).lower().split(";", 1)[0].strip()
    safe_media_type = _safe_preview_media_type(media_type)
    if safe_media_type is None:
        return None
    return EvidenceArtifact(body=body, media_type=safe_media_type)


def _safe_preview_media_type(media_type: str) -> str | None:
    """Browser-safe inline types; active SVG/HTML is downgraded to plain text."""

    if media_type in {"text/html", "application/xhtml+xml", "image/svg+xml"}:
        return "text/plain; charset=utf-8"
    if media_type.startswith(("text/", "image/", "audio/", "video/")):
        return media_type
    if media_type in {"application/pdf", "application/json"}:
        return media_type
    return None


def evidence_artifact_response(artifact: EvidenceArtifact) -> Response:
    """Build a sandboxed, non-cacheable response without a redirect or reusable locator."""

    return Response(
        content=artifact.body,
        media_type=artifact.media_type,
        headers={
            "Cache-Control": "private, no-store",
            "Content-Disposition": "inline",
            "Content-Security-Policy": "sandbox; default-src 'none'",
            "X-Content-Type-Options": "nosniff",
        },
    )


__all__ = [
    "EvidenceReference",
    "evidence_artifact_response",
    "evidence_reference",
    "live_artifact_claim_ids",
    "read_live_artifact",
]
