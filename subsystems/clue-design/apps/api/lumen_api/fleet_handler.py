"""The design fleet work handler (design-integration Part II, slice D5 Rounds B + C).

The same handler implementation serves two disjoint execution roles. Primary and embedded
workers claim only agent turns (scene, web or site); the dedicated ingestion coordinator is built
with ``ingestion_only=True`` and claims only brand-kit ingestions. Required claim-time
capabilities enforce this boundary in SQL. Per-image analysis has its own handler and pool.

Round C added the ingestion branch (it was parked with a loud log in Round B) and IN-HANDLER
CONTAINMENT: an exception escaping the executor terminalizes the design row ``failed`` under the
lease fence, so the one shape that could previously strand a row — a store fault between claim
and terminal write — no longer does. Only a containment write that ITSELF fails leaves a
``running`` row, and that residue is what ``lumen_api.fleet_reaper`` sweeps.

WHY THIS LIVES IN ``lumen_api`` AND NOT AT THE PLATFORM COMPOSITION ROOT
-----------------------------------------------------------------------
Executing a design turn means touching ``lumen_agent`` (the harnesses), ``lumen_api.main``'s
by-value config resolvers (brand kit, fonts, reference previews, asset library, custom-component
registry), and the design store. ``lumen_api`` already imports all three; ``clue_api`` imports
none of them, and the import direction ``lumen_api -> clue_api`` is forbidden outright (Rule 5:
nothing imports the composition root). So the handler *class* lives here, next to what it drives,
and ``clue_api.design_fleet`` is a thin registration wrapper that ``fleet_main`` composes.

NEW IMPORT EDGES, DELIBERATE
----------------------------
* ``lumen_api -> clue_fleet`` (this module + ``design_store.create_run_and_offer``). The design
  API must speak the queue's shape to offer work into it. Note what does NOT change: the design
  SUBSTRATE (``clue_design``) still imports no fleet — Rule S4 is enforced by import-linter and
  is untouched. The app layer above it is where the two planes are allowed to meet.
* ``clue_api -> lumen_api`` (the wrapper module). Legal: ``clue_api`` is the composition root and
  may import anything.

Neither edge is visible to import-linter, whose ``root_packages`` do not include ``lumen_api``
(the design tree is out of the root lint until Part-I Step-2). Recorded here so the omission is a
known state rather than an oversight.

THE ZOMBIE-THREAD RESIDUAL (R-D5-B3)
------------------------------------
The turn body is SYNCHRONOUS — ``agent.invoke`` blocks, and the tool substrate shells out to the
Rust engine and to node. It therefore runs under ``asyncio.to_thread`` so the worker's heartbeat
coroutine keeps beating; a blocked event loop would be a self-inflicted lease loss
(``clue_fleet.work_worker`` renews on the loop).

Cancellation is COOPERATIVE ONLY. Python cannot interrupt a thread, so on ``lease_lost`` /
``stop_requested`` the handler stops waiting and returns — it does not, and cannot, stop the
thread. The abandoned thread may finish minutes later and try to write a terminal result. That is
why every durable write this handler makes carries ``expected_generation``: the design row's
generation fence (``clue_design.runs``) refuses a stale writer's terminal write and raises
``DesignRunFencedError``, which is logged loudly and dropped. The zombie burns CPU until it
finishes; it cannot corrupt the run.
"""

from __future__ import annotations

import asyncio
import contextlib
from dataclasses import dataclass, replace
from typing import Any, Callable, Dict, Optional
from uuid import UUID

from clue_design.envelopes import DesignIngestionEnvelope, DesignTurnEnvelope
from clue_design.enums import DesignIngestionKind, DesignRunKind
from clue_design.errors import DesignJobFencedError, DesignRunFencedError
from clue_fleet.enums import FleetTaskKind
from clue_fleet.queue import TaskCapability
from clue_fleet.work_worker import WorkContext, WorkResult
from clue_obs.langfuse import observation, propagate_trace
from lumen_ingestion.jobs import IngestionJobStore
from py_lumen_config import settings
from py_lumen_obs import get_logger
from pydantic import TypeAdapter, ValidationError

from .database import NotFoundError
from .design_store import HybridRepository

JsonObject = Dict[str, Any]

logger = get_logger("lumen_api.fleet_handler")

#: One parse of the stored envelope, through the tagged union — never a raw dict lookup.
_ENVELOPE = TypeAdapter(DesignTurnEnvelope | DesignIngestionEnvelope)

