"""C7.9 production reader, governance, and owner-reference integration."""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import event, text

from clue_api.research_view_governance import CurrentStatementGovernanceEvaluator
from clue_api.research_view_owner_refs import ProductionOwnerReferenceResolver
from clue_api.research_view_runtime import ProductionResearchViewComposer
from clue_config import DEFAULT_STAGE0_POLICY, load_settings
from clue_core import (
    AccountStatus,
    Claim,
    ClaimFlavor,
    EntityType,
    ExtractionMethod,
    FieldDef,
    ICPCreatedFrom,
    IdentityBinding,
    PassKind,
    ProjectPhase,
    ReadinessGate,
    ResearchDataSpecies,
    ResearchMode,
    ResearchOwnedReference,
    ResearchSectionKind,
    ResearchStatement,
    ResearchSubjectRef,
    ResearchSupportRef,
    ResearchSupportRole,
    ResearchViewReadRequest,
    ReuseScope,
    UseClass,
    VerificationStatus,
    account_claim,
    contact_claim,
    new_operation_id,
    new_project_run_id,
    new_run_id,
)
from clue_db import db_lifespan, transaction
from clue_research.claimstore import (
    DerivationStore,
    ResearchViewFieldRoute,
    SeedField,
    WorkspaceScope,
    current_field_claims_resolved_for_product,
    derivation_supports,
    insert_claim,
    load_pack,
    record_verification,
    supersede_claim,
)
from clue_research.compliance import build_tombstone
from clue_research.durable import (
    AccountRunStatus,
    append_subject_activity,
    ensure_project_run,
    insert_account_run,
    save_references,
)
from clue_research.icp import create_icp_spec
from clue_research.identity import insert_account_entity, insert_contact_entity, stamp_reuse
from clue_research.narrative import (
    ResearchStatementCandidate,
    ResearchViewCompositionError,
)
from clue_research.stage0 import compile_product_context, evaluate_readiness
from clue_spine import create_brand, create_product, create_project
from tests._workspace import seed_workspace
from tests.db.conftest import run_async
from tests.profiling.conftest import conn_session_factory, rollback_conn

pytestmark = pytest.mark.usefixtures("require_profiling_db")

_WORKSPACE = "c7-production-readers"
_PRODUCT = "product-c7-reader"
_ICP_KEY = "enterprise"


def _section(view, kind: ResearchSectionKind):
    return next(section for section in view.sections if section.kind is kind)


