"""A project's own documents: anything the agent writes under ``project/``, and the human's edits.

Any markdown path under the project mount is a document. The agent writes ``plan.md`` there, or
``audience/icp-gi.md``, or ``notes/competitive-brief.md``, and each write appends an immutable
version to the chain at that path in this project's scope. There is no kind-per-folder and no list
of admitted paths: the platform records and tracks what the agent judged worth writing down, and a
document's *kind* and *title* are the document's own words (its front matter), not a shape this
module enforces (founder ruling 2026-09-14). Whether a document is the project's plan, its ICP or
its personas is a **pin** the human agreed to — a ``role`` in the document's front matter, or the
ICP confirmation gate — never a path this module recognizes.

The human edits every one of them through :func:`save_project_document`, the project-scoped twin of
the Knowledge PUT. Both hands append to one chain.

Two hands on one file is a lost-update problem, so the agent must say **which version it read**.
``expected_version`` is compared against the version at rest, and a mismatch is refused by name
rather than overwriting words the human typed in between: the agent re-reads the file under
``project/`` and writes again, keeping their edits. ``None`` means "nothing exists at this path
yet" and is only correct for the first write.

What the platform owns, and the model does not — stamped *over* the model's own front matter, so
every other thing it wrote survives:

* **status** — a document the agent writes is born ``ready``. An ICP, which has a confirmation
  gate, is not re-confirmed by being retyped: a human's text edit of a ``confirmed`` document comes
  back as ``proposed`` with the approval stamp dropped (ruling I), exactly as the brand Knowledge
  PUT does. The confirmed row it came from stays servable, because some project may still be
  pinned to precisely those bytes.
* **scope** — every read and every write here is inside one project. Another project's document is
  not an error, it is *absent*, which is also the answer another tenant's document gets.
* **version** — the number this write mints, stamped into the front matter by both hands, so the
  version of the file the agent reads is legible *in* the file it reads (ruling P) rather than
  only on the index card beside it.
* **authorship** — the turn and the human on it for the agent's write, ``user_edit`` for the
  human's, stamped into the front matter so the provenance survives in the bytes themselves.

The version chain is read and written with ``project_id = :project_id`` throughout, so the brand's
document at a path and a project's own are two histories that never interleave — what the scoped
unique index (``brand_knowledge_document_scope_path_version``) allows and this module respects.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from hashlib import sha256
from typing import Any
from uuid import NAMESPACE_URL, UUID, uuid4, uuid5

from sqlalchemy import text
from sqlalchemy.engine import RowMapping
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncConnection

from clue_api.arv2.icp_confirmation import _title as _titled_by_its_own_text
from clue_api.arv2.knowledge_frontmatter import parse_front_matter
from clue_api.arv2.onboarding_documents import KnowledgeDocument, render_markdown
from clue_api.knowledge_bytes import read_one_knowledge_bytes
from clue_storage import (
    StorageBackend,
    artifact_key,
    content_address,
    record_artifact,
)

__all__ = [
    "DEFAULT_DOCUMENT_KIND",
    "INSTRUCTIONS_PATH",
    "PLAN_PATH",
    "PLAN_WORKSPACE_PATH",
    "PROJECT_DOCUMENT_SOURCE_KEY",
    "USER_EDIT_SOURCE_KEY",
    "ProjectDocumentRefused",
    "ProjectDocumentRow",
    "ProjectDocumentWrite",
    "ProjectPlanWrite",
    "WrittenDocument",
    "create_human_project_document",
    "current_document_version",
    "current_plan_version",
    "get_project_document",
    "latest_project_document_version",
    "list_project_documents",
    "lock_project",
    "plan_document_id",
    "project_document_id",
    "read_project_document",
    "save_project_document",
    "workspace_path_of",
    "write_project_document",
    "write_project_plan",
]

#: The plan's row path — a default the skills suggest, never a rule this module checks. Folder-
#: qualified, because the ``path LIKE folder || '/%'`` CHECK holds for every knowledge document, and
#: the plan's folder is ``project``. Kept because two readers still fall back to it when no document
#: carries the ``role: plan`` the human pinned.
PLAN_PATH = "project/plan.md"
#: Where the plan is readable in the agent's workspace — in the mounted project library. This is
#: ``project_context_files.project_workspace_path(PLAN_PATH)`` — one leading ``project/`` segment is
#: the folder name, not a directory under the prefix, so the mounted prefix and the folder name
#: fold into one segment. It is restated here rather than imported for the reason ``icp_authoring``
#: restates its prefixes: ``clue_api.arv2`` may not import ``clue_api`` modules outside the lane
#: (Global Constraint 7).
PLAN_WORKSPACE_PATH = "project/plan.md"
#: The standing instructions a human types into the project home, stored as this project's own
#: document so the agent reads them in its workspace like everything else under ``project/``
#: (spec 2026-09-19 §2.6). Folder-qualified for the same reason :data:`PLAN_PATH` is.
INSTRUCTIONS_PATH = "project/instructions.md"
#: What a document calls itself when it says nothing. ``kind`` is the model's word for what it
#: wrote, read off its front matter; a document that declares none is simply a document.
DEFAULT_DOCUMENT_KIND = "document"
#: What each version's artifact row records as its origin — the agent's write and the human's edit
#: are different acts and are told apart at the artifact, not only in the front matter.
PROJECT_DOCUMENT_SOURCE_KEY = "arv2-project-document"
USER_EDIT_SOURCE_KEY = "arv2-project-document-user_edit"

_DOCUMENT_MEDIA_TYPE = "text/markdown"
_PLAN_NAMESPACE = "arv2-project-plan"
_DOCUMENT_NAMESPACE = "arv2-project-document"
#: Where this project's documents are readable in the agent's workspace. See
#: :data:`PLAN_WORKSPACE_PATH` for why the prefix is restated here rather than imported.
_PROJECT_INPUT_PREFIX = "project/"

#: A document is servable — it owns its path — while its bytes exist and it has not been
#: superseded. Restated rather than imported, for the Global Constraint 7 reason above.
_SERVABLE_STATUSES: tuple[str, ...] = ("ready", "proposed", "confirmed")
#: What a new version retires. ``confirmed`` is deliberately absent: a human's yes is some project's
#: pinned ICP, and a later version stands beside it rather than retiring it.
_RETIRABLE_STATUSES: tuple[str, ...] = ("ready", "proposed")
#: The approval stamp a confirmation writes. A text edit is not a re-confirmation, so these are
#: dropped from the version it mints (ruling I; the brand Knowledge PUT drops the same four).
_APPROVAL_KEYS: tuple[str, ...] = (
    "confirmed_by",
    "confirmation_mode",
    "confirmation_turn_ref",
    "confirmed_at",
    "confirmed_for_project_id",
    "product_selection_version",
)
#: The row columns every read here decodes.
_ROW_COLUMNS = (
    "document_id, path, kind, folder, version, status, updated_at, artifact_key, artifact_sha256"
)


def _utcnow() -> datetime:
    return datetime.now(UTC)


class ProjectDocumentRefused(Exception):
    """This document cannot be written, and the writer is told exactly why.

    Every refusal names something the caller can act on: an empty body, a version that is no longer
    current (re-read and write again), a document this project does not own, or another writer that
    took the version number in between.
    """

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


@dataclass(frozen=True, slots=True)
class ProjectDocumentWrite:
    """One write of one document under ``project/``. Scope, tenancy and authorship are ambient.

    ``path`` is the document's row path — the mount-relative path the model typed, folder-qualified
    (:func:`row_path_of`). ``document_text`` is the model's whole file, front matter and all: the
    header carries content the model owns (what it calls this document, its title, the ``role`` the
    human agreed to pin it under) beside the fields the platform stamps. ``expected_version`` is its
    statement about what it read.
    """

    workspace_id: str
    brand_id: str
    project_id: str
    turn_id: UUID
    user_id: str
    path: str
    document_text: str
    #: The version of this path this text was written against; ``None`` when it does not exist yet.
    expected_version: int | None


@dataclass(frozen=True, slots=True)
class ProjectPlanWrite:
    """One write of a project's plan, for the callers that still speak of the plan as a shape.

    Kept for ``write_project_document@1`` (retired from the profile, alive for replay) and its
    tests. A plan is no longer a kind or a path the platform knows — it is a document like any
    other — so this is a request shape, not a second mechanism.
    """

    workspace_id: str
    brand_id: str
    project_id: str
    turn_id: UUID
    user_id: str
    body: str
    #: The version of ``project/plan.md`` this body was written against; ``None`` when the file does
    #: not exist yet.
    expected_version: int | None


@dataclass(frozen=True, slots=True)
class WrittenDocument:
    """The version this write stored, named precisely enough for the agent to cite and re-open."""

    document_id: UUID
    path: str
    version: int
    #: Where the document is readable in the agent's workspace on the next turn.
    workspace_path: str
    replayed: bool


@dataclass(frozen=True, slots=True)
class ProjectDocumentRow:
    """One servable version of one of this project's documents."""

    document_id: UUID
    path: str
    kind: str
    version: int
    status: str
    updated_at: datetime
    artifact_key: str
    artifact_sha256: str
    #: The ICP this document is about, read off the path (``audience/icp-<key>.md`` and its
    #: ``audience/persona-<key>.md``), or ``None``. Taken from the path rather than the front matter
    #: so listing a project's documents costs one query and no blob reads.
    icp_key: str | None


