"""PB-B1 api-composition-root fleet wiring (``clue_api.fleet_wiring`` / ``clue_api.fleet_main``).

Composition-only assertions — construction, settings threading, the fail-loud single-flight
contract, and rubric-derived tier priority. No live Redis or Postgres (construction of the ``Db*``
stores and the lock factory makes no I/O), so these run in the offline ``make check`` suite.
"""

from __future__ import annotations

import asyncio
import contextlib
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import timedelta
from pathlib import Path
from uuid import uuid4

import pytest
from pydantic import SecretStr

from clue_api.fleet_main import (
    NoBootHandlersRegistered,
    _build_onboarding_handler,
    _require_registered,
    _start_orphan_sweep,
)
from clue_api.fleet_wiring import (
    build_account_lock_factory,
    build_fleet_deep_scheduler,
    build_fleet_run_driver,
    build_fleet_worker,
    build_multi_work_worker,
    enqueue_run_drive,
    register_boot_handlers,
    tier_priority_from_rubric,
)
from clue_config import Secrets, Settings
from clue_core import (
    PhaseContext,
    PhaseHandler,
    PhaseResult,
    PhaseStatus,
    ProjectPhase,
    new_project_run_id,
)
from clue_fleet import (
    FleetTaskKind,
    ProjectRunWorker,
    QueueBackedScheduler,
    WorkContext,
    WorkResult,
    default_tier_priority,
    enqueue_drive,
)
from clue_research.durable import PhaseHandlerRegistry, ProjectRun, ProjectRunStatus
from clue_research.icp.rubric import TierBand, TierCutoffs
from clue_storage import FsStorage
from tests.api.test_storage_wiring import FakeStorage
from tests.db.conftest import run_async
from tests.durable.conftest import FakeProjectRunStore
from tests.fleet.conftest import FakeLeaseStore, FakeTaskQueue


def _settings(**kwargs: object) -> Settings:
    return Settings(_env_file=None, **kwargs)  # type: ignore[arg-type]


# --- (a) the queue-backed scheduler is built WITH the lock factory; none → it will not build ---


def test_build_fleet_deep_scheduler_passes_the_lock_factory() -> None:
    settings = _settings()
    lock_factory = build_account_lock_factory(redis=object())  # no redis I/O at construction
    scheduler = build_fleet_deep_scheduler(
        settings, lock_factory=lock_factory, priority_for=default_tier_priority
    )
    assert isinstance(scheduler, QueueBackedScheduler)
    assert scheduler._lock_factory is lock_factory
    assert scheduler._priority_for is default_tier_priority
    # window + stale window come from CLUE_FLEET_* settings (policy as data)
    assert scheduler._window == settings.fleet_deep_window
    assert scheduler._stale_after == timedelta(seconds=settings.fleet_task_stale_after_s)


def test_build_fleet_deep_scheduler_requires_a_priority_policy() -> None:
    """``priority_for`` is a required keyword (Fix, PB-B1 review): the stock name-ladder must not
    ship as the *bound* policy for a real rubric (it collapses free-form band names — spec §5), so
    the builder does not default it. A forgotten policy is a construction-time ``TypeError``."""
    settings = _settings()
    lock_factory = build_account_lock_factory(redis=object())
    with pytest.raises(TypeError):
        build_fleet_deep_scheduler(settings, lock_factory=lock_factory)  # type: ignore[call-arg]


def test_queue_backed_scheduler_requires_a_lock_factory() -> None:
    """The fail-loud single-flight contract: the fleet scheduler makes ``lock_factory`` required, so
    a composition site cannot silently disable Doc C §4 single-flight (a forgotten factory is a
    construction-time ``TypeError``, not a double-spend)."""
    with pytest.raises(TypeError):
        QueueBackedScheduler(window=4)  # type: ignore[call-arg]


# --- (c) rubric-derived tier priority ranks real band labels, fallback after, else the ladder ---


