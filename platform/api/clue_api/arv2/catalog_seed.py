"""The ARV2 field pack (master plan §4 "new registered fields" + every key the answer keys wrote).

Rules (master plan §4): every field is optional — inside a value schema every sub-field is
optional except the one that identifies an item; a single scalar ``type`` only (the registry
validator rejects unions); ``contact.facet.*`` rows carry a ``use_class_hint`` and a TTL under
90 days. Canonical namespaces never pass ``pack=``.

The pack is deliberately *additive*: it registers only the keys the Zafran account run, the
person-depth run and the display recipes use that no shipped pack (``CORE_PACK``,
``DEEP_PROFILING_PACK``, ``COMMITTEE_PACK``) already carries — ``register_field`` refuses a
redefinition, so an overlap would be a hard boot failure rather than a merge.
"""

from __future__ import annotations

from datetime import timedelta
from typing import Any

from sqlalchemy.ext.asyncio import AsyncConnection

from clue_core import FieldDef, PassKind, UseClass
from clue_research.claimstore.packs import SeedField, load_pack

_STR: dict[str, Any] = {"type": "string"}
_STR_LIST: dict[str, Any] = {"type": "array", "items": {"type": "string"}}
_OBJ: dict[str, Any] = {"type": "object"}
_OBJ_LIST: dict[str, Any] = {"type": "array", "items": {"type": "object"}}


def _row(
    key: str,
    value_type: str,
    schema: dict[str, Any],
    description: str,
    *,
    pass_kind: PassKind = PassKind.DEEP,
    ttl_days: int = 90,
    use_class_hint: str | None = None,
) -> SeedField:
    validation: dict[str, Any] | None = (
        {"use_class_hint": use_class_hint} if use_class_hint else None
    )
    return SeedField(
        field_def=FieldDef(
            field_key=key,
            value_type=value_type,
            validation=validation,
            tier_plan=(),
            freshness_ttl=timedelta(days=ttl_days),
            pass_kind=pass_kind,
            gate=None,
        ),
        value_schema=schema,
        description=description,
    )


def _facet(
    key: str, value_type: str, schema: dict[str, Any], description: str, hint: str
) -> SeedField:
    return _row(key, value_type, schema, description, ttl_days=75, use_class_hint=hint)


_PROF = UseClass.PROFESSIONAL_PUBLIC.value
_PERS = UseClass.PERSONAL_PUBLIC_NON_SENSITIVE.value

