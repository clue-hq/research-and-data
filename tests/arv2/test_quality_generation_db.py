"""Durable revisions survive duplicates, late people and stale reconciliation."""

from dataclasses import replace
from datetime import timedelta
from decimal import Decimal
from types import SimpleNamespace
from uuid import uuid4

import pytest
from sqlalchemy import text

from clue_api.arv2.account_research_driver import Arv2AccountResearchWorkHandler
from clue_api.arv2.account_research_store import create_job
from clue_api.arv2.quality_generation import (
    ensure_generation,
    pending_continuations,
    read_generation,
    reconcile_generation,
    record_child_result,
    register_child,
    signal,
    signal_subject_change,
)
from clue_api.arv2.quality_results import QualityJobOutcome, ResearchUnitReport
from clue_research.identity import insert_contact_entity
from clue_storage.fs import FsStorage
from tests.arv2.account_research_job_helpers import finish_seeded_job
from tests.arv2.test_quality_claims_db import setup
from tests.claimstore.conftest import (  # noqa: F401
    migrated_db,
    require_claimstore_db,
    rollback_conn,
    run_async,
)

pytestmark = pytest.mark.usefixtures("require_claimstore_db")


def test_initial_terminal_history_late_people_and_replay(tmp_path):
    async def case():
        async with rollback_conn() as conn:
            storage = FsStorage(tmp_path)
            scope, _, cid = await setup(conn, storage)
            generation = await ensure_generation(conn, scope, context_id=cid)
            assert await ensure_generation(conn, scope, context_id=cid) == generation
            contact = await insert_contact_entity(
                conn, account_entity_id=scope.account_id, full_name="Fixture owner"
            )
            child = uuid4()
            await create_job(
                conn,
                job_id=child,
                run_id=scope.run_id,
                workspace_id=scope.workspace_id,
                account_entity_id=scope.account_id,
                subject_type="person",
                subject_entity_id=contact,
                profile_sha256="a" * 64,
                input_refs={"parent_job_id": str(scope.job_id)},
            )
            await register_child(conn, generation, job_id=child)
            await register_child(conn, generation, job_id=child)
            assert not await pending_continuations(conn)
            await finish_seeded_job(
                conn,
                model_rounds=0,
                tool_calls=0,
                cost_usd=Decimal(0),
                credits=Decimal(0),
                media_seconds=0,
                job_id=scope.job_id,
                status="completed",
                finalization={"receipt": "original"},
            )
            event = uuid4()
            revision = await signal(
                conn,
                workspace_id=scope.workspace_id,
                generation_id=generation.generation_id,
                event_id=event,
                reason="initial_settled",
            )
            assert (
                await signal(
                    conn,
                    workspace_id=scope.workspace_id,
                    generation_id=generation.generation_id,
                    event_id=event,
                    reason="initial_settled",
                )
                == revision
            )
            assert len(await pending_continuations(conn)) == 1
            assert await reconcile_generation(
                conn,
                workspace_id=scope.workspace_id,
                generation_id=generation.generation_id,
                expected_revision=revision,
            )
            # Pending child is visible as provisional, not falsely called successful.
            assert (
                await read_generation(
                    conn, workspace_id=scope.workspace_id, generation_id=generation.generation_id
                )
            ).state == "provisional"
            assert not await pending_continuations(conn)
            await finish_seeded_job(
                conn,
                model_rounds=0,
                tool_calls=0,
                cost_usd=Decimal(0),
                credits=Decimal(0),
                media_seconds=0,
                job_id=child,
                status="needs_review",
                finalization={"gap": "employment_conflict"},
            )
            assert (
                await record_child_result(conn, workspace_id=scope.workspace_id, job_id=child) == 1
            )
            assert (
                await record_child_result(conn, workspace_id=scope.workspace_id, job_id=child) == 1
            )
            newest = await read_generation(
                conn, workspace_id=scope.workspace_id, generation_id=generation.generation_id
            )
            assert newest.input_revision == revision + 1
            assert not await reconcile_generation(
                conn,
                workspace_id=scope.workspace_id,
                generation_id=generation.generation_id,
                expected_revision=revision,
            )
            assert await reconcile_generation(
                conn,
                workspace_id=scope.workspace_id,
                generation_id=generation.generation_id,
                expected_revision=newest.input_revision,
            )
            assert (
                await read_generation(
                    conn, workspace_id=scope.workspace_id, generation_id=generation.generation_id
                )
            ).state == "partial"
            assert (
                await conn.execute(
                    text("SELECT finalization_json FROM arv2_research_job WHERE job_id=:id"),
                    {"id": scope.job_id},
                )
            ).scalar_one() == {"receipt": "original"}
            event = {"workspace_id": scope.workspace_id, "entity_id": contact, "event_id": uuid4()}
            await signal_subject_change(conn, event)
            await signal_subject_change(conn, event)
            assert len(await pending_continuations(conn)) == 1
            await conn.execute(
                text(
                    "UPDATE arv2_account_research_generation SET state='suspended' "
                    "WHERE generation_id=:id"
                ),
                {"id": generation.generation_id},
            )
            await signal_subject_change(conn, {**event, "event_id": uuid4()})
            assert not await pending_continuations(conn)
            with pytest.raises(ValueError):
                await read_generation(
                    conn, workspace_id="foreign", generation_id=generation.generation_id
                )

    run_async(case())


