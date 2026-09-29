"""Typed proposals prove provenance, subject boundaries and actual read effects together."""

from dataclasses import replace
from uuid import uuid4

import pytest
from sqlalchemy import text

from clue_api.arv2.account_research_claims import JobScope
from clue_api.arv2.quality_claims import (
    ClaimProposal,
    ClaimSupport,
    SemanticAssessment,
    submit_proposal,
)
from clue_api.arv2.quality_context import build_context, persist_context
from clue_api.arv2.quality_evidence import (
    EvidenceUnavailable,
    JsonSupport,
    TextSupport,
    grant_manifest,
    revoke_grant,
)
from clue_research.claimstore import WorkspaceScope, claims_for, current_value
from clue_research.claimstore.quality import assess_claim
from clue_storage import read_verified_artifact
from clue_storage.fs import FsStorage
from tests.arv2.test_quality_evidence_db import NOW, save, seed
from tests.claimstore.conftest import (  # noqa: F401
    migrated_db,
    require_claimstore_db,
    rollback_conn,
    run_async,
)

pytestmark = pytest.mark.usefixtures("require_claimstore_db")


async def setup(conn, storage):
    op, _ = await seed(conn, storage)
    row = (
        (
            await conn.execute(
                text(
                    "SELECT project_id,product_selection_version "
                    "FROM arv2_research_run WHERE run_id=:run"
                ),
                {"run": op.run_id},
            )
        )
        .mappings()
        .one()
    )
    context = await build_context(
        conn,
        storage,
        workspace_id=op.workspace_id,
        project_id=row["project_id"],
        product_selection_version=row["product_selection_version"],
    )
    cid = await persist_context(conn, storage, context)
    await conn.execute(
        text("UPDATE arv2_research_run SET context_id=:cid WHERE run_id=:run"),
        {"cid": cid, "run": op.run_id},
    )
    job = JobScope(
        workspace_id=op.workspace_id,
        project_id=row["project_id"],
        project_run_id=op.run_id,
        run_id=op.run_id,
        job_id=op.job_id,
        account_id=op.account_id,
        account_name="Fixture",
        account_domain="example.test",
        icp_markdown="",
        persona_markdown="",
        already_established="",
        effort="high",
        committee_cap=4,
        today=NOW.date(),
    )
    return op, job, cid


def assessment(**changes):
    return SemanticAssessment(
        **dict(
            entity="supported",
            field_meaning="supported",
            entailment="supported",
            relationship_direction="not_applicable",
            temporal_scope="supported",
            explanation="The source concerns this account and states this fact.",
            **changes,
        )
    )


def test_provider_value_and_web_quote_use_originals_and_replay(tmp_path):
    async def case():
        async with rollback_conn() as conn:
            storage = FsStorage(tmp_path)
            op, job, cid = await setup(conn, storage)
            source = await save(
                conn, storage, op, {"company": {"employees": 64}}, kind="provider_record", url=None
            )
            grant = await grant_manifest(conn, op, consumer_id=uuid4())
            proposal = ClaimProposal(
                operation_key="employees",
                field_key="core.employee_count",
                value=64,
                support=(
                    JsonSupport(
                        source_id=source.source_id, pointer="/company/employees", expected_value=64
                    ),
                ),
                assessment=assessment(),
            )
            result = await submit_proposal(
                conn, storage, job, grant, proposal, context_id=cid, actor_ref="claim-specialist"
            )
            assert result.status == "supported"
            assert (
                await submit_proposal(
                    conn,
                    storage,
                    job,
                    grant,
                    proposal,
                    context_id=cid,
                    actor_ref="claim-specialist",
                )
            ).replayed
            scope = WorkspaceScope.for_workspace(op.workspace_id)
            claims = await claims_for(conn, op.account_id, scope=scope)
            assert len(claims) == 1 and claims[0].source_url is None
            assert claims[0].artifact_key == source.artifact_key
            assert (
                await current_value(conn, op.account_id, "core.employee_count", scope=scope)
            ).value_json == 64
            await revoke_grant(conn, grant)
            with pytest.raises(EvidenceUnavailable):
                await submit_proposal(
                    conn,
                    storage,
                    job,
                    grant,
                    proposal,
                    context_id=cid,
                    actor_ref="claim-specialist",
                )

    run_async(case())


def test_joined_quote_and_report_as_primary_fact_are_refused_without_copying_bad_text(tmp_path):
    async def case():
        async with rollback_conn() as conn:
            storage = FsStorage(tmp_path)
            op, job, cid = await setup(conn, storage)
            source = await save(
                conn, storage, op, "We use intake. Separate sentence. We use referrals."
            )
            report = await save(
                conn, storage, op, "A synthesis says accredited.", kind="research_report"
            )
            grant = await grant_manifest(conn, op, consumer_id=uuid4())
            invalid = ClaimProposal(
                operation_key="joined",
                field_key="account.intake_workflow",
                value="Uses intake and referrals",
                support=(
                    TextSupport(
                        source_id=source.source_id,
                        start=0,
                        end=25,
                        quote="We use intake and referrals.",
                    ),
                ),
                assessment=assessment(),
            )
            receipt = await submit_proposal(
                conn, storage, job, grant, invalid, context_id=cid, actor_ref="claim-specialist"
            )
            assert receipt.status == "refused" and receipt.claim_id is None
            key = (
                await conn.execute(
                    text("SELECT proposal_key FROM arv2_quality_proposal WHERE operation_id=:id"),
                    {"id": receipt.operation_id},
                )
            ).scalar_one()
            _, raw = await read_verified_artifact(
                conn, storage, workspace_id=op.workspace_id, storage_key=key
            )
            assert b"referrals" not in raw
            report_proposal = invalid.model_copy(
                update={
                    "operation_key": "report",
                    "support": (
                        TextSupport(
                            source_id=report.source_id,
                            start=0,
                            end=27,
                            quote="A synthesis says accredited.",
                        ),
                    ),
                }
            )
            assert (
                await submit_proposal(
                    conn,
                    storage,
                    job,
                    grant,
                    report_proposal,
                    context_id=cid,
                    actor_ref="claim-specialist",
                )
            ).status == "refused"
            assert not await claims_for(
                conn,
                op.account_id,
                scope=WorkspaceScope.for_workspace(op.workspace_id),
                include_superseded=True,
            )

    run_async(case())


