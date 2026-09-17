"""The fixed comprehensive research profiles — a cross-milestone platform contract.

Authority: ``docs/FI-comprehensive-account-contact-research-contract.md`` — §3.1 (the fixed
21-field account profile) and §7.1 (the fixed 15-field contact profile).  These two tuples are
the *one* definition of "the whole profile": the narrative plane reads them as its evidence
allowlists (``clue_research.narrative.prose`` aliases them as ``PROSE_ACCOUNT_FIELDS`` /
``PROSE_CONTACT_FIELDS``), directive validation admits their rows as directive-valid regardless
of per-field ``pass_kind`` or the pinned ICP's authored list (§3.3 row 1), and the platform's
static provider-ownership table (``clue_api.comprehensive_research_contract``) re-exports them so
ownership can never drift from breadth.

They live in ``core`` because that is the ratified seam for cross-milestone contracts: the
milestone worker packages (``durable``, ``narrative``, …) are mutually independent and may not
import each other, so a list consumed by directive validation (imported by ``durable``) *and* by
narrative synthesis must be defined below both (the ``workers are independent`` import contract,
``pyproject.toml``).

Deliberate exclusions (why a field you might expect is absent):

* ``core.company_email`` / ``core.company_phone`` / ``core.work_email`` / ``core.direct_phone``
  — contact channels (PII); neither a neutral summary nor a research profile needs them, and a
  tier-4 model must never be handed them.
* ``account.scoring.fit`` / ``account.scoring.intent`` — client-relative by construction
  (reserved ``tenant_private``); including them would make a PROJECT_NEUTRAL surface a function
  of one client's ICP (§7-D2).
* ``account.crm_relationship_status`` — the client's private relationship with the account, not
  a fact about the account.
* ``contact.role_on_committee`` / ``contact.persona`` / ``contact.class`` — client-relative
  committee assessments (the contact twin of the ``account.scoring.*`` exclusion).
* ``contact.import_record`` / ``contact.jurisdiction`` — compliance/provenance records about the
  claim pipeline, not facts about the person.
"""

from __future__ import annotations

from typing import Final

__all__ = [
    "COMPREHENSIVE_ACCOUNT_FIELDS",
    "COMPREHENSIVE_CONTACT_FIELDS",
]

#: §3.1 — the fixed 21-field account profile, in the contract table's order.
COMPREHENSIVE_ACCOUNT_FIELDS: Final[tuple[str, ...]] = (
    "core.account_name",
    "core.industry",
    "core.company_about",
    "core.employee_count",
    "core.employee_range",
    "core.hq_location",
    "core.annual_revenue",
    "core.revenue_band",
    "core.primary_tech_stack",
    "core.company_linkedin_url",
    "account.total_funding",
    "account.recent_funding",
    "account.hiring_velocity_eng",
    "account.operational_pain",
    "account.strategic_moves",
    "account.resonance.culture",
    "account.resonance.employee_sentiment",
    "account.resonance.attrition_signal",
    "account.resonance.eng_blog_tone",
    "account.resonance.public_frustrations",
    "account.resonance.buying_culture",
)

#: §7.1 — the fixed 15-field contact profile: the six Sumble-structured professional rows and the
#: nine Exa-Deep public-professional facet rows (the partition itself is owned and asserted by
#: ``clue_api.comprehensive_research_contract``).
COMPREHENSIVE_CONTACT_FIELDS: Final[tuple[str, ...]] = (
    "contact.current_title",
    "contact.job_function",
    "contact.job_level",
    "contact.team_membership",
    "contact.current_location",
    "contact.organization_relationship",
    "contact.facet.career_history",
    "contact.facet.publications",
    "contact.facet.public_appearances",
    "contact.facet.communication_style",
    "contact.facet.alma_mater",
    "contact.facet.stated_interests",
    "contact.facet.nickname",
    "contact.facet.causes",
    "contact.facet.recent_post",
)
