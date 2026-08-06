"""M8C C3 transport-free exact-contact Exa compiler and parser gates."""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from typing import cast
from uuid import uuid4

import pytest
from pydantic import ValidationError
from tests.api.account_deep_test_support import confirmed_account_research_direction
from tests.api.test_account_deep_fixture_a1 import _pages
from tests.profiling.conftest import migrated_db as migrated_db
from tests.profiling.conftest import require_profiling_db as require_profiling_db
from tests.stage0.conftest import rollback_conn

from clue_api.account_deep_source_policy import bind_healthcare_account_deep_source_override
from clue_api.exa_contact_compiler import (
    ExaDeepContactAcquisitionPlan,
    ExaDeepContactAdmittedField,
    compile_exa_contact_acquisition_plan,
    compile_registered_exa_contact_plan,
)
from clue_api.trial.account_deep_fixture import (
    PROJECT_RUN_ID,
    seed_insight_health_account_deep_fixture,
)
from clue_api.trial.discovery_fixture import PRODUCT_ID, PROJECT_ID, WORKSPACE_ID
from clue_config import ContactResearchPolicy
from clue_core import (
    ContactResearchIntent,
    ContactResearchSelection,
    ContactResearchSelectionBody,
    ContactResearchTarget,
    EffectiveFieldSourcePlan,
    EffectiveSourceAuthorization,
    EntityId,
    ICPCreatedFrom,
    ProjectPhase,
    ProjectRunId,
    ResearchDirectiveId,
    ResearchDirectivePin,
    ResearchQuestion,
    new_claim_id,
    new_entity_id,
    new_project_run_id,
)
from clue_research.durable import ProjectRunStatus, ensure_project_run, get_project_run
from clue_research.icp import create_icp_spec, get_icp_version
from clue_research.identity import insert_contact_entity
from clue_research.resolvers.exa import (
    ExaDeepConfig,
    ExaDeepContactBindingStatus,
    ExaDeepContactTargetLock,
    ExaDeepFieldSpec,
    ExaDeepSearchRequest,
    compile_exa_contact_deep_request,
    parse_and_normalize_exa_contact_deep_response,
)
from clue_research.resolvers.exa.deep_contract import exa_field_alias
from clue_storage import FsStorage

_FIXTURES = Path(__file__).parents[1] / "fixtures" / "contact_research" / "exa_c3"
_FIELD = "contact.facet.publications"
_WORKSPACE = "workspace-c3"
_PROJECT = "project-c3"
_ICP = "healthcare-contact-c3"


def _payload(name: str) -> dict[str, object]:
    return cast(dict[str, object], json.loads((_FIXTURES / name).read_text(encoding="utf-8")))


def test_c3_provider_fixture_manifest_is_content_addressed() -> None:
    manifest_path = _FIXTURES.parent / "c3_exa_contract_manifest.json"
    manifest = cast(dict[str, object], json.loads(manifest_path.read_text(encoding="utf-8")))
    assert manifest["endpoint"] == "POST https://api.exa.ai/search"
    assert manifest["search_type"] == "deep-reasoning"
    assert manifest["channel_reveals"] is False
    assert ContactResearchPolicy().exa_search_contract_ref == manifest["contract"]
    fixtures = cast(dict[str, str], manifest["fixtures"])
    assert set(fixtures) == {
        "exa_c3/supported.json",
        "exa_c3/empty.json",
        "exa_c3/malformed.json",
        "exa_c3/contradictory_profile.json",
        "exa_c3/same_name_wrong_employer.json",
    }
    for relative, expected in fixtures.items():
        body = (_FIXTURES.parent / relative).read_bytes()
        assert hashlib.sha256(body).hexdigest() == expected


def _pin(account_id: EntityId) -> ResearchDirectivePin:
    directive_id = ResearchDirectiveId(uuid4())
    return ResearchDirectivePin(
        directive_id=directive_id,
        directive_ref=f"research-directive:{directive_id}:v1",
        version=1,
        canonical_json_sha256="a" * 64,
        account_id=account_id,
    )


