"""The design API's store: Postgres via ``clue_design``. **SQLite is gone (D2.5B).**

Eight domains: DOCUMENTS (documents / envelopes / op log / snapshots / template revisions /
diagnostics — the D1a tables, D2.2); BRAND (kits + compatibility reports) and ASSETS (the
registry), D2.3; PERSONALIZATION (binding sets / instances / instance batches / the repair
queue) and WEB ACCOUNTS + WEB BATCHES (D2.4A); WEB PUBLISHES + PUBLISH REVISIONS and the
CUSTOM-COMPONENT registry (D2.4B); and since D2.5A AGENT RUNS + RUN EVENTS. That was the LAST
``Repository`` domain still reading SQLite (ingestion jobs never went through this seam — they
moved to ``clue_design.ingestion`` directly at D2.3), so **D2.5B deleted the SQLite substrate
outright**: the ``Repository`` base class, ``connect``/``run_migrations``, and
``apps/api/migrations/*.sql`` no longer exist. :class:`HybridRepository` is now a STANDALONE
class — every method below is a Postgres call, and nothing is inherited. (The name is kept
deliberately: renaming it is D5's job, alongside the bridge's deletion, so this slice is a pure
subtraction with no call-site churn.)

**The O5 bridge** (:class:`DesignStoreBridge`) — DISPOSABLE scaffolding, but **it does NOT die
at D5**, and the earlier "deleted at D5 with the daemon threads" note here was wrong about
which half D5 owns. **RULING (D5 Round C):** D5's promise was durable execution, and it kept it
— the daemon threads ARE gone, in-flight work survives a restart, and the WORKER path is
async-native (a leased ``clue_fleet`` handler on its own event loop, executing the synchronous
design body under ``asyncio.to_thread``). What D5 never promised is an async **request** path.
Every design route is still a synchronous FastAPI endpoint, by design, and a synchronous route
needs a synchronous store: the bridge is what makes that legal. Deleting it would mean rewriting
every route and every call site in ``main.py`` as ``async def`` — a surface change, not a
durable-execution change, and one with no behavioural payoff on its own.

**Where its death now belongs:** the surface work — **Part IV** (mounting the design editor in
the platform shell, where the routes are re-homed and re-shaped anyway) or **Part-I Step-2**
(week-one hygiene, which folds this tree into the root workspace/lint/typing graph). Whichever
lands first is the one that should make the routes ``async def`` and have them call
``clue_design`` directly. Until then the bridge is correct, load-bearing scaffolding rather than
a leftover. See ``docs/specs/design-integration-master-plan.md`` and the O5 ratification note in
``docs/specs/PD-part2-design-substrate.md`` §O5.

Mechanically unchanged: each call is ``asyncio.run`` of exactly ONE ``clue_design`` DAL coroutine
inside ONE engine/connection/transaction created for that call's private event loop (never a
pool from another loop). Anything atomic (allocate-seq + insert; CAS + stack update; scene write
+ asset promotion) is one coroutine — the founder's binding O5 rule. Costs (per-call engine,
awkward cancellation) are accepted. The "a restart still kills in-flight work" cost is the one
that is GONE: since D5 that work is leased fleet work, and a dead worker's run is re-claimed.

**The store** (:class:`HybridRepository`) — every method is one bridge call; main.py's call
sites are unchanged from the staged-port era. **Every cross-domain seam is CLOSED.** The
scene-asset PROMOTION seam closed
at D2.3 (``register_scene_assets`` runs inside the document write's own transaction). The LAST
one — custom-component reference VALIDATION, which ran against the SQLite registry before the
Postgres document write — closed at D2.4B: ``validate_custom_component_reference_changes`` was
not forked, its two reads (``get_web_account``, ``get_custom_component_artifact``) were simply
ported, so validation reads the SAME store the writes land in. (It is still a *separate*
transaction from the document write; the registry is append-only and immutable, so the only
residual interleaving is an account deleted between validation and write, which the
``design_custom_component`` CASCADE then makes structurally consistent anyway.)

**Workspace scoping (O4) is STRICT as of D2.5A.** ``resolve_workspace_id`` reads
``X-Workspace-Id`` and raises ``401 workspace.header_required`` when it is absent — there is no
longer an env fallback on the request path. The silent fallback was the dangerous part of the
staged seam: a caller that forgot the header did not fail, it quietly read and wrote *the dev
tenant's* data, and every request-path bug of that shape is invisible until it is a cross-tenant
incident. ``default_workspace_id()`` survives only for DIRECT store constructions (scripts, the
startup sweep, tests) that have no request to read a header from.

One surface genuinely could not send a header, and named its tenant in the URL instead:

* **Public publish serving** — an anonymous visitor sends no headers at all. O6b (ratified:
  option (a)) put the workspace in the PATH (``/w/{workspace_id}/p/{slug}``), served through
  main.py's ``public_repository`` dependency. **Custom-domain publishing S1 deleted that whole
  surface**: the page origin serves published pages, resolving the tenant from the request
  HOSTNAME through the hostname registry, and this app has no public route left. What survives
  here is the ``ensure_workspace=False`` constructor flag the page origin (and the test helpers
  that read a publish row) still build this store with — an anonymous read must never write, so
  an unknown tenant reads nothing through the fail-closed workspace-scoped reads.

(The run-event SSE stream used to be a second: ``EventSource`` cannot set request headers, so
``GET /agent/runs/{id}/events`` took ``?workspace_id=``. **D7 closed it.** The stream is now opened
with a single-use token minted through a normal header-authenticated ``POST
/agent/runs/{id}/stream-token``, and the workspace is read off the token row — so the one route
that could not carry a header no longer carries a *claim* either. See ``lumen_api.run_stream``.)

The dev workspace row is ensured lazily (once per process per workspace) — Part-IV auth deletes
that scaffolding. (The interim ``/w/{workspace_id}/p/...`` route is already gone; see above.)
"""

from __future__ import annotations

import asyncio
import logging
import os

# THE ONE SURVIVING sqlite3 REFERENCE IN THE DESIGN API (D2.5B deleted the substrate itself).
# ``sqlite3.IntegrityError`` is kept as the API's *constraint-violation exception type*: main.py
# and the route handlers catch it to raise the 409 duplicate-brand-kit / rejected-enum DTOs, and
# a Postgres ``IntegrityError``/``DataError`` is translated INTO it below so those DTOs are
# byte-identical to the SQLite era. Renaming it to a design-native error type is a deliberate
# follow-up (it touches ~8 handler sites), not part of this deletion slice.
import sqlite3
import threading
from collections.abc import Awaitable, Callable
from concurrent.futures import ThreadPoolExecutor
from enum import Enum
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple
from uuid import UUID

from clue_config import Settings
from clue_db import create_engine, database_url
from clue_spine.hostnames import active_custom_hostname as _active_custom_hostname
from clue_spine.hostnames import ensure_system_hostname
from clue_spine.hostnames import lock_system_hostname as _lock_system_hostname
from clue_spine.hostnames import system_hostname as _system_hostname
from clue_spine.pages_settings import get_pages_settings
from py_lumen_obs import get_logger
from clue_storage import StorageBackend
from clue_design import accounts as design_accounts
from clue_design import assets as design_assets
from clue_design import brand as design_brand
from clue_design import components as design_components
from clue_design import diagnostics as design_diagnostics
from clue_design import documents as design_documents
from clue_design import generation as design_generation
from clue_design import history as design_history
from clue_design import personalization as design_personalization
from clue_design import publishes as design_publishes
from clue_design import runs as design_runs
from clue_design import sessions as design_sessions
from clue_design import site_sections as design_site_sections
from clue_design import site_turn_workspace as design_site_turn_workspace
from clue_design import snapshots as design_snapshots
from clue_design import storage as design_storage
from clue_design import thumbnails as design_thumbnails
from clue_design import web_fragments as design_web_fragments
from clue_design.enums import DesignRunKind
from clue_design.errors import (
    DesignArtifactConflictError,
    DesignNotFoundError,
    DesignRunSaveFencedError,
    DesignSourceVersionConflictError,
    DesignVersionConflictError,
)
from fastapi import HTTPException, Request
from sqlalchemy import text
from sqlalchemy.exc import DataError, DBAPIError, IntegrityError
from sqlalchemy.ext.asyncio import AsyncConnection

from .database import (
    CustomComponentArtifactConflict,
    CustomComponentReferenceError,
    CustomComponentSourceVersionConflict,
    DesignResourceVersionConflict,
    FragmentReferenceError,
    NotFoundError,
    WebDocumentVersionConflict,
    WebPublishRevisionConflict,
    custom_component_artifact_candidate,
    custom_component_nodes,
    custom_component_props_schema_issue,
    custom_component_references,
    custom_component_source_candidate,
    fragment_references,
)
from .observability import log_event

JsonObject = Dict[str, Any]

_logger = get_logger("lumen_api.design_store")


class CustodyState(Enum):
    """How far one digest's durable custody actually reaches.

    ``READABLE`` is the only state that means "these bytes are safe". ``ROW_ONLY`` is the
    dangerous one: the ``artifact`` row claims custody the backend cannot honour, which reads as
    healthy to any row-level probe while every byte route 404s.
    """

    READABLE = "readable"
    ROW_ONLY = "row_only"
    ABSENT = "absent"

_DEV_WORKSPACE_ENV = "LUMEN_DEV_WORKSPACE_ID"
_DEV_WORKSPACE_DEFAULT = "ws_lumen_dev"
_WORKSPACE_HEADER = "X-Workspace-Id"

_ensured_workspaces: set[str] = set()
_ensure_lock = threading.Lock()


def default_workspace_id() -> str:
    """The dev workspace for DIRECT store constructions only — scripts, the startup orphan
    sweep, and tests. It is deliberately NOT a request-path fallback (see below)."""
    return os.environ.get(_DEV_WORKSPACE_ENV, _DEV_WORKSPACE_DEFAULT)


def _workspace_required() -> HTTPException:
    return HTTPException(
        status_code=401,
        detail={
            "code": "workspace.header_required",
            "message": f"{_WORKSPACE_HEADER} is required.",
            "header": _WORKSPACE_HEADER,
        },
    )


def resolve_workspace_id(request: Request) -> str:
    """The strict O4 seam (D2.5A): ``X-Workspace-Id`` or 401 — no fallback.

    An absent header used to silently resolve to the dev workspace, which meant a miswired
    caller read and wrote another tenant's rows and looked healthy doing it. Refusing is the
    only answer that keeps the fail-closed DAL honest at the edge.
    """
    workspace_id = request.headers.get(_WORKSPACE_HEADER)
    if not workspace_id:
        raise _workspace_required()
    return workspace_id


def _run_stream() -> Any:
    """``lumen_api.run_stream``, imported lazily — deliberately, for import weight.

    ``run_stream`` reaches the platform outbox through ``clue_execution.run_events``, and importing
    any ``clue_execution`` submodule executes that package's ``__init__``, which pulls the fleet
    worker → ``clue_fleet`` → ``clue_research.durable`` → LangGraph → ``httpx``. This module is the
    design API's most-imported one (``lumen_ingestion.describe`` imports it, and has a hygiene test
    pinning that a describe import pulls neither PIL nor httpx), so a module-level import here would
    make every design process — and every light tool that only wants the store — pay for LangGraph
    at import time. The three run-stream methods below are the only users; they pay on first call.
    """
    from . import run_stream

    return run_stream


def run_isolated[T](coro: "Awaitable[T]") -> T:
    """``asyncio.run`` the coroutine on a thread that owns no event loop.

    PUBLIC on purpose (F3.4, ledger T18-M-13). It was ``_run_isolated`` and had two consumers
    outside this module anyway — the isolation shutter and, in shape, the toolbelt's copy — so
    the underscore was documentation that had stopped being true.

    Normally that is the caller's own thread (a sync FastAPI endpoint runs in the threadpool).
    But some ported call sites run INSIDE a loop: the ingestion pipeline drives capture with its
    own ``asyncio.run(capture(...))`` and the stage reporter writes to the store from the
    callback (D2.3), and the one async endpoint would do the same. ``asyncio.run`` refuses that
    ("cannot be called from a running event loop"), so the call is handed to a one-shot worker
    thread instead — still exactly ONE loop / connection / transaction per call (the O5 rule),
    just not this thread's. Dies with the rest of the bridge — at the surface work (Part IV /
    Part-I Step-2), not at D5; see the module docstring's ruling.
    """
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(coro)  # type: ignore[arg-type]
    with ThreadPoolExecutor(max_workers=1) as pool:
        return pool.submit(asyncio.run, coro).result()  # type: ignore[arg-type]


