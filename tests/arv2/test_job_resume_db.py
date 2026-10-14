"""One audited operation takes a stopped research job back into the queue (spec §3.5)."""

from __future__ import annotations

import pytest
from sqlalchemy import text

from clue_api.arv2.account_research_store import begin_job, read_job
from clue_api.arv2.job_resume import (
    ResumeRefused,
    TopUp,
    list_stuck_jobs,
    offer_research_job,
    resume_research_job,
)
from clue_api.arv2.quality_execution import Allowance, bind_execution
from clue_api.arv2.quality_generation import ensure_generation
from clue_storage.fs import FsStorage
from tests.arv2.test_quality_claims_db import setup
from tests.arv2.test_quality_execution_db import execution
from tests.claimstore.conftest import (  # noqa: F401
    migrated_db,
    require_claimstore_db,
    rollback_conn,
    run_async,
)

pytestmark = pytest.mark.usefixtures("require_claimstore_db")

BASE = Allowance(20, 30, 4, 600_000)


async def _fail(conn, job, code="d_b_a_p_i_error"):
    await conn.execute(
        text(
            "UPDATE arv2_research_job SET status='needs_review', attempt=1, started_at=now(), "
            "finished_at=now(), failure_code=:code, failure_message='stopped' WHERE job_id=:job"
        ),
        {"job": job, "code": code},
    )


async def _audit_count(conn, job):
    return (
        await conn.execute(
            text("SELECT count(*) FROM arv2_research_job_resume WHERE job_id=:job"), {"job": job}
        )
    ).scalar_one()


async def _open_tasks(conn, job):
    return (
        await conn.execute(
            text(
                "SELECT count(*) FROM fleet_task WHERE work_id=:job "
                "AND status IN ('queued','claimed')"
            ),
            {"job": job},
        )
    ).scalar_one()


async def _resume(conn, op, **kwargs):
    return await resume_research_job(
        conn,
        workspace_id=kwargs.pop("workspace_id", op.workspace_id),
        job_id=op.job_id,
        actor="operator:test",
        reason=kwargs.pop("reason", "deadlock fixed"),
        **kwargs,
    )


def test_resume_moves_a_failed_job_back_to_the_queue_with_an_audit_row(tmp_path):
    async def case():
        async with rollback_conn() as conn:
            op, _, _ = await setup(conn, FsStorage(tmp_path))
            await _fail(conn, op.job_id)
            result = await _resume(conn, op)
            assert (result.status, result.restarted, result.attempt) == ("suspended", False, 1)
            row = await read_job(conn, job_id=op.job_id)
            assert (row.status, row.failure_code, row.finished_at) == ("suspended", None, None)
            assert row.restart_count == 0
            assert await _open_tasks(conn, op.job_id) == 1
            assert await _audit_count(conn, op.job_id) == 1

    run_async(case())


def test_restart_fresh_moves_the_counter(tmp_path):
    async def case():
        async with rollback_conn() as conn:
            op, _, _ = await setup(conn, FsStorage(tmp_path))
            await _fail(conn, op.job_id)
            result = await _resume(conn, op, restart_fresh=True)
            assert result.restarted
            assert (await read_job(conn, job_id=op.job_id)).restart_count == 1
            restarted = (
                await conn.execute(
                    text("SELECT restarted FROM arv2_research_job_resume WHERE job_id=:job"),
                    {"job": op.job_id},
                )
            ).scalar_one()
            assert restarted is True

    run_async(case())


def test_a_job_with_an_open_task_is_refused_and_writes_nothing(tmp_path):
    async def case():
        async with rollback_conn() as conn:
            op, _, _ = await setup(conn, FsStorage(tmp_path))
            await _fail(conn, op.job_id)
            await _resume(conn, op)
            with pytest.raises(ResumeRefused) as refused:
                await _resume(conn, op)
            assert refused.value.code == "job_already_queued"
            assert await _audit_count(conn, op.job_id) == 1

    run_async(case())