#: The envelope field a ``design_job`` payload uses to name its ingestion lane. Named here
#: because the claim-time capability filter must read it as a raw payload key — the filter runs
#: in SQL, before anything is claimed, and therefore before there is anything to parse.
_INGESTION_KIND_FIELD = "ingestion_kind"

#: Ingestion lanes gated behind a deployment flag: lane -> "is it on in this process?".
#: A lane absent from this map is runnable whenever the build contains it.
_FLAGGED_INGESTION_KINDS: Dict[str, Callable[[], bool]] = {
    DesignIngestionKind.AD_ASSETS.value: lambda: settings.lumen_brand_ad_assets,
}


def runnable_ingestion_kinds() -> frozenset[str]:
    """Which ``design_ingestion_kind`` values THIS process can actually execute (R3-B).

    Two independent reasons a lane is absent, and the first is the one that matters:

    * **The build does not contain it.** The set starts from ``DesignIngestionKind``'s own
      members, so a worker running older code simply has no member for a lane added after it
      was built — it cannot name the lane, so it cannot claim the lane. That is the whole
      mechanism behind the stale-worker guarantee, and it needs no version negotiation, no
      registry handshake, and no maintenance: a capability list can only ever be built out of
      what the process knows.
    * **A deployment flag it needs is off.** ``ad_assets`` needs ``LUMEN_BRAND_AD_ASSETS``;
      with it off, ``lumen_ingestion.ad_library.onboarding`` refuses the job outright, so
      claiming one could only ever produce a failure.

    Read live rather than cached, because the flag is a deployment property and a worker should
    claim under the configuration it would execute under.
    """
    kinds = {kind.value for kind in DesignIngestionKind}
    for kind, is_enabled in _FLAGGED_INGESTION_KINDS.items():
        if not is_enabled():
            kinds.discard(kind)
    return frozenset(kinds)


@dataclass(frozen=True)
class DesignTurnHost:
    """The process-local capabilities a turn needs that are NOT in its frozen envelope.

    Everything the *work* is defined by rides the envelope (R-D5-B2): it is immutable, so a
    takeover worker replays the same unit of work rather than re-reading state that has moved.
    These are the opposite: process-scoped handles and test seams that cannot be serialized —
    the Rust engine client, the node binary paths, and the two turn-runner overrides the design
    API's suite installs on ``app.state``.

    The embedded worker builds this from the live ``app.state`` (so injected storage and stubbed
    runners are honoured); the detached fleet worker builds the defaults, which are exactly the
    values ``create_app`` assigns when nothing is injected.
    """

    agent_turn_runner: Any = None
    web_turn_runner: Any = None
    #: Puck site turn test seam (Lane B): replaces the site runtime; see main.run_site_agent_turn.
    site_turn_runner: Any = None
    core: Any = None
    compiler_node_bin: str = "node"
    compiler_worker: Any = None
    compiler_timeout_seconds: Any = None
    storage: Any = None
    #: The app's engine materialization cache ROOT (D5 Round C). ``None`` re-derives it from
    #: settings, which is exactly what a detached worker has; the embedded worker passes
    #: ``app.state.engine_cache_root`` so worker and request paths mirror into the same tree.
    engine_cache_root: Any = None
    #: Authorized envelope -> model-boundary resolver, composed by the platform.
    #: Neither the callable nor resolved preference bodies enter the frozen job.
    preference_resolver_factory: Any = None
    #: Authorized envelope -> the platform reads for a leg turn, composed by the platform
    #: (design note 2026-09-19); the design API's own worker has none.
    platform_reads_factory: Any = None


class DesignTurnJobError(RuntimeError):
    """A design work item that cannot be executed at all (bad envelope, unknown run)."""