def _intent() -> ContactResearchIntent:
    account_id = new_entity_id()
    contact_id = new_entity_id()
    policy = ContactResearchPolicy().pin()
    body = ContactResearchSelectionBody(
        workspace_id=_WORKSPACE,
        project_id=_PROJECT,
        project_run_id=ProjectRunId(uuid4()),
        account_entity_id=account_id,
        research_directive=_pin(account_id),
        targets=(
            ContactResearchTarget(
                contact_entity_id=contact_id,
                committee_claim_ids=(new_claim_id(),),
                strong_identity_claim_ids=(new_claim_id(),),
                field_keys=(_FIELD,),
                directional_question_ids=("publication-direction",),
            ),
        ),
        policy=policy,
        source_profile_ref="source-profile:healthcare-contact-c3",
        jurisdiction_policy_ref="jurisdiction:strict:v1",
        use_policy_ref="use:professional-public:v1",
        retention_policy_ref="retention:contact:v1",
        budget_reservation_ref="budget:contact-c3",
        approved_by="human:owner",
        approved_at=datetime(2026, 8, 5, tzinfo=UTC),
    )
    selection = ContactResearchSelection.from_body(body, effective_policy=policy)
    return ContactResearchIntent.from_selection(selection, contact_entity_id=contact_id)


def _target(intent: ContactResearchIntent, **updates: object) -> ExaDeepContactTargetLock:
    target = ExaDeepContactTargetLock(
        contact_entity_id=intent.contact_entity_id,
        employer_account_id=intent.account_entity_id,
        canonical_full_name="Alex Rivera",
        canonical_profile_url="https://www.linkedin.com/in/alex-rivera-cascade",
        employer_name="Cascade Gastroenterology Associates",
        employer_domain="cascade-gastro.example",
        current_title="Director of Patient Access",
        job_function="Operations",
        location="Portland, Oregon",
        start_published_date=datetime(2025, 1, 1, tzinfo=UTC),
        end_published_date=datetime(2026, 8, 5, tzinfo=UTC),
    )
    return target.model_copy(update=updates)


def _admitted() -> ExaDeepContactAdmittedField:
    source_plan = EffectiveFieldSourcePlan.compile(
        workspace_id=_WORKSPACE,
        icp_key=_ICP,
        icp_version=1,
        field_key=_FIELD,
        sources=(EffectiveSourceAuthorization(source_key="exa_deep", source_tier=4),),
    )
    return ExaDeepContactAdmittedField(
        spec=ExaDeepFieldSpec(
            field_key=_FIELD,
            value_schema={
                "type": "array",
                "items": {
                    "type": "object",
                    "required": ["title"],
                    "properties": {
                        "title": {"type": "string"},
                        "venue": {"type": "string"},
                        "url": {"type": "string"},
                        "date": {"type": "string"},
                    },
                },
            },
        ),
        effective_source_plan=source_plan,
        freshness_seconds=30 * 86_400,
    )


def _plan(
    intent: ContactResearchIntent,
    target: ExaDeepContactTargetLock,
) -> ExaDeepContactAcquisitionPlan:
    return compile_exa_contact_acquisition_plan(
        intent=intent,
        target_lock=target,
        icp_key=_ICP,
        icp_version=1,
        fields=(_admitted(),),
        directional_questions=("Which attributable publications discuss referral operations?",),
        observation_window="contact-c3-acceptance",
        cost_cents_reserved_per_bundle=Decimal(10),
    )


