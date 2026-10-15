"""Real governed researcher tools, durable drafts, exact import and restart recovery."""

import json
from contextlib import asynccontextmanager
from dataclasses import replace
from uuid import UUID, uuid4

import pytest
from deepagents.backends.protocol import BackendProtocol
from sqlalchemy import text

from clue_api.arv2 import dossier_import
from clue_api.arv2.account_research_store import create_job
from clue_api.arv2.quality_execution import Allowance, bind_execution
from clue_api.arv2.quality_json_dossier import (
    DossierInput,
    DossierReceipt,
    FinishDossierTool,
    SaveDossierSectionTool,
    SaveSectionInput,
    UpdateDossierFindingsTool,
    ValidateDossierTool,
    read_json_dossier,
    validate_dossier_handoff,
)
from clue_api.arv2.quality_views import research_backend
from clue_api.arv2.research_operations import OperationScope
from clue_core import ExecutionId, OperationId
from clue_research.identity import insert_contact_entity
from clue_storage import read_verified_artifact
from clue_storage.fs import FsStorage
from clue_toolbelt import ToolContext
from tests.arv2.test_dossier_json import finding
from tests.arv2.test_quality_claims_db import setup
from tests.arv2.test_quality_evidence_db import save
from tests.arv2.test_quality_execution_db import execution
from tests.arv2.test_quality_path_tools_db import read
from tests.claimstore.conftest import (  # noqa: F401
    migrated_db,
    require_claimstore_db,
    rollback_conn,
    run_async,
)

pytestmark = pytest.mark.usefixtures("require_claimstore_db")


async def prepare(conn, tmp_path, person=False):
    storage = FsStorage(tmp_path)
    op, job, cid = await setup(conn, storage)
    job = replace(job, catalog_version="v4", input_refs={"quality_recipe_version": 16})
    if person:
        contact = await insert_contact_entity(
            conn, account_entity_id=job.account_id, full_name="Maya Fixture"
        )
        jid = uuid4()
        await create_job(
            conn,
            job_id=jid,
            run_id=job.run_id,
            workspace_id=job.workspace_id,
            account_entity_id=job.account_id,
            subject_type="person",
            subject_entity_id=contact,
            profile_sha256="a" * 64,
        )
        job = replace(job, job_id=jid, subject_kind="person", contact_id=contact)
        op = OperationScope(job.workspace_id, job.run_id, jid, job.account_id)
    await save(conn, storage, op, "“No — keep A | B.”\nA second line.")
    eid = await execution(conn, op, job.project_id)
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

    ctx = ToolContext(
        workspace_id=job.workspace_id,
        actor="agent",
        conn_factory=connections,
        operation_id=OperationId(uuid4()),
        execution_id=ExecutionId(eid),
    )
    backend = research_backend(BackendProtocol(), connections, storage, job, eid)
    index = await read(backend, "/evidence/index.json")
    path = index["sources"][0]["path"]
    return job, cid, storage, ctx, backend, path


async def invoke(tool_type, job, storage, ctx, args):
    result = await tool_type(job, storage, purge_unevidenced=False).invoke(args, ctx)
    # The actual C5 output contract must accept all nested receipts/IDs.
    return DossierReceipt.model_validate(result.references).result


@pytest.mark.parametrize("person", [False, True])
def test_targeted_updates_preserve_omissions_import_exactly_and_freeze(tmp_path, person):
    async def case():
        async with rollback_conn() as conn:
            job, cid, storage, ctx, backend, path = await prepare(conn, tmp_path, person)
            job = replace(job, input_refs={"quality_recipe_version": 24})
            first, second = finding(source_paths=[path]), finding("F002", source_paths=[path])
            args = SaveSectionInput(section="Voice", findings=[first, second])
            await invoke(SaveDossierSectionTool, job, storage, ctx, args)
            corrected = {**first, "finding": "Corrected quotation, unchanged attribution."}
            patch = SaveSectionInput(section="Voice", findings=[corrected])
            receipt = await invoke(UpdateDossierFindingsTool, job, storage, ctx, patch)
            repeated = await invoke(UpdateDossierFindingsTool, job, storage, ctx, patch)
            assert repeated["version"] == receipt["version"]
            saved = await read_json_dossier(conn, storage, job, cid)
            entries = saved["document"]["sections"][0]["findings"]
            assert entries[0]["finding"] == corrected["finding"]
            assert entries[1] == args.findings[1].model_dump(mode="json")
            check = await invoke(ValidateDossierTool, job, storage, ctx, DossierInput())
            assert check["valid"] and check["coverage"]["findings"] == 2
            assert check["coverage"]["referenced_source_records"] == 1
            await invoke(FinishDossierTool, job, storage, ctx, DossierInput())
            saved = await read_json_dossier(conn, storage, job, cid)
            assert saved["receipt"]["complete"] and saved["receipt"]["stored"] == 2
            refused = await invoke(UpdateDossierFindingsTool, job, storage, ctx, patch)
            assert not refused["saved"] and "frozen" in refused["error"].lower()

    run_async(case())