class DesignJobWorkHandler:
    """Claim one design run through the D5 CAS, execute its turn, land its terminal result.

    Shape follows the two shipped precedents deliberately: ``EntityResearchJobWorkHandler``
    (claim -> drive -> finalize, with the lease fence threaded through every store call) and
    ``AccountResearchFleetWorkHandler`` (the composition-root supervision wrapper).

    The claim, the execution and the containment write are all shape-agnostic: which DAL is
    claimed and which executor runs is decided by the envelope's type, and nothing else in the
    flow branches. That is the point of ONE fleet kind carrying a discriminated envelope — a
    third design job shape would add two dispatch entries, not a second handler.
    """

    kind = FleetTaskKind.DESIGN_JOB

    def __init__(
        self,
        *,
        host_provider: Any = None,
        checkpointer_factory: Any = None,
        spend_drain: Any = None,
        turn_callbacks_factory: Any = None,
        ingestion_only: bool = False,
        named_trace: bool = True,
    ) -> None:
        # Callables, not values: the embedded worker's host reads ``app.state`` at execution
        # time, so a test that swaps ``app.state.agent_turn_runner`` between turns is honoured.
        self._host_provider = host_provider if host_provider is not None else DesignTurnHost
        self._checkpointer_factory = checkpointer_factory
        # Lane 3 slice 5: the whole drain, injected. ``None`` is the bare library drain (rows and
        # nothing else); the platform composes one that also records a provider incident, so that
        # bookkeeping is written once on its side rather than once per design executor.
        self._spend_drain = spend_drain
        # Lane 3 slice 5: a factory, not a value — the platform's Langfuse handler and its
        # run-id registry are PER TURN, so a shared instance would cross-attribute one turn's
        # model calls onto another's observation. Called once per turn envelope; ingestion
        # takes none (it is a pipeline, not a graph).
        self._turn_callbacks_factory = turn_callbacks_factory
        self._ingestion_only = ingestion_only
        # Every drained job is one named Langfuse trace (2026-10-03 agent-scoped tracing spec,
        # R7). The platform's inline leg lane turns this off: its turns already run inside
        # ``design-leg.turn``, and a second trace name would rename the leg's trace.
        self._named_trace = named_trace

    @property
    def task_capabilities(self) -> "tuple[TaskCapability, ...]":
        """Primary workers serve turns; ingestion coordinators serve only ingestion.

        The required kind constraint is evaluated inside the SQL claim, so neither
        pool consumes the other's slots. Ingestion feature capabilities still apply.
        """
        return (
            TaskCapability(
                field="kind",
                required=True,
                supported=frozenset(
                    {"ingestion"} if self._ingestion_only else {"agent_turn", "web_turn", "site_turn"}
                ),
            ),
            TaskCapability(field=_INGESTION_KIND_FIELD, supported=runnable_ingestion_kinds()),
        )

    async def handle(self, context: WorkContext) -> WorkResult:
        """Execute one design job, and NEVER raise past this point (R3-B).

        Round C's in-handler containment covered exceptions out of the *executor* — everything
        after the claim. What it did not cover was its own preamble: parsing the envelope, the
        work-id check, and the claim read itself all run BEFORE the design row moves out of
        ``queued``, and a raise there escaped into
        :meth:`clue_fleet.LeasedWorkWorker._run_task`, whose ``except Exception`` is fleet-plane
        only — it marks the TASK failed and has no idea a design row exists. The row therefore
        stayed ``queued`` with ``error_json`` NULL forever. That is the exact nine-minute
        never-ending job the W5 acceptance walk watched.

        So the preamble is contained too, and by work id rather than by envelope: the work id is
        the one identifier that survives an envelope that will not parse.
        """
        if "kind" in context.payload and not self.task_capabilities[0].permits(context.payload):
            raise DesignTurnJobError("design task is outside this worker's execution pool")
        with self._job_trace(context.payload):
            try:
                return await self._handle(context)
            except Exception as error:
                return await self._contain_preamble_failure(context, error)

    @contextlib.contextmanager
    def _job_trace(self, payload: Dict[str, Any]) -> Any:
        """Open this job's named Langfuse trace, so the design graph's steps and the job's model
        calls land in one trace per job (R7). A no-op when Langfuse is not installed, when the
        lane opted out, or for a payload with no recognisable kind (the preamble refuses it)."""
        shape = _TRACE_SHAPES.get(str(payload.get("kind"))) if self._named_trace else None
        if shape is None:
            yield
            return
        name, as_type, keys, session_key, tag_keys = shape

        def text(key: str) -> Optional[str]:
            value = payload.get(key)
            return value if isinstance(value, str) and value else None

        tags = ("design", *(t for t in (text(k) for k in tag_keys) if t is not None))
        with (
            propagate_trace(
                trace_name=name,
                session_id=text(session_key) if session_key else None,
                user_id=text("workspace_id"),
                metadata={key: text(key) for key in keys},
                tags=tags,
            ),
            observation(name, as_type=as_type),
        ):
            yield

    def _turn_callbacks(self) -> Any:
        """This turn's LangChain callbacks: the injected factory's, else the platform's Langfuse
        handler (the fleet drain and the ingestion pool inject none), else none at all."""
        if self._turn_callbacks_factory is not None:
            return self._turn_callbacks_factory()
        from clue_gateway.langfuse_handler import build_langfuse_callbacks
        from lumen_agent.usage_collector import TurnCallbacks

        built = build_langfuse_callbacks()
        if built is None:
            return TurnCallbacks()
        return TurnCallbacks(handlers=(built.handler,), langfuse_ids=built.registry)

    async def _contain_preamble_failure(
        self, context: WorkContext, error: Exception
    ) -> WorkResult:
        """Terminalize the design row this task owns, then report honestly."""
        logger.error(
            "design_job.preamble_error",
            work_id=str(context.work_id),
            worker_id=context.worker_id,
            lease_generation=int(context.lease_generation),
            exc_info=error,
        )
        outcome = await asyncio.to_thread(_reconcile_dispatched_failure, context, error)
        logger.warning(
            "design_job.preamble_reconciled",
            work_id=str(context.work_id),
            reconciliation=outcome,
        )
        return WorkResult(
            outcome="preamble_error",
            references={
                "work_id": str(context.work_id),
                "error": str(error),
                "reconciliation": outcome,
            },
        )

    async def _handle(self, context: WorkContext) -> WorkResult:
        envelope = self._parse(context)
        if UUID(str(context.work_id)) != envelope.work_id:
            raise DesignTurnJobError("design work payload widens the leased work id")

        subject = _subject(envelope)
        generation = int(context.lease_generation)

        claimed = await asyncio.to_thread(
            _claim,
            envelope,
            context.worker_id,
            generation,
        )
        if claimed is None:
            # Fenced out (a newer generation owns it) or already terminal. Either way this worker
            # has nothing to do and must not touch the row. The task is FINISHED (not requeued,
            # not left claimed): a refusal is a permanent answer for this work id, and leaving
            # the row claimed would have it re-owned every stale-window forever.
            logger.warning(
                "design_job.claim_refused",
                work_id=str(context.work_id),
                worker_id=context.worker_id,
                lease_generation=generation,
                **subject,
            )
            return WorkResult(outcome="claim_refused", references=_refs(context, subject))

        host = self._host_provider()
        logger.info(
            "design_job.started",
            work_id=str(context.work_id),
            kind=envelope.kind,
            workspace_id=envelope.workspace_id,
            worker_id=context.worker_id,
            lease_generation=generation,
            **subject,
        )

        body = asyncio.create_task(
            asyncio.to_thread(self._execute, envelope, generation, host)
        )
        fence = asyncio.create_task(_first_of(context.lease_lost, context.stop_requested))
        try:
            done, _ = await asyncio.wait({body, fence}, return_when=asyncio.FIRST_COMPLETED)
        finally:
            fence.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await fence

        if body not in done:
            # Cooperative stop. The thread is NOT cancelled (Python cannot); it is abandoned, and
            # the generation fence on its durable writes is what protects the takeover's work.
            lost = context.lease_lost.is_set()
            logger.warning(
                "design_job.abandoned",
                work_id=str(context.work_id),
                worker_id=context.worker_id,
                lease_generation=generation,
                reason="lease_lost" if lost else "stop_requested",
                residual="the synchronous job thread keeps running until it finishes",
                **subject,
            )
            return WorkResult(
                outcome="lease_lost" if lost else "stopped",
                references=_refs(context, subject),
                requeue=True,
            )

        error = body.exception()
        if error is not None:
            # IN-HANDLER CONTAINMENT (D5 Round C). A raise from here — a store fault, not a
            # failed turn — used to mark only the FLEET task failed and leave the design row
            # ``running`` with nobody coming for it. So the row is terminalized here, under the
            # same generation fence, and the failure is reported honestly in the WorkResult.
            # Only when even THAT write fails does the row stay ``running``, which is the one
            # case the reaper exists for.
            logger.error(
                "design_job.handler_error",
                work_id=str(context.work_id),
                worker_id=context.worker_id,
                lease_generation=generation,
                exc_info=error,
                **subject,
            )
            contained = await asyncio.to_thread(
                _terminalize_failed, envelope, generation, error
            )
            return WorkResult(
                outcome="handler_error" if contained else "handler_error_uncontained",
                references={**_refs(context, subject), "error": str(error)},
            )

        status = body.result()
        logger.info(
            "design_job.finished",
            work_id=str(context.work_id),
            status=status,
            lease_generation=generation,
            **subject,
        )
        return WorkResult(outcome=status, references=_refs(context, subject))

    def _execute(self, envelope: Any, generation: int, host: Any) -> str:
        """Dispatch one claimed envelope to its executor, on the worker thread."""
        from .main import execute_ingestion_job

        if isinstance(envelope, DesignIngestionEnvelope):
            return str(execute_ingestion_job(
                envelope,
                host=host,
                expected_generation=generation,
                spend_drain=self._spend_drain,
            ))
        store = HybridRepository(workspace_id=envelope.workspace_id, ensure_workspace=False)
        return _execute_turn(
            envelope,
            store,
            generation,
            host,
            self._checkpointer_factory,
            spend_drain=self._spend_drain,
            turn_callbacks_factory=self._turn_callbacks,
        )

    def _parse(self, context: WorkContext) -> DesignTurnEnvelope | DesignIngestionEnvelope:
        try:
            return _ENVELOPE.validate_python(context.payload)
        except ValidationError as error:
            raise DesignTurnJobError(
                f"design work payload is not a valid design job envelope: {error}"
            ) from error


