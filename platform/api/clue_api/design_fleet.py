"""Design-job registration for the detached fleet worker (Part II slice D5 Round B — R-D5-B2).

A thin composition seam and nothing else. The design turn handler itself lives in
``lumen_api.fleet_handler``, next to the harnesses and by-value resolvers it drives, because
executing a turn needs ``lumen_agent`` and ``lumen_api.main`` — neither of which the platform
composition root has any business importing directly, and neither of which may import
``clue_api`` back (Rule 5: nothing imports the app layer).

So the direction is: ``clue_api.design_fleet`` -> ``lumen_api.fleet_handler``. Legal by
construction — the composition root is the one package allowed to import everything — and
deliberately narrow: this module knows the handler's *name*, never its internals.

The import is LAZY, inside :func:`build_design_job_handler`, for the same reason the design API
lazy-imports its own agent runtime: a platform worker deployed without the design extras must
start and drain everything else, not die at module load. ``settings.design_runtime_enabled``
is the production gate (the ``entity_research_runtime_enabled`` precedent); an unavailable
import behind an ENABLED switch is a hard, loud failure, because that combination means an
operator asked for design work and the deployment cannot do it.
"""

from __future__ import annotations

import asyncio
import contextlib
from collections.abc import Sequence
from datetime import timedelta
from typing import Any
from uuid import uuid4

from clue_api.design_event_forwarder import _DesignEventForwarder
from clue_api.design_memory_runtime import PreferenceResolverFactory
from clue_api.langfuse_callbacks import build_langfuse_callbacks
from clue_db import transaction
from clue_fleet import (
    LeaseGeneration,
    WorkId,
    acquire_work_lease,
    get_work_lease,
    release_work_lease,
    renew_work_lease,
)
from clue_fleet.enums import FleetTaskKind
from clue_fleet.lease import DEFAULT_LEASE_TTL
from clue_fleet.work_worker import WorkContext, WorkHandler
from clue_obs import get_logger

log = get_logger("clue_api.design_fleet")

#: The worker identity the inline design-leg lane holds its work lease under.
_DESIGN_LEG_LANE_WORKER_ID = "design-leg-inline-lane"


class DesignRuntimeUnavailable(RuntimeError):
    """``design_runtime_enabled`` is on but the design app is not importable in this process."""


async def _drain_design_spend(conn: Any, raw: Any, ledger: Any, stamp: Any) -> Any:
    """Land a design unit of work's buffered provider calls — with the platform's incidents.

    The shape ``lumen_api.spend.DrainFn`` names: the design side opens the connection and the
    transaction (it runs on a synchronous executor with its own private engine) and hands them
    here. ``artifacts=None`` because the design lane's response bodies are not persisted to the
    platform's artifact store; the rows land citing nothing there, and the money trail is still
    complete.
    """
    from clue_api.arv2.provider_ledger import drain_provider_calls

    return await drain_provider_calls(conn, raw=raw, ledger=ledger, artifacts=None, stamp=stamp)