def test_tier_priority_from_rubric_ranks_bands_most_selective_first() -> None:
    cutoffs = TierCutoffs(
        bands=(TierBand(tier="platinum"), TierBand(tier="gold"), TierBand(tier="silver")),
        fallback_tier="untiered",
    )
    priority = tier_priority_from_rubric(cutoffs)
    assert priority("platinum") == 0
    assert priority("gold") == 1
    assert priority("silver") == 2
    # labels are matched case-insensitively / trimmed (consistent with default_tier_priority)
    assert priority("  Platinum ") == 0
    # the fallback tier (cleared no band) sorts AFTER the last band
    assert priority("untiered") == 3
    # an unknown label is the LAST resort: ranked strictly after the fallback tier, never tying a
    # named band or the fallback (default_tier_priority("top")==0 would otherwise leapfrog to best).
    assert priority("mystery") == len(cutoffs.bands) + 1 + default_tier_priority("mystery")
    assert priority("mystery") > priority("untiered")
    assert priority("top") > priority("untiered")  # a ladder-known name still ranks last, not first


def test_default_tier_priority_alone_cannot_rank_rubric_names() -> None:
    """Why :func:`tier_priority_from_rubric` exists (spec §5): the stock policy ranks free-form
    band names at the unknown floor (100), collapsing their order — so it must not be bound."""
    assert default_tier_priority("platinum") == default_tier_priority("gold") == 100


# --- (d) the fleet-main composition builds a worker + driver from settings, no live redis ---


def test_build_fleet_run_driver_is_a_project_run() -> None:
    assert isinstance(build_fleet_run_driver(), ProjectRun)


def test_build_account_lock_factory_needs_no_live_redis_at_construction() -> None:
    assert callable(build_account_lock_factory(redis=object()))


def test_build_fleet_worker_threads_every_fleet_setting() -> None:
    settings = _settings(
        fleet_poll_interval_s=2.0,
        fleet_lease_ttl_s=40.0,
        fleet_heartbeat_interval_s=5.0,
        fleet_task_stale_after_s=80.0,
    )
    worker = build_fleet_worker(settings, driver=build_fleet_run_driver(), worker_id="w-1")
    assert isinstance(worker, ProjectRunWorker)
    assert worker.worker_id == "w-1"
    assert worker._poll_interval == 2.0
    assert worker._lease_ttl == timedelta(seconds=40.0)
    assert worker._heartbeat_interval == 5.0
    assert worker._task_stale_after == timedelta(seconds=80.0)


class _CompositionHandler:
    def __init__(self, kind: FleetTaskKind) -> None:
        self.kind = kind

    async def handle(self, context: WorkContext) -> WorkResult:
        return WorkResult(outcome="unused", references={"work_id": str(context.work_id)})


def test_multi_worker_accepts_one_optional_subject_neutral_entity_handler() -> None:
    graph = _CompositionHandler(FleetTaskKind.EXECUTE_GRAPH)
    entity = _CompositionHandler(FleetTaskKind.ENTITY_RESEARCH_JOB)
    worker = build_multi_work_worker(
        _settings(),
        driver=build_fleet_run_driver(),
        graph_handler=graph,
        entity_research_handler=entity,
        worker_id="shared-worker",
    )
    assert set(worker._handlers) == {
        FleetTaskKind.DRIVE_RUN,
        FleetTaskKind.EXECUTE_GRAPH,
        FleetTaskKind.ENTITY_RESEARCH_JOB,
    }

    with pytest.raises(ValueError, match="must own entity_research_job"):
        build_multi_work_worker(
            _settings(),
            driver=build_fleet_run_driver(),
            graph_handler=graph,
            entity_research_handler=graph,
        )


def test_multi_worker_accepts_one_optional_agent_turn_handler() -> None:
    """FI Lane D D2: the conversation drain is optional and kind-guarded like its neighbours.

    Optional because a deployment with chat disabled composes no conversation engine and nothing
    enqueues ``agent_turn`` tasks; kind-guarded because a handler wired to the wrong queue must be
    a composition-time error, not a silently mis-drained kind.
    """

    graph = _CompositionHandler(FleetTaskKind.EXECUTE_GRAPH)
    turns = _CompositionHandler(FleetTaskKind.AGENT_TURN)
    worker = build_multi_work_worker(
        _settings(),
        driver=build_fleet_run_driver(),
        graph_handler=graph,
        agent_turn_handler=turns,
        worker_id="shared-worker",
    )
    assert set(worker._handlers) == {
        FleetTaskKind.DRIVE_RUN,
        FleetTaskKind.EXECUTE_GRAPH,
        FleetTaskKind.AGENT_TURN,
    }

    with pytest.raises(ValueError, match="must own agent_turn"):
        build_multi_work_worker(
            _settings(),
            driver=build_fleet_run_driver(),
            graph_handler=graph,
            agent_turn_handler=graph,
        )


