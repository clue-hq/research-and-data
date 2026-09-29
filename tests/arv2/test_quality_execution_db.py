"""Parent/child dispatch allowances survive recovery and cannot cross research jobs."""

from contextlib import asynccontextmanager
from uuid import uuid4

import pytest
from sqlalchemy import text

from clue_api.arv2.quality_execution import (
    Allowance,
    ResearchAllowanceExhausted,
    SharedResearchAllowance,
    bind_execution,
    reserve,
)
from clue_storage.fs import FsStorage
from tests.arv2.test_quality_claims_db import setup
from tests.claimstore.conftest import (  # noqa: F401
    migrated_db,
    require_claimstore_db,
    rollback_conn,
    run_async,
)

pytestmark = pytest.mark.usefixtures("require_claimstore_db")


async def execution(conn, op, project, parent=None):
    eid = uuid4()
    key = (
        await conn.execute(
            text(
                "SELECT manifest_key FROM arv2_research_context_pin WHERE workspace_id=:ws LIMIT 1"
            ),
            {"ws": op.workspace_id},
        )
    ).scalar_one()
    await conn.execute(
        text("""
      INSERT INTO execution(id,workspace_id,project_id,parent_execution_id,started_by,
        parameter_artifact_key,parameter_manifest_hash,pin_manifest_hash)
      VALUES (:id,:ws,:project,:parent,'agent',:key,:sha,:sha)
    """),
        {
            "id": eid,
            "ws": op.workspace_id,
            "project": project,
            "parent": parent,
            "key": key,
            "sha": key.split("/")[-1],
        },
    )
    return eid


def test_parent_child_share_allowance_replay_and_privacy(tmp_path):
    async def case():
        async with rollback_conn() as conn:
            op, scope, cid = await setup(conn, FsStorage(tmp_path))
            parent = await execution(conn, op, scope.project_id)
            child = await execution(conn, op, scope.project_id, parent)
            limits = Allowance(2, 3, 1)
            for eid, role, pid in [
                (parent, "account_research", None),
                (child, "research_claims", parent),
            ]:
                await bind_execution(
                    conn,
                    op,
                    execution_id=eid,
                    context_id=cid,
                    role=role,
                    limits=limits,
                    parent_execution_id=pid,
                )
            aid = uuid4()
            await reserve(conn, op, execution_id=parent, kind="model", activity_id=aid)
            await reserve(conn, op, execution_id=parent, kind="model", activity_id=aid)
            await reserve(conn, op, execution_id=child, kind="model", activity_id=uuid4())
            # Rebinding on a fresh worker neither creates another allowance nor resets counters.
            await bind_execution(
                conn,
                op,
                execution_id=child,
                context_id=cid,
                role="research_claims",
                limits=limits,
                parent_execution_id=parent,
            )
            with pytest.raises(ResearchAllowanceExhausted):
                await reserve(conn, op, execution_id=parent, kind="model", activity_id=uuid4())
            with pytest.raises(ValueError, match="reset"):
                await bind_execution(
                    conn,
                    op,
                    execution_id=child,
                    context_id=cid,
                    role="research_claims",
                    limits=Allowance(20, 30, 10),
                    parent_execution_id=parent,
                )
            with pytest.raises(ValueError, match="original authority"):
                await reserve(conn, op, execution_id=child, kind="tool", activity_id=aid)
            with pytest.raises(ValueError, match="no research allowance"):
                await reserve(conn, op, execution_id=uuid4(), kind="tool", activity_id=uuid4())
            await conn.execute(
                text(
                    "UPDATE arv2_research_job SET "
                    "input_refs=jsonb_set(input_refs,'{privacy_stopped}','true') "
                    "WHERE job_id=:job"
                ),
                {"job": op.job_id},
            )
            with pytest.raises(ValueError, match="withdrawn"):
                await reserve(conn, op, execution_id=child, kind="tool", activity_id=uuid4())

    run_async(case())


def test_dispatch_failure_still_consumes_model_allowance(tmp_path):
    async def case():
        async with rollback_conn() as conn:
            op, scope, cid = await setup(conn, FsStorage(tmp_path))
            parent = await execution(conn, op, scope.project_id)
            await bind_execution(
                conn,
                op,
                execution_id=parent,
                context_id=cid,
                role="account_research",
                limits=Allowance(1, 2, 1),
            )

            @asynccontextmanager
            async def connections():
                yield conn

            calls = []

            async def provider(request):
                calls.append(request)
                raise RuntimeError("simulated dispatch failure")

            guard = SharedResearchAllowance(connections, op, parent)
            with pytest.raises(RuntimeError, match="dispatch failure"):
                await guard.awrap_model_call("request", provider)
            with pytest.raises(ResearchAllowanceExhausted):
                await guard.awrap_model_call("retry", provider)
            assert calls == ["request"]

    run_async(case())


