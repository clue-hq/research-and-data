"""Real dossier imports, batch readiness, targeted publication, and durable recovery."""

from contextlib import asynccontextmanager
from dataclasses import replace
from decimal import Decimal
from uuid import uuid4

import pytest
from sqlalchemy import text

from clue_api.arv2.account_research_store import finish_job
from clue_api.arv2.display.recipes import load_display_recipes
from clue_api.arv2.quality_catalog import CURRENT_RECIPE_VERSION
from clue_api.arv2.quality_execution import Allowance, bind_execution
from clue_api.arv2.quality_generation import pending_continuations, read_generation, signal
from clue_api.arv2.quality_json_dossier import (
    DossierInput,
    FinishDossierTool,
    SaveDossierSectionTool,
    SaveSectionInput,
)
from clue_api.arv2.quality_owned_narrative import (
    ReadNarrativeInput,
    ReadNarrativeInputsTool,
    WriteResearchNarrativeTool,
)
from clue_api.arv2.quality_pages import read_page
from clue_api.arv2.quality_reconciliation import run_reconciliation
from clue_api.arv2.research_operations import OperationScope
from clue_core import ExecutionId, OperationId
from tests.arv2.test_dossier_json import finding
from tests.arv2.test_quality_execution_db import execution
from tests.arv2.test_quality_json_dossier_db import invoke
from tests.arv2.test_quality_owned_narrative_db import call, draft
from tests.arv2.test_quality_person_release_db import initial
from tests.claimstore.conftest import (  # noqa: F401
    migrated_db,
    require_claimstore_db,
    rollback_conn,
    run_async,
)

pytestmark = pytest.mark.usefixtures("require_claimstore_db")


async def fixture(conn, tmp_path):
    parent, child, cid, storage, ctx, gen, path = await initial(conn, tmp_path)
    parent = replace(parent, input_refs={"quality_recipe_version": 24})
    child = replace(child, input_refs={**child.input_refs, "quality_recipe_version": 24})
    await conn.execute(
        text(
            "UPDATE arv2_research_job SET input_refs=input_refs || "
            "jsonb_build_object('quality_recipe_version',24) WHERE job_id=ANY(:ids)"
        ),
        {"ids": [parent.job_id, child.job_id]},
    )
    await load_display_recipes(conn)
    await invoke(FinishDossierTool, parent, storage, ctx, DossierInput())
    meta = await call(ReadNarrativeInputsTool, parent, storage, ctx, ReadNarrativeInput())
    assert (await call(WriteResearchNarrativeTool, parent, storage, ctx, draft(meta)))[
        "status"
    ] == "published"
    await finish_job(
        conn,
        job_id=parent.job_id,
        status="completed",
        model_rounds=0,
        tool_calls=0,
        cost_usd=Decimal(0),
        credits=Decimal(0),
        media_seconds=0,
        finalization={"original": True},
    )
    rev = await signal(
        conn,
        workspace_id=parent.workspace_id,
        generation_id=gen.generation_id,
        event_id=uuid4(),
        reason="initial_settled",
    )
    assert not await pending_continuations(conn)  # person still researching, no import
    op = OperationScope(child.workspace_id, child.run_id, child.job_id, child.account_id)
    eid = await execution(conn, op, child.project_id)
    await bind_execution(
        conn,
        op,
        execution_id=eid,
        context_id=cid,
        role="account_research",
        limits=Allowance(100, 100, 10),
    )
    pc = replace(ctx, execution_id=ExecutionId(eid), operation_id=OperationId(uuid4()))
    await invoke(
        SaveDossierSectionTool,
        child,
        storage,
        pc,
        SaveSectionInput(section="Public voice", findings=[finding(source_paths=[path])]),
    )
    await invoke(FinishDossierTool, child, storage, pc, DossierInput())
    assert len(await pending_continuations(conn)) == 1  # no person narrative/finalize required
    return parent, child, cid, storage, gen, rev, pc


