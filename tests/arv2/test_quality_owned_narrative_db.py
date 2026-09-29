"""Real imports -> owner pages -> unchanged wire blocks and scoped shared sections."""

import json
from dataclasses import replace
from uuid import uuid4

import pytest
from sqlalchemy import text

from clue_api.arv2.display.recipes import load_display_recipes
from clue_api.arv2.quality_execution import Allowance, bind_execution
from clue_api.arv2.quality_json_dossier import (
    DossierInput,
    FinishDossierTool,
    SaveDossierSectionTool,
    SaveSectionInput,
)
from clue_api.arv2.quality_owned_narrative import (
    ReadNarrativeInput,
    ReadNarrativeInputsTool,
    WriteNarrativeInput,
    WriteResearchNarrativeTool,
)
from clue_api.arv2.quality_pages import read_page
from clue_api.arv2.research_operations import OperationScope
from clue_core import ExecutionId, OperationId
from tests.arv2.test_dossier_json import finding
from tests.arv2.test_quality_execution_db import execution
from tests.arv2.test_quality_json_dossier_db import invoke
from tests.arv2.test_quality_person_release_db import initial
from tests.claimstore.conftest import (  # noqa: F401
    migrated_db,
    require_claimstore_db,
    rollback_conn,
    run_async,
)

pytestmark = pytest.mark.usefixtures("require_claimstore_db")


async def call(cls, job, storage, ctx, args):
    return (await cls(job, storage, purge_unevidenced=False).invoke(args, ctx)).references


def draft(meta, person=False):
    return WriteNarrativeInput(
        dossier_version=meta["dossier_version"],
        account_dossier_version=meta["account_dossier_version"],
        pages=[
            {
                "page": page,
                "sections": [
                    {
                        "key": r["key"],
                        "items": [
                            {
                                "h2": "Meaningful public wording",
                                "body": [
                                    {
                                        "text": "Original words remain intact.",
                                        "finding_ids": ["F001"],
                                        "account_finding_ids": ["F001"] if person else [],
                                        "kind": "qualified",
                                        "qualifications": ["Source-reported"],
                                    }
                                ],
                                "send_line": {
                                    "text": "A proposed question, not a quote.",
                                    "finding_ids": ["F001"],
                                    "kind": "inference",
                                }
                                if r["key"] == "openers"
                                else None,
                            }
                        ],
                    }
                    for r in sections
                ],
            }
            for page, sections in meta["sections"].items()
        ],
    )


