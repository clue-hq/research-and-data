"""The config-bounded Source Planner (M4.6 / ENG-129).

Given ``(mode, entity, field, ICP, …)`` the planner *selects and orders* the sources to consult —
the staged-flow §7d answer to "which open-web sources, in what order, for this field" that the
waterfall (M4.1) then drives. It is the architecture's resolution of the rigidity-vs-fabrication
tension: **config-bounded LLM planning** — the LLM may (a) expand/specialize the per-source queries
and (b) rank/pick *among the allowed sources*, but it can **never** introduce a source outside the
allowed set and **never** emit a value, an entity, or a claim. Three structural guarantees:

* **Hard allowed-set guard.** The allowed set (:func:`~clue_research.sources.source_profile.
  resolve_allowed_set` — profile ∩ registry-capable) is the floor; any planner output naming a
  ``source_key`` outside it is dropped. The LLM cannot widen the set even as the model is swapped.
* **Anti-fabrication by construction.** :class:`OrderedSourcePlan` carries only ``source_key``s +
  query strings — there is no field for a value/entity/claim, so the planner cannot fabricate one.
* **Trust-tier order is never reordered.** The plan orders *within* the waterfall's tier discipline
  (substrate §4): a stable sort by tier means a tier-1 source is never placed after a tier-3 one;
  the LLM refines *which* sources at each tier, not the tier order itself.

The LLM is **optional**: with no gateway the planner returns the deterministic, weight-ordered,
gated plan (the config is the floor). That is also why swapping the planning model leaves the
``OrderedSourcePlan`` contract and the allowed-set guarantee unchanged — the model only reorders
*within* the allowed set and writes queries; everything load-bearing is computed deterministically.
"""

from __future__ import annotations

import json
from collections.abc import Sequence
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.ext.asyncio import AsyncConnection

from clue_core import (
    CostCents,
    Entity,
    EntityScope,
    GateDecision,
    ICPSpec,
    LLMGateway,
    Message,
    Modality,
    ResearchMode,
    Role,
)
from clue_research.icp import ResolvedSourceProfile, SourceWeight
from clue_research.obs import (
    ATTR_FIELD_KEY,
    ATTR_ICP_ID,
    ATTR_N_SOURCES,
    ATTR_RESEARCH_MODE,
    SPAN_SOURCE_PLAN,
    apply_attributes,
    traced_step,
)
from clue_research.sources.source_profile import (
    AllowedSource,
    resolve_allowed_set,
)

# The profiling modes (M2/M4) — the only modes that may trigger an expensive modality (staged-flow
# §7d: discovery modes M1/M3 never transcribe). Named here so the default config reads clearly.
_PROFILING_MODES = frozenset({ResearchMode.ACCOUNT_PROFILING, ResearchMode.CONTACT_PROFILING})


class SourcePlannerConfig(BaseModel):
    """Versioned planner policy — *data, not code* (conventions §2; like ``ConfidenceThresholds``).

    The expensive-modality gate and the fan-out cap are the levers D7 surfaces, not hardcodes: a
    per-client/per-ICP override layers through the same config seam without touching the engine.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    version: int = 1
    # Modalities whose ``fetch → adapt → extract`` is expensive (transcription) and must be gated.
    expensive_modalities: frozenset[Modality] = Field(
        default_factory=lambda: frozenset({Modality.VIDEO, Modality.AUDIO})
    )
    # An expensive modality only runs in these modes (M2/M4 profiling; never M1/M3 discovery).
    gate_expensive_modes: frozenset[ResearchMode] = Field(
        default_factory=lambda: frozenset(_PROFILING_MODES)
    )
    # …and only for a source the profile weights at least this high (staged-flow §7d).
    gate_expensive_min_weight: SourceWeight = SourceWeight.HIGH
    # …and only for an entity whose tier is in this set ("high-tier entities"). ``None`` waives the
    # entity-tier requirement; an entity with no tier never clears a non-``None`` set (cautious).
    gate_expensive_entity_tiers: frozenset[str] | None = Field(
        default_factory=lambda: frozenset({"high"})
    )
    # Optional fan-out cap (cost governance, Doc C §5): at most this many sources per plan.
    max_sources: int | None = None
    # Cap the LLM's per-source query expansion (bounded fan-out).
    max_queries_per_source: int = 5


DEFAULT_SOURCE_PLANNER_CONFIG = SourcePlannerConfig()


class PlannedSource(BaseModel):
    """One source in an :class:`OrderedSourcePlan`: which source, at what tier, with what queries,
    and whether its (expensive) modality is gated to run. It carries **no value/entity/claim** — the
    planner emits sources + queries, never facts (the anti-fabrication invariant)."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    source_key: str
    tier: int
    weight: SourceWeight
    modality: Modality
    queries: tuple[str, ...] = ()
    gate_decision: GateDecision = GateDecision.RUN