def plan_document_id(*, turn_id: UUID, expected_version: int | None, body_sha256: str) -> UUID:
    """The replay id ``write_project_document@1`` minted, kept exactly as it was.

    The generic writer derives its own id from the path (:func:`project_document_id`); this one
    survives because the retired plan tool is still replayable, and a replayed call must land on
    the row it already wrote rather than mint a second version of the plan.
    """

    return uuid5(
        NAMESPACE_URL, f"{_PLAN_NAMESPACE}:{turn_id}:{expected_version or 0}:{body_sha256}"
    )


def project_document_id(
    *, turn_id: UUID, path: str, expected_version: int | None, document_sha256: str
) -> UUID:
    """The one id this turn's write of *this text* at this path and version will ever have.

    Derived rather than minted so a retried tool call finds its own row instead of publishing the
    same document twice. A replay re-sends identical arguments, so it lands on its own row exactly
    as before. Four things are in the key, and each of them is a genuinely different write:

    * the **turn**, so one turn's document is not another's;
    * the **path**, so one turn writing two documents writes two documents;
    * the **expected version**, because the same turn writing again after re-reading a newer
      version is a new link in the version chain;
    * the **text digest**, because the same turn writing *different words* against the same version
      is a rewrite, not a replay. Without it that second text was silently discarded and the agent
      was told it had been stored; with it, the rewrite mints a new id, fails the revision check
      against the version it just wrote, and comes back as the named revision conflict the agent
      already knows how to recover from.
    """

    return uuid5(
        NAMESPACE_URL,
        f"{_DOCUMENT_NAMESPACE}:{turn_id}:{path}:{expected_version or 0}:{document_sha256}",
    )


