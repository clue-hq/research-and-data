"""Offline tests for the :class:`~clue_fleet.ProjectRunWorker` drive loop (PB-B1).

Fake-driven (no DB): the seams (:class:`FakeLeaseStore`, :class:`FakeTaskQueue`,
:class:`ScriptedDriver`) isolate the control flow — claim → lease → step-loop → finish — and its
edges: terminal/paused/stalled outcomes, the lease-held-elsewhere handback, graceful stop,
lease-loss abort, and one run's fault not killing the worker."""

from __future__ import annotations

import asyncio
import time
from datetime import timedelta

import pytest
from tests.fleet.conftest import FakeLeaseStore, FakeTaskQueue, ScriptedDriver, run_row

from clue_core import CampaignPhase, new_campaign_run_id
from clue_fleet import FleetTaskKind, FleetTaskStatus, ProjectRunWorker, enqueue_drive
from clue_research.durable import CampaignRunStatus


def _worker(
    driver: ScriptedDriver,
    queue: FakeTaskQueue,
    leases: FakeLeaseStore,
    **overrides: object,
) -> ProjectRunWorker:
    defaults: dict[str, object] = {
        "worker_id": "worker-under-test",
        "poll_interval": 0.01,
        "heartbeat_interval": 60.0,  # quiet unless a test drives the heartbeat explicitly
        # A generous TTL so the quiet 60s heartbeat still satisfies the ``2·hb < lease_ttl``
        # constructor validation (review finding c); the heartbeat never fires in a fast test.
        "lease_ttl": timedelta(seconds=600),
    }
    defaults.update(overrides)
    return ProjectRunWorker(driver=driver, queue=queue, leases=leases, **defaults)  # type: ignore[arg-type]


def test_drive_to_completion_finishes_task_and_releases_lease() -> None:
    async def _run() -> None:
        run_id = new_campaign_run_id()
        queue, leases = FakeTaskQueue(), FakeLeaseStore()
        await enqueue_drive(queue, run_id)
        driver = ScriptedDriver(
            initial=run_row(run_id, phase=CampaignPhase.REVERSE_PROFILING),
            steps=[
                run_row(run_id, phase=CampaignPhase.ICP_CONFIRMED),
                run_row(run_id, phase=CampaignPhase.HANDOFF, status=CampaignRunStatus.COMPLETED),
            ],
        )
        worker = _worker(driver, queue, leases)

        assert await worker.drain_once() is True

        task = queue.row(FleetTaskKind.DRIVE_RUN, run_id, str(run_id))
        assert task.status is FleetTaskStatus.DONE
        assert task.result_ref["outcome"] == "completed"
        assert task.result_ref["status"] == "completed"
        assert driver.advances == 2
        # Lease was held for the drive and released after it.
        assert "acquire:worker-under-test" in leases.events
        assert leases.events[-1] == "release:worker-under-test"
        assert run_id not in leases.holders

    asyncio.run(_run())


@pytest.mark.parametrize(
    ("resting_status", "outcome"),
    [
        (CampaignRunStatus.PAUSED, "paused"),
        (CampaignRunStatus.FAILED, "failed"),
    ],
)
def test_suspended_and_failed_runs_finish_the_task(
    resting_status: CampaignRunStatus, outcome: str
) -> None:
    async def _run() -> None:
        run_id = new_campaign_run_id()
        queue, leases = FakeTaskQueue(), FakeLeaseStore()
        await enqueue_drive(queue, run_id)
        driver = ScriptedDriver(
            initial=run_row(run_id),
            steps=[run_row(run_id, phase=CampaignPhase.TIER_CHECKPOINT, status=resting_status)],
        )
        worker = _worker(driver, queue, leases)
        await worker.drain_once()

        task = queue.row(FleetTaskKind.DRIVE_RUN, run_id, str(run_id))
        assert task.status is FleetTaskStatus.DONE
        assert task.result_ref["outcome"] == outcome

    asyncio.run(_run())


def test_already_resting_run_is_finished_without_advancing() -> None:
    async def _run() -> None:
        run_id = new_campaign_run_id()
        queue, leases = FakeTaskQueue(), FakeLeaseStore()
        await enqueue_drive(queue, run_id)
        driver = ScriptedDriver(
            initial=run_row(run_id, status=CampaignRunStatus.PAUSED),
        )
        worker = _worker(driver, queue, leases)
        await worker.drain_once()

        assert driver.advances == 0
        task = queue.row(FleetTaskKind.DRIVE_RUN, run_id, str(run_id))
        assert task.result_ref["outcome"] == "paused"

    asyncio.run(_run())


