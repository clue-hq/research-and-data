"""Committee field-class — role/persona plus optional ``contact.class`` (M8.3/C7.1).

The plain ``contact.*`` fields cover the committee-discovery worker's inferred role/persona and
C7's optional, workspace-defined contact grouping. They are a small committee-owned pack,
**separate from the frozen tiny-seed** ``DEEP_PROFILING_PACK`` (resonance/facet only); wire
:func:`load_committee_pack` at the ``api`` composition root alongside ``load_deep_profiling_pack``.

Why these are *not* ``contact.facet.*``: they are professional-public committee assessments, not
rich personal hooks — so the facet governance CHECK (``identity_binding`` + ``use_class`` required)
does **not** apply to them (0004 is facet-scoped). M8.3 still tags them ``use_class=professional-
public`` + ``identity_binding`` per resolution strength (the contact field-claim provenance flavor),
because every admitted contact resolved through the M2 strong-key gate. ``reuse_scope`` inherits the
``contact`` class default ``TENANT_PRIVATE`` (a client's committee assessment never amortizes across
clients). **No ``tier_plan``** — these are produced by committee discovery (mode M3), not filled by
the M4 waterfall, so M8.4's gap scan (deep contact fields *with* a tier_plan) never tries to fill
them.
"""

from __future__ import annotations

from datetime import timedelta
from typing import Any

from sqlalchemy.ext.asyncio import AsyncConnection

from clue_core import (
    CONTACT_PROFESSIONAL_FIELD_KEYS,
    EntityType,
    FieldDef,
    PassKind,
    Persona,
    ResearchScope,
    ResearchSectionKind,
)
from clue_research.claimstore import ResearchViewFieldRoute, SeedField, load_pack

# --- field keys (conventions §3: plain contact.* committee facts) -----------
ROLE_ON_COMMITTEE = "contact.role_on_committee"
PERSONA = "contact.persona"
# C7.1 / REQ-16 A3: a pack/workspace-supplied grouping (for example,
# ``clinical``/``business``). It is not an enum and not an alias for committee persona. No claim
# means ``unknown``; consumers may not guess a class from title, role, or persona.
CONTACT_CLASS = "contact.class"

# M8C C1 — literal/provider-modeled professional facts from an already-acquired committee
# snapshot.  The tuple is frozen in core C0; aliases here keep committee consumers from repeating
# string keys and make this pack their one registration owner.
(
    CURRENT_TITLE,
    JOB_FUNCTION,
    JOB_LEVEL,
    TEAM_MEMBERSHIP,
    CURRENT_LOCATION,
    ORGANIZATION_RELATIONSHIP,
) = CONTACT_PROFESSIONAL_FIELD_KEYS

# The canonical persona/role set (conventions §3) — the closed value domain for both fields.
_PERSONA_VALUES: list[str] = [p.value for p in Persona]

# A ``contact.role_on_committee`` value carries the inferred role plus the role-plausibility verdict
# so a flagged (implausible) assignment is legible to M9/M12: ``plausible=false`` + a clamped
# ``confidence`` is the "flagged, not promoted" signal (M8.3 AC).
_ROLE_VALUE_SCHEMA: dict[str, Any] = {
    "type": "object",
    "required": ["role"],
    "properties": {
        "role": {"type": "string", "enum": _PERSONA_VALUES},
        "confidence": {"type": "number"},  # 0..1; the inference confidence (clamped if implausible)
        "plausible": {"type": "boolean"},  # the role-plausibility gate verdict
        "rationale": {"type": "string"},
    },
}

# ``contact.persona`` is the bare persona key — a closed enum for ``(account, persona)`` keying.
_PERSONA_VALUE_SCHEMA: dict[str, Any] = {"type": "string", "enum": _PERSONA_VALUES}

_TEAM_MEMBERSHIP_SCHEMA: dict[str, Any] = {
    "type": "array",
    "items": {
        "type": "object",
        "required": [
            "provider_team_id",
            "name",
            "organization_id",
            "relationship_basis",
        ],
        "properties": {
            "provider_team_id": {"type": "integer"},
            "name": {"type": "string"},
            "organization_id": {"type": "integer"},
            "relationship_basis": {
                "type": "string",
                "enum": ["provider_inferred_team_membership"],
            },
            "confidence": {"type": "number"},
            "source_url": {"type": "string"},
        },
    },
}

_CURRENT_LOCATION_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "raw": {"type": "string"},
        "country": {"type": "string"},
    },
}

_ORGANIZATION_RELATIONSHIP_SCHEMA: dict[str, Any] = {
    "type": "object",
    "required": ["relationship", "basis", "organization_id"],
    "properties": {
        "relationship": {"type": "string", "enum": ["current_employee"]},
        "basis": {
            "type": "string",
            "enum": [
                "provider_returned_current_employer",
                "provider_inferred_team_membership",
            ],
        },
        "organization_id": {"type": "integer"},
        "organization_name": {"type": "string"},
        "role_start_date": {"type": "string"},
        "provider_team_ids": {"type": "array", "items": {"type": "integer"}},
    },
}