@pytest.mark.parametrize("probe_count", (0, 24, 99))
def test_real_account_view_and_owner_references_compose_from_persisted_authorities(
    probe_count: int,
) -> None:
    """The production wrapper uses all real readers and emits no fixture-owned payload."""

    async def scenario() -> None:
        async with rollback_conn() as conn:
            await seed_workspace(conn, _WORKSPACE)
            brand = await create_brand(conn, workspace_id=_WORKSPACE, name="C7 reader brand")
            await create_product(
                conn,
                workspace_id=_WORKSPACE,
                brand_id=brand.brand_id,
                product_id=_PRODUCT,
                name="C7 reader product",
            )
            project = await create_project(
                conn,
                workspace_id=_WORKSPACE,
                brand_id=brand.brand_id,
                product_id=_PRODUCT,
                name="C7 reader project",
            )
            client_entity = await insert_account_entity(
                conn,
                canonical_name="C7 Reader Client",
                primary_domain="c7-reader-client.example",
                status=AccountStatus.ACTIVE,
                workspace_id=_WORKSPACE,
            )
            await create_icp_spec(
                conn,
                workspace_id=_WORKSPACE,
                icp_key=_ICP_KEY,
                created_from=ICPCreatedFrom.SYNTHESIS,
                activate=True,
                client_entity_id=client_entity,
                client_kb_version=1,
                product_id=_PRODUCT,
            )
            product_context = await compile_product_context(
                conn,
                workspace_id=_WORKSPACE,
                brand_id=brand.brand_id,
                product_id=_PRODUCT,
                client_entity_id=client_entity,
                client_kb_version=1,
                claim_refs=(),
            )
            readiness = await evaluate_readiness(
                conn,
                workspace_id=_WORKSPACE,
                brand_id=brand.brand_id,
                product_id=_PRODUCT,
                project_id=project.project_id,
                client_entity_id=client_entity,
                client_kb_version=1,
                icp_key=_ICP_KEY,
                icp_version=1,
                product_context_version_id=product_context.version_id,
                gate=ReadinessGate.DISCOVERY_SPEND,
                spec=DEFAULT_STAGE0_POLICY.readiness,
                metrics={
                    "coverage_ratio": 1.0,
                    "verified_claims": 1,
                    "open_policy_blocks": 0,
                },
                created_by_actor="agent",
            )
            project_run_id = new_project_run_id()
            await ensure_project_run(
                conn,
                project_run_id=project_run_id,
                project_id=project.project_id,
                workspace_id=_WORKSPACE,
                icp_key=_ICP_KEY,
                icp_version=1,
                client_entity_id=client_entity,
                client_kb_version=1,
                product_id=_PRODUCT,
                product_context_version_id=product_context.version_id,
                readiness_decision_id=readiness.readiness_decision_id,
                phase=ProjectPhase.HANDOFF,
            )
            account_id = await insert_account_entity(
                conn,
                canonical_name="C7 Reader Target",
                primary_domain="c7-reader.example",
                status=AccountStatus.ACTIVE,
                workspace_id=_WORKSPACE,
            )
            account_run_id = new_run_id()
            await insert_account_run(
                conn,
                account_run_id=account_run_id,
                project_run_id=project_run_id,
                entity_id=account_id,
                tier="top",
                status=AccountRunStatus.DONE,
            )

            pain = account_claim(
                entity_id=account_id,
                field_key="account.operational_pain",
                value_json="Manual handoffs slow down the revenue team.",
                source_tier=1,
                extraction_method=ExtractionMethod.API,
                confidence=0.94,
                run_id=account_run_id,
                research_mode=ResearchMode.ACCOUNT_PROFILING,
                source_url="https://c7-reader.example/company-update",
                evidence_span="The revenue team described manual handoffs as a bottleneck.",
            )
            pain_id = await insert_claim(conn, stamp_reuse(pain, workspace_id=_WORKSPACE))
            await record_verification(
                conn, pain_id, status=VerificationStatus.VERIFIED, corroborations=2
            )
            bulk_fields = tuple(
                f"account.resonance.c7_query_probe_{index:02d}" for index in range(probe_count)
            )
            await load_pack(
                conn,
                tuple(
                    SeedField(
                        field_def=FieldDef(
                            field_key=field_key,
                            value_type="str",
                            pass_kind=PassKind.DEEP,
                            reuse_scope=ReuseScope.TENANT_PRIVATE,
                        ),
                        value_schema={"type": "string"},
                        research_view_route=ResearchViewFieldRoute(
                            field_key=field_key,
                            entity_type=EntityType.ACCOUNT,
                            section_kind=ResearchSectionKind.INSIGHTS,
                            ordinal=100 + index,
                            context_scope=(
                                "project_run_pinned" if index == 0 else "subject_current"
                            ),
                            product_mode=("exact_required" if index == 0 else "neutral_or_exact"),
                        ),
                    )
                    for index, field_key in enumerate(bulk_fields)
                ),
            )
            bulk_claim_ids = []
            for index, field_key in enumerate(bulk_fields):
                bulk_claim = account_claim(
                    entity_id=account_id,
                    field_key=field_key,
                    value_json=f"Batch-governed research fact {index}.",
                    source_tier=1,
                    extraction_method=ExtractionMethod.API,
                    confidence=0.9,
                    run_id=account_run_id,
                    research_mode=ResearchMode.ACCOUNT_PROFILING,
                    source_url=f"https://c7-reader.example/research/{index}",
                    evidence_span=f"Evidence for batch-governed fact {index}.",
                )
                stamped_bulk_claim = stamp_reuse(bulk_claim, workspace_id=_WORKSPACE)
                if index == 0:
                    stamped_bulk_claim = stamped_bulk_claim.model_copy(
                        update={"product_id": _PRODUCT}
                    )
                bulk_claim_id = await insert_claim(conn, stamped_bulk_claim)
                await record_verification(
                    conn,
                    bulk_claim_id,
                    status=VerificationStatus.VERIFIED,
                )
                bulk_claim_ids.append(bulk_claim_id)
            if bulk_fields:
                foreign_run_claim = account_claim(
                    entity_id=account_id,
                    field_key=bulk_fields[0],
                    value_json="A newer fact from a different project-run scope.",
                    source_tier=1,
                    extraction_method=ExtractionMethod.API,
                    confidence=0.99,
                    run_id=new_run_id(),
                    research_mode=ResearchMode.ACCOUNT_PROFILING,
                    source_url="https://c7-reader.example/foreign-run",
                    evidence_span="This fact belongs to another project run.",
                )
                foreign_run_claim = stamp_reuse(
                    foreign_run_claim, workspace_id=_WORKSPACE
                ).model_copy(update={"product_id": _PRODUCT})
                foreign_run_claim_id = await insert_claim(conn, foreign_run_claim)
                await record_verification(
                    conn,
                    foreign_run_claim_id,
                    status=VerificationStatus.VERIFIED,
                )

            score = account_claim(
                entity_id=account_id,
                field_key="account.scoring.fit",
                value_json={
                    "value": 0.82,
                    "components": [
                        {
                            "field_key": "account.operational_pain",
                            "score": 0.82,
                            "weight": 1.0,
                            "evidence_claim_ids": [str(pain_id)],
                        }
                    ],
                    "rubric_version": 1,
                    "icp_key": _ICP_KEY,
                    "icp_version": 1,
                    "project_run_id": str(project_run_id),
                },
                source_tier=1,
                extraction_method=ExtractionMethod.API,
                confidence=1.0,
                run_id=account_run_id,
                research_mode=ResearchMode.ACCOUNT_PROFILING,
                source_url="https://c7-reader.example/internal-score",
            )
            score = stamp_reuse(score, workspace_id=_WORKSPACE).model_copy(
                update={"product_id": _PRODUCT}
            )
            score_id = await insert_claim(conn, score)
            await record_verification(conn, score_id, status=VerificationStatus.VERIFIED)
            contact_id = await insert_contact_entity(
                conn,
                account_entity_id=account_id,
                full_name="Jordan C7 Reader",
                linkedin_url="https://linkedin.com/in/jordan-c7-reader",
                status=AccountStatus.ACTIVE,
            )
            public_quote = contact_claim(
                entity_id=contact_id,
                field_key="contact.facet.recent_post",
                value_json="Reliable revenue workflows should remove repetitive handoffs.",
                source_tier=1,
                extraction_method=ExtractionMethod.API,
                confidence=0.91,
                run_id=account_run_id,
                research_mode=ResearchMode.CONTACT_PROFILING,
                identity_binding=IdentityBinding.STRONG,
                use_class=UseClass.PERSONAL_PUBLIC_NON_SENSITIVE,
                source_url="https://c7-reader.example/jordan-public-post",
                evidence_span=(
                    "Jordan wrote that reliable revenue workflows should remove repetitive "
                    "handoffs."
                ),
            )
            public_quote = stamp_reuse(public_quote, workspace_id=_WORKSPACE).model_copy(
                update={"product_id": _PRODUCT}
            )
            public_quote_id = await insert_claim(conn, public_quote)
            await record_verification(conn, public_quote_id, status=VerificationStatus.VERIFIED)
            await save_references(
                conn,
                account_run_id,
                references_index={
                    "account": [
                        str(pain_id),
                        str(score_id),
                        *(str(claim_id) for claim_id in bulk_claim_ids),
                    ],
                    "contacts": [str(public_quote_id)],
                },
                cost_cents=Decimal(0),
                status=AccountRunStatus.DONE,
            )
            await append_subject_activity(
                conn,
                workspace_id=_WORKSPACE,
                project_id=project.project_id,
                project_run_id=project_run_id,
                account_run_id=account_run_id,
                subject_entity_id=account_id,
                subject_entity_type=EntityType.ACCOUNT,
                product_id=_PRODUCT,
                owner_event_ref=f"run-event:{account_run_id}:research-completed",
                event_kind="research_completed",
                actor_category="agent",
                occurred_at=datetime(2026, 7, 30, 12, 0, tzinfo=UTC),
            )

            request = ResearchViewReadRequest(
                workspace_id=_WORKSPACE,
                project_id=project.project_id,
                project_run_id=project_run_id,
                subject_entity_id=account_id,
                subject_entity_type=EntityType.ACCOUNT,
                product_id=_PRODUCT,
            )
            conn_factory = conn_session_factory(conn)
            composer = ProductionResearchViewComposer(conn_factory=conn_factory)
            account_query_count = 0

            def count_account_query(*_args: object) -> None:
                nonlocal account_query_count
                account_query_count += 1

            event.listen(
                conn.sync_connection,
                "before_cursor_execute",
                count_account_query,
            )
            try:
                first = await composer.compose(request)
            finally:
                event.remove(
                    conn.sync_connection,
                    "before_cursor_execute",
                    count_account_query,
                )
            # The production path composes and governs 1/25/100 statements with one bounded query
            # plan. A per-statement governance/connection loop would blow through this ceiling.
            # Raised 30 → 31 by R11.5 (the M8D committee bridge): the committee read now asks which
            # account-research fleet run describes this project run before it reads references. That
            # is one bounded lookup for the whole composition, constant in statement count — exactly
            # what this ceiling exists to distinguish from a per-statement loop.
            assert account_query_count <= 31
            second = await composer.compose(request)

            assert first.source_state_sha256 == second.source_state_sha256
            insight = _section(first, ResearchSectionKind.INSIGHTS)
            statements = tuple(
                item for item in insight.items if isinstance(item, ResearchStatement)
            )
            assert len(statements) == probe_count + 1
            pain_statement = next(
                statement for statement in statements if statement.claim_id == pain_id
            )
            assert pain_statement.value_json == pain.value_json
            assert pain_statement.state.availability.value == "available"
            if bulk_fields:
                pinned_statement = next(
                    statement
                    for statement in statements
                    if str(statement.field_key) == bulk_fields[0]
                )
                assert pinned_statement.value_json == "Batch-governed research fact 0."
            assert {action.kind.value for action in pain_statement.evidence_actions} == {
                "open_public_source"
            }

            references = tuple(
                item
                for section in first.sections
                for item in section.items
                if isinstance(item, ResearchOwnedReference)
            )
            species = {item.data_species for item in references}
            assert {
                ResearchDataSpecies.IDENTITY,
                ResearchDataSpecies.EXECUTION,
                ResearchDataSpecies.SCORE,
                ResearchDataSpecies.ACTIVITY,
            } <= species
            assert next(
                item for item in references if item.data_species is ResearchDataSpecies.SCORE
            ).evidence_claim_ids == (pain_id,)

            resolved = await ProductionOwnerReferenceResolver(
                composer, conn_factory=conn_factory
            ).resolve(request, references)
            assert len(resolved) == len(references)
            assert all(item.etag and item.owner_version for item in resolved)
            score_value = next(
                item.value_json
                for item in resolved
                if item.reference.data_species is ResearchDataSpecies.SCORE
            )
            assert isinstance(score_value, dict)
            assert score_value["score"]["value"] == 0.82

            exact_route = ResearchViewFieldRoute(
                field_key="account.operational_pain",
                entity_type=EntityType.ACCOUNT,
                section_kind=ResearchSectionKind.INSIGHTS,
                product_mode="exact_required",
            )
            assert (
                await current_field_claims_resolved_for_product(
                    conn,
                    member_entity_ids=(account_id,),
                    routes=(exact_route,),
                    scope=WorkspaceScope.for_workspace(_WORKSPACE),
                    product_id=None,
                )
                == ()
            )

            with pytest.raises(ResearchViewCompositionError, match="subject_not_found"):
                await composer.compose(request.model_copy(update={"product_id": "another-product"}))

            contact_request = ResearchViewReadRequest(
                workspace_id=_WORKSPACE,
                project_id=project.project_id,
                project_run_id=project_run_id,
                subject_entity_id=contact_id,
                subject_entity_type=EntityType.CONTACT,
                product_id=_PRODUCT,
            )
            contact_view = await composer.compose(contact_request)
            quote_items = tuple(
                item
                for item in _section(contact_view, ResearchSectionKind.QUOTES).items
                if isinstance(item, ResearchStatement)
            )
            assert [item.claim_id for item in quote_items] == [public_quote_id]
            assert quote_items[0].state.availability.value == "available"
            assert quote_items[0].state.outreach_decision.value == "denied"
            assert _section(contact_view, ResearchSectionKind.PERSONALIZATION).items == ()

    run_async(scenario())


