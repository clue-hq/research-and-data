"""Source-profile serving + the registry-intersection allowed set (M4.6 / ENG-129).

The runtime half of the M3.3 source-profile seam (locked decision #5): **M3.3 *authors* the per-pack
priors** (``icp.source_profile`` / migration 0009); **M4.6 *serves and plans against* them**, keyed
to M4.2 ``source_key``s. This module owns two things and re-authors nothing (DRY):

* :func:`serve_source_profile` — resolve one *ICP*'s effective source profile by merging every pack
  in ``ICPSpec.enabled_packs`` (each resolved pack-default ⊕ client/ICP override by M3.3's
  :func:`~clue_research.icp.get_pack_source_profile`). This is the ICP-level analogue the spec calls
  ``get_source_profile(icp_version, field_class)`` — distinct from (and never shadowing) M3.3's
  *pack*-level ``get_source_profile(pack_key, …)`` it builds on.
* :func:`resolve_allowed_set` — the **allowed set = profile ∩ registry-capable**: the served
  weighted sources intersected with the sources the M4.2 registry says can actually *yield* at the
  relevant tier (``sources_for``). "Can't plan a source that doesn't exist" — a profile may name a
  ``source_key`` whose manifest is not yet seeded (the long-tail provider manifests); the
  intersection drops it. This is the hard floor the planner's config-bounded LLM may rank/pick
  *within* but never widen (staged-flow §7d).
"""

from __future__ import annotations

from collections.abc import Sequence

from pydantic import BaseModel, ConfigDict
from sqlalchemy.ext.asyncio import AsyncConnection

from clue_research.core import (
    CostCents,
    EntityScope,
    FieldClass,
    ICPSpec,
    Modality,
    classify_field_key,
    is_valid_field_key,
)
from clue_research.icp import (
    ResolvedSourceProfile,
    SourceWeight,
    WeightedSource,
    get_pack_source_profile,
    slot_for,
)
from clue_research.sources.registry import list_sources, sources_for


class ServedSourceProfile(BaseModel):
    """One *ICP*'s effective source profile — every enabled pack merged into one weighted set.

    The ICP-level analogue of M3.3's pack-level :class:`~clue_research.icp.ResolvedSourceProfile`:
    ``default`` is the pack-wide slot (merged across packs); ``by_field_class`` holds the
    field-class-specific slots any pack authored. :meth:`for_field_class` falls back to ``default``
    when a field-class has no specific slot (mirroring the pack-level resolver), so the starter
    packs — which author only the pack-wide default — serve that default for every field-class.
    """

    model_config = ConfigDict(frozen=True)

    packs: tuple[str, ...] = ()
    default: tuple[WeightedSource, ...] = ()
    by_field_class: dict[FieldClass, tuple[WeightedSource, ...]] = {}

    def for_field_class(self, field_class: FieldClass | None) -> tuple[WeightedSource, ...]:
        """The effective weighted sources for ``field_class`` (specific slot, else pack-wide)."""
        return slot_for(self.default, self.by_field_class, field_class)


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


def _merge_slot(weighted_lists: Sequence[Sequence[WeightedSource]]) -> tuple[WeightedSource, ...]:
    """Merge per-pack weighted-source lists into one ordered slot.

    Dedup by ``source_key`` keeping the strongest weight (tie-break: lowest authored ``rank``), then
    order by weight prior DESC → rank ASC → key (deterministic). For a single-pack ICP this exactly
    reproduces the pack's staged-flow §7c ordering, since each pack authors its sources in
    weight-descending order.
    """
    best: dict[str, WeightedSource] = {}
    for lst in weighted_lists:
        for ws in lst:
            current = best.get(ws.source_key)
            if (
                current is None
                or ws.weight.prior > current.weight.prior
                or (ws.weight.prior == current.weight.prior and ws.rank < current.rank)
            ):
                best[ws.source_key] = ws
    return tuple(sorted(best.values(), key=lambda w: (-w.weight.prior, w.rank, w.source_key)))


async def serve_source_profile(
    conn: AsyncConnection,
    spec: ICPSpec,
    *,
    packs: Sequence[str] | None = None,
) -> ServedSourceProfile:
    """Resolve ``spec``'s effective source profile: every enabled pack, merged.

    Each pack is resolved with the client/ICP override applied (M3.3's
    :func:`~clue_research.icp.get_pack_source_profile`, keyed by ``pack_key`` with
    ``client_id``/``icp_key`` from the spec — override > pack default). The merge unions the packs'
    weighted sets (see :func:`_merge_slot`). ``packs`` overrides ``spec.enabled_packs`` (for an
    audit of a subset); the default serves exactly the ICP's enabled packs.
    """
    pack_keys = tuple(packs) if packs is not None else tuple(spec.enabled_packs)
    profiles: list[ResolvedSourceProfile] = [
        await get_pack_source_profile(
            conn, pack_key, client_id=spec.client_id, icp_key=spec.icp_key
        )
        for pack_key in pack_keys
    ]

    explicit_fcs: set[FieldClass] = set()
    for profile in profiles:
        explicit_fcs.update(profile.by_field_class.keys())

    default = _merge_slot([profile.default for profile in profiles])
    by_field_class = {
        fc: _merge_slot([profile.for_field_class(fc) for profile in profiles])
        for fc in explicit_fcs
    }
    return ServedSourceProfile(packs=pack_keys, default=default, by_field_class=by_field_class)


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
    served: ServedSourceProfile | None = None,
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
