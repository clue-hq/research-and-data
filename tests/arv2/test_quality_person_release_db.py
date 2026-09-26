"""Committed imports release person work while the account is still running; no providers."""

import json
from contextlib import asynccontextmanager
from dataclasses import replace
from decimal import Decimal
from uuid import uuid4

import pytest
from sqlalchemy import text

from clue_api.arv2.account_research_store import create_job, finish_job
from clue_api.arv2.person_research_brief import read_person_brief, save_person_brief
from clue_api.arv2.quality_generation import ensure_generation, register_child, signal
from clue_api.arv2.quality_json_dossier import (
    BeginDossierRevisionTool,
    BeginRevisionInput,
    DossierInput,
    FinishDossierTool,
    SaveDossierSectionTool,
    SaveSectionInput,
    read_json_dossier,
)
from clue_api.arv2.quality_person_release import (
    PARENT_DOSSIER_PATH,
    READY_KIND,
    read_parent_dossier,
    ready_person_jobs,
)
from clue_api.arv2.research_operations import OperationScope
from clue_research.identity import insert_contact_entity
from tests.arv2.test_dossier_json import finding
from tests.arv2.test_quality_json_dossier_db import invoke, prepare
from tests.claimstore.conftest import (  # noqa: F401
    migrated_db,
    require_claimstore_db,
    rollback_conn,
    run_async,
)

pytestmark = pytest.mark.usefixtures("require_claimstore_db")


async def child_job(conn, storage, parent, cid, generation, version=18):
    contact = await insert_contact_entity(
        conn, account_entity_id=parent.account_id, full_name="Fixture researcher"
    )
    jid = uuid4()
    # Use production order: create the brief artifact before the person-job row.
    brief = await save_person_brief(
        conn,
        storage,
        parent,
        context_id=cid,
        person_job_id=jid,
        contact_id=contact,
        brief="Investigate the selected person's public voice.",
    )
    refs = {
        "parent_job_id": str(parent.job_id),
        "quality_recipe_version": version,
        "person_research_brief": brief,
    }
    await create_job(
        conn,
        job_id=jid,
        run_id=parent.run_id,
        workspace_id=parent.workspace_id,
        account_entity_id=parent.account_id,
        subject_type="person",
        subject_entity_id=contact,
        profile_sha256="a" * 64,
        input_refs=refs,
    )
    await register_child(conn, generation, job_id=jid)
    return replace(parent, job_id=jid, subject_kind="person", contact_id=contact, input_refs=refs)


async def initial(conn, tmp_path):
    parent, cid, storage, ctx, backend, path = await prepare(conn, tmp_path)
    parent = replace(parent, input_refs={"quality_recipe_version": 18})
    await conn.execute(
        text("UPDATE arv2_research_job SET status='in_progress' WHERE job_id=:id"),
        {"id": parent.job_id},
    )
    gen = await ensure_generation(
        conn,
        OperationScope(parent.workspace_id, parent.run_id, parent.job_id, parent.account_id),
        context_id=cid,
    )
    child = await child_job(conn, storage, parent, cid, gen)
    await invoke(
        SaveDossierSectionTool,
        parent,
        storage,
        ctx,
        SaveSectionInput(section="Voice", findings=[finding(source_paths=[path])]),
    )
    return parent, child, cid, storage, ctx, gen, path