def test_multi_worker_accepts_kind_guarded_optional_handlers() -> None:
    # Part II D5 Round B: design turns drain on the SAME leased worker as everything else — no
    # private drain — and every optional handler's kind is checked at construction so a wiring
    # mistake fails here rather than at claim time.
    graph = _CompositionHandler(FleetTaskKind.EXECUTE_GRAPH)
    recon = _CompositionHandler(FleetTaskKind.STAGE0_RECON)
    crawl = _CompositionHandler(FleetTaskKind.OFFICIAL_SITE_CRAWL)
    design = _CompositionHandler(FleetTaskKind.DESIGN_JOB)
    worker = build_multi_work_worker(
        _settings(),
        driver=build_fleet_run_driver(),
        graph_handler=graph,
        stage0_recon_handler=recon,
        official_site_crawl_handler=crawl,
        design_handler=design,
        worker_id="shared-worker",
    )
    assert FleetTaskKind.STAGE0_RECON in worker._handlers
    assert FleetTaskKind.OFFICIAL_SITE_CRAWL in worker._handlers
    assert FleetTaskKind.DESIGN_JOB in worker._handlers

    with pytest.raises(ValueError, match="must own stage0_recon"):
        build_multi_work_worker(
            _settings(),
            driver=build_fleet_run_driver(),
            graph_handler=graph,
            stage0_recon_handler=graph,
        )
    with pytest.raises(ValueError, match="must own official_site_crawl"):
        build_multi_work_worker(
            _settings(),
            driver=build_fleet_run_driver(),
            graph_handler=graph,
            official_site_crawl_handler=graph,
        )
    with pytest.raises(ValueError, match="must own design_job"):
        build_multi_work_worker(
            _settings(),
            driver=build_fleet_run_driver(),
            graph_handler=graph,
            design_handler=graph,
        )


def test_onboarding_handler_is_composed_when_given_and_kind_guarded() -> None:
    # Track O (O3): the onboarding-run drain joins on the same terms as its neighbours — optional
    # (a deployment without ``onboarding_v2_enabled`` composes no driver and nothing enqueues the
    # kind) and kind-guarded at construction rather than at claim time.
    graph = _CompositionHandler(FleetTaskKind.EXECUTE_GRAPH)
    handler = _CompositionHandler(FleetTaskKind.ONBOARDING_RUN)
    worker = build_multi_work_worker(
        _settings(),
        driver=build_fleet_run_driver(),
        graph_handler=graph,
        onboarding_handler=handler,
        worker_id="shared-worker",
    )
    assert worker._handlers[FleetTaskKind.ONBOARDING_RUN] is handler

    with pytest.raises(ValueError, match="must own onboarding_run"):
        build_multi_work_worker(
            _settings(),
            driver=build_fleet_run_driver(),
            graph_handler=graph,
            onboarding_handler=_CompositionHandler(FleetTaskKind.DESIGN_JOB),
        )


def test_arv2_account_research_handler_is_composed_when_given_and_kind_guarded() -> None:
    # Track R (R2): the account-research drain joins on the same terms as its neighbours —
    # optional (a deployment without ``arv2_account_research_enabled`` composes no account driver
    # and nothing enqueues the kind) and kind-guarded at construction rather than at claim time.
    graph = _CompositionHandler(FleetTaskKind.EXECUTE_GRAPH)
    handler = _CompositionHandler(FleetTaskKind.ARV2_ACCOUNT_RESEARCH)
    worker = build_multi_work_worker(
        _settings(),
        driver=build_fleet_run_driver(),
        graph_handler=graph,
        arv2_account_research_handler=handler,
        worker_id="shared-worker",
    )
    assert worker._handlers[FleetTaskKind.ARV2_ACCOUNT_RESEARCH] is handler

    with pytest.raises(ValueError, match="arv2_account_research_handler must own"):
        build_multi_work_worker(
            _settings(),
            driver=build_fleet_run_driver(),
            graph_handler=graph,
            arv2_account_research_handler=_CompositionHandler(FleetTaskKind.ONBOARDING_RUN),
        )


