"""Deep-profiling field-classes — ``account.resonance.*`` + ``contact.facet.*`` (M8.2 / M8.5).

The "tiny seed" the four M8 sub-issues fork from: it registers the two deep-pass field-classes
Doc C §2 introduces, as ``field_definition`` rows, so M8.4 can *populate* them and M10 can *govern*
them. It is pure registry data — **registered, never enumerated** (conventions §2): adding a field
is one ``SeedField`` row, never a pipeline fork. No migration (the ``field_definition`` table
already carries every column); no source-profile weights (that is M3.3, keyed on field-class); no
collectors/population (M8.1 resonance aspect / M8.4 facet population).

This pack is **M8-owned** and reuses ``claimstore.load_pack`` (the pattern ``icp/packs.py`` uses
to contribute ``account.resonance.research_prestige`` and ``stage0/fields.py`` uses for its packs):
``profiling -> claimstore`` is import-legal (the independence contract bans only worker→sibling-
worker). The two *proof* rows seeded in ``claimstore.CORE_PACK`` — ``account.resonance.culture`` and
``contact.facet.recent_post`` — are intentionally **left there and not re-declared here**; the
field-class is legitimately federated across packs (open by registration).

**The load-bearing asymmetry (Doc C §2: "power and governance are specified together").**

* ``account.resonance.*`` is **account-scoped, not personal.** Its ``gate`` is the deep-pass /
  faithfulness terminus only; it carries **no** ``use_class``/``identity_binding`` obligation. Its
  ``validation`` declares a *firewall* (:data:`_RESONANCE_FIREWALL`) — a named individual's
  special-category attribute must never be smuggled into a resonance value; that data belongs to
  ``contact.facet.*``/M10 (M8.2 AC6). The runtime rejection is the collector's (M8.2 part 2); the
  *declaration* lives here.
* ``contact.facet.*`` is **person-scoped and governed.** The governance is **structural**, not
  encoded per field-def: the ``contact.facet`` field-class itself forces every claim to carry
  ``identity_binding`` + ``use_class`` (the ``claim_contact_field_requires_governance`` DB CHECK +
  ``core.claim`` validator), a ``WEAK`` binding never promotes (``core.can_be_promoted``), and the
  M10 use-gate reads ``use_class``. So a facet field-def adds (a) a per-field ``use_class_hint``
  in ``validation`` — a *starting point* M8.4 refines from evidence, not the authoritative
  tag — and (b) a **shorter** ``freshness_ttl`` than a firmographic fact (Doc D §4 minimisation;
  every facet field is ``< core.employee_count``, M8.5 AC1). ``gate="committee-gated"`` mirrors
  the existing facet row and is advisory only (no gate string is machine-parsed except the JSON
  ``GateSpec``; the global pre-spend policy already requires a strong key for every field).

``reuse_scope`` is left unset on both classes: ``account.resonance`` and ``contact.facet`` both
default to ``TENANT_PRIVATE`` (``core.default_reuse_scope``), matching the existing canonical rows.

Freshness TTLs are *defaults as config* (D7) — graded by real volatility, not policy. ``exa_deep`` /
``parallel_task`` are the registered tier-4 synthesis sources (resolver-absent until M11 — a
``tier_plan`` is late-bound data; the waterfall returns an empty ``no_resolver`` result, never a
crash). Tier-3 review / long-tail *weighting* (Glassdoor-high for resonance, podcasts/X-high for
facets) is the pack source-profile's job (M3.3), out of scope here.
"""

from __future__ import annotations

from datetime import timedelta
from typing import Any

from sqlalchemy.ext.asyncio import AsyncConnection

from clue_core import EntityType, FieldDef, PassKind, ResearchSectionKind, UseClass
from clue_research.claimstore import ResearchViewFieldRoute, SeedField, load_pack

# --- namespaces ------------------------------------------------------------
NS_RESONANCE = "account.resonance"
NS_FACET = "contact.facet"

