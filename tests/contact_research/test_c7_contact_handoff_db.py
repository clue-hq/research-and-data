"""Database acceptance for the M8C C7 handoff projection; no provider transport is involved."""

from __future__ import annotations

from datetime import timedelta
from decimal import Decimal
from pathlib import Path
from uuid import UUID, uuid4

import pytest
from sqlalchemy import text
from tests.contact_research.test_c6_contact_selection_db import (
    _materialize,
    _selection_seed,
)
from tests.db.conftest import run_async
from tests.profiling.conftest import conn_session_factory, rollback_conn
from tests.profiling.conftest import migrated_db as migrated_db
from tests.profiling.conftest import require_profiling_db as require_profiling_db

from clue_api.contact_content_handoff import ContactContentHandoffService
from clue_api.toolbelt_wiring import build_toolbelt
from clue_api.trial.discovery_fixture import PRODUCT_ID, PROJECT_ID, WORKSPACE_ID
from clue_core import (
    AccountStatus,
    Claim,
    ContactContentHandoff,
    ContactDraftingFallback,
    ContactResearchSelection,
    ContactResearchSelectionId,
    ExtractionMethod,
    IdentityBinding,
    Persona,
    ResearchMode,
    UseClass,
    VerificationStatus,
    account_claim,
    contact_claim,
    new_operation_id,
)
from clue_core.entity_research import FieldSourceAuthority
from clue_research.claimstore import insert_claim, load_core_pack
from clue_research.durable import (
    AccountRunStatus,
    AccountRunSubPhase,
    ContactResearchSelectionApprovalAuthority,
    ContactResearchSelectionApprovalKind,
    cancel_contact_research_selection,
    save_references,
    set_account_sub_phase,
    store_contact_research_selection,
)
from clue_research.identity import insert_contact_entity, stamp_reuse
from clue_research.profiling.committee import (
    CURRENT_TITLE,
    PERSONA,
    ROLE_ON_COMMITTEE,
    load_committee_pack,
)
from clue_research.profiling.fields import FACET_PUBLICATIONS, load_deep_profiling_pack
from clue_storage import FsStorage
from clue_toolbelt import ToolContext, invoke_tool

pytestmark = pytest.mark.usefixtures("require_profiling_db")