def test_elapsed_runtime_recovery_owner_and_stop_are_shared(tmp_path):
    from dataclasses import replace

    from clue_api.arv2.quality_execution import begin_runtime, finish_runtime, runtime_remaining
    from clue_api.arv2.quality_generation import ensure_generation
    from clue_api.arv2.research_operations import job_available

    async def case():
        async with rollback_conn() as conn:
            op, scope, cid = await setup(conn, FsStorage(tmp_path))
            parent = await execution(conn, op, scope.project_id)
            await bind_execution(
                conn,
                op,
                execution_id=parent,
                context_id=cid,
                role="account_research",
                limits=Allowance(10, 20, 2, 10000),
            )
            first, recovery = uuid4(), uuid4()
            assert 9 < await begin_runtime(conn, op, owner=first) <= 10
            # Move the persisted start time, avoiding a real sleep in a final-behavior test.
            await conn.execute(
                text(
                    "UPDATE arv2_quality_allowance SET "
                    "runtime_started_at=clock_timestamp()-interval '3 seconds' WHERE job_id=:job"
                ),
                {"job": op.job_id},
            )
            assert 6 < await begin_runtime(conn, op, owner=recovery) <= 7
            await finish_runtime(conn, op, owner=first)  # stale worker cannot release new authority
            assert 6 < await runtime_remaining(conn, op, owner=recovery) <= 7
            with pytest.raises(ResearchAllowanceExhausted, match="authority"):
                await runtime_remaining(conn, op, owner=first)
            await finish_runtime(conn, op, owner=recovery)
            assert 6 < await begin_runtime(conn, op, owner=uuid4()) <= 7
            assert not await job_available(conn, replace(op, account_id=uuid4()))
            assert not await job_available(conn, replace(op, run_id=uuid4()))
            generation = await ensure_generation(conn, op, context_id=cid)
            await conn.execute(
                text(
                    "UPDATE arv2_account_research_generation SET state='suspended' "
                    "WHERE generation_id=:id"
                ),
                {"id": generation.generation_id},
            )
            with pytest.raises(ValueError, match="withdrawn"):
                await reserve(conn, op, execution_id=parent, kind="tool", activity_id=uuid4())
            await conn.execute(
                text(
                    "UPDATE arv2_account_research_generation SET state='researching' "
                    "WHERE generation_id=:id"
                ),
                {"id": generation.generation_id},
            )
            await conn.execute(
                text(
                    "UPDATE arv2_quality_allowance SET "
                    "runtime_started_at=clock_timestamp()-interval '11 seconds' WHERE job_id=:job"
                ),
                {"job": op.job_id},
            )
            with pytest.raises(ResearchAllowanceExhausted, match="exhausted"):
                await reserve(conn, op, execution_id=parent, kind="model", activity_id=uuid4())

    run_async(case())


def test_supervised_zero_runtime_keeps_usage_and_owner_checks(tmp_path):
    from math import isinf

    from clue_api.arv2.quality_execution import begin_runtime, finish_runtime, runtime_remaining

    async def case():
        async with rollback_conn() as conn:
            op, scope, cid = await setup(conn, FsStorage(tmp_path))
            parent = await execution(conn, op, scope.project_id)
            await bind_execution(
                conn,
                op,
                execution_id=parent,
                context_id=cid,
                role="account_research",
                limits=Allowance(10, 20, 2, 0),
            )
            owner = uuid4()
            assert isinf(await begin_runtime(conn, op, owner=owner))
            await conn.execute(
                text("""UPDATE arv2_quality_allowance
                SET runtime_started_at=clock_timestamp()-interval '2 hours'
                WHERE job_id=:job"""),
                {"job": op.job_id},
            )
            assert isinf(await runtime_remaining(conn, op, owner=owner))
            with pytest.raises(ResearchAllowanceExhausted, match="authority"):
                await runtime_remaining(conn, op, owner=uuid4())
            await finish_runtime(conn, op, owner=owner)
            used = (
                await conn.execute(
                    text("SELECT runtime_used_ms FROM arv2_quality_allowance WHERE job_id=:job"),
                    {"job": op.job_id},
                )
            ).scalar_one()
            assert used >= 7200000
            assert isinf(await begin_runtime(conn, op, owner=uuid4()))

    run_async(case())
