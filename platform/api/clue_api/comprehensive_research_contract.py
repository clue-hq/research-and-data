"""The frozen comprehensive account/contact research contracts (Slice A).

Authority: ``docs/FI-comprehensive-account-contact-research-contract.md`` — §3.1 (the fixed
21-field account profile and its static provider ownership) and §7.1 (the fixed 15-field
contact profile, split six Sumble-structured / nine Exa-Deep public-professional).

Three rules this module exists to make importable rather than re-derived per call site:

* **Field breadth is fixed, not planned.** A normal comprehensive request targets the whole
  ``PROSE_ACCOUNT_FIELDS`` / ``PROSE_CONTACT_FIELDS`` contract — never the three-field account
  acceptance subset (§3.3) and never a small contact acceptance subset (§7.1).
* **Provider ownership is static data, not a model decision.** §3.2 asks for deterministic
  contract expansion over the static mapping below — explicitly *not* a new adaptive gap
  planner or a model-authored waterfall.
* **Only the four permitted account field-sources may appear.** §2.2 defers Firecrawl,
  Scrapling, registries, CRM, Apollo, ZoomInfo, BuiltWith and every other provider family.

``COMPREHENSIVE_ACCOUNT_FIELD_SOURCES`` values are **ownership sets, not execution order**.
Execution order is the source planner's business, and tier discipline governs it (ruling,
2026-08-18): ``plan_sources`` stable-sorts by trust tier, so a dual-ownership row always plans
its tier-1 Sumble source before tier-4 ``exa_deep``, whatever order this table lists — and the
planned ``FieldSourceAuthority.source_keys`` is an ordered waterfall consumed stop-at-first-
confident-hit, never fanned out (fanning out double-buys the field). Acquisition happens only
*after* a fresh governed existing claim has failed to satisfy the field — every §3.1 row's
"reuse discovery truth" clause is the compiler's first step (§3.2 step 2), not a source. An
empty tuple means the field owns no acquisition source at all:
``core.employee_range`` and ``core.revenue_band`` are derived from governed employee-count /
revenue evidence (§3.1 rows 5 and 8), and ``core.account_name`` is canonical identity truth
reused from discovery (row 1).

**Consumer obligation.** This mapping states ownership only. A consumer MUST intersect this
preference list with the supported field set of the action it is about to dispatch before
dispatching it — ``organization_request()`` raises ``ValueError`` on unsupported field keys, so an
un-intersected dispatch is a crash, not a graceful skip.
"""

from collections.abc import Mapping
from types import MappingProxyType
from typing import Final

from clue_research.narrative.prose import PROSE_ACCOUNT_FIELDS
from clue_research.resolvers.sumble import SUMBLE_SOURCE_KEYS, sumble_action_supports_field

__all__ = [
    "COMPREHENSIVE_ACCOUNT_FIELDS",
    "COMPREHENSIVE_ACCOUNT_FIELD_SOURCES",
    "CONTACT_DEEP_FIELDS",
    "CONTACT_STRUCTURED_FIELDS",
    "source_can_request",
]


def source_can_request(source_key: str, field_key: str) -> bool:
    """Whether ``source_key``'s pinned provider action can put ``field_key`` on the wire.

    Ownership and requestability are different facts (see the module docstring's consumer
    obligation). Sumble's pinned v9 actions have a closed requestable set — ``sumble_organizations``
    owns seven §3.1 rows and can ask for three of them — and the resolver exposes that as
    policy-shaped data (``sumble_action_supports_field``) precisely so consumers intersect before
    dispatching. Exa Deep compiles its output schema per bundle from the field registry, so it can
    request any account row it owns.

    This is the *single* definition, read by both halves that must agree: the launcher intersects
    it into a new selection's authority, and the execution-completeness reader intersects it into
    the obligations it derives from an already-durable selection. A selection minted before the
    launcher learned to intersect still carries unrequestable pairs, and holding one outstanding
    is a deadlock with no exit — the tool refuses the request as ineligible, coverage refuses to
    close while it is outstanding, and the agent loops until the graph recursion cap kills the job
    (observed live). A pair no wire action can ever request is exhausted by construction and
    belongs in the coverage ledger as an honest gap, never as pending work.
    """

    if source_key in SUMBLE_SOURCE_KEYS:
        return sumble_action_supports_field(field_key, source_key)
    return True