def build_design_job_handler(
    *,
    enabled: bool,
    purpose: str = "design_job_drain",
    preference_resolver_factory: PreferenceResolverFactory | None = None,
    turn_callbacks_factory: Any = None,
    platform_reads_factory: Any = None,
    named_trace: bool = True,
) -> WorkHandler | None:
    """The ``design_job`` handler for :func:`build_multi_work_worker`, or ``None`` when off.

    Returned handlers carry ``kind == FleetTaskKind.DESIGN_JOB``; the worker builder re-checks
    that, so a wiring mistake fails at construction rather than at claim time.

    ``purpose`` names the composition site in the registration log. One worker boot builds TWO
    distinct handlers — the drain handler here and the inline leg lane's
    (:func:`build_design_leg_lane_driver`) — so the event fires twice, ~300ms apart, by design.
    Unlabelled it read as a double registration and sent a log-duplication hunt down the wrong
    path; the real duplication was two root console handlers (see ``clue_obs.config``).

    ``turn_callbacks_factory`` (lane 3 slice 5) is called once per TURN envelope on the design
    side and returns that turn's ``lumen_agent.usage_collector.TurnCallbacks``. The drain handler
    here takes none by default; :func:`build_design_leg_lane_driver` passes one that opens the
    platform's Langfuse handler, so a leg's design trio reports into the leg's own trace.

    ``platform_reads_factory`` (design note 2026-09-19) is the leg turn's reads — the target
    account's research through the governed tools and the seller's pinned knowledge — handed
    over the same way the preference resolver is: a live callable composed HERE with the
    worker's invoker and storage, which the design side calls and never assembles. Passed on
    only when present, so a deployment without it composes exactly the handler it did before.
    """
    if not enabled:
        return None
    try:
        from lumen_api.fleet_handler import build_design_job_handler as _build
    except Exception as error:  # pragma: no cover - deployment shape, not logic
        raise DesignRuntimeUnavailable(
            "design_runtime_enabled is set but lumen_api.fleet_handler cannot be imported; "
            "install the design app (subsystems/clue-design/apps/{api,agent_runtime}) or "
            "unset CLUE_DESIGN_RUNTIME_ENABLED"
        ) from error
    extras: dict[str, Any] = {
        # PRE-1b: the WHOLE drain, injected, so a design 402 opens a provider incident under the
        # ARV2 close rule — written once, here, instead of once per design executor. The design
        # side owns the connection and the transaction; this only says what to do with them.
        "spend_drain": _drain_design_spend,
        "turn_callbacks_factory": turn_callbacks_factory,
        # Every drained design job is one named Langfuse trace (2026-10-03 spec, R7); the inline
        # leg lane turns it off because its turns already run inside ``design-leg.turn``.
        "named_trace": named_trace,
    }
    if platform_reads_factory is not None:
        # The design side puts it on the host it builds, whichever host that is — so this rides
        # beside the preference resolver's host_provider rather than inside it.
        extras["platform_reads_factory"] = platform_reads_factory
    if preference_resolver_factory is None:
        handler: Any = _build(**extras)
    else:
        from lumen_api.fleet_handler import DesignTurnHost

        handler = _build(
            host_provider=lambda: DesignTurnHost(
                preference_resolver_factory=preference_resolver_factory
            ),
            **extras,
        )
    if handler.kind is not FleetTaskKind.DESIGN_JOB:
        raise DesignRuntimeUnavailable("the design handler does not own design_job tasks")
    log.info(
        "design_fleet.handler_registered",
        kind=FleetTaskKind.DESIGN_JOB.value,
        purpose=purpose,
    )
    return handler  # type: ignore[no-any-return]