async def _first_of(*events: asyncio.Event) -> None:
    """Resolve as soon as ANY of the worker's stop signals fires."""
    waiters = [asyncio.create_task(event.wait()) for event in events]
    try:
        await asyncio.wait(waiters, return_when=asyncio.FIRST_COMPLETED)
    finally:
        for waiter in waiters:
            waiter.cancel()
        await asyncio.gather(*waiters, return_exceptions=True)


#: Per envelope kind: the trace name, its observation type, the payload keys copied into the trace
#: metadata, the key used as the Langfuse session, and the keys added as tags beside ``design``.
_TRACE_SHAPES: Dict[str, tuple[str, Any, tuple[str, ...], Optional[str], tuple[str, ...]]] = {
    kind: (
        "design.turn",
        "agent",
        ("run_id", "document_id", "project_id"),
        "checkpoint_thread_id",
        ("kind",),
    )
    for kind in ("agent_turn", "web_turn")
}
#: A site turn opens a fresh thread per request (founder ruling 2026-10-11), so its Langfuse session
#: is its DOCUMENT, which groups a site's requests the way one continued thread groups a web page's.
_TRACE_SHAPES["site_turn"] = (
    "design.turn",
    "agent",
    ("run_id", "document_id", "project_id"),
    "document_id",
    ("kind",),
)
_TRACE_SHAPES["ingestion"] = (
    "design.ingestion",
    "chain",
    ("job_id",),
    None,
    ("kind", "ingestion_kind"),
)
_TRACE_SHAPES["asset_analysis"] = (
    "design.asset_analysis",
    "chain",
    ("job_id", "asset_id"),
    None,
    ("kind",),
)