def test_contact_compiler_is_exact_bounded_registry_shaped_and_channel_free() -> None:
    intent = _intent()
    plan = _plan(intent, _target(intent))
    bundle = plan.bundles[0]
    request = bundle.exa_request
    properties = request.output_schema["properties"]
    assert isinstance(properties, dict)
    assert set(properties) == {exa_field_alias(_FIELD)}
    assert request.search_type == "deep-reasoning"
    assert request.num_results == 50
    assert request.start_published_date == datetime(2025, 1, 1, tzinfo=UTC)
    assert request.end_published_date == datetime(2026, 8, 5, tzinfo=UTC)
    assert "exact person" in request.system_prompt.casefold()
    assert "exact employer" in request.system_prompt.casefold()
    assert "same-name" in request.system_prompt.casefold()
    assert "canonical professional profile" in request.system_prompt.casefold()
    assert "never return or infer email or phone" in request.system_prompt.casefold()
    assert "Alex Rivera" in request.query
    assert "Cascade Gastroenterology Associates" in request.query
    assert "cascade-gastro.example" in request.query
    assert request.additional_queries is not None and len(request.additional_queries) == 1
    assert bundle.request.subject_kind.value == "contact"
    assert bundle.request.contact_id == intent.contact_entity_id
    assert bundle.field_source_plans[0].authorization_for("exa_deep") is not None
    assert "core.work_email" not in json.dumps(bundle.request.request_payload)
    assert "core.direct_phone" not in json.dumps(bundle.request.request_payload)


def test_contact_and_employer_disambiguators_change_both_fingerprints() -> None:
    intent = _intent()
    base = _target(intent)
    variants = (
        base,
        _target(
            intent,
            canonical_profile_url="https://www.linkedin.com/in/alex-rivera-cascade-v2",
        ),
        _target(intent, employer_name="Cascade GI Associates"),
        _target(intent, employer_domain="cascade-gi.example"),
        _target(intent, current_title="VP Patient Access"),
        _target(intent, job_function="Administration"),
        _target(intent, location="Seattle, Washington"),
    )
    fingerprints = {
        (
            _plan(intent, target).bundles[0].request.reuse_fingerprint,
            _plan(intent, target).bundles[0].request.request_fingerprint,
        )
        for target in variants
    }
    assert len(fingerprints) == len(variants)


def test_contact_compiler_rejects_non_facet_fields_and_non_exa_authority() -> None:
    intent = _intent()
    with pytest.raises(ValueError, match="only registered contact.facet"):
        compile_exa_contact_deep_request(
            _target(intent),
            (ExaDeepFieldSpec(field_key="core.work_email", value_schema={"type": "string"}),),
        )
    with pytest.raises(ValueError, match="requires bounded deep-reasoning"):
        compile_exa_contact_deep_request(
            _target(intent),
            (_admitted().spec,),
            config=ExaDeepConfig(search_type="deep"),
        )
    wrong_plan = EffectiveFieldSourcePlan.compile(
        workspace_id=_WORKSPACE,
        icp_key=_ICP,
        icp_version=1,
        field_key=_FIELD,
        sources=(EffectiveSourceAuthorization(source_key="parallel_task", source_tier=4),),
    )
    with pytest.raises(ValidationError, match="does not admit exact exa_deep"):
        ExaDeepContactAdmittedField(
            spec=_admitted().spec,
            effective_source_plan=wrong_plan,
            freshness_seconds=1,
        )


@pytest.mark.parametrize(
    ("fixture", "expected_binding", "expected_fields"),
    (
        ("supported.json", ExaDeepContactBindingStatus.EXACT, 1),
        ("contradictory_profile.json", ExaDeepContactBindingStatus.CONTRADICTORY, 0),
        ("same_name_wrong_employer.json", ExaDeepContactBindingStatus.UNRESOLVED, 0),
    ),
)
def test_contact_parser_preserves_exact_and_rejected_target_bindings(
    fixture: str,
    expected_binding: ExaDeepContactBindingStatus,
    expected_fields: int,
) -> None:
    intent = _intent()
    target = _target(intent)
    request = _plan(intent, target).bundles[0].exa_request
    normalized = parse_and_normalize_exa_contact_deep_response(
        request,
        _payload(fixture),
        target=target,
    )
    assert len(normalized.synthesis.fields) == expected_fields
    assert normalized.citations[0].target_binding is expected_binding
    if expected_binding is ExaDeepContactBindingStatus.CONTRADICTORY:
        assert normalized.citations[0].reason_codes == ("professional_profile_mismatch",)
    if expected_binding is ExaDeepContactBindingStatus.UNRESOLVED:
        assert "exact_employer_unresolved_or_mismatched" in normalized.citations[0].reason_codes


