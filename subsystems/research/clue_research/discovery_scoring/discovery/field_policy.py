"""Versioned account-discovery envelope policy (M6A D0).

The policy defines what every discovered account must attempt before a discovery batch can seal.
It is data, not branching logic: exact employee count may fall back to a range, and exact annual
revenue may fall back to a bounded band.  Required attempts may end honestly in a terminal missing,
conflict, or policy disposition; hard identities may not.
"""

from __future__ import annotations

from clue_core import (
    DiscoveryEnvelopeField,
    DiscoveryEnvelopePolicy,
    DiscoveryFieldRequirement,
)

REVENUE_BAND_OPTIONS = (
    "under_1m",
    "1m_10m",
    "10m_50m",
    "50m_100m",
    "100m_500m",
    "500m_1b",
    "1b_plus",
)

DISCOVERY_ENVELOPE_POLICY_V1 = DiscoveryEnvelopePolicy(
    version="discovery-envelope-v1",
    fields=(
        DiscoveryEnvelopeField(
            logical_field_key="identity.account_name",
            label="Account name",
            requirement=DiscoveryFieldRequirement.HARD_IDENTITY,
            canonical_storage="account_entity.canonical_name",
            allow_terminal_disposition=False,
        ),
        DiscoveryEnvelopeField(
            logical_field_key="identity.primary_domain",
            label="Primary domain",
            requirement=DiscoveryFieldRequirement.HARD_IDENTITY,
            canonical_storage="account_entity.primary_domain + core.primary_domain",
            field_attempt_order=("core.primary_domain",),
            allow_terminal_disposition=False,
        ),
        DiscoveryEnvelopeField(
            logical_field_key="discovery.company_linkedin_url",
            label="LinkedIn company URL",
            requirement=DiscoveryFieldRequirement.REQUIRED_ATTEMPT,
            canonical_storage="core.company_linkedin_url",
            field_attempt_order=("core.company_linkedin_url",),
            allow_terminal_disposition=True,
        ),
        DiscoveryEnvelopeField(
            logical_field_key="discovery.industry",
            label="Industry",
            requirement=DiscoveryFieldRequirement.REQUIRED_ATTEMPT,
            canonical_storage="core.industry",
            field_attempt_order=("core.industry",),
            allow_terminal_disposition=True,
        ),
        DiscoveryEnvelopeField(
            logical_field_key="discovery.employee_size",
            label="Employee count or range",
            requirement=DiscoveryFieldRequirement.REQUIRED_ATTEMPT,
            canonical_storage="core.employee_count | core.employee_range",
            field_attempt_order=("core.employee_count", "core.employee_range"),
            allow_terminal_disposition=True,
        ),
        DiscoveryEnvelopeField(
            logical_field_key="discovery.headquarters",
            label="Headquarters or primary location",
            requirement=DiscoveryFieldRequirement.REQUIRED_ATTEMPT,
            canonical_storage="account_entity.hq_geo + core.hq_location",
            field_attempt_order=("core.hq_location",),
            allow_terminal_disposition=True,
        ),
        DiscoveryEnvelopeField(
            logical_field_key="discovery.revenue",
            label="Annual revenue or revenue band",
            requirement=DiscoveryFieldRequirement.REQUIRED_ATTEMPT,
            canonical_storage="core.annual_revenue | core.revenue_band",
            field_attempt_order=("core.annual_revenue", "core.revenue_band"),
            allow_terminal_disposition=True,
        ),
        DiscoveryEnvelopeField(
            logical_field_key="discovery.company_email",
            label="Public company email",
            requirement=DiscoveryFieldRequirement.OPTIONAL_ATTEMPT,
            canonical_storage="core.company_email",
            field_attempt_order=("core.company_email",),
            allow_terminal_disposition=True,
        ),
        DiscoveryEnvelopeField(
            logical_field_key="discovery.company_phone",
            label="Public company phone",
            requirement=DiscoveryFieldRequirement.OPTIONAL_ATTEMPT,
            canonical_storage="core.company_phone",
            field_attempt_order=("core.company_phone",),
            allow_terminal_disposition=True,
        ),
    ),
)


__all__ = ["DISCOVERY_ENVELOPE_POLICY_V1", "REVENUE_BAND_OPTIONS"]
