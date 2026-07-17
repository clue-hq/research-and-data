"""Graph-level tests for the bounded recursion knob (M7.2) — LangGraph in-memory saver, no DB.

These drive the per-account graph with stub workers that *request* facet sub-workers and assert the
runtime grants/denies them through the single ``SpawnGuard`` chokepoint: depth-0 tiers spawn
nothing, top tier spawns up to the per-aspect cap and no further, over-cap requests are hard-limited
with a ``cap_hit``, non-eligible aspects are denied, the dial is config-driven, budget can deny an
allowed spawn, and facet sub-workers return references only.
"""

from __future__ import annotations

from decimal import Decimal

from langgraph.checkpoint.memory import InMemorySaver

from clue_config import RecursionPolicy, TierRecursionCaps
from clue_core import new_campaign_run_id, new_entity_id
from clue_obs.otel import collect_spans
from clue_research.durable import (
    AccountResearchGraph,
    AccountRunStatus,
    AspectPlan,
    ResearchPlan,
    WorkerRegistry,
)
from tests.db.conftest import run_async
from tests.durable.conftest import FakeAccountRunStore, StubAspectWorker


def _graph(
    store: FakeAccountRunStore,
    *workers: StubAspectWorker,
    policy: RecursionPolicy | None = None,
) -> AccountResearchGraph:
    registry = WorkerRegistry()
    for worker in workers:
        registry.register(worker)
    return AccountResearchGraph(store=store, workers=registry, recursion_policy=policy)


def _resonance_plan(*, budget_envelope_cents: Decimal | None = None) -> ResearchPlan:
    return ResearchPlan(
        tier="top",
        aspects=(
            AspectPlan(
                aspect="account.resonance",
                field_keys=("account.resonance.culture",),
                budget_envelope_cents=budget_envelope_cents,
            ),
        ),
    )


def _run(graph: AccountResearchGraph, *, tier: str) -> object:
    async def _go() -> object:
        return await graph.run(
            new_entity_id(),
            tier=tier,
            campaign_run_id=new_campaign_run_id(),
            checkpointer=InMemorySaver(),
        )

    return run_async(_go())


def test_low_tier_depth_zero_spawns_no_facets() -> None:
    # default policy: an unlisted tier ("low") has max_depth=0 → no facet ever spawns, even though
    # the (eligible) aspect worker asks for one.
    store = FakeAccountRunStore(ResearchPlan(tier="low", aspects=_resonance_plan().aspects))
    aspect = StubAspectWorker(
        "account.resonance", facet_requests=[{"aspect": "account.resonance.facet"}]
    )
    facet = StubAspectWorker("account.resonance.facet")
    graph = _graph(store, aspect, facet)

    with collect_spans() as spans:
        result = _run(graph, tier="low")
    assert result.status is AccountRunStatus.DONE
    assert facet.calls == 0  # hard limit: no facet spawned at depth-0 tier
    names = [s.name for s in spans.get_finished_spans()]
    assert "account.graph.cap_hit" in names  # the denial was logged


def test_top_tier_spawns_facets_up_to_cap_and_no_further() -> None:
    # top tier: max_depth=2, max_facet_workers_per_aspect=2. The aspect requests FOUR facets → only
    # two spawn; the other two are cap_hit (count_exceeded) — the hard limit holds when the model
    # over-asks.
    policy = RecursionPolicy(
        by_tier={
            "top": TierRecursionCaps(
                max_depth=2, max_aspect_workers=8, max_facet_workers_per_aspect=2
            )
        }
    )
    store = FakeAccountRunStore(_resonance_plan())
    aspect = StubAspectWorker(
        "account.resonance",
        n_claims=1,
        facet_requests=[{"aspect": "account.resonance.facet"} for _ in range(4)],
    )
    facet = StubAspectWorker("account.resonance.facet", n_claims=1)  # leaf: requests no facets
    graph = _graph(store, aspect, facet, policy=policy)

    with collect_spans() as spans:
        result = _run(graph, tier="top")
    assert result.status is AccountRunStatus.DONE
    assert facet.calls == 2  # exactly the per-aspect cap, never four
    # references include both the aspect's and the two facets' claims (refs only).
    assert len(result.references_index["account.resonance"]) == 1
    assert len(result.references_index["account.resonance.facet"]) == 2
    cap_hits = [s for s in spans.get_finished_spans() if s.name == "account.graph.cap_hit"]
    assert len(cap_hits) == 2  # the two over-cap requests
    assert all(s.attributes.get("cap_hit_reason") == "count_exceeded" for s in cap_hits)