@pytest.mark.parametrize("person", [False, True])
def test_section_save_restart_exact_import_and_frozen_replay(tmp_path, person):
    async def case():
        async with rollback_conn() as conn:
            job, cid, storage, ctx, backend, path = await prepare(conn, tmp_path, person)
            entry = finding(source_paths=[path])
            linked = finding(
                "F002",
                source_paths=[path],
                review={
                    "status": "potential_conflict",
                    "reason": "Dates unclear",
                    "conflicts_with": ["F001"],
                },
            )
            # Forward references do not prevent incremental authoring.
            first = await invoke(
                SaveDossierSectionTool,
                job,
                storage,
                ctx,
                SaveSectionInput(section="Later statement", findings=[linked]),
            )
            assert first["saved"]
            assert not (await invoke(ValidateDossierTool, job, storage, ctx, DossierInput()))[
                "valid"
            ]
            assert not (await invoke(FinishDossierTool, job, storage, ctx, DossierInput()))[
                "finished"
            ]
            with pytest.raises(ValueError, match="Finish the JSON"):
                await validate_dossier_handoff(conn, storage, job, cid, ())
            await invoke(
                SaveDossierSectionTool,
                job,
                storage,
                ctx,
                SaveSectionInput(section="Public voice", findings=[entry]),
            )
            saved = await read(backend, "/research/dossier/latest.json")
            assert len(saved["document"]["sections"]) == 2
            assert (await backend.als("/research/dossier/")).entries
            rawref = saved["document_artifact_key"]
            _, raw = await read_verified_artifact(
                conn, storage, workspace_id=job.workspace_id, storage_key=rawref
            )
            assert json.loads(raw) == saved["document"]
            # Unknown sources and duplicate IDs leave the previously saved document intact.
            bad = await invoke(
                SaveDossierSectionTool,
                job,
                storage,
                ctx,
                SaveSectionInput(
                    section="Other", findings=[finding("F003", source_paths=["/evidence/no"])]
                ),
            )
            assert not bad["saved"]
            duplicate = await invoke(
                SaveDossierSectionTool,
                job,
                storage,
                ctx,
                SaveSectionInput(section="Other", findings=[entry]),
            )
            assert not duplicate["saved"]
            assert (await read_json_dossier(conn, storage, job, cid))["version"] == saved["version"]
            done = await invoke(FinishDossierTool, job, storage, ctx, DossierInput())
            assert done["finished"] and done["stored"] == 2, done
            final = await read_json_dossier(conn, storage, job, cid)
            assert final["state"] == "complete"
            rows = (
                (
                    await conn.execute(
                        text(
                            "SELECT entity_id,entity_type,field_key,value_json "
                            "FROM claim WHERE id = ANY(CAST(:ids AS uuid[]))"
                        ),
                        {"ids": done["claim_ids"]},
                    )
                )
                .mappings()
                .all()
            )
            assert len(rows) == 2
            for row in rows:
                assert row["entity_id"] == (job.contact_id if person else job.account_id)
                assert (
                    row["field_key"] == ("contact" if person else "account") + ".research_finding"
                )
                assert row["value_json"]["finding"] == entry["finding"]
            repeated = await invoke(FinishDossierTool, job, storage, ctx, DossierInput())
            assert repeated["claim_ids"] == done["claim_ids"]
            assert all(e["replayed"] for e in repeated["entries"])
            refused = await invoke(
                SaveDossierSectionTool,
                job,
                storage,
                ctx,
                SaveSectionInput(section="Public voice", findings=[]),
            )
            assert not refused["saved"]
            with pytest.raises(ValueError, match="every imported"):
                await validate_dossier_handoff(conn, storage, job, cid, ())
            await validate_dossier_handoff(
                conn, storage, job, cid, tuple(map(UUID, done["claim_ids"]))
            )
            with pytest.raises(ValueError, match="another task"):
                await read_json_dossier(conn, storage, job, uuid4())
            from clue_storage import StorageError

            source_key = (
                await conn.execute(
                    text("SELECT artifact_key FROM arv2_evidence_source WHERE job_id=:job"),
                    {"job": job.job_id},
                )
            ).scalar_one()
            await conn.execute(
                text(
                    "UPDATE artifact SET privacy_erased=true,erased_at=now() WHERE storage_key=:key"
                ),
                {"key": source_key},
            )
            with pytest.raises(StorageError):
                await read_json_dossier(conn, storage, job, cid)
            assert (await backend.aread("/research/dossier/latest.json")).error

    run_async(case())


