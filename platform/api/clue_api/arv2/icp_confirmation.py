"""The ICP knowledge document a human is asked about, the version they mint, and the project's pin.

ARV2 onboarding writes a brand's proposed ICPs as ``icp-definition`` knowledge documents
(``ARV2-ONBOARDING-PLAN.md`` §6.1). O6 makes one of those documents the *subject* of the ICP
confirmation gate: the thing the human reads is the thing the gate names, pinned by document id and
by the digest of its exact bytes, so an approval can only ever confirm the file that was on screen.

Three shapes:

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
* :func:`pin_project_icp` / :func:`current_project_icp_pin` — the durable **project ICP pin**
  (founder rulings 2026-09-10). A project pins exactly one confirmed ICP document version, by
  document id, written in the same transaction as the approval that minted it. Everything that
  asks "what is this project's ICP?" — the opening index card, the account launch, the person
  launch — reads that row, so a newer version on the same path (a re-synthesis proposal, or
  another project's confirmation) cannot change what an existing project reads or launches with.

A brand's ICPs are shared; a *confirmation* belongs to one project, and it says so in the confirmed
version's own front matter (``confirmed_for_project_id``) — data, not the selector: the pin is the
selector. Nothing here reads a Client-KB version, a readiness decision or a Stage-0 pin — an ICP is
a file, and a file is pinned by ref and digest (standing rule
``_memory/2026-09-07-no-old-lane-gate-may-block-new-lane.md``).
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
    "ProjectIcpPin",
    "confirm_icp_document",
    "current_icp_document",
    "current_project_icp_pin",
    "icp_gate_snapshot",
    "icp_gate_subject_ref",
    "pin_project_icp",
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
_DOCUMENT_COLUMNS = (
    "document_id, brand_id, project_id, derived_from_document_id, path, version, status, "
    "artifact_key, artifact_sha256"
)


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
    #: ``None`` for the brand's own document; set for a project-local variant, which only that
    #: project may read and confirm. The confirmed version inherits both this and the lineage
    #: below, so a variant's history stays inside its own scope.
    project_id: str | None
    derived_from_document_id: UUID | None


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


#: Every document this reader may see, newest per path, the project's own variant winning. The
#: ``kind`` is deliberately **not** filtered (founder ruling 2026-09-14): an ICP is whichever
#: document the human agreed to pin as one, written wherever the agent judged sensible and calling
#: itself whatever it calls itself, so the key in its front matter is the only thing that can find
#: it. :func:`current_icp_document` orders the candidates so the ICP-shaped ones are read first.
_SERVABLE_ICP_ROWS = text(
    "SELECT DISTINCT ON (path) "
    f"{_DOCUMENT_COLUMNS}, kind "
    "FROM brand_knowledge_document "
    "WHERE workspace_id = :workspace_id AND brand_id = :brand_id "
    "  AND status = ANY(:statuses) AND artifact_key IS NOT NULL "
    "  AND (project_id IS NULL OR project_id = :project_id) "
    "ORDER BY path, (project_id IS NULL), version DESC"
)


async def _servable_icp_rows(
    conn: AsyncConnection,
    *,
    workspace_id: str,
    brand_id: str,
    project_id: str | None,
) -> tuple[dict[str, Any], ...]:
    """The current servable documents this project may read — the max version of each path.

    Scope decides which row owns a path. A project sees the brand's documents *and* its own
    variants, and where both exist at one path the variant wins (``(project_id IS NULL)`` sorts
    ``false`` first, so ``DISTINCT ON`` keeps the project's row) — a project that rewrote its ICP
    reads what it rewrote. A read with no project (``:project_id`` bound ``None``) sees brand rows
    only: ``project_id = NULL`` is never true, so no project's private variant leaks into an
    unscoped read.
    """

    rows = (
        await conn.execute(
            _SERVABLE_ICP_ROWS,
            {
                "workspace_id": workspace_id,
                "brand_id": brand_id,
                "statuses": list(_SERVABLE_STATUSES),
                "project_id": project_id,
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
    project_id = row["project_id"]
    return IcpDocumentSubject(
        document_id=row["document_id"],
        brand_id=str(row["brand_id"]),
        project_id=None if project_id is None else str(project_id),
        derived_from_document_id=row["derived_from_document_id"],
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
    project_id: str | None = None,
) -> IcpDocumentSubject | None:
    """The ICP document for ``icp_key`` this project may read, through its own bytes.

    **The key is the identity, not the path and not the kind.** An ICP is a document a human agreed
    to pin as one, drafted wherever the agent judged sensible (founder ruling 2026-09-14), so this
    reads every servable document in the reader's scope — one query — and returns the first whose
    own front matter claims the key. The candidates are ordered by how ICP-shaped they are, which
    is a preference and never a filter: the path onboarding writes (``audience/icp-<key>.md``)
    first, then anything that calls itself an ``icp-definition``, then the rest in path order. So
    the ordinary case still costs exactly one blob read, while a draft at some other path under
    some other name is found rather than reported absent.

    ``project_id`` is the reader's scope: with it, a project-local variant of a path wins over the
    brand's document; without it, only brand-level documents are visible at all.
    """

    rows = await _servable_icp_rows(
        conn, workspace_id=workspace_id, brand_id=brand_id, project_id=project_id
    )
    path = _path_for(icp_key)
    ordered = sorted(
        rows,
        key=lambda row: (
            str(row["path"]) != path,
            str(row.get("kind")) != ICP_KIND,
            str(row["path"]),
        ),
    )
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
    automatic_turn_ref: str | None = None,
) -> dict[str, Any]:
    """The proposal's own front matter plus the §6.1 confirmation stamp."""

    front["status"] = "confirmed"
    front["confirmed_by"] = confirmed_by_user_id
    front["confirmed_at"] = confirmed_at.isoformat()
    front["confirmed_for_project_id"] = project_id
    if automatic_turn_ref is not None:
        front["confirmation_mode"] = "automatic"
        front["confirmation_turn_ref"] = automatic_turn_ref
    else:
        front.pop("confirmation_mode", None)
        front.pop("confirmation_turn_ref", None)
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
    automatic_turn_ref: str | None = None,
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
                automatic_turn_ref=automatic_turn_ref,
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
                    "WHERE workspace_id = :workspace_id AND brand_id = :brand_id AND path = :path "
                    "  AND project_id IS NOT DISTINCT FROM :project_id"
                ),
                {
                    "workspace_id": workspace_id,
                    "brand_id": brand_id,
                    "path": proposed.path,
                    # The *subject's* scope, not the confirming project's: confirming a brand
                    # document mints a brand version, and confirming a project's variant mints the
                    # next version of that variant. The two histories share a path and never
                    # interleave, which is exactly what the scoped unique index allows.
                    "project_id": proposed.project_id,
                },
            )
        ).scalar_one()
    )
    await conn.execute(
        text(
            "INSERT INTO brand_knowledge_document ("
            "  document_id, workspace_id, brand_id, project_id, derived_from_document_id, "
            "  folder, path, kind, version, status, "
            "  artifact_key, artifact_sha256, produced_by_step_id, produced_by_turn_id, "
            "  supersedes_document_id"
            ") VALUES ("
            "  :document_id, :workspace_id, :brand_id, :project_id, :derived_from, "
            "  :folder, :path, :kind, :version, "
            "  'confirmed', :artifact_key, :artifact_sha256, NULL, NULL, :supersedes"
            ") ON CONFLICT (document_id) DO NOTHING"
        ),
        {
            "document_id": document_id,
            "workspace_id": workspace_id,
            "brand_id": brand_id,
            # A confirmation does not change what a document *is*: the confirmed version keeps the
            # proposal's scope and the lineage back to the brand document it was cut from.
            "project_id": proposed.project_id,
            "derived_from": proposed.derived_from_document_id,
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


# =================================================================================================
# the project's ICP pin: one confirmed document version, chosen by a human, that never moves alone
# =================================================================================================


@dataclass(frozen=True, slots=True)
class ProjectIcpPin:
    """The confirmed ICP document version one project reads and launches against."""

    document_id: UUID
    icp_key: str
    artifact_key: str
    artifact_sha256: str
    product_selection_version: int | None
    version: int
    path: str
    #: The pinned document's own scope: ``None`` when the project pinned the brand's document, its
    #: own project id when it pinned a variant it authored.
    project_id: str | None


#: The current pin is the project's greatest ``pin_seq``. ``version`` and ``path`` are not columns
#: of the pin — they belong to the document version it names, and a document's version and path
#: never change — so they are joined rather than copied, and cannot drift from the row they
#: describe.
_CURRENT_PIN = text(
    """
    SELECT pin.document_id, pin.icp_key, pin.artifact_key, pin.artifact_sha256,
           pin.product_selection_version, doc.version, doc.path, doc.project_id
    FROM project_icp_pin AS pin
    JOIN brand_knowledge_document AS doc ON doc.document_id = pin.document_id
    WHERE pin.workspace_id = :workspace_id AND pin.project_id = :project_id
    ORDER BY pin.pin_seq DESC
    LIMIT 1
    """
)


async def current_project_icp_pin(
    conn: AsyncConnection,
    *,
    workspace_id: str,
    project_id: str,
) -> ProjectIcpPin | None:
    """This project's pinned ICP document, or ``None`` when a human has not pinned one yet.

    Read inside one workspace: another tenant's pin is indistinguishable from absence. A project
    with no pin is honestly unpinned — the launches refuse by name rather than falling back to
    "whatever the brand confirmed most recently", which is exactly the moving answer the pin
    exists to remove (founder rulings 2026-09-10).
    """

    row = (
        (
            await conn.execute(
                _CURRENT_PIN,
                {"workspace_id": workspace_id, "project_id": project_id},
            )
        )
        .mappings()
        .one_or_none()
    )
    if row is None:
        return None
    selection_version = row["product_selection_version"]
    pinned_project_id = row["project_id"]
    return ProjectIcpPin(
        document_id=row["document_id"],
        icp_key=str(row["icp_key"]),
        artifact_key=str(row["artifact_key"]),
        artifact_sha256=str(row["artifact_sha256"]),
        product_selection_version=(None if selection_version is None else int(selection_version)),
        version=int(row["version"]),
        path=str(row["path"]),
        project_id=None if pinned_project_id is None else str(pinned_project_id),
    )


async def pin_project_icp(
    conn: AsyncConnection,
    *,
    workspace_id: str,
    project_id: str,
    brand_id: str,
    document: ConfirmedIcp,
    product_selection_version: int | None,
    pinned_by_user_id: str,
) -> ProjectIcpPin:
    """Pin ``document`` as this project's ICP, appending a row unless it is already the pin.

    Called in the gate-approval transaction, immediately after :func:`confirm_icp_document`: the
    human's yes is one act, so the confirmed version and the pin that names it commit together or
    not at all.

    **Replay writes nothing.** A double-approve, or a retried request, re-derives the same
    confirmed document id, finds it is already the current pin, and returns it — the receipt of who
    pinned it and when stays the first one's, which is the truth.

    The table is append-only and the current pin is the greatest ``pin_seq``, so a future "switch
    this project's ICP" act appends its own row and this project's earlier pins remain readable as
    the history of what it researched against.
    """

    current = await current_project_icp_pin(conn, workspace_id=workspace_id, project_id=project_id)
    if current is not None and current.document_id == document.document_id:
        return current
    await conn.execute(
        text(
            "INSERT INTO project_icp_pin ("
            "  workspace_id, project_id, pin_seq, brand_id, document_id, icp_key, "
            "  artifact_key, artifact_sha256, product_selection_version, pinned_by_user_id"
            ") SELECT :workspace_id, :project_id, "
            "  COALESCE(MAX(pin_seq), 0) + 1, :brand_id, :document_id, :icp_key, "
            "  :artifact_key, :artifact_sha256, :product_selection_version, :pinned_by_user_id "
            "FROM project_icp_pin WHERE project_id = :project_id"
        ),
        {
            "workspace_id": workspace_id,
            "project_id": project_id,
            "brand_id": brand_id,
            "document_id": document.document_id,
            "icp_key": document.icp_key,
            "artifact_key": document.artifact_key,
            "artifact_sha256": document.artifact_sha256,
            "product_selection_version": product_selection_version,
            "pinned_by_user_id": pinned_by_user_id,
        },
    )
    # Read the pin back rather than trusting what was just written: the stored row, joined to its
    # document, is the one every launch and every turn will cite.
    stored = await current_project_icp_pin(conn, workspace_id=workspace_id, project_id=project_id)
    if stored is None:  # pragma: no cover - the INSERT above either landed or raised
        raise IcpConfirmationStale("the project's ICP pin did not persist")
    return stored
