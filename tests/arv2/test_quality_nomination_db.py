"""An AI Ark candidate keeps its original through governed nomination and person handoff."""

import json
from contextlib import asynccontextmanager
from dataclasses import replace
from uuid import uuid4

import pytest
from deepagents.backends.protocol import BackendProtocol
from sqlalchemy import text

from clue_api.arv2.account_research_store import read_job
from clue_api.arv2.committee_discovery import load_person_seed
from clue_api.arv2.quality_committee_tool import NominateCommitteeInput, NominateCommitteeTool
from clue_api.arv2.quality_execution import Allowance, bind_execution
from clue_api.arv2.quality_mapping import QualityProviderWriter
from clue_api.arv2.quality_provider_tools import AcquireResearchInput, AcquireResearchTool
from clue_api.arv2.quality_relationships import OrganizationScope, read_committee
from clue_api.arv2.quality_views import research_backend
from clue_api.arv2.transport import ScriptedTransport
from clue_core import ExecutionId, OperationId
from clue_storage.fs import FsStorage
from clue_toolbelt import ToolContext
from tests.arv2.test_committee_discovery_v2 import person
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


@pytest.mark.parametrize("revision", [5, 6, 9, 11, 12])
def test_candidate_original_survives_nomination_replay_and_person_seed(tmp_path, revision):
    async def case():
        async with rollback_conn() as conn:
            storage = FsStorage(tmp_path)
            op, scope, cid = await setup(conn, storage)
            scope = replace(
                scope, catalog_version="v4", input_refs={"quality_recipe_version": revision}
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
            # Discovery continues after an exhausted Exa retry, with the gap retained.
            from clue_api.arv2.research_operations import begin

            deep, _ = await begin(conn, op, "account_deep", {"offline": True})
            await conn.execute(
                text(
                    "UPDATE arv2_research_operation SET state='failed',"
                    "error_code='retry_exhausted' WHERE operation_id=:id"
                ),
                {"id": deep.operation_id},
            )
            wire = ScriptedTransport(
                [
                    response(
                        {
                            "content": [
                                {
                                    "id": "company-1",
                                    "link": {"domain": scope.account_domain},
                                    "summary": {"name": scope.account_name},
                                }
                            ]
                        }
                    ),
                    response({"content": [person(domain=scope.account_domain)], "last": True}),
                ]
            )
            rt = runtime(conn, scope, storage, wire)
            rt._writer = QualityProviderWriter(scope, storage, parent, rt.catalog, purge=True)

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
            acquire = AcquireResearchTool(rt)
            result = await acquire.invoke(
                AcquireResearchInput(
                    operation="discover_people",
                    arguments={
                        "role_key": "growth",
                        "rationale": "Owns marketing",
                        "titles": ["VP Marketing"],
                    },
                ),
                ctx,
            )
            assert result.references["status"] == "completed", result
            backend = research_backend(BackendProtocol(), connections, storage, scope, parent)
            saved = json.loads(await read_document(backend, result.references["result_path"]))
            candidate = saved["people"][0]["candidate_ref"]
            nominate = NominateCommitteeTool(scope, storage, purge_unevidenced=True)
            args = NominateCommitteeInput(
                candidate_ref=candidate,
                persona_key="champion",
                role="champion",
                organization_scope=OrganizationScope(
                    relationship="exact_company",
                    geography="global",
                    location_relevance="not_required",
                    rationale="Global marketing remit requires verification",
                ),
                rationale="Potential marketing owner; verify affiliation and buying remit",
            )
            context = replace(ctx, operation_id=OperationId(uuid4()))
            if revision >= 6:
                from clue_api.arv2.quality_committee_tool import (
                    NominateSourceCommitteeTool,
                    NominateSourceInput,
                )

                nominate = NominateSourceCommitteeTool(scope, storage, purge_unevidenced=True)
                args = NominateSourceInput(
                    candidate_ref=candidate,
                    persona_key="champion",
                    role="champion",
                    rationale="Source-reported marketing owner",
                )
            if revision >= 9:
                from clue_api.arv2.quality_committee_tool import (
                    NominateBriefedCommitteeTool,
                    NominateBriefedInput,
                )

                nominate = NominateBriefedCommitteeTool(scope, storage, purge_unevidenced=True)
                args = NominateBriefedInput(
                    **args.model_dump(),
                    research_brief="Research Dana for the selected seller. Read the full "
                    "person charter; explore the hiring initiative and earlier career. "
                    "Consult /research/context.json and /evidence/index.json.",
                )
            receipt = await nominate.invoke(args, context)
            replay = await nominate.invoke(args, context)
            assert replay.references["replayed"]
            assert receipt.references["person_job_id"] == replay.references["person_job_id"]
            job = await read_job(conn, job_id=receipt.references["person_job_id"])
            assert job.input_refs["candidate_ref"] == candidate
            assert job.input_refs["subject_scope"] == "account"
            members = await read_committee(
                conn, workspace_id=scope.workspace_id, account_id=scope.account_id, context_id=cid
            )
            assert len(members) == 1 and members[0].outreach_eligible == (revision >= 6)
            assert members[0].state == ("supported" if revision >= 6 else "candidate")
            if revision >= 6:
                assert not members[0].employment_claim_ids
                assert "current_affiliation_not_established" not in members[0].gaps
            person_scope = replace(
                scope,
                job_id=job.job_id,
                subject_kind="person",
                contact_id=job.subject_entity_id,
                person_name="Dana Test",
                input_refs=job.input_refs,
            )
            person_op = replace(op, job_id=job.job_id)
            person_execution = await execution(conn, person_op, scope.project_id)
            await bind_execution(
                conn,
                person_op,
                execution_id=person_execution,
                context_id=cid,
                role="account_research",
                limits=Allowance(30, 60, 4),
            )
            person_rt = runtime(conn, person_scope, storage, wire)
            person_rt._writer = QualityProviderWriter(
                person_scope, storage, person_execution, rt.catalog, purge=True
            )
            if revision >= 9:
                from clue_api.arv2.person_research_brief import (
                    person_task_instruction,
                    read_person_brief,
                )

                brief = await read_person_brief(conn, storage, person_scope, context_id=cid)
                assert brief["brief"] == args.research_brief
                assert args.research_brief in person_task_instruction(brief)
                view = research_backend(
                    BackendProtocol(), connections, storage, person_scope, person_execution
                )
                context_view = await read(view, "/research/context.json")
                assert context_view["discovery_references"]["candidate_ref"] == candidate
                assert context_view["selected_person"]["name"] == "Dana Test"
                envelope = json.loads(
                    await read_document(view, context_view["person_research_brief_path"])
                )
                assert envelope["brief"] == args.research_brief
                changed = args.model_copy(update={"research_brief": "Must not overwrite the job"})
                await nominate.invoke(changed, replace(context, operation_id=OperationId(uuid4())))
                assert (await read_person_brief(conn, storage, person_scope, context_id=cid))[
                    "brief"
                ] == args.research_brief
                # Originals and full pinned documents remain readable from the person job.
                evidence = await read(view, "/evidence/index.json")
                assert evidence["sources"]
                for path in context_view["document_paths"].values():
                    assert await read_document(view, path)
                with pytest.raises(ValueError):
                    await read_person_brief(
                        conn, storage, replace(person_scope, account_id=uuid4()), context_id=cid
                    )
            seed = await load_person_seed(person_rt)
            assert seed["candidate_ref"] == candidate
            assert len(wire.requests) == 2  # no extra named-person purchase
            if revision >= 6:
                from clue_api.arv2.quality_findings import (
                    RecordFindingInput,
                    RecordResearchFindingTool,
                )
                from clue_api.arv2.quality_page_tools import ResearchPageDraft
                from clue_api.arv2.quality_pages import (
                    CitedItem,
                    CitedSentence,
                    PageSectionDraft,
                    publish_page,
                    read_page,
                )

                finding = await RecordResearchFindingTool(
                    person_scope, storage, purge_unevidenced=True
                ).invoke(
                    RecordFindingInput(
                        operation_key="person-notes",
                        topic="Background",
                        finding="Source reports a remote role; location uncertain. "
                        "Phone: +1 202 555 0100.",
                        notes="Source-reported; no independent employment check.",
                    ),
                    replace(
                        ctx,
                        execution_id=ExecutionId(person_execution),
                        operation_id=OperationId(uuid4()),
                    ),
                )
                assert finding.references["claim_id"]
                await publish_page(
                    conn,
                    storage,
                    person_scope,
                    context_id=cid,
                    execution_id=person_execution,
                    model="offline",
                    draft=ResearchPageDraft(
                        page="contact",
                        sections=(
                            PageSectionDraft(
                                key="openers",
                                items=(
                                    CitedItem(
                                        h2="Relevant introduction",
                                        contactIds=(job.subject_entity_id,),
                                        body=(
                                            CitedSentence(text="Potential marketing relevance."),
                                        ),
                                        sendLine=CitedSentence(
                                            text="Your marketing work may be relevant "
                                            "to this product."
                                        ),
                                    ),
                                ),
                            ),
                        ),
                    ),
                )
                page = await read_page(conn, person_scope, context_id=cid, page="contact")
                assert "+1 202 555 0100" in json.dumps(page["display_block"])
                assert "Your marketing work" in json.dumps(page["display_block"])
            assert (
                await conn.execute(text("SELECT count(*) FROM arv2_generation_child"))
            ).scalar_one() == 1

    run_async(case())


@pytest.mark.parametrize("revision", [5, 9, 12])
def test_web_gap_uses_same_candidate_and_person_job_contract(tmp_path, revision):
    from clue_api.arv2.quality_committee_tool import (
        NominateWebCommitteeInput,
        NominateWebCommitteeTool,
    )
    from clue_api.arv2.quality_evidence import TextSupport
    from tests.arv2.test_quality_evidence_db import save

    async def case():
        async with rollback_conn() as conn:
            storage = FsStorage(tmp_path)
            op, scope, cid = await setup(conn, storage)
            scope = replace(
                scope, catalog_version="v4", input_refs={"quality_recipe_version": revision}
            )
            parent = await execution(conn, op, scope.project_id)
            await bind_execution(
                conn,
                op,
                execution_id=parent,
                context_id=cid,
                role="account_research",
                limits=Allowance(20, 40, 4),
            )
            body = (
                "Alex Example leads operations. Profile: https://www.linkedin.com/in/alex-example/"
            )
            source = await save(conn, storage, op, body)

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
            tool = NominateWebCommitteeTool(scope, storage, purge_unevidenced=True)
            args = NominateWebCommitteeInput(
                name="Alex Example",
                linkedin_url="https://www.linkedin.com/in/alex-example/",
                source=TextSupport(source_id=source.source_id, start=0, end=len(body), quote=body),
                persona_key="operations",
                role="champion",
                rationale="AI Ark left operations uncovered.",
                organization_scope=OrganizationScope(
                    relationship="exact_company",
                    geography="local",
                    location_relevance="supporting",
                    rationale="Assess responsibility at this organization.",
                ),
            )
            if revision >= 9:
                from clue_api.arv2.quality_committee_tool import (
                    NominateBriefedWebCommitteeTool,
                    NominateBriefedWebInput,
                )

                tool = NominateBriefedWebCommitteeTool(scope, storage, purge_unevidenced=True)
                args = NominateBriefedWebInput(
                    name=args.name,
                    linkedin_url=args.linkedin_url,
                    source_id=source.source_id,
                    persona_key=args.persona_key,
                    role=args.role,
                    rationale="Selected from the company page.",
                    research_brief="Research Alex for this seller; inspect the supplied "
                    "operations interview and retain the complete person charter.",
                )
            first = await tool.invoke(args, ctx)
            second = await tool.invoke(args, ctx)
            assert first.references["person_job_id"] == second.references["person_job_id"]
            assert second.references["replayed"]
            members = await read_committee(
                conn, workspace_id=op.workspace_id, account_id=op.account_id, context_id=cid
            )
            assert len(members) == 1
            assert members[0].state == ("supported" if revision >= 9 else "candidate")
            assert members[0].outreach_eligible == (revision >= 9)
            if revision >= 9:
                from clue_api.arv2.person_research_brief import read_person_brief
                from clue_storage import ArtifactIntegrityError

                job = await read_job(conn, job_id=first.references["person_job_id"])
                person_scope = replace(
                    scope,
                    job_id=job.job_id,
                    subject_kind="person",
                    contact_id=job.subject_entity_id,
                    input_refs=job.input_refs,
                )
                retained = await read_person_brief(conn, storage, person_scope, context_id=cid)
                assert retained["brief"] == args.research_brief
                # Erasing an original used by the parent also erases the derived assignment.
                await conn.execute(
                    text(
                        "UPDATE artifact SET privacy_erased=true,erased_at=now() "
                        "WHERE storage_key=:key"
                    ),
                    {"key": source.artifact_key},
                )
                with pytest.raises(ArtifactIntegrityError):
                    await read_person_brief(conn, storage, person_scope, context_id=cid)

    run_async(case())