def test_empty_is_a_paid_hard_miss_and_malformed_non_null_output_fails_closed() -> None:
    intent = _intent()
    target = _target(intent)
    request = _plan(intent, target).bundles[0].exa_request
    empty = parse_and_normalize_exa_contact_deep_response(
        request,
        _payload("empty.json"),
        target=target,
    )
    assert empty.all_null is True
    assert empty.synthesis.fields == ()
    assert empty.synthesis.cost_cents == Decimal(5)
    with pytest.raises(ValidationError, match="lack grounding"):
        parse_and_normalize_exa_contact_deep_response(
            request,
            _payload("malformed.json"),
            target=target,
        )


def test_contact_parser_rejects_generic_or_mismatched_request_target() -> None:
    intent = _intent()
    target = _target(intent)
    request = _plan(intent, target).bundles[0].exa_request
    generic_payload = request.model_dump(mode="json", by_alias=True)
    generic_payload.pop("startPublishedDate")
    generic_payload.pop("endPublishedDate")
    generic = ExaDeepSearchRequest.model_validate(generic_payload)
    with pytest.raises(ValueError, match="contact Search request variant"):
        parse_and_normalize_exa_contact_deep_response(
            generic,  # type: ignore[arg-type] - adversarial runtime reconstruction
            _payload("supported.json"),
            target=target,
        )
    mismatched = _target(intent, employer_name="Another Gastroenterology Group")
    with pytest.raises(ValueError, match="does not render its persisted"):
        parse_and_normalize_exa_contact_deep_response(
            request,
            _payload("supported.json"),
            target=mismatched,
        )


