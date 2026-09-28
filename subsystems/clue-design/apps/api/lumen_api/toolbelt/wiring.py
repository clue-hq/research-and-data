"""The design API's REAL tool invoker (Part II slice D6, ruling R-D6-2).

One write path. Every governed design mutation goes through :class:`DesignToolInvocations`,
which composes the **platform's own** production invoker over the **same durable tables** the
platform uses:

* ``tool_invocation`` — the A9 idempotency record (:class:`clue_toolbelt.DbIdempotencyStore`);
* ``execution`` / ``execution_cursor`` / ``execution_node`` / ``execution_attempt`` /
  ``execution_event`` / ``execution_artifact_ref`` — the C5.1 invocation journal
  (:class:`clue_execution.DbInvocationJournal` over :class:`clue_execution.DbExecutionJournal`);
* ``artifact`` + ``clue_storage`` — the canonical parameter snapshot every invocation is
  artifact-backed by (:class:`clue_execution.CanonicalParameterSnapshotter`).

It is NOT a re-implementation: the primitives are imported, only the *composition* is local,
because ``lumen_api`` may import ``clue_toolbelt``/``clue_execution``/``clue_storage`` (the D5
``clue_fleet`` precedent) but may not import ``clue_api`` (Rule 5 — nothing imports the app
layer). Two things therefore differ from ``clue_api.execution_wiring.build_tool_invoker``:

1. **The connection factory is per-invocation, not process-global.** ``build_tool_invoker``
   takes ``clue_db.transaction``, which reads the process-global engine ``db_lifespan`` installs.
   The design API deliberately never enters that lifespan on the request path (the O5 rule: one
   engine / one connection / one transaction per call, bound to *this* call's loop — see
   ``design_store``). So each invocation owns a private engine for its own event loop, and the
   factory hands the journal/idempotency/artifact writers independent transactions from it.
   Every one of those writers still commits independently, exactly as on the platform.
2. **The run-event transport is subject-keyed, not project-run-keyed (D7).** ``build_tool_invoker``
   wires ``ExecutionRunEventWriter`` → ``clue_research.durable.emit_run_event``, which stamps a
   ``project_run`` subject. A design invocation has no project run, and a design subsystem must not
   import research internals anyway — so the design composition wires
   :class:`_DesignRunEventTransport`, which emits the SAME rows onto the SAME ``run_event`` outbox
   under ``subject_kind='design_run'``. At D6 this was a documented no-op ("design already has its
   own ``design_run_event`` stream"); D7 dropped that stream, so the no-op became the last hole in
   the unified one — a governed design write was journaled but invisible to anyone watching the
   run. It now reaches the stream, fenced by the run's lease exactly like the turn's own progress.
   A REST invocation (a human on a route, no run in flight) still writes nothing: there is no
   subject to key it on, and inventing one would be worse than silence.

The public surface is deliberately SYNCHRONOUS (:meth:`DesignToolInvocations.invoke`): design
routes are ``def``, not ``async def``, and the deep agent's component registry is called from a
worker thread. The bridge is the same ``asyncio.run``-on-a-loopless-thread hop the store uses,
and it dies with the rest of the O5 scaffolding at Part IV / Part-I Step-2.
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Awaitable, Callable
from concurrent.futures import ThreadPoolExecutor
from contextlib import asynccontextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from uuid import UUID

from clue_core import ExecutionId, OperationId, new_operation_id, operation_id_from_key
from clue_db import create_engine
from clue_execution import (
    CanonicalParameterSnapshotter,
    DbExecutionJournal,
    DbInvocationJournal,
    ParameterArtifactState,
    ParameterArtifactStore,
    StoredParameterArtifact,
)
from clue_design.errors import DesignNotFoundError, DesignRunFencedError
from clue_storage import StorageBackend, get_artifact, record_artifact
from clue_toolbelt import (
    Actor,
    DbIdempotencyStore,
    Tool,
    ToolContext,
    ToolInvoker,
    ToolRegistry,
    ToolResult,
)
from py_lumen_obs import get_logger
from sqlalchemy.ext.asyncio import AsyncConnection

from ..design_store import _ensure_workspace
from ..run_stream import PROGRESS_TOPIC, fenced_emit, progress_payload
from .base import DesignToolHost
from .factory import build_design_tools

__all__ = [
    "DesignRunSubject",
    "DesignToolInvocations",
    "design_operation_id",
    "design_tool_host",
]

logger = get_logger("lumen_api.toolbelt")

#: How long an A9 record stays replayable. Mirrors the platform default
#: (``Settings.toolbelt_idempotency_ttl_s``) without importing ``clue_config`` settings into a
#: design module that has its own settings object.
DEFAULT_IDEMPOTENCY_TTL_S = 86400.0


def design_operation_id(workspace_id: str, tool: str, idempotency_key: str | None) -> OperationId:
    """Derive the logical-operation identity for one design invocation.

    With an ``Idempotency-Key`` the id is *stable* (so a retry replays the journal's terminal
    node and the A9 record instead of re-executing); without one it is fresh per call, which is
    exactly today's per-request semantics. Same derivation as the platform's tool route
    (``clue_api.projections_app``), so the two surfaces cannot drift.
    """
    if idempotency_key is None:
        return new_operation_id()
    return operation_id_from_key(workspace_id, f"tool:{tool}:{idempotency_key}")


class _DesignParameterArtifactStore(ParameterArtifactStore):
    """Governed parameter bodies on the same ``artifact`` substrate the platform uses.

    Deliberately a sibling of ``clue_api.execution_wiring.StorageParameterArtifactStore`` rather
    than an import of it (that module is in the app layer). The key contract is identical —
    ``{workspace_id}/{content_sha256}``, row before blob — so a parameter body written here is
    indistinguishable from one written by the platform, including to DSAR erasure.
    """

    def __init__(self, *, storage: StorageBackend, conn_factory: Any) -> None:
        self._storage = storage
        self._conn_factory = conn_factory

    async def persist(
        self,
        *,
        workspace_id: str,
        artifact_key: str,
        content_sha256: str,
        data: bytes,
        media_type: str,
    ) -> None:
        if artifact_key != f"{workspace_id}/{content_sha256}":
            raise ValueError("parameter artifact key does not encode its workspace and hash")
        async with self._conn_factory() as conn:
            artifact = await record_artifact(
                conn,
                storage_key=artifact_key,
                workspace_id=workspace_id,
                content_sha256=content_sha256,
                media_type=media_type,
                size_bytes=len(data),
                source_key="tool_parameters",
            )
            if (
                artifact.workspace_id != workspace_id
                or artifact.content_sha256 != content_sha256
                or artifact.size_bytes != len(data)
            ):
                raise ValueError("parameter artifact key is already bound to incompatible metadata")
            await self._storage.put(artifact_key, data, media_type=media_type)

    async def resolve(
        self,
        *,
        workspace_id: str,
        artifact_key: str,
    ) -> StoredParameterArtifact:
        if not artifact_key.startswith(f"{workspace_id}/"):
            return StoredParameterArtifact(state=ParameterArtifactState.MISSING)
        async with self._conn_factory() as conn:
            artifact = await get_artifact(conn, artifact_key)
        if artifact is None or artifact.workspace_id != workspace_id:
            return StoredParameterArtifact(state=ParameterArtifactState.MISSING)
        if artifact.erased_at is not None or artifact.purged_at is not None:
            return StoredParameterArtifact(state=ParameterArtifactState.ERASED)
        if not await self._storage.exists(artifact_key):
            return StoredParameterArtifact(state=ParameterArtifactState.MISSING)
        return StoredParameterArtifact(
            state=ParameterArtifactState.LIVE,
            data=await self._storage.get(artifact_key),
        )


@dataclass(frozen=True, slots=True)
class DesignRunSubject:
    """The run a batch of tool invocations belongs to, plus the lease generation it is fenced by.

    Present only on the WORKER path: a turn executing under a fleet lease knows both. A REST route
    knows neither (there is no run), which is exactly why the transport below no-ops without one.
    """

    run_id: str
    lease_generation: int | None = None


class _DesignRunEventTransport:
    """Journal → ``run_event`` outbox, keyed on the design run subject (see docstring point 2).

    The journal calls this for every execution event it records, handing it the execution's
    ``project_run_id`` — or, for design, the execution id standing in for one. That id is NOT the
    design run, so it is deliberately discarded: the subject comes from the invoker's own
    :class:`DesignRunSubject`, which is the only thing that knows which turn is driving.

    Two refusals are swallowed rather than propagated, because the JOURNAL is the authoritative
    record and the outbox is a projection of it — a stream problem must never lose an invocation:

    * ``DesignRunFencedError`` — a taken-over worker's tool call. ``fenced_emit`` raises BEFORE it
      writes anything, so the journal transaction is untouched and still commits.
    * ``DesignNotFoundError`` — the run row is gone (or the invocation names a run in another
      tenant). Same reasoning; logged, not raised.
    """

    def __init__(self, subject: DesignRunSubject | None) -> None:
        self._subject = subject

    async def append(
        self,
        conn: AsyncConnection,
        *,
        workspace_id: str,
        run_id: UUID,
        execution_id: ExecutionId,
        topic: str,
        payload: dict[str, Any],
    ) -> None:
        del run_id  # the execution's project-run stand-in; a design leg has no project run.
        subject = self._subject
        if subject is None:
            return
        try:
            await fenced_emit(
                conn,
                workspace_id=workspace_id,
                run_id=subject.run_id,
                topic=PROGRESS_TOPIC,
                payload=progress_payload(topic, dict(payload)),
                expected_generation=subject.lease_generation,
                execution_id=execution_id,
            )
        except (DesignNotFoundError, DesignRunFencedError):
            logger.warning(
                "design_tool.run_event_skipped",
                run_id=subject.run_id,
                execution_id=str(execution_id),
                topic=topic,
            )


def _run_isolated[T](coro: Awaitable[T]) -> T:
    """``asyncio.run`` on a thread that owns no loop — the O5 bridge's hop, verbatim.

    A sync FastAPI endpoint already qualifies; the ingestion pipeline and the fleet handler's
    turn body do not, so those callers get a one-shot worker thread instead. Shares the reasoning
    (and the fate) of ``design_store.run_isolated``.
    """
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(coro)  # type: ignore[arg-type]
    with ThreadPoolExecutor(max_workers=1) as pool:
        return pool.submit(asyncio.run, coro).result()  # type: ignore[arg-type]


def design_tool_host(
    *,
    storage: StorageBackend,
    core: Callable[[], Any],
    engine_cache_dir: Callable[[str], str] | None = None,
    web_export_node_bin: Callable[[], str],
    compiler_node_bin: Callable[[], str],
    compiler_worker_path: Callable[[], Path],
    compiler_timeout_seconds: Callable[[], float],
    compile_fn: Callable[[], Callable[..., dict[str, Any]]],
    ensure_workspace: bool = True,
) -> DesignToolHost:
    """Build the design app's tool host from its already-resolved collaborators."""
    from ..design_store import DesignBlobStore, HybridRepository

    return DesignToolHost(
        repository=lambda ws: HybridRepository(
            workspace_id=ws, ensure_workspace=ensure_workspace
        ),
        blobs=lambda ws: DesignBlobStore(storage, ws, ensure_workspace=ensure_workspace),
        engine_cache_dir=engine_cache_dir,
        core=core,
        web_export_node_bin=web_export_node_bin,
        compiler_node_bin=compiler_node_bin,
        compiler_worker_path=compiler_worker_path,
        compiler_timeout_seconds=compiler_timeout_seconds,
        compile_fn=compile_fn,
    )