class InlineDesignLaneDriver:
    """Drive one design-leg turn through the design fleet handler, inline, under a LIVE lease.

    P3.4's execution seam (PD-part3 D3). The design turn still runs on the design lane in every
    sense that matters — the same :class:`~lumen_api.fleet_handler.DesignJobWorkHandler`, the
    same claim CAS, the same generation fences, the same run-event stream — but it is *driven by
    the agent-turn worker* instead of queued as a second fleet task. The platform fleet drains
    one task per drain slot (``CLUE_FLEET_WORKER_CONCURRENCY``; exactly one by default),
    so an ``AGENT_TURN`` handler that enqueued a ``design_job`` and awaited it would deadlock a
    deployment whose slots are all busy against itself; holding the design
    work lease and calling the handler directly keeps single-flight, stop and fencing semantics
    without that hazard.

    **The lease is supervised, not fire-and-forget** (adversarial-review finding E; the B1
    supervised-heartbeat precedent). A design turn runs minutes against a 30s lease TTL, and the
    design reaper — enabled by the same switch as this lane — treats a dead lease with no fleet
    task as a strand. So :meth:`drive` races the handler against a renewal loop that beats at
    TTL/3, retries transient renew errors without killing the beat, and declares loss only when
    fenced (a higher generation took over) or when no beat can land before true expiry — at
    which point ``context.lease_lost`` flips and the handler abandons cooperatively, exactly as
    it does under the fleet worker.

    **Whatever happened, the drive ends by joining the run to a terminal state** (bounded).
    A takeover — a reaper-fed design_job worker after a genuine stall — owns only the *design
    run*; the platform turn/leg projection is this worker's alone, so re-joining the takeover's
    terminal result is the only path that completes the platform turn. The normal path pays one
    extra read; the fenced path converges instead of failing.

    Stop semantics are unchanged and doctrine-consistent: a user-stopped platform turn abandons
    the drive (asyncio cancellation), the lease is released, and already-launched design work
    may complete detached — the same stance every launched-work surface takes.
    """

    def __init__(
        self,
        *,
        handler: WorkHandler,
        conn_factory: Any = transaction,
        lease_ttl: timedelta = DEFAULT_LEASE_TTL,
        heartbeat_interval_s: float | None = None,
        join_poll_interval_s: float = 5.0,
        join_timeout_s: float = 1800.0,
        checkpoint_poll_interval_s: float = 1.0,
    ) -> None:
        self._handler = handler
        self._conn_factory = conn_factory
        self._lease_ttl = lease_ttl
        self._heartbeat_interval_s = (
            heartbeat_interval_s
            if heartbeat_interval_s is not None
            else lease_ttl.total_seconds() / 3.0
        )
        self._join_poll_interval_s = join_poll_interval_s
        self._join_timeout_s = join_timeout_s
        #: How often the checkpoint tail reads the design run's outbox. Faster than the join
        #: poll on purpose — the join is a rare recovery path, whereas this cadence is the
        #: latency a marketer sees between the agent committing a round and the canvas showing
        #: it. Slower than the design editor's own 4 Hz stream: rung B's op batches land once
        #: per mutation and rung A's checkpoints once per authoring round (tens of seconds) —
        #: neither is a per-compile-frame cadence, so a 1 Hz tail loses nothing but latency.
        self._checkpoint_poll_interval_s = checkpoint_poll_interval_s
        #: Every tail the CURRENT (or most recent) drive started — one per envelope, so a batch
        #: of N documents reports the frames of all N rather than of whichever ran last.
        #: :meth:`drive` sets it to its single forwarder; :meth:`drive_batch` to the batch's.
        self._forwarders: list[_DesignEventForwarder] = []
        #: Successful renewals across this driver's lifetime — observable, so a test (or an
        #: operator counter) can prove the beat is real rather than infer it from silence.
        self.renewals = 0

    @property
    def frames_forwarded(self) -> int:
        """Design frames — checkpoints and op batches alike — the current (or most recent) drive
        has put on the thread.

        Live rather than summed at the end, for the same reason :attr:`renewals` is: the tail's
        whole claim is that it announces work *while* the turn runs, and a counter that only
        settles afterwards could not tell that apart from a drain.

        Summed across a batch's tails: a multi-document leg's frames all belong to the one chat
        turn, so the count an operator (or a test) reads is the turn's, not one document's.
        """

        return sum(forwarder.forwarded for forwarder in self._forwarders)

    async def drive(self, *, envelope: Any) -> None:
        """Drive the run terminal, tailing its progress onto the leg's thread as it goes.

        The tail runs for the whole drive rather than on the join loop's tick, because the join
        loop only runs when this lane is NOT the one driving: in the ordinary case the handler
        holds the coroutine for the entire turn and the join never spins at all. A background
        poller is therefore the only placement from which a checkpoint can be announced *while*
        the turn is still running, which is the entire point (see
        :class:`~clue_api.design_event_forwarder._DesignEventForwarder` for why every one of its
        failures is swallowed).

        One final drain follows the drive: the last checkpoint of a fast turn can land between
        the tail's last poll and the terminal row, and a frame arriving a beat late is worth
        much more than a frame lost.
        """

        forwarder = _DesignEventForwarder(
            envelope=envelope,
            conn_factory=self._conn_factory,
            poll_interval_s=self._checkpoint_poll_interval_s,
        )
        self._forwarders = [forwarder]
        tail = asyncio.create_task(forwarder.run())
        try:
            await self._drive_to_terminal(envelope=envelope)
        finally:
            tail.cancel()
            with contextlib.suppress(asyncio.CancelledError, Exception):
                await tail
            # Unguarded on purpose: ``drain`` swallows its own failures, so the only thing this
            # can raise is the ``CancelledError`` of a drive the caller is stopping — which must
            # keep propagating rather than be absorbed into a silent normal return.
            await forwarder.drain()

    async def drive_batch(self, *, envelopes: Sequence[Any]) -> None:
        """Drive every run of one leg turn's batch terminal — spec §3.3 step 3.

        The single-run rule applied across siblings, unchanged: for every non-terminal run,
        acquire its lease and drive it inline if nobody holds it; skip it while a LIVE foreign
        lease proves another slot is driving it; when every run that is left is held elsewhere,
        wait and poll. Parallelism is therefore whatever the fleet's free slots supply — an idle
        fleet runs the siblings together, a fully busy one leaves them all to this slot, which
        drives them one after another. There is no new knob (ruling 2026-09-10).

        One tail per envelope for the whole drive, for the same reason :meth:`drive` starts one:
        each document's canvas reloads on its OWN run's checkpoint frames, and the frames must
        be announced while the batch is still running.

        A single-envelope batch delegates to :meth:`drive` verbatim, so a one-document leg keeps
        byte-identical behaviour (and byte-identical logs) to what shipped.
        """

        if len(envelopes) == 1:
            await self.drive(envelope=envelopes[0])
            return
        forwarders = [
            _DesignEventForwarder(
                envelope=envelope,
                conn_factory=self._conn_factory,
                poll_interval_s=self._checkpoint_poll_interval_s,
            )
            for envelope in envelopes
        ]
        self._forwarders = forwarders
        tails = [asyncio.create_task(forwarder.run()) for forwarder in forwarders]
        try:
            await self._drive_batch_to_terminal(envelopes=list(envelopes))
        finally:
            for tail in tails:
                tail.cancel()
            for tail in tails:
                with contextlib.suppress(asyncio.CancelledError, Exception):
                    await tail
            # Unguarded, exactly as in ``drive``: ``drain`` swallows its own failures, so the
            # only thing this can raise is the ``CancelledError`` of a drive being stopped.
            for forwarder in forwarders:
                await forwarder.drain()

    async def _drive_batch_to_terminal(self, *, envelopes: list[Any]) -> None:
        """The batch loop — drive what nobody holds, wait only on a live foreign lease.

        The window is **progress-based** rather than a fixed deadline, which is the one thing
        this loop does that the single-run one cannot: ``join_timeout_s`` is measured from the
        last moment the batch moved (a run reached terminal, or one of our own drives returned),
        so a busy fleet never fails a batch for being large — while a batch nobody is driving
        still fails within the same window one run does.
        """

        loop = asyncio.get_running_loop()
        last_progress = loop.time()
        pending = list(envelopes)
        while pending:
            progressed = False
            still: list[Any] = []
            for envelope in pending:
                if await self._run_is_terminal(envelope):
                    progressed = True
                    continue
                work_id = WorkId(envelope.work_id)
                async with self._conn_factory() as conn:
                    lease = await acquire_work_lease(
                        conn,
                        work_id=work_id,
                        worker_id=_DESIGN_LEG_LANE_WORKER_ID,
                        ttl=self._lease_ttl,
                    )
                if lease is not None:
                    await self._drive_claimed(envelope=envelope, work_id=work_id, lease=lease)
                    progressed = True
                    if not await self._run_is_terminal(envelope):
                        # Fenced mid-drive (or abandoned): re-check it on the next round, where
                        # it either re-acquires or waits on the takeover exactly like any other.
                        still.append(envelope)
                    continue
                async with self._conn_factory() as conn:
                    foreign = await get_work_lease(conn, work_id)
                if foreign is None or not foreign.live:
                    # Free, but our acquire raced someone's release: retry on the next round.
                    # That race IS movement, so it counts as progress.
                    still.append(envelope)
                    progressed = True
                    continue
                # A live foreign holder: a real slot is executing this job. Skip it and wait.
                log.info(
                    "design_leg.lane_lease_held_elsewhere",
                    work_id=str(work_id),
                )
                still.append(envelope)
            pending = still
            if not pending:
                return
            now = loop.time()
            if progressed:
                last_progress = now
            elif now - last_progress >= self._join_timeout_s:
                raise RuntimeError(
                    "the design-leg batch made no progress within the lane's join window; "
                    "the reaper (or an operator requeue) owns what is left"
                )
            await asyncio.sleep(self._join_poll_interval_s)

    async def _drive_to_terminal(self, *, envelope: Any) -> None:
        """Drive the run terminal — actively (MED-6, adversarial-review fix).

        The old shape parked in a blind bounded join whenever it did not hold the lease —
        but on a single-worker deployment the reaper's recovery ``design_job`` lands in the
        very queue the parked worker drains, so a dead holder meant a 30-minute stall. The
        loop's rule instead: **drive whenever nobody else is; wait only while a LIVE foreign
        lease proves someone else is; return the moment the run is terminal.** A fenced-out
        attempt re-acquires once the takeover's lease lapses without a terminal row; the
        claim CAS and the generation fence make the redrive exactly a D5 takeover.
        """

        work_id = WorkId(envelope.work_id)
        loop = asyncio.get_running_loop()
        deadline = loop.time() + self._join_timeout_s
        while True:
            async with self._conn_factory() as conn:
                lease = await acquire_work_lease(
                    conn,
                    work_id=work_id,
                    worker_id=_DESIGN_LEG_LANE_WORKER_ID,
                    ttl=self._lease_ttl,
                )
            if lease is not None:
                await self._drive_claimed(envelope=envelope, work_id=work_id, lease=lease)
            else:
                log.info(
                    "design_leg.lane_lease_held_elsewhere",
                    work_id=str(work_id),
                )
            if await self._run_is_terminal(envelope):
                return
            # Not terminal: either we were fenced mid-drive or a live foreign holder refused
            # the acquire. Wait while that holder's lease is LIVE; the moment it lapses with
            # no terminal row, loop back and drive the run ourselves.
            outcome = await self._await_terminal_or_free(envelope, work_id, deadline)
            if outcome == "terminal":
                return
            if outcome == "deadline":
                raise RuntimeError(
                    "the design-leg run did not reach a terminal state within the lane's "
                    "join window; the reaper (or an operator requeue) owns it now"
                )
            # outcome == "free": nobody is driving — re-acquire.

    async def _drive_claimed(self, *, envelope: Any, work_id: WorkId, lease: Any) -> None:
        generation = LeaseGeneration(lease.generation)
        lease_lost = asyncio.Event()
        context = WorkContext(
            task_id=uuid4(),
            work_id=work_id,
            worker_id=_DESIGN_LEG_LANE_WORKER_ID,
            lease_generation=generation,
            payload=envelope.model_dump(mode="json"),
            stop_requested=asyncio.Event(),
            lease_lost=lease_lost,
        )
        acquired_at = asyncio.get_running_loop().time()
        work = asyncio.create_task(self._handler.handle(context))
        beat = asyncio.create_task(
            self._keep_lease(
                work_id=work_id,
                generation=generation,
                lease_lost=lease_lost,
                acquired_at=acquired_at,
            )
        )
        try:
            done, _pending = await asyncio.wait({work, beat}, return_when=asyncio.FIRST_COMPLETED)
            if work in done:
                result = work.result()
            else:
                # The beat exited ⇒ it declared the lease lost. The handler races
                # ``lease_lost`` itself and abandons cooperatively — await that abandonment
                # rather than cancelling mid-write.
                result = await asyncio.shield(work)
                log.warning(
                    "design_leg.lane_fenced_out",
                    work_id=str(work_id),
                    outcome=result.outcome,
                )
            log.info(
                "design_leg.lane_drive_finished",
                work_id=str(work_id),
                outcome=result.outcome,
            )
        except asyncio.CancelledError:
            from clue_design import runs as design_runs

            async with self._conn_factory() as conn:
                await design_runs.request_run_cancellation(
                    conn, workspace_id=envelope.workspace_id, run_id=envelope.run_id
                )
            # Cancelling an asyncio wrapper does not stop its synchronous job thread.
            # Keep the heartbeat and handler alive until the actual body exits.
            await asyncio.shield(work)
            raise
        finally:
            for task in (beat, work):
                if not task.done():
                    task.cancel()
            with contextlib.suppress(asyncio.CancelledError, Exception):
                await beat
            if work.done() and not work.cancelled():
                with contextlib.suppress(Exception):
                    work.exception()
            async with self._conn_factory() as conn:
                await release_work_lease(
                    conn,
                    work_id=work_id,
                    worker_id=_DESIGN_LEG_LANE_WORKER_ID,
                    generation=generation,
                )

    async def _keep_lease(
        self,
        *,
        work_id: WorkId,
        generation: LeaseGeneration,
        lease_lost: asyncio.Event,
        acquired_at: float,
    ) -> None:
        """Mirror of ``LeasedWorkWorker._heartbeat`` (and the B1 supervised-beat ruling):
        transient renew errors are retried with a shrinking sleep and never silently kill the
        beat; loss is declared only when fenced or when no beat can land before true expiry."""

        loop = asyncio.get_running_loop()
        ttl_s = self._lease_ttl.total_seconds()
        deadline = acquired_at + ttl_s
        sleep_for = self._heartbeat_interval_s
        while True:
            await asyncio.sleep(sleep_for)
            t0 = loop.time()
            try:
                async with self._conn_factory() as conn:
                    renewed = await renew_work_lease(
                        conn,
                        work_id=work_id,
                        worker_id=_DESIGN_LEG_LANE_WORKER_ID,
                        generation=generation,
                        ttl=self._lease_ttl,
                    )
            except Exception:
                log.warning(
                    "design_leg.lane_renew_error",
                    work_id=str(work_id),
                    exc_info=True,
                )
                if loop.time() >= deadline - self._heartbeat_interval_s:
                    lease_lost.set()
                    return
                sleep_for = min(
                    self._heartbeat_interval_s,
                    max(0.05, (deadline - loop.time()) / 4),
                )
                continue
            if not renewed:
                lease_lost.set()
                return
            self.renewals += 1
            deadline = t0 + ttl_s
            sleep_for = self._heartbeat_interval_s

    async def _run_is_terminal(self, envelope: Any) -> bool:
        """One read of the run's terminal state. Lazy DAL import, like the whole module."""

        from clue_design import runs as design_runs

        async with self._conn_factory() as conn:
            run = await design_runs.get_run(
                conn,
                workspace_id=envelope.workspace_id,
                run_id=envelope.run_id,
            )
        return run is not None and run["status"] in ("succeeded", "failed")

    async def _await_terminal_or_free(self, envelope: Any, work_id: WorkId, deadline: float) -> str:
        """Poll until the run is terminal (``"terminal"``), the foreign lease lapses with no
        terminal row (``"free"`` — the caller re-acquires and drives), or the join window
        closes (``"deadline"``). Waiting is justified ONLY by a live foreign lease: a dead
        holder's work will never finish on its own, and the reaper's re-offer lands in the
        queue this very worker drains — so the lane recovers it inline instead (MED-6)."""

        loop = asyncio.get_running_loop()
        last_logged = loop.time()
        while True:
            if await self._run_is_terminal(envelope):
                return "terminal"
            async with self._conn_factory() as conn:
                lease = await get_work_lease(conn, work_id)
            if lease is None or not lease.live:
                return "free"
            now = loop.time()
            if now >= deadline:
                return "deadline"
            if now - last_logged >= 60.0:
                log.info(
                    "design_leg.lane_awaiting_foreign_holder",
                    run_id=str(envelope.run_id),
                    work_id=str(work_id),
                )
                last_logged = now
            await asyncio.sleep(self._join_poll_interval_s)


