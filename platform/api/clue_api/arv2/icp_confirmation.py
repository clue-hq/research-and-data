"""The ICP knowledge document a human is asked about, and the confirmed version they mint.

ARV2 onboarding writes a brand's proposed ICPs as ``icp-definition`` knowledge documents
(``ARV2-ONBOARDING-PLAN.md`` §6.1). O6 makes one of those documents the *subject* of the ICP
confirmation gate: the thing the human reads is the thing the gate names, pinned by document id and
by the digest of its exact bytes, so an approval can only ever confirm the file that was on screen.

Two functions, one shape each:

* :func:`current_icp_document` — the brand's current servable ICP document for one key, read back
  through its verified bytes so its ``product_ids``, its title and any existing confirmation are
  the document's own, never guessed. It is what the gate tool presents and what the answering route
  re-derives before it writes anything.
* :func:`confirm_icp_document` — the human's yes, expressed as **a new version of the same path**:
  the same body under confirmation-stamped front matter (``ARV2-ONBOARDING-PLAN.md`` §6.1), stored
  as its own content-addressed artifact, inserted as the next version with ``status = 'confirmed'``
  and ``supersedes_document_id`` naming the proposal, which is then retired. The document id is
  derived from ``(workspace, proposed document, project)``, so a replayed approval finds its own
  row instead of minting a second one.

A brand's ICPs are shared; a *confirmation* belongs to one project, and it says so in the confirmed
version's own front matter (``confirmed_for_project_id``). Nothing here reads a Client-KB version, a
readiness decision or a Stage-0 pin — an ICP is a file, and a file is pinned by ref and digest
(standing rule ``_memory/2026-09-07-no-old-lane-gate-may-block-new-lane.md``).
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any
from uuid import NAMESPACE_URL, UUID, uuid5

import yaml
from pydantic import JsonValue
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from clue_api.arv2.knowledge_frontmatter import parse_front_matter
from clue_api.arv2.onboarding_documents import KnowledgeDocument, render_markdown
from clue_storage import (
    ArtifactIntegrityError,
    StorageBackend,
    artifact_key,
    content_address,
    read_verified_artifact,
    record_artifact,
)

__all__ = [
    "ICP_ARTIFACT_MEDIA_TYPE",
    "ICP_CONFIRMATION_SOURCE_KEY",
    "ICP_KIND",
    "ConfirmedIcp",
    "IcpConfirmationStale",
    "IcpDocumentSubject",
    "confirm_icp_document",
    "current_icp_document",
    "icp_gate_snapshot",
    "icp_gate_subject_ref",
]

#: The one document kind this module confirms.
ICP_KIND = "icp-definition"
#: Knowledge documents are markdown with YAML front matter, on disk and in the artifact store.
ICP_ARTIFACT_MEDIA_TYPE = "text/markdown"
#: What the confirmed version's artifact row records as its origin.
ICP_CONFIRMATION_SOURCE_KEY = "arv2-icp-confirmation"

#: A document is servable input when its bytes exist and it has not been superseded. Restated here
#: rather than imported: ``clue_api.arv2`` may not import ``clue_api`` modules outside the lane
#: (Global Constraint 7), and the same tuple lives in ``brand_knowledge_context.SERVABLE_STATUSES``
#: and ``onboarding_store._SERVED_STATUSES``.
_SERVABLE_STATUSES: tuple[str, ...] = ("ready", "proposed", "confirmed")

_CONFIRMATION_NAMESPACE = "arv2-icp-confirmation"
_DOCUMENT_COLUMNS = "document_id, brand_id, path, version, status, artifact_key, artifact_sha256"


def _utcnow() -> datetime:
    return datetime.now(UTC)


class IcpConfirmationStale(ValueError):
    """The bytes being confirmed are not the bytes the human was shown."""


@dataclass(frozen=True, slots=True)
class IcpDocumentSubject:
    """One ICP knowledge document, named precisely enough to re-read exactly these bytes."""

    document_id: UUID
    brand_id: str
    path: str
    icp_key: str
    version: int
    status: str
    artifact_key: str
    artifact_sha256: str
    product_ids: tuple[str, ...]
    title: str
    confirmed_for_project_id: str | None


@dataclass(frozen=True, slots=True)
class ConfirmedIcp:
    """The version a human's approval minted."""

    document_id: UUID
    icp_key: str
    version: int
    artifact_key: str
    artifact_sha256: str
    supersedes_document_id: UUID
    product_selection_version: int | None


def _path_for(icp_key: str) -> str:
    return f"audience/icp-{icp_key}.md"


