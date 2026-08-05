"""M8C C0 contract, field, policy, and provider-reference exit gates."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

import pytest
from pydantic import ValidationError

from clue_config import ConfigOverlay, ContactResearchPolicy, OverlayStore, get_config
from clue_core import (
    CONTACT_CHANNEL_FIELD_KEYS,
    CONTACT_PROFESSIONAL_FIELD_KEYS,
    ChannelIdentityCorroboration,
    ChannelReachability,
    ChannelUseDecision,
    ContactChannel,
    ContactChannelAuthorization,
    ContactChannelState,
    ContactChannelValidation,
    ContactProviderFailureClass,
    ContactProviderFailureDisposition,
    ContactResearchIntent,
    ContactResearchSelection,
    ContactResearchSelectionBody,
    ContactResearchTarget,
    EntityId,
    IdentityBinding,
    ProjectRunId,
    ResearchDirectiveId,
    ResearchDirectivePin,
    classify_contact_provider_failure,
    new_claim_id,
    new_contact_research_selection_id,
    new_entity_id,
)
from clue_research.resolvers.exa.deep_contract import (
    ExaDeepFailureClass,
    ExaDeepSearchRequest,
    ExaDeepSearchResponse,
    classify_exa_deep_http_failure,
)
from clue_research.resolvers.sumble.people import SumblePeopleStatus, parse_people_response
from clue_research.resolvers.sumble.teams import parse_teams_response

_FIXTURES = Path(__file__).parents[1] / "fixtures"
_MANIFEST = _FIXTURES / "contact_research" / "c0_provider_contract_manifest.json"


def _pin(account_id: EntityId) -> ResearchDirectivePin:
    directive_id = ResearchDirectiveId(uuid4())
    return ResearchDirectivePin(
        directive_id=directive_id,
        directive_ref=f"research-directive:{directive_id}:v1",
        version=1,
        canonical_json_sha256="a" * 64,
        account_id=account_id,
    )


def _selection_body() -> ContactResearchSelectionBody:
    account_id = new_entity_id()
    return ContactResearchSelectionBody(
        workspace_id="workspace-c0",
        project_id="project-c0",
        project_run_id=ProjectRunId(uuid4()),
        account_entity_id=account_id,
        research_directive=_pin(account_id),
        targets=(
            ContactResearchTarget(
                contact_entity_id=new_entity_id(),
                committee_claim_ids=(new_claim_id(),),
                strong_identity_claim_ids=(new_claim_id(),),
                field_keys=("contact.current_title",),
            ),
        ),
        policy=ContactResearchPolicy().pin(),
        source_profile_ref="source-profile:healthcare:v3",
        jurisdiction_policy_ref="jurisdiction:strict:v1",
        use_policy_ref="use-policy:professional-public:v1",
        retention_policy_ref="retention:contact:v1",
        budget_reservation_ref="budget:contact-research:0",
        approved_by="user:owner",
        approved_at=datetime(2026, 8, 5, tzinfo=UTC),
    )


def test_selection_is_content_addressed_and_tamper_evident() -> None:
    body = _selection_body()
    receipt = ContactResearchSelection.from_body(body, effective_policy=body.policy)
    assert receipt.selection_sha256 == body.sha256()
    assert ContactResearchSelection.model_validate(receipt.model_dump()).selection_id == (
        receipt.selection_id
    )
    with pytest.raises(ValidationError, match="digest does not match"):
        ContactResearchSelection(
            selection_id=new_contact_research_selection_id(),
            body=body,
            selection_sha256="0" * 64,
        )


def test_selection_and_intent_fail_closed_on_cross_authority_or_policy_widening() -> None:
    body = _selection_body()
    foreign_account = new_entity_id()
    with pytest.raises(
        ValidationError, match="directive must belong to the exact selected account"
    ):
        ContactResearchSelectionBody.model_validate(
            {**body.model_dump(), "research_directive": _pin(foreign_account)}
        )

    target = body.targets[0]
    over_field_cap = ContactResearchPolicy(max_fields_per_contact=1).pin()
    with pytest.raises(ValidationError, match="effective policy field cap"):
        ContactResearchSelectionBody.model_validate(
            {
                **body.model_dump(),
                "policy": over_field_cap,
                "targets": (
                    target.model_copy(
                        update={
                            "field_keys": (
                                "contact.current_title",
                                "contact.job_function",
                            )
                        }
                    ),
                ),
            }
        )
    with pytest.raises(ValidationError, match="effective policy contact cap"):
        ContactResearchSelectionBody.model_validate(
            {
                **body.model_dump(),
                "policy": ContactResearchPolicy(max_selected_contacts=1).pin(),
                "targets": (
                    target,
                    target.model_copy(update={"contact_entity_id": new_entity_id()}),
                ),
            }
        )
    with pytest.raises(ValidationError, match="not a professional fact, personal facet"):
        ContactResearchSelectionBody.model_validate(
            {
                **body.model_dump(),
                "targets": (
                    target.model_copy(update={"field_keys": ("account.operational_pain",)}),
                ),
            }
        )
    with pytest.raises(ValidationError, match="effective Exa result cap"):
        ContactResearchSelectionBody.model_validate(
            {
                **body.model_dump(),
                "policy": ContactResearchPolicy(exa_max_results=10).pin(),
                "targets": (target.model_copy(update={"exa_max_results": 11}),),
            }
        )
    with pytest.raises(ValidationError, match="effective additional-query cap"):
        ContactResearchSelectionBody.model_validate(
            {
                **body.model_dump(),
                "policy": ContactResearchPolicy(exa_max_additional_queries=1).pin(),
                "targets": (
                    target.model_copy(
                        update={"directional_question_ids": ("question-1", "question-2")}
                    ),
                ),
            }
        )

    selection = ContactResearchSelection.from_body(body, effective_policy=body.policy)
    intent = ContactResearchIntent.from_selection(
        selection,
        contact_entity_id=target.contact_entity_id,
    )
    assert intent.selection_id == selection.selection_id
    assert intent.selection_sha256 == selection.selection_sha256
    assert intent.source_plan == body.policy.professional_source_plan
    assert intent.freshness_policy_ref == body.policy.freshness_policy_ref

    forged = intent.model_dump()
    forged["account_entity_id"] = foreign_account
    forged["source_plan"] = ("exa_deep",)
    with pytest.raises(ValidationError, match="widens or changes its parent selection"):
        ContactResearchIntent.model_validate(forged)
    with pytest.raises(ValueError, match="unselected contact"):
        ContactResearchIntent.from_selection(selection, contact_entity_id=new_entity_id())


def test_selection_enforces_aggregate_channel_provider_and_budget_caps() -> None:
    body = _selection_body()
    policy = ContactResearchPolicy(
        contact_reveals_enabled=True,
        channel_reveal_source_plan=("approved_email_provider",),
        email_reveal_native_unit_cap=1,
        email_reveal_budget_cents=25,
    ).pin()
    target = body.targets[0].model_copy(
        update={
            "field_keys": ("core.work_email",),
            "email": ContactChannelAuthorization(
                channel=ContactChannel.EMAIL,
                allowed=True,
                provider_source_keys=("approved_email_provider",),
                provider_native_unit_cap=1,
                budget_cap_cents=25,
                independent_validation_required=True,
            ),
        }
    )
    authorized = ContactResearchSelectionBody.model_validate(
        {**body.model_dump(), "policy": policy, "targets": (target,)}
    )
    intent = ContactResearchIntent.from_selection(
        ContactResearchSelection.from_body(authorized, effective_policy=authorized.policy),
        contact_entity_id=target.contact_entity_id,
    )
    assert intent.source_plan == ("approved_email_provider",)

    second = target.model_copy(update={"contact_entity_id": new_entity_id()})
    with pytest.raises(ValidationError, match="effective email native-unit cap"):
        ContactResearchSelectionBody.model_validate(
            {**body.model_dump(), "policy": policy, "targets": (target, second)}
        )
    unapproved = target.model_copy(
        update={
            "email": target.email.model_copy(
                update={"provider_source_keys": ("unapproved_provider",)}
            )
        }
    )
    with pytest.raises(ValidationError, match="outside the effective policy plan"):
        ContactResearchSelectionBody.model_validate(
            {**body.model_dump(), "policy": policy, "targets": (unapproved,)}
        )


def test_selection_and_intent_hashes_change_with_effective_policy() -> None:
    body = _selection_body()
    revised = body.model_copy(
        update={
            "policy": ContactResearchPolicy(
                contract_ref="M8C-C0-remediated@2026-08-05",
                professional_freshness_days=14,
            ).pin()
        }
    )
    revised = ContactResearchSelectionBody.model_validate(revised.model_dump())
    original_selection = ContactResearchSelection.from_body(body, effective_policy=body.policy)
    with pytest.raises(ValueError, match="differs from the effective config policy"):
        ContactResearchSelection.from_body(body, effective_policy=revised.policy)
    with pytest.raises(ValueError, match="no longer matches"):
        original_selection.require_effective_policy(revised.policy)
    revised_selection = ContactResearchSelection.from_body(revised, effective_policy=revised.policy)
    assert original_selection.selection_sha256 != revised_selection.selection_sha256
    assert (
        ContactResearchIntent.from_selection(
            original_selection,
            contact_entity_id=body.targets[0].contact_entity_id,
        ).sha256()
        != ContactResearchIntent.from_selection(
            revised_selection,
            contact_entity_id=revised.targets[0].contact_entity_id,
        ).sha256()
    )


def test_channel_validation_is_not_identity_promotion_or_use_permission() -> None:
    observed = new_claim_id()
    corroborating = new_claim_id()
    validated = ContactChannelValidation(
        channel=ContactChannel.EMAIL,
        observed_claim_id=observed,
        state=ContactChannelState.VALIDATED,
        identity_binding=IdentityBinding.STRONG,
        corroboration=ChannelIdentityCorroboration.MATCHED,
        reachability=ChannelReachability.REACHABLE,
        use_decision=ChannelUseDecision.NOT_EVALUATED,
        corroborating_claim_ids=(corroborating,),
        validation_reference_ids=("validator:receipt-1",),
    )
    assert validated.state is ContactChannelState.VALIDATED
    assert not validated.delivery_eligible

    verified = validated.model_copy(
        update={
            "state": ContactChannelState.VERIFIED_IDENTITY,
            "use_decision": ChannelUseDecision.ALLOWED,
        }
    )
    verified = ContactChannelValidation.model_validate(verified.model_dump())
    assert verified.delivery_eligible

    with pytest.raises(ValidationError, match="phone is delivery data"):
        ContactChannelValidation(
            channel=ContactChannel.PHONE,
            observed_claim_id=observed,
            state=ContactChannelState.VERIFIED_IDENTITY,
            identity_binding=IdentityBinding.STRONG,
            corroboration=ChannelIdentityCorroboration.MATCHED,
            reachability=ChannelReachability.REACHABLE,
            corroborating_claim_ids=(corroborating,),
            validation_reference_ids=("validator:receipt-2",),
        )


def test_channel_authorization_and_defaults_fail_closed() -> None:
    policy = ContactResearchPolicy()
    assert not policy.contact_reveals_enabled
    assert policy.channel_reveal_source_plan == ()
    assert policy.email_reveal_budget_cents == 0
    assert policy.phone_reveal_budget_cents == 0
    assert not policy.phone_identity_promotion_allowed

    with pytest.raises(ValidationError, match="disallowed channel"):
        ContactChannelAuthorization(
            channel=ContactChannel.EMAIL,
            allowed=False,
            provider_source_keys=("guessed_provider",),
            provider_native_unit_cap=1,
        )


def test_contact_policy_is_a_versioned_layered_config_surface() -> None:
    store = OverlayStore()
    override = ContactResearchPolicy(max_selected_contacts=2, max_fields_per_contact=6)
    store.set_client_overlay("workspace-c0", ConfigOverlay(contact_research_policy=override))
    config = get_config("workspace-c0", store=store)
    assert config.contact_research_policy == override
    assert config.contact_research_policy.pin() == override.pin()
    assert [version.layer for version in config.applied_versions] == ["defaults", "client"]


def test_canonical_field_meanings_are_unique_and_company_phone_is_not_person_phone() -> None:
    assert len(CONTACT_PROFESSIONAL_FIELD_KEYS) == len(set(CONTACT_PROFESSIONAL_FIELD_KEYS))
    assert set(CONTACT_PROFESSIONAL_FIELD_KEYS).isdisjoint(set(CONTACT_CHANNEL_FIELD_KEYS.values()))
    assert CONTACT_CHANNEL_FIELD_KEYS[ContactChannel.EMAIL] == "core.work_email"
    assert CONTACT_CHANNEL_FIELD_KEYS[ContactChannel.PHONE] == "core.direct_phone"
    assert CONTACT_CHANNEL_FIELD_KEYS[ContactChannel.PHONE] != "core.company_phone"


def test_provider_contract_versions_and_request_field_authority_are_explicit() -> None:
    manifest = json.loads(_MANIFEST.read_text(encoding="utf-8"))
    assert manifest["reviewed_at"] == "2026-08-05"
    runtime = manifest["sumble"]["runtime_contract"]
    public = manifest["sumble"]["public_reference"]
    assert runtime["api_version"] == "v9"
    assert not runtime["migration_authorized"]
    assert public["api_version"] == "v3"
    assert not public["runtime_authorized"]
    assert not manifest["sumble"]["contact_reveal"]["runtime_authorized"]
    assert not manifest["exa_websets"]["reference_contract"][
        "runtime_authorized_for_contact_enrichment"
    ]
    assert not manifest["exa_search"]["runtime_contract"]["contact_targeted_compiler_authorized"]
    assert manifest["exa_search"]["runtime_contract"]["contact_targeted_compiler_owner"] == (
        "M8C C3"
    )

    executable_operations = [
        *runtime["operations"],
        manifest["exa_search"]["runtime_contract"],
    ]
    for operation in executable_operations:
        assert operation["request_fields"]
        assert all(
            isinstance(authority, str) and authority.strip()
            for authority in operation["request_fields"].values()
        )
        assert operation["native_cost_unit"]
        assert operation["charge_event"]
        assert operation["retry_contract"]
        assert operation["rate_limit_contract"]


def test_every_c0_provider_fixture_reference_exists_and_public_v3_is_non_authorizing() -> None:
    manifest = json.loads(_MANIFEST.read_text(encoding="utf-8"))
    repository_root = Path(__file__).parents[2]
    fixture_paths: list[str] = []
    for operation in manifest["sumble"]["runtime_contract"]["operations"]:
        fixture_paths.extend(operation["fixture_paths"])
    fixture_paths.extend(manifest["provider_failure_contract"]["fixture_paths"])
    fixture_paths.extend(
        manifest["exa_search"]["runtime_contract"]["account_compatibility_fixture_paths"]
    )
    fixture_paths.append(manifest["sumble"]["public_reference"]["fixture_path"])
    assert all((repository_root / value).is_file() for value in fixture_paths)

    public_v3 = json.loads(
        (_FIXTURES / "providers" / "sumble" / "v3" / "public_people_contract.json").read_text(
            encoding="utf-8"
        )
    )
    assert public_v3["captured_at"] == "2026-08-05"
    assert public_v3["endpoint"] == "/v3/people/find"
    assert not public_v3["runtime_authorized"]
    assert public_v3["documented_contact_channels"] == []


def test_c0_sumble_success_empty_and_async_terminal_fixtures_parse_executably() -> None:
    provider_root = _FIXTURES / "providers" / "sumble" / "v9"
    expected_people = {
        "people_pending.json": SumblePeopleStatus.PENDING,
        "people_running.json": SumblePeopleStatus.RUNNING,
        "people_succeeded.json": SumblePeopleStatus.SUCCEEDED,
        "people_empty_succeeded.json": SumblePeopleStatus.SUCCEEDED,
        "people_failed.json": SumblePeopleStatus.FAILED,
    }
    for name, expected_status in expected_people.items():
        response = parse_people_response(json.loads((provider_root / name).read_text()))
        assert response.status is expected_status
    empty_people = parse_people_response(
        json.loads((provider_root / "people_empty_succeeded.json").read_text())
    )
    assert empty_people.people == () and empty_people.total == 0

    for name in ("teams_succeeded.json", "teams_empty_succeeded.json"):
        parse_teams_response(json.loads((provider_root / name).read_text()))
    empty_teams = parse_teams_response(
        json.loads((provider_root / "teams_empty_succeeded.json").read_text())
    )
    assert empty_teams.teams == () and empty_teams.total == 0


def test_c0_provider_failure_envelopes_classify_without_error_body_assumptions() -> None:
    manifest = json.loads(_MANIFEST.read_text(encoding="utf-8"))
    repository_root = Path(__file__).parents[2]
    contract = manifest["provider_failure_contract"]
    assert contract["applies_to"] == ["sumble_v9", "exa_search"]
    paths = contract["fixture_paths"]
    for relative in paths:
        fixture = json.loads((repository_root / relative).read_text(encoding="utf-8"))
        assert fixture["fixture_kind"] == "owned_transport_envelope"
        assert fixture["provider_body_contract"] == "opaque"
        for dispatched, expected_key in (
            (False, "expected_pre_dispatch"),
            (True, "expected_post_dispatch"),
        ):
            failure = classify_contact_provider_failure(
                fixture["status_code"],
                dispatched=dispatched,
                retry_after_seconds=fixture["retry_after_seconds"],
            )
            assert failure.failure_class is ContactProviderFailureClass(
                fixture["expected_failure_class"]
            )
            assert failure.disposition is ContactProviderFailureDisposition(fixture[expected_key])
            exa_expected = {
                ContactProviderFailureDisposition.HARD: ExaDeepFailureClass.HARD,
                ContactProviderFailureDisposition.BUDGET_PAUSED: ExaDeepFailureClass.BUDGET,
                ContactProviderFailureDisposition.RETRYABLE: ExaDeepFailureClass.RETRYABLE,
                ContactProviderFailureDisposition.SPEND_UNKNOWN: ExaDeepFailureClass.SPEND_UNKNOWN,
            }[failure.disposition]
            assert (
                classify_exa_deep_http_failure(fixture["status_code"], dispatched=dispatched)
                is exa_expected
            )

    assert (
        classify_contact_provider_failure(None, dispatched=False).disposition
        is ContactProviderFailureDisposition.RETRYABLE
    )
    assert (
        classify_contact_provider_failure(None, dispatched=True).disposition
        is ContactProviderFailureDisposition.SPEND_UNKNOWN
    )
    with pytest.raises(ValueError, match="successful HTTP status"):
        classify_contact_provider_failure(200, dispatched=False)


def test_c0_exa_fixtures_are_account_compatibility_evidence_not_contact_compiler_evidence() -> None:
    manifest = json.loads(_MANIFEST.read_text(encoding="utf-8"))
    runtime = manifest["exa_search"]["runtime_contract"]
    assert runtime["authority_scope"].startswith("provider capability")
    assert not runtime["contact_targeted_compiler_authorized"]
    repository_root = Path(__file__).parents[2]
    request_path, response_path = (
        repository_root / value for value in runtime["account_compatibility_fixture_paths"]
    )
    request = ExaDeepSearchRequest.model_validate_json(request_path.read_text(encoding="utf-8"))
    response = ExaDeepSearchResponse.model_validate_json(response_path.read_text(encoding="utf-8"))
    assert request.search_type == "deep-reasoning"
    assert response.request_id == "exa-deep-fixture-request-1"