def test_no_progress_run_stalls_instead_of_spinning() -> None:
    async def _run() -> None:
        run_id = new_campaign_run_id()
        queue, leases = FakeTaskQueue(), FakeLeaseStore()
        await enqueue_drive(queue, run_id)
        # advance() returns the same (phase, status) forever — e.g. AWAITING_INPUT not submitted.
        driver = ScriptedDriver(initial=run_row(run_id))
        worker = _worker(driver, queue, leases)
        await worker.drain_once()

        assert driver.advances == 1  # detected on the first repeat, no spin
        task = queue.row(FleetTaskKind.DRIVE_RUN, run_id, str(run_id))
        assert task.status is FleetTaskStatus.DONE
        assert task.result_ref["outcome"] == "stalled"

    asyncio.run(_run())


def test_lease_held_elsewhere_requeues_without_driving() -> None:
    async def _run() -> None:
        run_id = new_campaign_run_id()
        queue, leases = FakeTaskQueue(), FakeLeaseStore()
        leases.holders[run_id] = "another-worker"
        await enqueue_drive(queue, run_id)
        driver = ScriptedDriver(initial=run_row(run_id))
        worker = _worker(driver, queue, leases)
        await worker.drain_once()

        assert driver.advances == 0
        task = queue.row(FleetTaskKind.DRIVE_RUN, run_id, str(run_id))
        assert task.status is FleetTaskStatus.QUEUED  # handed back for the real driver / later
        assert leases.holders[run_id] == "another-worker"

    asyncio.run(_run())


def test_graceful_stop_mid_drive_requeues_and_releases() -> None:
    async def _run() -> None:
        run_id = new_campaign_run_id()
        queue, leases = FakeTaskQueue(), FakeLeaseStore()
        await enqueue_drive(queue, run_id)
        driver = ScriptedDriver(
            initial=run_row(run_id, phase=CampaignPhase.REVERSE_PROFILING),
            steps=[
                run_row(run_id, phase=CampaignPhase.ICP_CONFIRMED),
                run_row(run_id, phase=CampaignPhase.DISCOVERY),
                run_row(run_id, phase=CampaignPhase.HANDOFF, status=CampaignRunStatus.COMPLETED),
            ],
        )
        worker = _worker(driver, queue, leases)
        # Stop after the first phase completes: the in-flight advance finishes (phases are the
        # atomic unit), then the drive stops at the boundary.
        driver.on_advance = worker.stop
        await worker.drain_once()

        assert driver.advances == 1
        task = queue.row(FleetTaskKind.DRIVE_RUN, run_id, str(run_id))
        assert task.status is FleetTaskStatus.QUEUED  # handed back, resumable by any worker
        assert run_id not in leases.holders  # released

    asyncio.run(_run())


def test_renewal_denied_cancels_mid_phase_not_at_boundary() -> None:
    """Behavior change (audit finding #2): a denied renewal (``renew() -> False``) now cancels the
    in-flight phase *immediately* rather than waiting for the next phase boundary. This deliberately
    replaces the old ``test_lease_loss_aborts_the_drive_between_phases`` boundary semantics: the
    zombie window is now cancellation latency, not the rest of the phase."""

    async def _run() -> None:
        run_id = new_campaign_run_id()
        queue, leases = FakeTaskQueue(), FakeLeaseStore()
        await enqueue_drive(queue, run_id)
        # One long-blocking phase: if fencing waited for the boundary, the advance would run to
        # completion (~2s). Immediate cancellation kills it mid-flight — advance never finishes.
        driver = ScriptedDriver(
            initial=run_row(run_id),
            steps=[run_row(run_id, phase=CampaignPhase.ICP_CONFIRMED)],
            advance_delay_s=2.0,
        )
        leases.deny_renewal = True  # the first heartbeat's renew returns False → lease lost
        worker = _worker(
            driver, queue, leases, heartbeat_interval=0.05, lease_ttl=timedelta(seconds=0.5)
        )
        started = time.monotonic()
        await worker.drain_once()
        elapsed = time.monotonic() - started

        assert driver.advance_started == 1  # the phase began…
        assert driver.advance_finished == 0  # …and was cancelled mid-flight, not run to boundary
        assert elapsed < 1.5  # well under the 2s block — cancelled, not awaited
        task = queue.row(FleetTaskKind.DRIVE_RUN, run_id, str(run_id))
        assert task.status is FleetTaskStatus.QUEUED  # the taker (or a retry) drives it on
        # Released unconditionally after unwind (review finding d): holder-guarded, so in prod this
        # is a safe no-op once a real taker has re-acquired; it frees a still-held lease otherwise.
        assert "release:worker-under-test" in leases.events

    asyncio.run(_run())


