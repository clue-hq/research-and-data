"""M4.6 — DB-free structural invariants of the Source Planner (ENG-129).

These run on every CI pass (no ``require_db``): the anti-fabrication invariant (the plan has no
value/entity field), the hard allowed-set guard inside the LLM refinement, the pure gate logic, the
robust JSON parse, and the ``GateDecision`` relocation that lets the plan carry the literal verdict
M4.3 honors. The DB-backed acceptance criteria live in ``test_planner.py``.
"""

from __future__ import annotations

from decimal import Decimal

import clue_research.adapters as adapters
import clue_research.core as core
from clue_research.core import (
    Completion,
    EmbeddingResult,
    Entity,
    EntityScope,
    EntityType,
    GateDecision,
    Message,
    Modality,
    ResearchMode,
    new_entity_id,
)
from clue_research.icp import SourceWeight
from clue_research.sources import OrderedSourcePlan, PlannedSource, SourcePlannerConfig
from clue_research.sources.planner import _gate_for, _llm_refine, _parse_plan_json
from clue_research.sources.source_profile import AllowedSource

_M2 = ResearchMode.ACCOUNT_PROFILING
_M1 = ResearchMode.ACCOUNT_DISCOVERY
_CFG = SourcePlannerConfig()


class _ScriptedGateway:
    """A fake :class:`~clue_research.core.LLMGateway` returning a fixed completion (hermetic)."""

    def __init__(self, text: str) -> None:
        self._text = text

    def complete(self, *, model: str, messages: list[Message], **opts: object) -> Completion:
        return Completion(model=model, text=self._text)

    def embed(self, *, model: str, inputs: list[str]) -> EmbeddingResult:
        return EmbeddingResult(model=model)


def _allowed(
    source_key: str,
    *,
    weight: SourceWeight = SourceWeight.HIGH,
    tier: int = 3,
    modality: Modality = Modality.STRUCTURED,
    rank: int = 1,
) -> AllowedSource:
    return AllowedSource(
        source_key=source_key,
        weight=weight,
        rank=rank,
        tier=tier,
        modality=modality,
        entity_scope=EntityScope.BOTH,
        cost_cents=Decimal(1),
    )


def _entity() -> Entity:
    return Entity(entity_id=new_entity_id(), entity_type=EntityType.ACCOUNT)


# --- the GateDecision relocation (core is the single shared home) ------------


def test_gate_decision_is_one_shared_type() -> None:
    # The plan carries the literal verdict M4.3's run_pipeline honors via an identity check, so the
    # producer (planner, in sources) and the consumer (adapters) MUST bind to one object.
    assert adapters.GateDecision is core.GateDecision
    assert GateDecision.RUN.value == "run" and GateDecision.SKIP.value == "skip"


# --- anti-fabrication: the plan can structurally carry no value/entity/claim --


def test_plan_models_have_no_value_or_entity_field() -> None:
    forbidden = {"value", "value_json", "entity", "entity_id", "claim", "claims"}
    assert not (set(PlannedSource.model_fields) & forbidden)
    assert not (set(OrderedSourcePlan.model_fields) & forbidden)
    # the plan emits only source_keys + queries + the gate verdict.
    assert set(PlannedSource.model_fields) >= {"source_key", "queries", "gate_decision", "tier"}


def test_tier_plan_excludes_skipped_sources() -> None:
    plan = OrderedSourcePlan(
        field="account.resonance.culture",
        mode=_M2,
        ordered_sources=(
            PlannedSource(
                source_key="a", tier=1, weight=SourceWeight.HIGH, modality=Modality.STRUCTURED
            ),
            PlannedSource(
                source_key="pod",
                tier=3,
                weight=SourceWeight.HIGH,
                modality=Modality.AUDIO,
                gate_decision=GateDecision.SKIP,
            ),
        ),
    )
    assert plan.tier_plan() == ("a",)  # the SKIP'd expensive source is not consulted


# --- the pure gate logic (staged-flow §7d) -----------------------------------


def test_gate_runs_cheap_modality_always() -> None:
    src = _allowed("builtwith", modality=Modality.STRUCTURED, tier=1)
    assert _gate_for(src, mode=_M2, entity_tier="low", config=_CFG) is GateDecision.RUN


def test_gate_runs_expensive_only_when_high_tier_high_weight_profiling() -> None:
    pod = _allowed("podcast", modality=Modality.AUDIO, weight=SourceWeight.HIGH, tier=3)
    assert _gate_for(pod, mode=_M2, entity_tier="high", config=_CFG) is GateDecision.RUN
    # low-tier entity → skip
    assert _gate_for(pod, mode=_M2, entity_tier="low", config=_CFG) is GateDecision.SKIP
    # missing tier → skip (conservative: no spend without high-tier evidence)
    assert _gate_for(pod, mode=_M2, entity_tier=None, config=_CFG) is GateDecision.SKIP
    # discovery mode (M1) never triggers an expensive modality
    assert _gate_for(pod, mode=_M1, entity_tier="high", config=_CFG) is GateDecision.SKIP
    # low-weighted source class → skip even for a high-tier entity
    low = _allowed("podcast", modality=Modality.AUDIO, weight=SourceWeight.LOW, tier=3)
    assert _gate_for(low, mode=_M2, entity_tier="high", config=_CFG) is GateDecision.SKIP


# --- the hard allowed-set guard inside the LLM refinement ---------------------


def test_llm_refine_drops_off_set_sources() -> None:
    allowed = [_allowed("arxiv", tier=3), _allowed("github", tier=3)]
    # the model tries to introduce 'shady_blog' (not in the allowed set) — it must be dropped.
    gw = _ScriptedGateway(
        '{"ranking": ["github", "shady_blog", "arxiv"], '
        '"queries": {"github": ["repo activity"], "shady_blog": ["anything"]}}'
    )
    ranking, queries, dropped = _llm_refine(
        gw, "planner-model", "account.resonance.culture", _M2, _entity(), allowed, max_queries=5
    )
    assert ranking == ["github", "arxiv"]  # off-set 'shady_blog' removed; order otherwise kept
    assert dropped == ["shady_blog"]
    assert queries == {"github": ("repo activity",)}  # off-set source's queries dropped too
    assert "shady_blog" not in queries


def test_llm_refine_falls_back_on_unparseable_output() -> None:
    # a non-JSON answer (e.g. the deterministic stub gateway's digest) → empty refinement, no raise.
    gw = _ScriptedGateway("stub:deadbeefdeadbeef")
    ranking, queries, dropped = _llm_refine(
        gw, "m", "account", _M2, _entity(), [_allowed("arxiv")], max_queries=5
    )
    assert ranking == [] and queries == {} and dropped == []


def test_parse_plan_json_tolerates_fences_and_prose() -> None:
    assert _parse_plan_json('{"ranking": []}') == {"ranking": []}
    assert _parse_plan_json('```json\n{"ranking": ["a"]}\n```') == {"ranking": ["a"]}
    assert _parse_plan_json('here you go: {"ranking": ["a"]} done') == {"ranking": ["a"]}
    assert _parse_plan_json("stub:deadbeef") is None
    assert _parse_plan_json("[1, 2, 3]") is None  # a JSON array is not the expected object
