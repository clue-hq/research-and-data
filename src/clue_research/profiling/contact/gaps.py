"""Contact gap-field computation (M8.4) — the converge loop's checklist.

Mode M4 is *profiling*: closed and target-locked, the contact-axis analogue of M2's converge loop.
Before spending, it reads the active deep contact field set and the contact's current claims, and
computes the **gap fields** — deep ``contact.*`` / ``contact.facet.*`` fields with a ``tier_plan``
(i.e. fillable) that have no fresh resolved value yet. A field whose current value is missing or
stale (past its short personal-data TTL — people change) is a gap; a field with no ``tier_plan`` is
M3-produced (role/persona) and is **not** in the gap set (the waterfall/extraction cannot fill it).
"""

from __future__ import annotations

from collections.abc import Sequence

from sqlalchemy.ext.asyncio import AsyncConnection

from clue_research.claimstore import TenantScope, list_fields
from clue_research.core import EntityId, EntityType, FieldClass, FieldDef, FreshnessState, PassKind
from clue_research.identity import current_value_resolved


async def compute_contact_gap_fields(
    conn: AsyncConnection,
    contact_entity_id: EntityId,
    *,
    tenant_id: str,
    field_keys: Sequence[str] | None = None,
) -> list[FieldDef]:
    """The deep contact fields still needing research for this contact (the converge checklist).

    Enumerates registered ``pass=deep`` ``contact``/``contact.facet`` fields with a non-empty
    ``tier_plan`` (fillable), optionally narrowed to ``field_keys`` (the aspect's cluster), and
    keeps only those whose merge-resolved current value is absent or not ``FRESH``. Reads are
    tenant-scoped (facet/contact claims are tenant-private), resolved across merges."""
    registered: list[FieldDef] = []
    for field_class in (FieldClass.CONTACT_FACET, FieldClass.CONTACT):
        registered.extend(await list_fields(conn, pass_kind=PassKind.DEEP, field_class=field_class))

    wanted = set(field_keys) if field_keys is not None else None
    candidates = [
        field
        for field in registered
        if field.tier_plan and (wanted is None or field.field_key in wanted)
    ]

    scope = TenantScope.for_tenant(tenant_id)
    gaps: list[FieldDef] = []
    for field in candidates:
        current = await current_value_resolved(
            conn,
            contact_entity_id,
            field.field_key,
            scope=scope,
            entity_type=EntityType.CONTACT,
        )
        if current is None or current.freshness_state is not FreshnessState.FRESH:
            gaps.append(field)
    return gaps
