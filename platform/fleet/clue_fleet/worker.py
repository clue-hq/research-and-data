"""The detached ``ProjectRunWorker`` (PB-B1 — harness build step 0).

The separate process that owns *execution*: chat sessions plan and steer, the worker drives
(harness §6 — "sessions never execute research; the worker owns execution"). Its loop is a task
drain over the durable ``fleet_task`` queue:

    claim a ``drive_run`` task → acquire the run's driver lease → step the run
    (``advance`` per phase, heartbeating the lease concurrently) → finish the task with the
    run's resting state → release the lease.

**Kill-safety is inherited, not invented** (spec §2.3): kill -9 leaves the lease to expire, the
claimed task to go stale, and the run at its last durable checkpoint; the next worker re-owns
both and the M7 replay machinery (``COMMITTED`` short-circuit, phase + account-step idempotency
ledgers) makes the resume exactly-once. **Single-driver is enforced here**: the lease acquire is
the gate M7.3's zero-``stale_after`` phase idempotency was designed to stand behind — a second
worker cannot drive a leased run, and takes over only after expiry.

**Fencing is supervised-heartbeat + immediate mid-phase cancellation** (spec §2.3, the ruling
that replaces the earlier "cooperative fencing / abort at the next phase boundary" language). The
heartbeat is a *supervised* task, not a fire-and-forget coroutine: a renewal that raises no
longer silently kills it (the audit's finding #2 — a dead heartbeat while the phase runs on past
expiry lets a takeover worker drive the same run). Instead the heartbeat is resilient (a
transient renew fault is logged, the drive-task claim re-stamped, and the renew retried — with
denser retries as the deadline nears) and authoritative (it proves lease ownership against the
event loop's monotonic clock — a *conservative* deadline seeded from the pre-call instant of each
acquire/renew so the local deadline is never later than the DB's server-stamped ``expires_at`` —
and, once it can no longer prove ownership before true expiry, declares the lease lost). A
construction-time ``2·heartbeat_interval < lease_ttl`` invariant guarantees a healthy lease always
has a beat of margin, so a lone transient blip can't false-fence it. ``_drive_task`` supervises the
drive *and* the heartbeat together (``asyncio.wait(FIRST_COMPLETED)``): a heartbeat finishing while
the drive is still pending is a fencing event that **cancels the in-flight phase immediately**, so
the zombie window shrinks from "the rest of the phase" (unbounded) to cancellation latency (on a
same-tick photo finish the drive's real terminal result wins, never a spurious ``lease_lost``).
Once both children are fully unwound, ``_drive_task`` releases the lease **unconditionally** — a
holder-guarded no-op after a genuine takeover, but after a transient-error fence it frees the
still-held lease at once so a takeover needn't wait a full TTL for expiry. Hard fence tokens (a
lease token checked on every
durable write) are explicitly **deferred** — they touch ``durable/`` write paths outside B1's
treaty scope and are an integration/Temporal-era follow-up; the residual is that ``advance()``'s
durable writes are still un-fenced during the cancellation-latency window, the same class as the
documented resume-path residual, bounded by the M7 ledgers + the per-entity locks.

The worker never composes phase handlers: it drives the injected :class:`RunDriver` seam, which
:class:`~clue_research.durable.CampaignRun` satisfies structurally (asserted below). The
production composition (real handlers, budget engine, ledger) is ``clue_api`` wiring and lands
at integration (treaty §3.4); tests compose stub-handler drivers.
"""

from __future__ import annotations

import asyncio
import contextlib
from datetime import timedelta
from typing import Protocol, runtime_checkable
from uuid import UUID, uuid4

from pydantic import JsonValue

from clue_core import CampaignRunId
from clue_fleet.enums import FleetTaskKind, FleetTaskStatus
from clue_fleet.lease import DEFAULT_LEASE_TTL, DbLeaseStore, LeaseStore
from clue_fleet.queue import (
    DEFAULT_TASK_STALE_AFTER,
    DbTaskQueue,
    FleetTaskRow,
    TaskQueue,
)
from clue_obs import get_logger
from clue_research.durable import CampaignRun, CampaignRunRow, CampaignRunStatus

log = get_logger("clue_fleet.worker")

