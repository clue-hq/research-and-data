"""M4.6 acceptance: the config-bounded Source Planner (ENG-129).

One test per acceptance criterion: the hard allowed-set guard (drop off-set LLM output); plan ⊆
profile ∩ registry-capable; trust-tier order never reordered (also asserted against the M4.1
waterfall); the planner emits no value/entity; expensive-modality gating to high-tier/high-weight
profiling modes (and M4.3 honors the SKIP); the budget halt; the planning-LLM swap leaving the
contract + allowed-set guarantee unchanged; the deterministic (no-gateway) plan. A test pack +
test manifests give full control over tiers/modalities/weights.
"""

from __future__ import annotations

from decimal import Decimal

import pytest
from sqlalchemy.ext.asyncio import AsyncConnection

from clue_core import (
    Claim,
    Completion,
    EmbeddingResult,
    Entity,
    EntityScope,
    EntityType,
    ExtractionMethod,
    FieldDef,
    GateDecision,
    ICPCreatedFrom,
    ICPSpec,
    Message,
    Modality,
    PassKind,
    ResearchMode,
    SourceManifest,
    account_claim,
    new_entity_id,
    new_run_id,
)
from clue_obs.otel import (
    ATTR_FIELD_KEY,
    ATTR_N_SOURCES,
    SPAN_SOURCE_PLAN,
    collect_spans,
)
from clue_research.adapters import CallableClaimExtractor, run_pipeline
from clue_research.icp import (
    Pack,
    PackSourceSlot,
    SourceWeight,
    WeightedSource,
    create_icp_spec,
    register_pack_catalog,
)
from clue_research.sources import (
    RegistrySourceManifest,
    SourcePlannerConfig,
    bind_resolver,
    plan_sources,
    register_source,
    resolve_field,
)

from .conftest import rollback_conn, run_async

pytestmark = pytest.mark.usefixtures("require_db")

_M2 = ResearchMode.ACCOUNT_PROFILING
_M1 = ResearchMode.ACCOUNT_DISCOVERY
_FIELD = "account.operational_pain"  # an ACCOUNT field (manifests yielding "account" cover it)
_MODEL = "planner-model"


class _ScriptedGateway:
    """A fake LLMGateway returning a fixed completion text (hermetic planner refinement)."""

    def __init__(self, text: str) -> None:
        self._text = text

    def complete(self, *, model: str, messages: list[Message], **opts: object) -> Completion:
        return Completion(model=model, text=self._text)

    def embed(self, *, model: str, inputs: list[str]) -> EmbeddingResult:
        return EmbeddingResult(model=model)


class _Recorder:
    """A resolver double that records call order (for the waterfall tier-discipline check)."""

    tier = 1

    def __init__(self, key: str, claims: list[Claim], order: list[str]) -> None:
        self._key, self._claims, self._order = key, claims, order

    def resolve(self, entity: Entity, field: FieldDef) -> list[Claim]:
        self._order.append(self._key)
        return [c.model_copy(update={"entity_id": entity.entity_id}) for c in self._claims]


async def _manifest(
    conn: AsyncConnection,
    source_key: str,
    *,
    tier: int,
    modality: Modality = Modality.STRUCTURED,
    cost: Decimal = Decimal(1),
) -> None:
    await register_source(
        conn,
        RegistrySourceManifest(
            manifest=SourceManifest(
                source_key=source_key,
                modality=modality,
                entity_scope=EntityScope.ACCOUNT,
                yields=("account",),
                tier=tier,
                cost_cents=cost,
            )
        ),
    )


async def _testpack(conn: AsyncConnection, *weighted: WeightedSource) -> ICPSpec:
    """Register a 'testpack' whose pack-wide profile is ``weighted`` + an ICP enabling it."""
    await register_pack_catalog(
        conn,
        Pack(
            pack_key="testpack",
            namespace="testpack",
            title="Test pack",
            source_profile=(PackSourceSlot(sources=weighted),),
        ),
    )
    return await create_icp_spec(
        conn,
        client_id="acme",
        icp_key="seg1",
        created_from=ICPCreatedFrom.SYNTHESIS,
        enabled_packs=("testpack",),
    )


def _ws(source_key: str, weight: SourceWeight, rank: int) -> WeightedSource:
    return WeightedSource(source_key=source_key, weight=weight, rank=rank)


def _entity() -> Entity:
    return Entity(entity_id=new_entity_id(), entity_type=EntityType.ACCOUNT)