ARV2_PACK: tuple[SeedField, ...] = (
    _row(
        "account.committee_search_assessment",
        "object",
        _OBJ,
        "The account agent's buying-role hypothesis and search rationale, with evidence and "
        "provider-result references. An assessment, not a provider-certified responsibility.",
        ttl_days=30,
    ),
    # --- account: the master plan's new fields ---
    _row(
        "account.open_requisitions",
        "list[object]",
        {
            "type": "array",
            "items": {
                "type": "object",
                "required": ["title"],
                "properties": {
                    "title": _STR,
                    "dept": _STR,
                    "published": _STR,
                    "days_open": {"type": "integer"},
                    "salary_band": _STR,
                    "still_listed": {"type": "boolean"},
                    "url": _STR,
                },
            },
        },
        "Open job requisitions read from the company's own ATS board: title, department, publish "
        "date, days open, salary band, whether still listed, URL.",
    ),
    _row(
        "account.gtm_tooling_stack",
        "object",
        {
            "type": "object",
            "properties": {"present": _STR_LIST, "absent": _STR_LIST, "notes": _STR},
        },
        "CRM, outbound and ABM tools the company demonstrably uses (present) and tools explicitly "
        "named as not used (absent).",
    ),
    _row(
        "account.named_customers",
        "list[str]",
        _STR_LIST,
        "Customers the company itself names publicly (logos, case studies, press).",
    ),
    _row(
        "account.reputation_risk",
        "object",
        {
            "type": "object",
            "required": ["what"],
            "properties": {"what": _STR, "status": _STR, "source_note": _STR},
        },
        "A negative or contested public claim about the company with its status (confirmed, "
        "refuted, unresolved). Born outreach_safe=false.",
    ),
    _row(
        "account.abm_program_maturity",
        "object",
        _OBJ,
        "Evidence of the company's own ABM program: open ABM roles, named ABM tooling, stated "
        "ABM motion.",
    ),
    _row(
        "account.committee_candidate",
        "object",
        {
            "type": "object",
            # Only the persona identifies the row. A **vacant seat** is a finding about the
            # account ("nobody holds this role") and carries no name, so requiring one would make
            # every recorded vacancy land ``schema_valid=false``.
            "required": ["persona"],
            "properties": {
                "name": _STR,
                "title": _STR,
                "persona": {
                    "type": "string",
                    "enum": [
                        "economic_buyer",
                        "champion",
                        "user",
                        "technical_evaluator",
                        "blocker",
                    ],
                },
                "linkedin_url": _STR,
                "confirmed_by": _STR,
                "vacant_seat": {"type": "boolean"},
            },
        },
        "One buying-committee candidate the account agent confirmed on a non-provider URL: name, "
        "title, persona from the ICP persona map, LinkedIn URL, what confirmed the identity. A "
        "vacant seat is recorded with vacant_seat=true and no name (R3 creates the contact).",
    ),
    _row(
        "account.icp_fit_verdict",
        "object",
        {
            "type": "object",
            "required": ["gate", "verdict"],
            "properties": {
                "gate": _STR,
                "verdict": {"type": "string", "enum": ["pass", "likely", "unclear", "fail"]},
                "rationale": _STR,
                "claim_ids": _STR_LIST,
            },
        },
        "The agent's lenient fit verdict for one ICP hard gate, with the claim ids behind it. "
        "Information for the human; never a reason to stop research. Born outreach_safe=false.",
    ),
    _row(
        "core.legal_name",
        "str",
        _STR,
        "The registered legal entity name.",
        pass_kind=PassKind.SCORING,
        ttl_days=365,
    ),
    _row(
        "core.founded_year",
        "int",
        {"type": "integer"},
        "Year the company was founded.",
        pass_kind=PassKind.SCORING,
        ttl_days=365,
    ),
    # --- account: keys the Zafran run wrote ---
    _row(
        "core.company_crunchbase_url",
        "str",
        _STR,
        "Crunchbase profile URL.",
        pass_kind=PassKind.SCORING,
        ttl_days=365,
    ),
    _row(
        "core.company_languages",
        "list[str]",
        _STR_LIST,
        "Languages the company publishes in.",
        pass_kind=PassKind.SCORING,
        ttl_days=365,
    ),
    _row(
        "core.company_twitter_url",
        "str",
        _STR,
        "Company X/Twitter profile URL.",
        pass_kind=PassKind.SCORING,
        ttl_days=365,
    ),
    _row(
        "core.company_type",
        "str",
        _STR,
        "Provider company type label (private, public, non-profit…).",
        pass_kind=PassKind.SCORING,
        ttl_days=365,
    ),
    _row(
        "core.industries_all",
        "list[str]",
        _STR_LIST,
        "Every industry label the provider records, primary first.",
        pass_kind=PassKind.SCORING,
        ttl_days=180,
    ),
    _row(
        "core.tech_stack_categorised",
        "list[object]",
        _OBJ_LIST,
        "Technology stack grouped by category as the provider reports it.",
        pass_kind=PassKind.SCORING,
    ),
    _row(
        "account.employee_roster_sample",
        "list[object]",
        _OBJ_LIST,
        "A provider sample of employees (name, title) used to sketch org shape; never a committee "
        "source.",
    ),
    _row(
        "account.hiring_velocity",
        "object",
        _OBJ,
        "Open roles by department and their ages, from the company's own job board.",
    ),
    _row(
        "account.media_layer_index",
        "list[object]",
        _OBJ_LIST,
        "Podcasts and videos found for the account's people: media URL, duration, whether "
        "transcribed.",
    ),
    _row(
        "account.media_transcript_quality_warning",
        "object",
        _OBJ,
        "A recorded defect in a media transcript (model, media, symptom). Born "
        "outreach_safe=false; context only.",
    ),
    _row(
        "account.claimed_customer_logos",
        "list[str]",
        _STR_LIST,
        "Customer logos the company shows on its own site (proposed by the structuring pass).",
    ),
    _row(
        "account.claimed_outcomes_metrics",
        "object",
        _OBJ,
        "Outcome metrics the company claims for customers (proposed by the structuring pass).",
    ),
    _row(
        "account.product_packaging",
        "object",
        _OBJ,
        "How the company packages and names its products (proposed by the structuring pass).",
    ),
    # --- contact: plain professional facts ---
    _row(
        "contact.headline",
        "str",
        _STR,
        "The person's LinkedIn headline as published.",
        ttl_days=60,
    ),
    _row(
        "contact.member_badges",
        "object",
        _OBJ,
        "Provider-recorded profile badges (creator, premium, open-to-work).",
        ttl_days=60,
    ),
    _row(
        "contact.network_statistics",
        "object",
        {
            "type": "object",
            "properties": {
                "followers": {"type": "integer"},
                "connections": {"type": "integer"},
            },
        },
        "Follower and connection counts.",
        ttl_days=60,
    ),
    _row(
        "contact.reports_to",
        "object",
        {
            "type": "object",
            "required": ["contact_id"],
            "properties": {"contact_id": _STR, "name": _STR},
        },
        "The committee member this person reports to (a contact entity id).",
    ),
    _row(
        "contact.x_url",
        "str",
        _STR,
        "The person's X/Twitter profile URL.",
        ttl_days=180,
    ),
    # --- contact facets: the master plan's new fields ---
    _facet(
        "contact.facet.hooks",
        "list[str]",
        _STR_LIST,
        "Specific, recent, self-published facts usable as outreach hooks, each grounded in a "
        "quote.",
        _PROF,
    ),
    _facet(
        "contact.facet.openers",
        "list[str]",
        _STR_LIST,
        "Three grounded opening lines the marketer can send, each tied to a hook.",
        _PROF,
    ),
    _facet(
        "contact.facet.voice_quote",
        "object",
        {
            "type": "object",
            "required": ["text"],
            "properties": {
                "text": _STR,
                "media_url": _STR,
                "media_timestamp": _STR,
                "source_title": _STR,
            },
        },
        "A verbatim spoken quote with the media URL and timestamp it came from.",
        _PROF,
    ),
    _facet(
        "contact.facet.certifications",
        "list[str]",
        _STR_LIST,
        "Professional certifications the person lists.",
        _PROF,
    ),
    _facet(
        "contact.facet.education_highschool",
        "str",
        _STR,
        "High school, when self-published.",
        _PERS,
    ),
    _facet(
        "contact.facet.self_summary",
        "str",
        _STR,
        "The person's own summary of themselves, verbatim or lightly trimmed.",
        _PROF,
    ),
    _facet(
        "contact.facet.excluded_lookalike",
        "object",
        {
            "type": "object",
            "properties": {"discarded_media": _STR, "title": _STR, "reason": _STR},
        },
        "A same-name candidate the research rejected and why. Born outreach_safe=false; context "
        "only.",
        _PROF,
    ),
    _facet(
        "contact.facet.best_channel",
        "str",
        _STR,
        "The channel the research judges most likely to reach this person first.",
        _PROF,
    ),
    # --- contact facets: keys the runs wrote ---
    _facet(
        "contact.facet.conference_talk",
        "list[str]",
        _STR_LIST,
        "Conference talks the person gave, title and venue.",
        _PROF,
    ),
    _facet(
        "contact.facet.hobby",
        "list[str]",
        _STR_LIST,
        "Hobbies the person states publicly themselves.",
        _PERS,
    ),
    _facet(
        "contact.facet.other_roles",
        "list[str]",
        _STR_LIST,
        "Board seats, advisory and side roles the person lists.",
        _PROF,
    ),
    _facet(
        "contact.facet.recent_award",
        "list[str]",
        _STR_LIST,
        "Awards or recognitions the person announced.",
        _PROF,
    ),
    _facet(
        "contact.facet.stated_skills",
        "list[str]",
        _STR_LIST,
        "Skills the person lists on their own profile.",
        _PROF,
    ),
)

ARV2_FIELD_KEYS: frozenset[str] = frozenset(str(seed.field_def.field_key) for seed in ARV2_PACK)


async def load_arv2_pack(conn: AsyncConnection) -> None:
    """Register the ARV2 pack (idempotent — register_field is a no-op on an identical row)."""
    await load_pack(conn, ARV2_PACK)
    from clue_api.arv2.quality_relationships import load_relationship_fields

    await load_relationship_fields(conn)
    from clue_research.narrative.fields import load_narrative_pack

    await load_narrative_pack(conn)
