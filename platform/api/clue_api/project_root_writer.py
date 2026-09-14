"""The writer behind the project mount: a file write is a document version, chosen by its folder.

The agent sees a plain tree at ``project/`` — ``plan.md``, ``audience/icp-gi-dac.md``,
``audience/persona-gi-dac.md``, and the compiled files beside them — and writes to it with the
ordinary ``write_file``/``edit_file`` tools. Nothing about that tree is a file this process owns.
Every writable path in it is the *rendering* of a versioned row, so a write has to become the act
its owner already implements: authoring an ICP, writing a persona, writing the plan. This module
is where a path becomes that act.

**Kinds by folder.** The path is the only thing the backend hands over, so the path decides which
writer runs. ``audience/icp-<key>.md`` is an ICP proposal, ``audience/persona-<key>.md`` is a
persona, ``plan.md`` is the plan, and everything else is refused by name. The two refusals are
different on purpose: a compiled file (``status.md``, ``decisions.md``, ``index.json``,
``artifacts/``) is read-only because it is *derived* from rows the model cannot type over, while an
unrecognized path is simply not a document this project has a writer for — and the message says
which paths are.

**One transaction per write, on the bridge.** deepagents calls the backend synchronously and the
document writers are async, so every coroutine here runs on :class:`~clue_agents.bridge.AsyncBridge`
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
import re
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
from clue_api.arv2.icp_authoring import (
    IcpAuthoringRefused,
    IcpAuthoringRequest,
    author_icp_document,
)
from clue_api.arv2.knowledge_frontmatter import parse_front_matter
from clue_api.arv2.project_documents import (
    ICP_DEFINITION_KIND,
    PERSONA_KIND,
    PLAN_KIND,
    ProjectDocumentRefused,
    ProjectPersonaWrite,
    ProjectPlanWrite,
    current_document_version,
    persona_path,
    write_project_persona,
    write_project_plan,
)
from clue_api.project_library import ensure_project_library
from clue_db import ConnFactory, create_engine, database_url
from clue_storage import StorageBackend

__all__ = ["ProjectRootWriter", "bridge_bound_artifact_reader", "bridge_transaction"]

#: The two authored-document families, keyed off the folder and the file-name prefix the whole lane
#: already reads by (``icp_authoring._path_for`` and ``project_documents.persona_path``). The key is
#: constrained to the ICP-key alphabet here too, so a path that could never *be* an ICP key is an
#: unknown path rather than a refusal from deep inside the authoring writer.
_ICP = re.compile(r"^audience/icp-([a-z0-9-]+)\.md$")
_PERSONA = re.compile(r"^audience/persona-([a-z0-9-]+)\.md$")
#: Files the library compiles from this project's rows. They are real files in the tree and the
#: model may read them; none of them is a document, so none of them can be written back.
_COMPILED = frozenset({"status.md", "decisions.md", "index.json"})
#: The design artifacts, indexed by reference (W4). Their rows belong to the design subsystem.
_ARTIFACTS_PREFIX = "artifacts/"
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
    document writers guarantee that), so rolling back is the correct answer either way.
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


def _derived_from(front: Mapping[str, Any]) -> str | None:
    """The ICP key this draft says it was derived from, under either spelling the skills use."""

    for key in ("derived_from", "derived_from_icp_key"):
        value = front.get(key)
        if isinstance(value, str) and value:
            return value
    return None


@dataclass(frozen=True, slots=True)
class ProjectRootWriter:
    """The project mount's :class:`~clue_agents.versioned_root.VersionedRootWriter`.

    Bound to one turn: the workspace, the brand, the project, the turn and the human on it are all
    ambient here, because the model addresses a *path* and nothing else. That is also what makes
    the replay keys work — every writer below derives its document id from this turn.

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
        if match := _ICP.match(path):
            return self.bridge.run(self._write_icp(match.group(1), content))
        if match := _PERSONA.match(path):
            return self.bridge.run(self._write_persona(match.group(1), content, expected_version))
        if path == "plan.md":
            return self.bridge.run(self._write_plan(content, expected_version))
        raise VersionedWriteRefused(
            "unknown_project_path",
            "write an ICP at audience/icp-<key>.md, personas at audience/persona-<key>.md, "
            "or the plan at plan.md",
        )

    def refresh(self) -> dict[str, int]:
        """Re-materialize the library and return its fresh ``path → version`` map."""

        return self.bridge.run(self._refresh())

    # --- one document kind each ---------------------------------------------------------------

    async def _write_icp(self, icp_key: str, content: str) -> VersionedWriteOutcome:
        """Author one project-scoped ICP proposal.

        ``expected_version`` is deliberately unused: authoring an ICP is not an edit of the version
        the model read, it is a *new* version under that key, and the writer's own scoped unique
        index is the race it has to survive. The lineage the model claims (``derived_from``) is
        read off its own front matter and resolved by the authoring writer, which refuses a key
        that names nothing rather than storing a dangling parent.
        """

        front, _ = _front_matter(content)
        async with self.conn_factory() as conn:
            try:
                authored = await author_icp_document(
                    conn,
                    self.storage,
                    IcpAuthoringRequest(
                        workspace_id=self.workspace_id,
                        brand_id=self.brand_id,
                        project_id=self.project_id,
                        turn_id=self.turn_id,
                        user_id=self.user_id,
                        icp_key=icp_key,
                        document_text=content,
                        scope="project",
                        derived_from_icp_key=_derived_from(front),
                    ),
                )
            except IcpAuthoringRefused as exc:
                # Every authoring refusal is already something the model can act on in its next
                # turn, so its code and its sentence travel to the model unchanged.
                raise VersionedWriteRefused(exc.code, str(exc)) from exc
        return VersionedWriteOutcome(
            path=f"audience/icp-{icp_key}.md",
            version=authored.version,
            document_id=authored.document_id,
            kind=ICP_DEFINITION_KIND,
            # The row's own status, not a repeated "proposed": a replayed call may be reporting a
            # version a human has since confirmed, and what is at rest is the honest answer.
            status=authored.status,
            replayed=authored.replayed,
        )

    async def _write_persona(
        self, icp_key: str, content: str, expected_version: int | None
    ) -> VersionedWriteOutcome:
        """Write one persona for the project's pinned ICP. The whole text goes through."""

        path = persona_path(icp_key)
        async with self.conn_factory() as conn:
            try:
                written = await write_project_persona(
                    conn,
                    self.storage,
                    ProjectPersonaWrite(
                        workspace_id=self.workspace_id,
                        brand_id=self.brand_id,
                        project_id=self.project_id,
                        turn_id=self.turn_id,
                        user_id=self.user_id,
                        icp_key=icp_key,
                        document_text=content,
                        expected_version=expected_version,
                    ),
                )
            except ProjectDocumentRefused as exc:
                raise await self._refuse(
                    conn, exc, name=path, path=path, expected=expected_version
                ) from exc
        return VersionedWriteOutcome(
            path=path,
            version=written.version,
            document_id=written.document_id,
            kind=PERSONA_KIND,
            status="ready",
            replayed=written.replayed,
        )

    async def _write_plan(
        self, content: str, expected_version: int | None
    ) -> VersionedWriteOutcome:
        """Write the plan. Only the *body* goes through (ruling P3-5).

        The plan's front matter is the platform's alone — the version, the scope, the turn — and
        the model reads a file that has one, so it writes one back. Stripping it here is what keeps
        a round-trip through ``edit_file`` from stamping a stale version into the bytes of the new
        one, or from doubling the block on every write.
        """

        _, body = _front_matter(content)
        async with self.conn_factory() as conn:
            try:
                written = await write_project_plan(
                    conn,
                    self.storage,
                    ProjectPlanWrite(
                        workspace_id=self.workspace_id,
                        brand_id=self.brand_id,
                        project_id=self.project_id,
                        turn_id=self.turn_id,
                        user_id=self.user_id,
                        body=body,
                        expected_version=expected_version,
                    ),
                )
            except ProjectDocumentRefused as exc:
                raise await self._refuse(
                    conn,
                    exc,
                    name="plan.md",
                    path="project/plan.md",
                    expected=expected_version,
                ) from exc
        return VersionedWriteOutcome(
            path="plan.md",
            version=written.version,
            document_id=written.document_id,
            kind=PLAN_KIND,
            status="ready",
            replayed=written.replayed,
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
        """Translate a document writer's refusal into the one the model is shown.

        Only the two codes the *mount* has its own vocabulary for are renamed. A stale version
        becomes ``revision_conflict`` — the token the backend documents as "you are behind, read it
        again" — and its sentence names the version at rest, re-read here rather than parsed back
        out of the writer's message. Everything else (an unpinned ICP, front matter about another
        document) keeps its own code, because it is not a concurrency problem and telling the model
        it is would send it into a useless re-read loop.
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
