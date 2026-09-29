"""Durable revisions survive duplicates, late people and stale reconciliation."""

from decimal import Decimal
from uuid import uuid4

import pytest
from sqlalchemy import text

from clue_api.arv2.account_research_store import create_job, finish_job
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
from clue_research.identity import insert_contact_entity
from clue_storage.fs import FsStorage
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
            await finish_job(
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
            await finish_job(
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
