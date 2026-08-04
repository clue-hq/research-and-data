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
    ContactResearchSelection,
    ContactResearchSelectionBody,
    ContactResearchTarget,
    EntityId,
    IdentityBinding,
    ProjectRunId,
    ResearchDirectiveId,
    ResearchDirectivePin,
    new_claim_id,
    new_contact_research_selection_id,
    new_entity_id,
)

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
    receipt = ContactResearchSelection.from_body(body)
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
    fixture_paths.extend(manifest["exa_search"]["runtime_contract"]["fixture_paths"])
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
