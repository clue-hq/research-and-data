"""M6.1 (ENG-128) — Account Discovery: the acceptance criteria, end to end.

One test per acceptance criterion (plus the grounding invariant, strategy parsing, and query
planning). All pure (no DB): channels are doubles, dedup uses the M2 normalizers, the ICP spec is
in-memory.
"""

from __future__ import annotations

from decimal import Decimal

import pytest

from clue_research.core import new_entity_id, new_run_id
from clue_research.discovery_scoring import (
    LOOKALIKE_CHANNEL,
    CandidateHypothesis,
    CandidateRecord,
    ChannelRegistry,
    DiscoveryConfig,
    DiscoveryStrategy,
    StoppingReason,
    discover,
)
from clue_research.discovery_scoring.discovery.query_planning import plan_queries
from clue_research.discovery_scoring.discovery.strategy import DiscoveryStrategyError

from .conftest import (
    FakeChannel,
    FakeGateway,
    const_channel,
    empty_channel,
    icp_spec,
    record,
    run_async,
)


# --- AC1: parallel queries across channels; every candidate is grounded + channel-tagged ---------
def test_emits_grounded_candidates_across_all_configured_channels() -> None:
    apollo = const_channel("apollo", [record("apollo:1", domain="alpha.com", name="Alpha")])
    exa = const_channel("exa", [record("exa:1", domain="beta.com", name="Beta")])
    registry = ChannelRegistry((apollo, exa))
    spec = icp_spec(
        {"channels": ["apollo", "exa"], "static_queries": {"apollo": ["q"], "exa": ["q"]}}
    )

    result = run_async(discover(spec=spec, run_id=new_run_id(), channels=registry))

    assert {c.matched_channel for c in result.candidates} == {"apollo", "exa"}
    # every candidate is grounded (a source_record_ref/url) and channel-tagged
    for cand in result.candidates:
        assert cand.source_record_ref or cand.source_url
        assert cand.matched_channel
    assert {cy.source_key for cy in result.per_channel_yield} == {"apollo", "exa"}
    assert apollo.calls and exa.calls  # both channels were actually queried


# --- AC2: anti-fabrication — empty channels yield zero candidates even with LLM planning on -------
def test_anti_fabrication_empty_channels_emit_zero_candidates_with_planning_on() -> None:
    registry = ChannelRegistry((empty_channel("apollo"), empty_channel("exa")))
    gateway = FakeGateway(reply="some query\nanother query")
    spec = icp_spec({"channels": ["apollo", "exa"]})
    config = DiscoveryConfig(query_planner_model="test-model")  # planning ON

    result = run_async(
        discover(spec=spec, run_id=new_run_id(), channels=registry, gateway=gateway, config=config)
    )

    assert result.candidate_count == 0  # the LLM planned queries, but no record ⇒ no candidate
    assert gateway.complete_calls > 0  # planning genuinely ran
    assert result.stopping_reason is StoppingReason.EXHAUSTED


# --- AC3: stopping rule — marginal-yield drop vs budget cap, distinguished -----------------------
def test_stops_on_marginal_yield_drop() -> None:
    counter = {"n": 0}

    def responder(_query: object) -> list[CandidateRecord]:
        counter["n"] += 1
        i = counter["n"]
        # rounds 1-3 find new companies; from round 4 the channel only re-returns company #1
        domain = f"co{i}.com" if i <= 3 else "co1.com"
        return [record(f"r{i}", domain=domain)]

    channel = FakeChannel(source_key="c", responder=responder)
    registry = ChannelRegistry((channel,))
    spec = icp_spec(
        {"channels": ["c"], "static_queries": {"c": ["q1", "q2", "q3", "q4", "q5", "q6"]}}
    )
    config = DiscoveryConfig(window_size=2, marginal_yield_threshold=0.5, max_rounds=20)

    result = run_async(discover(spec=spec, run_id=new_run_id(), channels=registry, config=config))

    assert result.stopping_reason is StoppingReason.MARGINAL_YIELD
    assert result.candidate_count == 3  # only the three distinct companies
    # it stopped before consuming all six planned queries (saturation, not exhaustion)
    assert (result.yield_for("c") or 0) and result.yield_for("c").queries_issued < 6  # type: ignore[union-attr]


