"""PB-B1 api-composition-root fleet wiring (``clue_api.fleet_wiring`` / ``clue_api.fleet_main``).

Composition-only assertions — construction, settings threading, the fail-loud single-flight
contract, and rubric-derived tier priority. No live Redis or Postgres (construction of the ``Db*``
stores and the lock factory makes no I/O), so these run in the offline ``make check`` suite.
"""

from __future__ import annotations

import asyncio
import contextlib
import re
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import timedelta
from pathlib import Path
from uuid import uuid4

import pytest
from pydantic import SecretStr

from clue_api.fleet_main import (
    NoBootHandlersRegistered,
    _build_arv2_discovery_handler,
    _build_onboarding_handler,
    _require_registered,
    _start_orphan_sweep,
)
from clue_api.fleet_wiring import (
    _SerializedHandler,
    build_account_lock_factory,
    build_fleet_deep_scheduler,
    build_fleet_run_driver,
    build_fleet_worker,
    build_multi_work_worker,
    enqueue_run_drive,
    register_boot_handlers,
    selected_worker_kinds,
    tier_priority_from_rubric,
)
from clue_config import Secrets, Settings
from clue_config.gateway import GatewayConfig
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
    LeaseGeneration,
    ProjectRunWorker,
    QueueBackedScheduler,
    WorkContext,
    WorkId,
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


def test_multi_work_worker_threads_the_per_worker_concurrency_setting() -> None:
    """Founder ruling 2026-09-10: one process drives ``CLUE_FLEET_WORKER_CONCURRENCY`` tasks."""
    graph = _CompositionHandler(FleetTaskKind.EXECUTE_GRAPH)
    wide = build_multi_work_worker(
        _settings(fleet_worker_concurrency=6),
        driver=build_fleet_run_driver(),
        graph_handler=graph,
        worker_id="wide",
    )
    assert wide.concurrency == 6

    default = build_multi_work_worker(
        _settings(),
        driver=build_fleet_run_driver(),
        graph_handler=graph,
        worker_id="narrow",
    )
    assert default.concurrency == 1
    assert Settings.model_fields["fleet_worker_concurrency"].default == 1


def test_the_project_run_drive_is_the_one_serialised_kind() -> None:
    """Handler-safety audit (task 9d): ``drive_run`` is the one handler that is NOT safe under
    concurrent ``handle()`` calls on one instance, so it gets a per-handler lock.

    Two independent reasons, both established by reading the code:
    ``ComposingRunDriver.composed`` keeps an LRU registry cache with no lock and an ``await``
    between the miss and the fill (``run_composition.py``), and ``ProjectRun`` documents
    single-driver-per-run as a precondition it does not enforce — which the fleet cannot fence
    in-process either, because every slot claims under the SAME ``worker_id`` and
    ``work_lease``'s acquire re-issues a live lease at the same generation to its own worker.
    Serialising the kind restores exactly the invariant both were written under.
    """
    worker = build_multi_work_worker(
        _settings(fleet_worker_concurrency=4),
        driver=build_fleet_run_driver(),
        graph_handler=_CompositionHandler(FleetTaskKind.EXECUTE_GRAPH),
        agent_turn_handler=_CompositionHandler(FleetTaskKind.AGENT_TURN),
        onboarding_handler=_CompositionHandler(FleetTaskKind.ONBOARDING_RUN),
    )
    drive = worker._handlers[FleetTaskKind.DRIVE_RUN]
    assert isinstance(drive, _SerializedHandler)
    assert drive.kind is FleetTaskKind.DRIVE_RUN
    # Serialising is per kind, never per worker: every audited-safe kind still runs in parallel.
    for kind in (
        FleetTaskKind.EXECUTE_GRAPH,
        FleetTaskKind.AGENT_TURN,
        FleetTaskKind.ONBOARDING_RUN,
    ):
        assert not isinstance(worker._handlers[kind], _SerializedHandler)