def _subject(envelope: Any) -> Dict[str, str]:
    """The one identifier a log line should carry for this envelope's shape."""
    if isinstance(envelope, DesignIngestionEnvelope):
        return {"job_id": envelope.job_id, "ingestion_kind": str(envelope.ingestion_kind)}
    return {"run_id": envelope.run_id}


def _refs(context: WorkContext, subject: Dict[str, str]) -> Dict[str, Any]:
    return {"work_id": str(context.work_id), **subject}


def _fleet_plane_bridge() -> Any:
    """A store bridge with no tenant of its own — for the work-id-keyed fleet-plane calls.

    The claim and the containment write are keyed on the work id alone and the workspace is what
    they *return* (the same structural exemption ``get_run_by_work_id`` carries).
    ``ensure_workspace=False`` because neither may create a tenant row.
    """
    from .design_store import DesignStoreBridge, default_workspace_id

    return DesignStoreBridge(default_workspace_id(), ensure_workspace=False)


def _claim(envelope: Any, worker_id: str, lease_generation: int) -> Optional[JsonObject]:
    """The D5 claim CAS for either envelope shape, off the event loop.

    ``None`` = refused (fenced out, or already terminal) — and an unknown work id is folded into
    the same answer deliberately: the bridge translates the DAL's ``DesignNotFoundError`` into
    the API's ``NotFoundError``, and a work id with no design row is a POISON task. Nothing will
    ever make it runnable, so it is finished like a refusal rather than requeued forever.
    """
    from clue_design import ingestion as design_ingestion
    from clue_design import runs as design_runs

    claim = (
        design_ingestion.claim_job_for_execution
        if isinstance(envelope, DesignIngestionEnvelope)
        else design_runs.claim_run_for_execution
    )
    try:
        return _fleet_plane_bridge()._run(
            lambda conn: claim(
                conn,
                work_id=envelope.work_id,
                worker_id=worker_id,
                lease_generation=lease_generation,
            )
        )
    except NotFoundError:
        return None