def row_path_of(mount_path: str) -> str:
    """The row path of a document the model wrote at ``mount_path`` under the project mount.

    Every knowledge document's path is folder-qualified (``path LIKE folder || '/%'``), and the
    mount's own name is the folder for anything the model writes at the top of the tree: ``plan.md``
    is stored at ``project/plan.md``, which is what :func:`workspace_path_of` folds back to
    ``plan.md`` when the tree is compiled. A path that already names a folder keeps it.
    """

    return mount_path if "/" in mount_path else _PROJECT_INPUT_PREFIX + mount_path


def folder_of(row_path: str) -> str:
    """A document's folder: the first segment of its row path, which is what the CHECK compares."""

    return row_path.split("/", 1)[0]


def workspace_path_of(path: str) -> str:
    """Where a row path is readable in the agent's workspace.

    ``project_context_files.project_workspace_path``: one leading ``project/`` segment is the
    *folder* name, not a directory under the prefix, so the mounted prefix and a plan's folder fold
    into one segment while an ``audience/`` document keeps both. Restated rather than imported for
    the reason :data:`PLAN_WORKSPACE_PATH` gives.
    """

    return _PROJECT_INPUT_PREFIX + path.removeprefix(_PROJECT_INPUT_PREFIX)


def document_title(front: Mapping[str, Any], body: str, *, path: str) -> str:
    """What this document is called on screen: front matter's title, first heading, else file name.

    One rule for every surface that names a project document — the Gallery list, the transcript
    chip, the agent's focus card — so the same file is never called two things.
    """

    name = path.rsplit("/", 1)[-1]
    if name.endswith(".md"):
        name = name[:-3]
    return _titled_by_its_own_text(front, body, icp_key=name)


def _icp_key_of(path: str) -> str | None:
    for prefix in ("audience/icp-", "audience/persona-"):
        if path.startswith(prefix) and path.endswith(".md"):
            return path[len(prefix) : -len(".md")] or None
    return None


def _row(row: RowMapping) -> ProjectDocumentRow:
    path = str(row["path"])
    return ProjectDocumentRow(
        document_id=row["document_id"],
        path=path,
        kind=str(row["kind"]),
        version=int(row["version"]),
        status=str(row["status"]),
        updated_at=row["updated_at"],
        artifact_key=str(row["artifact_key"]),
        artifact_sha256=str(row["artifact_sha256"]),
        icp_key=_icp_key_of(path),
    )


async def current_document_version(
    conn: AsyncConnection, *, workspace_id: str, project_id: str, path: str
) -> int | None:
    """The version of one of this project's documents at rest, or ``None`` when it has none.

    Read over *every* row in the scope rather than the servable ones only: the next version number
    must be one no version of this path has ever used, or the scoped unique index would refuse it.
    The newest row is always the servable one here — this module is the only writer of these paths,
    and it retires the previous version in the same transaction — so this is also the version the
    agent read in its workspace.
    """

    version = await conn.scalar(
        text(
            "SELECT MAX(version) FROM brand_knowledge_document "
            "WHERE workspace_id = :workspace_id AND project_id = :project_id AND path = :path"
        ),
        {"workspace_id": workspace_id, "project_id": project_id, "path": path},
    )
    return None if version is None else int(version)


async def current_plan_version(
    conn: AsyncConnection, *, workspace_id: str, project_id: str
) -> int | None:
    """The version of this project's plan at rest, or ``None`` when it has none."""

    return await current_document_version(
        conn, workspace_id=workspace_id, project_id=project_id, path=PLAN_PATH
    )


async def _stored_document(
    conn: AsyncConnection, *, workspace_id: str, project_id: str, document_id: UUID
) -> WrittenDocument | None:
    """The row this write already produced, or ``None``. Read before anything is rendered.

    Scoped like every other read here: a row found by id alone would let one project's write be
    answered with another's row, and scope is part of a document's identity in this module.
    """

    row = (
        (
            await conn.execute(
                text(
                    "SELECT path, version FROM brand_knowledge_document "
                    "WHERE workspace_id = :workspace_id AND project_id = :project_id "
                    "  AND document_id = :document_id"
                ),
                {
                    "workspace_id": workspace_id,
                    "project_id": project_id,
                    "document_id": document_id,
                },
            )
        )
        .mappings()
        .one_or_none()
    )
    if row is None:
        return None
    path = str(row["path"])
    return WrittenDocument(
        document_id=document_id,
        path=path,
        version=int(row["version"]),
        workspace_path=workspace_path_of(path),
        replayed=True,
    )


async def _record_document(
    conn: AsyncConnection,
    *,
    workspace_id: str,
    document: KnowledgeDocument,
    source_key: str,
) -> tuple[str, str, bytes]:
    """Render one version's bytes and record their artifact row. Returns ``(key, sha256, bytes)``.

    The row is written here because the document row's ``artifact_key`` references it, so it must
    exist before the INSERT. The *bytes* are not written here: they are handed back for
    :func:`_store_bytes` to put once the version has actually landed, so a refused write leaves no
    unreferenced object behind.
    """

    data = render_markdown(document).encode("utf-8")
    sha = content_address(data)
    key = artifact_key(workspace_id, sha)
    await record_artifact(
        conn,
        storage_key=key,
        workspace_id=workspace_id,
        content_sha256=sha,
        media_type=_DOCUMENT_MEDIA_TYPE,
        size_bytes=len(data),
        source_key=source_key,
    )
    return key, sha, data


async def _store_bytes(storage: StorageBackend, key: str, data: bytes) -> None:
    """Write the version's bytes, after the row that cites them is at rest."""

    await storage.put(key, data, media_type=_DOCUMENT_MEDIA_TYPE)