def test_ready_before_account_settlement_and_published_parent_view(tmp_path):
    async def case():
        async with rollback_conn() as conn:
            parent, child, cid, storage, ctx, gen, path = await initial(conn, tmp_path)
            assert not await ready_person_jobs(conn)
            with pytest.raises(ValueError, match="no available completed"):
                await read_parent_dossier(conn, storage, child, cid)
            result = await invoke(FinishDossierTool, parent, storage, ctx, DossierInput())
            assert result["finished"]
            assert {r["job_id"] for r in await ready_person_jobs(conn)} == {child.job_id}
            assert (
                await conn.execute(
                    text("SELECT status FROM arv2_research_job WHERE job_id=:id"),
                    {"id": parent.job_id},
                )
            ).scalar_one() == "in_progress"
            assert (
                await conn.execute(
                    text(
                        "SELECT initial_settled_at FROM arv2_account_research_generation "
                        "WHERE generation_id=:id"
                    ),
                    {"id": gen.generation_id},
                )
            ).scalar_one() is None
            body = await read_parent_dossier(conn, storage, child, cid)
            assert body["read_only"] and body["path"] == PARENT_DOSSIER_PATH
            assert body["receipt"]["entries"][0]["claim_id"] == result["claim_ids"][0]
            assert (await read_person_brief(conn, storage, child, context_id=cid))["brief"]
            # A later draft is not exposed as the completed account dossier.
            saved = await read_json_dossier(conn, storage, parent, cid)
            await invoke(
                BeginDossierRevisionTool,
                parent,
                storage,
                ctx,
                BeginRevisionInput(expected_version=saved["version"], reason="New source"),
            )
            await invoke(
                SaveDossierSectionTool,
                parent,
                storage,
                ctx,
                SaveSectionInput(
                    section="Voice", findings=[finding(source_paths=[path], finding="Draft only")]
                ),
            )
            assert (await read_parent_dossier(conn, storage, child, cid))["document"] == body[
                "document"
            ]
            # A late nomination picks up the same readiness without waiting for settlement.
            second = await child_job(conn, storage, parent, cid, gen)
            assert {r["job_id"] for r in await ready_person_jobs(conn)} == {
                child.job_id,
                second.job_id,
            }
            # Narrative/account failure after import does not withhold the children.
            await finish_job(
                conn,
                job_id=parent.job_id,
                status="needs_review",
                failure_code="narrative_failed",
                finalization={"gap": "narrative"},
                model_rounds=0,
                tool_calls=0,
                cost_usd=Decimal(0),
                credits=Decimal(0),
                media_seconds=0,
            )
            assert len(await ready_person_jobs(conn)) == 2
            for bad in (
                replace(child, workspace_id="foreign"),
                replace(child, account_id=uuid4()),
                replace(child, contact_id=uuid4()),
            ):
                with pytest.raises(ValueError):
                    await read_parent_dossier(conn, storage, bad, cid)
            with pytest.raises(ValueError):
                await read_parent_dossier(conn, storage, child, uuid4())
            await conn.execute(
                text(
                    "UPDATE arv2_account_research_generation SET state='suspended' "
                    "WHERE generation_id=:id"
                ),
                {"id": gen.generation_id},
            )
            assert not await ready_person_jobs(conn)

    run_async(case())


def test_import_rollback_partial_failure_and_terminal_failure_do_not_release(tmp_path, monkeypatch):
    from clue_api.arv2 import dossier_import

    async def case():
        async with rollback_conn() as conn:
            parent, child, cid, storage, ctx, gen, path = await initial(conn, tmp_path)
            write = dossier_import.submit_proposal

            async def failed(*args, **kwargs):
                raise ValueError("Injected claim failure")

            monkeypatch.setattr(dossier_import, "submit_proposal", failed)
            result = await invoke(FinishDossierTool, parent, storage, ctx, DossierInput())
            assert not result["finished"] and not await ready_person_jobs(conn)
            # Even settlement cannot bypass the required import on new recipe jobs.
            await signal(
                conn,
                workspace_id=parent.workspace_id,
                generation_id=gen.generation_id,
                event_id=uuid4(),
                reason="initial_settled",
            )
            assert not await ready_person_jobs(conn)
            monkeypatch.setattr(dossier_import, "submit_proposal", write)
            transaction = await conn.begin_nested()
            assert (await invoke(FinishDossierTool, parent, storage, ctx, DossierInput()))[
                "finished"
            ]
            assert await ready_person_jobs(conn)
            await transaction.rollback()
            assert not await ready_person_jobs(conn)  # Readiness rolls back with claims/dossier.
            assert (await invoke(FinishDossierTool, parent, storage, ctx, DossierInput()))[
                "finished"
            ]
            marker_count = (
                await conn.execute(
                    text("SELECT count(*) FROM artifact_reference WHERE reference_kind=:kind"),
                    {"kind": READY_KIND},
                )
            ).scalar_one()
            await invoke(FinishDossierTool, parent, storage, ctx, DossierInput())
            assert (
                await conn.execute(
                    text("SELECT count(*) FROM artifact_reference WHERE reference_kind=:kind"),
                    {"kind": READY_KIND},
                )
            ).scalar_one() == marker_count
            await conn.execute(
                text(
                    "UPDATE arv2_research_job SET input_refs=input_refs || CAST(:refs AS jsonb) "
                    "WHERE job_id=:id"
                ),
                {"refs": json.dumps({"privacy_stopped": True}), "id": child.job_id},
            )
            assert not await ready_person_jobs(conn)

    run_async(case())