# --- account.resonance.* field keys (M8.2 / Doc C §2) ----------------------
RESONANCE_EMPLOYEE_SENTIMENT = f"{NS_RESONANCE}.employee_sentiment"
RESONANCE_ATTRITION_SIGNAL = f"{NS_RESONANCE}.attrition_signal"
RESONANCE_ENG_BLOG_TONE = f"{NS_RESONANCE}.eng_blog_tone"
RESONANCE_PUBLIC_FRUSTRATIONS = f"{NS_RESONANCE}.public_frustrations"
RESONANCE_BUYING_CULTURE = f"{NS_RESONANCE}.buying_culture"

# --- contact.facet.* field keys (M8.5 / Doc C §2) --------------------------
FACET_NICKNAME = f"{NS_FACET}.nickname"
FACET_STATED_INTERESTS = f"{NS_FACET}.stated_interests"
FACET_COMMUNICATION_STYLE = f"{NS_FACET}.communication_style"
FACET_PUBLIC_APPEARANCES = f"{NS_FACET}.public_appearances"
FACET_PUBLICATIONS = f"{NS_FACET}.publications"
FACET_CAUSES = f"{NS_FACET}.causes"
FACET_ALMA_MATER = f"{NS_FACET}.alma_mater"
FACET_CAREER_HISTORY = f"{NS_FACET}.career_history"

# The firewall every `account.resonance.*` field declares in `validation` (M8.2 AC6):
# and a named individual's special-category attribute must not enter a resonance value (it routes to
# `contact.facet.*`/M10). `validation` is round-tripped + drift-checked but never read by value
# validation (`value_schema` is the value validator), so it is the correct inert-metadata home.
_RESONANCE_FIREWALL: dict[str, Any] = {
    "account_scoped": True,
    "excludes_named_individual_special_category": True,
}

# `core.employee_count` freshness_ttl — the M8.5 AC1 ceiling every facet field must beat.
_FIRMOGRAPHIC_TTL = timedelta(days=90)


def _resonance(
    field_key: str,
    *,
    value_type: str,
    freshness_ttl: timedelta,
    value_schema: dict[str, Any],
    description: str,
) -> SeedField:
    """A deep-pass ``account.resonance.*`` row: tier-4 synthesis terminus, the account-scoped
    sensitivity firewall in ``validation``, no use-class/identity-binding (account-level, not
    personal). ``reuse_scope`` inherits the class default (``TENANT_PRIVATE``)."""
    return SeedField(
        field_def=FieldDef(
            field_key=field_key,
            value_type=value_type,
            validation=dict(_RESONANCE_FIREWALL),
            tier_plan=("exa_deep", "parallel_task"),
            freshness_ttl=freshness_ttl,
            pass_kind=PassKind.DEEP,
            gate="deep-pass",
        ),
        value_schema=value_schema,
        description=description,
        research_view_route=ResearchViewFieldRoute(
            field_key=field_key,
            entity_type=EntityType.ACCOUNT,
            section_kind=ResearchSectionKind.INSIGHTS,
        ),
    )


def _facet(
    field_key: str,
    *,
    value_type: str,
    freshness_ttl: timedelta,
    use_class_hint: UseClass,
    value_schema: dict[str, Any],
    description: str,
    section_kind: ResearchSectionKind,
    escalatable: bool = False,
) -> SeedField:
    """A deep-pass ``contact.facet.*`` row: a governed personal hook. Governance is **structural**
    (the field-class forces ``identity_binding`` + ``use_class`` on every claim, ``WEAK`` never
    promotes, M10 reads ``use_class``), so the def only adds a per-field ``use_class_hint`` (a
    starting point M8.4 refines from evidence; ``escalatable`` marks a hint whose per-claim tag may
    differ — e.g. an interest/cause tied to a religious or political cause escalates to
    ``sensitive``, Doc D §2) and a ``freshness_ttl`` shorter than a firmographic fact (Doc D
    §4). ``reuse_scope`` inherits the class default (``TENANT_PRIVATE``)."""
    if freshness_ttl >= _FIRMOGRAPHIC_TTL:
        raise ValueError(
            f"contact.facet field {field_key!r} must declare a freshness_ttl shorter than a "
            f"firmographic fact ({_FIRMOGRAPHIC_TTL.days}d; Doc D §4 / M8.5 AC1), got "
            f"{freshness_ttl.days}d"
        )
    validation: dict[str, Any] = {"use_class_hint": use_class_hint.value}
    if escalatable:
        validation["use_class_escalatable"] = True
    return SeedField(
        field_def=FieldDef(
            field_key=field_key,
            value_type=value_type,
            validation=validation,
            tier_plan=("exa_deep",),
            freshness_ttl=freshness_ttl,
            pass_kind=PassKind.DEEP,
            gate="committee-gated",
        ),
        value_schema=value_schema,
        description=description,
        research_view_route=ResearchViewFieldRoute(
            field_key=field_key,
            entity_type=EntityType.CONTACT,
            section_kind=section_kind,
        ),
    )


