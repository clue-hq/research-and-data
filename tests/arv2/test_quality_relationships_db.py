"""Actual claim writes and reads: identity alone cannot establish committee membership."""

from dataclasses import replace
from datetime import UTC, datetime
from uuid import uuid4

import pytest
from sqlalchemy import text

from clue_api.arv2.account_research_store import create_job
from clue_api.arv2.quality_claims import ClaimProposal, ClaimSupport, submit_proposal
from clue_api.arv2.quality_evidence import TextSupport, grant_manifest
from clue_api.arv2.quality_relationships import (
    COMMITTEE,
    EMPLOYMENT,
    CommitteeAssessment,
    EmploymentAssessment,
    OrganizationScope,
    read_committee,
)
from clue_api.arv2.research_operations import OperationScope
from clue_core import IdentityBinding, UseClass
from clue_research.claimstore.quality import assess_claim
from clue_research.identity import insert_contact_entity
from clue_storage.fs import FsStorage
from tests.arv2.test_quality_claims_db import assessment, setup
from tests.arv2.test_quality_evidence_db import save
from tests.claimstore.conftest import (  # noqa: F401
    migrated_db,
    require_claimstore_db,
    rollback_conn,
    run_async,
)

pytestmark = pytest.mark.usefixtures("require_claimstore_db")


@pytest.mark.parametrize(
    "geography,location",
    [("local", "required"), ("remote", "supporting"), ("global", "not_required")],
)
def test_person_contradiction_removes_established_seat_before_refresh(
    tmp_path, geography, location
):
    async def case():
        async with rollback_conn() as conn:
            storage = FsStorage(tmp_path)
            op, account, context = await setup(conn, storage)
            contact = await insert_contact_entity(
                conn, account_entity_id=account.account_id, full_name="Fixture Decision Owner"
            )
            jid = uuid4()
            await create_job(
                conn,
                job_id=jid,
                run_id=op.run_id,
                workspace_id=op.workspace_id,
                account_entity_id=account.account_id,
                subject_type="person",
                subject_entity_id=contact,
                profile_sha256="a" * 64,
            )
            person = replace(account, job_id=jid, subject_kind="person", contact_id=contact)
            person_op = OperationScope(op.workspace_id, op.run_id, jid, op.account_id)
            original = "This person leads intake operations at this exact organization."
            source = await save(conn, storage, person_op, original)
            pg = await grant_manifest(conn, person_op, consumer_id=uuid4())
            ag = await grant_manifest(conn, op, consumer_id=uuid4())
            org = OrganizationScope(
                relationship="exact_company",
                geography=geography,
                location_relevance=location,
                rationale="Scope established by employer and remit evidence.",
            )
            employment = EmploymentAssessment(
                account_id=op.account_id,
                contact_id=contact,
                affiliation="supported",
                time_scope="current",
                assessed_on=datetime.now(UTC).date(),
                organization_scope=org,
                rationale="Direct employer evidence.",
            )
            ep = ClaimProposal(
                operation_key="employment",
                field_key=EMPLOYMENT,
                value=employment.model_dump(mode="json"),
                support=(
                    TextSupport(
                        source_id=source.source_id, start=0, end=len(original), quote=original
                    ),
                ),
                assessment=assessment(),
                identity_binding=IdentityBinding.STRONG,
                use_class=UseClass.PROFESSIONAL_PUBLIC,
            )
            er = await submit_proposal(
                conn, storage, person, pg, ep, context_id=context, actor_ref="test"
            )
            assert er.status == "supported", er
            committee = CommitteeAssessment(
                account_id=op.account_id,
                contact_id=contact,
                context_id=context,
                persona_key="operations",
                role="champion",
                state="supported",
                remit="supported",
                organization_scope=org,
                employment_claim_ids=(er.claim_id,),
                rationale="The operational responsibility matches this selected product.",
            )
            cp = ClaimProposal(
                operation_key="committee",
                field_key=COMMITTEE,
                claim_kind="inference",
                value=committee.model_dump(mode="json"),
                support=(ClaimSupport(claim_ids=(er.claim_id,)),),
                assessment=assessment(),
            )
            cr = await submit_proposal(
                conn, storage, account, ag, cp, context_id=context, actor_ref="test"
            )
            assert cr.status == "supported", cr
            members = await read_committee(
                conn, workspace_id=op.workspace_id, account_id=op.account_id, context_id=context
            )
            assert (
                len(members) == 1
                and members[0].state == "supported"
                and members[0].outreach_eligible
            )
            assert not await read_committee(
                conn, workspace_id=op.workspace_id, account_id=op.account_id, context_id=uuid4()
            )
            # No page, reconciliation or replacement is necessary for immediate safe reads.
            await assess_claim(
                conn,
                workspace_id=op.workspace_id,
                entity_id=contact,
                claim_id=er.claim_id,
                operation_id=uuid4(),
                expected_revision=1,
                conclusion="unresolved",
                kind="conflict",
                rationale_key=source.artifact_key,
                support_artifacts=(source.artifact_key,),
                actor_ref="test",
                context_id=context,
            )
            members = await read_committee(
                conn, workspace_id=op.workspace_id, account_id=op.account_id, context_id=context
            )
            assert members[0].state == "needs_verification" and not members[0].outreach_eligible
            assert "current_affiliation_not_established" in members[0].gaps
            # The original claim stays auditable and the canonical contact remains unchanged.
            assert (
                await conn.execute(
                    text("SELECT account_entity_id FROM contact_entity WHERE id=:id"),
                    {"id": contact},
                )
            ).scalar_one() == op.account_id
            assert (
                await conn.execute(
                    text("SELECT count(*) FROM claim_quality_assessment WHERE claim_id=:id"),
                    {"id": er.claim_id},
                )
            ).scalar_one() == 2

    run_async(case())
