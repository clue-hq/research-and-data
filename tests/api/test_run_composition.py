"""PB-B4 slice 1 — the ``ComposingRunDriver`` composition (D1/D2) and resume convergence (D4).

Offline: composition is pure construction (no DB/redis I/O) when the ``spec_loader`` is injected, so
the D1 registry-isolation race, the composed phase set, the LRU cache, the missing-spec fail-loud,
and the D4 resume-parity construction all run in ``make check``. The end-to-end drive through the
real worker + real DB is ``tests/fleet/test_b4_composed_run_db.py`` (exit gate a).
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from decimal import Decimal
from uuid import uuid4

import pytest
from sqlalchemy import text

from clue_api.handoff_retention import RetentionSweepHandoffHandler
from clue_api.handoff_wiring import HandoffPhaseHandler
from clue_api.review.composition import ProjectRunResumeHook, _default_resume_run
from clue_api.run_composition import (
    ClientInputProviderMissing,
    ComposedRun,
    ComposingRunDriver,
    CompositionUnavailable,
    _default_gateway,
    _MissingClientInputHandler,
)
from clue_api.storage_wiring import SnapshotBindingPhaseHandler
from clue_config import GatewayConfig, load_settings
from clue_core import (
    ICPCreatedFrom,
    ICPSpec,
    PhaseContext,
    PhaseResult,
    PhaseStatus,
    ProjectPhase,
    ProjectRunId,
    new_entity_id,
    new_project_run_id,
    phase_key,
)
from clue_db import db_lifespan, transaction
from clue_fleet import QueueBackedScheduler
from clue_gateway import build_gateway
from clue_research.durable import (
    BudgetEngine,
    DbIdempotencyStore,
    DbProjectRunStore,
    ProjectRun,
    default_phase_handler_registry,
    register_phase_handler,
)
from clue_research.durable.enums import ProjectRunStatus
from clue_research.durable.project_run import ProjectRunRow
from tests._workspace import seed_project
from tests.api.test_storage_wiring import FakeStorage
from tests.db.conftest import run_async
from tests.fleet.conftest import ProcessLocalLockFactory

_ALL_PHASES = frozenset(ProjectPhase)


def _stub_gateway() -> object:
    return build_gateway(GatewayConfig(stub=True))


def _spec(
    icp_key: str,
    *,
    workspace_id: str = "ws",
    version: int = 1,
    product_id: str | None = None,
) -> ICPSpec:
    lineage = (
        {
            "client_entity_id": new_entity_id(),
            "client_kb_version": 1,
            "product_id": product_id,
        }
        if product_id is not None
        else {}
    )
    return ICPSpec(
        workspace_id=workspace_id,
        icp_key=icp_key,
        created_from=ICPCreatedFrom.SYNTHESIS,
        version=version,
        field_keys=(f"core.field_{icp_key}",),
        **lineage,  # type: ignore[arg-type]
    )


def _row(
    icp_key: str,
    *,
    workspace_id: str = "ws",
    version: int = 1,
    product_id: str | None = None,
) -> ProjectRunRow:
    now = datetime.now(UTC)
    return ProjectRunRow(
        id=new_project_run_id(),
        project_id="prj-test",
        brand_id="brd-test",
        workspace_id=workspace_id,
        icp_key=icp_key,
        icp_version=version,
        phase=ProjectPhase.REVERSE_PROFILING,
        status=ProjectRunStatus.ACTIVE,
        budget_cap_cents=None,
        spent_cents=Decimal(0),
        tier_cutoffs={},
        paused_at=None,
        resumed_at=None,
        created_at=now,
        updated_at=now,
        product_id=product_id,
    )


def _driver(specs: dict[tuple[str, str, int], ICPSpec], **kwargs: object) -> ComposingRunDriver:
    async def spec_loader(workspace_id: str, icp_key: str, icp_version: int) -> ICPSpec | None:
        await asyncio.sleep(0)  # a real await so concurrent gather() actually interleaves
        return specs.get((workspace_id, icp_key, icp_version))

    settings = kwargs.pop(
        "settings",
        load_settings(
            gateway_allow_stub=True,
            c7_production_handoff_enabled=True,
            _env_file=None,
        ),
    )
    return ComposingRunDriver(
        settings=settings,  # type: ignore[arg-type]
        gateway=_stub_gateway(),  # type: ignore[arg-type]
        storage=FakeStorage(),  # type: ignore[arg-type]
        lock_factory=ProcessLocalLockFactory(),  # type: ignore[arg-type]
        spec_loader=spec_loader,
        **kwargs,  # type: ignore[arg-type]
    )


def test_composed_registry_holds_every_phase() -> None:
    """A composed per-run registry can drive the whole sequence: all eight phases are bound (the
    M5/M6 surfaces + DEEP + VERIFICATION + REVIEW-from-boot + HANDOFF)."""

    async def scenario() -> None:
        row = _row("a")
        driver = _driver({("ws", "a", 1): _spec("a")})
        composed = await driver.composed(row)
        assert isinstance(composed, ComposedRun)
        assert composed.phases == _ALL_PHASES
        assert composed.spec.icp_key == "a"
        assert isinstance(composed.run, ProjectRun)

    run_async(scenario())


def test_composed_run_threads_committee_preparer_into_deep_orchestrator() -> None:
    async def scenario() -> None:
        preparer = object()
        composed = await _driver(
            {("ws", "a", 1): _spec("a")},
            committee_preparer=preparer,
        ).composed(_row("a"))
        assert composed.deep.orchestrator._committee_preparer is preparer

    run_async(scenario())


def test_composed_discovery_retains_injected_durable_batch_starter() -> None:
    class _Starter:
        async def ensure_started(self, ctx: PhaseContext):
            raise AssertionError(f"construction-only test invoked starter for {ctx.project_run_id}")

    async def scenario() -> None:
        starter = _Starter()
        composed = await _driver(
            {("ws", "a", 1): _spec("a")}, discovery_batch_starter=starter
        ).composed(_row("a"))
        wrapped = composed.registry.get(ProjectPhase.DISCOVERY)
        assert isinstance(wrapped, SnapshotBindingPhaseHandler)
        assert wrapped._inner._starter is starter

    run_async(scenario())


def test_composed_handoff_is_real_retention_wrapped_m12_handler() -> None:
    """C7.6 removed the documented-gap HANDOFF stand-in from production composition."""

    async def scenario() -> None:
        row = _row("a")
        composed = await _driver({("ws", "a", 1): _spec("a")}).composed(row)
        handoff = composed.registry.get(ProjectPhase.HANDOFF)
        assert isinstance(handoff, RetentionSweepHandoffHandler)
        assert isinstance(handoff._inner, HandoffPhaseHandler)

    run_async(scenario())


def test_c7_production_handoff_is_default_off_and_has_no_fallback_handler() -> None:
    """Rollback removes HANDOFF dispatch; it never reinstates the retired fake-success marker."""

    async def scenario() -> None:
        composed = await _driver(
            {("ws", "a", 1): _spec("a")},
            settings=load_settings(_env_file=None),
        ).composed(_row("a"))
        assert ProjectPhase.HANDOFF not in composed.phases
        assert composed.registry.get(ProjectPhase.HANDOFF) is None

    run_async(scenario())


def test_product_pin_mismatch_fails_closed_before_composition() -> None:
    """The run and ICP cannot silently select different product-scoped research."""

    async def scenario() -> None:
        driver = _driver({("ws", "a", 1): _spec("a", product_id="product-a")})
        with pytest.raises(CompositionUnavailable, match="product pin mismatch"):
            await driver.composed(_row("a", product_id="product-b"))

    run_async(scenario())


def test_two_icps_compose_isolated_registries_no_cross_talk() -> None:
    """The D1 race gate: two runs with **different** ICP specs, driven on one driver, compose
    **separate** registries — each with its OWN DEEP handler bound to its own spec. In the old
    process-global registry the two DEEP slots would collide (last-write-wins); per-run registries
    make cross-talk structurally impossible."""

    async def scenario() -> None:
        specs = {("ws", "a", 1): _spec("a"), ("ws", "b", 1): _spec("b")}
        driver = _driver(specs)
        row_a, row_b = _row("a"), _row("b")
        # Compose concurrently (interleaved) — the on-one-worker concurrency shape.
        a, b = await asyncio.gather(driver.composed(row_a), driver.composed(row_b))
        assert a.run is not b.run
        assert a.registry is not b.registry
        # Each run's DEEP handler is its own object — no shared/overwritten slot.
        deep_a = a.registry.get(ProjectPhase.DEEP)
        deep_b = b.registry.get(ProjectPhase.DEEP)
        assert deep_a is not None and deep_b is not None and deep_a is not deep_b
        # Each composed DEEP handler is bound to its run's OWN spec — read off the RETAINED DEEP
        # composition (the spec ``build_deep_phase_handler`` was actually constructed against), not
        # the convenience ``ComposedRun.spec`` field a composer set from its own local.
        assert a.deep.spec.icp_key == "a" and b.deep.spec.icp_key == "b"
        assert a.deep.spec is not b.deep.spec
        assert a.deep.spec.field_keys != b.deep.spec.field_keys
        # D2's untested claim: the composed DEEP scheduler is the fleet queue-backed scheduler
        # (single-flight + rubric-priority ON), not the in-process ``AccountScheduler`` default.
        assert isinstance(a.deep.scheduler, QueueBackedScheduler)
        assert isinstance(b.deep.scheduler, QueueBackedScheduler)

    run_async(scenario())


def test_composition_is_cached_per_key() -> None:
    async def scenario() -> None:
        driver = _driver({("ws", "a", 1): _spec("a")})
        row = _row("a")
        first = await driver.composed(row)
        second = await driver.composed(row)  # same project_run_id
        assert first is second  # LRU hit — not recomposed

    run_async(scenario())


def test_two_runs_with_same_icp_do_not_share_run_bound_committee_reader() -> None:
    """C7.6 makes project-run identity part of composition, even when the ICP is identical."""

    async def scenario() -> None:
        driver = _driver({("ws", "a", 1): _spec("a")})
        first = await driver.composed(_row("a"))
        second = await driver.composed(_row("a"))
        assert first is not second
        assert first.registry is not second.registry

    run_async(scenario())


def test_lru_evicts_beyond_cache_size() -> None:
    async def scenario() -> None:
        specs = {("ws", k, 1): _spec(k) for k in ("a", "b", "c")}
        driver = _driver(specs, cache_size=2)
        row_a = _row("a")
        a1 = await driver.composed(row_a)
        await driver.composed(_row("b"))
        await driver.composed(_row("c"))  # evicts "a" (least-recently-used)
        a2 = await driver.composed(row_a)  # recomposed → a fresh object
        assert a1 is not a2

    run_async(scenario())


def test_missing_spec_fails_loud() -> None:
    """A run whose ICP spec does not exist cannot compose the campaign-scoped DEEP/VERIFICATION —
    ``CompositionUnavailable`` rather than a spec-less drive (fail-loud, not silent)."""

    async def scenario() -> None:
        driver = _driver({})  # no specs registered
        with pytest.raises(CompositionUnavailable):
            await driver.composed(_row("ghost"))

    run_async(scenario())


# --- D4 resume convergence: the resume hook's default driver carries ledger + budget -------------


def test_default_resume_run_carries_ledger_and_budget() -> None:
    """The resume hook's default ``ProjectRun`` is fleet-parity: a ledger + budget engine, unlike
    the old bare ``ProjectRun()`` (the ``[B1×M13.2]`` gap). Construction-only assertion."""
    run = _default_resume_run()
    assert run._ledger is not None  # M7.4 exactly-once ledger (was None on the bare path)
    assert run._budget is not None  # BudgetEngine (was None → burn_down/estimate raised)
    # The old bare path had neither — the divergence this closes.
    bare = ProjectRun()
    assert bare._ledger is None and bare._budget is None


def _rp_ctx() -> PhaseContext:
    return PhaseContext(
        project_run_id=new_project_run_id(),
        project_id="prj-test",
        brand_id="brd-test",
        phase=ProjectPhase.REVERSE_PROFILING,
        workspace_id="ws",
        icp_key="a",
        icp_version=1,
    )


def test_missing_client_input_provider_raises_typed_actionable_error() -> None:
    """With no ``client_input_provider`` wired, REVERSE_PROFILING is composed as the fail-loud
    stand-in: running it raises a typed :class:`ClientInputProviderMissing` naming the ``[M5×M7]``
    gap and the ``client_input_provider`` seam — not the old bare pydantic ValidationError from
    deep inside synthesis."""

    async def scenario() -> None:
        with pytest.raises(ClientInputProviderMissing) as excinfo:
            await _MissingClientInputHandler().run(_rp_ctx())
        message = str(excinfo.value)
        assert "[M5×M7]" in message
        assert "client_input_provider" in message

    run_async(scenario())


def test_composer_wires_the_missing_client_input_handler_when_no_provider() -> None:
    """The composer registers the fail-loud stand-in (not the real handler) when no provider is
    injected — so a state-machine-driven reverse-profiling phase fails actionably."""

    async def scenario() -> None:
        driver = _driver({("ws", "a", 1): _spec("a")})  # no client_input_provider
        composed = await driver.composed(_row("a"))
        handler = composed.registry.get(ProjectPhase.REVERSE_PROFILING)
        assert handler is not None
        # Snapshot-bound wrapper delegates to the stand-in, which raises before any storage I/O.
        with pytest.raises(ClientInputProviderMissing):
            await handler.run(_rp_ctx())

    run_async(scenario())


# --- the no-silent-stub gateway gate (Fix 2) -----------------------------------------------------


class _NoKeySecrets:
    """Stands in for ``Secrets`` with no OpenRouter key configured."""

    openrouter_api_key = None


def test_default_gateway_refuses_stub_without_optin(monkeypatch: pytest.MonkeyPatch) -> None:
    """A missing ``OPENROUTER_API_KEY`` with ``gateway_allow_stub`` False is a loud RuntimeError
    naming the setting + the missing secret — never a silent canned-output StubGateway in prod."""
    from clue_api import run_composition

    monkeypatch.setattr(run_composition, "Secrets", _NoKeySecrets)
    settings = load_settings(gateway_allow_stub=False, _env_file=None)
    with pytest.raises(RuntimeError) as excinfo:
        run_composition._default_gateway(settings)
    message = str(excinfo.value)
    assert "CLUE_GATEWAY_ALLOW_STUB" in message
    assert "OPENROUTER_API_KEY" in message


def test_default_gateway_builds_stub_when_opted_in(monkeypatch: pytest.MonkeyPatch) -> None:
    """With the explicit ``gateway_allow_stub`` opt-in (CI/tests/scripts), a missing key builds the
    stub gateway (and logs the warning) rather than raising."""
    from clue_api import run_composition

    monkeypatch.setattr(run_composition, "Secrets", _NoKeySecrets)
    settings = load_settings(gateway_allow_stub=True, _env_file=None)
    gateway = _default_gateway(settings)
    assert gateway is not None


# --- the resume-path phase-ledger row (Fix 3b, DB-gated) -----------------------------------------


class _CompletingPhaseHandler:
    """A minimal :class:`~clue_core.PhaseHandler` that completes its phase on empty data — enough
    to let the default resume driver drive a run to DONE through the process-default registry."""

    def __init__(self, phase: ProjectPhase) -> None:
        self.phase = phase

    async def run(self, ctx: PhaseContext) -> PhaseResult:
        return PhaseResult(status=PhaseStatus.COMPLETED, accounts_processed=0)


class _PausingPhaseHandler:
    """Pauses its phase (a durable AWAITING_INPUT checkpoint) so the resume hook has something to
    approve."""

    def __init__(self, phase: ProjectPhase) -> None:
        self.phase = phase

    async def run(self, ctx: PhaseContext) -> PhaseResult:
        return PhaseResult(status=PhaseStatus.PAUSED, accounts_processed=0)


async def _run_phase_ledger_count(run_id: ProjectRunId) -> int:
    keys = [phase_key(run_id, phase) for phase in ProjectPhase]
    async with transaction() as conn:
        row = await conn.execute(
            text(
                "SELECT count(*) FROM idempotency_ledger "
                "WHERE key = ANY(:keys) AND scope = 'campaign_phase'"
            ),
            {"keys": keys},
        )
        return int(row.scalar_one())


@pytest.mark.usefixtures("require_profiling_db")
def test_default_resume_run_writes_a_phase_ledger_row() -> None:
    """The resume hook's DEFAULT driver (fleet-parity: a ``DbIdempotencyStore`` ledger) records an
    exactly-once ``campaign_phase`` ledger row when it finalizes the approved checkpoint — where the
    old bare ``ProjectRun()`` (ledger=None) wrote none (the ``[B1×M13.2]`` gap). DB-gated; drives
    against the real ``idempotency_ledger`` through minimal process-default phase handlers."""

    async def scenario() -> None:
        registry = default_phase_handler_registry()
        saved = {phase: registry.get(phase) for phase in registry.phases()}
        workspace_id = f"ws-b4-resume-{uuid4().hex[:12]}"
        async with db_lifespan():
            try:
                async with transaction() as conn:
                    project = await seed_project(conn, workspace_id)
                # Minimal completing handlers for every phase into the PROCESS-DEFAULT registry
                # (the one the default resume driver resolves through), then override
                # REVERSE_PROFILING to PAUSE so we get an AWAITING_INPUT checkpoint to approve.
                for phase in ProjectPhase:
                    register_phase_handler(_CompletingPhaseHandler(phase))
                register_phase_handler(_PausingPhaseHandler(ProjectPhase.REVERSE_PROFILING))

                machine = ProjectRun(
                    store=DbProjectRunStore(),
                    budget_engine=BudgetEngine(),
                    ledger=DbIdempotencyStore(),
                )
                run_id = await machine.start(
                    project_id=project.project_id,
                    workspace_id=workspace_id,
                    icp_key="seg",
                    icp_version=1,
                )
                paused = await machine.run_to_completion(run_id)
                # suspended at the reverse_profiling gate
                assert paused.status is ProjectRunStatus.PAUSED

                before = await _run_phase_ledger_count(run_id)
                assert before == 0  # the pause path writes no ledger row

                # Resume via the DEFAULT hook. C5.3 finalizes the checkpoint under the
                # fleet-parity ledger, then offers the detached driver work rather than racing it
                # in-process.
                await ProjectRunResumeHook().resume_review(run_id)

                after = await _run_phase_ledger_count(run_id)
                assert after > before  # the default driver's ledger recorded the finalized phase(s)
                final = await machine.status(run_id)
                assert final.status is ProjectRunStatus.ACTIVE
                async with transaction() as conn:
                    drive_status = (
                        await conn.execute(
                            text(
                                """
                                SELECT status FROM fleet_task
                                WHERE work_id = :run_id AND kind = 'drive_run'
                                """
                            ),
                            {"run_id": run_id},
                        )
                    ).scalar_one()
                assert str(drive_status) == "queued"
            finally:
                registry.clear()
                for handler in saved.values():
                    registry.register(handler)

    run_async(scenario())
