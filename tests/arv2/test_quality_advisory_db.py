"""Founder revision six: source-reported research remains writable and fully visible."""

import json
from contextlib import asynccontextmanager
from dataclasses import replace
from uuid import UUID, uuid4

import pytest
from deepagents.backends.protocol import BackendProtocol
from sqlalchemy import text

from clue_api.arv2.quality_claims import ClaimProposal, submit_proposal
from clue_api.arv2.quality_evidence import TextSupport, grant_manifest
from clue_api.arv2.quality_execution import Allowance, bind_execution
from clue_api.arv2.quality_findings import RecordFindingInput, RecordResearchFindingTool
from clue_api.arv2.quality_page_tools import ResearchPageDraft
from clue_api.arv2.quality_pages import CitedSentence, PageSectionDraft, publish_page, read_page
from clue_api.arv2.quality_views import research_backend
from clue_api.frontend_read.contract_v1 import ResearchDisplayBlock
from clue_core import ExecutionId, OperationId
from clue_research.claimstore.quality import assess_claim
from clue_storage.fs import FsStorage
from clue_toolbelt import ToolContext
from tests.arv2.test_quality_claims_db import assessment
from tests.arv2.test_quality_evidence_db import save
from tests.arv2.test_quality_execution_db import execution
from tests.arv2.test_quality_pages_db import clinical_context
from tests.arv2.test_quality_tools_db import read_document
from tests.claimstore.conftest import (  # noqa: F401
    migrated_db,
    require_claimstore_db,
    rollback_conn,
    run_async,
)

pytestmark = pytest.mark.usefixtures("require_claimstore_db")