def test_transient_renewal_exception_does_not_fence_or_kill_heartbeat() -> None:
    """The audit's exact trigger (a renewal that RAISES) made harmless: a single transient renew
    exception is logged and retried, the heartbeat survives, and a multi-phase drive completes
    normally with the lease released — no fencing."""

    async def _run() -> None:
        run_id = new_campaign_run_id()
        queue, leases = FakeTaskQueue(), FakeLeaseStore()
        await enqueue_drive(queue, run_id)
        driver = ScriptedDriver(
            initial=run_row(run_id, phase=CampaignPhase.REVERSE_PROFILING),
            steps=[
                run_row(run_id, phase=CampaignPhase.ICP_CONFIRMED),
                run_row(run_id, phase=CampaignPhase.DISCOVERY),
                run_row(run_id, phase=CampaignPhase.HANDOFF, status=CampaignRunStatus.COMPLETED),
            ],
            advance_delay_s=0.05,
        )
        leases.renew_raise_budget = 1  # the first renew raises, then all succeed
        # Generous TTL so the transient fault is nowhere near the deadline−margin fence.
        worker = _worker(
            driver, queue, leases, heartbeat_interval=0.02, lease_ttl=timedelta(seconds=5)
        )
        await worker.drain_once()

        assert "renew-raised:worker-under-test" in leases.events  # the trigger really fired…
        assert any(e.startswith("renew:") for e in leases.events)  # …and later renews succeeded
        task = queue.row(FleetTaskKind.DRIVE_RUN, run_id, str(run_id))
        assert task.status is FleetTaskStatus.DONE  # drove to completion — NOT fenced
        assert task.result_ref["outcome"] == "completed"
        assert leases.events[-1] == "release:worker-under-test"  # lease released, not abandoned
        assert run_id not in leases.holders

    asyncio.run(_run())


def test_persistent_renewal_exceptions_cancel_the_phase_before_expiry() -> None:
    """When renew keeps raising, the heartbeat cannot prove ownership; once it is within one beat
    of true TTL expiry it declares the lease lost and the supervisor cancels the in-flight phase —
    promptly, well before the long advance would have completed."""

    async def _run() -> None:
        run_id = new_campaign_run_id()
        queue, leases = FakeTaskQueue(), FakeLeaseStore()
        await enqueue_drive(queue, run_id)
        driver = ScriptedDriver(
            initial=run_row(run_id),
            steps=[run_row(run_id, phase=CampaignPhase.ICP_CONFIRMED)],
            advance_delay_s=2.0,  # blocks far longer than the lease TTL
        )
        leases.renew_always_raises = True
        worker = _worker(
            driver, queue, leases, heartbeat_interval=0.1, lease_ttl=timedelta(seconds=0.5)
        )
        started = time.monotonic()
        await worker.drain_once()
        elapsed = time.monotonic() - started

        assert driver.advance_started == 1  # the phase began…
        assert driver.advance_finished == 0  # …but was cancelled before it could finish
        assert elapsed < 1.5  # near the TTL (~0.5s), well under the 2s advance
        task = queue.row(FleetTaskKind.DRIVE_RUN, run_id, str(run_id))
        assert task.status is FleetTaskStatus.QUEUED  # lease_lost outcome → requeued
        # Transient-error fence: we may still hold the lease, so it is now released unconditionally
        # after unwind (review finding d) — freed at once so a takeover needn't wait for expiry.
        assert "release:worker-under-test" in leases.events

    asyncio.run(_run())


