"""Committee field-class — ``contact.role_on_committee`` + ``contact.persona`` (M8.3).

The two plain ``contact.*`` fields the committee-discovery worker writes per admitted member: the
inferred buying-committee role (with the role-plausibility verdict) and the persona key that makes
``(account, persona)`` addressable downstream (substrate §7). They are a small M8.3-owned pack,
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

from typing import Any

from sqlalchemy.ext.asyncio import AsyncConnection

from clue_research.claimstore import SeedField, load_pack
from clue_research.core import FieldDef, PassKind, Persona

# --- field keys (conventions §3: plain contact.* committee facts) -----------
ROLE_ON_COMMITTEE = "contact.role_on_committee"
PERSONA = "contact.persona"

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


def _committee_field(
    field_key: str, *, value_type: str, value_schema: dict[str, Any], description: str
) -> SeedField:
    """A plain ``contact.*`` committee field: deep pass, no ``tier_plan`` (M3-produced, not
    waterfall-filled), advisory ``gate``, ``reuse_scope`` inheriting the class default
    (``TENANT_PRIVATE``)."""
    return SeedField(
        field_def=FieldDef(
            field_key=field_key,
            value_type=value_type,
            tier_plan=(),  # produced by committee discovery, not the M4 waterfall
            pass_kind=PassKind.DEEP,
            gate="committee-gated",
        ),
        value_schema=value_schema,
        description=description,
    )


COMMITTEE_PACK: tuple[SeedField, ...] = (
    _committee_field(
        ROLE_ON_COMMITTEE,
        value_type="object",
        value_schema=_ROLE_VALUE_SCHEMA,
        description="Inferred buying-committee role + role-plausibility verdict (Output 3; M8.3).",
    ),
    _committee_field(
        PERSONA,
        value_type="str",
        value_schema=_PERSONA_VALUE_SCHEMA,
        description="Buying-committee persona key for (account, persona) addressing (M8.3).",
    ),
)

# The field keys this pack registers, for consumers/tests that need the set without re-deriving it.
COMMITTEE_FIELD_KEYS: tuple[str, ...] = tuple(s.field_def.field_key for s in COMMITTEE_PACK)


async def load_committee_pack(conn: AsyncConnection) -> None:
    """Register the ``contact.role_on_committee`` + ``contact.persona`` fields (idempotent;
    re-loading is a no-op). Additive and namespaced — never collides with ``CORE_PACK``,
    ``DEEP_PROFILING_PACK``, or the icp packs.

    Wire at the ``api`` composition root alongside ``load_core_pack`` / ``load_deep_profiling_pack``
    (the M8 deferral pattern); until then the committee tests load it per-transaction.
    """
    await load_pack(conn, COMMITTEE_PACK)