async def _waiting_account(
    conn, tmp_path, *, recipe=40, child_status="in_progress", idle_minutes=0, finish_parent=True
):
    """An account whose first turn settled at ``recipe``, with one person in ``child_status``."""
    op, scope, cid = await setup(conn, FsStorage(tmp_path))
    generation = await ensure_generation(conn, op, context_id=cid)
    contact = await insert_contact_entity(
        conn, account_entity_id=op.account_id, full_name="Fixture person"
    )
    child = uuid4()
    await create_job(
        conn,
        job_id=child,
        run_id=op.run_id,
        workspace_id=op.workspace_id,
        account_entity_id=op.account_id,
        subject_type="person",
        subject_entity_id=contact,
        profile_sha256="a" * 64,
        input_refs={"parent_job_id": str(op.job_id), "quality_recipe_version": recipe},
    )
    await register_child(conn, generation, job_id=child)
    await conn.execute(
        text("""UPDATE arv2_research_job SET status=:status, created_at=now()-interval '3 hours',
            started_at=CASE WHEN :status='not_started' THEN NULL
                ELSE now()-make_interval(mins=>:idle) END WHERE job_id=:job"""),
        {"status": child_status, "idle": idle_minutes, "job": child},
    )
    await conn.execute(
        text("""UPDATE arv2_research_job SET input_refs=COALESCE(input_refs,'{}'::jsonb)
            || jsonb_build_object('quality_recipe_version',CAST(:recipe AS int))
            WHERE job_id=:job"""),
        {"recipe": recipe, "job": op.job_id},
    )
    if not finish_parent:
        return op, scope, generation, child
    await finish_seeded_job(
        conn,
        model_rounds=0,
        tool_calls=0,
        cost_usd=Decimal(0),
        credits=Decimal(0),
        media_seconds=0,
        job_id=op.job_id,
        status="completed",
        finalization={"receipt": "original"},
    )
    await signal(
        conn,
        workspace_id=op.workspace_id,
        generation_id=generation.generation_id,
        event_id=uuid4(),
        reason="initial_settled",
    )
    return op, scope, generation, child


_STALL = timedelta(minutes=30)


def test_account_waits_for_person_in_progress(tmp_path):
    async def case():
        async with rollback_conn() as conn:
            await _waiting_account(conn, tmp_path, idle_minutes=29)
            assert not await pending_continuations(conn, stall_after=_STALL)

    run_async(case())