def build_design_leg_lane_driver(
    *,
    enabled: bool,
    preference_resolver_factory: PreferenceResolverFactory | None = None,
    platform_reads_factory: Any = None,
) -> InlineDesignLaneDriver | None:
    """The design-leg lane for :func:`build_agent_turn_work_handler`, or ``None`` when off.

    Same switch, same lazy import, same fail-loud stance as :func:`build_design_job_handler` —
    a deployment that drains design work can also drive a leg's design turns; one that does not
    must refuse loudly rather than wedge the leg (the ``None`` composes the runner's
    unavailable-lane backstop).

    Lane 3 slice 5: this lane — and only this lane — hands the design side a per-turn Langfuse
    handler. A leg turn runs inside ``design-leg.turn`` (``design_leg_wiring._dispatch``), so the
    trio's generations nest under that observation and each collected receipt can name the
    generation its money belongs to. The factory is called once per turn: the handler and its
    run-id registry are per turn, and a shared instance would cross-attribute one turn's model
    calls onto another's observation.
    """

    def turn_callbacks() -> Any:
        from lumen_agent.usage_collector import TurnCallbacks  # lazy, like fleet_handler

        built = build_langfuse_callbacks()
        if built is None:
            return TurnCallbacks()
        return TurnCallbacks(handlers=(built.handler,), langfuse_ids=built.registry)

    handler = build_design_job_handler(
        enabled=enabled,
        purpose="design_leg_inline_lane",
        preference_resolver_factory=preference_resolver_factory,
        turn_callbacks_factory=turn_callbacks,
        named_trace=False,
        # Design note 2026-09-19: the SAME reads the queued drain handler gets — a leg turn
        # driven inline and one taken over by a design_job worker are one unit of work.
        platform_reads_factory=platform_reads_factory,
    )
    if handler is None:
        return None
    return InlineDesignLaneDriver(handler=handler)