def _reconcile_dispatched_failure(context: WorkContext, error: Exception) -> str:
    """Fail the design row behind this WORK ID, off the event loop. Returns what happened.

    Keyed on the work id and nothing else, because the failure this repairs may be the envelope
    itself refusing to parse — in which case there is no ``job_id``/``run_id`` to key on, and the
    work id on the task is the only identifier left. It is enough: both design tables carry it
    uniquely, which is what ``get_job_by_work_id`` / ``get_run_by_work_id`` already exploit.

    Never raises. A reconciliation that explodes inside the handler's own error path would put
    the process straight back into the fleet-plane ``except`` this exists to keep it out of; the
    honest answer is a reported outcome, and the reaper's orphan sweep as the backstop.
    """
    from .fleet_reaper import reconcile_dispatched_failure

    try:
        return str(
            _fleet_plane_bridge()._run(
                lambda conn: reconcile_dispatched_failure(
                    conn,
                    work_id=UUID(str(context.work_id)),
                    code="design_job.preamble_error",
                    message=f"{type(error).__name__}: {error}",
                    lease_generation=int(context.lease_generation),
                )
            )
        )
    except Exception:
        logger.error(
            "design_job.reconciliation_failed",
            work_id=str(context.work_id),
            detail="the design row could not be terminalized; the reaper must recover it",
            exc_info=True,
        )
        return "unreconciled"


def _terminalize_failed(envelope: Any, generation: int, error: BaseException) -> bool:
    """Land a ``failed`` row for a job whose HANDLER raised. ``True`` when the write landed.

    The containment half of the D5 Round C stranded-work guarantee. A handler exception is a
    store/infrastructure fault rather than a failed turn, so the run or job has no terminal row
    of its own; without this it would sit ``running`` forever while the fleet marked its task
    FAILED. Fenced like every other worker write — a taken-over attempt must not stamp ``failed``
    over the live one.

    Returns ``False`` (never raises) when the write itself could not land: that is precisely the
    case the reaper exists for, and the handler must still report an honest outcome rather than
    exploding a second time inside its own error path.
    """
    detail: JsonObject = {
        "code": "design_job.handler_error",
        "message": f"{type(error).__name__}: {error}",
    }
    try:
        if isinstance(envelope, DesignIngestionEnvelope):
            store = IngestionJobStore(
                workspace_id=envelope.workspace_id, expected_generation=generation
            )
            store.fail(envelope.job_id, detail)
        else:
            HybridRepository(
                workspace_id=envelope.workspace_id, ensure_workspace=False
            ).complete_run(
                envelope.run_id,
                "failed",
                {"schema_version": 1, "status": "failed", "error": detail},
                "error",
                {"message": detail["message"]},
                expected_generation=generation,
            )
    except (DesignRunFencedError, DesignJobFencedError):
        # Already replaced by a takeover: its terminal row is the authoritative one. Contained.
        logger.warning(
            "design_job.containment_fenced",
            lease_generation=generation,
            **_subject(envelope),
        )
        return True
    except Exception:
        logger.error(
            "design_job.containment_failed",
            lease_generation=generation,
            detail="the design row could not be terminalized; the reaper must recover it",
            exc_info=True,
            **_subject(envelope),
        )
        return False
    return True


def executor_for_kind(kind: str) -> Any:
    """The executor for one design turn kind. An unknown kind is refused, never run as web: the old
    ``else execute_web_turn_job`` sent every non-scene envelope to the web executor."""

    from .main import execute_agent_turn_job, execute_site_turn_job, execute_web_turn_job

    executors = {
        DesignRunKind.AGENT_TURN.value: execute_agent_turn_job,
        DesignRunKind.WEB_TURN.value: execute_web_turn_job,
        DesignRunKind.SITE_TURN.value: execute_site_turn_job,
    }
    try:
        return executors[kind]
    except KeyError:
        raise DesignTurnJobError(f"no executor for design turn kind {kind!r}") from None