def test_partial_import_freezes_and_recovers_without_duplicate_claims(tmp_path, monkeypatch):
    async def case():
        async with rollback_conn() as conn:
            job, cid, storage, ctx, backend, path = await prepare(conn, tmp_path)
            await invoke(
                SaveDossierSectionTool,
                job,
                storage,
                ctx,
                SaveSectionInput(
                    section="Voice",
                    findings=[finding(source_paths=[path]), finding("F002", source_paths=[path])],
                ),
            )
            original = dossier_import.submit_proposal

            async def broken(*args, **kwargs):
                result = await original(*args, **kwargs)
                if args[4].value["dossier_entry"]["id"] == "F002":
                    raise RuntimeError("Interruption after write")
                return result

            monkeypatch.setattr(dossier_import, "submit_proposal", broken)
            result = await invoke(FinishDossierTool, job, storage, ctx, DossierInput())
            assert not result["finished"] and result["stored"] == 1
            assert (await read(backend, "/research/dossier/latest.json"))[
                "state"
            ] == "import_pending"
            monkeypatch.setattr(dossier_import, "submit_proposal", original)
            result = await invoke(FinishDossierTool, job, storage, ctx, DossierInput())
            assert result["finished"] and result["stored"] == 2
            assert result["entries"][0]["replayed"]
            assert (await read_json_dossier(conn, storage, job, cid))["state"] == "complete"

    run_async(case())