def test_driver_error_fails_the_task_but_not_the_worker() -> None:
    async def _run() -> None:
        run_id = new_campaign_run_id()
        queue, leases = FakeTaskQueue(), FakeLeaseStore()
        await enqueue_drive(queue, run_id)

        class ExplodingDriver:
            # §1a rename: flips at stage 2 (docs/specs/PB-rename-campaign-run-to-project-run.md)
            # — a fake RunDriver keeps the seam's legacy parameter names.
            async def status(self, campaign_run_id: object) -> object:
                raise RuntimeError("boom")

            async def advance(self, campaign_run_id: object) -> object:
                raise RuntimeError("boom")

        worker = ProjectRunWorker(
            driver=ExplodingDriver(),  # type: ignore[arg-type]
            queue=queue,  # type: ignore[arg-type]
            leases=leases,  # type: ignore[arg-type]
            worker_id="worker-under-test",
            poll_interval=0.01,
        )
        assert await worker.drain_once() is True  # no raise — the fleet keeps draining

        task = queue.row(FleetTaskKind.DRIVE_RUN, run_id, str(run_id))
        assert task.status is FleetTaskStatus.FAILED  # parked until an explicit requeue
        assert task.result_ref["outcome"] == "error"
        assert run_id not in leases.holders  # still released

    asyncio.run(_run())


def test_heartbeat_touches_the_drive_task_claim() -> None:
    """Each lease renewal also re-stamps the drive task's claim, so a live long drive never
    looks orphaned to other claimants (only a dead driver's claim goes stale)."""

    async def _run() -> None:
        run_id = new_campaign_run_id()
        queue, leases = FakeTaskQueue(), FakeLeaseStore()
        await enqueue_drive(queue, run_id)
        cycle = list(CampaignPhase)[1:] + list(CampaignPhase)[:1]
        steps = [run_row(run_id, phase=phase) for phase in cycle]
        steps.append(
            run_row(run_id, phase=CampaignPhase.HANDOFF, status=CampaignRunStatus.COMPLETED)
        )
        driver = ScriptedDriver(initial=run_row(run_id), steps=steps, advance_delay_s=0.02)
        worker = _worker(driver, queue, leases, heartbeat_interval=0.01)
        await worker.drain_once()

        assert queue.touches > 0

    asyncio.run(_run())


def test_paused_run_can_be_re_driven_after_resume() -> None:
    """The pause → human decision → resume loop: the finished (outcome=paused) drive task is
    re-opened by the next ``enqueue_drive`` and the run drives on to completion."""

    async def _run() -> None:
        run_id = new_campaign_run_id()
        queue, leases = FakeTaskQueue(), FakeLeaseStore()
        await enqueue_drive(queue, run_id)
        driver = ScriptedDriver(
            initial=run_row(run_id),
            steps=[
                run_row(
                    run_id, phase=CampaignPhase.TIER_CHECKPOINT, status=CampaignRunStatus.PAUSED
                )
            ],
        )
        worker = _worker(driver, queue, leases)
        await worker.drain_once()
        task = queue.row(FleetTaskKind.DRIVE_RUN, run_id, str(run_id))
        assert task.status is FleetTaskStatus.DONE
        assert task.result_ref["outcome"] == "paused"

        # The human approves; the resume surface re-offers the drive.
        assert await enqueue_drive(queue, run_id) is True
        driver.initial = run_row(run_id, phase=CampaignPhase.DEEP)
        driver.steps = [
            run_row(run_id, phase=CampaignPhase.HANDOFF, status=CampaignRunStatus.COMPLETED)
        ]
        assert await worker.drain_once() is True
        task = queue.row(FleetTaskKind.DRIVE_RUN, run_id, str(run_id))
        assert task.status is FleetTaskStatus.DONE
        assert task.result_ref["outcome"] == "completed"

    asyncio.run(_run())