async def lock_project(conn: AsyncConnection, *, workspace_id: str, project_id: str) -> None:
    """Take this project's row lock. **The first lock every writer of this project takes.**

    Public because a third writer joined the two below: the project library
    (``clue_api.project_library``) rewrites one tree per project, and it serializes that rewrite
    against the document writes it renders by taking exactly this lock, in exactly this order.

    Both hands write one version chain — the agent through :func:`write_project_plan`, the human
    through :func:`save_project_document` — and two writers that take the same two locks in
    opposite orders deadlock. Postgres then aborts one of them with ``40P01``, which is an
    ``OperationalError`` rather than an ``IntegrityError``, so it would escape both of this
    module's typed handlers and surface as a 500 instead of "someone wrote first". One total order
    — project row, then document rows — removes the cycle.
    """

    await conn.execute(
        text(
            "SELECT project_id FROM project "
            "WHERE workspace_id = :workspace_id AND project_id = :project_id FOR UPDATE"
        ),
        {"workspace_id": workspace_id, "project_id": project_id},
    )


async def _retire(
    conn: AsyncConnection,
    *,
    workspace_id: str,
    project_id: str,
    path: str,
    keeping: UUID,
) -> None:
    """Retire every other servable version of this path in this project's scope."""

    await conn.execute(
        text(
            "UPDATE brand_knowledge_document SET status = 'superseded', updated_at = now() "
            "WHERE workspace_id = :workspace_id AND project_id = :project_id AND path = :path "
            "  AND document_id <> :document_id AND status = ANY(:statuses)"
        ),
        {
            "workspace_id": workspace_id,
            "project_id": project_id,
            "path": path,
            "document_id": keeping,
            "statuses": list(_RETIRABLE_STATUSES),
        },
    )


async def _supersedes(
    conn: AsyncConnection, *, workspace_id: str, project_id: str, path: str
) -> UUID | None:
    """The row a new version at ``path`` follows: the servable one it was written against.

    It agrees with the current version in every ordinary case, and reading it rather than assuming
    it keeps a reader walking ``supersedes_document_id`` backwards from stepping off a row that was
    never retired.
    """

    return (
        await conn.execute(
            text(
                "SELECT document_id FROM brand_knowledge_document "
                "WHERE workspace_id = :workspace_id AND project_id = :project_id "
                "  AND path = :path AND status = ANY(:statuses) "
                "ORDER BY version DESC LIMIT 1"
            ),
            {
                "workspace_id": workspace_id,
                "project_id": project_id,
                "path": path,
                "statuses": list(_SERVABLE_STATUSES),
            },
        )
    ).scalar_one_or_none()


async def _insert_version(
    conn: AsyncConnection,
    *,
    document_id: UUID,
    workspace_id: str,
    brand_id: str,
    project_id: str,
    folder: str,
    path: str,
    kind: str,
    version: int,
    status: str,
    artifact_key_: str,
    artifact_sha256: str,
    supersedes: UUID | None,
    race_message: str,
) -> bool:
    """Insert one version row, returning whether *this* call is the one that published it.

    ``False`` means ``ON CONFLICT DO NOTHING`` matched: a concurrent twin of this exact call
    inserted the row first, so this call published nothing. That is the same logical event as the
    replay short-circuit each writer takes above, and is reported the same way — a caller is never
    told it wrote a version it did not write.

    ``produced_by_turn_id`` is left NULL, as ``icp_authoring`` and ``icp_confirmation`` leave it:
    the turn that wrote a version is recorded in the document's own front matter (``authored_by``),
    where the human and the model can both read it, and the column's foreign key would otherwise
    make the writer refuse a write whose turn is not journalled.
    """

    try:
        result = await conn.execute(
            text(
                "INSERT INTO brand_knowledge_document ("
                "  document_id, workspace_id, brand_id, project_id, folder, path, kind, version, "
                "  status, artifact_key, artifact_sha256, supersedes_document_id"
                ") VALUES ("
                "  :document_id, :workspace_id, :brand_id, :project_id, :folder, :path, :kind, "
                "  :version, :status, :artifact_key, :artifact_sha256, :supersedes"
                ") ON CONFLICT (document_id) DO NOTHING"
            ),
            {
                "document_id": document_id,
                "workspace_id": workspace_id,
                "brand_id": brand_id,
                "project_id": project_id,
                "folder": folder,
                "path": path,
                "kind": kind,
                "version": version,
                "status": status,
                "artifact_key": artifact_key_,
                "artifact_sha256": artifact_sha256,
                "supersedes": supersedes,
            },
        )
    except IntegrityError as exc:
        if "brand_knowledge_document_scope_path_version" in str(exc.orig):
            # Another writer took this version number between the read and the insert. Nothing
            # partial is at rest — the caller re-reads the document and writes again.
            raise ProjectDocumentRefused("project_document_version_race", race_message) from exc
        raise
    return result.rowcount != 0


def _stamped_front_matter(
    front: Mapping[str, Any],
    *,
    request: ProjectDocumentWrite,
    version: int,
    authored_at: datetime,
) -> dict[str, Any]:
    """The model's front matter with the platform's facts stamped over it.

    Everything the document itself says survives — what it calls itself, its title, the ``role`` a
    human agreed to pin it under, a persona list, an ``icp_key``. Only the six facts the model does
    not own are stamped last and therefore win: the version this write mints, the status it is born
    with, the scope it lives in, and who wrote it on which turn. Nothing is validated: a document
    whose header says something odd is a document that says something odd, and the readers that
    need a field say what is missing when they need it (founder ruling 2026-09-14).
    """

    stamped = dict(front)
    stamped["version"] = version
    stamped["status"] = "ready"
    stamped["project_id"] = request.project_id
    stamped["brand_id"] = request.brand_id
    stamped["authored_by"] = {"turn_id": str(request.turn_id), "user_id": request.user_id}
    stamped["authored_at"] = authored_at.isoformat()
    return stamped


