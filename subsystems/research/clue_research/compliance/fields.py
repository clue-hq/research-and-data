"""The M10 compliance field pack — the field-registry rows M10 owns (M10.1, M10.5).

A *pack* is a versioned set of field definitions registered idempotently (the M1.3 mechanism;
``claimstore.load_pack`` → ``register_field`` per row). M10 ships its own pack rather than editing
the M1-owned ``claimstore/packs.py`` ``CORE_PACK`` (a phase-3 pre-flight "must-not-touch"), and the
``api`` composition root appends :func:`load_compliance_pack` to ``RESEARCH_PACK_LOADERS`` (PF-7) so
the three milestone branches never co-edit a shared loader.

M10.1 adds ``contact.jurisdiction`` — the resolved data-protection regime stored *as a claim* (so it
carries provenance and supersedes via the normal merge; Doc D §1). It is a ``contact.*`` field
(``FieldClass.CONTACT``), **not** ``contact.facet.*``, so it does not require the
``identity_binding`` / ``use_class`` governance provenance the personal-hook class mandates; it is
``TENANT_PRIVATE`` (jurisdiction is about a named person — personal, never cross-tenant amortized).
M10.5 will extend this pack with shorter ``contact.facet.*`` retention/freshness rows.
"""

from __future__ import annotations

from datetime import timedelta

from sqlalchemy.ext.asyncio import AsyncConnection

from clue_core import FieldDef, PassKind, ReuseScope
from clue_research.claimstore import SeedField, load_pack

# The registered field-key for a contact's resolved regime (M10.1). Imported by the resolver so the
# key is spelled once.
CONTACT_JURISDICTION = "contact.jurisdiction"

COMPLIANCE_PACK: tuple[SeedField, ...] = (
    SeedField(
        field_def=FieldDef(
            field_key=CONTACT_JURISDICTION,
            value_type="object",
            tier_plan=(),  # computed by the M10.1 resolver, not fetched by a resolver chain
            # Jurisdiction changes only when a contact's location does; a later, higher-tier
            # location claim supersedes the prior jurisdiction claim via the normal merge.
            freshness_ttl=timedelta(days=180),
            pass_kind=PassKind.DEEP,  # resolved during the deep/verification pass on contacts
            # A named person's regime is personal data — tenant-isolated, never cross-tenant.
            reuse_scope=ReuseScope.TENANT_PRIVATE,
        ),
        # NB: the substrate validator (claimstore.registry._validate_payload) supports only a
        # *single* scalar ``type`` per property (its ``_SCALAR_CHECKS`` is keyed by a string, so a
        # list-typed ``"type": [...]`` would raise) — so ``region`` is a plain string and is
        # *omitted* from value_json when None (not ``required``; an absent optional key validates
        # cleanly). See JurisdictionResolverImpl._value_json.
        value_schema={
            "type": "object",
            "required": ["regime"],
            "properties": {
                "regime": {"type": "string"},
                "region": {"type": "string"},
                "confidence": {"type": "number"},
                "derived_from": {"type": "string"},
                "jurisdiction_unknown": {"type": "boolean"},
            },
        },
        description=(
            "Resolved data-protection regime for a contact (Doc D §1; M10.1). "
            "Tenant-private; value carries {regime, region, confidence, derived_from}."
        ),
    ),
)


async def load_compliance_pack(conn: AsyncConnection) -> None:
    """Register the M10 compliance field pack (idempotent; re-loading is a no-op)."""
    await load_pack(conn, COMPLIANCE_PACK)