class _BridgeLoop:
    """ONE long-lived event loop per process, on its own daemon thread, owning ONE pooled engine
    per database URL (brand-context slowness fix, 2026-10-04).

    The bridge used to ``asyncio.run`` every call on a private loop with a private engine: a new
    Postgres connection per store call and, because the shared S3 client lives per event loop, a
    new R2 client per byte read. Production served one brand-context image in a 30 s median with
    300 requests queued behind that setup. Every call now runs on this loop and borrows a pooled
    connection; the binding O5 rule is unchanged — each call is still exactly ONE coroutine in
    ONE connection/transaction, and the pool is only ever used on the loop that created it.

    A forked child (new pid) builds its own loop and engines; an inherited loop thread does not
    exist in the child. A call made FROM this loop's thread cannot wait on the loop it is
    blocking, so :meth:`DesignStoreBridge._run` gives such a call the old one-shot path.
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._pid: int | None = None
        self._loop: asyncio.AbstractEventLoop | None = None
        self._thread: threading.Thread | None = None
        self._engines: Dict[str, Any] = {}

    def _ensure(self) -> asyncio.AbstractEventLoop:
        with self._lock:
            alive = self._thread is not None and self._thread.is_alive()
            if self._loop is None or self._pid != os.getpid() or not alive:
                loop = asyncio.new_event_loop()
                thread = threading.Thread(
                    target=loop.run_forever, name="design-store-bridge", daemon=True
                )
                thread.start()
                self._loop, self._thread, self._pid, self._engines = loop, thread, os.getpid(), {}
            return self._loop

    def owns_current_thread(self) -> bool:
        return (
            self._thread is not None
            and self._pid == os.getpid()
            and threading.current_thread() is self._thread
        )

    def engine(self) -> Any:
        """The pooled engine for the CURRENT database URL (called on the loop thread only)."""
        url = database_url()
        engine = self._engines.get(url)
        if engine is None:
            engine = create_engine(url)
            self._engines[url] = engine
        return engine

    def run[T](self, coro_factory: Callable[[Any], Awaitable[T]]) -> T:
        loop = self._ensure()

        async def on_loop() -> T:
            return await coro_factory(self.engine())

        return asyncio.run_coroutine_threadsafe(on_loop(), loop).result()


_BRIDGE_LOOP = _BridgeLoop()


class DesignStoreBridge:
    """Sync facade over the async ``clue_design`` DAL — one call, one loop, one transaction."""

    def __init__(self, workspace_id: str, *, ensure_workspace: bool = True) -> None:
        self.workspace_id = workspace_id
        # Public (unauthenticated) serving passes False: an anonymous GET must never create a
        # workspace row, so an unknown tenant simply reads nothing and 404s (O6b).
        self.ensure_workspace = ensure_workspace

    def _run[T](self, fn: Callable[[AsyncConnection], Awaitable[T]]) -> T:
        async def _pooled_transaction(engine: Any) -> T:
            # The process-wide bridge loop's pooled engine: still one connection and one
            # transaction for this call (O5), but the connection is borrowed, not opened.
            async with engine.connect() as conn, conn.begin():
                if self.ensure_workspace:
                    await _ensure_workspace(conn, self.workspace_id)
                return await fn(conn)

        async def _one_transaction() -> T:
            # ``create_engine`` (a private engine) rather than ``db_lifespan``: the lifespan
            # registers a PROCESS-GLOBAL engine and refuses re-entry, so two bridge calls on two
            # threads collided with "db_lifespan is already active" (found at D2.4B by the
            # component source-CAS race test, which drives two concurrent writers on purpose).
            # Nothing under the bridge reads the global — every DAL coroutine is handed its
            # connection — so owning the engine locally is both correct and what O5 already
            # requires (one engine/connection/transaction per call, bound to THIS loop).
            engine = create_engine()
            try:
                async with engine.connect() as conn, conn.begin():
                    if self.ensure_workspace:
                        await _ensure_workspace(conn, self.workspace_id)
                    return await fn(conn)
            finally:
                await engine.dispose()

        try:
            bridge = _BRIDGE_LOOP
            if bridge.owns_current_thread():
                # Already ON the bridge loop (a store call from inside a store call): waiting on
                # the loop from its own thread would deadlock, so this one call is one-shot.
                return run_isolated(_one_transaction())
            return bridge.run(_pooled_transaction)
        except DesignNotFoundError as exc:
            raise NotFoundError(exc.kind, exc.key) from exc
        except DesignVersionConflictError as exc:
            # D6 Round C: the DAL has always named the resource ``kind``; documents keep their
            # own exception type (every existing handler catches it), and the round's two new CAS
            # sites — brand-kit version allocation and the batch cursor single-flight — surface
            # as the kind-carrying sibling rather than pretending to be a document.
            if exc.kind == "document":
                raise WebDocumentVersionConflict(
                    exc.key, exc.expected_version, exc.current_version
                ) from exc
            raise DesignResourceVersionConflict(
                exc.kind, exc.key, exc.expected_version, exc.current_version
            ) from exc
        except DesignArtifactConflictError as exc:
            # D2.4B: the immutable custom-component registry's two conflict species keep the
            # exact exception types main.py registers handlers for (409 DTOs), so the port is
            # invisible above this seam. D6 Round C adds the publish-revision species, which
            # shares the taxonomy error but not the component DTO.
            if exc.kind == "web_publish_revision":
                raise WebPublishRevisionConflict(exc.key) from exc
            raise CustomComponentArtifactConflict(exc.key) from exc
        except DesignSourceVersionConflictError as exc:
            raise CustomComponentSourceVersionConflict(
                exc.slug, exc.expected_version, exc.current_version
            ) from exc
        except (IntegrityError, DataError) as exc:
            # Constraint parity for the API's route handlers: a duplicate brand-kit
            # version raised ``sqlite3.IntegrityError`` (→ the 409 duplicate DTO), and so did
            # a rejected ``source`` under the SQLite CHECK the ``design_brand_kit_source``
            # enum now replaces. Both stay one exception type to the API, exactly as before.
            raise sqlite3.IntegrityError(str(exc.orig)) from exc
        except DBAPIError as exc:
            # asyncpg does NOT map an unknown enum label to DataError — it surfaces
            # ``InvalidTextRepresentationError`` as a bare DBAPIError (found at D2.3 by the
            # ingestion suite's "bogus source is still rejected" case). Translate only SQLSTATE
            # class 22 (data exception, e.g. 22P02 invalid_text_representation), which is
            # precisely the family of CHECKs the design enums replaced; anything else is a real
            # database fault and must keep its own type.
            sqlstate = getattr(exc.orig, "sqlstate", None) or ""
            if str(sqlstate).startswith("22"):
                raise sqlite3.IntegrityError(str(exc.orig)) from exc
            raise


async def _hold_site_save(
    conn: AsyncConnection, workspace_id: str, document_id: str, attempt: Any
) -> None:
    """The fence on an agent-run site save, inside the save's own transaction.

    Two halves, both locked ``FOR SHARE`` until the save commits, so neither a takeover's claim
    nor its lease acquire can slip in between this check and the write:

    1. the run row (``clue_design.runs.hold_run_for_save``): ``running`` at exactly this
       attempt's generation, and no version of this document saved by the run yet;
    2. the platform ``work_lease`` row for the run's work id still names this attempt's worker
       and generation. A lapsed lease nobody took is still held (Task 1's reclaim rule). Checked
       only when the attempt names its worker — every fleet and inline-lane attempt does; a
       direct executor call in a test that holds no lease names none.

    Refusals raise :class:`DesignRunSaveFencedError` / :class:`DesignRunAlreadySavedError`;
    nothing is written either way. The fleet import is local for the same reason as in
    :meth:`HybridRepository.create_run_and_offer`.
    """
    work_id = await design_runs.hold_run_for_save(
        conn,
        workspace_id=workspace_id,
        run_id=attempt.run_id,
        document_id=document_id,
        lease_generation=attempt.lease_generation,
    )
    await _hold_attempt_lease(conn, work_id, attempt)


async def _hold_site_attempt(conn: AsyncConnection, workspace_id: str, attempt: Any) -> None:
    """The fence on an attempt touching its site's session memory (site-turn durability,
    2026-10-16, controller ruling S1): the same two halves as :func:`_hold_site_save` — the run
    row ``running`` at exactly this attempt's generation, and its work lease — without the
    one-save-per-run check (the session is saved after the run's own save landed)."""
    work_id = await design_runs.hold_run(
        conn,
        workspace_id=workspace_id,
        run_id=attempt.run_id,
        lease_generation=attempt.lease_generation,
    )
    await _hold_attempt_lease(conn, work_id, attempt)


async def _hold_attempt_lease(conn: AsyncConnection, work_id: Any, attempt: Any) -> None:
    """The work-lease half of an attempt's fence; checked only when the attempt names its worker."""
    if attempt.worker_id is None:
        return
    from clue_fleet.lease import (
        LeaseGeneration,
        WorkId,
        get_work_lease,
        hold_work_lease,
    )

    if await hold_work_lease(
        conn,
        work_id=WorkId(work_id),
        worker_id=attempt.worker_id,
        generation=LeaseGeneration(attempt.lease_generation),
    ):
        return
    lease = await get_work_lease(conn, WorkId(work_id))
    raise DesignRunSaveFencedError(
        attempt.run_id,
        attempt.lease_generation,
        lease.generation if lease is not None else None,
        reason="lease",
    )


async def _ensure_workspace(conn: AsyncConnection, workspace_id: str) -> None:
    """Dev-only scaffolding (dies at Part-IV auth): the dev workspace row must exist for the
    tenancy FKs; ensured once per process per workspace, idempotently.

    It also allocates the workspace's system hostname (custom-domain publishing §4.1), the same
    allocator ``clue_spine.create_workspace`` uses — so a dev workspace scaffolded here has the
    registry row every public page URL is minted from, exactly like a provisioned one.
    """
    with _ensure_lock:
        already = workspace_id in _ensured_workspaces
    if already:
        return
    await conn.execute(
        text(
            "INSERT INTO workspace (workspace_id, name) VALUES (:w, :w)"
            " ON CONFLICT (workspace_id) DO NOTHING"
        ),
        {"w": workspace_id},
    )
    await ensure_system_hostname(
        conn, workspace_id=workspace_id, name=workspace_id, suffix=Settings().pages_system_suffix
    )
    with _ensure_lock:
        _ensured_workspaces.add(workspace_id)


# D5 Round B: ``list_orphaned_runs_across_workspaces`` is DELETED with the daemon threads.
# The startup sweep existed because turns ran on threads inside the API process, so a restart
# left every in-flight run stranded ``running`` forever. Turns are leased fleet work now: a dead
# worker's lease simply expires and a takeover worker re-claims the run through the D5 CAS. A
# sweep that failed those runs at boot would actively destroy recoverable work.


class DesignBlobStore:
    """The design API's BYTE store — platform ``clue_storage`` behind the same O5 bridge (D4).

    The sibling of :class:`HybridRepository`: that one is the row store, this one is the blob
    store, and both reach Postgres through :class:`DesignStoreBridge` (one call, one loop, one
    transaction). Every method is exactly ONE bridged coroutine, because a design byte write is
    ONE logical operation — the ``artifact`` row and the blob put must not be composed from two
    bridge calls (the O5 atomicity rule; splitting them would let a committed row outlive a
    failed put, or a blob land with no row).

    Handed to the call sites that used to take a ``store_root: Path`` into the API-local
    content-addressed tree. It carries its workspace because the storage key IS workspace-scoped
    (``{workspace_id}/design/{sha256}`` — ruling R-D4-2), so byte custody is per-tenant by
    construction rather than by caller discipline. Dies with the bridge when the design API's
    ROUTES become async and call ``clue_design.storage`` directly — the surface work (Part IV /
    Part-I Step-2), not D5; see the module docstring's ruling.
    """

    def __init__(
        self,
        storage: StorageBackend,
        workspace_id: str | None = None,
        *,
        ensure_workspace: bool = True,
    ) -> None:
        self.storage = storage
        self.workspace_id = workspace_id or default_workspace_id()
        self._bridge = DesignStoreBridge(self.workspace_id, ensure_workspace=ensure_workspace)

    def register(self, data: bytes, *, media_type: str, source_key: str) -> str:
        """Store one blob (row before blob, idempotent) and return its storage key."""
        return self._bridge._run(
            lambda conn: design_storage.register_design_bytes(
                conn,
                self.storage,
                workspace_id=self.workspace_id,
                data=data,
                media_type=media_type,
                source_key=source_key,
            )
        )

    def read(self, sha256: str) -> bytes:
        """Read one blob by digest. A missing/erased/foreign-workspace digest raises the
        bridge-translated ``NotFoundError`` (the DAL's fail-closed refusal)."""
        return self._bridge._run(
            lambda conn: design_storage.read_design_bytes(
                conn,
                self.storage,
                workspace_id=self.workspace_id,
                sha256=sha256,
            )
        )

    def read_blob(self, sha256: str) -> Tuple[str, bytes]:
        """``(media_type, data)`` in ONE bridged transaction — the ``artifact`` row's media type
        is what replaced the publish store's ``{digest}.meta.json`` sidecar (ruling R-D4-3)."""
        return self._bridge._run(
            lambda conn: design_storage.read_design_blob(
                conn,
                self.storage,
                workspace_id=self.workspace_id,
                sha256=sha256,
            )
        )

    def exists(self, sha256: str) -> bool:
        """Whether this workspace holds a live artifact row for ``sha256`` (no blob I/O)."""
        return self._bridge._run(
            lambda conn: design_storage.design_bytes_exist(
                conn, workspace_id=self.workspace_id, sha256=sha256
            )
        )

    def custody_states(self, digests: Iterable[str]) -> Dict[str, CustodyState]:
        """Where each digest stands between "a row says so" and "the bytes come back".

        :meth:`exists` answers a question about a ROW. That is the right probe for "may I skip
        recording metadata", and the wrong one for "are these bytes safe", because the row and
        the blob can diverge: a backend whose root moved, a restore that brought the database
        back without the object store, an out-of-band delete. When they do, ``exists`` says yes
        forever and every self-healing pass that trusts it skips the one digest it exists to
        rescue — which is exactly how a generated image stayed 404 on ``/asset-store/{digest}``
        across every later turn while the engine cache still held the bytes.

        Three states rather than a bool because a caller that repairs custody must be able to
        tell a REPAIR from a FIRST registration: the two deserve different behaviour when the
        backend itself is sick (see :func:`~lumen_api.asset_custody.register_scene_asset_backstop`).

        **Batched on purpose.** Every :class:`DesignStoreBridge` call builds and disposes its own
        engine (the O5 rule), so a per-digest probe made scene-persist cost scale in ROUND TRIPS:
        a 50-asset scene meant 50 engines. This is ONE bridged transaction — the row lookups are
        indexed primary-key reads on a single connection, and the backend stats (a HEAD on S3)
        run CONCURRENTLY inside it, so the wall cost is one engine plus one slow HEAD rather than
        fifty of each. Digests are de-duplicated and every one asked for is answered.
        """
        wanted = list(dict.fromkeys(digests))
        if not wanted:
            return {}

        async def _states(conn: AsyncConnection) -> Dict[str, CustodyState]:
            states: Dict[str, CustodyState] = {}
            rowed: List[str] = []
            for digest in wanted:
                if await design_storage.design_bytes_exist(
                    conn, workspace_id=self.workspace_id, sha256=digest
                ):
                    rowed.append(digest)
                else:
                    states[digest] = CustodyState.ABSENT
            readable = await asyncio.gather(*(self._bytes_retrievable(d) for d in rowed))
            for digest, ok in zip(rowed, readable):
                states[digest] = CustodyState.READABLE if ok else CustodyState.ROW_ONLY
            return states

        return self._bridge._run(_states)

    def has_readable_bytes(self, sha256: str) -> bool:
        """Whether this workspace holds live custody of ``sha256`` — row AND retrievable bytes.

        The single-digest reading of :meth:`custody_states`, for the callers that only need the
        verdict (a health check, a verifier). Anything walking a whole scene should batch.
        """
        return self.custody_states([sha256])[sha256] is CustodyState.READABLE

    async def _bytes_retrievable(self, sha256: str) -> bool:
        """Can the backend actually produce this digest's blob? A stat/HEAD, never a read.

        A backend that raises is read as "not retrievable" — the safe direction, since the
        caller's remedy (re-register from a cache) is idempotent — but it is LOGGED, because a
        misconfigured or unreachable backend and a genuinely missing blob are the same answer
        here and only one of them is an operator's problem.
        """
        key = design_storage.design_storage_key(self.workspace_id, sha256)
        try:
            return await self.storage.exists(key)
        except Exception as error:
            log_event(
                _logger,
                logging.WARNING,
                "design_blob.custody_probe_failed",
                workspace_id=self.workspace_id,
                storage_key=key,
                error=str(error),
                error_type=type(error).__name__,
            )
            return False

    def delete(self, sha256: str) -> bool:
        """Destroy this workspace's blob for ``sha256`` and tombstone its row (D4 Round B).

        The asset hard-delete GC's byte-level half. It has already established that no asset
        record and no document scene names the digest; this seam owns the row + blob."""
        return self._bridge._run(
            lambda conn: design_storage.delete_design_bytes(
                conn,
                self.storage,
                workspace_id=self.workspace_id,
                sha256=sha256,
            )
        )


def read_public_design_blob(storage: StorageBackend, sha256: str) -> Tuple[str, bytes]:
    """``(media_type, bytes)`` for ``GET /asset-store/{digest}`` — **workspace-unscoped** (R-D4-7).

    Not a :class:`DesignBlobStore` method precisely because it names no tenant: the route is
    O4-exempt (a published page and an origin-``null`` preview iframe cannot send the header),
    and before D4 it served one global content-addressed tree. Keeping it a free function makes
    that asymmetry impossible to miss at the call site. ``ensure_workspace=False`` — an
    anonymous GET must never create a workspace row. See
    ``clue_design.storage.read_public_design_blob`` for the full reasoning and its limits.
    """
    bridge = DesignStoreBridge(default_workspace_id(), ensure_workspace=False)
    return bridge._run(
        lambda conn: design_storage.read_public_design_blob(conn, storage, sha256=sha256)
    )


class HybridRepository:
    """The design API's store — every domain on Postgres via ``clue_design``.

    Standalone since D2.5B (it subclassed the SQLite ``Repository`` through the staged port; that
    base class is deleted). The name survives this slice on purpose: D5 owns the rename, and
    keeping it here means the deletion touches no call site's *spelling*.
    """

    def __init__(
        self,
        workspace_id: str | None = None,
        *,
        ensure_workspace: bool = True,
    ) -> None:
        # None -> the configured dev workspace (request paths always pass explicitly; the
        # default serves direct constructions in scripts/tests, which read the same env the
        # per-test isolation fixture sets).
        self.workspace_id = workspace_id or default_workspace_id()
        self._bridge = DesignStoreBridge(self.workspace_id, ensure_workspace=ensure_workspace)

    # --- documents ---------------------------------------------------------------------------

    def create_document(
        self,
        scene: JsonObject,
        brand_kit: Optional[JsonObject] = None,
        effective_brand_source: Optional[str] = None,
        effective_brand_mode: Optional[JsonObject] = None,
        doc_kind: str = "scene",
        template_document_id: Optional[str] = None,
        template_doc_version: Optional[int] = None,
        account_id: Optional[str] = None,
    ) -> JsonObject:
        if doc_kind == "web":
            # D2.4B: component references now validate against the SAME Postgres registry the
            # write lands in (the last cross-domain seam) — same fail-fast as before.
            self.validate_custom_component_reference_changes(
                before_web_doc={}, after_web_doc=scene, account_id=account_id
            )
            # F1.2: the same gate for fragment pins, beside its sibling and in the same posture.
            # F2.2: a DERIVATION inherits its template's pins — it copies them, it does not
            # choose them — so a retired fragment must not fail every per-account derivation of
            # every template that pins it.
            self.validate_fragment_reference_changes(
                before_web_doc={},
                after_web_doc=scene,
                inherited_fragment_ids=self.pinned_fragment_ids(template_document_id),
            )
        return self._bridge._run(
            lambda conn: design_documents.create_document(
                conn,
                workspace_id=self.workspace_id,
                scene=scene,
                brand_kit=brand_kit,
                effective_brand_source=effective_brand_source,
                effective_brand_mode=effective_brand_mode,
                doc_kind=doc_kind,
                template_document_id=template_document_id,
                template_doc_version=template_doc_version,
                account_id=account_id,
            )
        )

    def require_document(self, document_id: str) -> JsonObject:
        return self._bridge._run(
            lambda conn: design_documents.get_document(
                conn, workspace_id=self.workspace_id, document_id=document_id
            )
        )

    def replace_scene(
        self,
        document_id: str,
        scene: JsonObject,
        diagnostics: List[JsonObject],
        expected_base_version: Optional[int] = None,
    ) -> JsonObject:
        # D6 Round B (R-D6-B1): `expected_base_version` is FORWARDED (it used to be droppable
        # because this facade never accepted it). PUT /documents/{id}/scene carries no
        # base_version in its request contract, so its caller passes None and that route keeps
        # its documented last-writer-wins window; every caller that DOES hold a base version
        # gets the in-transaction CAS the DAL has always implemented.
        return self._bridge._run(
            lambda conn: design_documents.replace_scene(
                conn,
                workspace_id=self.workspace_id,
                document_id=document_id,
                scene=scene,
                diagnostics=diagnostics,
                expected_base_version=expected_base_version,
            )
        )

    def update_document_state(
        self,
        document_id: str,
        scene: JsonObject,
        diagnostics: List[JsonObject],
        operations: Iterable[JsonObject],
        source: str,
        actor_kind: str,
        actor_id: Optional[str],
        diagnostic_kind: str,
        effective_brand: Optional[Tuple[str, Optional[JsonObject], Optional[JsonObject]]],
        envelope: Optional[JsonObject] = None,
        expected_base_version: Optional[int] = None,
    ) -> JsonObject:
        # D6 Round B (R-D6-B1) — THE scene-path CAS closure. `clue_design.documents
        # .update_document_state` has accepted `expected_base_version` since D2.2 and checks it
        # under the row lock (`_check_cas`), but this facade never took the argument, so every
        # scene write silently degraded to last-writer-wins: the routes' handler-level
        # `require_base_version` pre-check reads the version, then the engine round-trip runs
        # (100s of ms), and only then does the write land — a concurrent writer landing inside
        # that window was lost without a trace. The pre-check stays (it is fast and gives the
        # friendly 409 body); this is the in-transaction truth behind it.
        ops = list(operations)
        return self._bridge._run(
            lambda conn: design_documents.update_document_state(
                conn,
                workspace_id=self.workspace_id,
                document_id=document_id,
                scene=scene,
                diagnostics=diagnostics,
                operations=ops,
                source=source,
                actor_kind=actor_kind,
                actor_id=actor_id,
                diagnostic_kind=diagnostic_kind,
                effective_brand=effective_brand,
                envelope=envelope,
                expected_base_version=expected_base_version,
            )
        )

    def update_web_document(
        self,
        document_id: str,
        web_doc: JsonObject,
        *,
        intent: Optional[str],
        checkpoint_label: Optional[str],
        operations: List[JsonObject],
        inverse_operations: Optional[List[JsonObject]],
        actor_kind: str = "agent",
        source: str = "agent",
        push_undo: bool = True,
        reverts_batch_id: Optional[str] = None,
        reapplies_batch_id: Optional[str] = None,
        expected_base_version: Optional[int] = None,
    ) -> JsonObject:
        before = self.require_document(document_id)
        self.validate_custom_component_reference_changes(
            before_web_doc=before["scene"],
            after_web_doc=web_doc,
            account_id=before.get("account_id"),
        )
        self.validate_fragment_reference_changes(
            before_web_doc=before["scene"], after_web_doc=web_doc
        )
        return self._bridge._run(
            lambda conn: design_documents.update_web_document(
                conn,
                workspace_id=self.workspace_id,
                document_id=document_id,
                web_doc=web_doc,
                intent=intent,
                checkpoint_label=checkpoint_label,
                operations=operations,
                inverse_operations=inverse_operations,
                actor_kind=actor_kind,
                source=source,
                push_undo=push_undo,
                reverts_batch_id=reverts_batch_id,
                reapplies_batch_id=reapplies_batch_id,
                expected_base_version=expected_base_version,
            )
        )

    def update_site_document(
        self,
        document_id: str,
        site: JsonObject,
        *,
        intent: Optional[str],
        checkpoint_label: Optional[str],
        operations: List[JsonObject],
        inverse_operations: Optional[List[JsonObject]],
        actor_kind: str,
        source: str,
        reverts_batch_id: Optional[str] = None,
        reapplies_batch_id: Optional[str] = None,
        expected_base_version: Optional[int] = None,
        attempt: Any = None,
    ) -> JsonObject:
        """The Puck site state write (Wave 2 Contract 2).

        The DAL's website write is kind-agnostic — it reads only the top-level title — so a site
        reuses it, with the same row lock, CAS, stack moves and 50-step cap. Unlike
        ``update_web_document`` it runs no WebDoc fragment or component validators: their page walk
        is WebDoc-shaped (a list of node maps) and means nothing for a site's dict of routes. The
        site's own checks (shape, custody, the site-kit validator) run in the tool before this.

        ``attempt`` (site-turn durability, 2026-10-16) is the run attempt an agent-run save is made
        by (``run_id``, ``lease_generation``, ``worker_id``). With one, the write lands only if, in
        this SAME transaction, the attempt still holds its run — see :func:`_hold_site_save` — and
        its history rows carry the run id. Without one (a human's save) nothing changes."""

        async def write(conn: AsyncConnection) -> JsonObject:
            if attempt is not None:
                await _hold_site_save(conn, self.workspace_id, document_id, attempt)
            return await design_documents.update_web_document(
                conn,
                workspace_id=self.workspace_id,
                document_id=document_id,
                web_doc=site,
                intent=intent,
                checkpoint_label=checkpoint_label,
                operations=operations,
                inverse_operations=inverse_operations,
                actor_kind=actor_kind,
                source=source,
                push_undo=True,
                reverts_batch_id=reverts_batch_id,
                reapplies_batch_id=reapplies_batch_id,
                expected_base_version=expected_base_version,
                actor_id=attempt.run_id if attempt is not None else None,
            )

        return self._bridge._run(write)

    def set_agent_instructions(self, document_id: str, instructions: Optional[str]) -> JsonObject:
        return self._bridge._run(
            lambda conn: design_documents.set_agent_instructions(
                conn,
                workspace_id=self.workspace_id,
                document_id=document_id,
                instructions=instructions,
            )
        )

    def set_layout_managed_editing(self, document_id: str, enabled: bool) -> JsonObject:
        return self._bridge._run(
            lambda conn: design_documents.set_layout_managed_editing(
                conn,
                workspace_id=self.workspace_id,
                document_id=document_id,
                enabled=enabled,
            )
        )

    def set_web_noindex(self, document_id: str, enabled: bool) -> JsonObject:
        """Clone-fidelity F4.3, ruling R-F1: the durable ``noindex`` stamp on ONE web document.

        Governed (``design_set_web_noindex``) like its ``set_layout_managed_editing`` sibling —
        it is a caller-initiated document mutation, and the CLEAR direction is the only door in
        the system that can take the robots meta off a page.
        """
        return self._bridge._run(
            lambda conn: design_documents.set_web_noindex(
                conn,
                workspace_id=self.workspace_id,
                document_id=document_id,
                enabled=enabled,
            )
        )

    def rename_document(self, document_id: str, title: str) -> JsonObject:
        """Artifacts page (2026-09-15): governed (``design_rename_document``) — the row title and
        the document JSON's title together, with a version bump (see the DAL docstring)."""
        return self._bridge._run(
            lambda conn: design_documents.rename_document(
                conn, workspace_id=self.workspace_id, document_id=document_id, title=title
            )
        )

    def set_document_archived(self, document_id: str, enabled: bool) -> JsonObject:
        """Artifacts page (2026-09-15): governed (``design_set_document_archived``); converges."""
        return self._bridge._run(
            lambda conn: design_documents.set_document_archived(
                conn, workspace_id=self.workspace_id, document_id=document_id, enabled=enabled
            )
        )

    def create_web_template(
        self,
        web_doc: JsonObject,
        account_id: Optional[str] = None,
        source_document_id: Optional[str] = None,
    ) -> JsonObject:
        """Clone one website-mode document into a template row.

        ``source_document_id`` (F2.2) names the document being cloned, so the template inherits
        its fragment pins rather than being read as choosing them fresh. Optional and absent-
        tolerant: without it the template is validated strictly, which is what a caller that
        genuinely composed a new document should get.
        """
        self.validate_custom_component_reference_changes(
            before_web_doc={}, after_web_doc=web_doc, account_id=account_id
        )
        self.validate_fragment_reference_changes(
            before_web_doc={},
            after_web_doc=web_doc,
            inherited_fragment_ids=self.pinned_fragment_ids(source_document_id),
        )
        return self._bridge._run(
            lambda conn: design_documents.create_web_template(
                conn,
                workspace_id=self.workspace_id,
                web_doc=web_doc,
                account_id=account_id,
            )
        )

    def list_web_templates(self) -> List[JsonObject]:
        return self._bridge._run(
            lambda conn: design_documents.list_web_templates(conn, workspace_id=self.workspace_id)
        )

    # D6 Round C: ``set_document_account`` is DELETED. It was dead facade surface — no route,
    # worker, agent or pipeline ever called it (the derive path sets the account inside
    # ``create_web_document``), so the D6 gate had a choice between minting a tool for a write
    # nothing performs or removing the write. The DAL function survives for the derive path and
    # for the one test that needs to plant a document's account directly.

    def count_documents_referencing(self, needle: str) -> int:
        return self._bridge._run(
            lambda conn: design_documents.count_documents_referencing(
                conn, workspace_id=self.workspace_id, needle=needle
            )
        )

    # --- document thumbnails (gallery cards) --------------------------------------------------

    def get_document_thumbnail(self, document_id: str, version: int) -> Optional[JsonObject]:
        """The cached thumbnail digest for this document version, or None."""
        return self._bridge._run(
            lambda conn: design_thumbnails.get_document_thumbnail(
                conn,
                workspace_id=self.workspace_id,
                document_id=document_id,
                version=version,
            )
        )

    def record_document_thumbnail(
        self, document_id: str, version: int, *, sha256: str, media_type: str
    ) -> JsonObject:
        """Claim the (document, version) thumbnail slot — idempotent upsert."""
        return self._bridge._run(
            lambda conn: design_thumbnails.record_document_thumbnail(
                conn,
                workspace_id=self.workspace_id,
                document_id=document_id,
                version=version,
                sha256=sha256,
                media_type=media_type,
            )
        )

    # --- brand kits + compatibility reports (D2.3) --------------------------------------------

    def create_brand_kit(
        self,
        brand_kit: JsonObject,
        brand_summary: JsonObject,
        diagnostics: List[JsonObject],
        source: str,
        brand_id: Optional[str] = None,
    ) -> JsonObject:
        """Publish a kit version. ``brand_id`` (D3, optional) pins the O2 brand-spine join
        explicitly; omitted, the DAL resolves-or-creates the workspace's brand."""
        return self._bridge._run(
            lambda conn: design_brand.create_brand_kit(
                conn,
                workspace_id=self.workspace_id,
                brand_kit=brand_kit,
                brand_summary=brand_summary,
                diagnostics=diagnostics,
                source=source,
                brand_id=brand_id,
            )
        )

    def publish_next_brand_kit_version(
        self,
        brand_kit: JsonObject,
        brand_summary: JsonObject,
        diagnostics: List[JsonObject],
        source: str,
        *,
        expected_base_version: int,
        brand_id: Optional[str] = None,
    ) -> JsonObject:
        """Publish the NEXT version of an existing kit, allocated under a lock (D6 Round C).

        The human-curation routes (logo, describe-assets) used to compute ``version + 1`` in
        Python between two transactions. See the DAL for why the lock is taken on the kit's
        lowest-version row and why ``expected_base_version`` is required.
        """
        return self._bridge._run(
            lambda conn: design_brand.publish_next_brand_kit_version(
                conn,
                workspace_id=self.workspace_id,
                brand_kit=brand_kit,
                brand_summary=brand_summary,
                diagnostics=diagnostics,
                source=source,
                expected_base_version=expected_base_version,
                brand_id=brand_id,
            )
        )

    def list_brand_kits(self, all_versions: bool = False) -> List[JsonObject]:
        return self._bridge._run(
            lambda conn: design_brand.list_brand_kits(
                conn, workspace_id=self.workspace_id, all_versions=all_versions
            )
        )

    def require_brand_kit(self, brand_kit_id: str, version: Optional[int] = None) -> JsonObject:
        return self._bridge._run(
            lambda conn: design_brand.get_brand_kit(
                conn,
                workspace_id=self.workspace_id,
                brand_kit_id=brand_kit_id,
                version=version,
            )
        )

    def update_brand_kit_approval(self, brand_kit_id: str, approval_status: str) -> JsonObject:
        return self._bridge._run(
            lambda conn: design_brand.update_brand_kit_approval(
                conn,
                workspace_id=self.workspace_id,
                brand_kit_id=brand_kit_id,
                approval_status=approval_status,
            )
        )

    def create_brand_compatibility_report(
        self,
        report_id: str,
        from_brand_kit: JsonObject,
        to_brand_kit: JsonObject,
        report: JsonObject,
        diagnostics: List[JsonObject],
    ) -> JsonObject:
        return self._bridge._run(
            lambda conn: design_brand.create_brand_compat_report(
                conn,
                workspace_id=self.workspace_id,
                report_id=report_id,
                from_brand_kit=from_brand_kit,
                to_brand_kit=to_brand_kit,
                report=report,
                diagnostics=diagnostics,
            )
        )

    def require_brand_compatibility_report(self, report_id: str) -> JsonObject:
        return self._bridge._run(
            lambda conn: design_brand.get_brand_compat_report(
                conn, workspace_id=self.workspace_id, report_id=report_id
            )
        )

    # --- asset registry (D2.3) ----------------------------------------------------------------

    def create_asset_record(self, record: JsonObject) -> JsonObject:
        return self._bridge._run(
            lambda conn: design_assets.create_asset_record(
                conn, workspace_id=self.workspace_id, record=record
            )
        )

    def create_asset_records(self, records: List[JsonObject]) -> List[str]:
        """Register many asset records in ONE transaction; returns their ids (D6 Round C).

        The ingestion worker promotes every asset a capture produced in one gesture. Looping the
        single-record facade would be one transaction — and, once governed, one private engine
        and one journal execution — per captured image.
        """
        deduped: List[JsonObject] = []
        seen: set = set()
        for record in records:
            asset_id = str(record["id"])
            if asset_id in seen:
                continue
            seen.add(asset_id)
            deduped.append(record)

        async def _write(conn: AsyncConnection) -> List[str]:
            written: List[str] = []
            for record in deduped:
                stored = await design_assets.create_asset_record(
                    conn, workspace_id=self.workspace_id, record=record
                )
                written.append(str(stored["asset"]["id"]))
            return written

        return self._bridge._run(_write)

    def require_asset_record(self, asset_id: str) -> JsonObject:
        return self._bridge._run(
            lambda conn: design_assets.get_asset_record(
                conn, workspace_id=self.workspace_id, asset_id=asset_id
            )
        )

    def get_asset_records(self, asset_ids: List[str]) -> Dict[str, JsonObject]:
        """Many asset records in ONE statement; ids that are not visible are simply absent."""
        return self._bridge._run(
            lambda conn: design_assets.get_asset_records(
                conn, workspace_id=self.workspace_id, asset_ids=asset_ids
            )
        )

    def list_asset_records(
        self,
        kind: Optional[str] = None,
        q: Optional[str] = None,
        include_archived: bool = False,
        limit: int = 50,
        offset: int = 0,
    ) -> List[JsonObject]:
        return self._bridge._run(
            lambda conn: design_assets.list_asset_records(
                conn,
                workspace_id=self.workspace_id,
                kind=kind,
                q=q,
                include_archived=include_archived,
                limit=limit,
                offset=offset,
            )
        )

    def update_asset_status(self, asset_id: str, status: str) -> JsonObject:
        return self._bridge._run(
            lambda conn: design_assets.update_asset_status(
                conn, workspace_id=self.workspace_id, asset_id=asset_id, status=status
            )
        )

    def delete_asset_record(self, asset_id: str) -> None:
        self._bridge._run(
            lambda conn: design_assets.delete_asset_record(
                conn, workspace_id=self.workspace_id, asset_id=asset_id
            )
        )

    def count_assets_with_digest(
        self, digest_value: str, exclude_asset_id: Optional[str] = None
    ) -> int:
        return self._bridge._run(
            lambda conn: design_assets.count_assets_with_digest(
                conn,
                workspace_id=self.workspace_id,
                digest_value=digest_value,
                exclude_asset_id=exclude_asset_id,
            )
        )

    # D6 Round C: ``register_scene_assets`` is DELETED from the facade for the same reason as
    # ``set_document_account`` — it had zero callers anywhere in the tree. Every scene-persist
    # path calls ``clue_design.assets.register_scene_assets`` IN-TRANSACTION (D2.3), which is
    # where scene asset promotion belongs; the facade wrapper was a second, unused way to do it
    # in its own transaction. The DAL function is untouched.

    def get_generation_result(self, generation_key: str) -> Optional[JsonObject]:
        """The pre-spend generation-cache probe (D6 Round C): a hit's LIVE asset, or ``None``.

        A read, so it is deliberately NOT a tool: the route consults it BEFORE calling a paid
        provider, and the write that claims the key is governed by
        ``design_register_generated_asset``.
        """
        return self._bridge._run(
            lambda conn: design_generation.get_generation_result(
                conn, workspace_id=self.workspace_id, generation_key=generation_key
            )
        )

    def record_generation_result(
        self, generation_key: str, record: JsonObject
    ) -> JsonObject:
        """Register a generated asset AND claim its ledger key — ONE transaction (D6 Round C)."""
        return self._bridge._run(
            lambda conn: design_generation.record_generation_result(
                conn,
                workspace_id=self.workspace_id,
                generation_key=generation_key,
                record=record,
            )
        )

    # --- scene-mode personalization (D2.4) ----------------------------------------------------

    def upsert_binding_set(
        self, binding: JsonObject, status: str, diagnostics: List[JsonObject]
    ) -> JsonObject:
        return self._bridge._run(
            lambda conn: design_personalization.upsert_binding_set(
                conn,
                workspace_id=self.workspace_id,
                binding=binding,
                status=status,
                diagnostics=diagnostics,
            )
        )

    def require_binding_set(self, binding_set_id: str) -> JsonObject:
        return self._bridge._run(
            lambda conn: design_personalization.get_binding_set(
                conn, workspace_id=self.workspace_id, binding_set_id=binding_set_id
            )
        )

    def list_binding_sets(self, template_revision_id: Optional[str] = None) -> List[JsonObject]:
        return self._bridge._run(
            lambda conn: design_personalization.list_binding_sets(
                conn,
                workspace_id=self.workspace_id,
                template_revision_id=template_revision_id,
            )
        )

    def delete_binding_set(self, binding_set_id: str) -> None:
        self._bridge._run(
            lambda conn: design_personalization.delete_binding_set(
                conn, workspace_id=self.workspace_id, binding_set_id=binding_set_id
            )
        )

    def upsert_instance(self, instance: JsonObject) -> JsonObject:
        """The derived instance's revision/binding/batch references are REAL composite FKs
        now (D1d), so a dangling reference surfaces as ``sqlite3.IntegrityError`` through the
        bridge's constraint-parity translation rather than as a silent orphan row."""
        return self._bridge._run(
            lambda conn: design_personalization.upsert_instance(
                conn, workspace_id=self.workspace_id, instance=instance
            )
        )

    def require_instance(self, instance_id: str) -> JsonObject:
        return self._bridge._run(
            lambda conn: design_personalization.get_instance(
                conn, workspace_id=self.workspace_id, instance_id=instance_id
            )
        )

    def list_instances(
        self,
        template_revision_id: Optional[str] = None,
        batch_id: Optional[str] = None,
    ) -> List[JsonObject]:
        return self._bridge._run(
            lambda conn: design_personalization.list_instances(
                conn,
                workspace_id=self.workspace_id,
                template_revision_id=template_revision_id,
                batch_id=batch_id,
            )
        )

    def create_batch(self, batch: JsonObject) -> JsonObject:
        return self._bridge._run(
            lambda conn: design_personalization.create_instance_batch(
                conn, workspace_id=self.workspace_id, batch=batch
            )
        )

    def update_batch_progress(
        self,
        batch_id: str,
        cursor: int,
        status: str,
        counts: JsonObject,
        manifest: List[JsonObject],
        diagnostics: List[JsonObject],
        expected_cursor: Optional[int] = None,
    ) -> JsonObject:
        """One chunk's progress. ``expected_cursor`` is the D6 Round C single-flight CAS."""
        return self._bridge._run(
            lambda conn: design_personalization.update_instance_batch_progress(
                conn,
                workspace_id=self.workspace_id,
                batch_id=batch_id,
                cursor=cursor,
                status=status,
                counts=counts,
                manifest=manifest,
                diagnostics=diagnostics,
                expected_cursor=expected_cursor,
            )
        )

    def require_batch(self, batch_id: str) -> JsonObject:
        return self._bridge._run(
            lambda conn: design_personalization.get_instance_batch(
                conn, workspace_id=self.workspace_id, batch_id=batch_id
            )
        )

    def upsert_repair_request(self, repair: JsonObject) -> JsonObject:
        return self._bridge._run(
            lambda conn: design_personalization.upsert_repair_request(
                conn, workspace_id=self.workspace_id, repair=repair
            )
        )

    def list_repair_queue(
        self, template_revision_id: str, status: Optional[str] = None
    ) -> List[JsonObject]:
        return self._bridge._run(
            lambda conn: design_personalization.list_repair_queue(
                conn,
                workspace_id=self.workspace_id,
                template_revision_id=template_revision_id,
                status=status,
            )
        )

    # --- web accounts + web batches (D2.4) ----------------------------------------------------

    def create_web_account(
        self,
        account_id: str,
        name: str,
        domain: Optional[str],
        logo_asset_id: Optional[str],
        data: JsonObject,
        notes: Optional[str],
    ) -> JsonObject:
        return self._bridge._run(
            lambda conn: design_accounts.create_web_account(
                conn,
                workspace_id=self.workspace_id,
                account_id=account_id,
                name=name,
                domain=domain,
                logo_asset_id=logo_asset_id,
                data=data,
                notes=notes,
            )
        )

    def get_web_account(self, account_id: str) -> Optional[JsonObject]:
        return self._bridge._run(
            lambda conn: design_accounts.get_web_account(
                conn, workspace_id=self.workspace_id, account_id=account_id
            )
        )

    def require_web_account(self, account_id: str) -> JsonObject:
        return self._bridge._run(
            lambda conn: design_accounts.require_web_account(
                conn, workspace_id=self.workspace_id, account_id=account_id
            )
        )

    def list_web_accounts(self) -> List[JsonObject]:
        return self._bridge._run(
            lambda conn: design_accounts.list_web_accounts(conn, workspace_id=self.workspace_id)
        )

    def update_web_account(self, account_id: str, patch: JsonObject) -> JsonObject:
        return self._bridge._run(
            lambda conn: design_accounts.update_web_account(
                conn,
                workspace_id=self.workspace_id,
                account_id=account_id,
                patch=patch,
            )
        )

    def delete_web_account(self, account_id: str) -> None:
        """Delete the Postgres account row.

        Since D2.4B the account's CUSTOM COMPONENT families live on Postgres too, behind
        ``design_custom_component_account_fk … ON DELETE CASCADE`` — so components, their source
        revisions, artifacts and compilations now go WITH the account instead of being orphaned
        (SQLite had no FK to ``web_accounts`` and left them behind forever).
        """
        self._bridge._run(
            lambda conn: design_accounts.delete_web_account(
                conn, workspace_id=self.workspace_id, account_id=account_id
            )
        )

    def create_web_batch(self, batch: JsonObject) -> JsonObject:
        return self._bridge._run(
            lambda conn: design_accounts.create_web_batch(
                conn, workspace_id=self.workspace_id, batch=batch
            )
        )

    def update_web_batch_progress(
        self,
        batch_id: str,
        cursor: int,
        status: str,
        manifest: List[JsonObject],
        expected_cursor: Optional[int] = None,
    ) -> JsonObject:
        """One chunk's progress. ``expected_cursor`` is the D6 Round C single-flight CAS."""
        return self._bridge._run(
            lambda conn: design_accounts.update_web_batch_progress(
                conn,
                workspace_id=self.workspace_id,
                batch_id=batch_id,
                cursor=cursor,
                status=status,
                manifest=manifest,
                expected_cursor=expected_cursor,
            )
        )

    def require_web_batch(self, batch_id: str) -> JsonObject:
        return self._bridge._run(
            lambda conn: design_accounts.require_web_batch(
                conn, workspace_id=self.workspace_id, batch_id=batch_id
            )
        )

    # --- web publishes + publish revisions (D2.4B) --------------------------------------------

    def register_web_publish_revision(self, revision: JsonObject) -> JsonObject:
        return self._bridge._run(
            lambda conn: design_publishes.register_web_publish_revision(
                conn, workspace_id=self.workspace_id, revision=revision
            )
        )

    def require_web_publish_revision(self, publish_id: str) -> JsonObject:
        return self._bridge._run(
            lambda conn: design_publishes.require_web_publish_revision(
                conn, workspace_id=self.workspace_id, publish_id=publish_id
            )
        )

    def upsert_web_publish(
        self,
        slug: str,
        document_id: str,
        doc_version: int,
        html: str,
        runtime_version: Optional[int],
        publish_id: Optional[str] = None,
    ) -> JsonObject:
        """Slugs are WORKSPACE-LOCAL now (O6): the PK is ``(workspace_id, slug)``, so two
        tenants publishing ``pricing`` no longer collide. The current→previous shift stays ONE
        statement."""
        return self._bridge._run(
            lambda conn: design_publishes.upsert_web_publish(
                conn,
                workspace_id=self.workspace_id,
                slug=slug,
                document_id=document_id,
                doc_version=doc_version,
                html=html,
                runtime_version=runtime_version,
                publish_id=publish_id,
            )
        )

    def require_web_publish(self, slug: str) -> JsonObject:
        return self._bridge._run(
            lambda conn: design_publishes.require_web_publish(
                conn, workspace_id=self.workspace_id, slug=slug
            )
        )

    def get_web_publish(self, slug: str) -> Optional[JsonObject]:
        return self._bridge._run(
            lambda conn: design_publishes.get_web_publish(
                conn, workspace_id=self.workspace_id, slug=slug
            )
        )

    def system_hostname(self) -> str | None:
        """The workspace's permanent ``<label>.<suffix>`` hostname.

        Custom-domain publishing §4.1.
        """
        return self._bridge._run(lambda conn: _system_hostname(conn, self.workspace_id))

    def active_custom_hostname(self) -> str | None:
        return self._bridge._run(lambda conn: _active_custom_hostname(conn, self.workspace_id))

    def pages_defaults(self) -> dict[str, str | None]:
        """Workspace page defaults applied at publish time (custom-domain publishing §4.2).

        They FILL IN, never override: the description is used only when the page derives an
        empty one, and the social preview only when the page carries no image node.
        """

        async def _read(conn: AsyncConnection) -> dict[str, str | None]:
            row = await get_pages_settings(conn, self.workspace_id)
            return {
                "page_description": row.page_description,
                "social_preview_sha256": row.social_preview_sha256,
            }

        return self._bridge._run(_read)

    def lock_system_hostname(self) -> None:
        """Freeze the workspace's system label at a successful publish (F5 R-F5-5, adopted by
        the 2026-09-28 reconciliation ruling): a published URL is out in the world, so its host
        segment must not move. Idempotent — ``locked_at`` stays the moment the address first
        went public."""
        self._bridge._run(
            lambda conn: _lock_system_hostname(conn, workspace_id=self.workspace_id)
        )

    def get_web_publish_for_document(self, document_id: str) -> Optional[JsonObject]:
        return self._bridge._run(
            lambda conn: design_publishes.get_web_publish_for_document(
                conn, workspace_id=self.workspace_id, document_id=document_id
            )
        )

    def set_web_publish_status(self, slug: str, status: str) -> Optional[JsonObject]:
        return self._bridge._run(
            lambda conn: design_publishes.set_web_publish_status(
                conn, workspace_id=self.workspace_id, slug=slug, status=status
            )
        )

    def unpublish_other_slugs(self, document_id: str, keep_slug: str) -> list[str]:
        """Take ``document_id`` off every live slug but ``keep_slug`` (a republish is a move)."""
        return self._bridge._run(
            lambda conn: design_publishes.unpublish_other_slugs(
                conn, workspace_id=self.workspace_id, document_id=document_id, keep_slug=keep_slug
            )
        )

    def rollback_web_publish(self, slug: str) -> Any:
        return self._bridge._run(
            lambda conn: design_publishes.rollback_web_publish(
                conn, workspace_id=self.workspace_id, slug=slug
            )
        )

    def get_web_publish_page(self, slug: str, route: str) -> Optional[JsonObject]:
        """One served route of a multi-page site (F5), or ``None``.

        ``None`` also covers a pre-F5 publish, which has no page rows at all — the caller falls
        back to the publish row's own ``html`` for ``/`` and 404s elsewhere."""
        return self._bridge._run(
            lambda conn: design_publishes.get_web_publish_page(
                conn, workspace_id=self.workspace_id, slug=slug, route=route
            )
        )

    def list_web_publish_pages(self, slug: str) -> list[JsonObject]:
        """Every route the site currently serves (route/page_id/html_digest, no html)."""
        return self._bridge._run(
            lambda conn: design_publishes.list_web_publish_pages(
                conn, workspace_id=self.workspace_id, slug=slug
            )
        )

    # --- custom-component registry (D2.4B) ----------------------------------------------------

    def register_custom_component_artifact(self, artifact: JsonObject) -> JsonObject:
        """Contract validation (blob/slug/content-address) runs here against the SHARED
        ``database.custom_component_artifact_candidate`` helper — same errors as the SQLite era —
        and the DAL then stores + arbitrates the immutable id's equal-content rule."""
        candidate = custom_component_artifact_candidate(artifact)
        return self._bridge._run(
            lambda conn: design_components.register_custom_component_artifact(
                conn, workspace_id=self.workspace_id, candidate=candidate
            )
        )

    def get_custom_component_artifact(self, artifact_id: str) -> Optional[JsonObject]:
        return self._bridge._run(
            lambda conn: design_components.get_custom_component_artifact(
                conn, workspace_id=self.workspace_id, artifact_id=artifact_id
            )
        )

    def get_custom_component_artifact_for_account(
        self, account_id: str, artifact_id: str
    ) -> Optional[JsonObject]:
        return self._bridge._run(
            lambda conn: design_components.get_custom_component_artifact_for_account(
                conn,
                workspace_id=self.workspace_id,
                account_id=account_id,
                artifact_id=artifact_id,
            )
        )

    def require_custom_component_artifact(self, account_id: str, artifact_id: str) -> JsonObject:
        return self._bridge._run(
            lambda conn: design_components.require_custom_component_artifact(
                conn,
                workspace_id=self.workspace_id,
                account_id=account_id,
                artifact_id=artifact_id,
            )
        )

    def list_custom_component_artifacts(
        self, account_id: str, slug: Optional[str] = None
    ) -> List[JsonObject]:
        return self._bridge._run(
            lambda conn: design_components.list_custom_component_artifacts(
                conn, workspace_id=self.workspace_id, account_id=account_id, slug=slug
            )
        )

    def list_custom_components(self, account_id: str) -> List[JsonObject]:
        return self._bridge._run(
            lambda conn: design_components.list_custom_components(
                conn, workspace_id=self.workspace_id, account_id=account_id
            )
        )

    def get_custom_component(self, account_id: str, slug: str) -> Optional[JsonObject]:
        return self._bridge._run(
            lambda conn: design_components.get_custom_component(
                conn, workspace_id=self.workspace_id, account_id=account_id, slug=slug
            )
        )

    def require_custom_component(self, account_id: str, slug: str) -> JsonObject:
        return self._bridge._run(
            lambda conn: design_components.require_custom_component(
                conn, workspace_id=self.workspace_id, account_id=account_id, slug=slug
            )
        )

    def create_custom_component_source_revision(
        self, source: JsonObject, *, expected_version: int
    ) -> JsonObject:
        """SQLite serialized the CAS with ``BEGIN IMMEDIATE``; the DAL takes the identity row's
        ``FOR UPDATE`` lock inside the bridge's single transaction (the O5 atomicity rule)."""
        candidate = custom_component_source_candidate(source, expected_version)
        return self._bridge._run(
            lambda conn: design_components.create_custom_component_source_revision(
                conn,
                workspace_id=self.workspace_id,
                candidate=candidate,
                expected_version=expected_version,
            )
        )

    def get_custom_component_source_revision(
        self, account_id: str, revision_id: str
    ) -> Optional[JsonObject]:
        return self._bridge._run(
            lambda conn: design_components.get_custom_component_source_revision(
                conn,
                workspace_id=self.workspace_id,
                account_id=account_id,
                revision_id=revision_id,
            )
        )

    def require_custom_component_source_revision(
        self, account_id: str, revision_id: str
    ) -> JsonObject:
        return self._bridge._run(
            lambda conn: design_components.require_custom_component_source_revision(
                conn,
                workspace_id=self.workspace_id,
                account_id=account_id,
                revision_id=revision_id,
            )
        )

    def get_current_custom_component_source(
        self, account_id: str, slug: str
    ) -> Optional[JsonObject]:
        return self._bridge._run(
            lambda conn: design_components.get_current_custom_component_source(
                conn, workspace_id=self.workspace_id, account_id=account_id, slug=slug
            )
        )

    def list_custom_component_source_revisions(
        self, account_id: str, slug: str
    ) -> List[JsonObject]:
        return self._bridge._run(
            lambda conn: design_components.list_custom_component_source_revisions(
                conn, workspace_id=self.workspace_id, account_id=account_id, slug=slug
            )
        )

    def record_custom_component_compilation(self, compilation: JsonObject) -> JsonObject:
        return self._bridge._run(
            lambda conn: design_components.record_custom_component_compilation(
                conn, workspace_id=self.workspace_id, compilation=compilation
            )
        )

    def require_custom_component_compilation(
        self, account_id: str, compilation_id: str
    ) -> JsonObject:
        return self._bridge._run(
            lambda conn: design_components.require_custom_component_compilation(
                conn,
                workspace_id=self.workspace_id,
                account_id=account_id,
                compilation_id=compilation_id,
            )
        )

    def list_custom_component_compilations(self, account_id: str, slug: str) -> List[JsonObject]:
        return self._bridge._run(
            lambda conn: design_components.list_custom_component_compilations(
                conn, workspace_id=self.workspace_id, account_id=account_id, slug=slug
            )
        )

    def validate_custom_component_reference_changes(
        self,
        *,
        before_web_doc: JsonObject,
        after_web_doc: JsonObject,
        account_id: Optional[str],
    ) -> None:
        """Resolve every newly introduced/re-pinned artifact.

        Existing missing pins remain loadable and render as placeholders; an
        unrelated edit does not become impossible because old registry data is
        unavailable. A new node, duplicate, or changed slug/artifact pair must
        resolve in the document's exact account.

        Relocated VERBATIM from the deleted SQLite ``Repository`` at D2.5B. It was the one
        method the staged port never overrode: its only two store reads (``get_web_account``,
        ``get_custom_component_artifact``) are Postgres calls on this class, so Python dispatch
        already ran the inherited walk against Postgres. With the base class gone the walk simply
        lives here; nothing about its behaviour changes.
        """

        before_nodes = custom_component_nodes(before_web_doc)
        after_nodes = custom_component_nodes(after_web_doc)
        before = custom_component_references(before_web_doc)
        after = custom_component_references(after_web_doc)
        resolved: Dict[Tuple[str, str], JsonObject] = {}

        def resolve(
            location: Tuple[str, str],
            node_id: str,
            slug: str,
            artifact_id: str,
        ) -> JsonObject:
            cached = resolved.get(location)
            if cached is not None:
                return cached
            if account_id is None:
                raise CustomComponentReferenceError(
                    "custom_component.account_required",
                    "the website must belong to an account before attaching a custom component",
                    node_id=node_id,
                    artifact_id=artifact_id,
                )
            if self.get_web_account(account_id) is None:
                raise CustomComponentReferenceError(
                    "custom_component.account_unresolved",
                    f"website account {account_id!r} was not found",
                    node_id=node_id,
                    artifact_id=artifact_id,
                )
            artifact = self.get_custom_component_artifact(artifact_id)
            if artifact is None:
                raise CustomComponentReferenceError(
                    "custom_component.artifact_unresolved",
                    f"custom component artifact {artifact_id!r} was not found",
                    node_id=node_id,
                    artifact_id=artifact_id,
                )
            if artifact["account_id"] != account_id:
                raise CustomComponentReferenceError(
                    "custom_component.artifact_forbidden",
                    "custom component artifact belongs to a different account",
                    node_id=node_id,
                    artifact_id=artifact_id,
                )
            if artifact["slug"] != slug:
                raise CustomComponentReferenceError(
                    "custom_component.artifact_slug_mismatch",
                    (
                        f"artifact {artifact_id!r} belongs to slug "
                        f"{artifact['slug']!r}, not {slug!r}"
                    ),
                    node_id=node_id,
                    artifact_id=artifact_id,
                )
            resolved[location] = artifact
            return artifact

        for location, (node_id, slug, artifact_id) in after.items():
            previous = before.get(location)
            if previous == (node_id, slug, artifact_id):
                continue
            resolve(location, node_id, slug, artifact_id)

        # SetNodeProps carries the whole custom-component value. Validate every
        # changed prop map against the exact pinned artifact's generated schema;
        # unchanged legacy/missing nodes remain movable and resizable.
        for location, node in after_nodes.items():
            previous = before_nodes.get(location)
            if (
                previous is not None
                and previous.get("slug") == node.get("slug")
                and previous.get("artifact_id") == node.get("artifact_id")
                and previous.get("props") == node.get("props")
            ):
                continue
            node_id = str(node.get("id") or location[1])
            slug = str(node.get("slug") or "")
            artifact_id = str(node.get("artifact_id") or "")
            artifact = resolve(location, node_id, slug, artifact_id)
            issue = custom_component_props_schema_issue(node.get("props"), artifact.get("manifest"))
            if issue is not None:
                raise CustomComponentReferenceError(
                    "custom_component.props_invalid",
                    f"custom component props do not match the pinned artifact: {issue}",
                    node_id=node_id,
                    artifact_id=artifact_id,
                )

    # --- fragment registry (clone-fidelity F1.2) ----------------------------------------------

    def find_web_fragment(self, fragment_id: str) -> Optional[JsonObject]:
        """Workspace-scoped fragment lookup by id alone — the reference-validation read."""
        return self._bridge._run(
            lambda conn: design_web_fragments.find_web_fragment(
                conn, workspace_id=self.workspace_id, fragment_id=fragment_id
            )
        )

    def require_web_fragment(self, fragment_id: str) -> JsonObject:
        return self._bridge._run(
            lambda conn: design_web_fragments.get_web_fragment(
                conn, workspace_id=self.workspace_id, fragment_id=fragment_id
            )
        )

    def list_web_fragments(
        self, section_role: Optional[str] = None, status: Optional[str] = None
    ) -> List[JsonObject]:
        return self._bridge._run(
            lambda conn: design_web_fragments.list_web_fragments(
                conn,
                workspace_id=self.workspace_id,
                section_role=section_role,
                status=status,
            )
        )

    def list_web_fragment_lineage(self, fragment_id: str) -> List[JsonObject]:
        """The rows of ONE fragment's repair family — the lineage resolver's bounded input.

        Same answer as filtering :meth:`list_web_fragments` by family, at the cost of the family
        rather than of the library: the resolver never looks outside a family, so the smaller
        read is not an approximation.
        """
        return self._bridge._run(
            lambda conn: design_web_fragments.list_web_fragment_lineage(
                conn, workspace_id=self.workspace_id, fragment_id=fragment_id
            )
        )

    def pinned_fragment_ids(self, document_id: Optional[str]) -> frozenset:
        """Every fragment id one existing document pins — the inherited context for a copy.

        An absent or unreadable source yields the empty set, which is the STRICT answer: the
        derivation is then validated as if it chose every pin itself. Failing open here would
        turn "the template is gone" into a way past the gate.
        """
        if not document_id:
            return frozenset()
        try:
            source = self.require_document(document_id)
        except NotFoundError:
            return frozenset()
        scene = source.get("scene") or {}
        if not isinstance(scene, dict):
            return frozenset()
        return frozenset(
            fragment_id for _node_id, fragment_id in fragment_references(scene).values()
        )

    def validate_fragment_reference_changes(
        self,
        *,
        before_web_doc: JsonObject,
        after_web_doc: JsonObject,
        inherited_fragment_ids: "frozenset | set | None" = None,
    ) -> None:
        """Resolve every newly introduced/re-pinned fragment id in this workspace's registry.

        The custom-component gate's twin, with the same semantics deliberately: existing missing
        pins remain loadable (they render as a placeholder) so an unrelated edit does not become
        impossible because registry data went away, while a new node, a duplicate, or a changed
        fragment id must resolve.

        Simpler than its sibling in exactly two ways, both because a fragment is content-addressed
        and workspace-scoped rather than account-scoped: there is no slug to agree with (the id IS
        the content, so a "wrong slug for this artifact" state cannot exist) and no account to
        belong to, so the fail-closed workspace-scoped read is the whole check. A fragment
        registered to another tenant resolves to ``None`` here exactly as an absent one does,
        which is what keeps a global content address from leaking across workspaces.

        **A new pin also needs an APPROVED fragment** (clone-fidelity F2.2). Ingestion mints
        cloned sections as ``draft``; a human releases them by approving the brand kit they came
        from. Until then they exist, they are listable, and they are simply not something a
        document may start using — which is the whole point of a draft. ``deprecated`` is
        refused for the mirror-image reason: it is a retirement, and a retirement that still
        accepted new users would not be one.

        The check is on NEW pins only, exactly like the resolution check beside it. A document
        that already pins a fragment stays loadable, renderable and editable no matter what that
        fragment's status later became — losing the ability to retitle a page because somebody
        retired one section of it would be absurd, and the render path is fail-soft by design.

        ``inherited_fragment_ids`` extends that to COPIES (RULED, F2.2 fix round). A per-account
        derivation and a save-as-template both create a brand-new row, so every pin in them looks
        new to a location-keyed diff even though the human chose none of them — and without this,
        retiring one cloned section would fail every future derivation of every template that
        pins it, which is a retirement that breaks published work rather than stopping new use.
        A pin whose fragment the SOURCE document already held is therefore exempt from the status
        check. It is not exempt from resolution: a copy that pins a fragment nobody holds renders
        the same hole a fresh one would. And it is bounded by what the source actually pins, so a
        derivation cannot smuggle a new pin in beside an inherited one.
        """
        inherited = frozenset(inherited_fragment_ids or ())
        before = fragment_references(before_web_doc)
        after = fragment_references(after_web_doc)
        resolved: set[str] = set()

        for location, (node_id, fragment_id) in after.items():
            if before.get(location) == (node_id, fragment_id):
                continue
            if fragment_id in resolved:
                continue
            row = self.find_web_fragment(fragment_id)
            if row is None:
                raise FragmentReferenceError(
                    "fragment.unresolved",
                    f"fragment {fragment_id!r} was not found in this workspace",
                    node_id=node_id,
                    fragment_id=fragment_id,
                )
            status = str(row.get("status") or "")
            if status != "approved" and fragment_id not in inherited:
                # A separate code from `unresolved` because the repairs differ: one is "mint
                # it", the other is "approve the brand kit it was cloned into".
                raise FragmentReferenceError(
                    "fragment.not_approved",
                    f"fragment {fragment_id!r} is {status or 'unknown'}; a document may only pin "
                    "an approved fragment (approve the brand kit it was cloned from)",
                    node_id=node_id,
                    fragment_id=fragment_id,
                )
            resolved.add(fragment_id)

    # --- retired surfaces ---------------------------------------------------------------------

    def require_asset_metadata(self, asset_id: str) -> JsonObject:
        """The legacy ``asset_metadata`` surface, retired by O3 (PD-part2-design-substrate §6).

        Its only writer — ``POST /asset-metadata`` — has returned 410 since D1, so the table has
        been unwritable for the whole port and was never given a Postgres home. D2.5B deleted the
        SQLite table with the rest of the substrate; the surviving ``GET /asset-metadata/{id}``
        therefore cannot find a row by construction, and 404s exactly as it did before.
        """
        raise NotFoundError("asset", asset_id)

    # --- agent runs + run events (D2.5A) ------------------------------------------------------

    def create_run(
        self,
        run_id: str,
        document_id: Optional[str],
        *,
        kind: str = "agent_turn",
        payload: Optional[JsonObject] = None,
    ) -> JsonObject:
        """Open ONE run row, born ``queued``. Nothing else.

        D5 Round A gave this method a claim half, because on the pre-fleet path the creator WAS
        the executor (a daemon thread started right after it returned) and a ``queued`` row with
        nobody coming for it would have stalled the API's pollers. Round B deletes both: the
        daemon threads are gone and the fleet worker does the claiming, so a run that has been
        offered but not yet claimed is now an honest, transient state rather than a lie.

        Kept as its own method (rather than folded into :meth:`create_run_and_offer`) because the
        design suite creates runs directly to exercise the run/event surface without a queue.
        """
        return self._bridge._run(
            lambda conn: design_runs.create_run(
                conn,
                workspace_id=self.workspace_id,
                run_id=run_id,
                document_id=document_id,
                kind=DesignRunKind(kind),
                payload=payload,
            )
        )

    def create_run_and_offer(
        self,
        run_id: str,
        document_id: Optional[str],
        *,
        kind: str,
        envelope: JsonObject,
        work_id: UUID,
        priority: int = 0,
    ) -> JsonObject:
        """Create the run AND offer its ``design_job`` to the fleet — ONE transaction (R-D5-B5).

        The atomicity is the point, and it is the ``launch_entity_research_run`` precedent
        (``clue_fleet.entity_research``: the run row and its tasks are offered in one
        transaction). Split across two commits there are two ways to be wrong and both are live
        failure modes: a run row with no task is a turn that never starts and never fails, and a
        task with no run row is a worker that claims work it cannot find. One transaction admits
        neither.

        ``envelope`` is the frozen ``DesignTurnEnvelope`` payload — it is stored TWICE on purpose:
        on ``design_agent_run.payload`` (the design plane's own immutable record of the work) and
        on ``fleet_task.payload_json`` (what the worker is handed). They are written in the same
        transaction from the same object, so they cannot disagree.
        """

        # D5 Round B: the design APP (never the design SUBSTRATE — Rule S4 forbids clue_design ->
        # clue_fleet and is untouched) speaks the fleet queue's shape, so a turn's run row and its
        # ``design_job`` task are offered in ONE transaction.
        #
        # Imported HERE, not at module scope, and that is load-bearing: `import clue_fleet` pulls
        # the whole fleet package, which reaches clue_research.durable -> langgraph -> langsmith ->
        # httpx. This module is on the import path of `lumen_ingestion.describe`, which has a
        # standing guard test that importing it drags in neither PIL nor httpx (the ingestion
        # lazy-import discipline). A module-level fleet import breaks that guard for no benefit —
        # only this one method needs the queue.
        from clue_core import ProjectRunId
        from clue_fleet.enums import FleetTaskKind
        from clue_fleet.queue import enqueue_task

        async def _create_and_offer(conn: AsyncConnection) -> JsonObject:
            run = await design_runs.create_run(
                conn,
                workspace_id=self.workspace_id,
                run_id=run_id,
                document_id=document_id,
                kind=DesignRunKind(kind),
                payload=envelope,
                work_id=work_id,
            )
            await enqueue_task(
                conn,
                kind=FleetTaskKind.DESIGN_JOB,
                project_run_id=ProjectRunId(work_id),
                dedup_key=str(work_id),
                payload=envelope,
                priority=priority,
                # A design run id is minted fresh per turn, so its work id is new by
                # construction; reopen_terminal would only matter for a re-offered id.
                reopen_terminal=False,
            )
            return run

        return self._bridge._run(_create_and_offer)

    def get_run(self, run_id: str) -> Optional[JsonObject]:
        return self._bridge._run(
            lambda conn: design_runs.get_run(conn, workspace_id=self.workspace_id, run_id=run_id)
        )

    def require_run(self, run_id: str) -> JsonObject:
        return self._bridge._run(
            lambda conn: design_runs.require_run(
                conn, workspace_id=self.workspace_id, run_id=run_id
            )
        )

    def get_site_turn_workspace(self, run_id: str) -> Optional[JsonObject]:
        """A running site turn's working copy (site-turn durability, Task 3), or ``None``."""
        return self._bridge._run(
            lambda conn: design_site_turn_workspace.get_site_turn_workspace(
                conn, workspace_id=self.workspace_id, run_id=run_id
            )
        )

    def put_site_turn_workspace(
        self,
        run_id: str,
        *,
        checkpoint_id: str,
        files: JsonObject,
        turn_state: JsonObject,
        files_sha256: str,
        attempt_generation: Optional[int],
    ) -> bool:
        """Overwrite the run's working copy; ``False`` when the attempt no longer holds the run."""
        return bool(
            self._bridge._run(
                lambda conn: design_site_turn_workspace.put_site_turn_workspace(
                    conn,
                    workspace_id=self.workspace_id,
                    run_id=run_id,
                    checkpoint_id=checkpoint_id,
                    files=files,
                    turn_state=turn_state,
                    files_sha256=files_sha256,
                    attempt_generation=attempt_generation,
                )
            )
        )

    def restamp_site_turn_workspace(
        self,
        run_id: str,
        *,
        checkpoint_id: str,
        turn_state: JsonObject,
        attempt_generation: Optional[int],
    ) -> bool:
        """Move the run's working copy on to a later checkpoint and turn state, keeping its files (a
        round that changed no file); ``False`` when there is no copy or the attempt no longer holds
        the run."""
        return bool(
            self._bridge._run(
                lambda conn: design_site_turn_workspace.restamp_site_turn_workspace(
                    conn,
                    workspace_id=self.workspace_id,
                    run_id=run_id,
                    checkpoint_id=checkpoint_id,
                    turn_state=turn_state,
                    attempt_generation=attempt_generation,
                )
            )
        )

    def request_run_cancellation(self, run_id: str) -> JsonObject:
        """Ask this run to stop (A3, defect R3-D). Idempotent; raises on an unknown/foreign run.

        The route's whole implementation. No fleet call, no signal, no status write — one stamp on
        the run row, which the driving worker reads at its next model-call boundary. See
        ``clue_design.runs.request_run_cancellation`` for the three honest outcomes."""
        return self._bridge._run(
            lambda conn: design_runs.request_run_cancellation(
                conn, workspace_id=self.workspace_id, run_id=run_id
            )
        )

    def cancellation_requested(self, run_id: str) -> bool:
        """Has this run been asked to stop? The worker-side probe (A3, defect R3-D).

        Called once per model call from inside the synchronous turn body, so it is deliberately
        the narrowest read in this class."""
        return bool(
            self._bridge._run(
                lambda conn: design_runs.cancellation_requested(
                    conn, workspace_id=self.workspace_id, run_id=run_id
                )
            )
        )

    def complete_run(
        self,
        run_id: str,
        status: str,
        result: Optional[JsonObject],
        event_type: str,
        event_data: Optional[JsonObject] = None,
        *,
        expected_generation: Optional[int] = None,
    ) -> int:
        """One bridge call, hence ONE transaction, for "this run is over" — the terminal result
        and its marker event land together or not at all (see ``clue_design.runs.complete_run``
        for the race this closes).

        ``expected_generation`` (D5 Round B) is the zombie fence: an abandoned turn thread whose
        worker has been taken over gets :class:`~clue_design.errors.DesignRunFencedError` here
        instead of overwriting the live attempt's result. Callers with no lease (tests, direct
        scripts) omit it and keep the unfenced behaviour.

        D7 moved the composition up a layer (``run_stream.complete_run_and_emit``): the terminal
        event now lands on the platform ``run_event`` outbox, which ``clue_design`` may not import.
        The transaction, the ordering (result first) and the fence are unchanged."""
        return self._bridge._run(
            lambda conn: _run_stream().complete_run_and_emit(
                conn,
                workspace_id=self.workspace_id,
                run_id=run_id,
                status=status,
                result=result,
                event_type=event_type,
                event_data=event_data,
                expected_generation=expected_generation,
            )
        )

    def emit_run_event(
        self,
        run_id: str,
        event_type: str,
        data: JsonObject,
        *,
        expected_generation: Optional[int] = None,
    ) -> int:
        """One progress event onto the run's durable stream; returns the outbox seq.

        The D7 successor to ``append_run_event``. The fence check, the emit and the ``updated_at``
        bump the reaper clocks on are ONE transaction (``run_stream.fenced_emit``) — no seq to
        allocate any more, because the platform outbox's identity column assigns it.

        ``expected_generation`` fences a taken-over attempt's progress events — see
        :meth:`complete_run`."""
        return self._bridge._run(
            lambda conn: _run_stream().emit_progress(
                conn,
                workspace_id=self.workspace_id,
                run_id=run_id,
                event_type=event_type,
                data=data,
                expected_generation=expected_generation,
            )
        )

    def mint_run_stream_token(self, run_id: str) -> str:
        """Mint this run's single-use SSE token (D7). Header-authenticated by construction: the
        store is built from the request's ``X-Workspace-Id``, so the token row records a *proven*
        tenant, which is what lets the stream route derive its workspace from the token instead of
        trusting a query parameter."""
        return str(
            self._bridge._run(
                lambda conn: _run_stream().mint_run_stream_token(
                    conn, workspace_id=self.workspace_id, run_id=run_id
                )
            )
        )

    def list_run_events(self, run_id: str) -> List[JsonObject]:
        """This run's whole stream in the shape ``design_run_event`` served (``{seq, type, data,
        created_at}``) — the run-snapshot endpoint's ``events`` key, unchanged across the swap.

        The pre-D7 ``after_seq`` parameter is gone: its only caller was the polled SSE loop, which
        D7 replaced with ``run_stream.stream_run_events``' cursor-driven replay."""
        return self._bridge._run(
            lambda conn: _run_stream().run_snapshot_events(
                conn, workspace_id=self.workspace_id, run_id=run_id
            )
        )

    def list_running_runs(self) -> List[JsonObject]:
        """This workspace's still-'running' runs, joined to their document's ``doc_kind`` —
        one Postgres query again (the D2.2-era version stitched SQLite rows to Postgres
        documents because only half the join had been ported)."""
        return self._bridge._run(
            lambda conn: design_runs.list_running_runs(conn, workspace_id=self.workspace_id)
        )

    def get_site_session(self, document_id: str) -> Optional[JsonObject]:
        """The website's session pointer (``version``, ``manifest_sha256``) or ``None`` when the
        site has none yet. Sync twin of :func:`clue_design.sessions.get_site_session`."""
        return self._bridge._run(
            lambda conn: design_sessions.get_site_session(
                conn, workspace_id=self.workspace_id, document_id=document_id
            )
        )

    def site_attempt_holds(self, attempt: Any) -> bool:
        """Whether this attempt still holds its run (run row and work lease); see
        :func:`_hold_site_attempt`. A read: it locks nothing past its own transaction."""
        try:
            self._bridge._run(lambda conn: _hold_site_attempt(conn, self.workspace_id, attempt))
        except DesignRunSaveFencedError:
            return False
        return True

    def save_site_session(
        self,
        document_id: str,
        *,
        expected_version: Optional[int],
        manifest_sha256: str,
        attempt: Any = None,
    ) -> Optional[int]:
        """Move the website's session pointer with compare-and-set (site-turn durability, K4-5).

        Returns the new version, or ``None`` when someone saved a newer copy meanwhile (nothing
        written). With an ``attempt``, the fence that it still holds its run is checked in the
        SAME transaction first, so a zombie can never move the pointer: it raises
        :class:`DesignRunSaveFencedError` and writes nothing."""

        async def _save(conn: AsyncConnection) -> Optional[int]:
            if attempt is not None:
                await _hold_site_attempt(conn, self.workspace_id, attempt)
            return await design_sessions.save_site_session(
                conn,
                workspace_id=self.workspace_id,
                document_id=document_id,
                expected_version=expected_version,
                manifest_sha256=manifest_sha256,
            )

        return self._bridge._run(_save)

    def latest_agent_written_version(self, document_id: str) -> int | None:
        """The version the DESIGN AGENT last committed to this document, or ``None``.

        Session continuity (2026-09-18): one document is one design session, and a continued
        session holds the scene IT wrote. Comparing this against the document's current version
        is how the executor knows a human (or another leg) moved the document between turns, and
        therefore what the drift note has to tell the agent. Sync twin of
        :func:`clue_design.sessions.latest_written_version`, on the same one-transaction bridge
        every other read here uses.
        """
        return self._bridge._run(
            lambda conn: design_sessions.latest_written_version(
                conn, workspace_id=self.workspace_id, document_id=document_id
            )
        )

    def latest_session_manifest_sha256(self, document_id: str, *, include_failed: bool = False) -> str | None:
        """The digest of the newest session-folder manifest this document's session stored, or
        ``None``.

        Session continuity (2026-09-18): the session folder lives on ONE worker's disk, so a turn
        that lands anywhere else restores it from this manifest before the agent sees its
        workspace. Sync twin of :func:`clue_design.sessions.latest_session_manifest_sha256`, on
        the same one-transaction bridge every other read here uses; ``include_failed`` is passed
        through as it is documented there.
        """
        return self._bridge._run(
            lambda conn: design_sessions.latest_session_manifest_sha256(
                conn, workspace_id=self.workspace_id, document_id=document_id, include_failed=include_failed
            )
        )

    def active_design_run_for_document(self, document_id: str) -> Optional[str]:
        """The run id of a design run currently DRIVING this document, or ``None``.

        The write lock's one read (scene live-streaming, rung A): while a design run is in flight
        on a document, the manual scene-write routes refuse with 409 ``document.agent_run_active``
        and name this run, so a human edit can never interleave with the run's own commits. The
        agent's own writes go through the governed tools, never those routes, so they are
        untouched by it. See :func:`clue_design.runs.active_run_for_document` for what counts as
        driving."""
        return self._bridge._run(
            lambda conn: design_runs.active_run_for_document(
                conn, workspace_id=self.workspace_id, document_id=document_id
            )
        )

    # --- cross-domain reads over the Postgres document feed ----------------------------------

    def list_custom_component_usages(self, account_id: str, slug: str) -> List[JsonObject]:
        """Exact document/node pins for one account-local component (ported walk).

        The SQL account predicate in the DAL feed is the tenancy boundary. The JSON walk then
        performs an exact kind/slug match (rather than trusting a broad LIKE) and returns only
        location/version metadata, never another document's source or page content.
        """
        rows = self._bridge._run(
            lambda conn: design_documents.list_web_documents_for_account(
                conn, workspace_id=self.workspace_id, account_id=account_id
            )
        )
        usages: List[JsonObject] = []
        for row in rows:
            for (page_id, node_id), node in sorted(custom_component_nodes(row["scene"]).items()):
                if node.get("slug") != slug:
                    continue
                usages.append(
                    {
                        "document_id": row["id"],
                        "document_title": row["title"],
                        "document_version": row["current_version"],
                        "page_id": page_id,
                        "node_id": node_id,
                        "artifact_id": node.get("artifact_id"),
                    }
                )
        return usages

    # --- history -----------------------------------------------------------------------------

    def list_envelopes(
        self,
        document_id: str,
        limit: Optional[int] = None,
        offset: int = 0,
        newest_first: bool = True,
    ) -> List[JsonObject]:
        return self._bridge._run(
            lambda conn: design_history.list_envelopes(
                conn,
                workspace_id=self.workspace_id,
                document_id=document_id,
                limit=limit,
                offset=offset,
                newest_first=newest_first,
            )
        )

    def require_envelope(self, document_id: str, batch_id: str) -> JsonObject:
        return self._bridge._run(
            lambda conn: design_history.get_envelope(
                conn,
                workspace_id=self.workspace_id,
                document_id=document_id,
                batch_id=batch_id,
            )
        )

    def get_site_sections(self, digests: List[str]) -> List[JsonObject]:
        """This workspace's agent-written sections for ``digests`` (Contract 4), in order."""
        return self._bridge._run(
            lambda conn: design_site_sections.get_site_sections(
                conn, workspace_id=self.workspace_id, digests=digests
            )
        )

    def list_latest_site_sections(self) -> List[JsonObject]:
        """The newest agent-written section of each name in this workspace."""
        return self._bridge._run(
            lambda conn: design_site_sections.list_latest_site_sections(
                conn, workspace_id=self.workspace_id
            )
        )

    def record_site_section(
        self,
        *,
        digest: str,
        name: str,
        source_sha256: str,
        css_sha256: str,
        props_schema: JsonObject,
        created_by_run_id: Optional[str],
    ) -> JsonObject:
        """Record one compiled agent section (Lane B, Contract 4). Governed: only
        ``toolbelt/site_sections.py`` calls it (test_write_path_governance)."""
        return self._bridge._run(
            lambda conn: design_site_sections.record_site_section(
                conn,
                workspace_id=self.workspace_id,
                digest=digest,
                name=name,
                source_sha256=source_sha256,
                css_sha256=css_sha256,
                props_schema=props_schema,
                created_by_run_id=created_by_run_id,
            )
        )

    def list_operations(self, document_id: str) -> List[JsonObject]:
        return self._bridge._run(
            lambda conn: design_history.list_operations(
                conn, workspace_id=self.workspace_id, document_id=document_id
            )
        )

    # --- snapshots + template revisions ------------------------------------------------------

    def create_snapshot(self, document_id: str, snapshot_id: str, reason: str) -> JsonObject:
        return self._bridge._run(
            lambda conn: design_snapshots.create_snapshot(
                conn,
                workspace_id=self.workspace_id,
                document_id=document_id,
                snapshot_id=snapshot_id,
                reason=reason,
            )
        )

    def list_snapshots(self, document_id: str) -> List[JsonObject]:
        return self._bridge._run(
            lambda conn: design_snapshots.list_snapshots(
                conn, workspace_id=self.workspace_id, document_id=document_id
            )
        )

    def require_snapshot(self, document_id: str, snapshot_id: str) -> JsonObject:
        return self._bridge._run(
            lambda conn: design_snapshots.get_snapshot(
                conn,
                workspace_id=self.workspace_id,
                document_id=document_id,
                snapshot_id=snapshot_id,
            )
        )

    def create_template_revision(
        self,
        document_id: str,
        template_revision_id: str,
        source_snapshot_id: Optional[str],
        scene: JsonObject,
        slot_summary: List[JsonObject],
    ) -> JsonObject:
        return self._bridge._run(
            lambda conn: design_snapshots.create_template_revision(
                conn,
                workspace_id=self.workspace_id,
                document_id=document_id,
                template_revision_id=template_revision_id,
                source_snapshot_id=source_snapshot_id,
                scene=scene,
                slot_summary=slot_summary,
            )
        )

    def require_template_revision(self, template_revision_id: str) -> JsonObject:
        return self._bridge._run(
            lambda conn: design_snapshots.get_template_revision(
                conn,
                workspace_id=self.workspace_id,
                template_revision_id=template_revision_id,
            )
        )

    # --- diagnostics -------------------------------------------------------------------------

    def store_diagnostics(
        self,
        document_id: str,
        kind: str,
        diagnostics: List[JsonObject],
        commit: bool = True,
    ) -> None:
        del commit  # SQLite-era knob; the bridge is one transaction per call.
        self._bridge._run(
            lambda conn: design_diagnostics.store_diagnostics(
                conn,
                workspace_id=self.workspace_id,
                document_id=document_id,
                kind=kind,
                diagnostics=diagnostics,
            )
        )

    def latest_diagnostics(
        self, document_id: str, kind: Optional[str] = None
    ) -> Optional[JsonObject]:
        return self._bridge._run(
            lambda conn: design_diagnostics.latest_diagnostics(
                conn,
                workspace_id=self.workspace_id,
                document_id=document_id,
                kind=kind,
            )
        )


def api_engine_cache_root(workspace_id: str) -> Path:
    """One workspace's engine materialization cache, resolved as ``create_app`` resolves it.

    The off-request-thread twin of the app's own ``engine_cache_dir``: agent-turn workers and
    the by-value resolvers below run outside a request, so they cannot read ``app.state``.
    Deliberately per-WORKSPACE for the same reason the in-app accessor is — the engine resolves
    purely by digest, so one shared tree would let a turn read another tenant's bytes.
    """
    from py_lumen_config import settings

    path = settings.effective_asset_store_root / workspace_id
    path.mkdir(parents=True, exist_ok=True)
    return path