# --- allowed set = profile ∩ registry-capable; the hard LLM guard ------------


def test_plan_keeps_only_registered_capable_sources() -> None:
    async def _run() -> None:
        async with rollback_conn() as conn:
            await _manifest(conn, "reg_src", tier=1)
            spec = await _testpack(
                conn, _ws("reg_src", SourceWeight.HIGH, 1), _ws("ghost_src", SourceWeight.HIGH, 2)
            )
            plan = await plan_sources(conn, spec=spec, entity=_entity(), field=_FIELD, mode=_M2)
            # ghost_src has no manifest → dropped by the intersection; only reg_src is plannable.
            assert [s.source_key for s in plan.ordered_sources] == ["reg_src"]

    run_async(_run())


def test_hard_guard_drops_off_set_llm_source() -> None:
    async def _run() -> None:
        async with rollback_conn() as conn:
            await _manifest(conn, "a", tier=1)
            await _manifest(conn, "b", tier=1)
            spec = await _testpack(
                conn, _ws("a", SourceWeight.HIGH, 1), _ws("b", SourceWeight.HIGH, 2)
            )
            # the model tries to inject 'evil_source' (outside the allowed set) — must be dropped.
            gw = _ScriptedGateway('{"ranking": ["b", "evil_source", "a"], "queries": {}}')
            plan = await plan_sources(
                conn,
                spec=spec,
                entity=_entity(),
                field=_FIELD,
                mode=_M2,
                gateway=gw,
                planner_model=_MODEL,
            )
            planned = {s.source_key for s in plan.ordered_sources}
            assert planned == {"a", "b"}  # never widened beyond the allowed set
            assert "evil_source" not in plan.tier_plan()
            assert plan.dropped_off_set == ("evil_source",)
            # the LLM's preferred order (b before a) is honored within the (single) tier.
            assert plan.tier_plan() == ("b", "a")

    run_async(_run())


# --- never reorders trust tiers (also vs the M4.1 waterfall) -----------------


def test_plan_never_places_tier3_before_tier1() -> None:
    async def _run() -> None:
        async with rollback_conn() as conn:
            await _manifest(conn, "t3src", tier=3)
            await _manifest(conn, "t1src", tier=1)
            # the profile weights the tier-3 source HIGHER than the tier-1 one — the plan must STILL
            # consult tier-1 first (tier trust order is never overridden by weight).
            spec = await _testpack(
                conn, _ws("t3src", SourceWeight.HIGH, 1), _ws("t1src", SourceWeight.LOW, 2)
            )
            plan = await plan_sources(conn, spec=spec, entity=_entity(), field=_FIELD, mode=_M2)
            assert [s.tier for s in plan.ordered_sources] == [1, 3]  # non-decreasing tiers
            assert plan.tier_plan() == ("t1src", "t3src")

            # …and the waterfall, driven over the plan, consults tier-1 before tier-3.
            order: list[str] = []
            bind_resolver("t1src", _Recorder("t1src", [_claim(tier=1, confidence=0.5)], order))
            bind_resolver("t3src", _Recorder("t3src", [_claim(tier=3, confidence=0.9)], order))
            field = FieldDef(
                field_key=_FIELD,
                value_type="str",
                tier_plan=plan.tier_plan(),
                pass_kind=PassKind.DEEP,
            )
            await resolve_field(conn, _entity(), field, mode=_M2, run_id=new_run_id())
            assert order == ["t1src", "t3src"]

    run_async(_run())


# --- the planner emits no value/entity (anti-fabrication) --------------------


def test_planner_ignores_fabricated_value_or_entity_from_llm() -> None:
    async def _run() -> None:
        async with rollback_conn() as conn:
            await _manifest(conn, "a", tier=1)
            spec = await _testpack(conn, _ws("a", SourceWeight.HIGH, 1))
            # a hostile model tries to smuggle a value + a candidate entity — both are ignored; the
            # plan can only carry source_keys + queries.
            gw = _ScriptedGateway(
                '{"ranking": ["a"], "queries": {"a": ["pain points"]}, '
                '"value": "fabricated revenue", "candidate_entity": "FakeCorp Inc"}'
            )
            plan = await plan_sources(
                conn,
                spec=spec,
                entity=_entity(),
                field=_FIELD,
                mode=_M2,
                gateway=gw,
                planner_model=_MODEL,
            )
            assert [s.source_key for s in plan.ordered_sources] == ["a"]
            assert plan.ordered_sources[0].queries == ("pain points",)
            dump = plan.model_dump_json()
            assert "FakeCorp" not in dump and "fabricated revenue" not in dump

    run_async(_run())