def test_stops_on_budget_cap_distinct_reason() -> None:
    counter = {"n": 0}

    def responder(_query: object) -> list[CandidateRecord]:
        counter["n"] += 1
        i = counter["n"]
        return [record(f"r{i}", domain=f"co{i}.com", cost_cents=Decimal(5))]

    channel = FakeChannel(source_key="c", responder=responder)
    registry = ChannelRegistry((channel,))
    spec = icp_spec({"channels": ["c"], "static_queries": {"c": ["q1", "q2", "q3", "q4", "q5"]}})
    # yield stays high (every record is new), so only the budget can stop it
    config = DiscoveryConfig(
        window_size=2, marginal_yield_threshold=0.0, discovery_budget_cap_cents=Decimal(10)
    )

    result = run_async(discover(spec=spec, run_id=new_run_id(), channels=registry, config=config))

    assert result.stopping_reason is StoppingReason.BUDGET_CAP
    assert result.total_cost_cents >= Decimal(10)
    assert result.candidate_count == 2  # two rounds × 5c = 10c reaches the cap


# --- AC4: lookalike expansion is tagged with its seed -------------------------------------------
def test_lookalike_expansion_tags_channel_and_seed() -> None:
    seed_a = new_entity_id()
    seed_b = new_entity_id()

    def responder(query: object) -> list[CandidateRecord]:
        seed = query.seed_entity_id  # type: ignore[attr-defined]
        return [record(f"look:{seed}", domain=f"{seed}.com")]

    channel = FakeChannel(source_key=LOOKALIKE_CHANNEL, responder=responder)
    registry = ChannelRegistry((channel,))
    spec = icp_spec(
        {"channels": [LOOKALIKE_CHANNEL], "seed_entity_ids": [str(seed_a), str(seed_b)]}
    )

    result = run_async(discover(spec=spec, run_id=new_run_id(), channels=registry))

    assert result.candidate_count == 2
    assert all(c.matched_channel == LOOKALIKE_CHANNEL for c in result.candidates)
    assert {c.seed_entity_id for c in result.candidates} == {seed_a, seed_b}


# --- AC5: swapping a channel's provider (same source_key) yields an identical contract -----------
def test_provider_swap_yields_identical_candidate_contract() -> None:
    rec = record("org:1", domain="acme.com", name="Acme", signal="series-b")
    spec = icp_spec({"channels": ["apollo"], "static_queries": {"apollo": ["q"]}})

    provider_a = const_channel("apollo", [rec])
    result_a = run_async(
        discover(spec=spec, run_id=new_run_id(), channels=ChannelRegistry((provider_a,)))
    )
    # a *different* provider bound under the same source_key, returning the same-shaped record
    provider_b = const_channel("apollo", [rec])
    result_b = run_async(
        discover(spec=spec, run_id=new_run_id(), channels=ChannelRegistry((provider_b,)))
    )

    (cand_a,) = result_a.candidates
    (cand_b,) = result_b.candidates
    # identical candidate-stream contract regardless of which provider answered
    assert cand_a.model_dump() == cand_b.model_dump()
    assert cand_a.matched_channel == "apollo"


# --- AC6: per-channel yield counters are queryable by (run_id, source_key) -----------------------
def test_per_channel_yield_counters_are_queryable() -> None:
    apollo = const_channel("apollo", [record("a:1", domain="a.com"), record("a:2", domain="b.com")])
    registry = ChannelRegistry((apollo,))
    spec = icp_spec({"channels": ["apollo"], "static_queries": {"apollo": ["q"]}})
    run_id = new_run_id()

    result = run_async(discover(spec=spec, run_id=run_id, channels=registry))

    assert result.run_id == run_id
    cy = result.yield_for("apollo")
    assert cy is not None
    assert cy.queries_issued == 1
    assert cy.records_returned == 2
    assert cy.new_candidates == 2
    assert result.yield_for("nonexistent") is None