def _key_from_path(path: str) -> str:
    return path.removeprefix("audience/icp-").removesuffix(".md")


def _product_ids(front: Mapping[str, Any]) -> tuple[str, ...]:
    raw = front.get("product_ids")
    if not isinstance(raw, list):
        return ()
    return tuple(value for value in raw if isinstance(value, str) and value)


def _title(front: Mapping[str, Any], body: str, *, icp_key: str) -> str:
    """The document's own title: its front matter's, else its first heading, else its key.

    Never invented — the fallbacks are the document's own text, and the last one is the identity
    the human is already looking at.
    """

    declared = front.get("title")
    if isinstance(declared, str) and declared.strip():
        return declared.strip()
    for line in body.splitlines():
        stripped = line.strip()
        if stripped.startswith("#"):
            heading = stripped.lstrip("#").strip()
            if heading:
                return heading
    return icp_key


def _confirmed_for(front: Mapping[str, Any]) -> str | None:
    value = front.get("confirmed_for_project_id")
    return value if isinstance(value, str) and value else None


async def _servable_icp_rows(
    conn: AsyncConnection,
    *,
    workspace_id: str,
    brand_id: str,
) -> tuple[dict[str, Any], ...]:
    """The brand's current servable ICP documents — the max version of each path."""

    rows = (
        await conn.execute(
            text(
                f"SELECT DISTINCT ON (path) {_DOCUMENT_COLUMNS} "
                "FROM brand_knowledge_document "
                "WHERE workspace_id = :workspace_id AND brand_id = :brand_id "
                "  AND kind = :kind AND status = ANY(:statuses) AND artifact_key IS NOT NULL "
                "ORDER BY path, version DESC"
            ),
            {
                "workspace_id": workspace_id,
                "brand_id": brand_id,
                "kind": ICP_KIND,
                "statuses": list(_SERVABLE_STATUSES),
            },
        )
    ).mappings()
    return tuple(dict(row) for row in rows.all())


async def _subject_from_row(
    conn: AsyncConnection,
    storage: StorageBackend,
    *,
    workspace_id: str,
    row: Mapping[str, Any],
) -> IcpDocumentSubject | None:
    """Read one row's verified bytes into a subject, or nothing at all.

    A document whose bytes no longer verify, or whose front matter cannot be read, is not a
    document the platform may put in front of a human — so it is skipped rather than presented
    half-known. The caller's refusal (``icp_document_not_found`` / a stale gate) is the honest
    outcome; a fabricated subject never is.
    """

    try:
        record, body = await read_verified_artifact(
            conn,
            storage,
            storage_key=str(row["artifact_key"]),
            workspace_id=workspace_id,
        )
    except ArtifactIntegrityError:
        return None
    if record.content_sha256 != str(row["artifact_sha256"]):
        return None
    try:
        front, rest = parse_front_matter(body.decode())
    except (UnicodeDecodeError, ValueError, yaml.YAMLError):
        return None
    path = str(row["path"])
    declared = front.get("icp_key")
    icp_key = declared if isinstance(declared, str) and declared else _key_from_path(path)
    return IcpDocumentSubject(
        document_id=row["document_id"],
        brand_id=str(row["brand_id"]),
        path=path,
        icp_key=icp_key,
        version=int(row["version"]),
        status=str(row["status"]),
        artifact_key=str(row["artifact_key"]),
        artifact_sha256=str(row["artifact_sha256"]),
        product_ids=_product_ids(front),
        title=_title(front, rest, icp_key=icp_key),
        confirmed_for_project_id=_confirmed_for(front),
    )


async def current_icp_document(
    conn: AsyncConnection,
    storage: StorageBackend,
    *,
    workspace_id: str,
    brand_id: str,
    icp_key: str,
) -> IcpDocumentSubject | None:
    """This brand's current ICP document for ``icp_key``, read back through its own bytes.

    The path is the identity onboarding writes (``audience/icp-<key>.md``), so it is tried first.
    The fallback scan exists because the key is a front-matter fact and a document written under
    some other path still carries it; a key that no servable document claims is honestly absent.
    """

    rows = await _servable_icp_rows(conn, workspace_id=workspace_id, brand_id=brand_id)
    path = _path_for(icp_key)
    ordered = sorted(rows, key=lambda row: (str(row["path"]) != path, str(row["path"])))
    for row in ordered:
        subject = await _subject_from_row(conn, storage, workspace_id=workspace_id, row=row)
        if subject is not None and subject.icp_key == icp_key:
            return subject
    return None