@pytest.mark.parametrize("person", [False, True])
def test_real_deep_agent_c5_tools_and_cold_finalization_replay(tmp_path, person):
    import asyncio

    from langchain_core.messages import ToolMessage
    from langgraph.checkpoint.memory import InMemorySaver

    from clue_agents import (
        AgentExecutionStatus,
        AgentWorkspaceFactory,
        ScriptedAgentChatModel,
        WorkspaceRootPolicy,
    )
    from clue_api.agent_turn_wiring import DurableAgentArtifactStore
    from clue_api.arv2.evidence_paths import source_path
    from clue_api.arv2.quality_execution import Allowance
    from clue_api.quality_research_wiring import ResearchUnitRuntime, quality_tools
    from clue_config import load_settings
    from tests.arv2.test_quality_runtime_db import call

    async def case():
        async with rollback_conn() as conn:
            storage = FsStorage(tmp_path / "blobs")
            op, job, cid = await setup(conn, storage)
            job = replace(job, catalog_version="v4", input_refs={"quality_recipe_version": 16})
            if person:
                contact = await insert_contact_entity(
                    conn, account_entity_id=job.account_id, full_name="Fixture Person"
                )
                jid = uuid4()
                await create_job(
                    conn,
                    job_id=jid,
                    run_id=job.run_id,
                    workspace_id=job.workspace_id,
                    account_entity_id=job.account_id,
                    subject_type="person",
                    subject_entity_id=contact,
                    profile_sha256="a" * 64,
                )
                job = replace(job, job_id=jid, subject_kind="person", contact_id=contact)
                op = OperationScope(job.workspace_id, job.run_id, jid, job.account_id)
            source = await save(conn, storage, op, "My team keeps the complete public wording.")
            connection_lock = asyncio.Lock()

            @asynccontextmanager
            async def connections():
                async with connection_lock, conn.begin_nested():
                    yield conn

            saver = InMemorySaver()

            @asynccontextmanager
            async def checkpoints(execution_id):
                yield saver

            for directory in ("source", "home"):
                (tmp_path / directory).mkdir(mode=0o700)
            workspaces = AgentWorkspaceFactory(
                prepared_root=WorkspaceRootPolicy(
                    configured_root=tmp_path / "runtime",
                    source_root=tmp_path / "source",
                    home_root=tmp_path / "home",
                ).prepare(),
                artifact_sink=DurableAgentArtifactStore(storage=storage, conn_factory=connections),
            )
            builds = []

            class ReceiptModel(ScriptedAgentChatModel):
                def _generate(self, messages, stop=None, run_manager=None, **kwargs):
                    result = super()._generate(
                        messages, stop=stop, run_manager=run_manager, **kwargs
                    )
                    message = result.generations[0].message
                    if message.tool_calls[0]["id"] == "call-report":

                        def find(value):
                            if isinstance(value, dict):
                                if value.get("finished") and "claim_ids" in value:
                                    return value["claim_ids"]
                                for child in value.values():
                                    found = find(child)
                                    if found:
                                        return found
                            if isinstance(value, list):
                                for child in value:
                                    found = find(child)
                                    if found:
                                        return found
                            return None

                        ids = None
                        for m in reversed(messages):
                            if isinstance(m, ToolMessage):
                                ids = find(json.loads(m.content))
                                if ids:
                                    break
                        assert ids, "Must use the actual import receipt"
                        message.tool_calls[0]["args"]["content"] = json.dumps(
                            {
                                "schema_version": "research-unit-v1",
                                "context_id": str(cid),
                                "job_id": str(job.job_id),
                                "summary": "Imported original wording.",
                                "claim_ids": ids,
                                "gaps": ["Scripted storage test, not live research"],
                            }
                        )
                    return result

            class Models:
                def build(self, **kwargs):
                    builds.append(kwargs["role"])
                    assert kwargs["role"] == "account_research"
                    return ReceiptModel(
                        responses=[
                            call(
                                "read_file",
                                {
                                    "file_path": "/.deepagent/skills/claim-ready-"
                                    + ("person" if person else "account")
                                    + "-dossier/v1/SKILL.md"
                                },
                                "skill",
                            ),
                            call(
                                "save_dossier_section",
                                {
                                    "section": "Public voice",
                                    "findings": [
                                        finding(
                                            source_paths=[source_path(source.model_dump())],
                                            finding="My team keeps the complete public wording.",
                                        )
                                    ],
                                },
                                "save",
                            ),
                            call("validate_dossier", {}, "validate"),
                            call("finish_dossier", {}, "import"),
                            call(
                                "write_file",
                                {"file_path": "/outputs/research.json", "content": "{}"},
                                "report",
                            ),
                            call(
                                "finalize_turn",
                                {"status": "completed", "user_message": "Saved."},
                                "final",
                            ),
                        ]
                    )

            runtime = ResearchUnitRuntime(
                scope=job,
                context_id=cid,
                settings=load_settings(_env_file=None),
                storage=storage,
                connections=connections,
                models=Models(),
                workspaces=workspaces,
                tools=quality_tools(job, storage, purge=True),
                limits=Allowance(20, 30, 4),
                checkpointer_factory=checkpoints,
            )
            result = await runtime.run(objective="Form and import the original saved finding.")
            assert result.status is AgentExecutionStatus.COMPLETED, result
            report = await runtime.report(result)
            assert len(report.claim_ids) == 1
            assert builds == ["account_research"]
            repeated = await runtime.run(objective="Form and import the original saved finding.")
            assert repeated.execution_id == result.execution_id
            assert builds == ["account_research"]
            assert (await runtime.report(repeated)).claim_ids == report.claim_ids
            nodes = (
                (
                    await conn.execute(
                        text("SELECT tool_name FROM execution_node WHERE execution_id=:id"),
                        {"id": result.execution_id},
                    )
                )
                .scalars()
                .all()
            )
            assert {"save_dossier_section", "validate_dossier", "finish_dossier"} <= set(nodes)
            assert "record_research_finding" not in nodes
            workspaces.close()

    run_async(case())