def test_focused_update_no_claim_copy_and_advance_snapshot_with_new_inputs(tmp_path):
    async def case():
        async with rollback_conn() as conn:
            parent, child, cid, storage, gen, rev, pc = await fixture(conn, tmp_path)
            meta = await call(ReadNarrativeInputsTool, child, storage, pc, ReadNarrativeInput())
            await call(WriteResearchNarrativeTool, child, storage, pc, draft(meta, True))
            claims_before = (
                await conn.execute(
                    text("SELECT count(*) FROM claim WHERE workspace_id=:ws"),
                    {"ws": parent.workspace_id},
                )
            ).scalar_one()
            blocks_before = dict(
                (
                    await conn.execute(
                        text(
                            "SELECT section_key,display_block_id FROM display_block "
                            "WHERE subject_id=:id AND superseded_at IS NULL"
                        ),
                        {"id": parent.account_id},
                    )
                ).all()
            )
            calls = []

            @asynccontextmanager
            async def connections():
                async with conn.begin_nested():
                    yield conn

            async def generate(packet):
                calls.append(packet)
                own = next(c for c in packet["claims"] if c["entity_id"] == str(child.contact_id))
                # A later input arrives while this snapshot is being processed.
                await signal(
                    conn,
                    workspace_id=parent.workspace_id,
                    generation_id=gen.generation_id,
                    event_id=uuid4(),
                    reason="person_result",
                )
                return {
                    "updates": [
                        {
                            "page": "overview",
                            "section": {
                                "key": "why-they-fit",
                                "intro": [
                                    {
                                        "text": "Their own public statement matters.",
                                        "claimIds": [own["id"]],
                                    }
                                ],
                            },
                        }
                    ]
                }

            args = {
                "conn_factory": connections,
                "storage": storage,
                "scope": parent,
                "context_id": cid,
                "generation_id": gen.generation_id,
                "revision": rev,
                "generate": generate,
                "model": "offline-editor",
                "stopped": lambda: False,
            }
            out = await run_reconciliation(**args)
            assert out["updated_sections"] == 1 and len(calls) == 1
            current = await read_generation(
                conn, workspace_id=parent.workspace_id, generation_id=gen.generation_id
            )
            assert current.reconciled_revision == rev and current.input_revision > rev
            assert (await run_reconciliation(**args))["replayed"] and len(calls) == 1
            assert (
                await conn.execute(
                    text("SELECT count(*) FROM claim WHERE workspace_id=:ws"),
                    {"ws": parent.workspace_id},
                )
            ).scalar_one() == claims_before
            blocks_after = dict(
                (
                    await conn.execute(
                        text(
                            "SELECT section_key,display_block_id FROM display_block "
                            "WHERE subject_id=:id AND superseded_at IS NULL"
                        ),
                        {"id": parent.account_id},
                    )
                ).all()
            )
            assert blocks_before["why-they-fit"] != blocks_after["why-they-fit"]
            assert all(
                blocks_before[k] == blocks_after[k] for k in blocks_before if k != "why-they-fit"
            )
            contact = await read_page(conn, child, context_id=cid, page="contact")
            assert not contact["stale"]  # account narrative update isn't new person evidence
            # Status-only signal has no changed evidence: settles without another model call.
            await run_reconciliation(**{**args, "revision": current.input_revision})
            assert len(calls) == 1
            assert not await pending_continuations(conn)

    run_async(case())


