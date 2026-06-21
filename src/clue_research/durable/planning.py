"""The orchestrator/lead's plan: gap-field detection + aspect clustering (M7.1).

The lead node reads the active deep-pass research schema (M3 field registry, via M4) and the
account's ``current_value`` (M1 merge view), computes which fields are *gaps* (no fresh value yet),
and clusters them into **aspect plans** — one cluster per field-class — each handed to one aspect
worker. The plan is a typed, serializable object persisted to ``account_run.plan_json`` **before
any worker spawns** (substrate §5b: externalize the plan early so the run survives a crash and the
lead's context never re-ingests detail).

Clustering by field-class is deliberate: the recursion-eligible classes the M7.2 knob recurses on
— ``account.resonance.*`` and ``contact.facet.*`` — are exactly these aspect keys, so the
two-level fan-out attaches cleanly. ``worker_count`` / ``depth`` / ``budget_envelope_cents`` are
the effort-scaling parameters this issue *exposes*; their per-tier values are enforced by M7.2's
caps and M7.5's budget (M7.1 ships safe single-worker, depth-0 defaults).
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Sequence

from pydantic import BaseModel, ConfigDict
from sqlalchemy.ext.asyncio import AsyncConnection

from clue_research.claimstore import current_values
from clue_research.claimstore.registry import get_field, list_fields
from clue_research.claimstore.tenancy import TenantScope
from clue_research.core import CostCents, EntityId, FreshnessState, PassKind
from clue_research.core.field import FieldClass, FieldDef, field_namespace


class AspectPlan(BaseModel):
    """One aspect cluster the lead plans (M7.1): a field-class's gap fields, the worker count to
    spawn, the recursion depth allowed, and (M7.5) the budget envelope. The orchestrator dispatches
    one :class:`~clue_research.core.AspectWorker` per aspect; ``depth`` ≥ 1 marks an aspect that the
    M7.2 knob may let recurse into facet sub-workers."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    aspect: str
    field_keys: tuple[str, ...]
    worker_count: int = 1
    depth: int = 0
    budget_envelope_cents: CostCents | None = None


class ResearchPlan(BaseModel):
    """The lead's typed research plan for one account run (M7.1) — persisted to
    ``account_run.plan_json`` before any worker spawns. Holds the ordered aspect clusters and the
    tier that scaled them; never any claim values."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    tier: str
    aspects: tuple[AspectPlan, ...] = ()

    @property
    def gap_field_count(self) -> int:
        return sum(len(a.field_keys) for a in self.aspects)


def _aspect_key(field: FieldDef) -> str:
    """The aspect-cluster key for a field: its field-class, except packs cluster by their namespace
    (so ``healthcare.*`` and ``frontier_ai.*`` are distinct aspects, not one ``pack`` blob)."""
    if field.field_class is FieldClass.PACK:
        return field_namespace(field.field_key)
    return field.field_class.value


def build_plan(
    gap_fields: Sequence[FieldDef],
    *,
    tier: str,
    worker_count: int = 1,
    depth: int = 0,
) -> ResearchPlan:
    """Cluster gap fields into aspect plans (pure). Deterministic: aspects are ordered by key and
    field keys within an aspect are sorted, so the same gaps always yield the same plan (a stable
    ``plan_json`` across retries). ``worker_count``/``depth`` are the effort-scaling knobs M7.2/M7.5
    parameterize per tier; M7.1 applies the safe defaults uniformly."""
    clustered: dict[str, list[str]] = defaultdict(list)
    for field in gap_fields:
        clustered[_aspect_key(field)].append(field.field_key)
    aspects = tuple(
        AspectPlan(
            aspect=aspect,
            field_keys=tuple(sorted(keys)),
            worker_count=worker_count,
            depth=depth,
        )
        for aspect, keys in sorted(clustered.items())
    )
    return ResearchPlan(tier=tier, aspects=aspects)


async def compute_gap_fields(
    conn: AsyncConnection,
    entity_id: EntityId,
    *,
    scope: TenantScope,
    field_keys: Sequence[str] | None = None,
) -> list[FieldDef]:
    """Return the deep-pass fields that still need research for ``entity_id`` (M7.1).

    A field is a **gap** when the merge view yields no current truth for it, or yields a value that
    is not ``FRESH`` (``STALE`` past its TTL, or ``EXPIRED`` aged-out) — all mean a fresh value is
    wanted. ``field_keys`` narrows the schema to an ICP-active subset (the campaign layer gives it);
    ``None`` uses the full registered deep-pass schema (``pass_kind = deep``). Non-fresh-but-present
    fields are returned so a refresh is scheduled, never silently dropped (substrate §1/§6)."""
    if field_keys is None:
        fields = await list_fields(conn, pass_kind=PassKind.DEEP)
    else:
        fields = [f for k in field_keys if (f := await get_field(conn, k)) is not None]
    if not fields:
        return []

    values = await current_values(conn, [entity_id], [f.field_key for f in fields], scope=scope)
    gaps: list[FieldDef] = []
    for field in fields:
        current = values.get((entity_id, field.field_key))
        if current is None or current.freshness_state is not FreshnessState.FRESH:
            gaps.append(field)
    return gaps
