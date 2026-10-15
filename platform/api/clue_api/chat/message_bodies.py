"""Server-side hydration of a page of transcript message bodies.

FI Lane D slice **D3**, the ratified contract's cold-load read (charter §3.6: *initial/cold load
comes from paginated durable messages plus current gate/run projections, not replaying the entire
SSE history*). D0 deliberately made message summaries **body-free** — the body of every message is
a content-addressed artifact behind its own permissioned read — which is correct for a list and
useless for a transcript: a browser cannot issue one artifact fetch per message and still render a
conversation.

So this is the opt-in: given one already-paginated page of summaries, resolve that page's bodies in
one round trip, inside the caller's workspace, and bounded three ways.

* **By the page.** It hydrates the page it is given and nothing else — the pagination limit is the
  fan-out limit, so there is no request shape that hydrates a whole thread.
* **By bytes.** A cumulative budget stops the walk; messages past it come back unhydrated with a
  reason instead of a truncated body, so a consumer can tell "too large" from "empty".
* **By type.** Only text-shaped media types are decoded. A binary artifact is not a message body
  and never becomes one by being base64'd into a transcript.

Every read is workspace-scoped in SQL and skips erased, purged, and tombstoned artifacts, so an
executed DSAR erasure removes the words from this surface too — the same posture the artifact
reader takes, restated here because this is the one place a *bulk* body read exists.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from clue_api.knowledge_bytes import cached_bytes, fetch_concurrently, remember_bytes
from clue_storage import ArtifactNotFound, StorageBackend, content_address

__all__ = [
    "DEFAULT_BODY_BUDGET_BYTES",
    "HydratedBody",
    "hydrate_message_bodies",
]

#: The cumulative byte budget one hydrated page may spend. Sized for prose: 50 messages of a few KB
#: each fits comfortably, a page containing a pasted document does not silently become a megabyte
#: response.
DEFAULT_BODY_BUDGET_BYTES = 512_000

#: Media types whose bytes are a *message*. Anything else is an attachment with its own read.
_TEXT_MEDIA_PREFIXES = ("text/",)
_TEXT_MEDIA_TYPES = frozenset({"application/json", "application/vnd.clue.agent-message+json"})


@dataclass(frozen=True, slots=True)
class HydratedBody:
    """One message's body, or the honest reason it is absent."""

    artifact_key: str
    body: str | None
    #: ``None`` when the body is present; otherwise a stable reason code the UI can act on:
    #: ``unavailable`` (erased/purged/no durable row), ``artifact_missing`` (the durable row
    #: exists but its physical bytes do not), ``digest_mismatch``, ``not_text``, ``budget``.
    reason: str | None = None


def _is_text(media_type: str) -> bool:
    return media_type in _TEXT_MEDIA_TYPES or media_type.startswith(_TEXT_MEDIA_PREFIXES)


async def hydrate_message_bodies(
    conn: AsyncConnection,
    *,
    storage: StorageBackend,
    workspace_id: str,
    references: Sequence[tuple[str, str]],
    budget_bytes: int = DEFAULT_BODY_BUDGET_BYTES,
) -> dict[str, HydratedBody]:
    """Resolve ``(artifact_key, sha256)`` pairs into decoded bodies, keyed by artifact key.

    The digest is re-checked against the bytes, not merely against the row: a body whose stored
    bytes no longer match what the message committed to is reported ``digest_mismatch`` and
    withheld. Serving different words than the transcript recorded would be worse than serving
    none, and this is a transcript.
    """

    unique: dict[str, str] = {}
    for artifact_key, sha256 in references:
        unique.setdefault(artifact_key, sha256)
    if not unique:
        return {}
    rows = (
        (
            await conn.execute(
                text(
                    "SELECT storage_key, content_sha256, media_type, size_bytes "
                    "FROM artifact a "
                    "WHERE a.workspace_id = :workspace_id "
                    "  AND a.storage_key = ANY(CAST(:keys AS text[])) "
                    "  AND a.erased_at IS NULL AND a.purged_at IS NULL "
                    "  AND NOT EXISTS (SELECT 1 FROM agent_artifact_tombstone t "
                    "                  WHERE t.workspace_id = a.workspace_id "
                    "                    AND t.artifact_key = a.storage_key)"
                ),
                {"workspace_id": workspace_id, "keys": list(unique)},
            )
        )
        .mappings()
        .all()
    )
    durable = {str(row["storage_key"]): row for row in rows}

    def eligible(artifact_key: str, sha256: str) -> bool:
        row = durable.get(artifact_key)
        return (
            row is not None and row["content_sha256"] == sha256 and _is_text(str(row["media_type"]))
        )

    # The downloads overlap and are served from the content cache on a reload (2026-10-15: nine
    # bodies fetched one after another were most of a 5.3 s chat load). The budget is applied below
    # exactly as before; the bodies it would admit if every fetch succeeds are fetched up front, and
    # one a failure frees room for is fetched on its own in the loop.
    planned: list[str] = []
    optimistic = 0
    for artifact_key, sha256 in unique.items():
        if not eligible(artifact_key, sha256):
            continue
        size = int(durable[artifact_key]["size_bytes"])
        if optimistic + size > budget_bytes:
            continue
        optimistic += size
        if cached_bytes(workspace_id, (artifact_key, sha256)) is None:
            planned.append(artifact_key)
    fetched = await fetch_concurrently(storage, planned)

    hydrated: dict[str, HydratedBody] = {}
    spent = 0
    for artifact_key, sha256 in unique.items():
        row = durable.get(artifact_key)
        if row is None or row["content_sha256"] != sha256:
            hydrated[artifact_key] = HydratedBody(
                artifact_key=artifact_key,
                body=None,
                reason="unavailable" if row is None else "digest_mismatch",
            )
            continue
        if not _is_text(str(row["media_type"])):
            hydrated[artifact_key] = HydratedBody(
                artifact_key=artifact_key, body=None, reason="not_text"
            )
            continue
        size = int(row["size_bytes"])
        if spent + size > budget_bytes:
            hydrated[artifact_key] = HydratedBody(
                artifact_key=artifact_key, body=None, reason="budget"
            )
            continue
        data: bytes | Exception | None = cached_bytes(workspace_id, (artifact_key, sha256))
        if data is None:
            data = fetched.get(artifact_key)
        if data is None:
            data = (await fetch_concurrently(storage, [artifact_key]))[artifact_key]
        if isinstance(data, ArtifactNotFound):
            # The durable row proves that bytes once existed, while the backend no longer has
            # them. That is materially different from erased/purged metadata and must remain a
            # per-message absence: one lost historical blob cannot make the whole thread a 500.
            hydrated[artifact_key] = HydratedBody(
                artifact_key=artifact_key,
                body=None,
                reason="artifact_missing",
            )
            continue
        if isinstance(data, Exception):
            raise data
        if content_address(data) != sha256:
            hydrated[artifact_key] = HydratedBody(
                artifact_key=artifact_key, body=None, reason="digest_mismatch"
            )
            continue
        remember_bytes(workspace_id, (artifact_key, sha256), data)
        spent += size
        hydrated[artifact_key] = HydratedBody(
            artifact_key=artifact_key, body=data.decode("utf-8", errors="replace")
        )
    return hydrated