def test_production_projection_is_reference_only_governed_and_names_skipped_contacts(
    tmp_path: Path,
) -> None:
    async def scenario() -> None:
        async with rollback_conn() as conn:
            seed = await _selection_seed(
                conn,
                FsStorage(tmp_path / "m8c-c7-artifacts"),
                suffix="m8c-c7-handoff",
            )
            initial = await _materialize(seed)
            await load_core_pack(conn)
            await load_committee_pack(conn)
            await load_deep_profiling_pack(conn)

            async def contact_fact(
                field_key: str,
                value: object,
                *,
                use_class: UseClass = UseClass.PROFESSIONAL_PUBLIC,
                research_mode: ResearchMode = ResearchMode.CONTACT_PROFILING,
            ) -> Claim:
                claim = stamp_reuse(
                    contact_claim(
                        entity_id=seed.contact_id,
                        field_key=field_key,
                        value_json=value,  # type: ignore[arg-type]
                        source_tier=1,
                        extraction_method=ExtractionMethod.API,
                        confidence=0.97,
                        run_id=seed.account_run_id,
                        research_mode=research_mode,
                        identity_binding=IdentityBinding.STRONG,
                        use_class=use_class,
                        source_url="https://provider.example/evidence",
                        evidence_span=f"Exact-contact evidence for {field_key}",
                    ),
                    workspace_id=WORKSPACE_ID,
                ).model_copy(
                    update={
                        "product_id": PRODUCT_ID,
                        "verification_status": VerificationStatus.VERIFIED,
                    }
                )
                await insert_claim(conn, claim)
                return claim

            role = await contact_fact(
                ROLE_ON_COMMITTEE,
                {
                    "role": Persona.CHAMPION.value,
                    "confidence": 0.97,
                    "plausible": True,
                    "rationale": "owns referral operations",
                },
                research_mode=ResearchMode.COMMITTEE_DISCOVERY,
            )
            persona = await contact_fact(
                PERSONA,
                Persona.CHAMPION.value,
                research_mode=ResearchMode.COMMITTEE_DISCOVERY,
            )
            title = await contact_fact(CURRENT_TITLE, "VP, Referral Operations")
            facet = await contact_fact(
                FACET_PUBLICATIONS,
                [{"title": "Reducing referral handoffs", "venue": "Public practice journal"}],
                use_class=UseClass.PERSONAL_PUBLIC_NON_SENSITIVE,
            )
            await conn.execute(
                text(
                    "INSERT INTO use_decision "
                    "(claim_id, usable_for_outreach, reason, regime, policy_version) "
                    "VALUES (:claim_id, true, 'allowed', 'strict', 1)"
                ),
                {"claim_id": facet.id},
            )
            pain = stamp_reuse(
                account_claim(
                    entity_id=seed.account_id,
                    field_key="account.operational_pain",
                    value_json="Manual referral handoffs create avoidable delays.",
                    source_tier=1,
                    extraction_method=ExtractionMethod.API,
                    confidence=0.95,
                    run_id=seed.account_run_id,
                    research_mode=ResearchMode.ACCOUNT_PROFILING,
                    source_url="https://m8c-c7.example/operations",
                    evidence_span="The practice reports delays from manual referral handoffs.",
                ),
                workspace_id=WORKSPACE_ID,
            ).model_copy(
                update={
                    "verification_status": VerificationStatus.VERIFIED,
                }
            )
            await insert_claim(conn, pain)

            target = initial.body.targets[0].model_copy(
                update={
                    "committee_claim_ids": (role.id, persona.id),
                    "field_keys": (CURRENT_TITLE, FACET_PUBLICATIONS),
                    "field_source_authority": (
                        FieldSourceAuthority(
                            field_key=CURRENT_TITLE,
                            source_keys=initial.body.policy.professional_source_plan,
                        ),
                        FieldSourceAuthority(
                            field_key=FACET_PUBLICATIONS,
                            source_keys=initial.body.policy.personal_facet_source_plan,
                        ),
                    ),
                    "facet_keys": (FACET_PUBLICATIONS,),
                }
            )
            successor_body = initial.body.model_copy(
                update={
                    "targets": (target,),
                    "approved_at": initial.body.approved_at + timedelta(seconds=1),
                }
            )
            selection = ContactResearchSelection.from_body(
                successor_body,
                effective_policy=successor_body.policy,
                selection_id=ContactResearchSelectionId(
                    UUID("00000000-0000-0000-0000-000000000001")
                ),
            )
            await store_contact_research_selection(
                conn,
                selection,
                account_run_id=seed.account_run_id,
                predecessor_id=initial.selection_id,
                approval=ContactResearchSelectionApprovalAuthority(
                    kind=ContactResearchSelectionApprovalKind.HUMAN_SUCCESSOR,
                    operation_id=uuid4(),
                    approved_by=successor_body.approved_by,
                    action_ref="human-action:m8c-c7-successor",
                    approved_at=successor_body.approved_at,
                ),
            )
            skipped_id = await insert_contact_entity(
                conn,
                account_entity_id=seed.account_id,
                full_name="Skipped C7",
                linkedin_url="https://linkedin.com/in/skipped-m8c-c7",
                status=AccountStatus.ACTIVE,
            )
            await save_references(
                conn,
                seed.account_run_id,
                references_index={
                    "account": [str(pain.id)],
                    "committee": [
                        str(seed.committee_claim_ids[0]),
                        str(role.id),
                        str(persona.id),
                    ],
                    "committee_contacts": [str(seed.contact_id), str(skipped_id)],
                    f"contact:{seed.contact_id}": [str(title.id), str(facet.id)],
                    "contact_research_selection": [
                        f"contact-selection:{selection.selection_id}:{selection.selection_sha256}"
                    ],
                },
                cost_cents=Decimal(0),
                status=AccountRunStatus.DONE,
            )
            await set_account_sub_phase(
                conn,
                seed.account_run_id,
                AccountRunSubPhase.CONTACTS_COMPLETE,
            )

            service = ContactContentHandoffService(conn_factory=conn_session_factory(conn))
            handoff = await service.compose(
                workspace_id=WORKSPACE_ID,
                project_id=PROJECT_ID,
                project_run_id=seed.project_run_id,
                account_entity_id=seed.account_id,
                product_id=PRODUCT_ID,
            )
            assert len(handoff.bundles) == 1
            bundle = handoff.bundles[0]
            assert bundle.contact_entity_id == seed.contact_id
            assert bundle.persona is Persona.CHAMPION
            assert [item.claim_id for item in bundle.drafting_context.professional_claims] == [
                title.id
            ]
            assert [item.claim_id for item in bundle.drafting_context.personal_facet_claims] == [
                facet.id
            ]
            assert [item.claim_id for item in bundle.drafting_context.account_context_claims] == [
                pain.id
            ]
            assert bundle.drafting_context.fallback is ContactDraftingFallback.CONTACT_PERSONALIZED
            assert bundle.delivery_channels == ()
            assert {item.state.value for item in bundle.coverage.channels} == {"not_requested"}
            assert set(bundle.coverage.filled_field_keys) == {CURRENT_TITLE, FACET_PUBLICATIONS}
            assert bundle.coverage.searched_source_keys == ()
            assert set(bundle.coverage.unsearched_source_keys) == {
                "exa_deep",
                "sumble_people",
                "sumble_teams",
            }
            assert bundle.coverage.committee_coverage_estimate is None
            assert bundle.coverage.coverage_reason_codes == ("committee_coverage_not_durable",)
            assert handoff.exclusions[0].contact_entity_id == skipped_id
            assert handoff.exclusions[0].selected is False

            payload = handoff.model_dump(mode="json")
            serialized = handoff.model_dump_json()
            assert "value_json" not in serialized
            assert "VP, Referral Operations" not in serialized
            assert "person@example" not in serialized
            assert "core.work_email" not in serialized
            assert "core.direct_phone" not in serialized
            assert payload["bundles"][0]["drafting_context"]["professional_claims"][0][
                "claim_id"
            ] == str(title.id)

            # The real toolbelt binding serves the same governed reference-only projection to the
            # reviewed content/reviewer profiles; it is not merely a directly callable service.
            registry = build_toolbelt(
                storage=None,
                gateway=None,
                conn_factory=conn_session_factory(conn),
                contact_content_handoff=service,
            )
            tool_result = await invoke_tool(
                registry,
                "compose_contact_content_handoff",
                {
                    "project_id": PROJECT_ID,
                    "project_run_id": str(seed.project_run_id),
                    "account_entity_id": str(seed.account_id),
                    "product_id": PRODUCT_ID,
                },
                ToolContext(
                    workspace_id=WORKSPACE_ID,
                    actor="agent",
                    conn_factory=conn_session_factory(conn),
                    operation_id=new_operation_id(),
                ),
                idempotency_ttl_s=86_400,
            )
            tool_handoff = ContactContentHandoff.model_validate(tool_result.references["handoff"])
            assert tool_handoff.workspace_id == handoff.workspace_id
            assert tool_handoff.project_run_id == handoff.project_run_id
            assert tuple(item.contact_entity_id for item in tool_handoff.bundles) == (
                seed.contact_id,
            )
            assert (
                tool_handoff.bundles[0].drafting_context.professional_claims[0].claim_id == title.id
            )
            assert "value_json" not in tool_handoff.model_dump_json()

            await cancel_contact_research_selection(
                conn,
                workspace_id=WORKSPACE_ID,
                selection_id=selection.selection_id,
                cancelled_by="human:m8c-c7-test",
                reason_code="steering_changed",
            )
            cancelled_handoff = await service.compose(
                workspace_id=WORKSPACE_ID,
                project_id=PROJECT_ID,
                project_run_id=seed.project_run_id,
                account_entity_id=seed.account_id,
                product_id=PRODUCT_ID,
            )
            assert cancelled_handoff.bundles == ()
            assert cancelled_handoff.reason_codes == ("contact_research_selection_cancelled",)
            assert {item.contact_entity_id for item in cancelled_handoff.exclusions} == {
                seed.contact_id,
                skipped_id,
            }

            # Exact scope is resolved before the cancelled/no-selection branches inspect the
            # account-run committee index.  A caller cannot use those honest same-scope exclusion
            # lists as a cross-workspace/project/product contact-id oracle.
            for foreign_scope in (
                {
                    "workspace_id": "foreign-m8c-c7-workspace",
                    "project_id": PROJECT_ID,
                    "product_id": PRODUCT_ID,
                },
                {
                    "workspace_id": WORKSPACE_ID,
                    "project_id": "foreign-m8c-c7-project",
                    "product_id": PRODUCT_ID,
                },
                {
                    "workspace_id": WORKSPACE_ID,
                    "project_id": PROJECT_ID,
                    "product_id": "foreign-m8c-c7-product",
                },
            ):
                rejected = await service.compose(
                    project_run_id=seed.project_run_id,
                    account_entity_id=seed.account_id,
                    **foreign_scope,
                )
                assert rejected.bundles == ()
                assert rejected.exclusions == ()
                assert rejected.reason_codes == ("contact_handoff_scope_not_found",)

    run_async(scenario())
