"""Actual provider/drain/evidence/media seams on isolated Postgres; offline transports only."""

import json
from contextlib import asynccontextmanager
from dataclasses import replace
from uuid import UUID, uuid4

import pytest
from deepagents.backends.protocol import BackendProtocol
from sqlalchemy import text

from clue_api.arv2.account_research_store import create_job
from clue_api.arv2.quality_authority import resolve_authority
from clue_api.arv2.quality_evidence import EvidenceUnavailable, revoke_grant
from clue_api.arv2.quality_execution import Allowance, bind_execution
from clue_api.arv2.quality_provider_tools import AcquireResearchInput, AcquireResearchTool
from clue_api.arv2.quality_source_review import source_review
from clue_api.arv2.quality_views import research_backend
from clue_api.arv2.transport import HttpResponse, ScriptedTransport
from clue_core import ExecutionId, OperationId
from clue_research.identity import insert_contact_entity
from clue_storage.fs import FsStorage
from clue_toolbelt import ToolContext
from tests.arv2.test_committee_discovery_v2_db import response, runtime
from tests.arv2.test_quality_claims_db import setup
from tests.arv2.test_quality_execution_db import execution
from tests.arv2.test_quality_tools_db import read, read_document
from tests.claimstore.conftest import (  # noqa: F401
    migrated_db,
    require_claimstore_db,
    rollback_conn,
    run_async,
)

pytestmark = pytest.mark.usefixtures("require_claimstore_db")


async def person_setup(conn, storage):
    op, account, cid = await setup(conn, storage)
    contact = await insert_contact_entity(
        conn, account_entity_id=account.account_id, full_name="Dana Fixture"
    )
    jid = uuid4()
    await create_job(
        conn,
        job_id=jid,
        run_id=op.run_id,
        workspace_id=op.workspace_id,
        account_entity_id=op.account_id,
        subject_type="person",
        subject_entity_id=contact,
        profile_sha256="a" * 64,
    )
    scope = replace(
        account,
        job_id=jid,
        subject_kind="person",
        contact_id=contact,
        person_name="Dana Fixture",
        catalog_version="v4",
        input_refs={"quality_recipe_version": 11},
    )
    return replace(op, job_id=jid), scope, cid


