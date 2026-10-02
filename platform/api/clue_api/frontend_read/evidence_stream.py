"""Streaming one claim's retained evidence artifact — the E7 route's whole mechanism.

The claim store is the authority for provenance; the *rows* a browser reads
(``researchEvidence``) are composed by :mod:`clue_api.frontend_read.v1_shared`. This module owns
only the byte path behind them: resolve a claim's retained artifact, prove the stored bytes are
still the bytes the row describes, and hand them back in a response that cannot be cached,
redirected to, or executed. The storage key and any signed URL never cross the wire.

Its caller has already decided the request is *authorised* (the account and contact evidence routes
check the claim against what the served page actually cites). Nothing here re-opens that question.
"""

from __future__ import annotations

from fastapi import Response
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from clue_api.frontend_read.accounts_list import WireModel
from clue_core import Claim
from clue_storage import StorageBackend, StorageError, artifact_key, content_address


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
    "EvidenceArtifact",
    "evidence_artifact_response",
    "read_live_artifact",
]
