"""The arv2_display_page handler: writes a page once, a redelivery writes nothing (plan Task 2)."""

from __future__ import annotations

import asyncio
from typing import Any
from uuid import UUID, uuid4

import pytest
from sqlalchemy import text

from clue_api.arv2.display.fleet_handler import (
    Arv2DisplayPageWorkHandler,
    display_page_payload,
)
from clue_api.arv2.fleet_task import arv2_display_work_id
from clue_config import Settings
from clue_fleet import FleetTaskKind, LeaseGeneration, WorkContext
from tests.arv2.display._seed import seed_display_fixture
from tests.arv2.display.test_page_db import RoutingTransport, _block_counts, _factory
from tests.arv2.test_provider_ledger_db import FakeArtifacts
from tests.claimstore.conftest import (  # noqa: F401
    migrated_db,
    require_claimstore_db,
    rollback_conn,
)
from tests.db.conftest import run_async
from tests.profiling.conftest import conn_session_factory

pytestmark = pytest.mark.usefixtures("require_claimstore_db")

WORKSPACE = "ws_display_fleet"

#: The same shape the web seam's tests build: generation on, verification off, a real parallelism.
SETTINGS = Settings(
    _env_file=None,
    verification_enabled=False,
    arv2_display_max_parallel=4,
    arv2_display_generate_on_read=True,
)


def _context(payload: dict[str, Any]) -> WorkContext:
    return WorkContext(
        task_id=uuid4(),
        work_id=arv2_display_work_id(
            str(payload.get("subject_kind")),
            str(payload.get("subject_id")),
            str(payload.get("page")),
        ),
        worker_id="w1",
        lease_generation=LeaseGeneration(1),
        payload=payload,
        stop_requested=asyncio.Event(),
        lease_lost=asyncio.Event(),
    )


def test_the_handler_owns_the_display_kind() -> None:
    assert Arv2DisplayPageWorkHandler.kind is FleetTaskKind.ARV2_DISPLAY_PAGE


def test_a_page_task_writes_the_page_once_and_a_redelivery_writes_nothing() -> None:
    async def _run() -> None:
        async with rollback_conn(seed_pack=False) as conn:
            seeded = await seed_display_fixture(conn, workspace_id=WORKSPACE)
            transport = RoutingTransport()
            handler = Arv2DisplayPageWorkHandler(
                settings=SETTINGS,
                conn_factory=conn_session_factory(conn),
                runner_factory=_factory(transport),
                artifacts=FakeArtifacts(),
            )
            job_id = uuid4()
            payload = display_page_payload(
                workspace_id=seeded.workspace_id,
                subject_kind="contact",
                subject_id=str(seeded.nick),
                page="contact",
                job_id=job_id,
            )

            first = await handler.handle(_context(payload))
            assert first.outcome == "completed"
            assert first.requeue is False
            assert sorted(first.references["generated"]) == sorted(transport.sections)
            assert len(transport.sections) == 6
            assert await _block_counts(conn, seeded.workspace_id) == (6, 0)
            # The page's spend is stamped with the research job that produced its claims.
            stamped = (
                await conn.execute(
                    text(
                        "SELECT count(*) FROM provider_call_ledger "
                        "WHERE entity_research_job_id = :job_id AND phase = 'result'"
                    ),
                    {"job_id": job_id},
                )
            ).scalar_one()
            assert stamped == 6

            second = await handler.handle(_context(payload))
            assert second.outcome == "completed"
            assert second.references["generated"] == []
            assert len(transport.sections) == 6, "a redelivery costs nothing it already paid for"

    run_async(_run())


def test_a_payload_naming_no_subject_fails_without_requeue() -> None:
    handler = Arv2DisplayPageWorkHandler(
        settings=SETTINGS,
        conn_factory=None,  # type: ignore[arg-type]
        runner_factory=None,  # type: ignore[arg-type]
        artifacts=FakeArtifacts(),
    )
    result = asyncio.run(handler.handle(_context({"workspace_id": WORKSPACE})))
    assert result.outcome == "failed"
    assert result.requeue is False


def test_an_unknown_subject_fails_without_requeue() -> None:
    async def _run() -> None:
        async with rollback_conn(seed_pack=False) as conn:
            seeded = await seed_display_fixture(conn, workspace_id=WORKSPACE)
            handler = Arv2DisplayPageWorkHandler(
                settings=SETTINGS,
                conn_factory=conn_session_factory(conn),
                runner_factory=_factory(RoutingTransport(allowed=False)),
                artifacts=FakeArtifacts(),
            )
            payload = display_page_payload(
                workspace_id=seeded.workspace_id,
                subject_kind="account",
                subject_id=str(UUID(int=7)),
                page="overview",
            )
            result = await handler.handle(_context(payload))
            assert result.outcome == "failed"
            assert result.requeue is False
            assert result.references["reason"] == "SubjectNotFound"

    run_async(_run())