def test_personalization_cannot_launder_a_support_denied_for_outreach() -> None:
    """C7-D7 applies requested-use policy to every required transitive support."""

    async def scenario() -> None:
        async with rollback_conn() as conn:
            await seed_workspace(conn, _WORKSPACE)
            brand = await create_brand(conn, workspace_id=_WORKSPACE, name="C7 governance brand")
            await create_product(
                conn,
                workspace_id=_WORKSPACE,
                brand_id=brand.brand_id,
                product_id=_PRODUCT,
                name="C7 governance product",
            )
            account_id = await insert_account_entity(
                conn,
                canonical_name="C7 Governance Target",
                primary_domain="c7-governance.example",
                status=AccountStatus.ACTIVE,
                workspace_id=_WORKSPACE,
            )
            contact_id = await insert_contact_entity(
                conn,
                account_entity_id=account_id,
                full_name="Jordan Example",
                linkedin_url="https://linkedin.com/in/jordan-c7-governance",
                status=AccountStatus.ACTIVE,
            )
            personalization_field = "contact.personalization.recent_post_angle"
            await load_pack(
                conn,
                (
                    SeedField(
                        field_def=FieldDef(
                            field_key=personalization_field,
                            value_type="str",
                            pass_kind=PassKind.DEEP,
                            reuse_scope=ReuseScope.TENANT_PRIVATE,
                        ),
                        value_schema={"type": "string"},
                        research_view_route=ResearchViewFieldRoute(
                            field_key=personalization_field,
                            entity_type=EntityType.CONTACT,
                            section_kind=ResearchSectionKind.PERSONALIZATION,
                            purpose="personalization_candidate",
                            context_scope="project_run_pinned",
                            product_mode="exact_required",
                        ),
                    ),
                ),
            )
            run_id = new_run_id()
            support = contact_claim(
                entity_id=contact_id,
                field_key="contact.facet.recent_post",
                value_json="Spoke publicly about reliable customer-data workflows.",
                source_tier=1,
                extraction_method=ExtractionMethod.API,
                confidence=0.93,
                run_id=run_id,
                research_mode=ResearchMode.CONTACT_PROFILING,
                identity_binding=IdentityBinding.STRONG,
                use_class=UseClass.PERSONAL_PUBLIC_NON_SENSITIVE,
                source_url="https://c7-governance.example/public-post",
                evidence_span="Jordan discussed reliable customer-data workflows.",
            )
            support = stamp_reuse(support, workspace_id=_WORKSPACE).model_copy(
                update={"product_id": _PRODUCT}
            )
            support_id = await insert_claim(conn, support)
            await record_verification(conn, support_id, status=VerificationStatus.VERIFIED)

            derived = Claim(
                entity_id=contact_id,
                entity_type=EntityType.CONTACT,
                field_key=personalization_field,
                value_json="Open by referencing Jordan's public comments on reliable workflows.",
                source_tier=4,
                extraction_method=ExtractionMethod.LLM_SYNTHESIS,
                confidence=0.81,
                run_id=run_id,
                research_mode=ResearchMode.CONTACT_PROFILING,
                identity_binding=IdentityBinding.STRONG,
                use_class=UseClass.PERSONAL_PUBLIC_NON_SENSITIVE,
                claim_flavor=ClaimFlavor.DERIVED,
                reuse_scope=ReuseScope.TENANT_PRIVATE,
                workspace_id=_WORKSPACE,
                product_id=_PRODUCT,
                verification_status=VerificationStatus.VERIFIED,
            )
            support_ref = ResearchSupportRef(
                claim_id=support_id,
                role=ResearchSupportRole.DIRECT_EVIDENCE,
                ordinal=0,
            )
            await DerivationStore().create(
                conn,
                derived,
                ResearchSubjectRef(
                    entity_id=contact_id,
                    entity_type=EntityType.CONTACT,
                    canonical_entity_version=1,
                    parent_account_id=account_id,
                ),
                (support_ref,),
                workspace_id=_WORKSPACE,
                operation_id=new_operation_id(),
                scope=WorkspaceScope.for_workspace(_WORKSPACE),
            )
            await conn.execute(
                text(
                    """
                    INSERT INTO use_decision (
                        claim_id, usable_for_outreach, reason, regime, policy_version
                    ) VALUES
                        (:root_id, true, 'allowed', 'strict', 1),
                        (
                            :support_id, false, 'use_class_disallowed_for_regime',
                            'strict', 1
                        )
                    """
                ),
                {"root_id": derived.id, "support_id": support_id},
            )

            request = ResearchViewReadRequest(
                workspace_id=_WORKSPACE,
                project_id="project-governance",
                project_run_id=new_project_run_id(),
                subject_entity_id=contact_id,
                subject_entity_type=EntityType.CONTACT,
                product_id=_PRODUCT,
            )
            subject = ResearchSubjectRef(
                entity_id=contact_id,
                entity_type=EntityType.CONTACT,
                canonical_entity_version=1,
                parent_account_id=account_id,
            )
            candidate = ResearchStatementCandidate(
                section_kind=ResearchSectionKind.PERSONALIZATION,
                claim=derived,
                supports=await derivation_supports(conn, derived.id),
            )
            evaluator = CurrentStatementGovernanceEvaluator(conn, member_entity_ids=(contact_id,))
            denied = (await evaluator.evaluate(request, subject, (candidate,)))[derived.id]
            assert denied.state.availability.value == "available"
            assert denied.state.outreach_decision.value == "denied"
            assert "outreach_policy_denied" in denied.state.reason_codes

            await conn.execute(
                text(
                    """
                    UPDATE use_decision
                    SET usable_for_outreach = true, reason = 'allowed'
                    WHERE claim_id = :claim_id
                    """
                ),
                {"claim_id": support_id},
            )
            allowed = (await evaluator.evaluate(request, subject, (candidate,)))[derived.id]
            assert allowed.state.outreach_decision.value == "allowed"

    run_async(scenario())


