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