@pytest.mark.parametrize("subject", ["person", "account"])
def test_search_deep_and_page_keep_all_fields_with_replay_and_revocable_views(tmp_path, subject):
    async def case():
        async with rollback_conn() as conn:
            storage = FsStorage(tmp_path)
            if subject == "person":
                op, scope, cid = await person_setup(conn, storage)
            else:
                op, scope, cid = await setup(conn, storage)
                scope = replace(
                    scope, catalog_version="v4", input_refs={"quality_recipe_version": 12}
                )
            parent = await execution(conn, op, scope.project_id)
            await bind_execution(
                conn,
                op,
                execution_id=parent,
                context_id=cid,
                role="account_research",
                limits=Allowance(30, 60, 4),
            )
            old = {"url": "https://example.test/dana", "text": "Background. " * 850}
            fresh = {
                **old,
                "highlights": ["I write essays on creative practice."],
                "extras": {"links": ["https://example.test/essays"]},
                "profile": {"previous_employer": "Prior Co"},
            }
            report = "A general career summary, omitting the personal project. " * 150
            results = [
                fresh,
                *[
                    {
                        "url": f"https://example.test/{i}",
                        "text": f"Page {i}",
                        "highlights": [f"Finding {i}"],
                    }
                    for i in range(1, 12)
                ],
            ]
            wire = ScriptedTransport(
                [
                    response({"results": [old], "costDollars": {"total": 0.001}}),
                    response(
                        {
                            "output": {"content": report},
                            "results": results,
                            "costDollars": {"total": 0.05},
                        }
                    ),
                    response({"results": [fresh], "costDollars": {"total": 0.001}}),
                ]
            )
            rt = runtime(conn, scope, storage, wire)

            @asynccontextmanager
            async def connections():
                yield conn

            ctx = ToolContext(
                workspace_id=scope.workspace_id,
                actor="agent",
                conn_factory=connections,
                execution_id=ExecutionId(parent),
                operation_id=OperationId(uuid4()),
            )
            tool = AcquireResearchTool(rt)
            backend = research_backend(BackendProtocol(), connections, storage, scope, parent)

            async def call(operation, arguments):
                inputs = AcquireResearchInput(operation=operation, arguments=arguments)
                receipt = await tool.invoke(inputs, ctx)
                assert receipt.references["status"] == "completed", receipt
                saved = json.loads(await read_document(backend, receipt.references["result_path"]))
                return inputs, saved

            _, search = await call("search_web", {"query": "Dana earlier career interviews"})
            first = await read(backend, search["source_review_path"])
            assert first["sources"][0]["text_characters"] == len(old["text"])
            assert not first["sources"][0]["previous_capture"]
            request, deep = await call(
                "research_deep",
                {
                    "charter": "Research Dana with their known public background and voice. " * 10,
                    "additional_queries": ["Dana creative practice"],
                    **({"highlights_query": "Own projects"} if subject == "person" else {}),
                    "num_results": 40,
                },
            )
            overview = await read(backend, deep["source_review_path"])
            assert overview["total_results"] == 12
            assert len(overview["sources"]) == 12
            assert overview["next_path"] is None
            entry = overview["sources"][0]
            assert entry["previous_capture"]
            assert entry["changed_fields"] == []  # Identical text; new fields still matter.
            assert set(entry["added_fields"]) == {"highlights", "extras", "profile"}
            assert entry["highlights"][0]["text_segments"] == fresh["highlights"]
            assert json.loads(await read_document(backend, entry["full_source_path"])) == fresh
            tail = await read(backend, deep["source_review_path"].replace("/0.json", "/10.json"))
            assert len(tail["sources"]) == 2 and tail["next_path"] is None
            replay = await tool.invoke(request, ctx)
            assert replay.references["replayed"] and len(wire.requests) == 2
            _, page = await call("fetch_page", {"url": old["url"], "max_chars": 20000})
            assert (await read(backend, page["source_review_path"]))["sources"][0][
                "previous_capture"
            ]
            bodies = [json.loads(r.body) for r in wire.requests]
            assert bodies[0]["type"] == "auto"
            if subject == "person":
                assert bodies[0]["contents"]["text"]["maxCharacters"] == 10000
                assert bodies[1]["contents"]["highlights"]["query"] == "Own projects"
                assert bodies[2]["extras"] == {"links": 10, "imageLinks": 3}
            else:
                assert bodies[0]["contents"] == {"text": {"maxCharacters": 1500}}
                assert bodies[1]["additionalQueries"] == ["Dana creative practice"]
                assert bodies[1]["contents"] == {"highlights": True, "extras": {"links": 1}}
                assert bodies[2] == {"urls": [old["url"]], "text": {"maxCharacters": 20000}}
            assert (
                await conn.execute(
                    text(
                        "SELECT count(*) FROM provider_call_ledger "
                        "WHERE entity_research_job_id=:job "
                        "AND phase='result'"
                    ),
                    {"job": scope.job_id},
                )
            ).scalar_one() == 3
            # A new worker/runtime reads the same saved views, without paying again.
            rebuilt = research_backend(
                BackendProtocol(), connections, FsStorage(tmp_path), scope, parent
            )
            assert await read(rebuilt, deep["source_review_path"]) == overview
            await conn.execute(
                text(
                    "UPDATE artifact SET privacy_erased=true,erased_at=now() WHERE storage_key="
                    "(SELECT artifact_key FROM arv2_evidence_source WHERE source_id=:id)"
                ),
                {"id": UUID(entry["source_id"])},
            )
            erased = await read(rebuilt, deep["source_review_path"])
            assert all(s["source_id"] != entry["source_id"] for s in erased["sources"])
            assert (await rebuilt.aread(entry["full_source_path"])).error
            authority = await resolve_authority(conn, scope, parent)
            await revoke_grant(conn, authority.grant)
            with pytest.raises(EvidenceUnavailable):
                await source_review(conn, storage, authority.grant, UUID(deep["result_ref"]))
            assert len(wire.requests) == 3

    run_async(case())


def test_media_candidates_can_be_followed_to_original_transcript_without_repurchase():
    from clue_api.arv2.media_tools import (
        OpenTranscriptArgs,
        ReadMediaArgs,
        open_transcript,
        read_media,
    )
    from tests.arv2.test_media_store_db import seeded

    async def case():
        async with rollback_conn() as conn:
            rt = await seeded(conn)
            transcript = "Host: Why did you start?\nGuest: I wanted to explain creative practice."
            recording = (
                '<script type="application/ld+json">'
                + json.dumps(
                    {
                        "@type": "PodcastEpisode",
                        "name": "Conversation",
                        "transcript": transcript,
                    }
                )
                + "</script>"
            )
            wire = ScriptedTransport(
                [
                    HttpResponse(
                        200,
                        {"content-type": "text/html"},
                        b'<iframe src="/interview"></iframe><iframe src="/other"></iframe>',
                    ),
                    HttpResponse(200, {"content-type": "text/html"}, recording.encode()),
                ]
            )
            rt._transport_factory = lambda: wire
            first = await read_media(
                rt, ReadMediaArgs(url="https://example.com/landing", purpose="Read the interview")
            )
            assert first["state"] == "ambiguous"
            assert "read_media again" in first["next_action"]
            candidate = first["candidates"][0]
            assert candidate["recording_status"] == "candidate_not_yet_attempted"
            assert candidate["origin"]
            args = ReadMediaArgs(
                candidate_ref=UUID(candidate["candidate_ref"]),
                purpose="Read the selected interview",
            )
            result = await read_media(rt, args)
            assert result["state"] == "available" and "open_transcript" in result["next_action"]
            opened = await open_transcript(
                rt, OpenTranscriptArgs(version_ref=UUID(result["version_ref"]))
            )
            assert opened["text"] == transcript
            assert (await read_media(rt, args))["reused"]
            assert len(wire.requests) == 2

    run_async(case())