def test_flagged_derived_root_cannot_mask_erased_required_support() -> None:
    """A redacted dependency outranks the root's otherwise displayable review-required state."""

    async def scenario() -> None:
        async with rollback_conn() as conn:
            await seed_workspace(conn, _WORKSPACE)
            brand = await create_brand(conn, workspace_id=_WORKSPACE, name="C7 redaction brand")
            await create_product(
                conn,
                workspace_id=_WORKSPACE,
                brand_id=brand.brand_id,
                product_id=_PRODUCT,
                name="C7 redaction product",
            )
            account_id = await insert_account_entity(
                conn,
                canonical_name="C7 Redaction Target",
                primary_domain="c7-redaction.example",
                status=AccountStatus.ACTIVE,
                workspace_id=_WORKSPACE,
            )
            contact_id = await insert_contact_entity(
                conn,
                account_entity_id=account_id,
                full_name="Jordan Redaction",
                status=AccountStatus.ACTIVE,
            )
            derived_field = "contact.personalization.erased_support_precedence"
            await load_pack(
                conn,
                (
                    SeedField(
                        field_def=FieldDef(
                            field_key=derived_field,
                            value_type="str",
                            pass_kind=PassKind.DEEP,
                            reuse_scope=ReuseScope.TENANT_PRIVATE,
                        ),
                        value_schema={"type": "string"},
                    ),
                ),
            )
            support = stamp_reuse(
                contact_claim(
                    entity_id=contact_id,
                    field_key="contact.facet.recent_post",
                    value_json="A support value that must be erased.",
                    source_tier=1,
                    extraction_method=ExtractionMethod.API,
                    confidence=0.9,
                    run_id=new_run_id(),
                    research_mode=ResearchMode.CONTACT_PROFILING,
                    identity_binding=IdentityBinding.STRONG,
                    use_class=UseClass.PERSONAL_PUBLIC_NON_SENSITIVE,
                    source_url="https://c7-redaction.example/public-post",
                    evidence_span="Jordan published the support value.",
                ),
                workspace_id=_WORKSPACE,
            ).model_copy(
                update={
                    "reuse_scope": ReuseScope.TENANT_PRIVATE,
                    "workspace_id": _WORKSPACE,
                    "product_id": _PRODUCT,
                }
            )
            support_id = await insert_claim(conn, support)
            await record_verification(
                conn,
                support_id,
                status=VerificationStatus.VERIFIED,
            )
            derived = Claim(
                entity_id=contact_id,
                entity_type=EntityType.CONTACT,
                field_key=derived_field,
                value_json="A benign-looking derived statement.",
                source_tier=4,
                extraction_method=ExtractionMethod.LLM_SYNTHESIS,
                confidence=0.75,
                run_id=new_run_id(),
                research_mode=ResearchMode.CONTACT_PROFILING,
                identity_binding=IdentityBinding.STRONG,
                use_class=UseClass.PERSONAL_PUBLIC_NON_SENSITIVE,
                claim_flavor=ClaimFlavor.DERIVED,
                reuse_scope=ReuseScope.TENANT_PRIVATE,
                workspace_id=_WORKSPACE,
                product_id=_PRODUCT,
                verification_status=VerificationStatus.FLAGGED,
            )
            support_ref = ResearchSupportRef(
                claim_id=support_id,
                role=ResearchSupportRole.DIRECT_EVIDENCE,
                ordinal=0,
            )
            await DerivationStore().create(
                conn,
                derived,
                ResearchSubjectRef(
                    entity_id=contact_id,
                    entity_type=EntityType.CONTACT,
                    canonical_entity_version=1,
                    parent_account_id=account_id,
                ),
                (support_ref,),
                workspace_id=_WORKSPACE,
                operation_id=new_operation_id(),
                scope=WorkspaceScope.for_workspace(_WORKSPACE),
            )

            tombstone = build_tombstone(support, run_id=new_run_id())
            await conn.execute(
                text(
                    """
                    INSERT INTO dsar_tombstone (
                        erased_claim_id, tombstone_claim_id, contact_entity_id,
                        workspace_id, reason, scope
                    ) VALUES (
                        :erased, :tombstone, :contact, :workspace, 'erasure', 'all'
                    )
                    """
                ),
                {
                    "erased": support_id,
                    "tombstone": tombstone.id,
                    "contact": contact_id,
                    "workspace": _WORKSPACE,
                },
            )
            await supersede_claim(
                conn,
                support_id,
                tombstone,
                validate_field=False,
            )

            request = ResearchViewReadRequest(
                workspace_id=_WORKSPACE,
                project_id="project-redaction-precedence",
                project_run_id=new_project_run_id(),
                subject_entity_id=contact_id,
                subject_entity_type=EntityType.CONTACT,
                product_id=_PRODUCT,
            )
            subject = ResearchSubjectRef(
                entity_id=contact_id,
                entity_type=EntityType.CONTACT,
                canonical_entity_version=1,
                parent_account_id=account_id,
            )
            candidate = ResearchStatementCandidate(
                section_kind=ResearchSectionKind.PERSONALIZATION,
                claim=derived,
                supports=await derivation_supports(conn, derived.id),
            )
            decision = (
                await CurrentStatementGovernanceEvaluator(
                    conn,
                    member_entity_ids=(contact_id,),
                ).evaluate(request, subject, (candidate,))
            )[derived.id]

            assert decision.state.availability.value == "redacted"
            assert decision.state.reason_codes == ("dependency_erased",)
            assert decision.evidence_actions == ()

    run_async(scenario())


