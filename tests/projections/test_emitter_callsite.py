"""B4 slice-3 — the drive-path emission call site (offline).

Proves ``ComposingRunDriver.advance`` fires the injected :class:`RunEventEmitter` with the
before/after run rows around every step (the D8 wiring), and that the default emitter is the no-op
``NullRunEventEmitter`` (a composer driven without an outbox emits nothing — and never touches a
DB). Offline: the store, machine, and composition are all fakes; runs in ``make check``.
"""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from types import SimpleNamespace

from clue_api.run_composition import ComposingRunDriver
from clue_api.run_events_wiring import NullRunEventEmitter
from clue_config import GatewayConfig, load_settings
from clue_core import ProjectPhase, new_project_run_id
from clue_gateway import build_gateway
from clue_research.durable import ProjectRunRow, ProjectRunStatus
from tests.api.test_storage_wiring import FakeStorage
from tests.db.conftest import run_async


def _row(phase: ProjectPhase, status: ProjectRunStatus, run_id) -> ProjectRunRow:
    now = datetime.now(UTC)
    return ProjectRunRow(
        id=run_id,
        project_id="prj-test",
        brand_id="brd-test",
        workspace_id="ws",
        icp_key="k",
        icp_version=1,
        phase=phase,
        status=status,
        budget_cap_cents=None,
        spent_cents=Decimal(0),
        tier_cutoffs={},
        paused_at=None,
        resumed_at=None,
        created_at=now,
        updated_at=now,
    )


class _RecordingEmitter:
    def __init__(self) -> None:
        self.transitions: list[tuple[ProjectRunRow, ProjectRunRow]] = []

    async def phase_transition(self, before: ProjectRunRow, after: ProjectRunRow) -> None:
        self.transitions.append((before, after))


def _driver(**kwargs: object) -> ComposingRunDriver:
    async def spec_loader(workspace_id: str, icp_key: str, icp_version: int):
        return None

    return ComposingRunDriver(
        settings=load_settings(_env_file=None),
        gateway=build_gateway(GatewayConfig(stub=True)),
        storage=FakeStorage(),  # type: ignore[arg-type]
        spec_loader=spec_loader,
        **kwargs,  # type: ignore[arg-type]
    )


def test_advance_fires_emitter_with_before_and_after_rows() -> None:
    run_id = new_project_run_id()
    before = _row(ProjectPhase.DISCOVERY, ProjectRunStatus.ACTIVE, run_id)
    after = _row(ProjectPhase.SCORING, ProjectRunStatus.ACTIVE, run_id)

    class _FakeStore:
        """Only ``get`` is exercised (the probe status read)."""

        async def get(self, project_run_id):
            return before

    emitter = _RecordingEmitter()
    driver = _driver(store=_FakeStore(), event_emitter=emitter)

    class _FakeMachine:
        async def advance(self, project_run_id):
            return after

    async def _composed(row):
        return SimpleNamespace(run=_FakeMachine())

    # Shadow the composition (instance attribute wins over the method) — the emission call site is
    # what this test pins, not the composition itself (covered by the slice-1 suite).
    driver.composed = _composed  # type: ignore[method-assign]

    result = run_async(driver.advance(run_id))
    assert result is after
    assert emitter.transitions == [(before, after)]


def test_default_emitter_is_the_null_noop() -> None:
    driver = _driver()
    assert isinstance(driver._event_emitter, NullRunEventEmitter)  # noqa: SLF001
    # And the null emitter genuinely no-ops (no DB, no raise).
    run_id = new_project_run_id()
    row = _row(ProjectPhase.DISCOVERY, ProjectRunStatus.ACTIVE, run_id)
    run_async(NullRunEventEmitter().phase_transition(row, row))