def icp_gate_subject_ref(subject: IcpDocumentSubject) -> str:
    """The versioned display reference; the bare ids live in the snapshot beside it."""

    return f"brand-knowledge-document:{subject.document_id}:v{subject.version}"


def icp_gate_snapshot(subject: IcpDocumentSubject) -> dict[str, JsonValue]:
    """The immutable record of what was presented — the document, not a rendering of it."""

    return {
        "subject_kind": "brand_knowledge_document",
        "document_id": str(subject.document_id),
        "brand_id": subject.brand_id,
        "path": subject.path,
        "icp_key": subject.icp_key,
        "version": subject.version,
        "status": subject.status,
        "artifact_key": subject.artifact_key,
        "artifact_sha256": subject.artifact_sha256,
        "product_ids": list(subject.product_ids),
        "title": subject.title,
    }


def confirmed_document_id(
    *, workspace_id: str, proposed_document_id: UUID, project_id: str
) -> UUID:
    """The one id this project's confirmation of this proposal will ever have."""

    return uuid5(
        NAMESPACE_URL,
        f"{_CONFIRMATION_NAMESPACE}:{workspace_id}:{proposed_document_id}:{project_id}",
    )


def _confirmed_front_matter(
    front: dict[str, Any],
    *,
    project_id: str,
    confirmed_by_user_id: str,
    confirmed_at: datetime,
    product_selection_version: int | None,
) -> dict[str, Any]:
    """The proposal's own front matter plus the §6.1 confirmation stamp."""

    front["status"] = "confirmed"
    front["confirmed_by"] = confirmed_by_user_id
    front["confirmed_at"] = confirmed_at.isoformat()
    front["confirmed_for_project_id"] = project_id
    if product_selection_version is None:
        # No confirmed set to point at: the key is absent rather than null, so a reader never has
        # to tell "no set" from "set version unknown".
        front.pop("product_selection_version", None)
    else:
        front["product_selection_version"] = product_selection_version
    return front


def _may_retire(proposed: IcpDocumentSubject, *, project_id: str) -> bool:
    """Whether this project may retire the row it is confirming.

    A proposal is a draft nobody depends on, and a project's own earlier confirmation is its own
    to replace. Another project's confirmation is neither: it is that project's pinned ICP.
    """

    if proposed.status == "proposed":
        return True
    return proposed.status == "confirmed" and proposed.confirmed_for_project_id == project_id


async def _stored_confirmation(
    conn: AsyncConnection,
    *,
    document_id: UUID,
    proposed: IcpDocumentSubject,
    fallback_supersedes: UUID,
    product_selection_version: int | None,
) -> ConfirmedIcp | None:
    """The already-persisted confirmation row, or ``None`` when there is not one yet.

    ``product_selection_version`` is the caller's, not a column: the durable record of the set a
    confirmation was made against is the confirmed document's own front matter, and a replay of the
    same approval carries the same value that wrote it.
    """

    row = (
        (
            await conn.execute(
                text(
                    "SELECT version, artifact_key, artifact_sha256, supersedes_document_id "
                    "FROM brand_knowledge_document WHERE document_id = :document_id"
                ),
                {"document_id": document_id},
            )
        )
        .mappings()
        .one_or_none()
    )
    if row is None:
        return None
    supersedes = row["supersedes_document_id"]
    return ConfirmedIcp(
        document_id=document_id,
        icp_key=proposed.icp_key,
        version=int(row["version"]),
        artifact_key=str(row["artifact_key"]),
        artifact_sha256=str(row["artifact_sha256"]),
        supersedes_document_id=fallback_supersedes if supersedes is None else supersedes,
        product_selection_version=product_selection_version,
    )


