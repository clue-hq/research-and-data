"""The writer behind the project mount: a file write is a document version, whatever the path.

The agent sees a plain tree at ``project/`` — ``plan.md``, ``audience/icp-gi-dac.md``,
``notes/competitive-brief.md``, and the compiled files beside them — and writes to it with the
ordinary ``write_file``/``edit_file`` tools. Nothing about that tree is a file this process owns.
Every writable path in it is the *rendering* of a versioned row, so a write has to become the act
its owner already implements: appending a version to the document at that path. This module is
where a path becomes that act.

**Any markdown path is a document** (founder ruling 2026-09-14). There is no folder→kind map and no
list of admitted paths: the agent writes what it judges worth writing down, the platform records and
tracks it, and what the document *is* — its kind, its title, and whether the human agreed to pin it
as the plan, the ICP or the personas — is the document's own front matter, not a shape this module
checks. Two paths still refuse, and both are refusals about the *file*, never about its content: a
compiled file (``status.md``, ``decisions.md``, ``index.json``, ``artifacts/``) is read-only because
it is *derived* from rows the model cannot type over, and a path that is not markdown is not
something the project library can serve back.

**One transaction per write, on the bridge.** deepagents calls the backend synchronously and the
document writer is async, so every coroutine here runs on :class:`~clue_agents.bridge.AsyncBridge`
and opens its own transaction against an engine built *on that loop* (ruling P3-1). The engine is a
process singleton, exactly like the bridge: a per-call engine would mean a connection pool per tool
call. It never uses :func:`clue_db.transaction`, whose engine belongs to the serving process's loop
— a connection is bound to the loop that created it, and crossing them is the one thing this seam
exists to avoid.

**The library is re-materialized after every accepted write**, because the version the *next* write
must declare is the one this write just minted, and the model must be able to read back what it
wrote. :meth:`ProjectRootWriter.refresh` returns the fresh ``path → version`` map the mount holds
onto for exactly that.
"""

from __future__ import annotations

import atexit
from collections.abc import AsyncIterator, Mapping
from contextlib import asynccontextmanager, suppress
from dataclasses import dataclass
from typing import Any
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine

from clue_agents import (
    AgentArtifactReader,
    AgentWorkspaceFactory,
    VersionedWriteOutcome,
    VersionedWriteRefused,
)
from clue_agents.bridge import AsyncBridge, process_bridge
from clue_api.agent_turn_wiring import DurableAgentArtifactStore
from clue_api.arv2.knowledge_frontmatter import parse_front_matter
from clue_api.arv2.project_documents import (
    DEFAULT_DOCUMENT_KIND,
    ProjectDocumentRefused,
    ProjectDocumentWrite,
    current_document_version,
    row_path_of,
    write_project_document,
)
from clue_api.project_library import ensure_project_library
from clue_db import ConnFactory, create_engine, database_url
from clue_storage import StorageBackend

__all__ = ["ProjectRootWriter", "bridge_bound_artifact_reader", "bridge_transaction"]

#: Files the library compiles from this project's rows. They are real files in the tree and the
#: model may read them; none of them is a document, so none of them can be written back.
_COMPILED = frozenset({"status.md", "decisions.md", "index.json"})
#: The design artifacts, indexed by reference (W4). Their rows belong to the design subsystem.
_ARTIFACTS_PREFIX = "artifacts/"
#: What a document is written in. The library serves markdown with front matter and nothing else,
#: so a write of anything else would be stored and then served back as something it is not.
_DOCUMENT_SUFFIX = ".md"
#: The mount's own name, stripped off the library index's paths to get the mount-relative ones the
#: backend speaks. See :data:`clue_api.project_context_files.PROJECT_LIBRARY_PREFIX`.
_MOUNT_PREFIX = "project/"
#: Disposing a pool at interpreter exit is a courtesy, not a correctness property — the process is
#: leaving either way — so it is given a short deadline and never allowed to hold up the exit.
_DISPOSE_TIMEOUT_S = 5.0

#: The one engine this process's bridge-side writers share. Built by :func:`bridge_transaction`
#: from a coroutine *running on the bridge loop*, so its asyncpg pool binds to that loop and stays
#: there for its whole life.
_engine: AsyncEngine | None = None


async def _bridge_engine() -> AsyncEngine:
    """The bridge loop's engine, created on first use **on this loop**.

    No lock: this only ever runs on the bridge's single-threaded loop, and there is no ``await``
    between the check and the assignment, so two concurrent callers cannot both build one.
    """

    global _engine
    if _engine is None:
        _engine = create_engine(database_url())
    return _engine