# --- dedup: the same company found via two channels is admitted once -----------------------------
def test_dedup_collapses_same_company_across_channels() -> None:
    apollo = const_channel("apollo", [record("apollo:x", domain="same.com", name="Same Inc")])
    exa = const_channel("exa", [record("exa:y", domain="https://www.same.com", name="Same Inc")])
    registry = ChannelRegistry((apollo, exa))
    spec = icp_spec(
        {"channels": ["apollo", "exa"], "static_queries": {"apollo": ["q"], "exa": ["q"]}}
    )

    result = run_async(discover(spec=spec, run_id=new_run_id(), channels=registry))

    assert result.candidate_count == 1  # collapsed by registrable domain (same.com)
    # apollo (queried first) wins the new candidate; exa sees it as a duplicate
    assert result.yield_for("apollo").new_candidates == 1  # type: ignore[union-attr]
    assert result.yield_for("exa").new_candidates == 0  # type: ignore[union-attr]


# --- a channel named in the strategy but not bound is skipped (no error) -------------------------
def test_unbound_channel_is_skipped() -> None:
    apollo = const_channel("apollo", [record("a:1", domain="a.com")])
    registry = ChannelRegistry((apollo,))  # "ghost" is named below but not bound
    spec = icp_spec(
        {"channels": ["apollo", "ghost"], "static_queries": {"apollo": ["q"], "ghost": ["q"]}}
    )

    result = run_async(discover(spec=spec, run_id=new_run_id(), channels=registry))

    assert {cy.source_key for cy in result.per_channel_yield} == {"apollo"}
    assert result.candidate_count == 1


def test_empty_strategy_finds_nothing() -> None:
    result = run_async(discover(spec=icp_spec({}), run_id=new_run_id(), channels=ChannelRegistry()))
    assert result.candidate_count == 0
    assert result.per_channel_yield == ()
    assert result.stopping_reason is StoppingReason.EXHAUSTED


# --- the grounding invariant is structural (cannot construct an ungrounded candidate) -----------
def test_candidate_record_requires_grounding() -> None:
    record("ok", domain="x.com")  # grounded → fine
    with pytest.raises(ValueError, match="source_record_ref or source_url"):
        CandidateRecord(matched_signal="match")  # neither ref nor url


def test_candidate_hypothesis_requires_grounding() -> None:
    with pytest.raises(ValueError, match="source_record_ref or source_url"):
        CandidateHypothesis(matched_channel="apollo")  # neither ref nor url


# --- strategy parsing (M6's interpretation of the opaque slot) ----------------------------------
def test_strategy_parses_slot_and_overrides() -> None:
    seed = new_entity_id()
    strategy = DiscoveryStrategy.from_slot(
        {
            "channels": ["apollo", "exa"],
            "icp_filters": {"industry": "saas", "size_band": "50-200"},
            "seed_entity_ids": [str(seed)],
            "static_queries": {"apollo": ["a", "b"]},
            "marginal_yield_threshold": 0.2,
            "discovery_budget_cap_cents": 250,
            "window_size": 5,
        }
    )
    assert strategy.channels == ("apollo", "exa")
    assert strategy.icp_filters["industry"] == "saas"
    assert strategy.seed_entity_ids == (seed,)
    assert strategy.static_queries["apollo"] == ("a", "b")
    config = strategy.resolve_config(DiscoveryConfig())
    assert config.marginal_yield_threshold == 0.2
    assert config.discovery_budget_cap_cents == Decimal(250)
    assert config.window_size == 5


def test_strategy_rejects_malformed_seed() -> None:
    with pytest.raises(DiscoveryStrategyError, match="not a valid UUID"):
        DiscoveryStrategy.from_slot({"seed_entity_ids": ["not-a-uuid"]})


# --- query planning: static-only without a gateway; widened (queries only) with one --------------
def test_query_planning_is_static_without_a_gateway() -> None:
    strategy = DiscoveryStrategy(static_queries={"apollo": ("seed-q",)})
    planned = plan_queries(
        channel="apollo", strategy=strategy, config=DiscoveryConfig(), gateway=None
    )
    assert planned == ("seed-q",)


def test_query_planning_widens_with_a_gateway_but_keeps_static_first() -> None:
    strategy = DiscoveryStrategy(static_queries={"apollo": ("seed-q",)})
    config = DiscoveryConfig(query_planner_model="test-model")
    gateway = FakeGateway(reply="extra one\nextra two\nseed-q")  # 'seed-q' dup is dropped
    planned = plan_queries(channel="apollo", strategy=strategy, config=config, gateway=gateway)
    assert planned[0] == "seed-q"
    assert "extra one" in planned and "extra two" in planned
    assert planned.count("seed-q") == 1