async def confirm_icp_document(
    conn: AsyncConnection,
    storage: StorageBackend,
    *,
    workspace_id: str,
    brand_id: str,
    project_id: str,
    proposed: IcpDocumentSubject,
    expected_sha256: str,
    confirmed_by_user_id: str,
    product_selection_version: int | None,
    now: Callable[[], datetime] = _utcnow,
) -> ConfirmedIcp:
    """Mint the ``confirmed`` version of ``proposed`` for one project.

    Raises :class:`IcpConfirmationStale` when the stored bytes are not the ones the caller pinned:
    a confirmation is a statement about exact bytes, so bytes that moved are refused rather than
    confirmed on the human's behalf.

    **Which row is retired.** The subject is retired only when this project is entitled to retire
    it — it is still a ``proposed`` draft, or it is this project's *own* earlier confirmation. A
    row confirmed for **another** project is left ``confirmed`` untouched: that project pins its
    ICP by artifact key and requires the row to still be confirmed
    (``arv2.account_research_launch._pinned_icp``), so retiring it would break its launches. The
    two confirmations then coexist as different versions of the same path.

    **Replay.** The document id is derived from ``(workspace, proposal, project)``, so a second
    call for the same confirmation finds its own row and returns it *before* reading, rendering or
    storing anything — a replay must not leave an orphan artifact behind per attempt.
    """

    document_id = confirmed_document_id(
        workspace_id=workspace_id,
        proposed_document_id=proposed.document_id,
        project_id=project_id,
    )
    replayed = await _stored_confirmation(
        conn,
        document_id=document_id,
        proposed=proposed,
        fallback_supersedes=proposed.document_id,
        product_selection_version=product_selection_version,
    )
    if replayed is not None:
        return replayed

    record, body = await read_verified_artifact(
        conn,
        storage,
        storage_key=proposed.artifact_key,
        workspace_id=workspace_id,
    )
    if record.content_sha256 != expected_sha256:
        raise IcpConfirmationStale("the ICP document's bytes differ from the reviewed digest")
    front, markdown = parse_front_matter(body.decode())
    rendered = render_markdown(
        KnowledgeDocument(
            kind=ICP_KIND,
            folder=proposed.path.split("/", 1)[0],
            path=proposed.path,
            front_matter=_confirmed_front_matter(
                front,
                project_id=project_id,
                confirmed_by_user_id=confirmed_by_user_id,
                confirmed_at=now(),
                product_selection_version=product_selection_version,
            ),
            body=markdown,
            cost=None,
        )
    ).encode()
    sha = content_address(rendered)
    key = artifact_key(workspace_id, sha)
    await record_artifact(
        conn,
        storage_key=key,
        workspace_id=workspace_id,
        content_sha256=sha,
        media_type=ICP_ARTIFACT_MEDIA_TYPE,
        size_bytes=len(rendered),
        source_key=ICP_CONFIRMATION_SOURCE_KEY,
    )
    await storage.put(key, rendered, media_type=ICP_ARTIFACT_MEDIA_TYPE)

    next_version = int(
        (
            await conn.execute(
                text(
                    "SELECT COALESCE(MAX(version), 0) + 1 FROM brand_knowledge_document "
                    "WHERE workspace_id = :workspace_id AND brand_id = :brand_id AND path = :path"
                ),
                {"workspace_id": workspace_id, "brand_id": brand_id, "path": proposed.path},
            )
        ).scalar_one()
    )
    await conn.execute(
        text(
            "INSERT INTO brand_knowledge_document ("
            "  document_id, workspace_id, brand_id, folder, path, kind, version, status, "
            "  artifact_key, artifact_sha256, produced_by_step_id, produced_by_turn_id, "
            "  supersedes_document_id"
            ") VALUES ("
            "  :document_id, :workspace_id, :brand_id, :folder, :path, :kind, :version, "
            "  'confirmed', :artifact_key, :artifact_sha256, NULL, NULL, :supersedes"
            ") ON CONFLICT (document_id) DO NOTHING"
        ),
        {
            "document_id": document_id,
            "workspace_id": workspace_id,
            "brand_id": brand_id,
            "folder": proposed.path.split("/", 1)[0],
            "path": proposed.path,
            "kind": ICP_KIND,
            "version": next_version,
            "artifact_key": key,
            "artifact_sha256": sha,
            # ``produced_by_turn_id`` stays NULL on purpose: the answering turn's ``agent_turn``
            # row does not exist yet when the route commits this (the engine creates it when the
            # turn runs), so the FK could not be satisfied. The confirming human is in the front
            # matter (``confirmed_by``) and the immutable gate answer is the durable authority.
            "supersedes": proposed.document_id,
        },
    )
    if _may_retire(proposed, project_id=project_id):
        await conn.execute(
            text(
                "UPDATE brand_knowledge_document SET status = 'superseded', updated_at = now() "
                "WHERE document_id = :document_id AND status = ANY(:statuses)"
            ),
            {"document_id": proposed.document_id, "statuses": list(_SERVABLE_STATUSES)},
        )
    # Read the row back rather than trusting the values just computed: the stored version is the
    # one every reader will cite.
    stored = await _stored_confirmation(
        conn,
        document_id=document_id,
        proposed=proposed,
        fallback_supersedes=proposed.document_id,
        product_selection_version=product_selection_version,
    )
    if stored is None:  # pragma: no cover - the INSERT above either landed or conflicted
        raise IcpConfirmationStale("the confirmed ICP document did not persist")
    return stored