async def write_project_document(
    conn: AsyncConnection,
    storage: StorageBackend,
    request: ProjectDocumentWrite,
    *,
    now: Callable[[], datetime] = _utcnow,
    document_id: UUID | None = None,
) -> WrittenDocument:
    """Store one document as the next ``ready`` version of its path in this project's scope.

    The one writer behind every path under ``project/``. It does not ask what the document *is*:
    the path is the model's, the kind and the title are the document's own front matter, and a
    document nobody has a use for yet is still recorded and versioned (founder ruling 2026-09-14).

    **Replay.** The id is derived from ``(turn, path, expected version, text digest)``, so a retried
    call — identical arguments — finds its own row and returns it *before* anything is rendered or
    stored, and a rewrite within one turn is refused by name rather than discarded. ``authored_at``
    is the one non-deterministic value in the bytes, and that short-circuit is what keeps a replay
    from becoming a different document. ``document_id`` overrides the derivation for the one legacy
    caller whose replay key was minted before this writer existed.

    Raises :class:`ProjectDocumentRefused` — never a partial write — for every refusable condition.
    """

    if not request.document_text.strip():
        raise ProjectDocumentRefused(
            "project_document_body_empty",
            f"{request.path} is empty; write the document as markdown",
        )
    try:
        front, body = parse_front_matter(request.document_text, preserve_body=True)
    except ValueError:
        # No front matter at all, or one that is not a mapping: the model wrote plain markdown and
        # the platform supplies the machine-readable header itself.
        front, body = {}, request.document_text

    path = request.path
    workspace_path = workspace_path_of(path)
    if document_id is None:
        document_id = project_document_id(
            turn_id=request.turn_id,
            path=path,
            expected_version=request.expected_version,
            document_sha256=sha256(request.document_text.encode("utf-8")).hexdigest(),
        )
    replayed = await _stored_document(
        conn,
        workspace_id=request.workspace_id,
        project_id=request.project_id,
        document_id=document_id,
    )
    if replayed is not None:
        return replayed

    # The one lock order every writer of this project takes (see :func:`lock_project`); a replay
    # above costs none.
    await lock_project(conn, workspace_id=request.workspace_id, project_id=request.project_id)
    current = await current_document_version(
        conn, workspace_id=request.workspace_id, project_id=request.project_id, path=path
    )
    if current != request.expected_version:
        raise ProjectDocumentRefused(
            "project_document_revision_conflict",
            f"{path} is at version {current}; you expected {request.expected_version}. "
            f"Re-read {workspace_path} and write again.",
        )

    # Known before the bytes are rendered, so the version this write mints is *in* the front
    # matter: the skill tells the agent to pass "the version of the file you read", and this is
    # what makes that readable in the file it reads (ruling P).
    version = (current or 0) + 1
    declared = front.get("kind")
    kind = declared if isinstance(declared, str) and declared.strip() else DEFAULT_DOCUMENT_KIND
    key, sha, data = await _record_document(
        conn,
        workspace_id=request.workspace_id,
        document=KnowledgeDocument(
            kind=kind,
            folder=folder_of(path),
            path=path,
            front_matter=_stamped_front_matter(
                front, request=request, version=version, authored_at=now()
            ),
            body=body,
            cost=None,
        ),
        source_key=PROJECT_DOCUMENT_SOURCE_KEY,
    )
    supersedes = await _supersedes(
        conn, workspace_id=request.workspace_id, project_id=request.project_id, path=path
    )
    inserted = await _insert_version(
        conn,
        document_id=document_id,
        workspace_id=request.workspace_id,
        brand_id=request.brand_id,
        project_id=request.project_id,
        folder=folder_of(path),
        path=path,
        kind=kind,
        version=version,
        status="ready",
        artifact_key_=key,
        artifact_sha256=sha,
        supersedes=supersedes,
        race_message=(
            f"another writer published version {version} of {path}; "
            f"re-read {workspace_path} and write again"
        ),
    )
    if inserted:
        await _retire(
            conn,
            workspace_id=request.workspace_id,
            project_id=request.project_id,
            path=path,
            keeping=document_id,
        )
    # The bytes land only now, with the row that cites them at rest: a refused write above leaves
    # no unreferenced object behind, because its artifact row rolls back with the transaction. The
    # twin below still stores its bytes, so the artifact row it did record is never a dangling
    # promise of an object that was never written.
    await _store_bytes(storage, key, data)
    stored = await _stored_document(
        conn,
        workspace_id=request.workspace_id,
        project_id=request.project_id,
        document_id=document_id,
    )
    if stored is None:
        # Nothing landed in *this* scope: the derived id is held by a row this project does not
        # own, so the version was not published here and the caller is told so rather than handed
        # another scope's row.
        raise ProjectDocumentRefused(
            "project_document_version_race", f"the written {path} did not persist"
        )
    return WrittenDocument(
        document_id=stored.document_id,
        path=stored.path,
        version=stored.version,
        workspace_path=workspace_path,
        replayed=not inserted,
    )


