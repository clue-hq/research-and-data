"""Conservative, layered contact-research policy defaults (M8C C0)."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field, model_validator


class ContactResearchPolicy(BaseModel):
    """Policy-as-data for bounded contact research and separately metered reveals.

    The C0 default admits snapshot-backed professional facts and Exa contact research as source
    families, but authorizes no email/phone provider and reserves zero reveal budget.  A later C5
    revision must replace this complete sub-tree before a reveal is executable.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    policy_version: int = Field(default=1, ge=1)
    contract_ref: str = "M8C-C0@2026-08-05"
    sumble_runtime_contract_ref: str = "sumble-rest-v9@2026-08-05"
    sumble_public_reference_ref: str = "sumble-public-v3@2026-08-05-non-authorizing"
    exa_search_contract_ref: str = "exa-search-deep-reasoning@2026-08-05"
    exa_websets_contract_ref: str = "exa-websets-reference@2026-08-05-non-authorizing"
    max_selected_contacts: int = Field(default=3, ge=1, le=20)
    max_fields_per_contact: int = Field(default=8, ge=1, le=32)
    exa_max_results: int = Field(default=50, ge=1, le=50)
    exa_max_additional_queries: int = Field(default=10, ge=0, le=10)
    professional_source_plan: tuple[str, ...] = ("sumble_people", "sumble_teams")
    personal_facet_source_plan: tuple[str, ...] = ("exa_deep",)
    channel_reveal_source_plan: tuple[str, ...] = ()
    professional_freshness_days: int = Field(default=30, ge=1, le=365)
    personal_facet_freshness_days: int = Field(default=30, ge=1, le=365)
    contact_reveals_enabled: bool = False
    email_reveal_native_unit_cap: int = Field(default=0, ge=0)
    phone_reveal_native_unit_cap: int = Field(default=0, ge=0)
    email_reveal_budget_cents: int = Field(default=0, ge=0)
    phone_reveal_budget_cents: int = Field(default=0, ge=0)
    phone_identity_promotion_allowed: bool = False
    approved_strong_profile_hosts: tuple[str, ...] = ("linkedin.com",)

    @model_validator(mode="after")
    def _policy_is_bounded_and_fail_closed(self) -> ContactResearchPolicy:
        for label, values in (
            ("professional source plan", self.professional_source_plan),
            ("personal facet source plan", self.personal_facet_source_plan),
            ("channel reveal source plan", self.channel_reveal_source_plan),
            ("strong profile hosts", self.approved_strong_profile_hosts),
        ):
            if len(set(values)) != len(values):
                raise ValueError(f"contact research {label} must be unique")
        if not self.professional_source_plan or not self.personal_facet_source_plan:
            raise ValueError("contact research requires professional and personal-facet plans")
        if self.phone_identity_promotion_allowed:
            raise ValueError("M8C C0 keeps phone as delivery data, never an identity key")
        reveal_budgets = (
            self.email_reveal_native_unit_cap,
            self.phone_reveal_native_unit_cap,
            self.email_reveal_budget_cents,
            self.phone_reveal_budget_cents,
        )
        if not self.contact_reveals_enabled and (
            self.channel_reveal_source_plan or any(reveal_budgets)
        ):
            raise ValueError("disabled contact reveals require no provider plan and zero budgets")
        if self.contact_reveals_enabled and (
            not self.channel_reveal_source_plan or not any(reveal_budgets)
        ):
            raise ValueError("enabled contact reveals require providers and a non-zero reservation")
        return self


DEFAULT_CONTACT_RESEARCH_POLICY = ContactResearchPolicy()


__all__ = ["ContactResearchPolicy", "DEFAULT_CONTACT_RESEARCH_POLICY"]