class DesignToolInvocations:
    """The design subsystem's single governed write path."""

    def __init__(
        self,
        *,
        host: DesignToolHost,
        storage: StorageBackend,
        idempotency_ttl_s: float = DEFAULT_IDEMPOTENCY_TTL_S,
        run_subject: DesignRunSubject | None = None,
    ) -> None:
        self._host = host
        self._registry = ToolRegistry()
        from .factory import is_default_design_tool
        for tool in build_design_tools(host):
            self._registry.register(tool, make_default=is_default_design_tool(tool))
        self._storage = storage
        self._idempotency_ttl_s = idempotency_ttl_s
        # D7: present on the worker path (a turn is driving), absent on the request path.
        self._run_subject = run_subject

    @property
    def registry(self) -> ToolRegistry:
        return self._registry

    def bound_to(self, subject: DesignRunSubject) -> "DesignToolInvocations":
        """The same tools, with their invocations streamed onto ``subject``'s run (D7).

        A cheap re-composition rather than a mutable field: the run subject is fixed for the life
        of a turn, and an invoker whose subject could change under it would be a race waiting to
        happen. The registry is rebuilt from the same host, so the tools are identical."""
        return DesignToolInvocations(
            host=self._host,
            storage=self._storage,
            idempotency_ttl_s=self._idempotency_ttl_s,
            run_subject=subject,
        )

    def tool(self, name: str) -> Tool:
        return self._registry.get(name)

    def invoke(
        self,
        name: str,
        body: dict[str, Any],
        *,
        workspace_id: str,
        actor: Actor = "human",
        actor_id: str | None = None,
        idempotency_key: str | None = None,
    ) -> ToolResult:
        """Run one governed design tool. Synchronous — see the module docstring."""
        if actor == "agent" and self._run_subject is not None:
            if self._host.repository(workspace_id).cancellation_requested(self._run_subject.run_id):
                from lumen_agent.cancellation import TurnCancelled

                raise TurnCancelled()
        return _run_isolated(
            self._ainvoke(
                name,
                body,
                workspace_id=workspace_id,
                actor=actor,
                actor_id=actor_id,
                idempotency_key=idempotency_key,
            )
        )

    async def _ainvoke(
        self,
        name: str,
        body: dict[str, Any],
        *,
        workspace_id: str,
        actor: Actor,
        actor_id: str | None,
        idempotency_key: str | None,
    ) -> ToolResult:
        engine = create_engine()
        try:

            @asynccontextmanager
            async def conn_factory() -> AsyncIterator[AsyncConnection]:
                async with engine.begin() as conn:
                    yield conn

            # The journal's ``execution.workspace_id`` FK needs the tenant row, and on the design
            # side that row is dev scaffolding the store ensures lazily (Part-IV auth deletes it).
            async with conn_factory() as conn:
                await _ensure_workspace(conn, workspace_id)

            invoker = ToolInvoker(
                registry=self._registry,
                snapshotter=CanonicalParameterSnapshotter(
                    _DesignParameterArtifactStore(
                        storage=self._storage, conn_factory=conn_factory
                    )
                ),
                journal=DbInvocationJournal(
                    conn_factory=conn_factory,
                    repository=DbExecutionJournal(
                        transport=_DesignRunEventTransport(self._run_subject)
                    ),
                ),
                idempotency_store=DbIdempotencyStore(conn_factory=conn_factory),
                idempotency_ttl_s=self._idempotency_ttl_s,
            )
            context = ToolContext(
                workspace_id=workspace_id,
                actor=actor,
                actor_id=actor_id,
                conn_factory=conn_factory,
                operation_id=design_operation_id(workspace_id, name, idempotency_key),
            )
            return await invoker.invoke(
                name, body, context, idempotency_key=idempotency_key
            )
        finally:
            await engine.dispose()
