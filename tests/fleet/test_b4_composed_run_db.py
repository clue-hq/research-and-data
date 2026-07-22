"""PB-B4 slice 1 exit gate (a) — the composed worker drives a WHOLE run end-to-end (DB-gated).

A stub-mode run drives ``reverse_profiling → … → handoff`` **through the real
:class:`~clue_fleet.ProjectRunWorker` + the real ``ComposingRunDriver``
against a live Postgres** — the composer builds a per-run registry (all five M5/M6 phases + DEEP +
VERIFICATION + REVIEW-from-boot + HANDOFF) with a stub gateway (``api_key`` absent), an empty
``ChannelRegistry`` / ``committee_sources``, a process-local single-flight lock (no redis), and the
``[M5×M7]`` client-input provider, so every phase completes on empty data.

Skips without a reachable, migrated DB. Runs under a bare ``db_lifespan`` (committed rows — the
worker's ``Db*`` stores each open their own transaction, so a single rolled-back conn cannot span
them; hermeticity is by a per-run unique ``workspace_id``, the fleet-DB-test convention).
"""

from __future__ import annotations

from datetime import timedelta
from uuid import uuid4

import pytest
from sqlalchemy import text
from tests.api.test_storage_wiring import FakeStorage
from tests.fleet.conftest import ProcessLocalLockFactory, run_async

from clue_api.run_composition import ComposingRunDriver
from clue_config import GatewayConfig
from clue_core import ICPCreatedFrom, PhaseContext, ProjectPhase
from clue_db import db_lifespan, transaction
from clue_fleet import DbLeaseStore, DbTaskQueue, ProjectRunWorker, enqueue_drive
from clue_gateway import build_gateway
from clue_research.claimstore import CORE_PACK, load_core_pack
from clue_research.discovery_scoring.discovery import ChannelRegistry
from clue_research.durable import (
    BudgetEngine,
    DbIdempotencyStore,
    DbProjectRunStore,
    ProjectRun,
    ProjectRunStatus,
)
from clue_research.icp import (
    RubricEntry,
    ScoringRubric,
    ScoringTransform,
    SubRubric,
    TierBand,
    TierCutoffs,
    rubric_to_slot,
)
from clue_research.icp.spec import create_icp_spec
from clue_research.stage0 import ClientInput

pytestmark = pytest.mark.usefixtures("require_fleet_db")

_EMP = "core.employee_count"
_FUND = "account.recent_funding"


def _rubric() -> ScoringRubric:
    return ScoringRubric(
        fit=SubRubric(
            entries=(
                RubricEntry(
                    field_key=_EMP, transform=ScoringTransform.LINEAR, params={"lo": 0, "hi": 1000}
                ),
            )
        ),
        intent=SubRubric(
            entries=(RubricEntry(field_key=_FUND, transform=ScoringTransform.BOOLEAN),)
        ),
        tier_cutoffs=TierCutoffs(
            bands=(TierBand(tier="high", min_fit=0.4, min_intent=0.5),), fallback_tier="low"
        ),
    )


async def _ledger_phase_count() -> int:
    async with transaction() as conn:
        row = await conn.execute(
            text("SELECT count(*) FROM idempotency_ledger WHERE scope = 'campaign_phase'")
        )
        return int(row.scalar_one())