def test_unverified_finding_reaches_specialist_and_page_without_relationship_or_catalog(tmp_path):
    async def case():
        async with rollback_conn() as conn:
            storage = FsStorage(tmp_path)
            op, scope, _, cid, _, _ = await clinical_context(conn, storage)
            scope = replace(scope, input_refs={"quality_recipe_version": 6})
            source = await save(
                conn, storage, op, "The report suggests intake expansion.", kind="research_report"
            )
            parent = await execution(conn, op, scope.project_id)
            child = await execution(conn, op, scope.project_id, parent)
            for eid, role, pid in [
                (parent, "account_research", None),
                (child, "research_narrative", parent),
            ]:
                await bind_execution(
                    conn,
                    op,
                    execution_id=eid,
                    context_id=cid,
                    role=role,
                    parent_execution_id=pid,
                    limits=Allowance(20, 40, 10),
                )

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
            tool = RecordResearchFindingTool(scope, storage, purge_unevidenced=True)
            args = RecordFindingInput(
                operation_key="intake-source-report",
                topic="Intake expansion",
                finding={
                    "detail": "Expansion reported; timing unclear",
                    "contact": "professional@example.test",
                },
                source_ids=(source.source_id,),
                notes="Timing is uncertain; keep visible.",
            )
            receipt = await tool.invoke(args, ctx)
            assert receipt.references["status"] == "qualified"
            assert (await tool.invoke(args, ctx)).references["replayed"]
            claim_id = UUID(receipt.references["claim_id"])
            backend = research_backend(BackendProtocol(), connections, storage, scope, child)
            value = json.loads(await read_document(backend, f"/research/claim/{claim_id}/0.json"))
            assert value["value_json"]["finding"]["detail"] == args.finding["detail"]
            assert value["status"] == "qualified"

            draft = ResearchPageDraft(
                page="overview",
                sections=(
                    PageSectionDraft(
                        key="why-they-fit",
                        intro=(
                            CitedSentence(
                                text="Intake expansion may be relevant to MagicDocs; "
                                "timing is uncertain.",
                                claimIds=(claim_id,),
                                kind="inference",
                            ),
                        ),
                    ),
                    PageSectionDraft(
                        key="watch-outs",
                        intro=(
                            CitedSentence(text="This remains an uncertain finding.", kind="gap"),
                        ),
                    ),
                ),
            )
            await publish_page(
                conn,
                storage,
                scope,
                context_id=cid,
                execution_id=child,
                model="offline",
                draft=draft,
            )
            # No employment/value-narrative proof, complete-section form, or digest required.
            page = await read_page(conn, scope, context_id=cid, page="overview")
            ResearchDisplayBlock.model_validate(page["display_block"])
            # Only the designed sections, restricted as their recipes say (ruling 2026-09-29).
            sections = {s["key"]: s for s in page["display_block"]["sections"]}
            # Incident 2026-09-29: the agents' read tool served only the legacy display lane and
            # refused current-lane pages with ``overview_not_written``. It must serve the page the
            # account screen serves (same context selection), scoped by the caller's project or
            # by the account's only project.
            from clue_api.arv2.quality_read import select_quality_context
            from clue_api.arv2.read_tools import read_account_research
            from clue_config import Settings

            shown = await select_quality_context(
                conn, workspace_id=scope.workspace_id, subject_id=scope.account_id
            )
            assert shown is not None and shown.scope is not None and shown.context_id is not None
            screen = await read_page(
                conn, shown.scope, context_id=shown.context_id, page="overview"
            )
            expected = {
                x["key"]
                for x in screen["display_block"]["sections"]
                if x.get("intro") or x.get("items")
            }
            assert expected
            for project in (scope.project_id, None):
                research = await read_account_research(
                    conn,
                    workspace_id=scope.workspace_id,
                    account_entity_id=str(scope.account_id),
                    section="overview",
                    settings=Settings(_env_file=None),
                    project_id=project,
                )
                assert {x.section_key for x in research.overview} == expected
            assert sections["watch-outs"]["restricted"]
            assert not {"research-notes", "research-findings"} & sections.keys()
            assert str(claim_id) in page["cited_claim_ids"]
            # A finding the overview cites is not repeated in Insights' Miscellaneous; the
            # overview carries no findings list of its own.
            insights = await read_page(conn, scope, context_id=cid, page="insights")
            misc = next(
                s for s in insights["display_block"]["sections"] if s["key"] == "miscellaneous"
            )
            assert all(str(claim_id) not in json.dumps(i) for i in misc["items"])

            # The frontend read selects the pinned policy; it must not silently revert to v5.
            from clue_api.arv2.account_research_catalog import bundle_pin
            from clue_api.arv2.quality_catalog import load_quality_resources
            from clue_api.arv2.quality_policy import advisory_research
            from clue_api.arv2.quality_read import select_quality_context

            await conn.execute(
                text(
                    "UPDATE arv2_research_run SET profile_ref=:ref,profile_sha256=:sha "
                    "WHERE run_id=:run"
                ),
                {
                    "ref": "agent-profile:arv2-account:v4",
                    "sha": bundle_pin(load_quality_resources("arv2-account")),
                    "run": scope.run_id,
                },
            )
            selected = await select_quality_context(
                conn,
                workspace_id=scope.workspace_id,
                subject_id=scope.account_id,
                project_id=scope.project_id,
            )
            assert selected.scope and advisory_research(selected.scope)
            projected = await read_page(
                conn, selected.scope, context_id=selected.context_id, page="overview"
            )
            assert str(claim_id) in projected["cited_claim_ids"]

            row = (
                await conn.execute(
                    text("SELECT artifact_key FROM claim WHERE id=:id"), {"id": claim_id}
                )
            ).one()
            await assess_claim(
                conn,
                workspace_id=scope.workspace_id,
                entity_id=scope.account_id,
                claim_id=claim_id,
                operation_id=uuid4(),
                expected_revision=1,
                conclusion="invalid",
                rationale_key=row.artifact_key,
                support_artifacts=(),
                actor_ref="reviewer",
                context_id=cid,
                kind="withdrawal",
            )
            after = await read_page(conn, scope, context_id=cid, page="overview")
            assert "Disputed or withdrawn" not in json.dumps(after["display_block"])
            # A withdrawn finding never reaches Miscellaneous either.
            withdrawn = await read_page(conn, scope, context_id=cid, page="insights")
            assert "Expansion reported" not in json.dumps(withdrawn["display_block"])
            # A stopped evidence grant still prevents reading another execution's originals.
            from clue_api.arv2.quality_authority import resolve_authority
            from clue_api.arv2.quality_evidence import revoke_grant

            authority = await resolve_authority(conn, scope, child)
            await revoke_grant(conn, authority.grant)
            assert (await backend.aread(f"/research/claim/{claim_id}/0.json")).error

    run_async(case())


def test_catalog_shape_and_relationship_proofs_do_not_refuse_source_research(tmp_path):
    async def case():
        async with rollback_conn() as conn:
            storage = FsStorage(tmp_path)
            op, scope, _, cid, _, _ = await clinical_context(conn, storage)
            scope = replace(scope, input_refs={"quality_recipe_version": 6})
            source = await save(conn, storage, op, "Headcount is around sixty; source uncertain.")
            grant = await grant_manifest(conn, op, consumer_id=uuid4())
            for field, value in [
                ("core.employee_count", "around sixty"),
                ("account.committee_assessment", {"person": "Source-reported executive"}),
            ]:
                result = await submit_proposal(
                    conn,
                    storage,
                    scope,
                    grant,
                    ClaimProposal(
                        operation_key=field,
                        field_key=field,
                        value=value,
                        support=(
                            TextSupport(
                                source_id=source.source_id,
                                start=0,
                                end=len("Headcount is around sixty; source uncertain."),
                                quote="Headcount is around sixty; source uncertain.",
                            ),
                        ),
                        assessment=assessment(),
                    ),
                    context_id=cid,
                    actor_ref="claim-specialist",
                )
                assert result.claim_id is not None, result

    run_async(case())