def test_historical_children_keep_settlement_boundary(tmp_path):
    async def case():
        async with rollback_conn() as conn:
            parent, child, cid, storage, ctx, gen, path = await initial(conn, tmp_path)
            old = await child_job(conn, storage, parent, cid, gen, version=17)
            assert not await ready_person_jobs(conn)
            await signal(
                conn,
                workspace_id=parent.workspace_id,
                generation_id=gen.generation_id,
                event_id=uuid4(),
                reason="initial_settled",
            )
            assert [r["job_id"] for r in await ready_person_jobs(conn)] == [old.job_id]

    run_async(case())


def test_sweep_recovers_import_offer_and_child_finishes_before_parent(tmp_path):
    from clue_api.agent_turn_wiring import DurableAgentArtifactStore
    from clue_api.arv2.account_research_driver import Arv2AccountResearchWorkHandler
    from clue_api.arv2.claim_writer import LenientClaimWriter
    from clue_api.arv2.quality_generation import pending_continuations
    from tests.arv2.icp_fixture import settings_for
    from tests.arv2.test_account_research_driver_db import _Clients
    from tests.arv2.test_quality_driver_db import Queue

    async def case():
        async with rollback_conn() as conn:
            parent, child, cid, storage, ctx, gen, path = await initial(conn, tmp_path)

            @asynccontextmanager
            async def connections():
                async with conn.begin_nested():
                    yield conn

            async def no_model(**kwargs):
                raise AssertionError("No model or provider needed to recover the offer")

            queue = Queue()

            def handler():
                return Arv2AccountResearchWorkHandler(
                    settings=settings_for(),
                    conn_factory=connections,
                    artifacts=DurableAgentArtifactStore(storage=storage, conn_factory=connections),
                    storage=storage,
                    clients=_Clients(),
                    model_provider=None,
                    model_id="fixture/research",
                    writer=LenientClaimWriter(lenient=True),
                    quality_runner=no_model,
                    queue=queue,
                )

            assert await handler().sweep_quality() == 0
            await invoke(FinishDossierTool, parent, storage, ctx, DossierInput())
            # No in-memory completion callback: a fresh handler recovers the durable marker.
            assert await handler().sweep_quality() == 1
            assert await handler().sweep_quality() == 0
            offer = next(iter(queue.offers.values()))
            assert offer["payload"]["job_id"] == str(child.job_id)
            assert "continuation" not in offer["payload"]
            await finish_job(
                conn,
                job_id=child.job_id,
                status="completed",
                finalization={"done": True},
                model_rounds=0,
                tool_calls=0,
                cost_usd=Decimal(0),
                credits=Decimal(0),
                media_seconds=0,
            )
            assert await handler().sweep_quality() == 0
            assert not await pending_continuations(conn)
            assert (
                await conn.execute(
                    text("SELECT terminal_status FROM arv2_generation_child WHERE job_id=:id"),
                    {"id": child.job_id},
                )
            ).scalar_one() == "completed"

    run_async(case())


def test_person_workspace_exposes_parent_dossier_and_rejects_writes(tmp_path):
    from deepagents.backends.protocol import BackendProtocol

    from clue_api.arv2.person_research_brief import person_task_instruction
    from clue_api.arv2.quality_execution import Allowance, bind_execution
    from clue_api.arv2.quality_views import research_backend
    from tests.arv2.test_quality_execution_db import execution
    from tests.arv2.test_quality_tools_db import read

    async def case():
        async with rollback_conn() as conn:
            parent, child, cid, storage, ctx, gen, path = await initial(conn, tmp_path)
            await invoke(FinishDossierTool, parent, storage, ctx, DossierInput())
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

            @asynccontextmanager
            async def connections():
                yield conn

            backend = research_backend(BackendProtocol(), connections, storage, child, eid)
            context = await read(backend, "/research/context.json")
            assert context["account_research_references"]["dossier"] == PARENT_DOSSIER_PATH
            assert (await read(backend, PARENT_DOSSIER_PATH))["receipt"]["complete"]
            assert (await backend.awrite(PARENT_DOSSIER_PATH, "modified")).error
            assert (await backend.aedit(PARENT_DOSSIER_PATH, "Voice", "Changed")).error
            brief = await read_person_brief(conn, storage, child, context_id=cid)
            assert PARENT_DOSSIER_PATH in person_task_instruction(
                brief, account_dossier_available=True
            )
            assert PARENT_DOSSIER_PATH not in person_task_instruction(brief)

    run_async(case())