# --- expensive-modality gating + M4.3 honoring -------------------------------


def test_expensive_modality_gated_by_tier_and_weight() -> None:
    async def _run() -> None:
        async with rollback_conn() as conn:
            await _manifest(conn, "podcast", tier=3, modality=Modality.AUDIO)
            spec = await _testpack(conn, _ws("podcast", SourceWeight.HIGH, 1))
            high = await plan_sources(
                conn, spec=spec, entity=_entity(), field=_FIELD, mode=_M2, entity_tier="high"
            )
            assert high.ordered_sources[0].gate_decision is GateDecision.RUN
            assert high.tier_plan() == ("podcast",)  # gated open → consulted

            low = await plan_sources(
                conn, spec=spec, entity=_entity(), field=_FIELD, mode=_M2, entity_tier="low"
            )
            assert low.ordered_sources[0].gate_decision is GateDecision.SKIP
            assert low.tier_plan() == ()  # gated off → not consulted

            disc = await plan_sources(
                conn, spec=spec, entity=_entity(), field=_FIELD, mode=_M1, entity_tier="high"
            )
            assert disc.ordered_sources[0].gate_decision is GateDecision.SKIP  # discovery never

    run_async(_run())


def test_m4_3_run_pipeline_honors_the_skip_gate() -> None:
    async def _run() -> None:
        async with rollback_conn() as conn:
            await _manifest(conn, "podcast", tier=3, modality=Modality.AUDIO)
            spec = await _testpack(conn, _ws("podcast", SourceWeight.HIGH, 1))
            entity = _entity()
            plan = await plan_sources(
                conn, spec=spec, entity=entity, field=_FIELD, mode=_M2, entity_tier="low"
            )
            skip = plan.ordered_sources[0].gate_decision
            assert skip is GateDecision.SKIP
            field = FieldDef(
                field_key=_FIELD, value_type="str", tier_plan=("podcast",), pass_kind=PassKind.DEEP
            )
            # M4.3 honors the planner's verdict: a SKIP incurs no fetch/transcription, no claims —
            # even though 'podcast' has no adapter registered (the SKIP short-circuits before it,
            # and before the extractor the caller still declares).
            claims = await run_pipeline(
                conn,
                "podcast",
                "https://example.com/ep1.mp3",
                entity,
                field,
                run_id=new_run_id(),
                research_mode=_M2,
                extractor=CallableClaimExtractor(lambda n, e, f: []),
                gate_decision=skip,
            )
            assert claims == []

    run_async(_run())


# --- budget halt -------------------------------------------------------------


def test_budget_halts_before_the_exceeding_source() -> None:
    async def _run() -> None:
        async with rollback_conn() as conn:
            await _manifest(conn, "a", tier=1, cost=Decimal(5))
            await _manifest(conn, "b", tier=1, cost=Decimal(5))
            spec = await _testpack(
                conn, _ws("a", SourceWeight.HIGH, 1), _ws("b", SourceWeight.HIGH, 2)
            )
            # budget 7: a (cost 5) is planned; b would push spend to 10 > 7 → halt before it.
            plan = await plan_sources(
                conn,
                spec=spec,
                entity=_entity(),
                field=_FIELD,
                mode=_M2,
                budget_envelope=Decimal(7),
            )
            assert [s.source_key for s in plan.ordered_sources] == ["a"]
            assert "halted early" in plan.rationale

    run_async(_run())


# --- swapping the planning LLM leaves the contract + guarantee unchanged ------


def test_swapping_planner_llm_keeps_contract_and_allowed_set() -> None:
    async def _run() -> None:
        async with rollback_conn() as conn:
            await _manifest(conn, "a", tier=1)
            await _manifest(conn, "b", tier=1)
            spec = await _testpack(
                conn, _ws("a", SourceWeight.HIGH, 1), _ws("b", SourceWeight.HIGH, 2)
            )
            gw_a = _ScriptedGateway('{"ranking": ["a", "b"], "queries": {}}')
            gw_b = _ScriptedGateway('{"ranking": ["b", "a"], "queries": {}}')
            plan_a = await plan_sources(
                conn,
                spec=spec,
                entity=_entity(),
                field=_FIELD,
                mode=_M2,
                gateway=gw_a,
                planner_model=_MODEL,
            )
            plan_b = await plan_sources(
                conn,
                spec=spec,
                entity=_entity(),
                field=_FIELD,
                mode=_M2,
                gateway=gw_b,
                planner_model="a-different-model",
            )
            # same allowed-set membership regardless of model; only the within-tier order differs.
            assert set(plan_a.tier_plan()) == set(plan_b.tier_plan()) == {"a", "b"}
            assert plan_a.tier_plan() == ("a", "b") and plan_b.tier_plan() == ("b", "a")

    run_async(_run())


