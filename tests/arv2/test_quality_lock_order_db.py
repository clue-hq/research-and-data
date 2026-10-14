"""Authority checks and allowance reserves on one job never deadlock each other.

Production, 2026-10-13: a person job died on ``40P01``. An evidence tool held the job's execution
row (``resolve_authority``) and then asked for the shared allowance row (``reserve``), while the
model-call middleware held the allowance row and inserted an activity row whose foreign key needs a
key-share lock on that same execution row. Spawning a specialist (``bind_execution``) has the same
shape: it holds the allowance row and inserts a child execution row whose foreign key names the
parent's execution row. Each case below replays one of those orders on two real connections.

The seed is committed (both transactions must see it) under a workspace and user of its own, the
``test_discovery_launch_db`` precedent.
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from uuid import UUID, uuid4

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from clue_api.arv2.account_research_catalog import arv2_account_profile_sha256
from clue_api.arv2.account_research_claims import JobScope
from clue_api.arv2.account_research_launch import launch_arv2_account_research
from clue_api.arv2.quality_authority import resolve_authority
from clue_api.arv2.quality_context import build_context, persist_context
from clue_api.arv2.quality_execution import Allowance, bind_execution, reserve
from clue_api.arv2.research_operations import OperationScope
from clue_db import db_lifespan
from clue_research.claimstore import load_core_pack
from clue_storage.fs import FsStorage
from tests.arv2.icp_fixture import seed_icp_fixture, settings_for
from tests.arv2.test_account_research_launch_db import _request
from tests.arv2.test_quality_evidence_db import NOW
from tests.arv2.test_quality_execution_db import execution
from tests.claimstore.conftest import (  # noqa: F401
    migrated_db,
    require_claimstore_db,
    run_async,
)

pytestmark = pytest.mark.usefixtures("require_claimstore_db")

LIMITS = Allowance(50, 50, 5)


async def _seed(conn: AsyncConnection, storage: FsStorage) -> tuple[OperationScope, JobScope, UUID]:
    await load_core_pack(conn)
    user_id = f"usr_lock_{uuid4().hex[:10]}"
    fixture = await seed_icp_fixture(
        conn, storage, workspace_id=f"ws_lock_{uuid4().hex[:10]}", user_id=user_id
    )
    receipt = await launch_arv2_account_research(
        conn,
        _request(fixture, requested_by_user_id=user_id),
        storage=storage,
        settings=settings_for(
            arv2_account_research_enabled=True, arv2_research_catalog_version="v2"
        ),
        profile_sha256=arv2_account_profile_sha256(version="v2"),
    )
    op = OperationScope(
        fixture.workspace_id, receipt.run_id, receipt.job_ids[0], UUID(str(fixture.accounts[0]))
    )
    run = (
        (
            await conn.execute(
                text(
                    "SELECT project_id,product_selection_version "
                    "FROM arv2_research_run WHERE run_id=:run"
                ),
                {"run": op.run_id},
            )
        )
        .mappings()
        .one()
    )
    context = await build_context(
        conn,
        storage,
        workspace_id=op.workspace_id,
        project_id=run["project_id"],
        product_selection_version=run["product_selection_version"],
    )
    cid = await persist_context(conn, storage, context)
    await conn.execute(
        text("UPDATE arv2_research_run SET context_id=:cid WHERE run_id=:run"),
        {"cid": cid, "run": op.run_id},
    )
    job = JobScope(
        workspace_id=op.workspace_id,
        project_id=run["project_id"],
        project_run_id=op.run_id,
        run_id=op.run_id,
        job_id=op.job_id,
        account_id=op.account_id,
        account_name="Fixture",
        account_domain="example.test",
        icp_markdown="",
        persona_markdown="",
        already_established="",
        effort="high",
        committee_cap=4,
        today=NOW.date(),
    )
    return op, job, cid


async def _settle(observer: AsyncConnection, pid: int, task: asyncio.Task) -> str:
    """Return "lock" once the backend waits on a row lock, or "done" once its task finished."""
    for _ in range(200):
        if task.done():
            return "done"
        waiting = (
            await observer.execute(
                text("SELECT wait_event_type FROM pg_stat_activity WHERE pid=:p"), {"p": pid}
            )
        ).scalar_one_or_none()
        if waiting == "Lock":
            return "lock"
        await asyncio.sleep(0.05)
    raise AssertionError("the transaction neither finished nor waited on a lock")


Second = Callable[[AsyncConnection, OperationScope, UUID, UUID, UUID], Awaitable[None]]


async def _middleware_reserve(conn, op, cid, parent, child) -> None:
    # SharedResearchAllowance.awrap_model_call: allowance row, then an activity row whose FK
    # takes a key-share lock on the parent's execution row.
    await reserve(conn, op, execution_id=parent, kind="model", activity_id=uuid4())


async def _specialist_bind(conn, op, cid, parent, child) -> None:
    # Spawning a specialist: allowance row, then a child execution row whose FK takes a key-share
    # lock on the parent's execution row.
    await bind_execution(
        conn,
        op,
        execution_id=child,
        context_id=cid,
        role="research_claims",
        limits=LIMITS,
        parent_execution_id=parent,
    )


@pytest.mark.parametrize(
    "second", [_middleware_reserve, _specialist_bind], ids=["middleware_reserve", "specialist_bind"]
)
def test_evidence_tool_and_a_concurrent_allowance_holder_do_not_deadlock(tmp_path, second: Second):
    async def scenario() -> None:
        storage = FsStorage(tmp_path)
        async with db_lifespan() as engine:
            async with engine.begin() as conn:
                op, job, cid = await _seed(conn, storage)
                parent = await execution(conn, op, job.project_id)
                child = await execution(conn, op, job.project_id, parent)
                await bind_execution(
                    conn,
                    op,
                    execution_id=parent,
                    context_id=cid,
                    role="account_research",
                    limits=LIMITS,
                )

            async with (
                engine.connect() as observer,
                engine.connect() as tool_conn,
                engine.connect() as other_conn,
            ):
                await observer.execute(text("SELECT 1"))
                await observer.commit()
                tool_txn = await tool_conn.begin()
                other_txn = await other_conn.begin()
                tool_pid = (await tool_conn.execute(text("SELECT pg_backend_pid()"))).scalar_one()
                other_pid = (await other_conn.execute(text("SELECT pg_backend_pid()"))).scalar_one()
                try:
                    # acquire_research_evidence: authority first (the parent's execution row)...
                    authority = await resolve_authority(tool_conn, job, parent)
                    other = asyncio.create_task(second(other_conn, op, cid, parent, child))
                    other_state = await _settle(observer, other_pid, other)
                    # ...then the shared allowance row.
                    tool = asyncio.create_task(
                        reserve(
                            tool_conn,
                            authority.grant.scope,
                            execution_id=parent,
                            kind="tool",
                            activity_id=uuid4(),
                        )
                    )
                    if other_state == "done":
                        # The second transaction never waited on the tool's lock; it now holds the
                        # allowance row, so the tool queues behind it until it commits.
                        await other
                        assert await _settle(observer, tool_pid, tool) == "lock"
                        await other_txn.commit()
                    await asyncio.wait_for(asyncio.gather(tool, other), timeout=20)
                    await tool_txn.commit()
                    if other_txn.is_active:
                        await other_txn.commit()
                finally:
                    if other_txn.is_active:
                        await other_txn.rollback()
                    if tool_txn.is_active:
                        await tool_txn.rollback()

            async with engine.connect() as conn:
                kinds = sorted(
                    (
                        await conn.execute(
                            text("SELECT kind FROM arv2_quality_activity WHERE job_id=:job"),
                            {"job": op.job_id},
                        )
                    ).scalars()
                )
            assert kinds == (["model", "tool"] if second is _middleware_reserve else ["tool"])

    run_async(scenario())