@pytest.mark.parametrize("person", [False, True])
def test_revision_reuses_replaces_remaps_and_preserves_history(tmp_path, person):
    from clue_api.arv2.quality_json_dossier import BeginDossierRevisionTool, BeginRevisionInput

    async def case():
        async with rollback_conn() as conn:
            job, cid, storage, ctx, backend, path = await prepare(conn, tmp_path, person)
            job = replace(job, input_refs={"quality_recipe_version": 17})
            first = finding("F001", source_paths=[path])
            second = finding("F002", source_paths=[path], finding="Independent announcement")
            related = finding(
                "F003",
                source_paths=[path],
                review={
                    "status": "potential_conflict",
                    "reason": "Uncertain dates",
                    "conflicts_with": ["F001"],
                },
            )
            removed = finding("F004", source_paths=[path], finding="Researcher's question")
            await invoke(
                SaveDossierSectionTool,
                job,
                storage,
                ctx,
                SaveSectionInput(section="Voice", findings=[first, second, related, removed]),
            )
            initial = await invoke(FinishDossierTool, job, storage, ctx, DossierInput())
            old_ids = {e["id"]: e["claim_id"] for e in initial["entries"]}
            from clue_api.arv2.display.recipes import load_display_recipes
            from clue_api.arv2.quality_generation import (
                ensure_generation,
                read_generation,
                signal_subject_change,
            )
            from clue_api.arv2.quality_page_inputs import page_inputs
            from clue_research.claimstore.quality import deliver_invalidations

            await load_display_recipes(conn)
            generation = await ensure_generation(
                conn,
                OperationScope(job.workspace_id, job.run_id, job.job_id, job.account_id),
                context_id=cid,
            )
            await deliver_invalidations(
                conn, workspace_id=job.workspace_id, apply=signal_subject_change
            )
            page = "contact" if person else "overview"
            old_inputs = await page_inputs(conn, job, context_id=cid, page=page)
            saved = await read_json_dossier(conn, storage, job, cid)
            assert not (
                await invoke(
                    BeginDossierRevisionTool,
                    job,
                    storage,
                    ctx,
                    BeginRevisionInput(
                        expected_version=saved["version"] + 1, reason="Wrong version"
                    ),
                )
            )["started"]
            assert (
                await invoke(
                    BeginDossierRevisionTool,
                    job,
                    storage,
                    ctx,
                    BeginRevisionInput(
                        expected_version=saved["version"],
                        reason="More precise wording",
                        withdrawals={"F004": "Investigator question, not an observation"},
                    ),
                )
            )["started"]
            first = {
                **first,
                "finding": "Revised observation with uncertain attribution",
                "review": {"status": "insufficient_context", "reason": "Attribution uncertain"},
            }
            addition = finding("F005", source_paths=[path], finding="New independent event")
            await invoke(
                SaveDossierSectionTool,
                job,
                storage,
                ctx,
                SaveSectionInput(section="Voice", findings=[first, second, related, addition]),
            )
            result = await invoke(FinishDossierTool, job, storage, ctx, DossierInput())
            assert result["finished"], result
            ids = {e["id"]: e["claim_id"] for e in result["entries"]}
            # Existing page dependencies change immediately; durable refresh signals replay once.
            changed_inputs = await page_inputs(conn, job, context_id=cid, page=page)
            assert changed_inputs.sha256 != old_inputs.sha256
            await deliver_invalidations(
                conn, workspace_id=job.workspace_id, apply=signal_subject_change
            )
            changed_generation = await read_generation(
                conn, workspace_id=job.workspace_id, generation_id=generation.generation_id
            )
            assert changed_generation.input_revision > old_inputs.generation.input_revision
            await deliver_invalidations(
                conn, workspace_id=job.workspace_id, apply=signal_subject_change
            )
            assert (
                await read_generation(
                    conn, workspace_id=job.workspace_id, generation_id=generation.generation_id
                )
            ).input_revision == changed_generation.input_revision
            assert ids["F002"] == old_ids["F002"]
            assert ids["F001"] != old_ids["F001"]
            assert ids["F003"] != old_ids["F003"]  # Reference now points at the revised finding.
            rows = (
                (
                    await conn.execute(
                        text("""SELECT c.id,c.value_json,c.superseded_by,q.conclusion
                FROM claim c JOIN claim_quality_current q ON q.claim_id=c.id
                WHERE c.id=ANY(:ids)"""),
                        {"ids": [UUID(x) for x in [*old_ids.values(), *ids.values()]]},
                    )
                )
                .mappings()
                .all()
            )
            byid = {str(r["id"]): r for r in rows}
            assert str(byid[old_ids["F001"]]["superseded_by"]) == ids["F001"]
            assert byid[old_ids["F004"]]["conclusion"] == "invalid"
            assert byid[ids["F001"]]["conclusion"] != "supported"
            assert byid[ids["F003"]]["value_json"]["review"]["conflicts_with"] == [ids["F001"]]
            # Corrected values and immutable originals both survive; no replacement of raw evidence.
            assert byid[old_ids["F001"]]["value_json"]["finding"] != first["finding"]
            replay = await invoke(FinishDossierTool, job, storage, ctx, DossierInput())
            assert replay["claim_ids"] == result["claim_ids"]
            assert (await read_json_dossier(conn, storage, job, cid))["version"] == saved[
                "version"
            ] + 3
            events = (
                await conn.execute(
                    text("SELECT count(*) FROM claim_quality_event WHERE claim_id=:id"),
                    {"id": UUID(old_ids["F001"])},
                )
            ).scalar_one()
            assert events >= 2  # Initial assessment plus durable invalidation of old version.
            # Reverting wording creates a new version; it never revives a retired claim.
            latest = await read_json_dossier(conn, storage, job, cid)
            await invoke(
                BeginDossierRevisionTool,
                job,
                storage,
                ctx,
                BeginRevisionInput(
                    expected_version=latest["version"], reason="Resolve attribution"
                ),
            )
            await invoke(
                SaveDossierSectionTool,
                job,
                storage,
                ctx,
                SaveSectionInput(
                    section="Voice",
                    findings=[finding("F001", source_paths=[path]), second, related, addition],
                ),
            )
            final = await invoke(FinishDossierTool, job, storage, ctx, DossierInput())
            assert final["finished"], final
            assert next(e["claim_id"] for e in final["entries"] if e["id"] == "F001") not in (
                ids["F001"],
                old_ids["F001"],
            )

    run_async(case())