async def write_project_plan(
    conn: AsyncConnection,
    storage: StorageBackend,
    request: ProjectPlanWrite,
    *,
    now: Callable[[], datetime] = _utcnow,
) -> WrittenDocument:
    """Store one plan as the next version of ``project/plan.md``. A document like any other.

    Thin over :func:`write_project_document`, and kept only for ``write_project_document@1`` — the
    tool the profile no longer grants but a replayed turn still resolves — so it keeps that tool's
    replay id (:func:`plan_document_id`) rather than the path-derived one.
    """

    return await write_project_document(
        conn,
        storage,
        ProjectDocumentWrite(
            workspace_id=request.workspace_id,
            brand_id=request.brand_id,
            project_id=request.project_id,
            turn_id=request.turn_id,
            user_id=request.user_id,
            path=PLAN_PATH,
            document_text=request.body,
            expected_version=request.expected_version,
        ),
        now=now,
        document_id=plan_document_id(
            turn_id=request.turn_id,
            expected_version=request.expected_version,
            body_sha256=sha256(request.body.encode("utf-8")).hexdigest(),
        ),
    )


async def list_project_documents(
    conn: AsyncConnection, *, workspace_id: str, project_id: str
) -> tuple[ProjectDocumentRow, ...]:
    """This project's own servable documents — the highest such version of each path, in path order.

    Brand-level documents are deliberately absent: this answers "what has this project written for
    itself", and the brand's knowledge is a different surface's question. Read inside one workspace,
    so another tenant's project rows are indistinguishable from absence.
    """

    rows = (
        await conn.execute(
            text(
                f"SELECT DISTINCT ON (path) {_ROW_COLUMNS} FROM brand_knowledge_document "
                "WHERE workspace_id = :workspace_id AND project_id = :project_id "
                "  AND status = ANY(:statuses) AND artifact_key IS NOT NULL "
                "ORDER BY path, version DESC"
            ),
            {
                "workspace_id": workspace_id,
                "project_id": project_id,
                "statuses": list(_SERVABLE_STATUSES),
            },
        )
    ).mappings()
    return tuple(_row(row) for row in rows.all())


async def get_project_document(
    conn: AsyncConnection, *, workspace_id: str, project_id: str, document_id: UUID
) -> ProjectDocumentRow | None:
    """One document of this project by its row id, in any status, or ``None``.

    Absence and staleness are different answers, and only the first is decided here. A row of
    another project or another workspace, and a row whose bytes were never written, are absence —
    indistinguishable from a document that never existed, so neither can be used to probe for what
    another project owns. A superseded, archived, or otherwise unservable row of *this* project is a
    real row and is returned: it is the version the user tagged, and the composer's validation is
    what then refuses it as stale rather than as missing.
    """

    row = await _document(
        conn,
        workspace_id=workspace_id,
        project_id=project_id,
        document_id=document_id,
        servable_only=False,
    )
    if row is None or row["artifact_key"] is None:
        return None
    return _row(row)


async def latest_project_document_version(
    conn: AsyncConnection, *, workspace_id: str, project_id: str, path: str
) -> int | None:
    """The highest servable version of one path in this project — what the Gallery lists."""

    value = (
        await conn.execute(
            text(
                "SELECT version FROM brand_knowledge_document "
                "WHERE workspace_id = :workspace_id AND project_id = :project_id "
                "  AND path = :path AND status = ANY(:statuses) AND artifact_key IS NOT NULL "
                "ORDER BY version DESC LIMIT 1"
            ),
            {
                "workspace_id": workspace_id,
                "project_id": project_id,
                "path": path,
                "statuses": list(_SERVABLE_STATUSES),
            },
        )
    ).scalar()
    return None if value is None else int(value)


async def _document(
    conn: AsyncConnection,
    *,
    workspace_id: str,
    project_id: str,
    document_id: UUID,
    servable_only: bool = True,
    for_update: bool = False,
) -> RowMapping | None:
    """One of *this* project's document versions, or ``None``.

    Scope is part of the identity, not a check applied afterwards: another project's document and a
    document that never existed get the same answer, so neither read nor edit can be used to probe
    for what another project owns.

    ``servable_only=False`` is the editor's read: a version that has been superseded still *exists*,
    and telling its editor "this is no longer the current version" is a truer answer than telling
    them the document is gone.
    """

    return (
        (
            await conn.execute(
                text(
                    f"SELECT {_ROW_COLUMNS}, brand_id, derived_from_document_id "
                    "FROM brand_knowledge_document "
                    "WHERE workspace_id = :workspace_id AND project_id = :project_id "
                    "  AND document_id = :document_id"
                    + (
                        " AND status = ANY(:statuses) AND artifact_key IS NOT NULL"
                        if servable_only
                        else ""
                    )
                    + (" FOR UPDATE" if for_update else "")
                ),
                {
                    "workspace_id": workspace_id,
                    "project_id": project_id,
                    "document_id": document_id,
                    "statuses": list(_SERVABLE_STATUSES),
                },
            )
        )
        .mappings()
        .one_or_none()
    )


async def _front_and_body(
    conn: AsyncConnection,
    storage: StorageBackend,
    *,
    workspace_id: str,
    row: RowMapping,
) -> tuple[dict[str, Any], str]:
    """The document's front matter and its body, read from the verified artifact."""

    # Verified and cached by content (clue_api.knowledge_bytes); a digest that differs from the
    # row's raises DocumentDigestMismatch, which is still the ValueError this read always raised.
    raw = await read_one_knowledge_bytes(
        conn,
        storage,
        workspace_id=workspace_id,
        ref=(str(row["artifact_key"]), str(row["artifact_sha256"])),
    )
    try:
        return parse_front_matter(raw.decode("utf-8"), preserve_body=True)
    except (UnicodeDecodeError, ValueError):
        return {}, raw.decode("utf-8", errors="replace")