def test_enabled_production_app_starts_with_real_c7_collaborators(tmp_path) -> None:
    """Flag-on startup migrates/loads route metadata and serves the canonical route."""

    from clue_api.projections_main import build_application

    async def registered_field_keys() -> set[str]:
        async with db_lifespan(), transaction() as conn:
            rows = await conn.execute(text("SELECT field_key FROM field_definition"))
            return {str(row[0]) for row in rows}

    async def remove_newly_registered_fields(existing: set[str]) -> None:
        # Production startup correctly commits the global field/route registry. Keep this test
        # hermetic, however: several older DB-gated tests intentionally register local definitions
        # for core field keys inside rollback transactions. Routes disappear through the migration's
        # ON DELETE CASCADE FK.
        async with db_lifespan(), transaction() as conn:
            if existing:
                await conn.execute(
                    text(
                        """
                        DELETE FROM field_definition
                        WHERE NOT (field_key = ANY(:existing))
                        """
                    ),
                    {"existing": sorted(existing)},
                )
            else:
                await conn.execute(text("DELETE FROM field_definition"))

    existing_fields = run_async(registered_field_keys())
    settings = load_settings(
        _env_file=None,
        storage_backend="fs",
        storage_fs_root=str(tmp_path / "artifacts"),
        c7_research_view_read_enabled=True,
    )
    try:
        app = build_application(settings)
        with TestClient(app) as client:
            response = client.get(
                (
                    "/v1/projects/missing-project/accounts/"
                    "00000000-0000-0000-0000-00000000c799/research-view"
                ),
                headers={"X-Workspace-Id": "missing-workspace"},
            )
        assert response.status_code == 404
    finally:
        run_async(remove_newly_registered_fields(existing_fields))
