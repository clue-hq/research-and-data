"""Production completion from durable research; no providers or model purchases."""

import json
from dataclasses import replace
from uuid import UUID, uuid4

import pytest
from sqlalchemy import text

from clue_api.arv2.quality_claims import ClaimProposal, submit_proposal
from clue_api.arv2.quality_completion import (
    build_completion_report,
    completion_notes,
)
from clue_api.arv2.quality_evidence import TextSupport, grant_manifest
from clue_api.arv2.quality_json_dossier import DossierInput, FinishDossierTool
from clue_api.arv2.quality_results import ResearchUnitReport, validate_report
from clue_api.arv2.research_operations import OperationScope
from tests.arv2.test_quality_claims_db import assessment
from tests.arv2.test_quality_json_dossier_db import invoke
from tests.arv2.test_quality_person_release_db import initial
from tests.claimstore.conftest import (  # noqa: F401
    migrated_db,
    require_claimstore_db,
    rollback_conn,
    run_async,
)

pytestmark = pytest.mark.usefixtures("require_claimstore_db")


def test_backend_rebuilds_ids_and_preserves_judgment_and_readiness(tmp_path):
    async def case():
        async with rollback_conn() as conn:
            job, child, cid, storage, ctx, gen, path = await initial(conn, tmp_path)
            notes = completion_notes(
                json.dumps(
                    {
                        "summary": "Meaningful findings saved.",
                        "gaps": ["Interview unavailable"],
                        "claim_ids": ["incorrect model bookkeeping"],
                        "job_id": "wrong",
                        "pending_person_job_ids": [str(uuid4())],
                    }
                ),
                None,
            )
            with pytest.raises(ValueError, match="call finish_dossier"):
                await build_completion_report(conn, storage, job, cid, notes)
            imported = await invoke(FinishDossierTool, job, storage, ctx, DossierInput())
            report = await build_completion_report(conn, storage, job, cid, notes)
            assert set(report.claim_ids) == {UUID(i) for i in imported["claim_ids"]}
            assert report.pending_person_job_ids == (child.job_id,)
            assert report.job_id == job.job_id and report.context_id == cid
            assert report.summary == notes.summary and report.gaps == notes.gaps
            assert report.delivery["claims_imported"] is True
            assert report.delivery["narrative_published"] is False
            assert await build_completion_report(conn, storage, job, cid, notes) == report
            # Recipe 25+: the researcher writes no pages (the driver's writer does, afterwards).
            separate = replace(job, input_refs={"quality_recipe_version": 25})
            separate_report = await build_completion_report(conn, storage, separate, cid, notes)
            assert separate_report.claim_ids == report.claim_ids
            # A damaged parent pointer must not silently hide a registered child from
            # backend-built completion. Generation membership is an independent check.
            await conn.execute(
                text(
                    "UPDATE arv2_research_job SET input_refs=input_refs || "
                    "jsonb_build_object('parent_job_id',CAST(:self AS text)) WHERE job_id=:id"
                ),
                {"id": child.job_id, "self": str(child.job_id)},
            )
            with pytest.raises(ValueError, match="stored delegation.*backend repair"):
                await build_completion_report(conn, storage, job, cid, notes)
            current = replace(job, input_refs={"quality_recipe_version": 24})
            with pytest.raises(ValueError, match="read_narrative_inputs"):
                await build_completion_report(conn, storage, current, cid, notes)
            foreign = replace(job, workspace_id="unrelated-workspace")
            with pytest.raises(ValueError):
                await build_completion_report(conn, storage, foreign, cid, notes)

    run_async(case())


def test_account_committee_reference_is_context_not_person_owned_output(tmp_path):
    async def case():
        async with rollback_conn() as conn:
            job, child, cid, storage, ctx, gen, path = await initial(conn, tmp_path)
            source = (
                await conn.execute(
                    text("SELECT source_id FROM arv2_evidence_source WHERE job_id=:job LIMIT 1"),
                    {"job": job.job_id},
                )
            ).scalar_one()
            grant = await grant_manifest(
                conn,
                OperationScope(job.workspace_id, job.run_id, job.job_id, job.account_id),
                consumer_id=uuid4(),
            )
            quote = "“No — keep A | B.”"
            selection = await submit_proposal(
                conn,
                storage,
                job,
                grant,
                ClaimProposal(
                    operation_key="completion-selection",
                    field_key="account.committee_selection",
                    claim_kind="inference",
                    value={
                        "contact_id": str(child.contact_id),
                        "persona_key": "fixture",
                        "role": "other",
                        "rationale": "Fixture selection",
                    },
                    support=(TextSupport(source_id=source, start=0, end=len(quote), quote=quote),),
                    assessment=assessment(),
                ),
                context_id=cid,
                actor_ref="test",
            )
            assert selection.claim_id
            claim_id = selection.claim_id
            report = ResearchUnitReport(
                job_id=child.job_id,
                context_id=cid,
                summary="Person complete",
                committee_assessment_ids=(claim_id,),
            )
            await validate_report(conn, child, cid, report)
            # An account context reference cannot be misrepresented as person-owned output.
            with pytest.raises(ValueError, match="claim_ids.*committee_assessment_ids"):
                await validate_report(
                    conn,
                    child,
                    cid,
                    report.model_copy(
                        update={"claim_ids": (claim_id,), "committee_assessment_ids": ()}
                    ),
                )
            for invalid_scope in (
                replace(child, contact_id=uuid4()),
                replace(child, account_id=uuid4()),
                replace(child, workspace_id="different-workspace"),
            ):
                with pytest.raises(ValueError, match="committee_assessment_ids"):
                    await validate_report(conn, invalid_scope, cid, report)
            other_context = uuid4()
            with pytest.raises(ValueError, match="committee_assessment_ids"):
                await validate_report(
                    conn,
                    child,
                    other_context,
                    report.model_copy(update={"context_id": other_context}),
                )
            with pytest.raises(ValueError, match="unprocessed_source_ids.*evidence/index"):
                await validate_report(
                    conn,
                    child,
                    cid,
                    report.model_copy(update={"unprocessed_source_ids": (uuid4(),)}),
                )

    run_async(case())