@pytest.mark.parametrize("subject", ["person", "account"])
def test_real_deepagent_materializes_full_skills_and_finalizes_with_model_journal(
    tmp_path, monkeypatch, subject
):
    import asyncio

    from langgraph.checkpoint.memory import InMemorySaver

    from clue_agents import (
        AgentExecutionStatus,
        AgentWorkspaceFactory,
        ScriptedAgentChatModel,
        WorkspaceRootPolicy,
    )
    from clue_api.agent_turn_wiring import DurableAgentArtifactStore
    from clue_api.quality_research_wiring import ResearchUnitRuntime, quality_tools
    from clue_config import load_settings
    from tests.arv2.test_quality_runtime_db import call

    seen = []
    original = ScriptedAgentChatModel._generate

    def capture(self, messages, *args, **kwargs):
        seen.append("\n".join(str(m.content) for m in messages))
        return original(self, messages, *args, **kwargs)

    monkeypatch.setattr(ScriptedAgentChatModel, "_generate", capture)

    async def case():
        async with rollback_conn() as conn:
            storage = FsStorage(tmp_path / "blobs")
            if subject == "person":
                _, scope, cid = await person_setup(conn, storage)
                skills = ("person-depth-charter/v1", "person-dossier/v1")
            else:
                _, scope, cid = await setup(conn, storage)
                scope = replace(
                    scope, catalog_version="v4", input_refs={"quality_recipe_version": 12}
                )
                skills = ("account-dossier/v3", "person-research-briefing/v2")
            lock = asyncio.Lock()

            @asynccontextmanager
            async def connections():
                async with lock, conn.begin_nested():
                    yield conn

            saver = InMemorySaver()

            @asynccontextmanager
            async def checkpoints(execution_id):
                yield saver

            class Models:
                def build(self, **kwargs):
                    return ScriptedAgentChatModel(
                        responses=[
                            call(
                                "read_file",
                                {
                                    "file_path": f"/.deepagent/skills/{skills[0]}/SKILL.md",
                                    "limit": 500,
                                },
                                "charter",
                            ),
                            call(
                                "read_file",
                                {
                                    "file_path": f"/.deepagent/skills/{skills[1]}/SKILL.md",
                                    "limit": 600,
                                },
                                "skill",
                            ),
                            call(
                                "write_file",
                                {
                                    "file_path": "outputs/research.json",
                                    "content": json.dumps(
                                        {
                                            "schema_version": "research-unit-v1",
                                            "job_id": str(scope.job_id),
                                            "context_id": str(cid),
                                            "summary": "Offline resource integration check.",
                                            "gaps": ["No live research in this scripted test."],
                                        }
                                    ),
                                },
                                "report",
                            ),
                            call(
                                "finalize_turn",
                                {
                                    "status": "completed",
                                    "user_message": "Resource integration checked.",
                                },
                                "finish",
                            ),
                        ]
                    )

            for name in ("source", "home"):
                (tmp_path / name).mkdir()
            workspaces = AgentWorkspaceFactory(
                prepared_root=WorkspaceRootPolicy(
                    configured_root=tmp_path / "runtime",
                    source_root=tmp_path / "source",
                    home_root=tmp_path / "home",
                ).prepare(),
                artifact_sink=DurableAgentArtifactStore(storage=storage, conn_factory=connections),
            )
            rt = ResearchUnitRuntime(
                scope=scope,
                context_id=cid,
                settings=load_settings(_env_file=None),
                storage=storage,
                connections=connections,
                models=Models(),
                workspaces=workspaces,
                tools=quality_tools(scope, storage, purge=False),
                limits=Allowance(10, 20, 4),
                checkpointer_factory=checkpoints,
            )
            outcome = await rt.run(objective="Read the full person instructions, then finish.")
            assert outcome.status is AgentExecutionStatus.COMPLETED
            if subject == "person":
                assert "Discover broadly before composing" in seen[-1]
                assert "Hobbies and sports" in seen[-1]
                assert "KNOWN SAME-NAME EXCLUSIONS" in seen[-1]
                assert "Follow relevant media through to its content" in seen[-1]
            else:
                assert "Discover systems through work before guessing brands" in seen[-1]
                assert "source_review_path" in seen[-1]
                assert "Teaching example: Clue → fictional Acme" in seen[-1]
                assert "Interpret missing results honestly" in seen[-1]
                assert "person-specific" in seen[-1]
                assert "/scratch/" not in seen[-1]
            assert (
                await conn.execute(
                    text("SELECT count(*) FROM agent_model_call WHERE execution_id=:id"),
                    {"id": outcome.execution_id},
                )
            ).scalar_one() == 4
            again = await rt.run(objective="Read the full person instructions, then finish.")
            assert again.status is AgentExecutionStatus.COMPLETED and len(seen) == 4
            workspaces.close()

    run_async(case())