@pytest.mark.parametrize(
    "prepare,code",
    [
        (
            "UPDATE arv2_research_job SET status='completed', finished_at=now() WHERE job_id=:job",
            "job_completed",
        ),
        ("SELECT 1", "job_not_started"),
        (
            "UPDATE arv2_research_job SET input_refs=COALESCE(input_refs,'{}'::jsonb)"
            " || '{\"privacy_stopped\": true}'::jsonb, status='suspended' WHERE job_id=:job",
            "privacy_stopped",
        ),
    ],
)
def test_jobs_that_are_not_stuck_or_were_stopped_are_refused(tmp_path, prepare, code):
    async def case():
        async with rollback_conn() as conn:
            op, _, _ = await setup(conn, FsStorage(tmp_path))
            await conn.execute(text(prepare), {"job": op.job_id})
            with pytest.raises(ResumeRefused) as refused:
                await _resume(conn, op)
            assert refused.value.code == code
            assert await _audit_count(conn, op.job_id) == 0

    run_async(case())


def test_a_suspended_generation_and_frozen_outputs_are_refused(tmp_path):
    async def case():
        async with rollback_conn() as conn:
            op, _, cid = await setup(conn, FsStorage(tmp_path))
            await _fail(conn, op.job_id, code="workspace_conflict")
            with pytest.raises(ResumeRefused) as frozen:
                await _resume(conn, op)
            assert frozen.value.code == "outputs_frozen"
            await _fail(conn, op.job_id)
            generation = await ensure_generation(conn, op, context_id=cid)
            await conn.execute(
                text(
                    "UPDATE arv2_account_research_generation SET state='suspended' "
                    "WHERE generation_id=:id"
                ),
                {"id": generation.generation_id},
            )
            with pytest.raises(ResumeRefused) as stopped:
                await _resume(conn, op)
            assert stopped.value.code == "research_stopped"

    run_async(case())


def test_input_errors_and_other_workspaces_are_refused(tmp_path):
    async def case():
        async with rollback_conn() as conn:
            op, _, _ = await setup(conn, FsStorage(tmp_path))
            await _fail(conn, op.job_id)
            for kwargs, code in (
                ({"reason": "  "}, "reason_required"),
                ({"top_up": TopUp(tool_calls=-1)}, "invalid_top_up"),
                ({"top_up": TopUp(tool_calls=5)}, "invalid_top_up"),  # no allowance row yet
                ({"workspace_id": "ws_someone_else"}, "job_not_found"),
            ):
                with pytest.raises(ResumeRefused) as refused:
                    await _resume(conn, op, **kwargs)
                assert refused.value.code == code, kwargs
            assert await _audit_count(conn, op.job_id) == 0

    run_async(case())


def test_a_topped_up_allowance_binds_on_the_next_claim(tmp_path):
    async def case():
        async with rollback_conn() as conn:
            op, scope, cid = await setup(conn, FsStorage(tmp_path))
            parent = await execution(conn, op, scope.project_id)
            await bind_execution(
                conn, op, execution_id=parent, context_id=cid, role="account_research", limits=BASE
            )
            await _fail(conn, op.job_id)
            top_up = TopUp(model_calls=5, tool_calls=10, delegations=1, runtime_minutes=2)
            assert (await _resume(conn, op, top_up=top_up)).top_up_applied == top_up
            limits = (
                await conn.execute(
                    text(
                        "SELECT max_model_calls,max_tool_calls,max_delegations,max_runtime_ms "
                        "FROM arv2_quality_allowance WHERE job_id=:job"
                    ),
                    {"job": op.job_id},
                )
            ).one()
            assert tuple(limits) == (25, 40, 5, 720_000)
            # The next claim binds with the configured base limits; the recorded top-up explains
            # the difference, so it is not mistaken for a reset.
            assert await begin_job(conn, job_id=op.job_id) is not None
            restarted = await execution(conn, op, scope.project_id)
            await bind_execution(
                conn,
                op,
                execution_id=restarted,
                context_id=cid,
                role="account_research",
                limits=BASE,
            )
            with pytest.raises(ValueError):
                await bind_execution(
                    conn,
                    op,
                    execution_id=await execution(conn, op, scope.project_id),
                    context_id=cid,
                    role="account_research",
                    limits=Allowance(21, 30, 4, 600_000),
                )

    run_async(case())