def test_failed_revision_rolls_back_and_can_be_repaired_or_discarded(tmp_path, monkeypatch):
    from clue_api.arv2 import dossier_revision
    from clue_api.arv2.quality_json_dossier import (
        BeginDossierRevisionTool,
        BeginRevisionInput,
        DiscardDossierRevisionTool,
        DiscardRevisionInput,
    )

    async def case():
        async with rollback_conn() as conn:
            job, cid, storage, ctx, backend, path = await prepare(conn, tmp_path)
            job = replace(job, input_refs={"quality_recipe_version": 17})
            original = finding(source_paths=[path])
            await invoke(
                SaveDossierSectionTool,
                job,
                storage,
                ctx,
                SaveSectionInput(section="Voice", findings=[original]),
            )
            initial = await invoke(FinishDossierTool, job, storage, ctx, DossierInput())
            saved = await read_json_dossier(conn, storage, job, cid)
            await invoke(
                BeginDossierRevisionTool,
                job,
                storage,
                ctx,
                BeginRevisionInput(expected_version=saved["version"], reason="Correction"),
            )
            # Accidental omission cannot silently retire the original.
            await invoke(
                SaveDossierSectionTool,
                job,
                storage,
                ctx,
                SaveSectionInput(section="Voice", findings=[]),
            )
            invalid = await invoke(FinishDossierTool, job, storage, ctx, DossierInput())
            assert not invalid["finished"] and "withdrawals" in str(invalid["errors"])
            await invoke(
                SaveDossierSectionTool,
                job,
                storage,
                ctx,
                SaveSectionInput(section="Voice", findings=[{**original, "finding": "Corrected"}]),
            )
            before = (await conn.execute(text("SELECT count(*) FROM claim"))).scalar_one()
            retire = dossier_revision.assess_claim

            async def fail(*args, **kwargs):
                raise ValueError("Injected retirement failure")

            monkeypatch.setattr(dossier_revision, "assess_claim", fail)
            failed = await invoke(FinishDossierTool, job, storage, ctx, DossierInput())
            assert not failed["finished"] and not failed["claim_ids"]
            assert (await conn.execute(text("SELECT count(*) FROM claim"))).scalar_one() == before
            monkeypatch.setattr(dossier_revision, "assess_claim", retire)
            latest = await read_json_dossier(conn, storage, job, cid)
            assert latest["state"] == "draft"
            result = await invoke(FinishDossierTool, job, storage, ctx, DossierInput())
            assert result["finished"], result
            latest = await read_json_dossier(conn, storage, job, cid)
            await invoke(
                BeginDossierRevisionTool,
                job,
                storage,
                ctx,
                BeginRevisionInput(expected_version=latest["version"], reason="Optional extension"),
            )
            draft = await read_json_dossier(conn, storage, job, cid)
            assert (
                await invoke(
                    DiscardDossierRevisionTool,
                    job,
                    storage,
                    ctx,
                    DiscardRevisionInput(expected_version=draft["version"]),
                )
            )["discarded"]
            restored = await invoke(FinishDossierTool, job, storage, ctx, DossierInput())
            assert restored["claim_ids"] == result["claim_ids"] != initial["claim_ids"]

    run_async(case())