async def read_project_document(
    conn: AsyncConnection,
    storage: StorageBackend,
    *,
    workspace_id: str,
    project_id: str,
    document_id: UUID,
    servable_only: bool = True,
) -> tuple[ProjectDocumentRow, dict[str, Any], str] | None:
    """One of this project's documents with its front matter and body, or ``None``.

    ``servable_only=False`` is the editor's read, for the reason :func:`_document` gives: a version
    this project *has* superseded still exists, and serving it with its real ``superseded`` status
    lets an editor holding it rebase, where a 404 would only say it is gone. A row whose bytes were
    never written has nothing to serve and is absent either way.
    """

    row = await _document(
        conn,
        workspace_id=workspace_id,
        project_id=project_id,
        document_id=document_id,
        servable_only=servable_only,
    )
    if row is None or row["artifact_key"] is None:
        return None
    front, body = await _front_and_body(conn, storage, workspace_id=workspace_id, row=row)
    return _row(row), front, body


def _edited_front_matter(
    front: Mapping[str, Any],
    *,
    status: str,
    was_confirmed: bool,
    document_id: UUID,
    version: int,
    new_version: int,
    user_id: str,
    edited_at: datetime,
) -> dict[str, Any]:
    """The document's front matter with the human's edit stamped over it.

    A text edit cannot carry another version's approval forward, so the stamp is dropped when the
    version being edited was the confirmed one; everything the document itself says survives.
    ``version`` is the platform's, restated as the version *this* edit mints, so the number in the
    file is always the number of the file (ruling P).
    """

    stamped = dict(front)
    if was_confirmed:
        for key in _APPROVAL_KEYS:
            stamped.pop(key, None)
    stamped["version"] = new_version
    stamped["status"] = status
    stamped["user_edit"] = {
        "user_id": user_id,
        "edited_at": edited_at.isoformat(),
        "source_document_id": str(document_id),
        "source_version": version,
    }
    return stamped


async def save_project_document(
    conn: AsyncConnection,
    storage: StorageBackend,
    *,
    workspace_id: str,
    project_id: str,
    document_id: UUID,
    body: str,
    expected_revision: int,
    user_id: str,
    now: Callable[[], datetime] = _utcnow,
) -> ProjectDocumentRow:
    """Append one human-edited version of this project's document. The Knowledge PUT, scoped here.

    Never mutates bytes an existing turn or gate pinned: the edit is a new version, and the one it
    came from is retired unless it was ``confirmed`` — a project may still be pinned to exactly
    those bytes, so that row stays servable and the edit returns to ``proposed`` for review
    (ruling I). A plan has no confirmation gate, so it stays ``ready``.

    Raises :class:`ProjectDocumentRefused`: ``project_document_not_found`` when this project owns no
    such servable document, ``project_document_revision_conflict`` when a newer version exists,
    ``project_document_body_empty`` for an empty body.
    """

    if not body.strip():
        raise ProjectDocumentRefused(
            "project_document_body_empty", "the document body is empty; nothing was saved"
        )
    # Serialize competing human saves for this project, and take this lock *before* the document
    # row's: one order for both writers is what keeps the agent's write and this one from
    # deadlocking (see :func:`lock_project`). Other publishers may still race to insert the next
    # version; the unique index remains the final arbiter.
    await lock_project(conn, workspace_id=workspace_id, project_id=project_id)
    row = await _document(
        conn,
        workspace_id=workspace_id,
        project_id=project_id,
        document_id=document_id,
        servable_only=False,
        for_update=True,
    )
    if row is None:
        raise ProjectDocumentRefused(
            "project_document_not_found", "this project has no such editable document"
        )
    if str(row["status"]) not in _SERVABLE_STATUSES or row["artifact_key"] is None:
        # The version being edited has been superseded (or never had bytes): a newer one exists,
        # which is the same answer a stale ``expected_revision`` gets.
        raise ProjectDocumentRefused(
            "project_document_revision_conflict",
            f"{row['path']} has a newer version than the one you edited. The draft was not saved.",
        )
    latest = await conn.scalar(
        text(
            "SELECT MAX(version) FROM brand_knowledge_document "
            "WHERE workspace_id = :workspace_id AND project_id = :project_id AND path = :path"
        ),
        {"workspace_id": workspace_id, "project_id": project_id, "path": str(row["path"])},
    )
    if row["version"] != expected_revision or latest != row["version"]:
        raise ProjectDocumentRefused(
            "project_document_revision_conflict",
            f"{row['path']} is at version {latest}; you expected {expected_revision}. "
            "The draft was not saved.",
        )
    front, original = await _front_and_body(conn, storage, workspace_id=workspace_id, row=row)
    if original == body:
        return _row(row)

    status = "proposed" if row["status"] == "confirmed" else str(row["status"])
    new_version = int(row["version"]) + 1
    key, sha, data = await _record_document(
        conn,
        workspace_id=workspace_id,
        document=KnowledgeDocument(
            kind=str(row["kind"]),
            folder=str(row["folder"]),
            path=str(row["path"]),
            front_matter=_edited_front_matter(
                front,
                status=status,
                was_confirmed=row["status"] == "confirmed",
                document_id=document_id,
                version=int(row["version"]),
                new_version=new_version,
                user_id=user_id,
                edited_at=now(),
            ),
            body=body,
            cost=None,
        ),
        source_key=USER_EDIT_SOURCE_KEY,
    )
    new_id = uuid4()
    try:
        await conn.execute(
            text(
                "INSERT INTO brand_knowledge_document ("
                "  document_id, workspace_id, brand_id, project_id, derived_from_document_id, "
                "  folder, path, kind, version, status, artifact_key, artifact_sha256, "
                "  supersedes_document_id"
                ") VALUES ("
                "  :document_id, :workspace_id, :brand_id, :project_id, :derived_from, "
                "  :folder, :path, :kind, :version, :status, :artifact_key, :artifact_sha256, "
                "  :supersedes"
                ")"
            ),
            {
                "document_id": new_id,
                "workspace_id": workspace_id,
                "brand_id": row["brand_id"],
                "project_id": project_id,
                # The edited version keeps the lineage of the row it was typed over, so a variant's
                # link back to the brand profile it adapts survives a human's pass over it.
                "derived_from": row["derived_from_document_id"],
                "folder": row["folder"],
                "path": row["path"],
                "kind": row["kind"],
                "version": new_version,
                "status": status,
                "artifact_key": key,
                "artifact_sha256": sha,
                "supersedes": document_id,
            },
        )
    except IntegrityError as exc:
        if "brand_knowledge_document_scope_path_version" in str(exc.orig):
            raise ProjectDocumentRefused(
                "project_document_version_race",
                f"another writer published version {new_version} of "
                f"{row['path']}; the draft was not saved",
            ) from exc
        raise
    if row["status"] != "confirmed":
        await conn.execute(
            text(
                "UPDATE brand_knowledge_document SET status = 'superseded', updated_at = now() "
                "WHERE document_id = :document_id"
            ),
            {"document_id": document_id},
        )
    # The bytes land with the row that cites them at rest, and after the version it replaces has
    # been retired: a refused save above leaves no unreferenced object behind.
    await _store_bytes(storage, key, data)
    saved = await _document(
        conn, workspace_id=workspace_id, project_id=project_id, document_id=new_id
    )
    if saved is None:  # pragma: no cover - the INSERT above either landed or raised
        raise ProjectDocumentRefused(
            "project_document_version_race", "the edited document did not persist"
        )
    return _row(saved)