def test_the_onboarding_handler_is_off_unless_the_lane_flag_is_set(tmp_path: Path) -> None:
    """The production gate for Track O: no flag, no handler — and nothing enqueues the kind."""
    secrets = Secrets(_env_file=None, exa_api_key=SecretStr("exa-test"))  # type: ignore[call-arg]
    storage = FsStorage(tmp_path)

    assert _build_onboarding_handler(_settings(), secrets, storage=storage) is None

    composed = _build_onboarding_handler(
        _settings(onboarding_v2_enabled=True), secrets, storage=storage
    )
    assert composed is not None
    assert composed.kind is FleetTaskKind.ONBOARDING_RUN


def test_the_flag_without_an_exa_key_composes_no_handler_rather_than_refusing_to_boot(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Ruling (O3): a keyless worker with the flag on warns and drains no onboarding work.

    Failing the boot would take every other kind of work on the process down with it, and a
    keyless handler would fail each run at its first provider call; leaving the kind undrained
    keeps the enqueued runs waiting for a correctly-credentialed worker instead.
    """
    monkeypatch.delenv("CLUE_EXA_API_KEY", raising=False)
    keyless = Secrets(_env_file=None)  # type: ignore[call-arg]
    assert keyless.exa_api_key is None
    assert (
        _build_onboarding_handler(
            _settings(onboarding_v2_enabled=True), keyless, storage=FsStorage(tmp_path)
        )
        is None
    )


def test_the_synthesis_seam_hands_o4_outcomes_to_the_o3_handler(tmp_path: Path) -> None:
    """The O3 ⇄ O4 join, both calls: O4's ``IcpSynthesisResult``/``OnboardingSynthesisResult``
    become the driver's ``IcpSynthesisOutcome``/``SynthesisOutcome`` field for field (and the
    driver's ``IcpRef`` becomes O4's ``RegisteredIcp`` on the way back in), and the composed
    handler carries the seam rather than ``None``."""
    from decimal import Decimal

    from clue_api.arv2.onboarding_driver import IcpRef, IcpSynthesisOutcome, SynthesisOutcome
    from clue_api.fleet_main import _SynthesisSeam
    from clue_api.onboarding_synthesis_wiring import (
        IcpSynthesisResult,
        OnboardingSynthesisResult,
        RegisteredIcp,
    )

    document_id = uuid4()
    registered = RegisteredIcp(
        document_id=document_id,
        icp_key="clinical-ops",
        version=2,
        path="audience/icp-clinical-ops.md",
    )
    handed: list[RegisteredIcp] = []

    class _Launcher:
        async def launch_icps(self, **kwargs: object) -> IcpSynthesisResult:
            return IcpSynthesisResult("completed", None, None, Decimal("0.03"), (registered,))

        async def launch_persona(
            self, *, icp: RegisteredIcp, **kwargs: object
        ) -> OnboardingSynthesisResult:
            handed.append(icp)
            return OnboardingSynthesisResult(
                "failed", "turn_failed", "boom", Decimal("0.05"), (uuid4(),)
            )

    seam = _SynthesisSeam(_Launcher())  # type: ignore[arg-type]
    icp_outcome = run_async(
        seam.launch_icps(workspace_id="ws", brand_id="brd", run_id=uuid4(), step_id=uuid4())
    )
    assert icp_outcome == IcpSynthesisOutcome(
        status="completed",
        failure_code=None,
        failure_message=None,
        cost_usd=Decimal("0.03"),
        icps=(
            IcpRef(
                document_id=document_id,
                icp_key="clinical-ops",
                version=2,
                path="audience/icp-clinical-ops.md",
            ),
        ),
    )

    persona_outcome = run_async(
        seam.launch_persona(
            workspace_id="ws",
            brand_id="brd",
            run_id=uuid4(),
            step_id=uuid4(),
            icp=icp_outcome.icps[0],
        )
    )
    assert persona_outcome == SynthesisOutcome(
        status="failed",
        failure_code="turn_failed",
        failure_message="boom",
        cost_usd=Decimal("0.05"),
    )
    assert handed == [registered], "the driver's IcpRef reaches O4 as its own RegisteredIcp"

    secrets = Secrets(_env_file=None, exa_api_key=SecretStr("exa-test"))  # type: ignore[call-arg]
    composed = _build_onboarding_handler(
        _settings(onboarding_v2_enabled=True), secrets, storage=FsStorage(tmp_path), synthesis=seam
    )
    assert composed is not None and composed._synthesis is seam


def test_the_design_handler_is_off_unless_the_runtime_switch_is_set() -> None:
    """The production gate: no switch, no handler — and therefore no import of the design app."""
    from clue_api.design_fleet import build_design_job_handler

    assert build_design_job_handler(enabled=False) is None
    enabled = build_design_job_handler(enabled=True)
    assert enabled is not None
    assert enabled.kind is FleetTaskKind.DESIGN_JOB


# --- the resume-surface helper (spec §2.4): re-driving is a fresh enqueue_drive -------------------


class _RecordingQueue:
    """Captures the one ``enqueue`` the drive helper issues (a minimal ``TaskQueue`` stand-in)."""

    def __init__(self) -> None:
        self.calls: list[dict[str, object]] = []

    async def enqueue(self, **kwargs: object) -> bool:
        self.calls.append(kwargs)
        return True


def test_enqueue_run_drive_offers_a_reopenable_drive_run() -> None:
    queue = _RecordingQueue()
    run_id = new_project_run_id()
    ok = run_async(enqueue_run_drive(run_id, queue=queue))  # type: ignore[arg-type]
    assert ok
    (call,) = queue.calls
    assert call["kind"] is FleetTaskKind.DRIVE_RUN
    assert call["dedup_key"] == str(run_id)
    assert call["reopen_terminal"] is True


def test_enqueue_run_drive_routes_recipe_owned_run_to_graph_work() -> None:
    owner = uuid4()
    legacy_queue = _RecordingQueue()
    graph_queue = _RecordingQueue()

    class _OwnerResult:
        def scalar_one_or_none(self) -> object:
            return owner

    class _OwnerConnection:
        async def execute(self, _statement: object, _params: object) -> _OwnerResult:
            return _OwnerResult()

    @asynccontextmanager
    async def owner_connection() -> AsyncIterator[_OwnerConnection]:
        yield _OwnerConnection()

    run_id = new_project_run_id()
    ok = run_async(
        enqueue_run_drive(
            run_id,
            queue=legacy_queue,  # type: ignore[arg-type]
            work_queue=graph_queue,  # type: ignore[arg-type]
            conn_factory=owner_connection,  # type: ignore[arg-type]
        )
    )
    assert ok
    assert legacy_queue.calls == []
    (call,) = graph_queue.calls
    assert call["kind"] is FleetTaskKind.EXECUTE_GRAPH
    assert call["work_id"] == owner
    assert call["dedup_key"] == str(owner)
    assert call["reopen_terminal"] is True


# --- the worker-boot phase-handler composition (Fix 1) -------------------------------------------


class _StubPhaseHandler:
    """A trivial COMPLETED :class:`~clue_core.PhaseHandler` for one phase — stands in for the
    per-``(client, icp)`` handler the enqueuing app registers at run start (e.g. DEEP), so the boot
    registry can be driven offline without the DB-bound REVIEW resolver."""

    def __init__(self, phase: ProjectPhase) -> None:
        self.phase = phase

    async def run(self, ctx: PhaseContext) -> PhaseResult:
        return PhaseResult(status=PhaseStatus.COMPLETED, payload={})


_STUB_IS_A_PHASE_HANDLER: type[PhaseHandler] = _StubPhaseHandler


def test_register_boot_handlers_registers_review_and_skips_per_project_phases() -> None:
    """The boot composition registers the one process-wide-composable handler (REVIEW) and skips
    the per-``(client, icp)`` / not-yet-integrable phases (DEEP/VERIFICATION/HANDOFF) — so the
    registry is non-empty (the worker starts) without inventing stubs for campaign handlers."""
    registry = PhaseHandlerRegistry()
    phases = register_boot_handlers(_settings(), storage=FakeStorage(), registry=registry)
    assert ProjectPhase.REVIEW in phases
    assert registry.get(ProjectPhase.REVIEW) is not None
    for skipped in (ProjectPhase.DEEP, ProjectPhase.VERIFICATION, ProjectPhase.HANDOFF):
        assert skipped not in phases
    # storage=None is the written opt-out; the surface stays composable without a backend.
    none_phases = register_boot_handlers(_settings(), storage=None, registry=PhaseHandlerRegistry())
    assert ProjectPhase.REVIEW in none_phases


def test_boot_registry_drives_a_run_through_the_fleet_worker() -> None:
    """End-to-end (fakes for queue/lease, in-memory run store): the registry that
    ``register_boot_handlers`` populated drives a run through the real :class:`ProjectRunWorker` →
    :class:`ProjectRun` loop. A boot-/run-registered phase advances; the next phase — with no
    handler — makes the drive stop with ``outcome=error`` (the documented fail-loud behavior)."""

    async def scenario() -> None:
        registry = PhaseHandlerRegistry()
        phases = register_boot_handlers(_settings(), storage=FakeStorage(), registry=registry)
        assert ProjectPhase.REVIEW in phases  # the boot contribution to the registry
        # A run-start handler (mirrors DEEP being registered per run) so the drive is DB-free.
        registry.register(_StubPhaseHandler(ProjectPhase.REVERSE_PROFILING))

        machine = ProjectRun(store=FakeProjectRunStore(), registry=registry)
        run_id = await machine.start(
            project_id="prj-test", workspace_id="ws", icp_key="icp", icp_version=1
        )

        queue = FakeTaskQueue()
        leases = FakeLeaseStore()
        await enqueue_drive(queue, run_id)  # type: ignore[arg-type]
        worker = ProjectRunWorker(
            driver=machine,
            queue=queue,  # type: ignore[arg-type]
            leases=leases,  # type: ignore[arg-type]
            worker_id="w-boot",
            poll_interval=0.01,
            lease_ttl=timedelta(seconds=30),
            heartbeat_interval=5.0,
            task_stale_after=timedelta(seconds=60),
        )
        await worker.drain_once()

        run = await machine.status(run_id)
        # the registered REVERSE_PROFILING advanced; ICP_CONFIRMED (no handler) is where it stopped.
        assert run.phase is ProjectPhase.ICP_CONFIRMED
        assert run.status is ProjectRunStatus.ACTIVE
        task = queue.row(FleetTaskKind.DRIVE_RUN, run_id, str(run_id))
        assert task.result_ref.get("outcome") == "error"  # unregistered next phase → fail-loud

    run_async(scenario())


def test_empty_boot_registry_refuses_to_start() -> None:
    """The worker refuses to start (clean error) if no handlers composed — better than FAILing every
    task it claims. A non-empty set passes the gate."""
    with pytest.raises(NoBootHandlersRegistered):
        _require_registered(frozenset())
    _require_registered(frozenset({ProjectPhase.REVIEW}))  # non-empty → no raise


# --- the background orphan-blob sweep task (Fix 5) -----------------------------------------------


def test_orphan_sweep_task_started_when_enabled() -> None:
    async def scenario() -> None:
        settings = _settings(storage_orphan_sweep_interval_s=3600.0)
        task = _start_orphan_sweep(settings, FakeStorage())
        assert task is not None
        task.cancel()  # cancel before it ever sleeps a real interval
        with contextlib.suppress(asyncio.CancelledError):
            await task

    run_async(scenario())


def test_orphan_sweep_disabled_when_interval_zero() -> None:
    settings = _settings(storage_orphan_sweep_interval_s=0.0)
    assert _start_orphan_sweep(settings, FakeStorage()) is None


# --- the background design reaper (Part II D5 Round C) -------------------------------------------


def test_design_reaper_is_off_unless_the_runtime_switch_is_set() -> None:
    """Gated on the SAME switch as the handler: a deployment that does not DRAIN design work has
    no business RE-OFFERING it, and the reaper import must not be paid for when it is off."""
    from clue_api.design_fleet import start_design_reaper

    assert start_design_reaper(enabled=False, interval_s=300.0) is None


def test_design_reaper_started_when_enabled_and_disabled_at_zero_interval() -> None:
    """Same disabled-by-non-positive-interval convention the orphan sweep uses."""
    from clue_api.design_fleet import start_design_reaper

    async def scenario() -> None:
        assert start_design_reaper(enabled=True, interval_s=0.0) is None
        task = start_design_reaper(enabled=True, interval_s=3600.0)
        assert task is not None
        task.cancel()  # cancel before it ever sleeps a real interval
        with contextlib.suppress(asyncio.CancelledError):
            await task

    run_async(scenario())