def test_generated_response_replay_survives_publication_failure(tmp_path, monkeypatch):
    async def case():
        async with rollback_conn() as conn:
            parent, child, cid, storage, gen, rev, _ = await fixture(conn, tmp_path)

            @asynccontextmanager
            async def connections():
                async with conn.begin_nested():
                    yield conn

            calls = []

            async def generate(packet):
                calls.append(1)
                id = packet["changed"][0]
                return {
                    "updates": [
                        {
                            "page": "overview",
                            "section": {
                                "key": "why-they-fit",
                                "intro": [{"text": "Preserved evidence", "claimIds": [id]}],
                            },
                        }
                    ]
                }

            args = {
                "conn_factory": connections,
                "storage": storage,
                "scope": parent,
                "context_id": cid,
                "generation_id": gen.generation_id,
                "revision": rev,
                "generate": generate,
                "model": "offline-editor",
                "stopped": lambda: False,
            }
            import clue_api.arv2.quality_reconciliation as module

            async def fail(*a, **kw):
                raise ValueError("injected publication failure")

            with monkeypatch.context() as patch:
                patch.setattr(module, "publish_page", fail)
                with pytest.raises(ValueError, match="injected"):
                    await run_reconciliation(**args)
            assert (
                await conn.execute(
                    text("SELECT state FROM arv2_narrative_reconciliation WHERE generation_id=:id"),
                    {"id": gen.generation_id},
                )
            ).scalar_one() == "generated"
            await run_reconciliation(**args)
            assert len(calls) == 1

    run_async(case())


@pytest.mark.parametrize("race", ["claim", "section", "erasure"])
def test_changed_inputs_cannot_publish_stale_output(tmp_path, race):
    async def case():
        async with rollback_conn() as conn:
            parent, child, cid, storage, gen, rev, _ = await fixture(conn, tmp_path)

            @asynccontextmanager
            async def connections():
                async with conn.begin_nested():
                    yield conn

            async def generate(packet):
                own = next(c for c in packet["claims"] if c["entity_id"] == str(child.contact_id))
                if race == "claim":
                    # A correction has committed while the editor is generating.
                    from clue_research.claimstore.quality import assess_claim

                    claim = (
                        await conn.execute(
                            text("""SELECT c.id,c.artifact_key,q.revision
                        FROM claim c JOIN claim_quality_current q ON q.claim_id=c.id
                        WHERE c.workspace_id=:ws AND c.entity_id=:person LIMIT 1"""),
                            {"ws": parent.workspace_id, "person": child.contact_id},
                        )
                    ).one()
                    await assess_claim(
                        conn,
                        workspace_id=parent.workspace_id,
                        entity_id=child.contact_id,
                        claim_id=claim.id,
                        operation_id=uuid4(),
                        expected_revision=claim.revision,
                        conclusion="invalid",
                        actor_ref="test-reviewer",
                        kind="withdrawal",
                        context_id=cid,
                        rationale_key=claim.artifact_key,
                        support_artifacts=(claim.artifact_key,),
                    )
                elif race == "section":
                    await conn.execute(
                        text("""UPDATE display_block SET superseded_at=now()
                        WHERE subject_id=:account AND section_key='why-they-fit'"""),
                        {"account": parent.account_id},
                    )
                else:
                    await conn.execute(
                        text("""UPDATE artifact SET erased_at=now()
                        WHERE storage_key IN (SELECT packet_key FROM arv2_narrative_reconciliation
                          WHERE generation_id=:generation)"""),
                        {"generation": gen.generation_id},
                    )
                return {
                    "updates": [
                        {
                            "page": "overview",
                            "section": {
                                "key": "why-they-fit",
                                "intro": [{"text": "Must not publish", "claimIds": [own["id"]]}],
                            },
                        }
                    ]
                }

            with pytest.raises(Exception, match="changed|unavailable|erased|Erased"):
                await run_reconciliation(
                    conn_factory=connections,
                    storage=storage,
                    scope=parent,
                    context_id=cid,
                    generation_id=gen.generation_id,
                    revision=rev,
                    generate=generate,
                    model="offline-editor",
                    stopped=lambda: False,
                )
            assert not (
                await conn.execute(
                    text("""SELECT EXISTS(SELECT 1 FROM display_block
                WHERE subject_id=:account AND body_json::text LIKE '%Must not publish%')"""),
                    {"account": parent.account_id},
                )
            ).scalar_one()
            current = await read_generation(
                conn, workspace_id=parent.workspace_id, generation_id=gen.generation_id
            )
            assert current.reconciled_revision < rev

    run_async(case())