class OrderedSourcePlan(BaseModel):
    """The planner's output: the ordered, tier-disciplined, gated source set + the dropped off-set
    keys (audit) + a human rationale. Drives the waterfall (M4.1) via :meth:`tier_plan`."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    field: str
    mode: ResearchMode
    ordered_sources: tuple[PlannedSource, ...] = ()
    # source_keys an LLM named that were NOT in the allowed set — dropped by the hard guard (audit).
    dropped_off_set: tuple[str, ...] = ()
    rationale: str = ""

    def tier_plan(self) -> tuple[str, ...]:
        """The executable ``tier_plan`` for the waterfall: the **RUN** sources' keys, in plan order.

        A ``SKIP`` source (expensive modality gated off) is omitted — it would yield nothing — so a
        caller drives the waterfall over only the sources the plan means to consult, via
        ``field_def.model_copy(update={"tier_plan": plan.tier_plan()})``.
        """
        return tuple(
            s.source_key for s in self.ordered_sources if s.gate_decision is GateDecision.RUN
        )


def _gate_for(
    source: AllowedSource,
    *,
    mode: ResearchMode,
    entity_tier: str | None,
    config: SourcePlannerConfig,
) -> GateDecision:
    """The expensive-modality gate verdict for one source (staged-flow §7d).

    A non-expensive modality always runs. An expensive one runs only in a profiling mode (M2/M4),
    for a high-enough-weighted source, for a high-tier entity — else ``SKIP`` (no spend). M4.3's
    ``run_pipeline`` honors the verdict verbatim.
    """
    if source.modality not in config.expensive_modalities:
        return GateDecision.RUN
    if mode not in config.gate_expensive_modes:
        return GateDecision.SKIP
    if source.weight.prior < config.gate_expensive_min_weight.prior:
        return GateDecision.SKIP
    tiers = config.gate_expensive_entity_tiers
    if tiers is not None and (entity_tier is None or entity_tier not in tiers):
        return GateDecision.SKIP
    return GateDecision.RUN


def _planner_messages(
    field: str, mode: ResearchMode, entity: Entity, allowed: Sequence[AllowedSource]
) -> list[Message]:
    """Build the config-bounded planning prompt: the allowed set + the task, with the hard rules.

    The entity is named by **id and type only** — never any of its facts — so the model has nothing
    to fabricate from. The model is told it may only choose among the listed sources and write
    queries; the runtime guard enforces it regardless of what the model returns.
    """
    catalog = [
        {
            "source_key": s.source_key,
            "tier": s.tier,
            "weight": s.weight.value,
            "modality": s.modality.value,
        }
        for s in allowed
    ]
    system = (
        "You are a source planner for a research pipeline. You are given an ALLOWED SET of sources "
        "(each with a trust tier, a weight, and a modality) that can populate a field for an "
        "entity. Choose and order the sources to consult and write specific search queries.\n"
        "HARD RULES:\n"
        "1. Use ONLY source_keys from the allowed set. Never name any other source.\n"
        "2. Never invent a fact, a value, or an entity. Return ONLY sources and search queries.\n"
        "3. Do not reorder trust tiers; prefer higher-weight sources within a tier.\n"
        'Return STRICT JSON: {"ranking": [source_key, ...], '
        '"queries": {source_key: [query, ...]}}. No prose, no code fences.'
    )
    user = json.dumps(
        {
            "field": field,
            "mode": mode.value,
            "entity": {"entity_id": str(entity.entity_id), "entity_type": entity.entity_type.value},
            "allowed_set": catalog,
        }
    )
    return [Message(role=Role.SYSTEM, content=system), Message(role=Role.USER, content=user)]


def _parse_plan_json(text: str) -> dict[str, object] | None:
    """Parse the planner LLM's JSON, tolerating fences/prose; return ``None`` if unusable.

    Robustness is the point: a non-JSON answer (e.g. the deterministic stub gateway's digest) must
    fall back to the deterministic plan, never raise — the config is always the floor.
    """
    for candidate in (text, _slice_braces(text)):
        if not candidate:
            continue
        try:
            parsed = json.loads(candidate)
        except (json.JSONDecodeError, ValueError):
            continue
        if isinstance(parsed, dict):
            return parsed
    return None


def _slice_braces(text: str) -> str | None:
    start = text.find("{")
    end = text.rfind("}")
    return text[start : end + 1] if 0 <= start < end else None


def _llm_refine(
    gateway: LLMGateway,
    model: str,
    field: str,
    mode: ResearchMode,
    entity: Entity,
    allowed: Sequence[AllowedSource],
    *,
    max_queries: int,
) -> tuple[list[str], dict[str, tuple[str, ...]], list[str]]:
    """Run the config-bounded LLM refinement, applying the hard allowed-set guard to its output.

    Returns ``(ranking, queries, dropped)``: ``ranking`` is the LLM's preferred consult order
    **filtered to the allowed set**; ``queries`` are per-allowed-source query strings (capped);
    ``dropped`` are off-set keys the LLM tried to introduce (audit). Any failure → empty refinement
    (the deterministic plan stands).
    """
    allowed_keys = {s.source_key for s in allowed}
    completion = gateway.complete(
        model=model, messages=_planner_messages(field, mode, entity, allowed)
    )
    parsed = _parse_plan_json(completion.text)
    if parsed is None:
        return [], {}, []

    raw_ranking = parsed.get("ranking")
    ranking: list[str] = []
    dropped: list[str] = []
    if isinstance(raw_ranking, list):
        for key in raw_ranking:
            if not isinstance(key, str):
                continue
            if key in allowed_keys and key not in ranking:
                ranking.append(key)
            elif key not in allowed_keys and key not in dropped:
                dropped.append(key)  # the hard guard: an off-set source is dropped, never planned

    raw_queries = parsed.get("queries")
    queries: dict[str, tuple[str, ...]] = {}
    if isinstance(raw_queries, dict):
        for key, value in raw_queries.items():
            if not isinstance(key, str) or key not in allowed_keys:
                # an off-set source named via the queries channel is also a guard violation — drop
                # + audit it (like the ranking branch). A malformed value for an IN-set key is not
                # an off-set attempt, so it is skipped silently, not recorded as dropped.
                if isinstance(key, str) and key not in allowed_keys and key not in dropped:
                    dropped.append(key)
                continue
            if not isinstance(value, list):
                continue
            qs = tuple(q for q in value if isinstance(q, str) and q.strip())[:max_queries]
            if qs:
                queries[key] = qs
    return ranking, queries, dropped


async def plan_sources(
    conn: AsyncConnection,
    *,
    spec: ICPSpec,
    entity: Entity,
    field: str,
    mode: ResearchMode,
    tier_scope: int | None = None,
    entity_tier: str | None = None,
    entity_scope: EntityScope | str | None = None,
    budget_envelope: Decimal | None = None,
    gateway: LLMGateway | None = None,
    planner_model: str | None = None,
    config: SourcePlannerConfig = DEFAULT_SOURCE_PLANNER_CONFIG,
    served: ResolvedSourceProfile | None = None,
) -> OrderedSourcePlan:
    """Select + order the sources to consult for ``field`` under ``spec`` (staged-flow §7d).

    Resolves the allowed set (profile ∩ registry-capable, :func:`resolve_allowed_set`), optionally
    lets the LLM rank/pick within it and write queries (``gateway`` + ``planner_model``; omit either
    for the deterministic config-only plan), orders within trust-tier discipline, applies the
    expensive-modality gate + the ``budget_envelope`` halt, and returns the plan. It writes no
    claims and never names a source outside the allowed set.

    ``entity_tier`` is the entity's assigned tier band (e.g. ``"high"`` from M3.4's ``assign_tier``)
    — the gate's "high-tier entity" input. ``budget_envelope`` is the per-call source-spend ceiling
    (M7.5-owned, honored here): the plan halts before the first RUN source that would exceed it.
    ``tier_scope`` is an **inclusive upper bound** — the plan spans every tier ``<= tier_scope``
    (``None`` = all tiers), so passing ``3`` plans the trust-tiered tiers 1–3 and excludes the
    tier-4 synthesis placeholders (M4 ships tiers 1–3); the plan still orders within tier order.

    The plan's per-source ``queries`` are **inert** LLM-expanded search intents here — never claims
    or entities; a downstream consumer that drives them must target-lock each to the resolved
    ``entity_id`` (the discovery existence-gate), never letting a query string introduce an entity.
    """
    allowed = await resolve_allowed_set(
        conn, spec, field, max_tier=tier_scope, entity_scope=entity_scope, served=served
    )
    icp_id = f"{spec.client_id}/{spec.icp_key}@{spec.version}"

    with traced_step(
        SPAN_SOURCE_PLAN,
        **{ATTR_ICP_ID: icp_id, ATTR_FIELD_KEY: field, ATTR_RESEARCH_MODE: mode.value},
    ) as span:
        if not allowed:
            apply_attributes(span, {ATTR_N_SOURCES: 0})
            return OrderedSourcePlan(
                field=field,
                mode=mode,
                rationale=(
                    "no registered, profile-weighted source can yield this field at the requested "
                    "tier (empty allowed set) — nothing to plan"
                ),
            )

        # --- config-bounded LLM refinement (optional; hard-guarded) ---------------
        ranking: list[str] = []
        queries: dict[str, tuple[str, ...]] = {}
        dropped: list[str] = []
        used_llm = gateway is not None and planner_model is not None
        if used_llm:
            assert gateway is not None and planner_model is not None  # narrowed by used_llm
            ranking, queries, dropped = _llm_refine(
                gateway,
                planner_model,
                field,
                mode,
                entity,
                allowed,
                max_queries=config.max_queries_per_source,
            )

        # --- within-tier preference order, then a STABLE sort by tier (tier discipline) ----
        order_index = {key: i for i, key in enumerate(ranking)}
        served_pos = {s.source_key: i for i, s in enumerate(allowed)}
        preferred = sorted(
            allowed,
            key=lambda s: order_index.get(s.source_key, len(ranking) + served_pos[s.source_key]),
        )
        tier_ordered = sorted(preferred, key=lambda s: s.tier)  # stable → tier-1 never after tier-3

        # --- gate + budget halt ---------------------------------------------------
        # The fan-out cap (max_sources) and the budget envelope bound the *consulted* (RUN) sources
        # only — a SKIP yields nothing, spends nothing, and is not consulted (tier_plan() omits it),
        # so neither knob should count it (mirrors how budget already treats SKIP as free).
        included: list[PlannedSource] = []
        spent: CostCents = Decimal(0)
        n_run = 0
        budget_halted = False
        for source in tier_ordered:
            gate = _gate_for(source, mode=mode, entity_tier=entity_tier, config=config)
            if gate is GateDecision.RUN:
                if config.max_sources is not None and n_run >= config.max_sources:
                    break  # fan-out cap reached — don't consult another RUN source
                if budget_envelope is not None and spent + source.cost_cents > budget_envelope:
                    budget_halted = True
                    break  # halt before the first RUN source that would exceed the envelope
            included.append(
                PlannedSource(
                    source_key=source.source_key,
                    tier=source.tier,
                    weight=source.weight,
                    modality=source.modality,
                    queries=queries.get(source.source_key, ()),
                    gate_decision=gate,
                )
            )
            if gate is GateDecision.RUN:
                spent += source.cost_cents
                n_run += 1

        apply_attributes(span, {ATTR_N_SOURCES: len(included)})
        return OrderedSourcePlan(
            field=field,
            mode=mode,
            ordered_sources=tuple(included),
            dropped_off_set=tuple(dropped),
            rationale=_rationale(
                used_llm=used_llm,
                n_allowed=len(allowed),
                n_included=len(included),
                dropped=dropped,
                budget_halted=budget_halted,
            ),
        )


def _rationale(
    *, used_llm: bool, n_allowed: int, n_included: int, dropped: Sequence[str], budget_halted: bool
) -> str:
    parts = [
        f"{'LLM-ranked' if used_llm else 'config-ordered'} within the allowed set "
        f"({n_included}/{n_allowed} sources planned, tier-ordered)"
    ]
    if dropped:
        parts.append(
            f"dropped {len(dropped)} off-set source(s) the planner named: {sorted(dropped)}"
        )
    if budget_halted:
        parts.append("halted early: the next source would exceed the budget envelope")
    return "; ".join(parts)