def test_registered_compiler_resolves_real_registry_directive_and_source_plan(
    require_profiling_db: None,
    tmp_path: Path,
) -> None:
    del require_profiling_db

    async def scenario() -> None:
        async with rollback_conn() as conn:
            fixture = await seed_insight_health_account_deep_fixture(
                conn,
                pages=_pages(),
                storage=FsStorage(tmp_path / "artifacts"),
            )
            parent_icp = await get_icp_version(
                conn,
                WORKSPACE_ID,
                fixture.deep_icp_key,
                fixture.deep_icp_version,
            )
            assert parent_icp is not None
            parent_run = await get_project_run(conn, PROJECT_RUN_ID)
            assert parent_run is not None
            assert parent_run.product_context_version_id is not None
            assert parent_run.readiness_decision_id is not None
            icp_key = "healthcare-contact-c3-db"
            await bind_healthcare_account_deep_source_override(
                conn,
                workspace_id=WORKSPACE_ID,
                icp_key=icp_key,
                version=1,
            )
            icp = await create_icp_spec(
                conn,
                workspace_id=WORKSPACE_ID,
                icp_key=icp_key,
                created_from=ICPCreatedFrom.CLIENT_EDIT,
                field_keys=(_FIELD,),
                enabled_packs=("healthcare_practice",),
                source_profile_ref={"contract": "m8c-c3-contact-source-profile-v1"},
                created_by="human:c3-test",
                activate=True,
                client_entity_id=parent_icp.client_entity_id,
                client_kb_version=parent_icp.client_kb_version,
                product_id=parent_icp.product_id,
            )
            project_run_id = new_project_run_id()
            await ensure_project_run(
                conn,
                project_run_id=project_run_id,
                project_id=PROJECT_ID,
                workspace_id=WORKSPACE_ID,
                icp_key=icp.icp_key,
                icp_version=icp.version,
                phase=ProjectPhase.DEEP,
                status=ProjectRunStatus.ACTIVE,
                client_entity_id=icp.client_entity_id,
                client_kb_version=icp.client_kb_version,
                product_id=PRODUCT_ID,
                product_context_version_id=parent_run.product_context_version_id,
                readiness_decision_id=parent_run.readiness_decision_id,
            )
            contact_id = await insert_contact_entity(
                conn,
                account_entity_id=fixture.selected_account_id,
                full_name="Alex Rivera",
                linkedin_url="https://www.linkedin.com/in/alex-rivera-c3-db",
                geo={"city": "Portland", "region": "Oregon"},
            )
            question = ResearchQuestion(
                question_id="publication-direction",
                text="Which attributable publications discuss referral operations?",
                target_field_key=_FIELD,
                source_family_hints=("exa_deep",),
            )
            _, account_spec = await confirmed_account_research_direction(
                conn,
                workspace_id=WORKSPACE_ID,
                project_id=PROJECT_ID,
                product_id=PRODUCT_ID,
                account_id=fixture.selected_account_id,
                icp_key=icp.icp_key,
                icp_version=icp.version,
                field_keys=(_FIELD,),
                allowed_source_keys=("exa_deep",),
                questions=(question,),
                contact_profiling_allowed=True,
            )
            directive = account_spec.research_directive
            assert directive is not None
            policy = ContactResearchPolicy().pin()
            body = ContactResearchSelectionBody(
                workspace_id=WORKSPACE_ID,
                project_id=PROJECT_ID,
                project_run_id=project_run_id,
                account_entity_id=fixture.selected_account_id,
                research_directive=directive,
                targets=(
                    ContactResearchTarget(
                        contact_entity_id=contact_id,
                        committee_claim_ids=(new_claim_id(),),
                        strong_identity_claim_ids=(new_claim_id(),),
                        field_keys=(_FIELD,),
                        directional_question_ids=(question.question_id,),
                    ),
                ),
                policy=policy,
                source_profile_ref="source-profile:healthcare-contact-c3-db",
                jurisdiction_policy_ref="jurisdiction:strict:v1",
                use_policy_ref="use:professional-public:v1",
                retention_policy_ref="retention:contact:v1",
                budget_reservation_ref="budget:contact-c3-db",
                approved_by="human:owner",
                approved_at=datetime(2026, 8, 5, tzinfo=UTC),
            )
            selection = ContactResearchSelection.from_body(body, effective_policy=policy)
            intent = ContactResearchIntent.from_selection(
                selection,
                contact_entity_id=contact_id,
            )
            plan = await compile_registered_exa_contact_plan(
                conn,
                intent=intent,
                effective_policy=policy,
                observation_window="contact-c3-db",
            )
            assert plan.field_count == 1
            bundle = plan.bundles[0]
            assert bundle.request.contact_id == contact_id
            assert bundle.request.account_id == fixture.selected_account_id
            assert bundle.field_source_plans[0].field_key == _FIELD
            assert bundle.field_source_plans[0].authorization_for("exa_deep") is not None

            unregistered_body = body.model_copy(
                update={
                    "targets": (
                        body.targets[0].model_copy(
                            update={"field_keys": ("contact.facet.not_registered_c3",)}
                        ),
                    )
                }
            )
            unregistered_body = ContactResearchSelectionBody.model_validate(
                unregistered_body.model_dump()
            )
            unregistered_selection = ContactResearchSelection.from_body(
                unregistered_body,
                effective_policy=policy,
            )
            with pytest.raises(ValueError, match="not registered with a schema"):
                await compile_registered_exa_contact_plan(
                    conn,
                    intent=ContactResearchIntent.from_selection(
                        unregistered_selection,
                        contact_entity_id=contact_id,
                    ),
                    effective_policy=policy,
                    observation_window="contact-c3-unregistered",
                )

    from tests.db.conftest import run_async

    run_async(scenario())