def test_a_serialised_handler_runs_one_handle_at_a_time_and_forwards_its_kind() -> None:
    class _Overlapping:
        kind = FleetTaskKind.DRIVE_RUN

        def __init__(self) -> None:
            self.in_flight = 0
            self.peak = 0
            self.release = asyncio.Event()
            self.entered = asyncio.Event()

        async def handle(self, context: WorkContext) -> WorkResult:
            self.in_flight += 1
            self.peak = max(self.peak, self.in_flight)
            self.entered.set()
            try:
                await self.release.wait()
            finally:
                self.in_flight -= 1
            return WorkResult(outcome="done", references={})

    async def scenario() -> None:
        inner = _Overlapping()
        serialised = _SerializedHandler(inner)
        assert serialised.kind is FleetTaskKind.DRIVE_RUN
        # An inner handler that declares no R3-B capabilities still claims its whole kind.
        assert serialised.task_capabilities == ()

        context = WorkContext(
            task_id=uuid4(),
            work_id=WorkId(uuid4()),
            worker_id="w",
            lease_generation=LeaseGeneration(1),
            payload={},
            stop_requested=asyncio.Event(),
            lease_lost=asyncio.Event(),
        )
        first = asyncio.create_task(serialised.handle(context))
        second = asyncio.create_task(serialised.handle(context))
        await asyncio.wait_for(inner.entered.wait(), timeout=2.0)
        for _ in range(100):
            await asyncio.sleep(0)
        assert inner.peak == 1  # RED without the lock: the second call enters and peak is 2

        inner.release.set()
        await asyncio.wait_for(asyncio.gather(first, second), timeout=2.0)
        assert inner.peak == 1

    asyncio.run(scenario())


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


def test_arv2_discovery_handler_is_composed_when_given_and_kind_guarded() -> None:
    # Track R (R4): the discovery drain joins on the same terms as its neighbours — optional (a
    # deployment without ``arv2_discovery_enabled`` or without ``CLUE_EXA_API_KEY`` composes no
    # discovery driver and nothing enqueues the kind) and kind-guarded at construction, so a
    # handler wired to the wrong keyword fails here rather than after a run has claimed its row.
    graph = _CompositionHandler(FleetTaskKind.EXECUTE_GRAPH)
    handler = _CompositionHandler(FleetTaskKind.ARV2_DISCOVERY)
    worker = build_multi_work_worker(
        _settings(),
        driver=build_fleet_run_driver(),
        graph_handler=graph,
        arv2_discovery_handler=handler,
        worker_id="shared-worker",
    )
    assert worker._handlers[FleetTaskKind.ARV2_DISCOVERY] is handler

    with pytest.raises(ValueError, match="arv2_discovery_handler must own"):
        build_multi_work_worker(
            _settings(),
            driver=build_fleet_run_driver(),
            graph_handler=graph,
            arv2_discovery_handler=_CompositionHandler(FleetTaskKind.ARV2_ACCOUNT_RESEARCH),
        )


def test_arv2_display_page_handler_is_composed_when_given_and_kind_guarded() -> None:
    # Spec 2026-09-12: the display-page drain joins on the same terms as its neighbours — optional
    # (a deployment with the display flag off, or no model key, composes none) and kind-guarded at
    # construction, so a handler wired to the wrong keyword fails here rather than at claim time.
    graph = _CompositionHandler(FleetTaskKind.EXECUTE_GRAPH)
    handler = _CompositionHandler(FleetTaskKind.ARV2_DISPLAY_PAGE)
    worker = build_multi_work_worker(
        _settings(),
        driver=build_fleet_run_driver(),
        graph_handler=graph,
        arv2_display_page_handler=handler,
        worker_id="shared-worker",
    )
    assert worker._handlers[FleetTaskKind.ARV2_DISPLAY_PAGE] is handler

    with pytest.raises(ValueError, match="arv2_display_page_handler must own"):
        build_multi_work_worker(
            _settings(),
            driver=build_fleet_run_driver(),
            graph_handler=graph,
            arv2_display_page_handler=_CompositionHandler(FleetTaskKind.ARV2_DISCOVERY),
        )


