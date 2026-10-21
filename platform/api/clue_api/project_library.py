"""The project library: one project's settled state, compiled once and synced when it moves.

The same state is compiled from the project's rows and written into each chat's own ``project/``
folder, beside its ``agent/`` root (F3, spec WS-37; ruling AW-9), and mounted at ``project/``. No
folder is shared with another chat: a chat's folder can be deleted whole without touching anyone
else's turn, and a project's library of a few dozen kilobytes is cheap to hold once per chat.

Five rules make that safe:

* **Digest-refreshed, not time-refreshed.** :func:`project_library_digest` hashes the rows the
  library is compiled from — one cheap round trip per source, plus the project's library epoch
  (AW-20) — and the chat's copy records that digest in its ``index.json``. A turn that finds the
  recorded digest already in place compiles and writes nothing; one that finds a different digest
  writes only the files that changed (WS-36).
* **One version per path (W3).** The library is the project's *settled* state, so a document path
  holds exactly one file: the version this project **pinned** where there is a pin, the highest
  servable version otherwise. The per-turn seeds carry a superseded pin's newer sibling as a real
  ``.vN`` file; the library does not, and ``status.md`` says in words that a newer version exists
  rather than naming a file the tree does not hold.
* **Artifacts by reference (W4).** ``artifacts/index.json`` names each design document — id, kind,
  title, status, version, time, origin thread — and carries none of its scene. A design document's
  content is served by the editor, not by a markdown tree an agent reads as context.
* **Read-only to the agent.** The copy ends frozen (0400 files in 0500 folders); the agent writes
  documents only through the versioned writer, which refreshes this copy afterwards.
* **A turn reads the generation it pinned.** The project can move between two attempts of one
  turn. So a turn's ``agent_turn_project_files`` pin records this generation's files —
  ``index.json`` among them — and a later attempt syncs the chat's copy to exactly those pinned
  files (:func:`sync_pinned_project_library`).

Postgres stays the truth. This tree is a *rendering* of those rows: nothing server-side reads it
to decide anything, and deleting it costs only the rewrite.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import os
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, replace
from datetime import datetime
from typing import Any, Final

from pydantic import ValidationError
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from clue_agents import AgentArtifactReader, AgentWorkspaceFactory, WorkspaceConflict
from clue_agents.tree_sync import sync_directory
from clue_agents.worker_area import ChatScope
from clue_api.arv2.icp_confirmation import current_project_icp_pin
from clue_api.arv2.knowledge_frontmatter import parse_front_matter
from clue_api.arv2.project_documents import lock_project
from clue_api.brand_knowledge_context import (
    KnowledgeDocumentRef,
    current_project_knowledge_refs,
    document_ref,
)
from clue_api.design_leg_wiring import head_of_abm_doc_kind, project_design_documents
from clue_api.project_context_files import (
    PROJECT_LIBRARY_PREFIX,
    CompiledProjectFile,
    PinnedProjectFile,
    ProjectFilesPinConflict,
    ProjectLibraryIndexCard,
    canonical_json,
    compile_project_library_index_card,
    project_workspace_path,
    summary_of,
)
from clue_api.project_status import (
    ProjectDocumentFacts,
    load_project_decisions,
    load_project_status_facts,
    render_decisions_markdown,
    render_status_markdown,
)
from clue_research.stage0 import StatementRoute
from clue_storage import StorageBackend, read_verified_artifact

__all__ = [
    "ARTIFACT_INDEX_PATH",
    "LIBRARY_INDEX_PATH",
    "ProjectLibrarySnapshot",
    "compile_project_library",
    "bump_project_library_epoch",
    "ensure_project_library",
    "installed_project_library_digest",
    "pinned_library_digest",
    "project_library_digest",
    "sync_pinned_project_library",
]

#: The chat folder's own ``project/`` segment, and the mount's reserved name.
_LIBRARY_DIR: Final = "project"
#: The tree's own manifest, inside the tree — a file of the generation like any other, so one
#: turn's pin records it and a later attempt can rebuild the generation from the pin alone.
LIBRARY_INDEX_PATH: Final = "index.json"
#: Where the project's design artifacts are named, by reference.
ARTIFACT_INDEX_PATH: Final = "artifacts/index.json"
# Include compiler changes in fresh-turn cache identity. Historical pins retain
# their exact bytes; only the next unpinned generation gets the new rendering.
_LIBRARY_FORMAT_VERSION: Final = 2

_STATUS_SUMMARY: Final = "ICP, products, plan, accounts, discovery and research, as of this turn."
_DECISIONS_SUMMARY: Final = (
    "Recorded project decisions with source, scope and correction references."
)
_ARTIFACTS_SUMMARY: Final = "Design artifacts of this project, by reference."
_INDEX_SUMMARY: Final = "Index of this project's library."


# --- the refresh digest ----------------------------------------------------------------------

# Every statement the client volunteered about this project's state — the rows ``decisions.md`` is
# rendered from. The table is append-only (a correction is a new row), so a count and the newest
# timestamp move whenever the file would.
_STATEMENTS = text(
    "SELECT count(*) AS total, max(created_at) AS latest FROM volunteered_statement "
    "WHERE workspace_id = :ws AND project_id = :project AND route_kind = :route"
)

# ``status.md``'s account count. Not one of the run tables, and not derivable from them: a human
# approving discovered candidates, or importing a list, writes here and nowhere else.
_ACCOUNTS = text(
    "SELECT count(*) AS total, max(added_at) AS latest FROM project_account "
    "WHERE workspace_id = :ws AND project_id = :project"
)

_LATEST_DISCOVERY = text(
    "SELECT run_id, status, finished_at FROM arv2_discovery_run "
    "WHERE workspace_id = :ws AND project_id = :project "
    "ORDER BY created_at DESC, run_id DESC LIMIT 1"
)

# The latest research run and its jobs in one round trip. ``LEFT JOIN`` so a run with no jobs yet
# still contributes its own status — a run that starts empty and finishes must move the digest.
_LATEST_RESEARCH = text(
    """
    WITH latest AS (
        SELECT run_id, status FROM arv2_research_run
        WHERE workspace_id = :ws AND project_id = :project
        ORDER BY created_at DESC, run_id DESC LIMIT 1
    )
    SELECT latest.run_id, latest.status AS run_status, job.job_id, job.status AS job_status
    FROM latest
    LEFT JOIN arv2_research_job job
      ON job.run_id = latest.run_id AND job.workspace_id = :ws
    ORDER BY job.job_id
    """
)

_LATEST_PERSONA_RUN = text(
    "SELECT run_id, kind, status FROM onboarding_run "
    "WHERE workspace_id = :ws AND project_id = :project AND kind = 'personas' "
    "ORDER BY requested_at DESC, run_id DESC LIMIT 1"
)


_EPOCH = text(
    "SELECT epoch FROM project_library_epoch WHERE workspace_id = :ws AND project_id = :project"
)


async def project_library_digest(
    conn: AsyncConnection,
    *,
    workspace_id: str,
    project_id: str,
) -> str:
    """A cheap digest over every row the library is compiled from, one round trip per source.

    This runs at the start of every turn, so it reads *identity and state*, never content: ids,
    versions, statuses, counts and the newest timestamp of each source. The bytes behind them are
    content-addressed, so a document whose ``(document_id, version, status)`` is unchanged is
    byte-identical, and nothing has to be fetched to know it.

    The contributing sources, each one query:

    1. **This project's servable documents** — ``(document_id, version, status)`` of every
       project-scoped knowledge document (its ICP variants, personas and plan).
    2. **The ICP pin** — the ``document_id`` this project pinned, or null. A re-pin to an older
       confirmed version changes nothing else, and it changes which file the library serves.
    3. **The ``project_state`` statements** — the count and newest ``created_at`` of the rows
       ``decisions.md`` quotes. Append-only, so both move when the file would.
    4. **Project accounts** — the count and newest ``added_at`` behind ``status.md``'s account
       line. (Beyond the sources the plan enumerates, because approving discovered candidates
       moves this and no run row: without it ``status.md`` would keep reporting a stale count,
       which reads as a confident wrong number rather than as staleness.)
    5. **The latest discovery run** — ``(run_id, status, finished_at)``.
    6. **The latest research run** — its ``(run_id, status)`` and the ``(job_id, status)`` of every
       job in it.
    7. **The latest personas onboarding run** — ``(run_id, kind, status)``.
    8. **Every design document of this project** — ``(id, current_version, updated_at)``, the rows
       ``artifacts/index.json`` names.

    The compiler format version also contributes: a new renderer must reach fresh turns even
    when those rows have not changed. So does the project's library epoch (AW-20), which a privacy
    erasure bumps when it changes a file's content without moving any row above. Historical
    per-turn pins keep their original file bytes.

    What it deliberately does *not* watch: a discovery run's per-candidate verdicts. Those move
    ``status.md``'s verified/shown/approved tallies while a run is *running*, and the run's own
    status and ``finished_at`` move when it settles — so the counts a finished run reports are
    refreshed, and a running run's are as of the last refresh.
    """

    params = {"ws": workspace_id, "project": project_id}
    documents = await current_project_knowledge_refs(
        conn, workspace_id=workspace_id, project_id=project_id
    )
    pin = await current_project_icp_pin(conn, workspace_id=workspace_id, project_id=project_id)
    statements = (
        (await conn.execute(_STATEMENTS, {**params, "route": StatementRoute.PROJECT_STATE.value}))
        .mappings()
        .one()
    )
    accounts = (await conn.execute(_ACCOUNTS, params)).mappings().one()
    discovery = (await conn.execute(_LATEST_DISCOVERY, params)).mappings().first()
    research = (await conn.execute(_LATEST_RESEARCH, params)).mappings().all()
    personas = (await conn.execute(_LATEST_PERSONA_RUN, params)).mappings().first()
    design = await project_design_documents(conn, workspace_id=workspace_id, project_id=project_id)
    epoch = (await conn.execute(_EPOCH, params)).scalar_one_or_none()

    facts: dict[str, Any] = {
        "format_version": _LIBRARY_FORMAT_VERSION,
        # AW-20: an erasure that changes a file without moving any row above bumps this.
        "epoch": int(epoch or 0),
        "documents": sorted([str(ref.document_id), ref.version, ref.status] for ref in documents),
        "icp_pin": None if pin is None else str(pin.document_id),
        "statements": [int(statements["total"]), _iso(statements["latest"])],
        "accounts": [int(accounts["total"]), _iso(accounts["latest"])],
        "discovery": (
            None
            if discovery is None
            else [
                str(discovery["run_id"]),
                str(discovery["status"]),
                _iso(discovery["finished_at"]),
            ]
        ),
        "research": (
            None
            if not research
            else {
                "run": [str(research[0]["run_id"]), str(research[0]["run_status"])],
                "jobs": sorted(
                    [str(row["job_id"]), str(row["job_status"])]
                    for row in research
                    if row["job_id"] is not None
                ),
            }
        ),
        "personas": (
            None
            if personas is None
            else [
                str(personas["run_id"]),
                str(personas["kind"]),
                str(personas["status"]),
            ]
        ),
        "artifacts": sorted(
            [str(row["id"]), int(row["current_version"]), _iso(row["updated_at"])] for row in design
        ),
    }
    return hashlib.sha256(canonical_json(facts)).hexdigest()


def _iso(value: datetime | None) -> str | None:
    return None if value is None else value.isoformat()


# --- compiling one generation ----------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class ProjectLibrarySnapshot:
    """One generation of the library: its files, the manifest over them, and their digest."""

    files: tuple[CompiledProjectFile, ...]
    index: ProjectLibraryIndexCard
    digest: str


@dataclass(frozen=True, slots=True)
class _LibraryDocument:
    """One project document as the library serves it: one version, at one plain path."""

    file: CompiledProjectFile
    facts: ProjectDocumentFacts


def _front_matter_of(body: bytes) -> Mapping[str, Any]:
    """One document's front matter, or nothing at all.

    A document whose header cannot be read is not an error here: the bytes are still served, and
    the facts compiled beside them simply say less. Never a refusal — the tree is the model's whole
    view of the project, and an odd header in one file must not empty it.
    """

    try:
        front, _ = parse_front_matter(body.decode("utf-8"), preserve_body=True)
    except (UnicodeDecodeError, ValueError):
        return {}
    return front


def _string(value: Any) -> str | None:
    """One front-matter value, when it is a non-empty string. Anything else says nothing."""

    return value.strip() if isinstance(value, str) and value.strip() else None


def _library_path(row_path: str) -> str:
    """One document's path *inside* the tree: the mounted path with the mount's name removed.

    Derived from :func:`project_workspace_path` rather than spelled out, exactly as the brand
    library derives its tree paths, so the library and the seeds can never fold the ``project/``
    folder segment differently.
    """

    return project_workspace_path(row_path, prefix=PROJECT_LIBRARY_PREFIX).removeprefix(
        PROJECT_LIBRARY_PREFIX
    )


async def _library_documents(
    conn: AsyncConnection,
    storage: StorageBackend,
    *,
    workspace_id: str,
    project_id: str,
) -> tuple[_LibraryDocument, ...]:
    """This project's documents, one version per path, in path order (W3).

    The current set (``current_project_knowledge_refs``) is ``DISTINCT ON (path) … version DESC``
    — the *newest* servable version of each path. That is the right answer for every path except
    the one this project pinned: the pin is the version the human agreed to and every launch
    researches against, so it owns its path here even when a newer version has since been
    authored, and the newer version is reported in words rather than served as a second file.

    A **brand-scoped** pin is served here too, at the plain project path. The brand library is
    shared by every project of the brand, so the newest version owns the name there — this is the
    one place an older pinned brand version stays readable as what this project's ICP *is*.

    Every document's bytes are verified twice, exactly as ``current_project_documents`` verifies
    them: :func:`read_verified_artifact` against its durable artifact row, and then the row's own
    ``artifact_sha256`` against what was read. Serving bytes that are not the bytes the document
    row names would hand the model a document this project never authored, under a name it trusts.
    """

    refs = await current_project_knowledge_refs(
        conn, workspace_id=workspace_id, project_id=project_id
    )
    served: dict[str, KnowledgeDocumentRef] = {ref.path: ref for ref in refs}
    superseded: dict[str, KnowledgeDocumentRef] = {}
    pin = await current_project_icp_pin(conn, workspace_id=workspace_id, project_id=project_id)
    if pin is not None:
        # A pinned row with no bytes is honestly absent: there is nothing to verify or serve.
        pinned = await document_ref(conn, workspace_id=workspace_id, document_id=pin.document_id)
        if pinned is not None:
            current = served.get(pinned.path)
            if current is not None and current.document_id != pinned.document_id:
                superseded[pinned.path] = current
            served[pinned.path] = pinned

    documents: list[_LibraryDocument] = []
    for path in sorted(served):
        ref = served[path]
        record, body = await read_verified_artifact(
            conn, storage, storage_key=ref.artifact_key, workspace_id=workspace_id
        )
        if record.content_sha256 != ref.artifact_sha256:
            raise ProjectFilesPinConflict(
                f"the project document {ref.path!r} no longer matches its stored digest"
            )
        newer = superseded.get(path)
        # The document's own header, read from the bytes already in hand: what it calls itself, and
        # the role a human agreed to pin it under (``role: plan``). ``status.md``'s Plan section
        # reads that role rather than a path (founder ruling 2026-09-14), and this is the one place
        # in the compile where the bytes are open.
        front = _front_matter_of(body)
        documents.append(
            _LibraryDocument(
                file=CompiledProjectFile(
                    path=_library_path(ref.path),
                    kind=ref.kind,
                    body=body,
                    version=ref.version,
                    status=ref.status,
                    summary=summary_of(body),
                ),
                facts=ProjectDocumentFacts(
                    # The **row** path, because ``status.md``'s renderer folds it into a workspace
                    # path itself and falls back to the plan's row path.
                    path=ref.path,
                    version=ref.version,
                    status=ref.status,
                    updated_at=ref.updated_at,
                    role=_string(front.get("role")),
                    title=_string(front.get("title")),
                    newer_version=(
                        None if newer is None or newer.version <= ref.version else newer.version
                    ),
                    newer_status=(
                        None if newer is None or newer.version <= ref.version else newer.status
                    ),
                ),
            )
        )
    return tuple(documents)


async def _artifact_index(
    conn: AsyncConnection,
    *,
    workspace_id: str,
    project_id: str,
) -> tuple[CompiledProjectFile, int]:
    """The project's design artifacts, by reference (W4), and how many there are.

    Read through ``design_leg_wiring.project_design_documents`` — the one statement that knows a
    design document belongs to a project through the legs of that project's threads — so the
    library and the gallery rail cannot disagree about which artifacts a project has.

    What each entry carries is deliberately a *handle*: enough to name the artifact, say what kind
    it is and how far along it is, and ask for it by id. Never ``pages_json``, never any part of
    the scene: that content is megabytes of engine JSON, it is served by the editor, and a turn
    that needs it opens the artifact rather than reading a markdown tree.
    """

    rows = await project_design_documents(conn, workspace_id=workspace_id, project_id=project_id)
    artifacts: list[dict[str, Any]] = []
    for row in rows:
        entry: dict[str, Any] = {
            "id": str(row["id"]),
            "doc_kind": head_of_abm_doc_kind(str(row["doc_kind"])),
            "title": str(row["title"]),
            "status": str(row["status"]),
            "current_version": int(row["current_version"]),
            "updated_at": _iso(row["updated_at"]),
            "origin_thread_id": str(row["origin_thread_id"]),
        }
        artifact_type = row["artifact_type"]
        if artifact_type is not None:
            entry["artifact_type"] = str(artifact_type)
        artifacts.append(entry)
    body = canonical_json({"schema_version": "1", "project_id": project_id, "artifacts": artifacts})
    return (
        CompiledProjectFile(
            path=ARTIFACT_INDEX_PATH,
            kind="artifact-index",
            body=body,
            version=None,
            status="compiled",
            summary=_ARTIFACTS_SUMMARY,
        ),
        len(artifacts),
    )


async def compile_project_library(
    conn: AsyncConnection,
    storage: StorageBackend,
    artifacts: AgentArtifactReader,
    *,
    workspace_id: str,
    project_id: str,
) -> ProjectLibrarySnapshot:
    """Compile one whole generation of this project's library from its rows.

    The digest is taken **first**, before a single row is read for content. A project that moves
    while this runs therefore leaves a generation that is *newer* than the digest recorded beside
    it, so the next refresh sees a difference and rebuilds. Taking it last would record a digest
    newer than the bytes and leave the tree stale until something else moved.

    ``status.md`` and ``decisions.md`` are the plan-1 compilers' own output, with one substitution:
    the documents section is rendered from the documents *this tree serves* (one version per path,
    W3) rather than from the seed surface's two-file spelling, so the file cannot name a ``.vN``
    path the library does not hold.
    """

    digest = await project_library_digest(conn, workspace_id=workspace_id, project_id=project_id)
    documents = await _library_documents(
        conn, storage, workspace_id=workspace_id, project_id=project_id
    )
    facts = await load_project_status_facts(conn, workspace_id=workspace_id, project_id=project_id)
    decisions = await load_project_decisions(
        conn, artifacts, workspace_id=workspace_id, project_id=project_id
    )
    artifact_index, artifact_count = await _artifact_index(
        conn, workspace_id=workspace_id, project_id=project_id
    )
    served = (
        CompiledProjectFile(
            path="status.md",
            kind="project-status",
            # Both summaries are literal: these files are section-structured, so their first prose
            # line is one section's content ("Not confirmed.") and would tell the model something
            # false about the whole file.
            body=render_status_markdown(
                replace(facts, documents=tuple(item.facts for item in documents))
            ).encode(),
            version=None,
            status="compiled",
            summary=_STATUS_SUMMARY,
        ),
        CompiledProjectFile(
            path="decisions.md",
            kind="project-decisions",
            body=render_decisions_markdown(decisions).encode(),
            version=None,
            status="compiled",
            summary=_DECISIONS_SUMMARY,
        ),
        artifact_index,
        *(item.file for item in documents),
    )
    # The manifest describes the files it ships *with*, so it is compiled over them and then
    # joins them as a file of its own. It cannot be one of its own entries — its entry would have
    # to carry the digest of bytes that do not exist until the entry is written — so it is added
    # after, and `_library_files` installs the whole set unchanged. Being a file is what lets one
    # turn's pin record the manifest and a later attempt rebuild the tree from the pin alone.
    index = compile_project_library_index_card(
        project_id=project_id,
        files=served,
        library_sha256=digest,
        artifacts=artifact_count,
    )
    return ProjectLibrarySnapshot(
        files=(
            *served,
            CompiledProjectFile(
                path=LIBRARY_INDEX_PATH,
                kind="project-library-index",
                body=index.canonical_bytes(),
                version=None,
                status="compiled",
                summary=_INDEX_SUMMARY,
            ),
        ),
        index=index,
        digest=digest,
    )


# --- materializing it ------------------------------------------------------------------------


async def ensure_project_library(
    conn: AsyncConnection,
    storage: StorageBackend,
    artifacts: AgentArtifactReader,
    workspaces: AgentWorkspaceFactory,
    *,
    chat: ChatScope,
    snapshot: ProjectLibrarySnapshot | None = None,
) -> ProjectLibrarySnapshot:
    """Sync this chat's ``project/`` copy if the rows behind it have moved, and describe it.

    The digest comes first, and a copy that already records it is returned **as it stands**: its
    own manifest is read back off disk and nothing is compiled, fetched or written. The returned
    snapshot carries no file bodies in that case, because nothing moved and the caller has nothing
    to do with them. When the digest moved, the generation is compiled and only the files that
    changed are written (WS-36).

    The compile takes the DB row lock every writer of this project takes
    (:func:`~clue_api.arv2.project_documents.lock_project`), so it is not racing a document write
    it is rendering. One turn per chat is enforced in Postgres, so the copy has no concurrent
    writer. The filesystem work runs in a worker thread.

    ``snapshot`` is a generation the caller has **already** compiled — the production turn compiles
    one to pin it, and paying for a second identical compile here would double the one cost this
    module exists to remove. Given it, this function only compares its digest to the installed one
    and syncs it if they differ.

    A privacy erasure that changes a file's content without moving any row the digest reads bumps
    the project's library epoch (:func:`bump_project_library_epoch`), which the digest includes,
    so every chat's copy resyncs on its next turn (AW-20).
    """

    digest = (
        snapshot.digest
        if snapshot is not None
        else await project_library_digest(
            conn, workspace_id=chat.workspace_id, project_id=chat.project_id
        )
    )
    installed = await asyncio.to_thread(_read_installed_index, workspaces, chat=chat)
    if installed is not None and installed.library_sha256 == digest:
        return (
            snapshot
            if snapshot is not None
            else ProjectLibrarySnapshot(files=(), index=installed, digest=digest)
        )

    if snapshot is None:
        snapshot = await compile_project_library(
            conn,
            storage,
            artifacts,
            workspace_id=chat.workspace_id,
            project_id=chat.project_id,
        )
    await lock_project(conn, workspace_id=chat.workspace_id, project_id=chat.project_id)
    await asyncio.to_thread(
        _sync_generation,
        workspaces,
        chat=chat,
        files={file.path: file.body for file in snapshot.files},
        digest=snapshot.digest,
    )
    return snapshot


async def bump_project_library_epoch(
    conn: AsyncConnection, *, workspace_id: str, project_id: str
) -> int:
    """Move the project's library epoch on, so every chat's copy resyncs; return the new epoch."""

    row = (
        await conn.execute(
            text(
                "INSERT INTO project_library_epoch (workspace_id, project_id) VALUES (:ws, :p) "
                "ON CONFLICT (workspace_id, project_id) DO UPDATE SET "
                "epoch = project_library_epoch.epoch + 1, updated_at = now() RETURNING epoch"
            ),
            {"ws": workspace_id, "p": project_id},
        )
    ).one()
    return int(row[0])


def _read_installed_index(
    workspaces: AgentWorkspaceFactory, *, chat: ChatScope
) -> ProjectLibraryIndexCard | None:
    """The manifest of the chat's installed copy, or None when there is nothing usable there.

    A manifest this code cannot read — an absent copy, or a card written by a schema this build
    does not know — is *absence*, not an error: the answer is to compile the generation this build
    does understand and sync it over the old one.
    """

    chat_fd = workspaces.chat_dir_fd(chat)
    try:
        try:
            directory_fd = os.open(_LIBRARY_DIR, _DIR_FLAGS, dir_fd=chat_fd)
        except FileNotFoundError:
            return None
        try:
            file_fd = os.open(LIBRARY_INDEX_PATH, _READ_FLAGS, dir_fd=directory_fd)
        except FileNotFoundError:
            return None
        finally:
            os.close(directory_fd)
        try:
            chunks = []
            while chunk := os.read(file_fd, 64 * 1024):
                chunks.append(chunk)
        finally:
            os.close(file_fd)
    finally:
        os.close(chat_fd)
    try:
        return ProjectLibraryIndexCard.model_validate(json.loads(b"".join(chunks)))
    except (ValidationError, ValueError):
        return None


def _sync_generation(
    workspaces: AgentWorkspaceFactory,
    *,
    chat: ChatScope,
    files: Mapping[str, bytes],
    digest: str,
) -> None:
    """Bring ``<chat>/project`` to exactly one generation, writing only what changed.

    The one writer, for the live generation and for a turn's pinned one. A generation whose own
    ``index.json`` does not record ``digest`` is refused rather than served: a pin whose files and
    manifest disagree must not become the agent's library.
    """

    if _recorded_digest(files.get(LIBRARY_INDEX_PATH)) != digest:
        raise WorkspaceConflict("a project library generation must record the digest it is")
    chat_fd = workspaces.chat_dir_fd(chat)
    try:
        sync_directory(chat_fd, _LIBRARY_DIR, files, frozen=True)
    finally:
        os.close(chat_fd)


def _recorded_digest(body: bytes | None) -> str | None:
    if body is None:
        return None
    try:
        document = json.loads(body.decode())
    except (UnicodeDecodeError, ValueError):
        return None
    recorded = document.get("library_sha256") if isinstance(document, dict) else None
    return recorded if isinstance(recorded, str) and recorded else None


_DIR_FLAGS: Final = (
    os.O_RDONLY
    | getattr(os, "O_DIRECTORY", 0)
    | getattr(os, "O_NOFOLLOW", 0)
    | getattr(os, "O_CLOEXEC", 0)
)
_READ_FLAGS: Final = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_CLOEXEC", 0)


# --- replaying one turn's pinned generation ----------------------------------------------------


def pinned_library_digest(files: Sequence[PinnedProjectFile]) -> str | None:
    """The ``library_sha256`` recorded in a pin's own ``index.json``, or None when it has none.

    This is how a second attempt of one turn asks "is the library still the tree I pinned?": the
    pin carries the manifest as a file like any other, and the manifest carries the digest of the
    rows that generation was compiled from. A pin *without* an ``index.json`` is a pin written
    before the library existed (or by a build that did not record one) — absence, not an error, so
    the caller falls back to the live tree rather than failing a turn forever over a receipt it
    cannot use.

    The body is read as plain JSON rather than validated as a
    :class:`~clue_api.project_context_files.ProjectLibraryIndexCard`: that model forbids extra
    keys, so a card written by a *newer* build would fail here and fail identically on every later
    attempt. One key is all this needs.
    """

    body = next((file.body for file in files if file.ref.path == LIBRARY_INDEX_PATH), None)
    if body is None:
        return None
    try:
        document = json.loads(body.decode())
    except (UnicodeDecodeError, ValueError):
        return None
    if not isinstance(document, dict):
        return None
    recorded = document.get("library_sha256")
    return recorded if isinstance(recorded, str) and recorded else None


async def installed_project_library_digest(
    workspaces: AgentWorkspaceFactory, *, chat: ChatScope
) -> str | None:
    """The digest of the generation installed in this chat's ``project/`` copy, if any.

    None means "there is nothing here I can read as a library" — absent, or carrying a manifest
    this build does not understand — which is exactly the case where a pinned set must be synced
    rather than trusted to be already on disk.
    """

    installed = await asyncio.to_thread(_read_installed_index, workspaces, chat=chat)
    return None if installed is None else installed.library_sha256


async def sync_pinned_project_library(
    workspaces: AgentWorkspaceFactory,
    *,
    chat: ChatScope,
    files: Sequence[PinnedProjectFile],
    digest: str,
) -> None:
    """Sync this chat's ``project/`` copy to one turn's pinned generation.

    A retry whose pinned generation is no longer the installed one syncs the chat's own copy to
    exactly the pinned files (only what differs is written). The bytes are the pinned ones,
    already verified against the pin by
    :func:`~clue_api.project_context_files.read_pinned_project_files`, and ``digest`` is the
    ``library_sha256`` the pinned manifest itself records, so a pin whose files and manifest
    disagree is refused rather than served.
    """

    await asyncio.to_thread(
        _sync_generation,
        workspaces,
        chat=chat,
        files={file.ref.path: file.body for file in files},
        digest=digest,
    )