def test_conservative_deadline_declares_loss_no_later_than_true_expiry() -> None:
    """Review finding (a): the ownership deadline is seeded from the loop time captured *before*
    the acquire round-trip (and refreshed from a pre-renew capture), so the local deadline is
    never later than the DB's ``expires_at``. With a slow store, the OLD code — which seeded the
    deadline *after* the round-trip returned — drifts the fence a full round-trip past true expiry.

    A ``RecordingDriver`` timestamps the moment its long-blocking advance is cancelled (i.e. when
    the heartbeat declared the lease lost). Under the fix the loss lands close to
    ``t_acquire + ttl``; under the old post-round-trip seed it drifts markedly later — the RED
    (observed ~1.1s vs the fix's ~0.7s for a 0.6s TTL with 0.3s store latency)."""

    async def _run() -> None:
        run_id = new_campaign_run_id()
        queue, leases = FakeTaskQueue(), FakeLeaseStore()
        await enqueue_drive(queue, run_id)
        leases.latency_s = 0.3  # a slow store: acquire and every renew take ~0.3s
        leases.renew_always_raises = True  # ownership can never be re-proven → deadline governs

        loop = asyncio.get_running_loop()

        class RecordingDriver:
            def __init__(self) -> None:
                self.cancelled_at: float | None = None

            # §1a rename: flips at stage 2 — a fake RunDriver keeps the seam's legacy param names.
            async def status(self, campaign_run_id: object) -> object:
                return run_row(run_id)

            async def advance(self, campaign_run_id: object) -> object:
                try:
                    await asyncio.sleep(10)  # long-blocking phase; only cancellation ends it
                except asyncio.CancelledError:
                    self.cancelled_at = loop.time()
                    raise
                return run_row(run_id)

        driver = RecordingDriver()
        ttl_s = 0.6
        worker = ProjectRunWorker(
            driver=driver,  # type: ignore[arg-type]
            queue=queue,  # type: ignore[arg-type]
            leases=leases,  # type: ignore[arg-type]
            worker_id="worker-under-test",
            poll_interval=0.01,
            heartbeat_interval=0.1,
            lease_ttl=timedelta(seconds=ttl_s),
        )
        t_acquire = loop.time()
        await worker.drain_once()

        assert driver.cancelled_at is not None  # the phase was fenced (cancelled), not run to end
        drift = driver.cancelled_at - t_acquire
        # The fix lands the fence within ~one heartbeat+latency of true expiry (~0.7s here); the old
        # post-round-trip seed drifts it a full acquire-round-trip later (~1.1s). 0.9s cleanly
        # separates the two.
        assert drift <= 0.9, f"lease-loss declared too late ({drift:.3f}s after acquire)"

    asyncio.run(_run())


def test_constructor_rejects_too_wide_heartbeat() -> None:
    """Review finding (c): ``2·heartbeat_interval < lease_ttl`` is enforced at construction — a
    config where a single transient renew blip would false-fence a healthy lease is a build error,
    not a latent runtime hazard."""
    driver = ScriptedDriver(initial=run_row(new_campaign_run_id()))
    with pytest.raises(ValueError, match="heartbeat_interval"):
        ProjectRunWorker(
            driver=driver,  # type: ignore[arg-type]
            heartbeat_interval=5.0,
            lease_ttl=timedelta(seconds=8),  # 2*5 = 10 >= 8 → rejected
        )
    # 2*1 = 2 < 10 → accepted.
    ProjectRunWorker(
        driver=driver,  # type: ignore[arg-type]
        heartbeat_interval=1.0,
        lease_ttl=timedelta(seconds=10),
    )


def test_release_after_transient_error_fence_frees_the_lease_immediately() -> None:
    """Review finding (d): after a transient-error fence the worker may still hold the lease, so
    the ``finally`` now releases it UNCONDITIONALLY (holder-guarded) once the drive is unwound —
    the still-held lease is freed at once so a takeover need not wait a full TTL. The OLD code
    skipped release whenever ``lease_lost`` was set, stalling the run until expiry (RED: no
    ``release`` event; the holder slot stays ours; a second worker's acquire is denied)."""

    async def _run() -> None:
        run_id = new_campaign_run_id()
        queue, leases = FakeTaskQueue(), FakeLeaseStore()
        await enqueue_drive(queue, run_id)
        leases.renew_always_raises = True  # persistent renew fault → transient-error fence
        driver = ScriptedDriver(
            initial=run_row(run_id),
            steps=[run_row(run_id, phase=CampaignPhase.ICP_CONFIRMED)],
            advance_delay_s=2.0,  # long phase; the fence cancels it mid-flight
        )
        worker = _worker(
            driver, queue, leases, heartbeat_interval=0.1, lease_ttl=timedelta(seconds=0.5)
        )
        await worker.drain_once()

        assert any(e.startswith("release:worker-under-test") for e in leases.events)  # RED old
        assert run_id not in leases.holders  # holder slot cleared, not left ours
        # A second worker can acquire immediately — no expire() needed (the lease was freed).
        acquired = await leases.acquire(
            project_run_id=run_id, worker_id="worker-2", ttl=timedelta(seconds=1)
        )
        assert acquired is True

    asyncio.run(_run())