def _execute_turn(
    envelope: DesignTurnEnvelope,
    store: HybridRepository,
    generation: int,
    host: DesignTurnHost,
    checkpointer_factory: Any,
    *,
    spend_drain: Any = None,
    turn_callbacks_factory: Any = None,
) -> str:
    """Run ONE design turn to a terminal result. Synchronous by nature; called via to_thread.

    Returns the terminal run status (``succeeded`` / ``failed``), or ``fenced`` when the terminal
    write was refused because a takeover worker owns the run.

    The lazy ``lumen_api.main`` import (in :func:`executor_for_kind`) breaks a genuine cycle:
    ``main`` imports THIS module to build the embedded worker, and the turn executors live in
    ``main`` because every by-value resolver they need (brand kit, fonts, references, asset
    library, engine cache) lives there.
    """
    executor = executor_for_kind(envelope.kind)

    def sink(event_type: str, data: JsonObject) -> None:
        try:
            # D7: the run's progress now lands on the platform ``run_event`` outbox as a
            # ``design.run.event`` under this run's subject. Same fence, same best-effort
            # semantics, same call shape — only the substrate underneath changed.
            store.emit_run_event(
                envelope.run_id, event_type, data, expected_generation=generation
            )
        except DesignRunFencedError:
            # A taken-over turn must stop polluting the live run's event stream. Logged once per
            # event rather than swallowed silently, so a zombie is visible in the logs.
            logger.warning(
                "design_job.event_fenced",
                run_id=envelope.run_id,
                lease_generation=generation,
                event_type=event_type,
            )
        except Exception:  # progress events are best-effort, exactly as before D5
            pass

    checkpointer_cm = (
        checkpointer_factory(envelope.checkpoint_thread_id)
        if checkpointer_factory is not None
        else contextlib.nullcontext(None)
    )
    with checkpointer_cm as checkpointer:
        # Design session continuity (2026-09-18): the thread is the DOCUMENT's session, so a
        # thread that already carries state means the agent has been here before — this turn
        # continues a conversation instead of opening one. The executors gate the brief and the
        # history blocks on it, because re-sending what the thread already holds says everything
        # twice. Probed HERE, under the saver the turn will actually run on, and BEFORE the turn
        # touches it (the first invoke writes state of its own).
        session_continued = _thread_has_state(checkpointer, envelope.checkpoint_thread_id)
        # Lane 3 slice 5: ONE call per turn. The factory mints this turn's Langfuse handler and
        # the registry it fills; the executor adds the receipt collector to them.
        callbacks = turn_callbacks_factory() if turn_callbacks_factory is not None else None
        status, response, event_type, event_data = executor(
            envelope,
            store=store,
            host=host,
            event_sink=sink,
            checkpointer=checkpointer,
            # D7: the turn's governed tool invocations reach the same stream, fenced by the same
            # lease generation (see ``lumen_api.toolbelt.wiring._DesignRunEventTransport``).
            lease_generation=generation,
            spend_drain=spend_drain,
            callbacks=callbacks,
            session_continued=session_continued,
        )

    try:
        store.complete_run(
            envelope.run_id,
            status,
            response,
            event_type,
            event_data,
            expected_generation=generation,
        )
    except DesignRunFencedError as error:
        logger.error(
            "design_job.terminal_write_fenced",
            run_id=envelope.run_id,
            lease_generation=generation,
            current_generation=error.current_generation,
            detail="a takeover worker owns this run; the abandoned attempt's result was dropped",
        )
        return "fenced"
    return status


def _thread_has_state(checkpointer: Any, thread_id: str) -> bool:
    """Does the session thread already carry earlier turns? Best-effort; ``False`` on doubt.

    ``False`` is the safe answer in both directions: the turn still runs, and the executors
    simply send the brief and the history they would have sent before session continuity — one
    duplicated block, never a lost one. So a saver that cannot answer must not fail the turn.
    """
    if checkpointer is None:
        return False
    try:
        return checkpointer.get_tuple({"configurable": {"thread_id": thread_id}}) is not None
    except Exception:  # noqa: BLE001 - a saver that cannot answer must not fail the turn
        logger.warning("design_job.session_state_unreadable", thread_id=thread_id, exc_info=True)
        return False


# --- the LangGraph Postgres checkpointer (R-D5-B4) --------------------------------------------

#: Checking (and, behind, installing) the tables is a round trip per turn.
#: Do it once per process per DSN; a fresh database in a test process still gets its tables
#: because the set is process-local, not persisted.
_CHECKPOINTER_SETUP_DONE: set[str] = set()


def _psycopg_dsn(value: str) -> str:
    """Mirror of ``clue_api.entity_research_runtime_wiring._psycopg_dsn``.

    The platform's ``database_url()`` names an async driver; ``PostgresSaver`` is the SYNC saver
    and speaks plain psycopg. It has to be the sync one: the turn body it wraps is synchronous
    and runs inside ``asyncio.to_thread``, where there is no event loop to await on.
    """
    return value.replace("postgresql+asyncpg://", "postgresql://").replace(
        "postgresql+psycopg://",
        "postgresql://",
    )