def test_account_person_storage_replay_and_shared_owner_projection(tmp_path, monkeypatch):
    async def case():
        async with rollback_conn() as conn:
            parent, child, cid, storage, ctx, gen, path = await initial(conn, tmp_path)
            parent = replace(parent, input_refs={"quality_recipe_version": 20})
            child = replace(child, input_refs={**child.input_refs, "quality_recipe_version": 20})
            await load_display_recipes(conn)
            with pytest.raises(ValueError, match="Complete finish_dossier"):
                await call(ReadNarrativeInputsTool, parent, storage, ctx, ReadNarrativeInput())
            await invoke(FinishDossierTool, parent, storage, ctx, DossierInput())
            meta = await call(ReadNarrativeInputsTool, parent, storage, ctx, ReadNarrativeInput())
            args = draft(meta)
            out = await call(WriteResearchNarrativeTool, parent, storage, ctx, args)
            assert out["status"] == "published", out
            assert len(out["block_ids"]) == 11
            assert len(json.dumps(out).encode()) < 16384
            assert (await call(WriteResearchNarrativeTool, parent, storage, ctx, args)) == out
            # A failure after Overview was saved must roll back that replacement too.
            import clue_api.arv2.quality_owned_narrative as narrative

            original_publish = narrative.publish_page

            async def fail_second_page(*a, **kw):
                if kw["draft"].page == "insights":
                    raise ValueError("Injected second-page failure")
                return await original_publish(*a, **kw)

            changed = args.model_dump()
            changed["pages"][0]["sections"][0]["items"][0]["body"][0]["text"] = "Replacement"
            with monkeypatch.context() as patch:
                patch.setattr(narrative, "publish_page", fail_second_page)
                failed = await call(
                    WriteResearchNarrativeTool,
                    parent,
                    storage,
                    ctx,
                    WriteNarrativeInput.model_validate(changed),
                )
                assert failed["status"] == "refused"
            overview = await read_page(conn, parent, context_id=cid, page="overview")
            assert overview["display_block"]["sections"][0]["items"][0]["body"][0]["text"] == (
                "Original words remain intact."
            )
            insight = await read_page(conn, parent, context_id=cid, page="insights")
            shared = next(
                s for s in insight["display_block"]["sections"] if s["key"] == "context-only"
            )
            notes = next(
                s for s in overview["display_block"]["sections"] if s["key"] == "watch-outs"
            )
            assert shared["items"] == notes["items"]
            assert shared["restricted"] and notes["restricted"]
            assert "contact-insights" not in insight["stale"]
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
            personctx = replace(
                ctx, execution_id=ExecutionId(eid), operation_id=OperationId(uuid4())
            )
            await invoke(
                SaveDossierSectionTool,
                child,
                storage,
                personctx,
                SaveSectionInput(section="Voice", findings=[finding(source_paths=[path])]),
            )
            await invoke(FinishDossierTool, child, storage, personctx, DossierInput())
            personmeta = await call(
                ReadNarrativeInputsTool, child, storage, personctx, ReadNarrativeInput()
            )
            personargs = draft(personmeta, True)
            personout = await call(
                WriteResearchNarrativeTool, child, storage, personctx, personargs
            )
            assert personout["status"] == "published", personout
            contact = await read_page(conn, child, context_id=cid, page="contact")
            sentences = contact["display_block"]["sections"][0]["items"][0]["body"]
            assert len(sentences[0]["claimIds"]) == 2  # F001 resolves to two different subjects.
            assert sentences[0]["text"] == "Original words remain intact."
            opener = next(s for s in contact["display_block"]["sections"] if s["key"] == "openers")[
                "items"
            ][0]
            assert opener["sendLine"]["channel"] == "email"
            assert opener["sendLine"]["text"] == "A proposed question, not a quote."
            insight = await read_page(conn, parent, context_id=cid, page="insights")
            # The person's insights live on the contact page only (ruling 2026-09-29).
            assert not any(
                s["key"] == "contact-insights" for s in insight["display_block"]["sections"]
            )
            import os
            from pathlib import Path

            if export := os.environ.get("NARRATIVE_TEST_EXPORT"):
                from clue_api.frontend_read.v1_shared import research_evidence_for

                evidence = await research_evidence_for(
                    conn,
                    workspace_id=parent.workspace_id,
                    claim_ids=tuple(
                        dict.fromkeys((*insight["cited_claim_ids"], *contact["cited_claim_ids"]))
                    ),
                )
                Path(export).write_text(
                    json.dumps(
                        {
                            "overview": overview["display_block"],
                            "insights": insight["display_block"],
                            "contact": contact["display_block"],
                            "evidence": [
                                e.model_dump(mode="json", by_alias=True) for e in evidence
                            ],
                        },
                        default=str,
                    )
                )
            # Both owned Miscellaneous sections survive storage with source references,
            # and remain public, collapsed sections rather than restricted notes.
            for result in (insight, contact):
                misc = next(
                    s for s in result["display_block"]["sections"] if s["key"] == "miscellaneous"
                )
                assert not misc["restricted"] and not misc["defaultOpen"]
                assert misc["items"][0]["body"][0]["claimIds"]
                assert misc["items"][0]["body"][0]["text"] == "Original words remain intact."
            assert not any(
                s["key"] == "miscellaneous" for s in overview["display_block"]["sections"]
            )
            # No account-authored copy of the person section was stored.
            assert (
                await conn.execute(
                    text(
                        "SELECT count(*) FROM display_block WHERE workspace_id=:ws "
                        "AND section_key='contact-insights'"
                    ),
                    {"ws": parent.workspace_id},
                )
            ).scalar_one() == 0
            # Wrong section/page, stale versions and unknown IDs cannot partially replace a page.
            for changes in [
                {"dossier_version": meta["dossier_version"] + 1},
                {"pages": personargs.pages},
            ]:
                refused = await call(
                    WriteResearchNarrativeTool,
                    parent,
                    storage,
                    ctx,
                    args.model_copy(update=changes),
                )
                assert refused["status"] == "refused"
            raw = args.model_dump()
            raw["pages"][1]["sections"][0]["items"][0]["body"][0]["finding_ids"] = ["F999"]
            assert (
                await call(
                    WriteResearchNarrativeTool,
                    parent,
                    storage,
                    ctx,
                    WriteNarrativeInput.model_validate(raw),
                )
            )["status"] == "refused"
            assert (await call(WriteResearchNarrativeTool, parent, storage, ctx, args)) == out
            # Cross-subject raw UUID is rejected even when syntactically valid.
            raw = personargs.model_dump()
            raw["pages"][0]["sections"][0]["items"][0]["body"][0]["claim_ids"] = [uuid4()]
            assert (
                await call(
                    WriteResearchNarrativeTool,
                    child,
                    storage,
                    personctx,
                    WriteNarrativeInput.model_validate(raw),
                )
            )["status"] == "refused"

    run_async(case())