#: §3.1 — the fixed 21-field account profile, re-exported verbatim from the prose contract so
#: the two can never drift.
COMPREHENSIVE_ACCOUNT_FIELDS: Final[tuple[str, ...]] = PROSE_ACCOUNT_FIELDS

#: §3.1 — static provider ownership, one row per field, in the table's order. Frozen at runtime
#: (a mapping proxy), not merely by annotation: the rows are founder-adjudicated purchase
#: decisions, so a consumer must never mutate them in place.
COMPREHENSIVE_ACCOUNT_FIELD_SOURCES: Final[Mapping[str, tuple[str, ...]]] = MappingProxyType(
    {
        # 1 — reuse canonical identity/discovery truth; no acquisition source.
        "core.account_name": (),
        # 2 — reuse discovery truth; otherwise a supported Sumble organization action or Exa Deep.
        "core.industry": ("sumble_organizations", "exa_deep"),
        # 3 — reuse discovery truth; otherwise Exa Deep (qualitative) or Sumble Organizations.
        "core.company_about": ("exa_deep", "sumble_organizations"),
        # 4 — reuse discovery truth; otherwise Sumble Organizations when available.
        "core.employee_count": ("sumble_organizations",),
        # 5 — reuse or derive from governed employee-count evidence; no acquisition source.
        "core.employee_range": (),
        # 6 — reuse discovery truth; otherwise Sumble Organizations.
        "core.hq_location": ("sumble_organizations",),
        # 7 — reuse discovery truth; otherwise the supported existing provider mapping, which among
        #     the permitted four is Exa Deep (Sumble's pinned organization attributes carry no
        #     revenue figure).
        "core.annual_revenue": ("exa_deep",),
        # 8 — reuse or derive from governed revenue evidence; no acquisition source.
        "core.revenue_band": (),
        # 9 — acquire through Sumble Tech Stack.
        "core.primary_tech_stack": ("sumble_tech_stack",),
        # 10 — reuse discovery truth or Sumble organization identity data.
        "core.company_linkedin_url": ("sumble_organizations",),
        # 11 — Sumble Organizations or Exa Deep where the existing manifest supports it.
        "account.total_funding": ("sumble_organizations", "exa_deep"),
        # 12 — Sumble Organizations or grounded Exa Deep research.
        "account.recent_funding": ("sumble_organizations", "exa_deep"),
        # 13 — Sumble Jobs.
        "account.hiring_velocity_eng": ("sumble_jobs",),
        # 14 — Exa Deep.
        "account.operational_pain": ("exa_deep",),
        # 15 — Exa Deep.
        "account.strategic_moves": ("exa_deep",),
        # 16 — Exa Deep.
        "account.resonance.culture": ("exa_deep",),
        # 17 — Exa Deep.
        "account.resonance.employee_sentiment": ("exa_deep",),
        # 18 — Exa Deep.
        "account.resonance.attrition_signal": ("exa_deep",),
        # 19 — Exa Deep.
        "account.resonance.eng_blog_tone": ("exa_deep",),
        # 20 — Exa Deep.
        "account.resonance.public_frustrations": ("exa_deep",),
        # 21 — Exa Deep.
        "account.resonance.buying_culture": ("exa_deep",),
    }
)

#: §7.1 — the six fields Sumble Teams/People owns as structured professional enrichment.
CONTACT_STRUCTURED_FIELDS: Final[tuple[str, ...]] = (
    "contact.current_title",
    "contact.job_function",
    "contact.job_level",
    "contact.team_membership",
    "contact.current_location",
    "contact.organization_relationship",
)

#: §7.1 — the nine facet fields Exa Deep owns as public professional research. Together with
#: :data:`CONTACT_STRUCTURED_FIELDS` this partitions ``PROSE_CONTACT_FIELDS`` exactly; §7.1 is
#: explicit that the two slots must not point at the same Exa-only builder.
CONTACT_DEEP_FIELDS: Final[tuple[str, ...]] = (
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