def test_revision_refuses_out_of_band_claim_change(tmp_path):
    from clue_api.arv2.quality_json_dossier import BeginDossierRevisionTool, BeginRevisionInput
    from clue_research.claimstore.quality import assess_claim

    async def case():
        async with rollback_conn() as conn:
            job, cid, storage, ctx, backend, path = await prepare(conn, tmp_path)
            job = replace(job, input_refs={"quality_recipe_version": 17})
            original = finding(source_paths=[path])
            await invoke(
                SaveDossierSectionTool,
                job,
                storage,
                ctx,
                SaveSectionInput(section="Voice", findings=[original]),
            )
            initial = await invoke(FinishDossierTool, job, storage, ctx, DossierInput())
            saved = await read_json_dossier(conn, storage, job, cid)
            await invoke(
                BeginDossierRevisionTool,
                job,
                storage,
                ctx,
                BeginRevisionInput(expected_version=saved["version"], reason="Correction"),
            )
            await invoke(
                SaveDossierSectionTool,
                job,
                storage,
                ctx,
                SaveSectionInput(section="Voice", findings=[{**original, "finding": "Changed"}]),
            )
            await assess_claim(
                conn,
                workspace_id=job.workspace_id,
                entity_id=job.account_id,
                claim_id=UUID(initial["claim_ids"][0]),
                operation_id=uuid4(),
                expected_revision=1,
                conclusion="unresolved",
                kind="conflict",
                actor_ref="independent-review",
                rationale_key=saved["artifact_key"],
                support_artifacts=(),
                context_id=cid,
            )
            result = await invoke(FinishDossierTool, job, storage, ctx, DossierInput())
            assert not result["finished"] and not result["claim_ids"]
            assert "changed since revision began" in str(result["errors"])

    run_async(case())