def test_batch_waits_for_all_imports_or_failures_and_scope_is_enforced(tmp_path):
    async def case():
        from clue_api.arv2.quality_reconciliation import prepare, read_payload
        from tests.arv2.test_quality_person_release_db import child_job

        async with rollback_conn() as conn:
            parent, child, cid, storage, gen, rev, _ = await fixture(conn, tmp_path)
            late = await child_job(conn, storage, parent, cid, gen, version=24)
            assert not await pending_continuations(conn)
            with pytest.raises(ValueError, match="not ready"):
                await prepare(conn, storage, parent, cid, gen.generation_id, rev)
            await finish_job(
                conn,
                job_id=late.job_id,
                status="needs_review",
                model_rounds=0,
                tool_calls=0,
                cost_usd=Decimal(0),
                credits=Decimal(0),
                media_seconds=0,
                finalization={"reason": "test failure"},
            )
            assert await pending_continuations(conn)
            with pytest.raises(ValueError, match="scope"):
                await prepare(conn, storage, parent, uuid4(), gen.generation_id, rev)
            row = await prepare(conn, storage, parent, cid, gen.generation_id, rev)
            packet = await read_payload(conn, storage, parent.workspace_id, row["packet_key"])
            assert packet["input"]["_editorial_system"]
            people = packet["input"]["people"]
            assert len(people) == 2
            assert all(p["delegation"] for p in people)
            assert any(p["job_status"] == "needs_review" for p in people)
            # Exact input and aliases are reused without reassembly.
            assert (await prepare(conn, storage, parent, cid, gen.generation_id, rev))[
                "packet_key"
            ] == row["packet_key"]

    run_async(case())


@pytest.mark.parametrize("bad_lease", [False, True])
def test_fleet_routes_to_editor_and_fences_lease(tmp_path, bad_lease, monkeypatch):
    from unittest.mock import AsyncMock

    monkeypatch.setattr(
        "clue_api.arv2.quality_reconciliation.account_research_model",
        AsyncMock(return_value="original-account-model"),
    )

    async def case():
        import asyncio
        from types import SimpleNamespace
        from unittest.mock import AsyncMock

        from clue_api.arv2 import account_research_store
        from clue_api.arv2.account_research_driver import Arv2AccountResearchWorkHandler
        from clue_api.arv2.quality_generation import continuation_work_id
        from clue_fleet.lease import LeaseGeneration, WorkId, acquire_work_lease
        from clue_fleet.work_worker import WorkContext

        async with rollback_conn() as conn:
            parent, _, cid, storage, gen, rev, _ = await fixture(conn, tmp_path)
            wid = WorkId(continuation_work_id(gen))
            assert wid == continuation_work_id(replace(gen, generation_id=uuid4()))
            assert await acquire_work_lease(conn, work_id=wid, worker_id="editor")
            assert await acquire_work_lease(conn, work_id=wid, worker_id="competing-editor") is None
            context = WorkContext(
                task_id=uuid4(),
                work_id=wid,
                worker_id="editor",
                lease_generation=LeaseGeneration(2 if bad_lease else 1),
                payload={
                    "workspace_id": parent.workspace_id,
                    "generation_id": str(gen.generation_id),
                    "input_revision": rev,
                },
                stop_requested=asyncio.Event(),
                lease_lost=asyncio.Event(),
            )

            @asynccontextmanager
            async def connections():
                async with conn.begin_nested():
                    yield conn

            composition = SimpleNamespace(
                scope=parent, run=SimpleNamespace(context_id=cid), model_id="original-account-model"
            )
            researcher = AsyncMock(
                return_value=SimpleNamespace(reconciliation_reply={"updates": []})
            )
            handler = SimpleNamespace(
                _connection=connections,
                _storage=storage,
                _store=account_research_store,
                _compose_quality=AsyncMock(return_value=composition),
                _tool_runtime=lambda composition: None,
                _quality_runner=researcher,
                _jobs=asyncio.Semaphore(1),
                _settings=SimpleNamespace(arv2_display_model="offline"),
            )
            handler._focused_reconciliation = lambda *args: (
                Arv2AccountResearchWorkHandler._focused_reconciliation(handler, *args)
            )
            if not bad_lease:
                from clue_api.arv2.quality_reconciliation import prepare

                await prepare(conn, storage, parent, cid, gen.generation_id, rev)
                await signal(
                    conn,
                    workspace_id=parent.workspace_id,
                    generation_id=gen.generation_id,
                    event_id=uuid4(),
                    reason="person_result",
                )
            if bad_lease:
                with pytest.raises(asyncio.CancelledError):
                    await Arv2AccountResearchWorkHandler._quality_continuation(handler, context)
                researcher.assert_not_awaited()
            else:
                result = await Arv2AccountResearchWorkHandler._quality_continuation(
                    handler, context
                )
                assert result.outcome == "completed"
                researcher.assert_awaited_once()
                again = await Arv2AccountResearchWorkHandler._quality_continuation(handler, context)
                assert again.references["superseded"]
                researcher.assert_awaited_once()
            if not bad_lease:
                args = researcher.await_args.kwargs
                assert args["model_id"] == "original-account-model"
                assert args["reconciliation"]["_validation_packet"]
                assert args["unit_key"].startswith("reconcile:")

    run_async(case())