def test_runtime_top_up_on_an_unlimited_allowance_is_refused(tmp_path):
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
                limits=Allowance(20, 30, 4, 0),
            )
            await _fail(conn, op.job_id)
            with pytest.raises(ResumeRefused) as refused:
                await _resume(conn, op, top_up=TopUp(runtime_minutes=5))
            assert refused.value.code == "invalid_top_up"

    run_async(case())


def test_the_stuck_list_shows_failed_and_stranded_jobs_with_their_resumability(tmp_path):
    async def case():
        async with rollback_conn() as conn:
            op, _, _ = await setup(conn, FsStorage(tmp_path))
            other = (
                await conn.execute(
                    text("SELECT job_id FROM arv2_research_job WHERE run_id=:run AND job_id<>:job"),
                    {"run": op.run_id, "job": op.job_id},
                )
            ).scalar_one()
            assert await list_stuck_jobs(conn, workspace_id=op.workspace_id) == []
            await _fail(conn, op.job_id, code="workspace_conflict")
            await conn.execute(
                text(
                    "UPDATE arv2_research_job SET status='in_progress', attempt=1, "
                    "started_at=now() WHERE job_id=:job"
                ),
                {"job": other},
            )
            stuck = {j.job_id: j for j in await list_stuck_jobs(conn, workspace_id=op.workspace_id)}
            assert set(stuck) == {op.job_id, other}
            assert (stuck[op.job_id].state, stuck[op.job_id].resumable) == ("failed", False)
            assert stuck[op.job_id].refusal == "outputs_frozen"
            assert (stuck[other].state, stuck[other].resumable) == ("stalled", True)
            await offer_research_job(
                conn, job_id=other, run_id=op.run_id, workspace_id=op.workspace_id
            )
            listed = {j.job_id for j in await list_stuck_jobs(conn, workspace_id=op.workspace_id)}
            assert listed == {op.job_id}
            assert await list_stuck_jobs(conn, workspace_id="ws_someone_else") == []
            assert stuck[op.job_id].as_json()["job_id"] == str(op.job_id)

    run_async(case())


def test_a_resumed_account_job_settling_again_moves_its_generation(tmp_path):
    """A job resumed after it settled once settles again on a later attempt; that is a new
    event for its generation, while a redelivered settle of the same attempt is not."""
    import inspect
    from uuid import NAMESPACE_URL, uuid5

    from clue_api.arv2.account_research_driver import Arv2AccountResearchWorkHandler
    from clue_api.arv2.quality_generation import initial_settle_event_id, signal

    async def case():
        async with rollback_conn() as conn:
            op, _, cid = await setup(conn, FsStorage(tmp_path))
            generation = await ensure_generation(conn, op, context_id=cid)
            # Attempt 1 keeps the id every job already used, so existing jobs replay unchanged.
            assert initial_settle_event_id(op.job_id, 1) == uuid5(
                NAMESPACE_URL, f"quality-initial:{op.job_id}"
            )

            async def settle(attempt: int) -> int:
                return await signal(
                    conn,
                    workspace_id=op.workspace_id,
                    generation_id=generation.generation_id,
                    event_id=initial_settle_event_id(op.job_id, attempt),
                    reason="initial_settled",
                )

            first = await settle(1)
            assert await settle(1) == first
            assert await settle(2) == first + 1

    run_async(case())
    # The driver's settle uses it (not a fixed per-job id).
    assert "initial_settle_event_id" in inspect.getsource(
        Arv2AccountResearchWorkHandler._settle_quality
    )