def _committee_field(
    field_key: str,
    *,
    value_type: str,
    value_schema: dict[str, Any],
    description: str,
    research_scope: ResearchScope | None = None,
) -> SeedField:
    """A plain ``contact.*`` committee field: deep pass, no ``tier_plan`` (M3-produced, not
    waterfall-filled), advisory ``gate``, ``reuse_scope`` inheriting the class default
    (``TENANT_PRIVATE``). ``research_scope`` is declared only for the two fields that *are* the
    per-project targeting decision (FI-2 §5.2); the rest inherit the neutral default."""
    return SeedField(
        field_def=FieldDef(
            field_key=field_key,
            value_type=value_type,
            tier_plan=(),  # produced by committee discovery, not the M4 waterfall
            pass_kind=PassKind.DEEP,
            gate="committee-gated",
            research_scope=research_scope,
        ),
        value_schema=value_schema,
        description=description,
    )


def _professional_field(
    field_key: str,
    *,
    value_type: str,
    value_schema: dict[str, Any],
    description: str,
    ordinal: int,
) -> SeedField:
    """A 30-day professional fact routed into the governed contact research view."""

    return SeedField(
        field_def=FieldDef(
            field_key=field_key,
            value_type=value_type,
            tier_plan=(),
            freshness_ttl=timedelta(days=30),
            pass_kind=PassKind.DEEP,
            gate="committee-gated",
        ),
        value_schema=value_schema,
        description=description,
        research_view_route=ResearchViewFieldRoute(
            field_key=field_key,
            entity_type=EntityType.CONTACT,
            section_kind=ResearchSectionKind.PROFESSIONAL_SIGNALS,
            context_scope="project_run_pinned",
            product_mode="neutral_or_exact",
            ordinal=ordinal,
        ),
    )


COMMITTEE_PACK: tuple[SeedField, ...] = (
    # The buying committee is a per-project targeting decision — each project resolves its own, so
    # both committee fields are PROJECT_RELATIVE (FI-2 §5.2, founder-ratified 2026-08-08).
    _committee_field(
        ROLE_ON_COMMITTEE,
        value_type="object",
        value_schema=_ROLE_VALUE_SCHEMA,
        description="Inferred buying-committee role + role-plausibility verdict (Output 3; M8.3).",
        research_scope=ResearchScope.PROJECT_RELATIVE,
    ),
    _committee_field(
        PERSONA,
        value_type="str",
        value_schema=_PERSONA_VALUE_SCHEMA,
        description="Buying-committee persona key for (account, persona) addressing (M8.3).",
        research_scope=ResearchScope.PROJECT_RELATIVE,
    ),
    _committee_field(
        CONTACT_CLASS,
        value_type="str",
        value_schema={"type": "string"},
        description=(
            "Optional pack/workspace contact-class value (C7.1 / REQ-16 A3). "
            "Separate from committee persona; an absent claim means unknown."
        ),
    ),
    _professional_field(
        CURRENT_TITLE,
        value_type="str",
        value_schema={"type": "string"},
        description="Provider-returned current professional title for an admitted contact.",
        ordinal=10,
    ),
    _professional_field(
        JOB_FUNCTION,
        value_type="str",
        value_schema={"type": "string"},
        description="Provider-returned current job function for an admitted contact.",
        ordinal=20,
    ),
    _professional_field(
        JOB_LEVEL,
        value_type="str",
        value_schema={"type": "string"},
        description="Provider-returned current job level for an admitted contact.",
        ordinal=30,
    ),
    _professional_field(
        TEAM_MEMBERSHIP,
        value_type="list[object]",
        value_schema=_TEAM_MEMBERSHIP_SCHEMA,
        description=(
            "Provider-modeled organization-team membership with explicit relationship basis."
        ),
        ordinal=40,
    ),
    _professional_field(
        CURRENT_LOCATION,
        value_type="object",
        value_schema=_CURRENT_LOCATION_SCHEMA,
        description="Provider-returned current professional location/country.",
        ordinal=50,
    ),
    _professional_field(
        ORGANIZATION_RELATIONSHIP,
        value_type="object",
        value_schema=_ORGANIZATION_RELATIONSHIP_SCHEMA,
        description=(
            "Exact-account current-employment relationship with returned or modeled basis."
        ),
        ordinal=60,
    ),
)

# The field keys this pack registers, for consumers/tests that need the set without re-deriving it.
COMMITTEE_FIELD_KEYS: tuple[str, ...] = tuple(s.field_def.field_key for s in COMMITTEE_PACK)


async def load_committee_pack(conn: AsyncConnection) -> None:
    """Register the committee role/persona/class fields (idempotent;
    re-loading is a no-op). Additive and namespaced — never collides with ``CORE_PACK``,
    ``DEEP_PROFILING_PACK``, or the icp packs.

    Wire at the ``api`` composition root alongside ``load_core_pack`` / ``load_deep_profiling_pack``
    (the M8 deferral pattern); until then the committee tests load it per-transaction.
    """
    await load_pack(conn, COMMITTEE_PACK)