def test_photo_finish_prefers_the_drives_terminal_result() -> None:
    """Review finding (e): when the final advance and the fencing renew resolve on the same tick,
    ``asyncio.wait`` can return with BOTH tasks done. The drive's real result must win — a
    terminal run must not be misreported ``lease_lost`` and requeued. Checked ``drive in done``
    first now; the OLD ``heartbeat in done`` branch flaked into a spurious ``lease_lost``.

    Repeated to expose the race; under the fix the outcome is ALWAYS ``completed``."""

    async def _run() -> None:
        for i in range(25):
            run_id = new_campaign_run_id()
            queue, leases = FakeTaskQueue(), FakeLeaseStore()
            await enqueue_drive(queue, run_id)
            gate = asyncio.Event()
            leases.renew_gate = gate  # a renew parks on the gate, returns False when it is set
            driver = ScriptedDriver(
                initial=run_row(run_id),
                steps=[
                    run_row(run_id, phase=CampaignPhase.HANDOFF, status=CampaignRunStatus.COMPLETED)
                ],
                advance_delay_s=0.002,  # slightly longer than the beat, so the renew is parked
                on_advance=gate.set,  # the final advance releases the fencing renew, same tick
            )
            worker = _worker(
                driver,
                queue,
                leases,
                heartbeat_interval=0.0005,
                lease_ttl=timedelta(seconds=1),
            )
            await worker.drain_once()

            task = queue.row(FleetTaskKind.DRIVE_RUN, run_id, str(run_id))
            assert task.result_ref.get("outcome") == "completed", (
                f"iteration {i}: terminal drive misreported as {task.result_ref.get('outcome')!r}"
            )
            assert task.status is FleetTaskStatus.DONE

    asyncio.run(_run())


def test_touch_runs_on_the_renew_error_path_too() -> None:
    """Review finding (f): the drive-task claim is re-stamped every beat — including beats where
    the renew errored — so a sustained transient renew fault can't let a live driver's claim cross
    ``task_stale_after`` (which would let a sibling re-own and double-run the job). The OLD code
    touched only after a *successful* renew, so a persistently-erroring renew stamped nothing
    (RED: ``queue.touches == 0``)."""

    async def _run() -> None:
        run_id = new_campaign_run_id()
        queue, leases = FakeTaskQueue(), FakeLeaseStore()
        await enqueue_drive(queue, run_id)
        leases.renew_always_raises = True  # every renew errors → no successful renew, ever
        cycle = list(CampaignPhase)[1:]
        steps = [run_row(run_id, phase=phase) for phase in cycle]
        steps.append(
            run_row(run_id, phase=CampaignPhase.HANDOFF, status=CampaignRunStatus.COMPLETED)
        )
        driver = ScriptedDriver(initial=run_row(run_id), steps=steps, advance_delay_s=0.03)
        # A large TTL so the drive completes long before the deadline-margin fence — the point is
        # to observe error-beat touches, not a fence.
        worker = _worker(
            driver, queue, leases, heartbeat_interval=0.01, lease_ttl=timedelta(seconds=5)
        )
        await worker.drain_once()

        assert any(e.startswith("renew-raised:") for e in leases.events)  # the fault fired…
        assert queue.touches > 0  # …and the claim was still touched on the error beats (RED old)

    asyncio.run(_run())


def test_run_loop_drains_until_stopped() -> None:
    async def _run() -> None:
        run_a, run_b = new_campaign_run_id(), new_campaign_run_id()
        queue, leases = FakeTaskQueue(), FakeLeaseStore()
        await enqueue_drive(queue, run_a)
        await enqueue_drive(queue, run_b)
        driver = ScriptedDriver(
            initial=run_row(run_a, status=CampaignRunStatus.COMPLETED),
        )
        worker = _worker(driver, queue, leases)

        async def _stop_when_drained() -> None:
            while any(
                queue.row(FleetTaskKind.DRIVE_RUN, run, str(run)).status is not FleetTaskStatus.DONE
                for run in (run_a, run_b)
            ):
                await asyncio.sleep(0.01)
            worker.stop()

        await asyncio.wait_for(asyncio.gather(worker.run(), _stop_when_drained()), timeout=5)
        assert worker.stopping

    asyncio.run(_run())
