"""The registry-intersection allowed set (M4.6 / ENG-129).

The runtime, M4-side half of the source-profile seam (locked decision #5). M3 *authors and serves*
the priors — M3.3 authors the per-pack priors (``icp.source_profile`` / migration 0009), and
``clue_research.icp.serve_source_profile`` merges them into one
:class:`~clue_research.icp.ResolvedSourceProfile`. This module *plans against* that profile,
keyed to M4.2 ``source_key``s, and owns exactly one thing (re-authoring nothing — DRY):

* :func:`resolve_allowed_set` — the **allowed set = served profile ∩ registry-capable**: the served
  weighted sources (:func:`~clue_research.icp.serve_source_profile`) intersected with the sources
  the M4.2 registry says can actually *yield* at the relevant tier (``sources_for``). "Can't plan a
  source that doesn't exist" — a profile may name a ``source_key`` whose manifest is not yet seeded
  (the long-tail provider manifests); the intersection drops it. This is the hard floor the
  planner's config-bounded LLM may rank/pick *within* but never widen (staged-flow §7d).
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict
from sqlalchemy.ext.asyncio import AsyncConnection

from clue_core import (
    CostCents,
    EntityScope,
    FieldClass,
    ICPSpec,
    Modality,
    classify_field_key,
    is_valid_field_key,
)
from clue_research.icp import ResolvedSourceProfile, SourceWeight, serve_source_profile
from clue_research.sources.registry import list_sources, sources_for


class AllowedSource(BaseModel):
    """One source in the **allowed set** — a profile-weighted ``source_key`` the registry confirms
    can yield the field, enriched with the manifest facts the planner needs (tier, modality, cost,
    whether an expensive adapter is required). The planner orders/gates over these; it never widens
    the set beyond what :func:`resolve_allowed_set` returns.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    source_key: str
    weight: SourceWeight
    rank: int  # the profile's authored consult order (tie-break within equal weight)
    tier: int
    modality: Modality
    entity_scope: EntityScope
    requires_adapter: str | None = None
    cost_cents: CostCents


def _slot_field_class(field: str) -> FieldClass | None:
    """The source-profile slot a ``field`` (a field-key or a field-class token) resolves to.

    A concrete key (``core.work_email``) → its class; a canonical class token
    (``account.resonance``) → that class; a pack-namespace field or an unknown token → ``None``
    (the pack-wide default, where the served profile falls back). ``FieldClass.PACK`` is treated as
    ``None`` on purpose: it is a single value shared by *every* pack namespace, so it cannot key a
    per-vertical slot in a multi-pack merge — pack-namespace fields are served by the unambiguous
    pack-wide default (where packs author their pack-field sources), never a cross-pack PACK slot.
    """
    fc: FieldClass | None
    if is_valid_field_key(field):
        fc = classify_field_key(field)
    else:
        try:
            fc = FieldClass(field)
        except ValueError:
            return None
    return None if fc is FieldClass.PACK else fc


async def resolve_allowed_set(
    conn: AsyncConnection,
    spec: ICPSpec,
    field: str,
    *,
    max_tier: int | None = None,
    entity_scope: EntityScope | str | None = None,
    served: ResolvedSourceProfile | None = None,
) -> tuple[AllowedSource, ...]:
    """The allowed set for ``field`` under ``spec``: served weighted sources ∩ registry-capable.

    ``field`` is a field-key or a field-class token. The result keeps only profile ``source_key``s
    the registry confirms can *yield* ``field`` (``sources_for``, M4.2) — registered and active —
    preserving the served weight order and enriching each with its manifest
    (tier/modality/cost/``requires_adapter``). ``max_tier`` is an **inclusive upper bound**: the set
    spans every tier ``<= max_tier`` (``None`` = all tiers), so the plan can span the trust-tiered
    tiers 1..max_tier rather than a single exact tier (passing ``3`` excludes the tier-4 synthesis
    placeholders). ``entity_scope`` widens ``both`` sources. This is the hard floor the planner
    orders and gates over; a profile source whose manifest is absent/inactive/over-tier is silently
    dropped (a correct "can't plan what doesn't exist").
    """
    served = served or await serve_source_profile(conn, spec)
    weighted = served.for_field_class(_slot_field_class(field))
    if not weighted:
        return ()

    # capability across ALL tiers (max_tier is applied below as an inclusive bound, not an exact
    # match), enriched from a single list_sources pass (avoids an N+1 get_source per source).
    capable = set(await sources_for(conn, field, entity_scope=entity_scope, active=True))
    manifests = {m.source_key: m for m in await list_sources(conn, active=True)}
    allowed: list[AllowedSource] = []
    for ws in weighted:
        if ws.source_key not in capable:
            continue
        manifest = manifests.get(ws.source_key)
        if manifest is None:  # capable came from the registry, so this is defensive only
            continue
        if max_tier is not None and manifest.tier > max_tier:
            continue  # over the inclusive tier bound (e.g. a tier-4 placeholder when planning 1..3)
        allowed.append(
            AllowedSource(
                source_key=ws.source_key,
                weight=ws.weight,
                rank=ws.rank,
                tier=manifest.tier,
                modality=manifest.modality,
                entity_scope=manifest.entity_scope,
                requires_adapter=manifest.requires_adapter,
                cost_cents=manifest.cost_cents,
            )
        )
    return tuple(allowed)