@pytest.mark.parametrize("person", [False, True])
def test_reciprocal_conflicts_survive_revision_reuse_and_targeted_correction(tmp_path, person):
    from clue_api.arv2.quality_json_dossier import BeginDossierRevisionTool, BeginRevisionInput

    async def case():
        async with rollback_conn() as conn:
            job, cid, storage, ctx, backend, path = await prepare(conn, tmp_path, person)
            job = replace(job, input_refs={"quality_recipe_version": 24})
            a = finding(
                source_paths=[path],
                review={
                    "status": "potential_conflict",
                    "reason": "Sources disagree",
                    "conflicts_with": ["F002"],
                },
            )
            b = finding(
                "F002",
                source_paths=[path],
                review={
                    "status": "potential_conflict",
                    "reason": "Sources disagree",
                    "conflicts_with": ["F001"],
                },
            )
            await invoke(
                SaveDossierSectionTool,
                job,
                storage,
                ctx,
                SaveSectionInput(section="Voice", findings=[a, b]),
            )
            await invoke(FinishDossierTool, job, storage, ctx, DossierInput())
            baseline = await read_json_dossier(conn, storage, job, cid)
            old_ids = {e["id"]: str(e["claim_id"]) for e in baseline["receipt"]["entries"]}
            for change in (False, True):
                saved = await read_json_dossier(conn, storage, job, cid)
                await invoke(
                    BeginDossierRevisionTool,
                    job,
                    storage,
                    ctx,
                    BeginRevisionInput(expected_version=saved["version"], reason="Review"),
                )
                if change:
                    await invoke(
                        UpdateDossierFindingsTool,
                        job,
                        storage,
                        ctx,
                        SaveSectionInput(
                            section="Voice", findings=[{**a, "finding": "Corrected statement"}]
                        ),
                    )
                await invoke(FinishDossierTool, job, storage, ctx, DossierInput())
                current = await read_json_dossier(conn, storage, job, cid)
                assert current["receipt"]["complete"], current["receipt"]
                ids = {e["id"]: str(e["claim_id"]) for e in current["receipt"]["entries"]}
                if not change:
                    assert ids == old_ids and current["receipt"]["reused"] == 2
                else:
                    assert all(ids[k] != old_ids[k] for k in ids)
                    for key, other in (("F001", "F002"), ("F002", "F001")):
                        value = (
                            await conn.execute(
                                text("SELECT value_json FROM claim WHERE id=CAST(:id AS uuid)"),
                                {"id": ids[key]},
                            )
                        ).scalar_one()
                        assert value["review"]["conflicts_with"] == [ids[other]]
                        retired = (
                            await conn.execute(
                                text("SELECT superseded_by FROM claim WHERE id=CAST(:id AS uuid)"),
                                {"id": old_ids[key]},
                            )
                        ).scalar_one()
                        assert str(retired) == ids[key]

    run_async(case())


def test_v2_saves_the_valid_findings_names_the_rest_and_never_drops_a_stored_one(tmp_path):
    from clue_api.arv2.quality_json_dossier import (
        SaveDossierSectionToolV2,
        SaveSectionInputV2,
        UpdateDossierFindingsToolV2,
    )

    async def case():
        async with rollback_conn() as conn:
            job, cid, storage, ctx, backend, path = await prepare(conn, tmp_path)
            job = replace(job, input_refs={"quality_recipe_version": 26})
            one, three = finding(source_paths=[path]), finding("F003", source_paths=[path])
            two = {k: v for k, v in finding("F002", source_paths=[path]).items() if k != "review"}
            receipt = await invoke(
                SaveDossierSectionToolV2,
                job,
                storage,
                ctx,
                SaveSectionInputV2(section="Voice", findings=[one, two, three]),
            )
            assert receipt["saved"] and receipt["entries"] == 2
            assert [r["id"] for r in receipt["refused"]] == ["F002"]
            assert "review.status" in receipt["refused"][0]["reason"]
            saved = await read_json_dossier(conn, storage, job, cid)
            ids = [f["id"] for f in saved["document"]["sections"][0]["findings"]]
            assert ids == ["F001", "F003"]

            # Re-sending a stored finding without review keeps the stored version.
            bare_one = {k: v for k, v in one.items() if k != "review"}
            again = await invoke(
                SaveDossierSectionToolV2,
                job,
                storage,
                ctx,
                SaveSectionInputV2(section="Voice", findings=[bare_one, three]),
            )
            assert again["saved"] and [r["id"] for r in again["refused"]] == ["F001"]
            saved = await read_json_dossier(conn, storage, job, cid)
            kept = saved["document"]["sections"][0]["findings"]
            assert [f["id"] for f in kept] == ["F001", "F003"] and kept[0]["review"]

            # Nothing valid: nothing changes, and the refusal is explicit.
            none = await invoke(
                SaveDossierSectionToolV2,
                job,
                storage,
                ctx,
                SaveSectionInputV2(section="Voice", findings=[two]),
            )
            assert not none["saved"] and [r["id"] for r in none["refused"]] == ["F002"]

            # The corrected finding goes in with an update.
            fixed = {**two, "review": {"status": "supported", "reason": "Source says this"}}
            update = await invoke(
                UpdateDossierFindingsToolV2,
                job,
                storage,
                ctx,
                SaveSectionInputV2(section="Voice", findings=[fixed]),
            )
            assert update["saved"] and update["refused"] == []
            saved = await read_json_dossier(conn, storage, job, cid)
            assert [f["id"] for f in saved["document"]["sections"][0]["findings"]] == [
                "F001",
                "F003",
                "F002",
            ]

    run_async(case())