# --- account.resonance.* (Doc C §2: culture/sentiment/frustrations; tier-4, evidence-bound) -------
RESONANCE_PACK: tuple[SeedField, ...] = (
    _resonance(
        RESONANCE_EMPLOYEE_SENTIMENT,
        value_type="object",
        freshness_ttl=timedelta(days=30),
        value_schema={
            "type": "object",
            "required": ["label"],
            "properties": {
                "label": {
                    "type": "string",
                    "enum": ["positive", "neutral", "negative", "mixed"],
                },
                "polarity": {"type": "number"},  # -1.0..1.0; range enforced by the writer
                "summary": {"type": "string"},
            },
        },
        description="Aggregate employee sentiment, Glassdoor-style (Doc C §2; tier-4, governed).",
    ),
    _resonance(
        RESONANCE_ATTRITION_SIGNAL,
        value_type="object",
        freshness_ttl=timedelta(days=30),
        value_schema={
            "type": "object",
            "required": ["signal_type"],
            "properties": {
                "signal_type": {"type": "string", "enum": ["morale", "attrition", "layoff"]},
                "direction": {
                    "type": "string",
                    "enum": ["improving", "stable", "worsening"],
                },
                "summary": {"type": "string"},
            },
        },
        description="Morale / attrition / layoff signal (Doc C §2; tier-4).",
    ),
    _resonance(
        RESONANCE_ENG_BLOG_TONE,
        value_type="object",
        freshness_ttl=timedelta(days=60),
        value_schema={
            "type": "object",
            "required": ["tone_label"],
            "properties": {"tone_label": {"type": "string"}, "summary": {"type": "string"}},
        },
        description="Tone/voice of the company's engineering blog (Doc C §2; tier-4).",
    ),
    _resonance(
        RESONANCE_PUBLIC_FRUSTRATIONS,
        value_type="list[object]",
        freshness_ttl=timedelta(days=30),
        value_schema={
            "type": "array",
            "items": {
                "type": "object",
                "required": ["frustration"],
                "properties": {
                    "frustration": {"type": "string"},
                    "summary": {"type": "string"},
                },
            },
        },
        description="Publicly aired frustrations about the account (Doc C §2; tier-4).",
    ),
    _resonance(
        RESONANCE_BUYING_CULTURE,
        value_type="object",
        freshness_ttl=timedelta(days=90),
        value_schema={
            "type": "object",
            "required": ["culture_label"],
            "properties": {"culture_label": {"type": "string"}, "summary": {"type": "string"}},
        },
        description="'What it's like to buy here' — procurement culture (Doc C §2; tier-4).",
    ),
)

