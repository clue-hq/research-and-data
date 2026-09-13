"""The project library: one project's settled state, compiled once and refreshed when it moves.

A turn's project seeds compile ``status.md``, ``decisions.md`` and every project document *again*,
pin them, and copy them into that one thread's workspace — once per turn, per thread. The library
does it the other way round: the same state is compiled once, beside the threads, at
``<ws>/projects/<project>/library/``, and every thread of the project mounts that one frozen tree
read-only at ``project/``. Nothing is copied into a workspace, and the project's state is written
as many times as it *changes* rather than as many times as it is read.

Four rules make that safe:

* **Digest-refreshed, not time-refreshed.** :func:`project_library_digest` hashes the rows the
  library is compiled from — one cheap round trip per source — and the tree records that digest in
  its ``index.json``. A turn that finds the recorded digest already in place writes nothing at
  all, so the tree every sibling thread is holding descriptors on is not churned by a turn that
  changed nothing.
* **One version per path (W3).** The library is the project's *settled* state, so a document path
  holds exactly one file: the version this project **pinned** where there is a pin, the highest
  servable version otherwise. The per-turn seeds carry a superseded pin's newer sibling as a real
  ``.vN`` file; the library does not, and ``status.md`` says in words that a newer version exists
  rather than naming a file the tree does not hold.
* **Artifacts by reference (W4).** ``artifacts/index.json`` names each design document — id, kind,
  title, status, version, time, origin thread — and carries none of its scene. A design document's
  content is served by the editor, not by a markdown tree an agent reads as context.
* **Read-only.** :class:`~clue_agents.library_tree.LibraryTree` installs each generation
  atomically as 0400 files in 0500 directories, and the mount is opened ``read_only``.

Postgres stays the truth. This tree is a *rendering* of those rows: nothing server-side reads it
to decide anything, and deleting it costs only the rewrite.
"""

from __future__ import annotations

import asyncio
import hashlib
import os
import threading
from collections.abc import Callable
from dataclasses import dataclass, replace
from datetime import datetime
from typing import Any, Final

from pydantic import ValidationError
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from clue_agents import AgentArtifactReader, AgentWorkspaceFactory
from clue_agents.library_tree import LibraryFile, LibraryTree
from clue_api.arv2.icp_confirmation import current_project_icp_pin
from clue_api.arv2.project_documents import lock_project
from clue_api.brand_knowledge_context import (
    KnowledgeDocumentRef,
    current_project_knowledge_refs,
    document_ref,
)
from clue_api.design_leg_wiring import project_design_documents
from clue_api.project_context_files import (
    PROJECT_LIBRARY_PREFIX,
    CompiledProjectFile,
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
    "ProjectLibrarySnapshot",
    "compile_project_library",
    "ensure_project_library",
    "project_library_digest",
]

#: The library's own directory below ``<ws>/projects/<project>/``, and the mount's reserved name.
_LIBRARY_DIR: Final = "library"
_INDEX_NAME: Final = "index.json"
#: Where the project's design artifacts are named, by reference.
ARTIFACT_INDEX_PATH: Final = "artifacts/index.json"
#: One materializer at a time in this process, for the reason the brand library takes the same
#: lock: ``LibraryTree.replace`` reclaims residue by name prefix, so two concurrent replaces of one
#: tree would discard each other's in-flight build. Across processes the DB row lock
#: (:func:`~clue_api.arv2.project_documents.lock_project`) is what serializes two workers, and the
#: install is atomic either way — the loser rewrites a tree, never half of one.
_MATERIALIZE_LOCK: Final = threading.Lock()