def start_design_reaper(*, enabled: bool, interval_s: float) -> Any:
    """Start the D5 Round C stranded-design-work reaper, or ``None`` when off.

    Same seam, same laziness and same switch as :func:`build_design_job_handler` — the reaper
    lives in ``lumen_api.fleet_reaper`` because judging a stranded design row means reading the
    design DAL, which the composition root does not otherwise touch. It is gated on the SAME
    ``design_runtime_enabled`` switch as the handler on purpose: a deployment that does not drain
    design work has no business re-offering it either.

    Must be called with a running event loop. Returns the task so the caller can cancel it on
    drain (``lumen_api.fleet_reaper.stop_reaper``).
    """
    if not enabled:
        return None
    try:
        from lumen_api.fleet_reaper import start_reaper
    except Exception as error:  # pragma: no cover - deployment shape, not logic
        raise DesignRuntimeUnavailable(
            "design_runtime_enabled is set but lumen_api.fleet_reaper cannot be imported; "
            "install the design app (subsystems/clue-design/apps/{api,agent_runtime}) or "
            "unset CLUE_DESIGN_RUNTIME_ENABLED"
        ) from error
    return start_reaper(interval_s=interval_s)


def start_design_event_pruner(*, interval_s: float, retention_s: float) -> Any:
    """Start the D8 design run-event pruner, or ``None`` when off (``interval_s <= 0``).

    Same lazy seam as the two above and, deliberately, a DIFFERENT switch. The handler and the
    reaper are gated on ``design_runtime_enabled`` because both act on work — a deployment that
    does not drain design turns must not claim or re-offer them. Retention is not work: it is a
    substrate property of a shared table, and it is governed by its own interval knob
    (``design_run_event_prune_interval_s``, **default 0 = disabled**), which is the founder-facing
    switch for the one sweep in the platform that destroys durable run-visibility history.

    Because that default is off, a platform worker without the design app installed never reaches
    the import; a deployment that turns the sweep on and cannot import the design app fails loudly,
    exactly as an enabled-but-unavailable handler does.

    The retention floor is applied inside ``lumen_api.event_pruner`` (never here), so every entry
    point into the pruner gets it. Must be called with a running event loop.
    """
    if interval_s <= 0:
        return None
    try:
        from lumen_api.event_pruner import start_pruner
    except Exception as error:  # pragma: no cover - deployment shape, not logic
        raise DesignRuntimeUnavailable(
            "design_run_event_prune_interval_s is set but lumen_api.event_pruner cannot be "
            "imported; install the design app (subsystems/clue-design/apps/{api,agent_runtime}) "
            "or unset CLUE_DESIGN_RUN_EVENT_PRUNE_INTERVAL_S"
        ) from error
    return start_pruner(interval_s=interval_s, retention_s=retention_s)


__all__ = [
    "DesignRuntimeUnavailable",
    "InlineDesignLaneDriver",
    "build_design_job_handler",
    "build_design_leg_lane_driver",
    "start_design_event_pruner",
    "start_design_reaper",
]