def test_the_discovery_handler_is_off_unless_the_lane_flag_and_the_key_are_both_set(
    tmp_path: Path,
) -> None:
    """The production gate for R4: no flag, no handler; a flag with no key, a warning and none."""
    storage = FsStorage(tmp_path)
    keyed = Secrets(_env_file=None, exa_api_key=SecretStr("exa-test"))  # type: ignore[call-arg]
    keyless = Secrets(_env_file=None)  # type: ignore[call-arg]

    off = _settings(arv2_discovery_enabled=False)  # on by default since 2026-10-04
    assert _build_arv2_discovery_handler(off, keyed, storage=storage) is None

    on = _settings(arv2_discovery_enabled=True)
    assert _build_arv2_discovery_handler(on, keyless, storage=storage) is None

    composed = _build_arv2_discovery_handler(on, keyed, storage=storage)
    assert composed is not None
    assert composed.kind is FleetTaskKind.ARV2_DISCOVERY


def test_the_onboarding_handler_is_off_unless_the_lane_flag_is_set(tmp_path: Path) -> None:
    """The production gate for Track O: no flag, no handler — and nothing enqueues the kind."""
    secrets = Secrets(_env_file=None, exa_api_key=SecretStr("exa-test"))  # type: ignore[call-arg]
    storage = FsStorage(tmp_path)

    off = _settings(onboarding_v2_enabled=False)  # on by default since 2026-09-12
    assert _build_onboarding_handler(off, secrets, storage=storage) is None

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