def test_noop_does_not_certify_missing_original_account_pages(tmp_path):
    async def case():
        async with rollback_conn() as conn:
            parent, _, cid, storage, gen, rev, _ = await fixture(conn, tmp_path)
            await conn.execute(
                text("""UPDATE display_block SET superseded_at=now()
                WHERE subject_id=:subject"""),
                {"subject": parent.account_id},
            )

            @asynccontextmanager
            async def connections():
                async with conn.begin_nested():
                    yield conn

            async def generate(packet):
                return {"updates": []}

            out = await run_reconciliation(
                conn_factory=connections,
                storage=storage,
                scope=parent,
                context_id=cid,
                generation_id=gen.generation_id,
                revision=rev,
                generate=generate,
                model="offline",
                stopped=lambda: False,
            )
            assert out["updated_sections"] == 0 and out["response_key"]
            result = await read_generation(
                conn, workspace_id=parent.workspace_id, generation_id=gen.generation_id
            )
            assert result.state == "needs_review" and result.reconciled_revision == rev
            assert not await pending_continuations(conn)

    run_async(case())


def test_real_launch_persists_resolved_recipe_for_scheduler(tmp_path):
    async def case():
        from datetime import UTC, datetime

        from clue_api.arv2.account_research_catalog import arv2_account_profile_sha256
        from clue_api.arv2.account_research_driver import Arv2AccountResearchWorkHandler
        from clue_api.arv2.account_research_launch import launch_arv2_account_research
        from clue_api.arv2.account_research_store import read_job, read_run
        from clue_storage.fs import FsStorage
        from tests.arv2.icp_fixture import seed_icp_fixture, settings_for
        from tests.arv2.test_account_research_launch_db import _request

        async with rollback_conn() as conn:
            storage = FsStorage(tmp_path / "blobs")
            fixture_data = await seed_icp_fixture(conn, storage)
            launch = await launch_arv2_account_research(
                conn,
                _request(fixture_data, account_entity_ids=(fixture_data.accounts[0],)),
                settings=settings_for(arv2_account_research_enabled=True),
                storage=storage,
                profile_sha256=arv2_account_profile_sha256(version="v4"),
            )
            job = await read_job(conn, job_id=launch.job_ids[0])
            run = await read_run(conn, run_id=launch.run_id)
            assert "quality_recipe_version" not in job.input_refs
            owner = object.__new__(Arv2AccountResearchWorkHandler)
            owner._storage = storage
            owner._clock = lambda: datetime.now(UTC)
            owner._model_id = owner._person_model_id = "unused"
            composition = await owner._compose_quality(conn, job, run)
            persisted = await read_job(conn, job_id=job.job_id)
            assert persisted.input_refs["quality_recipe_version"] == CURRENT_RECIPE_VERSION
            assert persisted.input_refs == composition.scope.input_refs

    run_async(case())