def test_non_eligible_aspect_is_denied_recursion() -> None:
    # "account" is not a recursion-eligible class → its facet requests are all denied
    # (not_eligible), even on top tier.
    store = FakeAccountRunStore(
        ResearchPlan(
            tier="top",
            aspects=(AspectPlan(aspect="account", field_keys=("account.recent_funding",)),),
        )
    )
    aspect = StubAspectWorker("account", facet_requests=[{"aspect": "account.facet"}])
    facet = StubAspectWorker("account.facet")
    graph = _graph(store, aspect, facet)

    with collect_spans() as spans:
        result = _run(graph, tier="top")
    assert result.status is AccountRunStatus.DONE
    assert facet.calls == 0
    cap_hits = [s for s in spans.get_finished_spans() if s.name == "account.graph.cap_hit"]
    assert any(s.attributes.get("cap_hit_reason") == "not_eligible" for s in cap_hits)


def test_two_level_dive_reaches_max_depth_then_stops() -> None:
    # A self-requesting eligible worker recurses until the depth cap terminates it. top tier
    # max_depth=2 → it runs at depths 0, 1, 2 (three invocations), depth-3 spawn denied.
    policy = RecursionPolicy(
        by_tier={
            "top": TierRecursionCaps(
                max_depth=2, max_aspect_workers=8, max_facet_workers_per_aspect=1
            )
        }
    )
    store = FakeAccountRunStore(_resonance_plan())
    worker = StubAspectWorker("account.resonance", facet_requests=[{"aspect": "account.resonance"}])
    graph = _graph(store, worker, policy=policy)

    result = _run(graph, tier="top")
    assert result.status is AccountRunStatus.DONE
    assert worker.calls == 3
    assert worker.seen_depths == [0, 1, 2]  # bounded two-level dive, no deeper


def test_recursion_is_config_driven_no_code_change() -> None:
    # The same low-tier run spawns NO facets under the default policy but DOES once an overlay
    # raises "low" to depth 1 — proving the dial is data, not code.
    store_off = FakeAccountRunStore(ResearchPlan(tier="low", aspects=_resonance_plan().aspects))
    aspect_off = StubAspectWorker(
        "account.resonance", facet_requests=[{"aspect": "account.resonance.facet"}]
    )
    facet_off = StubAspectWorker("account.resonance.facet")
    assert _run(_graph(store_off, aspect_off, facet_off), tier="low").status
    assert facet_off.calls == 0

    tuned = RecursionPolicy(
        by_tier={
            "low": TierRecursionCaps(
                max_depth=1, max_aspect_workers=4, max_facet_workers_per_aspect=2
            )
        }
    )
    store_on = FakeAccountRunStore(ResearchPlan(tier="low", aspects=_resonance_plan().aspects))
    aspect_on = StubAspectWorker(
        "account.resonance", facet_requests=[{"aspect": "account.resonance.facet"}]
    )
    facet_on = StubAspectWorker("account.resonance.facet")
    _run(_graph(store_on, aspect_on, facet_on, policy=tuned), tier="low")
    assert facet_on.calls == 1  # the config bump alone enabled one level of recursion


def test_budget_denies_an_otherwise_allowed_spawn_gracefully() -> None:
    # depth + count caps allow the facet, but the per-account budget envelope is exhausted (0) →
    # denied for budget; the run still completes (the aspect is just not deepened).
    store = FakeAccountRunStore(_resonance_plan(budget_envelope_cents=Decimal(0)))
    aspect = StubAspectWorker(
        "account.resonance", facet_requests=[{"aspect": "account.resonance.facet"}]
    )
    facet = StubAspectWorker("account.resonance.facet")
    graph = _graph(store, aspect, facet)

    with collect_spans() as spans:
        result = _run(graph, tier="top")
    assert result.status is AccountRunStatus.DONE
    assert facet.calls == 0
    cap_hits = [s for s in spans.get_finished_spans() if s.name == "account.graph.cap_hit"]
    assert any(s.attributes.get("cap_hit_reason") == "budget" for s in cap_hits)


def test_worker_sees_soft_recursion_caps_in_context_params() -> None:
    # The dual-enforcement *soft* half: the runtime hands the worker its recursion budget via
    # ctx.params so M8 can put it in the prompt. (The SpawnGuard is the hard half.)
    policy = RecursionPolicy(
        by_tier={
            "top": TierRecursionCaps(
                max_depth=2, max_aspect_workers=8, max_facet_workers_per_aspect=3
            )
        }
    )
    store = FakeAccountRunStore(_resonance_plan())
    worker = StubAspectWorker("account.resonance", n_claims=1)
    graph = _graph(store, worker, policy=policy)

    _run(graph, tier="top")
    recursion = worker.seen_params[0]["recursion"]
    assert recursion["max_depth"] == 2
    assert recursion["max_facet_workers_per_aspect"] == 3
    assert recursion["eligible"] is True
    assert recursion["current_depth"] == 0