# Drive outcomes recorded on the finished task's ``result_ref.outcome`` — the vocabulary the B4
# projections will read. ``completed``/``failed`` mirror the run's terminal status; ``paused`` is
# a suspended run (human gate / budget graceful-stop / client pause — re-driving is a fresh
# enqueue by the resume surface); ``stalled`` is an ACTIVE run that made no progress (awaiting a
# checkpoint submission), mirroring ``run_to_completion``'s no-progress guard.
_TERMINAL_OUTCOMES = {
    CampaignRunStatus.COMPLETED: "completed",
    CampaignRunStatus.FAILED: "failed",
    CampaignRunStatus.PAUSED: "paused",
}


@runtime_checkable
class RunDriver(Protocol):
    """The slice of :class:`~clue_research.durable.CampaignRun` the worker drives (PB-B1).

    A structural seam (conventions §2) so the loop is testable with a fake driver; the real
    state machine satisfies it (asserted at the bottom of this module). The worker owns the
    step loop — one ``advance`` per phase — so it can heartbeat, honour a graceful stop, and be
    fenced on lease loss. Fencing cancels the in-flight ``advance`` immediately (spec §2.3); the
    between-phase ``lease_lost`` check in :meth:`ProjectRunWorker._drive` is only a cheap belt.

    The ``campaign_run_id`` parameter name is a deliberate stage-1 exception: it is checked for
    parameter-name compatibility by the static ``_CAMPAIGN_RUN_IS_A_RUN_DRIVER`` conformance
    assertion against the untouchable ``durable.CampaignRun``, which B1 may not edit."""

    # §1a rename: flips at stage 2 (docs/specs/PB-rename-campaign-run-to-project-run.md)
    async def status(self, campaign_run_id: CampaignRunId) -> CampaignRunRow: ...

    # §1a rename: flips at stage 2 (docs/specs/PB-rename-campaign-run-to-project-run.md)
    async def advance(self, campaign_run_id: CampaignRunId) -> CampaignRunRow: ...


