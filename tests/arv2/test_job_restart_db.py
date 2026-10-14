"""A job whose conversation cannot be continued restarts under a new execution (spec §3.2)."""

from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager

import pytest
from sqlalchemy import text

from clue_api.agent_turn_wiring import DurableAgentArtifactStore
from clue_api.arv2.account_research_catalog import arv2_account_profile_sha256
from clue_api.arv2.account_research_driver import Arv2AccountResearchWorkHandler
from clue_api.arv2.account_research_launch import launch_arv2_account_research
from clue_api.arv2.account_research_store import begin_job, read_job
from clue_api.arv2.claim_writer import LenientClaimWriter
from clue_api.arv2.display.recipes import load_display_recipes
from clue_api.arv2.job_resume import ResearchRestartRequired, restart_on_claim
from clue_storage.fs import FsStorage
from tests.arv2.icp_fixture import seed_icp_fixture, settings_for
from tests.arv2.test_account_research_driver_db import _Clients
from tests.arv2.test_account_research_launch_db import _request
from tests.arv2.test_quality_driver_db import Queue, work
from tests.claimstore.conftest import (  # noqa: F401
    migrated_db,
    require_claimstore_db,
    rollback_conn,
    run_async,
)

pytestmark = pytest.mark.usefixtures("require_claimstore_db")


async def _launch(conn, storage):
    fixture = await seed_icp_fixture(conn, storage)
    await load_display_recipes(conn)
    settings = settings_for(arv2_account_research_enabled=True)
    launch = await launch_arv2_account_research(
        conn,
        _request(fixture, account_entity_ids=(fixture.accounts[0],)),
        settings=settings,
        storage=storage,
        profile_sha256=arv2_account_profile_sha256(version="v4"),
    )
    return fixture, settings, launch


async def _audits(conn, job):
    return (
        await conn.execute(
            text(
                "SELECT actor, restarted, attempt_before FROM arv2_research_job_resume "
                "WHERE job_id=:job ORDER BY created_at"
            ),
            {"job": job},
        )
    ).all()


def test_restart_on_claim_moves_the_counter_parks_the_job_and_audits(tmp_path):
    async def case():
        async with rollback_conn() as conn:
            _, _, launch = await _launch(conn, FsStorage(tmp_path))
            job = launch.job_ids[0]
            claimed = await begin_job(conn, job_id=job)
            assert claimed is not None and claimed.attempt == 1
            assert await restart_on_claim(
                conn, job_id=job, attempt=1, reason="instructions_changed"
            )
            row = await read_job(conn, job_id=job)
            assert (row.status, row.restart_count) == ("suspended", 1)
            assert [tuple(a) for a in await _audits(conn, job)] == [
                ("system:instructions_changed", True, 1)
            ]
            # Fenced: the same attempt cannot restart a job it no longer runs.
            assert not await restart_on_claim(
                conn, job_id=job, attempt=1, reason="instructions_changed"
            )
            assert len(await _audits(conn, job)) == 1

    run_async(case())


def test_a_second_restart_counts_from_the_first(tmp_path):
    async def case():
        async with rollback_conn() as conn:
            _, _, launch = await _launch(conn, FsStorage(tmp_path))
            job = launch.job_ids[0]
            for attempt in (1, 2):
                assert (await begin_job(conn, job_id=job)).attempt == attempt
                assert await restart_on_claim(
                    conn, job_id=job, attempt=attempt, reason="context_changed_before_start"
                )
            assert (await read_job(conn, job_id=job)).restart_count == 2

    run_async(case())


def test_the_driver_restarts_requeues_and_the_next_claim_runs_the_new_conversation(tmp_path):
    async def case():
        async with rollback_conn() as conn:
            storage = FsStorage(tmp_path / "blobs")
            fixture, settings, launch = await _launch(conn, storage)
            lock = asyncio.Lock()

            @asynccontextmanager
            async def connections():
                async with lock, conn.begin_nested():
                    yield conn

            seen = []

            class NoLegacyModels:
                def build(self, **kwargs):
                    raise AssertionError("legacy agent must not run for a quality job")

            async def runner(*, scope, context_id, runtime, objective, model_id, unit_key=None):
                seen.append(scope.restart_count)
                if len(seen) == 1:
                    raise ResearchRestartRequired("instructions_changed")
                raise RuntimeError("second claim reached the runner")

            handler = Arv2AccountResearchWorkHandler(
                settings=settings,
                conn_factory=connections,
                artifacts=DurableAgentArtifactStore(storage=storage, conn_factory=connections),
                storage=storage,
                clients=_Clients(),
                model_provider=NoLegacyModels(),
                model_id="fixture/research",
                writer=LenientClaimWriter(lenient=True),
                quality_runner=runner,
                queue=Queue(),
            )
            job = launch.job_ids[0]
            first = await handler.handle(work(job, launch.run_id, fixture.workspace_id))
            assert (first.outcome, first.requeue) == ("stopped", True)
            row = await read_job(conn, job_id=job)
            assert (row.status, row.restart_count) == ("suspended", 1)
            await handler.handle(work(job, launch.run_id, fixture.workspace_id))
            assert seen == [0, 1]

    run_async(case())
