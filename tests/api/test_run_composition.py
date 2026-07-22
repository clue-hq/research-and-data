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

import pytest

from clue_api.review.composition import _default_resume_run
from clue_api.run_composition import ComposedRun, ComposingRunDriver, CompositionUnavailable
from clue_config import GatewayConfig
from clue_core import ICPCreatedFrom, ICPSpec, ProjectPhase, new_project_run_id
from clue_gateway import build_gateway
from clue_research.durable import ProjectRun
from clue_research.durable.enums import ProjectRunStatus
from clue_research.durable.project_run import ProjectRunRow
from tests.api.test_storage_wiring import FakeStorage
from tests.db.conftest import run_async
from tests.fleet.conftest import ProcessLocalLockFactory

_ALL_PHASES = frozenset(ProjectPhase)


def _stub_gateway() -> object:
    return build_gateway(GatewayConfig(stub=True))


def _spec(icp_key: str, *, workspace_id: str = "ws", version: int = 1) -> ICPSpec:
    return ICPSpec(
        workspace_id=workspace_id,
        icp_key=icp_key,
        created_from=ICPCreatedFrom.SYNTHESIS,
        version=version,
        field_keys=(f"core.field_{icp_key}",),
    )


def _row(icp_key: str, *, workspace_id: str = "ws", version: int = 1) -> ProjectRunRow:
    now = datetime.now(UTC)
    return ProjectRunRow(
        id=new_project_run_id(),
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
    )


def _driver(specs: dict[tuple[str, str, int], ICPSpec], **kwargs: object) -> ComposingRunDriver:
    async def spec_loader(workspace_id: str, icp_key: str, icp_version: int) -> ICPSpec | None:
        return specs.get((workspace_id, icp_key, icp_version))

    return ComposingRunDriver(
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
        assert a.spec.icp_key == "a" and b.spec.icp_key == "b"
        # Each run's DEEP handler is its own object — no shared/overwritten slot.
        deep_a = a.registry.get(ProjectPhase.DEEP)
        deep_b = b.registry.get(ProjectPhase.DEEP)
        assert deep_a is not None and deep_b is not None and deep_a is not deep_b
        # And the field-registry the spec carries proves each saw its own spec.
        assert a.spec.field_keys != b.spec.field_keys

    run_async(scenario())


def test_composition_is_cached_per_key() -> None:
    async def scenario() -> None:
        driver = _driver({("ws", "a", 1): _spec("a")})
        first = await driver.composed(_row("a"))
        second = await driver.composed(_row("a"))  # same (ws, icp_key, version) key
        assert first is second  # LRU hit — not recomposed

    run_async(scenario())


def test_lru_evicts_beyond_cache_size() -> None:
    async def scenario() -> None:
        specs = {("ws", k, 1): _spec(k) for k in ("a", "b", "c")}
        driver = _driver(specs, cache_size=2)
        a1 = await driver.composed(_row("a"))
        await driver.composed(_row("b"))
        await driver.composed(_row("c"))  # evicts "a" (least-recently-used)
        a2 = await driver.composed(_row("a"))  # recomposed → a fresh object
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