@asynccontextmanager
async def bridge_transaction() -> AsyncIterator[AsyncConnection]:
    """One transaction on the bridge loop's engine; commit on success, roll back on error.

    The shape of :func:`clue_db.transaction`, against this module's engine rather than the serving
    process's. Every write here is one transaction: a refusal raises before any row is at rest (the
    document writer guarantees that), so rolling back is the correct answer either way.
    """

    engine = await _bridge_engine()
    async with engine.begin() as conn:
        yield conn


def _dispose_bridge_engine() -> None:
    """Close the pool at interpreter exit, if one was ever opened.

    Registered once at import, like the bridge's own hook, so it cannot accumulate; it is a no-op
    when no write ever happened. Registered *after* ``clue_agents.bridge``'s hook and therefore run
    before it (atexit is LIFO), which is what lets the dispose still reach a live loop.
    """

    global _engine
    engine, _engine = _engine, None
    if engine is None:
        return
    # Deliberately broad: a closed bridge, a wedged pool or a half-torn-down interpreter are all
    # the same non-event here, and there is nobody left to tell.
    with suppress(Exception):
        process_bridge().run(engine.dispose(), timeout_s=_DISPOSE_TIMEOUT_S)


atexit.register(_dispose_bridge_engine)


def bridge_bound_artifact_reader(
    storage: StorageBackend,
    conn_factory: ConnFactory = bridge_transaction,
) -> AgentArtifactReader:
    """An artifact reader whose database work runs on the same connections the writer's does.

    Ruling P3-14: *every* database access a bridge coroutine makes goes through the bridge's own
    connection factory. The writer itself obeys that through ``conn_factory``, but it is not the
    only thing here that touches the database — :meth:`ProjectRootWriter.refresh` compiles the
    library, and compiling reads the artifact index back through an
    :class:`~clue_agents.ports.AgentArtifactReader`. The serving process's reader defaults to
    :func:`clue_db.transaction`, whose engine belongs to the *worker's* loop, so handing it to the
    writer put a main-loop asyncpg connection on the bridge loop — which died exactly as an
    asyncpg connection dies when it is used from the wrong loop: ``Task … attached to a different
    loop``, raised while the connection was being torn down, after the document row had already
    landed. The model was then told its write had succeeded but could not be re-read, and the turn
    stalled.

    So the reader the writer gets is built here, from the writer's own factory, and the caller
    keeps its ordinary reader for everything that runs on its own loop. The default argument is the
    honest one: a reader built without a factory is for the bridge, because that is the only reason
    this function exists.
    """

    return DurableAgentArtifactStore(storage=storage, conn_factory=conn_factory)


def _front_matter(text: str) -> tuple[dict[str, Any], str]:
    """``(front matter, body)``, or ``({}, text)`` when the text carries no readable block."""

    try:
        return parse_front_matter(text, preserve_body=True)
    except ValueError:
        return {}, text


def _kind(front: Mapping[str, Any]) -> str:
    """What this document calls itself, or plainly a document."""

    declared = front.get("kind")
    return declared if isinstance(declared, str) and declared.strip() else DEFAULT_DOCUMENT_KIND