def test_composed_worker_drives_reverse_profiling_through_handoff() -> None:
    async def scenario() -> None:
        workspace_id = f"ws-b4-e2e-{uuid4().hex[:12]}"
        icp_key = "seg-b4"

        async with db_lifespan():
            try:
                # Seed (committed): the core field pack (the scoring rubric's fields) + the active
                # ICP spec (rubric + tier bands) the phases read. Source manifests are intentionally
                # NOT seeded — with no resolvers bound the waterfalls resolve nothing and the phases
                # still complete on empty data, and seeding the *global* source_manifest registry
                # would leak into (and collide with) other suites' redefinitions (committed-row
                # hygiene).
                async with transaction() as conn:
                    await load_core_pack(conn)
                async with transaction() as conn:
                    await create_icp_spec(
                        conn,
                        workspace_id=workspace_id,
                        icp_key=icp_key,
                        created_from=ICPCreatedFrom.SYNTHESIS,
                        field_keys=(_EMP, _FUND),
                        scoring_rubric=rubric_to_slot(_rubric()),
                        activate=True,
                    )

                store = DbProjectRunStore()
                machine = ProjectRun(
                    store=store, budget_engine=BudgetEngine(), ledger=DbIdempotencyStore()
                )
                run_id = await machine.start(
                    workspace_id=workspace_id, icp_key=icp_key, icp_version=1
                )

                async def provide_client_input(_ctx: PhaseContext) -> ClientInput:
                    # The [M5×M7] threading seam: what production will look up per workspace; here a
                    # minimal client so the real reverse-profiling handler completes on empty data.
                    return ClientInput(name="Stub Co", website="https://stub.example")

                driver = ComposingRunDriver(
                    gateway=build_gateway(GatewayConfig(stub=True)),
                    storage=FakeStorage(),  # type: ignore[arg-type]
                    lock_factory=ProcessLocalLockFactory(),  # process-local single-flight, no redis
                    channels=ChannelRegistry(),  # empty: discovery finds nothing, advances
                    committee_sources=(),
                    client_input_provider=provide_client_input,
                )
                queue = DbTaskQueue()
                worker = ProjectRunWorker(
                    driver=driver,
                    queue=queue,
                    leases=DbLeaseStore(),
                    worker_id=f"w-b4-{uuid4().hex[:8]}",
                    poll_interval=0.05,
                    lease_ttl=timedelta(seconds=30),
                    heartbeat_interval=5.0,
                    task_stale_after=timedelta(seconds=60),
                )

                before = await _ledger_phase_count()

                # Drive #1: reverse_profiling → icp_confirmed → discovery → scoring →
                # tier_checkpoint, which suspends at the durable human gate (PAUSED).
                await enqueue_drive(queue, run_id)
                await worker.drain_once()
                run = await machine.status(run_id)
                assert run.phase is ProjectPhase.TIER_CHECKPOINT, run.phase
                assert run.status is ProjectRunStatus.PAUSED, run.status

                # Approve the checkpoint (resume), then drive #2: deep → verification → handoff →
                # DONE.
                await machine.submit_checkpoint(run_id, decision={"action": "approve"})
                await enqueue_drive(queue, run_id)  # reopen_terminal: re-drive the paused run
                await worker.drain_once()
                run = await machine.status(run_id)
                assert run.phase is ProjectPhase.HANDOFF, run.phase
                assert run.status is ProjectRunStatus.COMPLETED, run.status

                # The composed run bound the M7.4 ledger (D2/D4 parity with the worker driver): the
                # phase finalizes recorded exactly-once rows (the bare pre-B4 driver wrote none).
                assert await _ledger_phase_count() > before
            finally:
                # ``field_definition`` is a GLOBAL-by-key registry; leaving the committed core pack
                # behind would collide with tests/durable's differing ``account.strategic_moves``
                # definition (FieldRedefinitionError), breaking the rerun-idempotency standing gate.
                # Delete exactly the rows ``load_core_pack`` seeded — enumerable from CORE_PACK;
                # every core field is ``pack=None`` so there is no pack row to remove — leaving the
                # suite rerun-clean. (The run's own project_run/ledger/icp_spec rows are hermetic by
                # the unique per-run ``workspace_id`` and left committed, the fleet-DB-test
                # convention.)
                field_keys = [seed.field_def.field_key for seed in CORE_PACK]
                async with transaction() as conn:
                    await conn.execute(
                        text("DELETE FROM field_definition WHERE field_key = ANY(:keys)"),
                        {"keys": field_keys},
                    )

    run_async(scenario())