def test_the_catalog_reconciler_is_composed_per_run_only_with_a_model_credential(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """O3's identity ladder: the model stage is composed as a **factory of one reconciler per
    run**, built over the catalog step's own sinks so its one call lands on the ledger with the
    run's stamp (slice 1b).

    Same posture as the Exa key one level up, one step softer: a missing OpenRouter key (or the
    flag off) still composes the handler — the sync then runs its deterministic rungs alone, which
    is what it did before the stage existed — but it says so once, at composition.
    """
    from clue_api.arv2.onboarding_reconcile import OpenRouterCatalogReconciler

    monkeypatch.delenv("CLUE_OPENROUTER_API_KEY", raising=False)
    secrets = Secrets(_env_file=None, exa_api_key=SecretStr("exa-test"))  # type: ignore[call-arg]
    assert secrets.openrouter_api_key is None
    settings = _settings(
        onboarding_v2_enabled=True,
        onboarding_catalog_reconcile_enabled=True,
        arv2_raw_root=str(tmp_path / "raw"),
    )

    keyless = _build_onboarding_handler(settings, secrets, storage=FsStorage(tmp_path))
    assert keyless is not None, "no model key never costs the lane its handler"
    assert keyless._reconciler_factory is None

    keyed = Secrets(  # type: ignore[call-arg]
        _env_file=None,
        exa_api_key=SecretStr("exa-test"),
        openrouter_api_key=SecretStr("or-test"),
    )
    composed = _build_onboarding_handler(settings, keyed, storage=FsStorage(tmp_path))
    assert composed is not None and composed._reconciler_factory is not None
    from clue_api.arv2.sinks import MemoryLedger, MemoryRawSink

    reconciler = composed._reconciler_factory(MemoryRawSink(), MemoryLedger())
    assert isinstance(reconciler, OpenRouterCatalogReconciler)
    assert reconciler._model == settings.onboarding_reconcile_model
    assert reconciler._base_url == GatewayConfig().base_url

    off = _build_onboarding_handler(
        _settings(
            onboarding_v2_enabled=True,
            onboarding_catalog_reconcile_enabled=False,
            arv2_raw_root=str(tmp_path / "raw"),
        ),
        keyed,
        storage=FsStorage(tmp_path),
    )
    assert off is not None and off._reconciler_factory is None


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


def test_the_design_handler_puts_the_platform_reads_factory_on_the_host_it_builds() -> None:
    """Design note 2026-09-19: the platform's reads reach the design turn the same way the
    scoped-preference resolver does — a factory on the host, never a value in the frozen job.

    Both factories are independent switches, so the host must be built when EITHER is present:
    a deployment with design memory off still composes the reads, and one with no reads still
    composes the resolver.
    """
    from clue_api.design_fleet import build_design_job_handler

    reads = object()
    prefs = object()

    only_reads = build_design_job_handler(enabled=True, platform_reads_factory=reads)
    assert only_reads is not None
    host = only_reads._host_provider()
    assert host.platform_reads_factory is reads
    assert host.preference_resolver_factory is None

    both = build_design_job_handler(
        enabled=True, platform_reads_factory=reads, preference_resolver_factory=prefs
    )
    assert both is not None
    host = both._host_provider()
    assert (host.platform_reads_factory, host.preference_resolver_factory) == (reads, prefs)


def test_the_design_leg_lane_forwards_the_platform_reads_factory() -> None:
    """The inline leg lane and the queued drain handler must see the SAME reads — a leg turn
    driven inline and one taken over by a design_job worker are the same unit of work."""
    from clue_api.design_fleet import build_design_leg_lane_driver

    reads = object()
    lane = build_design_leg_lane_driver(enabled=True, platform_reads_factory=reads)
    assert lane is not None
    assert lane._handler._host_provider().platform_reads_factory is reads


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


# --- CLUE_FLEET_WORKER_KINDS: one VM, separate pools (first deployment, 2026-10-01) ---


def test_blank_worker_kinds_means_every_kind() -> None:
    assert selected_worker_kinds("") is None
    assert selected_worker_kinds("  ") is None
    assert Settings.model_fields["fleet_worker_kinds"].default == ""


def test_worker_kinds_parse_comma_separated_names() -> None:
    assert selected_worker_kinds("agent_turn, design_job") == frozenset(
        {FleetTaskKind.AGENT_TURN, FleetTaskKind.DESIGN_JOB}
    )


def test_an_unknown_worker_kind_fails_at_startup() -> None:
    with pytest.raises(ValueError, match="agent_turns"):
        selected_worker_kinds("agent_turns")


def test_a_worker_limited_to_one_kind_registers_only_that_kind() -> None:
    worker = build_multi_work_worker(
        _settings(fleet_worker_kinds="agent_turn", fleet_worker_concurrency=10),
        driver=build_fleet_run_driver(),
        graph_handler=_CompositionHandler(FleetTaskKind.EXECUTE_GRAPH),
        agent_turn_handler=_CompositionHandler(FleetTaskKind.AGENT_TURN),
        onboarding_handler=_CompositionHandler(FleetTaskKind.ONBOARDING_RUN),
    )
    assert set(worker._handlers) == {FleetTaskKind.AGENT_TURN}
    assert worker.concurrency == 10


def test_a_selection_that_leaves_no_handler_fails_at_startup() -> None:
    # design_job is selected but this deployment composed no design handler.
    with pytest.raises(ValueError, match="no handler"):
        build_multi_work_worker(
            _settings(fleet_worker_kinds="design_job"),
            driver=build_fleet_run_driver(),
            graph_handler=_CompositionHandler(FleetTaskKind.EXECUTE_GRAPH),
        )


def test_every_kind_is_registered_when_the_selection_is_blank() -> None:
    worker = build_multi_work_worker(
        _settings(),
        driver=build_fleet_run_driver(),
        graph_handler=_CompositionHandler(FleetTaskKind.EXECUTE_GRAPH),
        agent_turn_handler=_CompositionHandler(FleetTaskKind.AGENT_TURN),
    )
    assert {FleetTaskKind.DRIVE_RUN, FleetTaskKind.EXECUTE_GRAPH, FleetTaskKind.AGENT_TURN} <= set(
        worker._handlers
    )


def test_worker_kinds_env_name_is_documented_blank() -> None:
    text = (Path(__file__).resolve().parents[2] / ".env.example").read_text(encoding="utf-8")
    assert re.search(r"^CLUE_FLEET_WORKER_KINDS=$", text, re.MULTILINE)