# --- contact.facet.* (Doc C §2: rich personal hooks; M8.5; governed by Doc D) ------------------
FACET_PACK: tuple[SeedField, ...] = (
    _facet(
        FACET_NICKNAME,
        value_type="str",
        freshness_ttl=timedelta(days=75),
        use_class_hint=UseClass.PERSONAL_PUBLIC_NON_SENSITIVE,
        value_schema={"type": "string"},
        description="Preferred / known-by name beyond the legal first name (Doc C §2).",
        section_kind=ResearchSectionKind.BACKGROUND,
    ),
    _facet(
        FACET_STATED_INTERESTS,
        value_type="list[str]",
        freshness_ttl=timedelta(days=45),
        use_class_hint=UseClass.PERSONAL_PUBLIC_NON_SENSITIVE,
        escalatable=True,  # an interest tied to a religious/political cause escalates to sensitive
        value_schema={"type": "array", "items": {"type": "string"}},
        description="Publicly stated interests / topics (Doc C §2; an interest tied to a "
        "religious/political cause is tagged sensitive per-claim — Doc D §2).",
        section_kind=ResearchSectionKind.BACKGROUND,
    ),
    _facet(
        FACET_COMMUNICATION_STYLE,
        value_type="object",
        freshness_ttl=timedelta(days=60),
        use_class_hint=UseClass.PROFESSIONAL_PUBLIC,
        value_schema={
            "type": "object",
            "required": ["style_label"],
            "properties": {"style_label": {"type": "string"}, "summary": {"type": "string"}},
        },
        description="Inferred communication style / tone from public activity (Doc C §2).",
        section_kind=ResearchSectionKind.BACKGROUND,
    ),
    _facet(
        FACET_PUBLIC_APPEARANCES,
        value_type="list[object]",
        freshness_ttl=timedelta(days=60),
        use_class_hint=UseClass.PROFESSIONAL_PUBLIC,
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
        description="Podcasts / talks / panels the person appeared in (Doc C §2).",
        section_kind=ResearchSectionKind.QUOTES,
    ),
    _facet(
        FACET_PUBLICATIONS,
        value_type="list[object]",
        freshness_ttl=timedelta(days=75),
        use_class_hint=UseClass.PROFESSIONAL_PUBLIC,
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
        description="Articles / papers / books the person authored (Doc C §2).",
        section_kind=ResearchSectionKind.PUBLICATIONS,
    ),
    _facet(
        FACET_CAUSES,
        value_type="list[object]",
        freshness_ttl=timedelta(days=60),
        use_class_hint=UseClass.SENSITIVE,
        escalatable=True,  # de-escalates per-claim only if evidently not special-category
        value_schema={
            "type": "array",
            "items": {
                "type": "object",
                "required": ["cause"],
                "properties": {"cause": {"type": "string"}, "context": {"type": "string"}},
            },
        },
        description="Publicly supported causes — religion/politics-adjacent, so the hint is "
        "sensitive by default (Doc D §2).",
        section_kind=ResearchSectionKind.BACKGROUND,
    ),
    _facet(
        FACET_ALMA_MATER,
        value_type="list[str]",
        freshness_ttl=timedelta(days=75),
        use_class_hint=UseClass.PERSONAL_PUBLIC_NON_SENSITIVE,
        value_schema={"type": "array", "items": {"type": "string"}},
        description="School(s) / university the person attended (Doc C §2).",
        section_kind=ResearchSectionKind.EDUCATION,
    ),
    _facet(
        FACET_CAREER_HISTORY,
        value_type="list[object]",
        freshness_ttl=timedelta(days=75),
        use_class_hint=UseClass.PROFESSIONAL_PUBLIC,
        value_schema={
            "type": "array",
            "items": {
                "type": "object",
                "required": ["org"],
                "properties": {
                    "org": {"type": "string"},
                    "role": {"type": "string"},
                    "start": {"type": "string"},
                    "end": {"type": "string"},
                },
            },
        },
        description="Professional history beyond the current title — prior roles (Doc C §2).",
        section_kind=ResearchSectionKind.CAREER,
    ),
)

# The full deep-profiling field set (M8.2 part-1 + M8.5). Disjoint from CORE_PACK's two proof rows
# (`account.resonance.culture`, `contact.facet.recent_post`) and the icp `frontier_ai` pack's
# `account.resonance.research_prestige`, which the field-class is federated with.
DEEP_PROFILING_PACK: tuple[SeedField, ...] = RESONANCE_PACK + FACET_PACK

# The field keys this pack registers, for consumers/tests that need the set without re-deriving it.
RESONANCE_FIELD_KEYS: tuple[str, ...] = tuple(s.field_def.field_key for s in RESONANCE_PACK)
FACET_FIELD_KEYS: tuple[str, ...] = tuple(s.field_def.field_key for s in FACET_PACK)


async def load_deep_profiling_pack(conn: AsyncConnection) -> None:
    """Register the ``account.resonance.*`` + ``contact.facet.*`` field set (idempotent; re-loading
    is a no-op). Additive and namespaced — it never collides with ``CORE_PACK`` or the icp packs.

    Wire this at the ``api`` composition root alongside ``load_core_pack`` (M8 deferral pattern);
    until that exists, the seed's own tests load it per-transaction.
    """
    await load_pack(conn, DEEP_PROFILING_PACK)