def test_semantically_invalid_observation_stays_auditable_and_context_is_exact(tmp_path):
    async def case():
        async with rollback_conn() as conn:
            storage = FsStorage(tmp_path)
            op, job, cid = await setup(conn, storage)
            body = "The company received a magazine ranking."
            source = await save(conn, storage, op, body)
            grant = await grant_manifest(conn, op, consumer_id=uuid4())
            semantic = assessment().model_copy(
                update={
                    "field_meaning": "contradicted",
                    "explanation": "A magazine ranking does not establish accreditation.",
                }
            )
            proposal = ClaimProposal(
                operation_key="ranking",
                field_key="account.accreditation",
                value="Accredited",
                support=(
                    TextSupport(source_id=source.source_id, start=0, end=len(body), quote=body),
                ),
                assessment=semantic,
            )
            with pytest.raises(EvidenceUnavailable):
                await submit_proposal(
                    conn,
                    storage,
                    job,
                    grant,
                    proposal,
                    context_id=uuid4(),
                    actor_ref="claim-specialist",
                )
            with pytest.raises(EvidenceUnavailable):
                await submit_proposal(
                    conn,
                    storage,
                    replace(job, account_id=uuid4()),
                    grant,
                    proposal,
                    context_id=cid,
                    actor_ref="claim-specialist",
                )
            receipt = await submit_proposal(
                conn, storage, job, grant, proposal, context_id=cid, actor_ref="claim-specialist"
            )
            assert receipt.status == "invalid" and receipt.claim_id
            scope = WorkspaceScope.for_workspace(op.workspace_id)
            assert not await claims_for(conn, op.account_id, scope=scope)
            assert (
                len(await claims_for(conn, op.account_id, scope=scope, include_superseded=True))
                == 1
            )
            row = (
                await conn.execute(
                    text(
                        "SELECT description FROM workspace_field_definition WHERE workspace_id=:ws "
                        "AND field_key='account.accreditation'"
                    ),
                    {"ws": op.workspace_id},
                )
            ).scalar_one()
            assert "magazine" not in row and "ranking" not in row

    run_async(case())


def test_inference_uses_shared_support_edges_and_disappears_when_support_is_withdrawn(tmp_path):
    async def case():
        async with rollback_conn() as conn:
            storage = FsStorage(tmp_path)
            op, job, context = await setup(conn, storage)
            source = await save(
                conn, storage, op, {"employees": 64}, kind="provider_record", url=None
            )
            grant = await grant_manifest(conn, op, consumer_id=uuid4())
            fact = ClaimProposal(
                operation_key="employees",
                field_key="core.employee_count",
                value=64,
                support=(
                    JsonSupport(
                        source_id=source.source_id, pointer="/employees", expected_value=64
                    ),
                ),
                assessment=assessment(),
            )
            first = await submit_proposal(
                conn, storage, job, grant, fact, context_id=context, actor_ref="claim-specialist"
            )
            inference = ClaimProposal(
                operation_key="interpretation",
                field_key="account.team_size_context",
                value="A team of this size may share operational roles.",
                claim_kind="inference",
                support=(ClaimSupport(claim_ids=(first.claim_id,)),),
                assessment=assessment(),
            )
            second = await submit_proposal(
                conn,
                storage,
                job,
                grant,
                inference,
                context_id=context,
                actor_ref="claim-specialist",
            )
            assert second.status == "supported"
            assert (
                await conn.execute(
                    text(
                        "SELECT supporting_claim_id FROM claim_derivation "
                        "WHERE derived_claim_id=:id"
                    ),
                    {"id": second.claim_id},
                )
            ).scalar_one() == first.claim_id
            scope = WorkspaceScope.for_workspace(op.workspace_id)
            assert len(await claims_for(conn, op.account_id, scope=scope)) == 2
            await assess_claim(
                conn,
                workspace_id=op.workspace_id,
                entity_id=op.account_id,
                claim_id=first.claim_id,
                operation_id=uuid4(),
                expected_revision=1,
                conclusion="invalid",
                rationale_key=source.artifact_key,
                actor_ref="claim-specialist",
                support_artifacts=(source.artifact_key,),
                context_id=context,
                kind="withdrawal",
            )
            assert not await claims_for(conn, op.account_id, scope=scope)
            assert (
                len(await claims_for(conn, op.account_id, scope=scope, include_superseded=True))
                == 2
            )

    run_async(case())