class ProjectRunWorker:
    """The detached worker process's engine (PB-B1). Construct with the injected collaborators,
    call :meth:`run` in the process's event loop, and :meth:`stop` (e.g. from a SIGTERM handler)
    for a graceful drain — finish the in-flight phase, hand the task back, release the lease."""

    def __init__(
        self,
        *,
        driver: RunDriver,
        queue: TaskQueue | None = None,
        leases: LeaseStore | None = None,
        worker_id: str | None = None,
        poll_interval: float = 1.0,
        lease_ttl: timedelta = DEFAULT_LEASE_TTL,
        heartbeat_interval: float = 10.0,
        task_stale_after: timedelta = DEFAULT_TASK_STALE_AFTER,
    ) -> None:
        # Config validation (review finding c): a lease needs at least *two* heartbeats of margin
        # inside one TTL. When ``2·heartbeat_interval >= lease_ttl`` the first post-renew beat is
        # already inside the ``deadline − heartbeat_interval`` loss margin, so a single transient
        # renew blip false-fences a perfectly healthy lease. Reject that config at construction
        # rather than let it fence at runtime. (This closes part of the settings-validation backlog
        # item; full Settings-level validation of the ``CLUE_FLEET_*`` knobs remains open.)
        if heartbeat_interval * 2 >= lease_ttl.total_seconds():
            raise ValueError(
                "heartbeat_interval * 2 must be < lease_ttl "
                f"(got heartbeat_interval={heartbeat_interval}s, "
                f"lease_ttl={lease_ttl.total_seconds()}s): a lease needs two heartbeats of margin "
                "inside one TTL, else a single transient renew fault false-fences a live lease."
            )
        self._driver = driver
        self._queue: TaskQueue = queue if queue is not None else DbTaskQueue()
        self._leases: LeaseStore = leases if leases is not None else DbLeaseStore()
        self.worker_id = worker_id if worker_id is not None else f"worker:{uuid4()}"
        self._poll_interval = poll_interval
        self._lease_ttl = lease_ttl
        self._heartbeat_interval = heartbeat_interval
        self._task_stale_after = task_stale_after
        self._stop = asyncio.Event()

    def stop(self) -> None:
        """Request a graceful drain: claim nothing further; the in-flight phase finishes, its
        task is requeued, its lease released. Safe from a signal handler."""
        self._stop.set()

    @property
    def stopping(self) -> bool:
        return self._stop.is_set()

    async def run(self) -> None:
        """The drain loop: claim → drive → finish, until :meth:`stop`."""
        log.info("worker.start", worker_id=self.worker_id)
        while not self._stop.is_set():
            drove = await self.drain_once()
            if not drove:
                await self._sleep(self._poll_interval)
        log.info("worker.stop", worker_id=self.worker_id)

    async def drain_once(self) -> bool:
        """Claim and drive at most one ``drive_run`` task; ``False`` when nothing was claimable
        (the caller polls). Exposed for tests and for single-shot drains."""
        task = await self._queue.claim_next(
            kind=FleetTaskKind.DRIVE_RUN,
            worker_id=self.worker_id,
            stale_after=self._task_stale_after,
        )
        if task is None:
            return False
        await self._drive_task(task)
        return True

    # -- internals --

    async def _drive_task(self, task: FleetTaskRow) -> None:
        run_id = task.project_run_id
        # Capture the loop clock BEFORE the acquire round-trip (review finding a): the DB stamps
        # ``expires_at`` server-side at statement time, so seeding the heartbeat's ownership
        # deadline from *this* pre-call instant (rather than from the time the round-trip returns)
        # keeps the local deadline ≤ the DB expiry — the fence never fires after true expiry.
        t_acquire = asyncio.get_running_loop().time()
        acquired = await self._leases.acquire(
            project_run_id=run_id, worker_id=self.worker_id, ttl=self._lease_ttl
        )
        if not acquired:
            # Another worker holds this run's lease live — it is the driver, not us. Hand the
            # task back (it will be claimable again once we or another worker retry after the
            # lease state changes) and back off one poll to avoid a tight claim/requeue spin.
            log.info("worker.lease_held_elsewhere", worker_id=self.worker_id, run_id=str(run_id))
            await self._queue.requeue(task_id=task.task_id, worker_id=self.worker_id)
            await self._sleep(self._poll_interval)
            return

        lease_lost = asyncio.Event()
        drive = asyncio.create_task(self._drive(run_id, lease_lost))
        heartbeat = asyncio.create_task(
            self._heartbeat(run_id, task.task_id, lease_lost, t_acquire)
        )
        outcome: str
        run: CampaignRunRow | None
        try:
            done, _pending = await asyncio.wait(
                {drive, heartbeat}, return_when=asyncio.FIRST_COMPLETED
            )
            if drive in done:
                # The DRIVE finished first — its result is authoritative even on a same-tick photo
                # finish where the heartbeat also completed (review finding e): a terminal drive
                # must never be misreported ``lease_lost`` and requeued for a redundant re-drive.
                # Stop heartbeating and read the drive's result (or re-raise its exception).
                heartbeat.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await heartbeat
                outcome, run = drive.result()
            else:
                # FENCING EVENT: only the heartbeat finished (the drive is still pending) — the
                # lease is gone (or is about to expire). Ensure the flag is set, surface any crash
                # (never silently drop the heartbeat's exception — that was the bug), then cancel
                # the in-flight phase IMMEDIATELY (mid-phase, not at the next boundary — the zombie
                # window is now cancellation latency) and take the lease_lost outcome path.
                lease_lost.set()
                hb_exc = heartbeat.exception()
                if hb_exc is not None:
                    log.error(
                        "worker.heartbeat_crashed",
                        worker_id=self.worker_id,
                        run_id=str(run_id),
                        exc_info=hb_exc,
                    )
                drive.cancel()
                # Suppress ONLY the child's cancellation — a CancelledError aimed at the worker
                # loop itself (from `await asyncio.wait`) is BaseException and still propagates.
                with contextlib.suppress(asyncio.CancelledError):
                    await drive
                outcome, run = "lease_lost", None
        except Exception:
            # One run's fault must not kill the worker (the fleet keeps draining other runs):
            # record the task FAILED — it stays parked until an explicit requeue — and move on.
            log.exception("worker.drive_error", worker_id=self.worker_id, run_id=str(run_id))
            await self._queue.finish(
                task_id=task.task_id,
                worker_id=self.worker_id,
                status=FleetTaskStatus.FAILED,
                result_ref={"outcome": "error"},
            )
            return
        finally:
            # Fully unwind BOTH children before touching the lease (review finding d): cancel any
            # still-running child and gather both so a cancelled ``advance`` can never still be
            # mid-write when we release. ``return_exceptions=True`` also retrieves any stray
            # exception so it isn't logged as never-retrieved.
            if not drive.done():
                drive.cancel()
            if not heartbeat.done():
                heartbeat.cancel()
            await asyncio.gather(drive, heartbeat, return_exceptions=True)
            # Release UNCONDITIONALLY, now that the drive is fully unwound. Release is
            # holder-guarded (``WHERE worker_id = :me``): after a genuine takeover it is a safe
            # no-op (the lease belongs to the taker), but after a *transient-error* fence we may
            # still hold the lease — releasing frees it at once so a takeover need not wait a full
            # TTL for expiry. Never let a release fault mask the real drive outcome.
            try:
                await self._leases.release(project_run_id=run_id, worker_id=self.worker_id)
            except Exception:
                log.warning(
                    "worker.release_error",
                    worker_id=self.worker_id,
                    run_id=str(run_id),
                    exc_info=True,
                )

        result_ref: dict[str, JsonValue] = {"outcome": outcome}
        if run is not None:
            result_ref["phase"] = run.phase.value
            result_ref["status"] = run.status.value
        log.info("worker.drive_end", worker_id=self.worker_id, run_id=str(run_id), outcome=outcome)
        if outcome in ("stopped", "lease_lost"):
            # Unfinished business: graceful stop hands the run back for any worker to continue;
            # a lost lease means someone else already owns the drive — either way the task goes
            # back to the queue (holder-guarded: a no-op if a stale-reclaim already re-owned it).
            await self._queue.requeue(task_id=task.task_id, worker_id=self.worker_id)
            return
        await self._queue.finish(
            task_id=task.task_id,
            worker_id=self.worker_id,
            status=FleetTaskStatus.DONE,
            result_ref=result_ref,
        )

    async def _drive(
        self, run_id: CampaignRunId, lease_lost: asyncio.Event
    ) -> tuple[str, CampaignRunRow | None]:
        """Advance the run phase-by-phase until it rests. Returns the drive outcome and the last
        observed run row (``None`` only if the first status read raised). Lease loss now fences by
        *cancelling* this coroutine mid-phase (``_drive_task`` supervises the heartbeat); the
        ``lease_lost`` check below is only a cheap between-phase belt, not the real mechanism."""
        run = await self._driver.status(run_id)
        while True:
            terminal = _TERMINAL_OUTCOMES.get(run.status)
            if terminal is not None:
                return terminal, run
            if self._stop.is_set():
                return "stopped", run
            if lease_lost.is_set():
                return "lease_lost", run
            before = (run.phase, run.status)
            run = await self._driver.advance(run_id)
            resting = _TERMINAL_OUTCOMES.get(run.status)
            if resting is not None:
                return resting, run
            if (run.phase, run.status) == before:
                # ACTIVE but not moving (e.g. awaiting a checkpoint submission) — stop rather
                # than spin; mirrors ``run_to_completion``'s no-progress guard.
                return "stalled", run

    async def _heartbeat(
        self, run_id: CampaignRunId, task_id: UUID, lease_lost: asyncio.Event, t_acquire: float
    ) -> None:
        """The supervised, authoritative lease heartbeat (spec §2.3 — replaces cooperative
        fencing). Renews the lease each beat; when it can no longer prove ownership it sets
        ``lease_lost`` and returns, which ``_drive_task`` reads as a fencing event and uses to
        cancel the in-flight phase immediately (not at the next boundary).

        Resilient to transient faults, authoritative on true loss:

        * ``renew()`` returns ``False`` → the lease is authoritatively gone (expired or taken):
          flag lease-lost and return.
        * ``renew()`` RAISES → a transient fault (a DB blip on the renewal path — the audit's
          exact trigger). Log it (keep the traceback) and keep beating; the coroutine must NOT
          die. But we can only keep driving while we can still prove ownership — ownership is
          tracked against the event loop's monotonic clock (``deadline``). Once we are within one
          ``heartbeat_interval`` of true expiry (no beat of safety margin left before the lease
          lapses) we can no longer guarantee a renewal in time, so we declare the lease lost and
          let the supervisor fence the phase.

        **Conservative deadline** (review finding a): ``deadline`` is seeded from ``t_acquire`` —
        the loop time captured *before* the acquire round-trip in ``_drive_task`` — and refreshed
        after each successful renew from ``t0``, the loop time captured *before* that renew's
        round-trip. Since the DB stamps ``expires_at`` server-side at statement time, the local
        deadline is thus always ≤ the DB's true expiry (monotonic-vs-DB-clock drift over one TTL is
        negligible). That, plus the construction-time ``2·heartbeat_interval < lease_ttl``
        guarantee, means declaring loss at ``deadline − heartbeat_interval`` genuinely leaves a
        beat of margin before any takeover is possible.

        **Denser retries near the deadline** (review finding b): on the renew-error path we retry
        after a fraction of the remaining margin (bounded below by 50ms) rather than a full beat,
        so a transient blip gets several attempts inside the remaining margin, not one.

        ``touch()`` re-stamps the drive-task claim EVERY beat — including error beats (review
        finding f) — so a sustained renew fault can't let a live driver's claim cross
        ``task_stale_after`` and be re-owned by a sibling. ``touch()`` failures (``False`` or
        exception) are logged and ignored — the churn is recoverable and holder-guarded; it is not
        a fencing matter."""
        loop = asyncio.get_running_loop()
        # The acquire just succeeded → we own the lease for a full TTL from the pre-acquire instant.
        deadline = t_acquire + self._lease_ttl.total_seconds()
        sleep_for = self._heartbeat_interval
        while True:
            await asyncio.sleep(sleep_for)
            t0 = loop.time()  # capture BEFORE the renew round-trip (conservative deadline)
            try:
                renewed = await self._leases.renew(
                    project_run_id=run_id, worker_id=self.worker_id, ttl=self._lease_ttl
                )
            except Exception:
                log.warning(
                    "worker.renew_error",
                    worker_id=self.worker_id,
                    run_id=str(run_id),
                    exc_info=True,
                )
                if loop.time() >= deadline - self._heartbeat_interval:
                    # No safety margin left to land a beat before true expiry — ownership can no
                    # longer be proven; declare it lost so the phase is fenced before takeover.
                    log.warning(
                        "worker.lease_lost_after_renew_errors",
                        worker_id=self.worker_id,
                        run_id=str(run_id),
                    )
                    lease_lost.set()
                    return
                # Still within margin: keep the drive-task claim fresh (finding f) and retry sooner
                # than a full beat — several attempts inside the shrinking margin (finding b).
                await self._touch(task_id, run_id)
                sleep_for = min(self._heartbeat_interval, max(0.05, (deadline - loop.time()) / 4))
                continue
            if not renewed:
                log.warning("worker.lease_lost", worker_id=self.worker_id, run_id=str(run_id))
                lease_lost.set()
                return
            # Renewed → ownership proven for another full TTL from the pre-renew instant ``t0``.
            deadline = t0 + self._lease_ttl.total_seconds()
            sleep_for = self._heartbeat_interval
            await self._touch(task_id, run_id)

    async def _touch(self, task_id: UUID, run_id: CampaignRunId) -> None:
        """Re-stamp the drive-task claim so a live long drive never looks orphaned; failures are
        logged and ignored (holder-guarded, recoverable — not a fencing matter)."""
        try:
            await self._queue.touch(task_id=task_id, worker_id=self.worker_id)
        except Exception:
            log.warning(
                "worker.touch_error",
                worker_id=self.worker_id,
                run_id=str(run_id),
                exc_info=True,
            )

    async def _sleep(self, seconds: float) -> None:
        """Sleep, but wake immediately on :meth:`stop` (a draining worker exits promptly)."""
        with contextlib.suppress(TimeoutError):
            await asyncio.wait_for(self._stop.wait(), timeout=seconds)


async def enqueue_drive(
    queue: TaskQueue, project_run_id: CampaignRunId, *, priority: int = 0
) -> bool:
    """Offer a run to the fleet: enqueue its ``drive_run`` task (dedup key = the run id — one
    drive task per run at a time; a queued/claimed one is a no-op). ``reopen_terminal``: a
    *finished* drive task (the run paused at the human gate, stalled, or previously failed) is
    re-opened for a fresh drive, so the resume surface can always just call this after
    ``submit_checkpoint``/``resume``; tests call it directly."""
    return await queue.enqueue(
        kind=FleetTaskKind.DRIVE_RUN,
        project_run_id=project_run_id,
        dedup_key=str(project_run_id),
        priority=priority,
        reopen_terminal=True,
    )


# Static conformance (the ``deep/handler.py`` pattern): the real state machine must satisfy the
# seam the worker is typed against, so fake-driven loop tests exercise the surface the
# integration wiring will bind.
_CAMPAIGN_RUN_IS_A_RUN_DRIVER: type[RunDriver] = CampaignRun