@pytest.mark.parametrize("person", [False, True])
def test_pre_miscellaneous_narrative_can_publish_without_refresh_loop(tmp_path, person):
    async def case():
        async with rollback_conn() as conn:
            parent, child, cid, storage, ctx, gen, path = await initial(conn, tmp_path)
            parent = replace(parent, input_refs={"quality_recipe_version": 20})
            child = replace(child, input_refs={**child.input_refs, "quality_recipe_version": 20})
            await load_display_recipes(conn)
            await invoke(FinishDossierTool, parent, storage, ctx, DossierInput())
            job = child if person else parent
            if person:
                op = OperationScope(
                    child.workspace_id, child.run_id, child.job_id, child.account_id
                )
                eid = await execution(conn, op, child.project_id)
                await bind_execution(
                    conn,
                    op,
                    execution_id=eid,
                    context_id=cid,
                    role="account_research",
                    limits=Allowance(100, 100, 10),
                )
                ctx = replace(ctx, execution_id=ExecutionId(eid), operation_id=OperationId(uuid4()))
                await invoke(
                    SaveDossierSectionTool,
                    child,
                    storage,
                    ctx,
                    SaveSectionInput(section="Voice", findings=[finding(source_paths=[path])]),
                )
                await invoke(FinishDossierTool, child, storage, ctx, DossierInput())
            meta = await call(ReadNarrativeInputsTool, job, storage, ctx, ReadNarrativeInput())
            raw = draft(meta, person).model_dump()
            for page in raw["pages"]:
                page["sections"] = [s for s in page["sections"] if s["key"] != "miscellaneous"]
            out = await call(
                WriteResearchNarrativeTool,
                job,
                storage,
                ctx,
                WriteNarrativeInput.model_validate(raw),
            )
            assert out["status"] == "published", out
            result = await read_page(
                conn, job, context_id=cid, page="contact" if person else "insights"
            )
            misc = next(
                s for s in result["display_block"]["sections"] if s["key"] == "miscellaneous"
            )
            assert misc["items"] == [] and not misc["restricted"] and not misc["pending"]
            assert "miscellaneous" not in result["pending"]
            assert "published yet" in misc["emptyMessage"]
            assert "miscellaneous" not in result["stale"]

    run_async(case())