def test_account_stops_waiting_after_stall(tmp_path):
    async def case():
        async with rollback_conn() as conn:
            _, _, generation, child = await _waiting_account(conn, tmp_path, idle_minutes=31)
            pending = await pending_continuations(conn, stall_after=_STALL)
            assert [g.generation_id for g in pending] == [generation.generation_id]
            status = await conn.execute(
                text("SELECT status FROM arv2_research_job WHERE job_id=:job"), {"job": child}
            )
            assert status.scalar_one() == "in_progress"

    run_async(case())


def test_recent_activity_keeps_the_account_waiting(tmp_path):
    async def case():
        from clue_api.arv2.quality_execution import Allowance, bind_execution
        from clue_api.arv2.research_operations import OperationScope
        from tests.arv2.test_quality_execution_db import execution

        async with rollback_conn() as conn:
            op, scope, generation, child = await _waiting_account(conn, tmp_path, idle_minutes=120)
            cid = generation.context_id
            person = OperationScope(op.workspace_id, op.run_id, child, op.account_id)
            eid = await execution(conn, op, scope.project_id)
            await bind_execution(
                conn,
                person,
                execution_id=eid,
                context_id=cid,
                role="account_research",
                parent_execution_id=None,
                limits=Allowance(5, 5, 1),
            )
            await conn.execute(
                text("""INSERT INTO arv2_quality_activity
                    (activity_id,workspace_id,job_id,execution_id,kind,created_at)
                    VALUES (:id,:ws,:job,:execution,'tool',now()-interval '5 minutes')"""),
                {"id": uuid4(), "ws": op.workspace_id, "job": child, "execution": eid},
            )
            assert not await pending_continuations(conn, stall_after=_STALL)

    run_async(case())


def test_not_started_person_is_never_skipped(tmp_path):
    async def case():
        async with rollback_conn() as conn:
            await _waiting_account(conn, tmp_path, child_status="not_started")
            assert not await pending_continuations(conn, stall_after=_STALL)

    run_async(case())


def test_privacy_stopped_person_is_not_waited_for(tmp_path):
    async def case():
        async with rollback_conn() as conn:
            _, _, generation, child = await _waiting_account(conn, tmp_path, idle_minutes=1)
            await conn.execute(
                text("""UPDATE arv2_research_job SET
                    input_refs=input_refs||jsonb_build_object('privacy_stopped',true)
                    WHERE job_id=:job"""),
                {"job": child},
            )
            pending = await pending_continuations(conn, stall_after=_STALL)
            assert [g.generation_id for g in pending] == [generation.generation_id]

    run_async(case())


def test_recipe_39_ignores_stall(tmp_path):
    async def case():
        async with rollback_conn() as conn:
            await _waiting_account(conn, tmp_path, recipe=39, idle_minutes=31)
            assert not await pending_continuations(conn, stall_after=_STALL)

    run_async(case())


def _pages_handler():
    handler = Arv2AccountResearchWorkHandler.__new__(Arv2AccountResearchWorkHandler)
    handler._page_writer = None  # the writer must not be reached
    return handler


def _research_result():
    return QualityJobOutcome(
        status="completed",
        execution_id=uuid4(),
        finalization_key="fixture",
        report=ResearchUnitReport(context_id=uuid4(), job_id=uuid4(), summary="Fixture."),
        failure_code=None,
    )


def test_write_pages_defers_at_40(tmp_path):
    async def case():
        async with rollback_conn() as conn:
            _, scope, _ = await setup(conn, FsStorage(tmp_path))
        refs = {"quality_recipe_version": 40}
        account = replace(scope, catalog_version="v4", input_refs=refs)
        person = replace(
            scope,
            catalog_version="v4",
            input_refs={**refs, "parent_job_id": str(uuid4())},
            subject_kind="person",
            contact_id=uuid4(),
        )
        handler = _pages_handler()

        def composition(job_scope):
            return SimpleNamespace(scope=job_scope, run=SimpleNamespace(context_id=uuid4()))

        written = await handler._write_pages(composition(account), _research_result())
        assert written.deferred_pages == ("insights", "overview")
        assert written.status == "completed"
        written = await handler._write_pages(composition(person), _research_result())
        assert written.deferred_pages == ("contact",)
        assert written.status == "completed"

    run_async(case())