async def create_human_project_document(
    conn: AsyncConnection,
    storage: StorageBackend,
    *,
    workspace_id: str,
    project_id: str,
    path: str,
    kind: str,
    title: str,
    body: str,
    user_id: str,
    now: Callable[[], datetime] = _utcnow,
) -> ProjectDocumentRow:
    """The FIRST version of a path a human writes with no turn behind it (spec 2026-09-19 §2.6).

    Every other version under ``project/`` is born from something: the agent's write names the turn
    that produced it, and :func:`save_project_document` names the version it was typed over. The
    project home's Instructions panel has neither — a human opens an empty panel and types — so
    this writer exists for exactly that act: version 1, ``ready``, authored by a user and no turn.
    ``produced_by_turn_id`` stays NULL, which is what the column's nullability is for.

    It creates and only creates. A path that already has any version — servable or not — is refused
    with ``project_document_exists``, because appending to it is :func:`save_project_document`'s
    job and doing it here would mint a second version 1 the scoped unique index refuses anyway.
    The project's row lock is taken first, in the one order every writer of this project takes it
    (see :func:`lock_project`), so two humans racing the same empty panel serialize: the second
    reads the first's version and is refused rather than deadlocking or duplicating.
    """

    if not body.strip():
        raise ProjectDocumentRefused(
            "project_document_body_empty", "the document body is empty; nothing was saved"
        )
    await lock_project(conn, workspace_id=workspace_id, project_id=project_id)
    existing = await current_document_version(
        conn, workspace_id=workspace_id, project_id=project_id, path=path
    )
    if existing is not None:
        raise ProjectDocumentRefused(
            "project_document_exists",
            f"{path} is already at version {existing}; edit its current version instead",
        )
    brand_id = await conn.scalar(
        text("SELECT brand_id FROM project WHERE workspace_id = :w AND project_id = :p"),
        {"w": workspace_id, "p": project_id},
    )
    if brand_id is None:
        raise ProjectDocumentRefused("project_not_found", "no such project in this workspace")
    authored_at = now()
    key, sha, data = await _record_document(
        conn,
        workspace_id=workspace_id,
        document=KnowledgeDocument(
            kind=kind,
            folder=folder_of(path),
            path=path,
            # The same facts :func:`_edited_front_matter` stamps on a human's later edit, so
            # version 1 and version 2 of this path carry one header and not two shapes.
            front_matter={
                "kind": kind,
                "title": title,
                "status": "ready",
                "version": 1,
                "project_id": project_id,
                "user_edit": {"user_id": user_id, "edited_at": authored_at.isoformat()},
            },
            body=body,
            cost=None,
        ),
        source_key=USER_EDIT_SOURCE_KEY,
    )
    document_id = uuid4()
    await conn.execute(
        text(
            "INSERT INTO brand_knowledge_document ("
            "  document_id, workspace_id, brand_id, project_id, folder, path, kind, version, "
            "  status, artifact_key, artifact_sha256"
            ") VALUES ("
            "  :document_id, :workspace_id, :brand_id, :project_id, :folder, :path, :kind, 1, "
            "  'ready', :artifact_key, :artifact_sha256"
            ")"
        ),
        {
            "document_id": document_id,
            "workspace_id": workspace_id,
            "brand_id": brand_id,
            "project_id": project_id,
            "folder": folder_of(path),
            "path": path,
            "kind": kind,
            "artifact_key": key,
            "artifact_sha256": sha,
        },
    )
    # The bytes land with the row that cites them at rest, exactly as the two writers above do: a
    # refused create leaves no unreferenced object behind.
    await _store_bytes(storage, key, data)
    created = await _document(
        conn,
        workspace_id=workspace_id,
        project_id=project_id,
        document_id=document_id,
        servable_only=True,
    )
    if created is None:  # pragma: no cover - the INSERT above either landed or raised
        raise ProjectDocumentRefused(
            "project_document_version_race", f"the created {path} did not persist"
        )
    return _row(created)
