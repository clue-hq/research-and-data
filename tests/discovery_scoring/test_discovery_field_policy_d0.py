"""M6A D0 — versioned discovery-envelope policy and core field registrations."""

from __future__ import annotations

from clue_core import DiscoveryFieldRequirement
from clue_research.claimstore.packs import CORE_PACK
from clue_research.discovery_scoring import DISCOVERY_ENVELOPE_POLICY_V1


def test_discovery_envelope_has_hard_identity_required_and_optional_groups() -> None:
    policy = DISCOVERY_ENVELOPE_POLICY_V1
    by_key = {str(field.logical_field_key): field for field in policy.fields}

    assert policy.version == "discovery-envelope-v1"
    assert set(policy.required_fields) == {
        "identity.account_name",
        "identity.primary_domain",
        "discovery.company_linkedin_url",
        "discovery.industry",
        "discovery.employee_size",
        "discovery.headquarters",
        "discovery.revenue",
    }
    assert set(policy.optional_fields) == {
        "discovery.company_email",
        "discovery.company_phone",
    }
    assert by_key["identity.account_name"].requirement is DiscoveryFieldRequirement.HARD_IDENTITY
    assert by_key["identity.account_name"].allow_terminal_disposition is False
    assert by_key["identity.primary_domain"].allow_terminal_disposition is False


def test_employee_and_revenue_groups_prefer_exact_values_then_bounded_fallbacks() -> None:
    by_key = {str(field.logical_field_key): field for field in DISCOVERY_ENVELOPE_POLICY_V1.fields}

    assert by_key["discovery.employee_size"].field_attempt_order == (
        "core.employee_count",
        "core.employee_range",
    )
    assert by_key["discovery.revenue"].field_attempt_order == (
        "core.annual_revenue",
        "core.revenue_band",
    )


def test_every_policy_field_attempt_is_registered_in_the_core_pack() -> None:
    registered = {str(seed.field_def.field_key) for seed in CORE_PACK}
    attempted = {
        str(field_key)
        for field in DISCOVERY_ENVELOPE_POLICY_V1.fields
        for field_key in field.field_attempt_order
    }

    assert attempted <= registered
    assert {
        "core.company_linkedin_url",
        "core.industry",
        "core.employee_range",
        "core.hq_location",
        "core.annual_revenue",
        "core.revenue_band",
        "core.company_email",
        "core.company_phone",
    } <= registered


def test_contact_channels_are_company_general_contacts_not_personal_reveals() -> None:
    by_field = {str(seed.field_def.field_key): seed for seed in CORE_PACK}

    assert "not a person's" in (by_field["core.company_email"].description or "").lower()
    assert "not a person's" in (by_field["core.company_phone"].description or "").lower()
    assert by_field["core.company_email"].field_def.field_key != "core.work_email"