def _title(front: Mapping[str, Any], body: str, *, path: str) -> str:
    """What this document is called: its own ``title``, else its first heading, else its file name.

    Never invented, and never the platform's word for it — the card the human sees on the turn says
    what the document says it is. The same rule the ICP gate and the documents list already serve,
    stated once more here because the outcome travels to the card before either of them is read.
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
    return path.rsplit("/", 1)[-1].removesuffix(_DOCUMENT_SUFFIX)


@dataclass(frozen=True, slots=True)
class ProjectRootWriter:
    """The project mount's :class:`~clue_agents.versioned_root.VersionedRootWriter`.

    Bound to one turn: the workspace, the brand, the project, the turn and the human on it are all
    ambient here, because the model addresses a *path* and nothing else. That is also what makes
    the replay key work — the document id below is derived from this turn.

    ``conn_factory`` is the seam a test replaces: the default opens its own transaction on the
    bridge loop's engine, and a test injects one that yields its own connection so nothing commits.
    """

    bridge: AsyncBridge
    storage: StorageBackend
    artifacts: AgentArtifactReader
    workspaces: AgentWorkspaceFactory
    workspace_id: str
    brand_id: str
    project_id: str
    turn_id: UUID
    user_id: str
    conn_factory: ConnFactory = bridge_transaction

    # --- the seam -----------------------------------------------------------------------------

    def write(
        self,
        *,
        path: str,
        content: str,
        expected_version: int | None,
    ) -> VersionedWriteOutcome:
        """Take one write of a mount-relative path as a new version of the document it names."""

        if path in _COMPILED or path.startswith(_ARTIFACTS_PREFIX):
            raise VersionedWriteRefused(
                "compiled_file_read_only",
                f"{path} is compiled from the project's rows; it cannot be written",
            )
        if not path.endswith(_DOCUMENT_SUFFIX):
            raise VersionedWriteRefused(
                "unsupported_document_type",
                f"{path} is not markdown; the project's documents are .md files",
            )
        return self.bridge.run(self._write(path, content, expected_version))

    def refresh(self) -> dict[str, int]:
        """Re-materialize the library and return its fresh ``path → version`` map."""

        return self.bridge.run(self._refresh())

    # --- one writer, any path -----------------------------------------------------------------

    async def _write(
        self, path: str, content: str, expected_version: int | None
    ) -> VersionedWriteOutcome:
        """Append one version of the document at ``path``. The whole text goes through.

        The front matter is read twice on purpose: the writer stamps its own facts over the model's
        and stores the result, while the outcome reported back to the turn carries what the
        *document* says it is — its kind and its title — so the card the human sees is named by the
        document rather than by the platform.
        """

        front, body = _front_matter(content)
        row_path = row_path_of(path)
        async with self.conn_factory() as conn:
            try:
                written = await write_project_document(
                    conn,
                    self.storage,
                    ProjectDocumentWrite(
                        workspace_id=self.workspace_id,
                        brand_id=self.brand_id,
                        project_id=self.project_id,
                        turn_id=self.turn_id,
                        user_id=self.user_id,
                        path=row_path,
                        document_text=content,
                        expected_version=expected_version,
                    ),
                )
            except ProjectDocumentRefused as exc:
                raise await self._refuse(
                    conn, exc, name=path, path=row_path, expected=expected_version
                ) from exc
        return VersionedWriteOutcome(
            path=path,
            version=written.version,
            document_id=written.document_id,
            kind=_kind(front),
            status="ready",
            replayed=written.replayed,
            title=_title(front, body, path=path),
        )

    async def _refresh(self) -> dict[str, int]:
        """Materialize the library and read the versions off its manifest.

        A compiled file has no version and is simply absent from the map, which is exactly the
        ``None`` the backend sends for "I read no version of this" — and the refusal the compiled
        paths get above means that ``None`` is never acted on.
        """

        async with self.conn_factory() as conn:
            snapshot = await ensure_project_library(
                conn,
                self.storage,
                self.artifacts,
                self.workspaces,
                workspace_id=self.workspace_id,
                project_id=self.project_id,
            )
        return {
            entry.path.removeprefix(_MOUNT_PREFIX): entry.version
            for entry in snapshot.index.files
            if entry.version is not None
        }

    # --- refusals -----------------------------------------------------------------------------

    async def _refuse(
        self,
        conn: AsyncConnection,
        exc: ProjectDocumentRefused,
        *,
        name: str,
        path: str,
        expected: int | None,
    ) -> VersionedWriteRefused:
        """Translate the document writer's refusal into the one the model is shown.

        Only the codes the *mount* has its own vocabulary for are renamed. A stale version becomes
        ``revision_conflict`` — the token the backend documents as "you are behind, read it again"
        — and its sentence names the version at rest, re-read here rather than parsed back out of
        the writer's message. Everything else keeps its own code, because it is not a concurrency
        problem and telling the model it is would send it into a useless re-read loop.
        """

        if exc.code == "project_document_revision_conflict":
            current = await current_document_version(
                conn, workspace_id=self.workspace_id, project_id=self.project_id, path=path
            )
            return VersionedWriteRefused(
                "revision_conflict",
                f"{name} is at version {current}, you read version {expected} — read it again",
            )
        if exc.code == "project_document_version_race":
            # Another writer took this exact version number mid-flight. The same recovery as a
            # stale read, so the same code — and the writer's own sentence already says so.
            return VersionedWriteRefused("revision_conflict", str(exc))
        if exc.code == "project_document_body_empty":
            return VersionedWriteRefused("body_empty", str(exc))
        return VersionedWriteRefused(exc.code, str(exc))