@pytest.mark.parametrize("version", [20, 24])
@pytest.mark.parametrize("person", [False, True])
@pytest.mark.parametrize("report_mode", ["legacy", "notes", "none"])
def test_native_researcher_writes_pages_without_specialist_and_replays(
    tmp_path, monkeypatch, person, version, report_mode
):
    import asyncio
    from contextlib import asynccontextmanager

    from langchain_core.messages import ToolMessage
    from langgraph.checkpoint.memory import InMemorySaver

    from clue_agents import (
        AgentExecutionStatus,
        AgentWorkspaceFactory,
        ScriptedAgentChatModel,
        WorkspaceRootPolicy,
    )
    from clue_api.agent_turn_wiring import DurableAgentArtifactStore
    from clue_api.arv2.quality_json_dossier import read_json_dossier
    from clue_api.quality_research_wiring import ResearchUnitRuntime, quality_tools
    from clue_config import load_settings
    from tests.arv2.test_quality_runtime_db import call as model_call

    def unexpected_specialist_runtime(*args, **kwargs):
        pytest.fail("Current research must not construct specialist or delegation runtimes")

    for constructor in ("FreshWakeSpecialistRunner", "DbAgentDelegationRuntime"):
        monkeypatch.setattr(
            f"clue_api.quality_research_wiring.{constructor}", unexpected_specialist_runtime
        )

    async def case():
        async with rollback_conn() as conn:
            parent, child, cid, storage, ctx, gen, path = await initial(conn, tmp_path / "blobs")
            parent = replace(parent, input_refs={"quality_recipe_version": version})
            await load_display_recipes(conn)
            await invoke(FinishDossierTool, parent, storage, ctx, DossierInput())
            job = parent
            if person:
                job = replace(
                    child, input_refs={**child.input_refs, "quality_recipe_version": version}
                )
                op = OperationScope(job.workspace_id, job.run_id, job.job_id, job.account_id)
                eid = await execution(conn, op, job.project_id)
                await bind_execution(
                    conn,
                    op,
                    execution_id=eid,
                    context_id=cid,
                    role="account_research",
                    limits=Allowance(100, 100, 10),
                )
                childctx = replace(
                    ctx, execution_id=ExecutionId(eid), operation_id=OperationId(uuid4())
                )
                await invoke(
                    SaveDossierSectionTool,
                    job,
                    storage,
                    childctx,
                    SaveSectionInput(section="Voice", findings=[finding(source_paths=[path])]),
                )
                await invoke(FinishDossierTool, job, storage, childctx, DossierInput())
            saved = await read_json_dossier(conn, storage, job, cid)
            claimids = [e["claim_id"] for e in saved["receipt"]["entries"]]
            lock = asyncio.Lock()

            @asynccontextmanager
            async def connections():
                async with lock, conn.begin_nested():
                    yield conn

            saver = InMemorySaver()

            @asynccontextmanager
            async def checkpoints(execution_id):
                yield saver

            for directory in ["source", "home"]:
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

            class Writer(ScriptedAgentChatModel):
                def _generate(self, messages, stop=None, run_manager=None, **kwargs):
                    result = super()._generate(
                        messages, stop=stop, run_manager=run_manager, **kwargs
                    )
                    msg = result.generations[0].message
                    if msg.tool_calls[0]["name"] == "write_research_narrative":

                        def locate(x):
                            if isinstance(x, dict):
                                if "dossier_version" in x and "sections" in x:
                                    return x
                                for v in x.values():
                                    if found := locate(v):
                                        return found
                            if isinstance(x, list):
                                for v in x:
                                    if found := locate(v):
                                        return found
                            return None

                        meta = None
                        for m in reversed(messages):
                            if isinstance(m, ToolMessage):
                                meta = locate(json.loads(m.content))
                                if meta:
                                    break
                        assert meta, "Must use actual governed tool input receipt"
                        msg.tool_calls[0]["args"] = draft(meta, person).model_dump(mode="json")
                    return result

            class Models:
                def build(self, **kwargs):
                    builds.append(kwargs["role"])
                    assert kwargs["role"] == "account_research"
                    responses = [
                        model_call("read_narrative_inputs", {}, "inputs"),
                        model_call("write_research_narrative", {}, "write"),
                        model_call(
                            "write_file",
                            {
                                "file_path": "/outputs/research.json",
                                "content": json.dumps(
                                    {
                                        "schema_version": "research-unit-v1",
                                        "context_id": str(cid),
                                        "job_id": str(job.job_id),
                                        "summary": "Own narrative saved after existing import.",
                                        "claim_ids": claimids,
                                        "gaps": ["Scripted contract test, not live research."],
                                    }
                                ),
                            },
                            "report",
                        ),
                        model_call(
                            "finalize_turn",
                            {"status": "completed", "user_message": "Saved owned pages."},
                            "finish",
                        ),
                    ]
                    if report_mode == "none":
                        responses.pop(2)
                    elif report_mode == "notes":
                        responses[2].tool_calls[0]["args"]["content"] = json.dumps(
                            {
                                "summary": "Own narrative saved after existing import.",
                                "gaps": ["Scripted contract test, not live research."],
                                "claim_ids": ["obsolete bookkeeping is ignored"],
                            }
                        )
                    return Writer(responses=responses)

            runtime = ResearchUnitRuntime(
                scope=job,
                context_id=cid,
                settings=load_settings(_env_file=None),
                storage=storage,
                connections=connections,
                models=Models(),
                workspaces=workspaces,
                tools=quality_tools(job, storage, purge=True),
                limits=Allowance(100, 100, 10),
                checkpointer_factory=checkpoints,
            )
            outcome = await runtime.run(
                objective="Continue from the imported dossier and write your own narrative."
            )
            assert outcome.status is AgentExecutionStatus.COMPLETED, outcome
            report = await runtime.report(outcome)
            assert {str(i) for i in report.claim_ids} == set(claimids)
            assert report.delivery["claims_imported"]
            assert report.delivery["narrative_published"]
            assert report.delivery["narrative_pages"]
            assert builds == ["account_research"]
            nodes = set(
                (
                    await conn.execute(
                        text("SELECT tool_name FROM execution_node WHERE execution_id=:id"),
                        {"id": outcome.execution_id},
                    )
                ).scalars()
            )
            assert {"read_narrative_inputs", "write_research_narrative"} <= nodes
            assert "delegate_specialist" not in nodes
            rows = (
                await conn.execute(
                    text("SELECT page,section_key FROM display_block WHERE execution_id=:id"),
                    {"id": outcome.execution_id},
                )
            ).all()
            assert len(rows) == (6 if person else 11)
            repeated = await runtime.run(
                objective="Continue from the imported dossier and write your own narrative."
            )
            assert repeated.execution_id == outcome.execution_id and builds == ["account_research"]
            workspaces.close()

    run_async(case())