def _ensure_checkpoint_tables(saver: Any) -> None:
    """Run LangGraph's ``setup()`` only when the database is behind the installed library.

    Sync twin of ``clue_api.agent_execution_wiring.ensure_checkpoint_tables`` (this subsystem may
    not import the platform app). The tables come from the platform's Alembic migration
    ``4a94970221e9``, created by the owner; production opens this saver as ``clue_worker``, which
    has no CREATE on schema public, and ``setup()`` always issues ``CREATE TABLE IF NOT EXISTS``
    (2026-10-03). A database the migration has not reached still gets ``setup()``.
    """
    import psycopg

    latest = len(saver.MIGRATIONS) - 1
    try:
        # LangGraph's own read in setup(); its connections return dict rows.
        row = saver.conn.execute(
            "SELECT v FROM checkpoint_migrations ORDER BY v DESC LIMIT 1"
        ).fetchone()
        recorded = row["v"] if row is not None else None
    except psycopg.errors.UndefinedTable:
        recorded = None
    if recorded is None or recorded < latest:
        saver.setup()


@contextlib.contextmanager
def postgres_design_checkpointer(thread_id: str) -> Any:
    """Open the design turn's LangGraph saver on the platform database.

    Opened INSIDE the turn thread (the caller is ``_execute_turn``, itself under ``to_thread``),
    which is what makes a synchronous saver correct here. The thread is the DOCUMENT's design
    session for a leg turn (one document = one session, 2026-09-18) and the design run id for a
    turn that has no document — the caller decides, so a continued session's messages are here
    under the id its earlier turns wrote. See ``lumen_agent/checkpoint.py`` for what resuming
    that thread does and does not mean today.
    """
    from clue_db import database_url
    from langgraph.checkpoint.postgres import PostgresSaver

    dsn = _psycopg_dsn(database_url())
    with PostgresSaver.from_conn_string(dsn) as saver:
        if dsn not in _CHECKPOINTER_SETUP_DONE:
            _ensure_checkpoint_tables(saver)
            _CHECKPOINTER_SETUP_DONE.add(dsn)
        logger.debug("design_job.checkpointer_open", thread_id=thread_id)
        yield saver


def build_design_job_handler(
    *,
    host_provider: Any = None,
    checkpointer_factory: Any = postgres_design_checkpointer,
    spend_drain: Any = None,
    turn_callbacks_factory: Any = None,
    platform_reads_factory: Any = None,
    ingestion_only: bool = False,
    named_trace: bool = True,
) -> DesignJobWorkHandler:
    """The ONE factory both deployments compose — the embedded worker and ``fleet_main``.

    ``checkpointer_factory=None`` runs turns without durable graph state (what the design API's
    stubbed-runner tests want: the stub never builds a graph, so a saver would only add a
    connection per turn). Ingestion never has one — it is a pipeline, not a graph.

    ``turn_callbacks_factory`` (lane 3 slice 5) is called once per TURN envelope and returns that
    turn's ``lumen_agent.usage_collector.TurnCallbacks``. With none, a turn gets the platform's
    Langfuse handler when Langfuse is installed (2026-10-03 spec, R7), so every path that runs the
    design graph reports it; receipts are collected into ``result_json`` either way.

    ``named_trace=False`` is for a caller that already runs the job inside its own named trace
    (the platform's inline leg lane, inside ``design-leg.turn``).

    ``platform_reads_factory`` (design note 2026-09-19) rides the HOST rather than the frozen
    job, like the preference resolver: it is a live callable the platform composes with its own
    tool invoker. It is applied here rather than inside each caller's ``host_provider`` so the
    rule holds however the host was built — the platform's provider carries its preference
    resolver, the default provider carries nothing, and both come back with these reads.
    """
    if platform_reads_factory is not None:
        build_host = host_provider if host_provider is not None else DesignTurnHost

        def with_platform_reads() -> DesignTurnHost:
            return replace(build_host(), platform_reads_factory=platform_reads_factory)

        host_provider = with_platform_reads

    return DesignJobWorkHandler(
        host_provider=host_provider,
        checkpointer_factory=checkpointer_factory,
        spend_drain=spend_drain,
        turn_callbacks_factory=turn_callbacks_factory,
        ingestion_only=ingestion_only,
        named_trace=named_trace,
    )


__all__ = [
    "DesignJobWorkHandler",
    "DesignTurnHost",
    "DesignTurnJobError",
    "build_design_job_handler",
    "postgres_design_checkpointer",
]