_STATUS_SUMMARY: Final = "ICP, products, plan, accounts, discovery and research, as of this turn."
_DECISIONS_SUMMARY: Final = "What the human told this project, in their words."
_ARTIFACTS_SUMMARY: Final = "Design artifacts of this project, by reference."


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

    facts: dict[str, Any] = {
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
                    # path itself and finds the plan by its row path.
                    path=ref.path,
                    version=ref.version,
                    status=ref.status,
                    updated_at=ref.updated_at,
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
            "doc_kind": str(row["doc_kind"]),
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
    files = (
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
    return ProjectLibrarySnapshot(
        files=files,
        index=compile_project_library_index_card(
            project_id=project_id,
            files=files,
            library_sha256=digest,
            artifacts=artifact_count,
        ),
        digest=digest,
    )


# --- materializing it ------------------------------------------------------------------------


async def ensure_project_library(
    conn: AsyncConnection,
    storage: StorageBackend,
    artifacts: AgentArtifactReader,
    workspaces: AgentWorkspaceFactory,
    *,
    workspace_id: str,
    project_id: str,
) -> ProjectLibrarySnapshot:
    """Materialize this project's library if the rows behind it have moved, and describe it.

    The digest comes first, and an installed tree that already records it is returned **as it
    stands**: its own manifest is read back off disk and nothing is compiled, fetched or written.
    That is the cheaper honest option — the alternative (recompile, compare, discard) would pay
    the whole compile, including every document's bytes, on every turn of an unchanged project,
    which is the cost the library exists to remove. The returned snapshot carries no file bodies
    in that case, because nothing moved and the caller has nothing to do with them.

    The rewrite is serialized two ways: the DB row lock every writer of this project takes
    (:func:`~clue_api.arv2.project_documents.lock_project`), so a worker installing a generation
    is not racing a document write it is rendering, and a process-local lock, because
    ``LibraryTree.replace`` reclaims residue by name prefix. The filesystem work runs in a worker
    thread, so the turn's event loop is never held while a tree is written.
    """

    digest = await project_library_digest(conn, workspace_id=workspace_id, project_id=project_id)
    installed = await asyncio.to_thread(
        _read_installed_index, workspaces, workspace_id=workspace_id, project_id=project_id
    )
    if installed is not None and installed.library_sha256 == digest:
        return ProjectLibrarySnapshot(files=(), index=installed, digest=digest)

    snapshot = await compile_project_library(
        conn, storage, artifacts, workspace_id=workspace_id, project_id=project_id
    )
    await lock_project(conn, workspace_id=workspace_id, project_id=project_id)
    await asyncio.to_thread(
        _materialize,
        workspaces,
        workspace_id=workspace_id,
        project_id=project_id,
        snapshot=snapshot,
    )
    return snapshot


def _library_files(snapshot: ProjectLibrarySnapshot) -> tuple[LibraryFile, ...]:
    """The generation as the tree takes it: the manifest, then every file it describes."""

    return (
        LibraryFile(path=_INDEX_NAME, content=snapshot.index.canonical_bytes()),
        *(LibraryFile(path=file.path, content=file.body) for file in snapshot.files),
    )


def _read_installed_index(
    workspaces: AgentWorkspaceFactory,
    *,
    workspace_id: str,
    project_id: str,
) -> ProjectLibraryIndexCard | None:
    """The manifest of the installed generation, or None when there is nothing usable there.

    A manifest this code cannot read — an absent tree, or a card written by a schema this build
    does not know — is *absence*, not an error: the answer is to compile the generation this build
    does understand and install it over the old one.
    """

    document = _with_parent_fd(
        workspaces,
        workspace_id=workspace_id,
        project_id=project_id,
        act=lambda tree: tree.read_index(),
    )
    if document is None:
        return None
    try:
        return ProjectLibraryIndexCard.model_validate(document)
    except ValidationError:
        return None


def _materialize(
    workspaces: AgentWorkspaceFactory,
    *,
    workspace_id: str,
    project_id: str,
    snapshot: ProjectLibrarySnapshot,
) -> None:
    """Install one generation under ``<ws>/projects/<project>/library``, atomically."""

    with _MATERIALIZE_LOCK:
        _with_parent_fd(
            workspaces,
            workspace_id=workspace_id,
            project_id=project_id,
            act=lambda tree: tree.replace(_library_files(snapshot), digest=snapshot.digest),
        )


def _with_parent_fd[T](
    workspaces: AgentWorkspaceFactory,
    *,
    workspace_id: str,
    project_id: str,
    act: Callable[[LibraryTree], T],
) -> T:
    """Open this project's library parent, act on its tree, and close the descriptor.

    The descriptor is anchored and is the caller's to close — one place that owns it, rather than
    a ``try/finally`` at each of the two call sites.
    """

    parent_fd = workspaces.project_parent_fd(workspace_id, project_id)
    try:
        return act(LibraryTree(parent_fd=parent_fd, name=_LIBRARY_DIR))
    finally:
        os.close(parent_fd)
