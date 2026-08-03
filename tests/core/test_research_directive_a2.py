from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from uuid import UUID

import pytest
from pydantic import ValidationError

from clue_core import (
    EntityId,
    ResearchAccountScope,
    ResearchCommitteePlan,
    ResearchDirective,
    ResearchDirectiveAccountOverride,
    ResearchDirectiveAccountOverrideBody,
    ResearchDirectiveBody,
    ResearchDirectiveId,
    ResearchDirectiveOverrideId,
    ResearchDirectivePin,
    ResearchDirectiveStatus,
    ResearchEffortPolicy,
    ResearchPrivacyPolicy,
    ResearchQuestion,
    ResearchSourcePolicy,
    compose_account_research_directive,
    research_directive_digest,
    research_directive_override_digest,
)

ACCOUNT_ID = EntityId(UUID("10000000-0000-0000-0000-000000000001"))
DIRECTIVE_ID = ResearchDirectiveId(UUID("20000000-0000-0000-0000-000000000001"))
OVERRIDE_ID = ResearchDirectiveOverrideId(UUID("30000000-0000-0000-0000-000000000001"))
NOW = datetime(2026, 8, 4, 8, 0, tzinfo=UTC)


def _body() -> ResearchDirectiveBody:
    return ResearchDirectiveBody(
        account_scope=ResearchAccountScope(explicit_account_ids=(ACCOUNT_ID,)),
        field_keys=("account.operational_pain",),
        questions=(
            ResearchQuestion(
                question_id="fax-friction",
                text="Is there grounded public evidence of fax workflow friction?",
                target_field_key="account.operational_pain",
            ),
        ),
        committee_plan=ResearchCommitteePlan(
            functions=("Operations",),
            levels=("Director",),
            personas=("champion",),
        ),
        source_policy=ResearchSourcePolicy(
            allowed_source_keys=("exa_deep", "sumble_people"),
            preferred_source_keys=("sumble_people",),
        ),
        privacy_policy=ResearchPrivacyPolicy(),
        effort_policy=ResearchEffortPolicy(
            tier="tier_1",
            max_depth=2,
            max_fanout=8,
            budget_cap_cents=Decimal("250"),
            budget_envelope_ref="budget:account-deep-v1",
            recursion_policy_ref="recursion:account-deep-v1",
            freshness_policy_ref="freshness:account-deep-v1",
        ),
    )


def _directive(
    status: ResearchDirectiveStatus = ResearchDirectiveStatus.CONFIRMED,
) -> ResearchDirective:
    body = _body()
    digest = research_directive_digest(
        directive_id=DIRECTIVE_ID,
        workspace_id="ws-a2",
        project_id="project-a2",
        product_id="product-a2",
        icp_key="icp-a2",
        icp_version=2,
        version=1,
        body=body,
        memory_refs=("memory-a2",),
        source_turn_ref="turn:1",
        predecessor_id=None,
    )
    confirmed = status is not ResearchDirectiveStatus.DRAFT
    return ResearchDirective(
        directive_id=DIRECTIVE_ID,
        workspace_id="ws-a2",
        project_id="project-a2",
        product_id="product-a2",
        icp_key="icp-a2",
        icp_version=2,
        version=1,
        status=status,
        body=body,
        memory_refs=("memory-a2",),
        created_by="agent:head-of-abm",
        source_turn_ref="turn:1",
        canonical_json_sha256=digest,
        created_at=NOW,
        confirmed_by="human:user-1" if confirmed else None,
        confirming_turn_ref="turn:2" if confirmed else None,
        confirmed_at=NOW if confirmed else None,
    )


def _override() -> ResearchDirectiveAccountOverride:
    body = ResearchDirectiveAccountOverrideBody(
        include_field_keys=("account.strategic_moves",),
        exclude_field_keys=("account.operational_pain",),
        additional_questions=(
            ResearchQuestion(
                question_id="referral-friction",
                text="What grounded evidence describes referral coordination friction?",
                target_field_key="account.strategic_moves",
            ),
        ),
        exclusions=("do not infer patient-level facts",),
    )
    digest = research_directive_override_digest(
        override_id=OVERRIDE_ID,
        directive_id=DIRECTIVE_ID,
        workspace_id="ws-a2",
        account_id=ACCOUNT_ID,
        body=body,
        source_turn_ref="turn:1",
    )
    return ResearchDirectiveAccountOverride(
        override_id=OVERRIDE_ID,
        directive_id=DIRECTIVE_ID,
        workspace_id="ws-a2",
        account_id=ACCOUNT_ID,
        body=body,
        created_by="agent:head-of-abm",
        source_turn_ref="turn:1",
        canonical_json_sha256=digest,
        created_at=NOW,
    )


def test_effective_directive_composes_separate_account_override_and_exact_pin() -> None:
    directive = _directive()
    override = _override()

    effective = compose_account_research_directive(
        directive,
        account_id=ACCOUNT_ID,
        override=override,
    )

    assert effective.field_keys == ("account.strategic_moves",)
    assert tuple(item.question_id for item in effective.questions) == (
        "fax-friction",
        "referral-friction",
    )
    assert effective.pin == ResearchDirectivePin.from_records(directive, override)
    assert effective.exclusions == ("do not infer patient-level facts",)


def test_superseded_directive_can_only_be_rehydrated_for_an_existing_pin() -> None:
    superseded = _directive(ResearchDirectiveStatus.SUPERSEDED)

    with pytest.raises(ValueError, match="only a confirmed"):
        ResearchDirectivePin.from_records(superseded)

    pin = ResearchDirectivePin.from_records(superseded, allow_superseded=True)
    effective = compose_account_research_directive(
        superseded,
        account_id=ACCOUNT_ID,
        allow_superseded=True,
    )
    assert effective.pin == pin


def test_questions_are_guidance_and_source_authority_is_closed() -> None:
    with pytest.raises(ValidationError, match="target field or facet"):
        ResearchQuestion(question_id="untargeted", text="Find something interesting")
    with pytest.raises(ValidationError, match="both allowed and excluded"):
        ResearchSourcePolicy(
            allowed_source_keys=("exa_deep",),
            excluded_source_keys=("exa_deep",),
        )


def test_pin_rejects_mutable_or_fabricated_reference_labels() -> None:
    directive = _directive()
    with pytest.raises(ValidationError, match="ref does not match"):
        ResearchDirectivePin(
            directive_id=directive.directive_id,
            directive_ref="research-directive:latest",
            version=directive.version,
            canonical_json_sha256=directive.canonical_json_sha256,
        )