def test_max_aspect_workers_caps_level_one_breadth() -> None:
    # The level-1 breadth cap: with max_aspect_workers=1, a plan with two aspects spawns only one;
    # the other is dropped at dispatch with a depth-0 cap_hit (the hard limit on aspect breadth).
    policy = RecursionPolicy(
        by_tier={
            "top": TierRecursionCaps(
                max_depth=0, max_aspect_workers=1, max_facet_workers_per_aspect=0
            )
        }
    )
    store = FakeAccountRunStore(
        ResearchPlan(
            tier="top",
            aspects=(
                AspectPlan(aspect="account", field_keys=("account.recent_funding",)),
                AspectPlan(aspect="contact", field_keys=("contact.role_on_committee",)),
            ),
        )
    )
    a = StubAspectWorker("account")
    b = StubAspectWorker("contact")
    graph = _graph(store, a, b, policy=policy)

    with collect_spans() as spans:
        result = _run(graph, tier="top")
    assert result.status is AccountRunStatus.DONE
    assert a.calls + b.calls == 1  # only one aspect worker spawned, never both
    cap_hits = [s for s in spans.get_finished_spans() if s.name == "account.graph.cap_hit"]
    # (custom span attrs are stringified by the obs redaction, so depth reads back as "0".)
    assert any(
        s.attributes.get("cap_hit_reason") == "count_exceeded"
        and int(s.attributes.get("depth", -1)) == 0
        for s in cap_hits
    )


def test_budget_envelope_is_shared_across_sibling_facet_grants() -> None:
    # The per-aspect envelope is *reserved* as facets are granted: a 100-cent budget with two facets
    # estimated at 60 each grants only the first (100 ≥ 60 → remaining 40); the second is denied for
    # budget (40 < 60). Without the per-grant decrement, both would pass against the full 100.
    policy = RecursionPolicy(
        by_tier={
            "top": TierRecursionCaps(
                max_depth=2, max_aspect_workers=8, max_facet_workers_per_aspect=4
            )
        }
    )
    store = FakeAccountRunStore(_resonance_plan(budget_envelope_cents=Decimal(100)))
    aspect = StubAspectWorker(
        "account.resonance",
        facet_requests=[
            {"aspect": "account.resonance.facet", "estimated_cost_cents": "60"},
            {"aspect": "account.resonance.facet", "estimated_cost_cents": "60"},
        ],
    )
    facet = StubAspectWorker("account.resonance.facet")
    graph = _graph(store, aspect, facet, policy=policy)

    with collect_spans() as spans:
        result = _run(graph, tier="top")
    assert result.status is AccountRunStatus.DONE
    assert facet.calls == 1  # only the first facet fit the shared envelope
    cap_hits = [s for s in spans.get_finished_spans() if s.name == "account.graph.cap_hit"]
    assert any(s.attributes.get("cap_hit_reason") == "budget" for s in cap_hits)


def test_malformed_facet_estimate_cannot_inflate_or_crash_budget() -> None:
    # Regression for the drifted loose cost coercion: ``estimated_cost_cents`` is *worker-supplied*
    # (the least-trusted input). A negative estimate used to be subtracted from ``remaining``,
    # *inflating* the envelope (silent per-entity-cap evasion); a NaN used to signal an
    # InvalidOperation in the spawn-budget comparison, crashing the phase. Both now coerce to
    # None (== "no estimate" == free) via the shared ``parse_cost_cents``: the malformed facet is
    # granted at zero cost without moving ``remaining``, so a *real* over-budget follow-up facet is
    # still denied — the per-account cap holds and the run completes.
    for bad in ("-1000", "NaN"):
        policy = RecursionPolicy(
            by_tier={
                "top": TierRecursionCaps(
                    max_depth=2, max_aspect_workers=8, max_facet_workers_per_aspect=4
                )
            }
        )
        store = FakeAccountRunStore(_resonance_plan(budget_envelope_cents=Decimal(100)))
        aspect = StubAspectWorker(
            "account.resonance",
            facet_requests=[
                {"aspect": "account.resonance.facet", "estimated_cost_cents": bad},
                {"aspect": "account.resonance.facet", "estimated_cost_cents": "150"},
            ],
        )
        facet = StubAspectWorker("account.resonance.facet")
        graph = _graph(store, aspect, facet, policy=policy)

        with collect_spans() as spans:
            result = _run(graph, tier="top")
        assert result.status is AccountRunStatus.DONE  # no crash (the NaN case)
        # malformed → free; the real 150-cent facet is still denied (the envelope was not inflated).
        assert facet.calls == 1
        cap_hits = [s for s in spans.get_finished_spans() if s.name == "account.graph.cap_hit"]
        assert any(s.attributes.get("cap_hit_reason") == "budget" for s in cap_hits)