def test_deterministic_plan_without_a_gateway() -> None:
    async def _run() -> None:
        async with rollback_conn() as conn:
            await _manifest(conn, "a", tier=1)
            await _manifest(conn, "b", tier=2)
            spec = await _testpack(
                conn, _ws("a", SourceWeight.HIGH, 1), _ws("b", SourceWeight.MEDIUM, 2)
            )
            plan = await plan_sources(conn, spec=spec, entity=_entity(), field=_FIELD, mode=_M2)
            assert plan.tier_plan() == ("a", "b")  # config (weight then tier) order, no LLM
            assert "config-ordered" in plan.rationale

    run_async(_run())


def test_empty_allowed_set_returns_empty_plan() -> None:
    async def _run() -> None:
        async with rollback_conn() as conn:
            spec = await _testpack(conn, _ws("ghost", SourceWeight.HIGH, 1))  # no manifest
            plan = await plan_sources(conn, spec=spec, entity=_entity(), field=_FIELD, mode=_M2)
            assert plan.ordered_sources == ()
            assert "empty allowed set" in plan.rationale

    run_async(_run())


# --- the allowed set is the floor in BOTH directions: the LLM cannot NARROW it ----


def test_llm_omitting_an_allowed_source_still_plans_it() -> None:
    async def _run() -> None:
        async with rollback_conn() as conn:
            await _manifest(conn, "a", tier=1)
            await _manifest(conn, "b", tier=1)
            spec = await _testpack(
                conn, _ws("a", SourceWeight.HIGH, 1), _ws("b", SourceWeight.HIGH, 2)
            )
            gw = _ScriptedGateway('{"ranking": ["b"], "queries": {}}')  # omits 'a' entirely
            plan = await plan_sources(
                conn,
                spec=spec,
                entity=_entity(),
                field=_FIELD,
                mode=_M2,
                gateway=gw,
                planner_model=_MODEL,
            )
            # the config (allowed set) is the floor: an omitted allowed source is appended, not cut.
            assert set(plan.tier_plan()) == {"a", "b"}
            assert plan.tier_plan() == ("b", "a")  # ranked 'b'; 'a' appended by served position
            assert plan.dropped_off_set == ()  # an omission is not a guard drop

    run_async(_run())


def test_off_set_source_named_via_queries_is_dropped_and_audited() -> None:
    async def _run() -> None:
        async with rollback_conn() as conn:
            await _manifest(conn, "a", tier=1)
            spec = await _testpack(conn, _ws("a", SourceWeight.HIGH, 1))
            # the model names an off-set source only through the queries channel — also guarded.
            gw = _ScriptedGateway(
                '{"ranking": [], "queries": {"shady_blog": ["x"], "a": ["good"]}}'
            )
            plan = await plan_sources(
                conn,
                spec=spec,
                entity=_entity(),
                field=_FIELD,
                mode=_M2,
                gateway=gw,
                planner_model=_MODEL,
            )
            assert "shady_blog" not in {s.source_key for s in plan.ordered_sources}
            assert plan.dropped_off_set == ("shady_blog",)  # audited via the queries channel too
            assert plan.ordered_sources[0].queries == ("good",)  # the in-set query is kept

    run_async(_run())


# --- cost-governance levers: fan-out cap + budget treat a SKIP as free ----------