def test_strategy_rejects_out_of_range_knobs() -> None:
    with pytest.raises(DiscoveryStrategyError, match="window_size"):
        DiscoveryStrategy.from_slot({"window_size": 0})
    with pytest.raises(DiscoveryStrategyError, match="per_query_limit"):
        DiscoveryStrategy.from_slot({"per_query_limit": -1})
    with pytest.raises(DiscoveryStrategyError, match="marginal_yield_threshold"):
        DiscoveryStrategy.from_slot({"marginal_yield_threshold": 1.5})
    # bool must not leak through as an int (True is not a valid window_size of 1)
    with pytest.raises(DiscoveryStrategyError, match="window_size"):
        DiscoveryStrategy.from_slot({"window_size": True})


# --- review-hardening: fault isolation, hard budget cap, zero-seed lookalike, honest round cap ----
def test_channel_fault_is_isolated_and_does_not_abort_the_run() -> None:
    def boom(_query: object) -> list[CandidateRecord]:
        raise RuntimeError("provider down")

    flaky = FakeChannel(source_key="flaky", responder=boom)
    apollo = const_channel("apollo", [record("a:1", domain="alpha.com")])
    registry = ChannelRegistry((flaky, apollo))
    spec = icp_spec(
        {"channels": ["flaky", "apollo"], "static_queries": {"flaky": ["q"], "apollo": ["q"]}}
    )

    result = run_async(discover(spec=spec, run_id=new_run_id(), channels=registry))

    # a raising channel is isolated (its error is counted), the healthy channel's candidate survives
    assert result.candidate_count == 1
    assert result.yield_for("apollo").new_candidates == 1  # type: ignore[union-attr]
    assert result.yield_for("flaky").errors == 1  # type: ignore[union-attr]
    assert result.yield_for("flaky").new_candidates == 0  # type: ignore[union-attr]


def test_budget_cap_is_hard_no_single_round_overshoot() -> None:
    # one channel returns 100 records (1c each) in a single round; the cap is 10c
    flood = const_channel(
        "flood", [record(f"r{i}", domain=f"co{i}.com", cost_cents=Decimal(1)) for i in range(100)]
    )
    registry = ChannelRegistry((flood,))
    spec = icp_spec({"channels": ["flood"], "static_queries": {"flood": ["q"]}})
    config = DiscoveryConfig(discovery_budget_cap_cents=Decimal(10), marginal_yield_threshold=0.0)

    result = run_async(discover(spec=spec, run_id=new_run_id(), channels=registry, config=config))

    assert result.stopping_reason is StoppingReason.BUDGET_CAP
    assert result.total_cost_cents == Decimal(10)  # hard cap — no 10x in-round overshoot
    assert result.candidate_count == 10


def test_zero_seed_lookalike_finds_nothing() -> None:
    channel = FakeChannel(
        source_key=LOOKALIKE_CHANNEL, responder=lambda _q: [record("x", domain="x.com")]
    )
    spec = icp_spec({"channels": [LOOKALIKE_CHANNEL]})  # no seed_entity_ids
    result = run_async(
        discover(spec=spec, run_id=new_run_id(), channels=ChannelRegistry((channel,)))
    )
    assert result.candidate_count == 0
    assert result.stopping_reason is StoppingReason.EXHAUSTED
    assert channel.calls == []  # a lookalike channel with no seeds is never called


def test_round_cap_backstop_reports_honestly() -> None:
    counter = {"n": 0}

    def responder(_query: object) -> list[CandidateRecord]:
        counter["n"] += 1
        return [
            record(f"r{counter['n']}", domain=f"co{counter['n']}.com")
        ]  # always new (high yield)

    channel = FakeChannel(source_key="c", responder=responder)
    spec = icp_spec({"channels": ["c"], "static_queries": {"c": ["q1", "q2", "q3"]}})
    config = DiscoveryConfig(max_rounds=1, marginal_yield_threshold=0.0)  # backstop after one round

    result = run_async(
        discover(
            spec=spec, run_id=new_run_id(), channels=ChannelRegistry((channel,)), config=config
        )
    )

    # work remained (q2, q3) when the backstop fired → an honest ROUND_CAP, never a false EXHAUSTED
    assert result.stopping_reason is StoppingReason.ROUND_CAP
    assert result.candidate_count == 1