def test_max_sources_caps_run_sources_not_skips() -> None:
    async def _run() -> None:
        async with rollback_conn() as conn:
            await _manifest(
                conn, "pod", tier=1, modality=Modality.AUDIO
            )  # tier-1 so it sorts first
            await _manifest(conn, "a", tier=1)
            await _manifest(conn, "b", tier=2)
            spec = await _testpack(
                conn,
                _ws("pod", SourceWeight.HIGH, 1),
                _ws("a", SourceWeight.HIGH, 2),
                _ws("b", SourceWeight.HIGH, 3),
            )
            # entity_tier=low ⇒ 'pod' (audio) gates SKIP and must NOT consume a fan-out slot.
            plan = await plan_sources(
                conn,
                spec=spec,
                entity=_entity(),
                field=_FIELD,
                mode=_M2,
                entity_tier="low",
                config=SourcePlannerConfig(max_sources=1),
            )
            assert plan.tier_plan() == ("a",)  # one RUN source under the cap (not zero, not pod)
            gates = {s.source_key: s.gate_decision for s in plan.ordered_sources}
            assert gates["pod"] is GateDecision.SKIP  # surfaced for audit, but free of the cap
            assert "b" not in gates  # the cap stopped after the 1 RUN source

    run_async(_run())


def test_budget_too_small_for_first_source_yields_empty_halted_plan() -> None:
    async def _run() -> None:
        async with rollback_conn() as conn:
            await _manifest(conn, "a", tier=1, cost=Decimal(5))
            spec = await _testpack(conn, _ws("a", SourceWeight.HIGH, 1))
            plan = await plan_sources(
                conn,
                spec=spec,
                entity=_entity(),
                field=_FIELD,
                mode=_M2,
                budget_envelope=Decimal(3),
            )
            assert plan.ordered_sources == ()
            assert "halted early" in plan.rationale  # distinct from the empty-allowed-set plan

    run_async(_run())


def test_skip_source_does_not_consume_budget() -> None:
    async def _run() -> None:
        async with rollback_conn() as conn:
            # an EXPENSIVE (cost 100) audio source that gates SKIP must spend nothing, leaving the
            # envelope for the cheap RUN source after it.
            await _manifest(conn, "pod", tier=1, modality=Modality.AUDIO, cost=Decimal(100))
            await _manifest(conn, "a", tier=1, cost=Decimal(5))
            spec = await _testpack(
                conn, _ws("pod", SourceWeight.HIGH, 1), _ws("a", SourceWeight.HIGH, 2)
            )
            plan = await plan_sources(
                conn,
                spec=spec,
                entity=_entity(),
                field=_FIELD,
                mode=_M2,
                entity_tier="low",
                budget_envelope=Decimal(7),
            )
            assert plan.tier_plan() == ("a",)  # 'a' fits because the SKIP'd 'pod' cost nothing

    run_async(_run())


# --- tier_scope is an inclusive upper bound (excludes the tier-4 placeholders) ----


def test_tier_scope_excludes_higher_tiers() -> None:
    async def _run() -> None:
        async with rollback_conn() as conn:
            await _manifest(conn, "t1", tier=1)
            await _manifest(conn, "t4", tier=4)
            spec = await _testpack(
                conn, _ws("t1", SourceWeight.HIGH, 1), _ws("t4", SourceWeight.HIGH, 2)
            )
            full = await plan_sources(conn, spec=spec, entity=_entity(), field=_FIELD, mode=_M2)
            assert set(full.tier_plan()) == {"t1", "t4"}  # None = every tier
            bounded = await plan_sources(
                conn, spec=spec, entity=_entity(), field=_FIELD, mode=_M2, tier_scope=3
            )
            assert bounded.tier_plan() == ("t1",)  # tiers 1..3 only

    run_async(_run())


# --- observability: the plan emits its span ----------------------------------


def test_plan_emits_source_plan_span() -> None:
    async def _run() -> None:
        async with rollback_conn() as conn:
            await _manifest(conn, "a", tier=1)
            spec = await _testpack(conn, _ws("a", SourceWeight.HIGH, 1))
            with collect_spans() as exporter:
                await plan_sources(conn, spec=spec, entity=_entity(), field=_FIELD, mode=_M2)
            spans = [s for s in exporter.get_finished_spans() if s.name == SPAN_SOURCE_PLAN]
            assert len(spans) == 1
            attrs = spans[0].attributes
            assert attrs is not None
            assert attrs[ATTR_N_SOURCES] == 1
            assert attrs[ATTR_FIELD_KEY] == _FIELD

    run_async(_run())


def _claim(*, tier: int, confidence: float) -> Claim:
    return account_claim(
        entity_id=new_entity_id(),
        field_key=_FIELD,
        value_json="pain",
        source_tier=tier,
        extraction_method=ExtractionMethod.SCRAPE,
        confidence=confidence,
        run_id=new_run_id(),
        research_mode=_M2,
        source_url="https://example.com/x",
        evidence_span="evidence",
    )
