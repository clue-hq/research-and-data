"""The driver's sequencing, failure law and fan-out, on in-memory doubles.

Client logic, never provider behaviour: the Exa surface, the store and the artifact sink are all
doubled, so what these tests pin is the order the driver moves rows in, what it records when a
provider run comes back failed or empty, that the provider calls leave the event loop, and that
nothing escapes ``handle``.
"""

from __future__ import annotations

import asyncio
import hashlib
import threading
import time
from dataclasses import dataclass, field, replace
from datetime import date
from decimal import Decimal
from typing import Any
from uuid import uuid4

from clue_agents.contracts import ArtifactRef
from clue_api.arv2 import onboarding_driver
from clue_api.arv2.calls import CallCost
from clue_api.arv2.exa_client import ExaAgentRun, ExaDeepResult
from clue_api.arv2.onboarding_driver import (
    IcpRef,
    IcpSynthesisOutcome,
    OnboardingRunWorkHandler,
    SynthesisOutcome,
    _merge_lineups,
    onboarding_work_id,
)
from clue_api.arv2.onboarding_lineage import ProductLink
from clue_config import Settings
from clue_fleet import FleetTaskKind
from clue_fleet.lease import LeaseGeneration
from clue_fleet.work_worker import WorkContext


def _cost(usd: str, op: str = "agent-poll") -> CallCost:
    return CallCost(
        cost_usd=Decimal(usd),
        credits=Decimal(0),
        media_seconds=0,
        cost_source="metered",
        provider="exa",
        operation=op,
        raw_ref=f"raw/{op}",
        ledger_row_id=f"row-{op}",
    )


def _agent(structured: object, *, usd: str = "0.1", status: str = "completed") -> ExaAgentRun:
    completed = status == "completed"
    return ExaAgentRun(
        run_id=f"agent_run_{uuid4().hex[:6]}",
        status=status,
        stop_reason="schema_satisfied" if completed else None,
        output_text="ok" if completed else None,
        structured=structured if completed else None,
        grounding=[],
        usage={"searches": 3},
        cost_usd=Decimal(usd),
        error_code=None if completed else "provider_failed",
        error_message=None if completed else "boom",
        polls=1,
        raw_refs=("raw/a",),
        ledger_row_ids=("row-a",),
        costs=(_cost(usd),),
        cost=_cost(usd),
    )


def _deep(products: list[dict[str, Any]]) -> ExaDeepResult:
    return ExaDeepResult(
        output_text="{}",
        output_object={"coverage_note": "own + open", "products": products},
        report_text=None,
        grounding=[],
        results=(),
        status=200,
        cost_usd=Decimal("0.015"),
        request_id="req",
        raw_ref="raw/d",
        ledger_row_id="row-d",
        cost=_cost("0.015", "deep-reasoning"),
        retried=False,
    )


OVERVIEW: dict[str, Any] = {
    "facts": {"legal_name": "Insight Health AI, Inc."},
    "sections": dict.fromkeys(
        (
            "origin_story",
            "business_model",
            "positioning",
            "market_position",
            "customer_segments",
            "leadership",
            "recent_context",
        ),
        "text",
    ),
    "competitors": [],
    "named_customers": [],
    "not_found": [],
}
REVIEWS: dict[str, Any] = {
    "summary": "thin",
    "themes_positive": [],
    "themes_negative": [],
    "reviews": [],
    "case_studies": [],
    "not_found": ["no G2 page"],
}
PRODUCT: dict[str, Any] = {
    "overview": "x",
    "capabilities": ["a"],
    "use_cases": [],
    "integrations": [],
    "pricing": None,
    "differentiators": [],
    "competitors": [],
    "customer_evidence": [],
    "who_it_is_for": None,
    "not_found": [],
}


@dataclass
class FakeExa:
    """Answers by label; records the order calls were made in and which thread they ran on."""

    agent_answers: dict[str, ExaAgentRun]
    deep_answer: ExaDeepResult
    calls: list[str] = field(default_factory=list)
    threads: set[int] = field(default_factory=set)
    concurrent: int = 0
    peak: int = 0
    queries: list[str] = field(default_factory=list)
    guard: threading.Lock = field(default_factory=threading.Lock)

    def agent_run(
        self,
        *,
        query: str,
        output_schema: Any,
        effort: str,
        system_prompt: str | None = None,
        label: str = "exa-agent",
        poll_interval_s: float = 4.0,
        timeout_s: float = 900.0,
    ) -> ExaAgentRun:
        del query, output_schema, effort, system_prompt, poll_interval_s, timeout_s
        with self.guard:
            self.threads.add(threading.get_ident())
            self.concurrent += 1
            self.peak = max(self.peak, self.concurrent)
        time.sleep(0.01)
        with self.guard:
            self.calls.append(label)
            self.concurrent -= 1
        return self.agent_answers[label.split(":")[0]]

    def deep_reasoning(
        self,
        *,
        system_prompt: str,
        query: str,
        output_schema: Any,
        label: str = "exa-deep",
        **_: Any,
    ) -> ExaDeepResult:
        del system_prompt, output_schema
        with self.guard:
            self.threads.add(threading.get_ident())
            self.calls.append(label)
            self.queries.append(query)
        return self.deep_answer


@dataclass
class FakeStore:
    """Records every transition the driver makes, in order.

    ``events`` is the ordered transcript. ``opened``/``settled`` are the same facts keyed by
    ``step_id`` so a test can ask *which* step landed *what* — the fan-out opens several steps of
    the same kind, so the ordered transcript alone cannot answer that.
    """

    events: list[tuple[Any, ...]] = field(default_factory=list)
    documents: dict[Any, Any] = field(default_factory=dict)
    opened: dict[Any, tuple[str, Any]] = field(default_factory=dict)
    settled: dict[Any, dict[str, Any]] = field(default_factory=dict)

    async def create_run(self, conn: Any, **kw: Any) -> None:
        self.events.append(("create_run", kw))

    async def mark_run_running(self, conn: Any, *, run_id: Any) -> None:
        self.events.append(("run_running", run_id))

    async def start_step(self, conn: Any, **kw: Any) -> None:
        self.events.append(("start_step", kw["kind"], kw.get("subject_ref")))
        self.opened[kw["step_id"]] = (kw["kind"], kw.get("subject_ref"))

    async def open_document(self, conn: Any, **kw: Any) -> int:
        self.events.append(("open_document", kw["path"]))
        return 1

    async def publish_document(self, conn: Any, **kw: Any) -> None:
        self.events.append(("publish", kw["document_id"]))
        self.documents[kw["document_id"]] = kw

    async def fail_document(self, conn: Any, **kw: Any) -> None:
        self.events.append(("fail_document", kw["status"]))

    async def finish_step(self, conn: Any, **kw: Any) -> None:
        self.events.append(("finish_step", kw["status"], kw.get("failure_code")))
        self.settled[kw["step_id"]] = dict(kw)

    async def finish_run(self, conn: Any, *, run_id: Any) -> str:
        self.events.append(("finish_run", run_id))
        return "completed"

    async def fail_run(self, conn: Any, *, run_id: Any) -> None:
        self.events.append(("fail_run", run_id))

    def landed(self, kind: str, subject: Any = None) -> dict[str, Any]:
        """The terminal kwargs of the one step with this ``(kind, subject_ref)``."""
        matches = [
            self.settled[step_id]
            for step_id, opened in self.opened.items()
            if opened == (kind, subject) and step_id in self.settled
        ]
        assert len(matches) == 1, f"expected exactly one settled {kind}:{subject}, got {matches}"
        return matches[0]


class GapAwareStore(FakeStore):
    """``finish_run`` as the real store computes it: any ``empty``/``failed`` step means gaps.

    Only the tests that assert on the *run's* status need this; the rest keep the flat
    ``completed`` so a step outcome under test never changes an unrelated assertion.
    """

    async def finish_run(self, conn: Any, *, run_id: Any) -> str:
        self.events.append(("finish_run", run_id))
        gaps = any(step["status"] in ("empty", "failed") for step in self.settled.values())
        return "completed_with_gaps" if gaps else "completed"


class FakeArtifacts:
    def __init__(self) -> None:
        self.bodies: list[bytes] = []

    async def persist_body(
        self,
        *,
        workspace_id: str,
        data: bytes,
        media_type: str,
        subject_bindings: Any = (),
        project_bindings: Any = (),
    ) -> ArtifactRef:
        del subject_bindings, project_bindings
        self.bodies.append(data)
        sha = hashlib.sha256(data).hexdigest()
        return ArtifactRef(
            workspace_id=workspace_id,
            artifact_key=f"{workspace_id}/{sha}",
            sha256=sha,
            media_type=media_type,
            byte_count=len(data),
        )


class NullConn:
    async def __aenter__(self) -> NullConn:
        return self

    async def __aexit__(self, *exc: Any) -> None:
        return None


def _context(run_id: Any, ws: str = "ws-drv", brand: str = "brd-drv") -> WorkContext:
    return WorkContext(
        task_id=uuid4(),
        work_id=onboarding_work_id(run_id),
        worker_id="t",
        lease_generation=LeaseGeneration(1),
        payload={
            "run_id": str(run_id),
            "workspace_id": ws,
            "brand_id": brand,
            "company_domain": "insighthealth.ai",
            "company_name": "Insight Health",
        },
        stop_requested=asyncio.Event(),
        lease_lost=asyncio.Event(),
    )


async def _no_products(conn: Any, **kw: Any) -> tuple[ProductLink, ...]:
    del conn, kw
    return ()


async def _no_known_products(conn: Any, brand_id: str) -> tuple[str, ...]:
    """The offline stand-in for the brand's product read: these tests never reach a database, and
    the production default would run SQL on the null connection."""
    del conn, brand_id
    return ()


def _handler(
    exa: FakeExa,
    store: FakeStore,
    *,
    synthesis: Any = None,
    links: Any = None,
    known_products: Any = None,
    settings_overrides: dict[str, Any] | None = None,
) -> OnboardingRunWorkHandler:
    settings = Settings(_env_file=None, **(settings_overrides or {}))
    return OnboardingRunWorkHandler(
        settings=settings,
        conn_factory=NullConn,
        artifacts=FakeArtifacts(),
        exa=lambda *, run_id, step_label: exa,
        client_binder=None,
        synthesis=synthesis,
        clock=lambda: date(2026, 9, 7),
        store=store,
        synchronize_catalog=links or _no_products,
        known_products=known_products or _no_known_products,
    )


def _icp(key: str) -> IcpRef:
    return IcpRef(document_id=uuid4(), icp_key=key, version=1, path=f"audience/icp-{key}.md")


def _all_answers(products: list[dict[str, Any]] | None = None) -> FakeExa:
    """A provider that answers every step of a whole run successfully."""
    return FakeExa(
        {
            "overview": _agent(OVERVIEW),
            "reviews": _agent(REVIEWS),
            "product_research": _agent(PRODUCT),
        },
        _deep(
            products
            if products is not None
            else [
                {
                    "name": "MagicFlow",
                    "short_description": "Orchestration.",
                    "offering_kind": "platform",
                }
            ]
        ),
    )


async def _one_link(conn: Any, **kw: Any) -> tuple[ProductLink, ...]:
    del conn, kw
    return (ProductLink("prd_magicflow", "MagicFlow", "created", 0, uuid4()),)


def test_fast_recon_runs_the_three_calls_in_parallel_off_the_loop_then_syncs_then_synthesis() -> (
    None
):
    exa = FakeExa(
        {
            "overview": _agent(OVERVIEW, usd="0.5"),
            "reviews": _agent(REVIEWS),
            "product_research": _agent(PRODUCT),
        },
        _deep(
            [
                {
                    "name": "MagicFlow",
                    "short_description": "Orchestration.",
                    "offering_kind": "platform",
                }
            ]
        ),
    )
    store = FakeStore()
    seen: dict[str, Any] = {}

    async def fake_sync(conn: Any, **kw: Any) -> tuple[ProductLink, ...]:
        del conn
        seen["products"] = kw["products"]
        return (ProductLink("prd_magicflow", "MagicFlow", "created", 0, uuid4()),)

    icp = _icp("clinical-ops")

    class Synth:
        async def launch_icps(self, **kw: Any) -> IcpSynthesisOutcome:
            store.events.append(("synthesis", kw["step_id"] is not None))
            return IcpSynthesisOutcome(
                status="completed",
                failure_code=None,
                failure_message=None,
                cost_usd=Decimal("0.2"),
                icps=(icp,),
            )

        async def launch_persona(self, **kw: Any) -> SynthesisOutcome:
            return SynthesisOutcome(
                status="completed", failure_code=None, failure_message=None, cost_usd=Decimal("0.1")
            )

    handler = _handler(exa, store, synthesis=Synth(), links=fake_sync)
    run_id = uuid4()

    result = asyncio.run(handler.handle(_context(run_id)))

    assert handler.kind is FleetTaskKind.ONBOARDING_RUN
    assert result.outcome == "completed"
    assert result.references["run_id"] == str(run_id)
    assert exa.peak >= 2, "the fast calls overlap"
    assert threading.get_ident() not in exa.threads, "provider calls never run on the loop thread"
    kinds = [event[1] for event in store.events if event[0] == "start_step"]
    assert kinds[:3] == ["overview", "lineup", "reviews"]
    assert "catalog_sync" in kinds
    assert kinds.index("catalog_sync") > kinds.index("lineup")
    assert kinds.index("synthesis") > kinds.index("catalog_sync")
    # the background fan-out starts after the synthesis (ICP) turn was opened, not before it
    assert kinds.index("product_research") > kinds.index("synthesis")
    assert seen["products"][0].name == "MagicFlow"
    assert ("finish_run", run_id) in store.events
    publishes = [event for event in store.events if event[0] == "publish"]
    # overview, catalog, reviews, one product — the synthesis and persona turns register their own
    # documents inside the launcher, so neither opens or publishes one here.
    assert len(publishes) == 4


def test_a_failed_provider_run_is_recorded_on_the_step_and_the_run_still_finishes() -> None:
    exa = FakeExa(
        {"overview": _agent(None, status="failed"), "reviews": _agent(REVIEWS)}, _deep([])
    )
    store = FakeStore()
    handler = _handler(exa, store)

    result = asyncio.run(handler.handle(_context(uuid4())))

    assert result.outcome == "completed"
    finishes = [event for event in store.events if event[0] == "finish_step"]
    assert ("finish_step", "failed", "provider_failed") in finishes
    assert ("finish_step", "empty", None) in finishes  # the empty lineup
    assert ("finish_step", "completed", None) in finishes  # reviews still landed
    assert ("fail_document", "failed") in store.events
    assert store.events[-1][0] == "finish_run"


def test_without_a_synthesis_launcher_the_synthesis_step_ends_empty_with_a_reason() -> None:
    exa = FakeExa({"overview": _agent(OVERVIEW), "reviews": _agent(REVIEWS)}, _deep([]))
    store = FakeStore()
    handler = _handler(exa, store, synthesis=None)

    asyncio.run(handler.handle(_context(uuid4())))

    assert ("start_step", "synthesis", None) in store.events
    empties = [event for event in store.events if event[0] == "finish_step" and event[1] == "empty"]
    assert empties, "synthesis ends empty when no launcher is composed"


def test_the_background_fan_out_respects_the_concurrency_cap() -> None:
    products = [
        {"name": f"P{index}", "short_description": "d", "offering_kind": "product"}
        for index in range(6)
    ]
    exa = FakeExa(
        {
            "overview": _agent(OVERVIEW),
            "reviews": _agent(REVIEWS),
            "product_research": _agent(PRODUCT),
        },
        _deep(products),
    )
    store = FakeStore()

    async def fake_sync(conn: Any, **kw: Any) -> tuple[ProductLink, ...]:
        del conn, kw
        return tuple(
            ProductLink(f"prd_{index}", f"P{index}", "created", 0, uuid4()) for index in range(6)
        )

    handler = _handler(
        exa, store, links=fake_sync, settings_overrides={"onboarding_max_parallel_runs": 2}
    )
    exa.peak = 0

    asyncio.run(handler.handle(_context(uuid4())))

    product_calls = [call for call in exa.calls if call.startswith("product_research")]
    assert len(product_calls) == 6
    assert exa.peak <= 3  # 2 background + at most one lingering fast call


def test_an_unexpected_exception_is_contained_and_fails_the_run_row() -> None:
    """A defect in the driver's OWN machinery — not a provider outcome — still lands the run.

    A provider raise is a step outcome under the failure law, so the store is what explodes here:
    the run must still come back ``failed``, not requeued, with ``fail_run`` recorded.
    """

    class ExplodingStore(FakeStore):
        async def mark_run_running(self, conn: Any, *, run_id: Any) -> None:
            raise RuntimeError("kaboom")

    exa = FakeExa({}, _deep([]))
    store = ExplodingStore()
    handler = _handler(exa, store)

    result = asyncio.run(handler.handle(_context(uuid4())))

    assert result.outcome == "failed"
    assert result.requeue is False
    assert any(event[0] == "fail_run" for event in store.events)


def test_a_lost_lease_before_work_requeues_without_touching_rows() -> None:
    exa = FakeExa({}, _deep([]))
    store = FakeStore()
    handler = _handler(exa, store)
    context = _context(uuid4())
    context.lease_lost.set()

    result = asyncio.run(handler.handle(context))

    assert result.requeue is True
    assert store.events == []


def test_the_lineup_merge_never_moves_an_own_domain_entry_so_grounding_stays_attributable() -> None:
    """The catalog mapper attaches citations by index, so own positions are load-bearing.

    Two own-domain entries that normalize to the same name must BOTH survive, in place: collapsing
    the second would shift ``Beacon`` from index 2 to index 1 and hand it ``products[1]``'s
    citations. Only new open-web names are appended, after every own index.
    """
    own_grounding = [
        {"field": "products[0].name", "citations": [{"url": "https://own/a", "title": "A"}]},
        {"field": "products[2].name", "citations": [{"url": "https://own/b", "title": "B"}]},
    ]
    own = replace(
        _deep(
            [
                {"name": "MagicFlow", "short_description": "One.", "offering_kind": "platform"},
                {
                    "name": "  magicflow ",
                    "short_description": "Same name.",
                    "offering_kind": "product",
                },
                {"name": "Beacon", "short_description": "Two.", "offering_kind": "product"},
            ]
        ),
        grounding=own_grounding,
    )
    open_web = replace(
        _deep(
            [
                {"name": "beacon", "short_description": "Dup of own.", "offering_kind": "product"},
                {"name": "Cortex", "short_description": "New.", "offering_kind": "product"},
            ]
        ),
        grounding=[{"field": "products[0].name", "citations": [{"url": "https://web/x"}]}],
    )

    merged = _merge_lineups(own, open_web)

    products = merged.output_object["products"]  # type: ignore[index]
    assert [entry["name"] for entry in products] == [
        "MagicFlow",
        "  magicflow ",
        "Beacon",
        "Cortex",
    ]
    assert [entry["short_description"] for entry in products[:3]] == ["One.", "Same name.", "Two."]
    assert merged.grounding == own_grounding, "only the own-domain pass's grounding is carried"


def test_the_lineup_query_names_the_products_already_on_file_on_a_re_run() -> None:
    """Both passes ask the same question, so both must carry the hint: an open-web pass that did
    not know the on-file names is exactly where a near-miss spelling gets invented."""
    exa = FakeExa({"overview": _agent(OVERVIEW), "reviews": _agent(REVIEWS)}, _deep([]))
    handler = _handler(
        exa,
        FakeStore(),
        known_products=lambda conn, brand: asyncio.sleep(0, result=("MagicFlow", "Aura AI Scribe")),
    )

    asyncio.run(handler.handle(_context(uuid4())))

    assert len(exa.queries) == 2
    for query in exa.queries:
        assert "Exhaustive list of products of insighthealth.ai" in query
        assert "Known products already on file for this company" in query
        assert "MagicFlow" in query
        assert "Aura AI Scribe" in query


def test_a_first_run_asks_the_bare_question() -> None:
    """Nothing on file, nothing to name — the hint is absent rather than empty."""
    exa = FakeExa({"overview": _agent(OVERVIEW), "reviews": _agent(REVIEWS)}, _deep([]))
    handler = _handler(exa, FakeStore())

    asyncio.run(handler.handle(_context(uuid4())))

    assert exa.queries == ["Exhaustive list of products of insighthealth.ai"] * 2


def test_an_unreadable_product_list_degrades_to_the_bare_question_instead_of_failing_the_run() -> (
    None
):
    """The hint is an optimization, not an input. Losing it costs a re-run some name drift; letting
    it raise would cost the whole run, because ``handle``'s containment fails the run row."""

    async def exploding(conn: Any, brand_id: str) -> tuple[str, ...]:
        del conn, brand_id
        raise RuntimeError("db down")

    exa = FakeExa({"overview": _agent(OVERVIEW), "reviews": _agent(REVIEWS)}, _deep([]))
    store = FakeStore()
    handler = _handler(exa, store, known_products=exploding)

    result = asyncio.run(handler.handle(_context(uuid4())))

    assert result.outcome == "completed"
    assert exa.queries == ["Exhaustive list of products of insighthealth.ai"] * 2
    assert not [event for event in store.events if event[0] == "fail_run"]


def test_every_registered_icp_gets_its_own_persona_step() -> None:
    """The O4 split on the driver: one ``synthesis`` step for the ICP turn, then one ``persona``
    step per ICP the turn actually registered, keyed by the ICP's key."""
    icps = (_icp("clinical-ops"), _icp("revenue-cycle"))
    seen: list[IcpRef] = []

    class Synth:
        async def launch_icps(self, **kw: Any) -> IcpSynthesisOutcome:
            return IcpSynthesisOutcome("completed", None, None, Decimal("0.2"), icps)

        async def launch_persona(self, *, icp: IcpRef, **kw: Any) -> SynthesisOutcome:
            seen.append(icp)
            return SynthesisOutcome("completed", None, None, Decimal("0.1"))

    store = GapAwareStore()
    handler = _handler(_all_answers(), store, synthesis=Synth(), links=_one_link)

    result = asyncio.run(handler.handle(_context(uuid4())))

    assert result.outcome == "completed"
    assert [ref.icp_key for ref in seen] == ["clinical-ops", "revenue-cycle"]
    assert ("start_step", "persona", "clinical-ops") in store.events
    assert ("start_step", "persona", "revenue-cycle") in store.events
    for key in ("clinical-ops", "revenue-cycle"):
        landed = store.landed("persona", key)
        assert landed["status"] == "completed"
        # each step carries ITS turn's cost; the store sums the steps, the driver sums nothing
        assert landed["cost_usd"] == Decimal("0.1")
    assert store.landed("synthesis")["cost_usd"] == Decimal("0.2")


def test_a_failed_icp_turn_opens_no_persona_steps_and_the_run_still_finishes() -> None:
    """No ICPs, no persona work list — and the run reports the gap rather than failing."""

    class Synth:
        async def launch_icps(self, **kw: Any) -> IcpSynthesisOutcome:
            return IcpSynthesisOutcome(
                "failed", "recipe_refused", "the gate refused", Decimal(0), ()
            )

        async def launch_persona(self, **kw: Any) -> SynthesisOutcome:
            raise AssertionError("no persona turn may run without a registered ICP")

    store = GapAwareStore()
    handler = _handler(_all_answers(), store, synthesis=Synth(), links=_one_link)

    result = asyncio.run(handler.handle(_context(uuid4())))

    assert result.outcome == "completed_with_gaps"
    assert not [event for event in store.events if event[:2] == ("start_step", "persona")]
    landed = store.landed("synthesis")
    assert (landed["status"], landed["failure_code"]) == ("failed", "recipe_refused")


def test_one_failed_persona_leaves_the_icp_step_completed_and_the_run_finishes_with_gaps() -> None:
    """The persona turns are independent: one that fails takes only its own step down, and it
    cannot walk the ICP step (whose profiles ARE registered) back off ``completed``."""
    icps = (_icp("clinical-ops"), _icp("revenue-cycle"))

    class Synth:
        async def launch_icps(self, **kw: Any) -> IcpSynthesisOutcome:
            return IcpSynthesisOutcome("completed", None, None, Decimal("0.2"), icps)

        async def launch_persona(self, *, icp: IcpRef, **kw: Any) -> SynthesisOutcome:
            if icp.icp_key == "revenue-cycle":
                # no code from the launcher: the driver must still write a legal ``failed`` row
                return SynthesisOutcome(
                    "failed", None, "the turn ran out of steps", Decimal("0.02")
                )
            return SynthesisOutcome("completed", None, None, Decimal("0.1"))

    store = GapAwareStore()
    handler = _handler(_all_answers(), store, synthesis=Synth(), links=_one_link)

    result = asyncio.run(handler.handle(_context(uuid4())))

    assert result.outcome == "completed_with_gaps"
    assert store.landed("synthesis")["status"] == "completed"
    assert store.landed("persona", "clinical-ops")["status"] == "completed"
    failed = store.landed("persona", "revenue-cycle")
    assert failed["status"] == "failed"
    assert failed["failure_code"] == "unspecified"
    assert failed["cost_usd"] == Decimal("0.02")


def test_the_persona_and_product_fan_outs_share_the_one_concurrency_cap() -> None:
    """Personas are background work like the product reports, under the SAME semaphore: three
    personas and six products may never put more than ``onboarding_max_parallel_runs`` in flight."""
    guard = threading.Lock()
    live = {"now": 0, "peak": 0, "ran": 0}

    def enter() -> None:
        with guard:
            live["now"] += 1
            live["peak"] = max(live["peak"], live["now"])
            live["ran"] += 1

    def leave() -> None:
        with guard:
            live["now"] -= 1

    class GaugedExa(FakeExa):
        def agent_run(self, **kw: Any) -> ExaAgentRun:
            bounded = str(kw.get("label", "")).startswith("product_research")
            if bounded:
                enter()
            try:
                return super().agent_run(**kw)
            finally:
                if bounded:
                    leave()

    icps = tuple(_icp(f"icp-{index}") for index in range(3))

    class Synth:
        async def launch_icps(self, **kw: Any) -> IcpSynthesisOutcome:
            return IcpSynthesisOutcome("completed", None, None, Decimal(0), icps)

        async def launch_persona(self, **kw: Any) -> SynthesisOutcome:
            enter()
            try:
                await asyncio.sleep(0.02)
            finally:
                leave()
            return SynthesisOutcome("completed", None, None, Decimal(0))

    products = [
        {"name": f"P{index}", "short_description": "d", "offering_kind": "product"}
        for index in range(6)
    ]
    exa = GaugedExa(
        {
            "overview": _agent(OVERVIEW),
            "reviews": _agent(REVIEWS),
            "product_research": _agent(PRODUCT),
        },
        _deep(products),
    )

    async def fake_sync(conn: Any, **kw: Any) -> tuple[ProductLink, ...]:
        del conn, kw
        return tuple(
            ProductLink(f"prd_{index}", f"P{index}", "created", 0, uuid4()) for index in range(6)
        )

    store = FakeStore()
    handler = _handler(
        exa,
        store,
        synthesis=Synth(),
        links=fake_sync,
        settings_overrides={"onboarding_max_parallel_runs": 2},
    )

    asyncio.run(handler.handle(_context(uuid4())))

    assert live["ran"] == 9, "six product reports and three persona turns all ran"
    assert live["peak"] == 2, "both fan-outs are capped by the one semaphore, and they do overlap"


def test_persona_turns_start_the_moment_the_icps_land_not_after_the_products_finish() -> None:
    """Ordering ruling: the persona fan-out is created right after the ICP turn returns, so a
    persona turn overlaps the product reports instead of queueing behind all of them.

    The products block until the first persona turn starts. If the driver waited for the fan-out
    before opening the persona steps, they would time out on that gate and report it.
    """
    gate = threading.Event()
    order: list[str] = []

    class GatedExa(FakeExa):
        def agent_run(self, **kw: Any) -> ExaAgentRun:
            if str(kw.get("label", "")).startswith("product_research"):
                order.append(f"product:{gate.wait(timeout=5.0)}")
            return super().agent_run(**kw)

    class Synth:
        async def launch_icps(self, **kw: Any) -> IcpSynthesisOutcome:
            return IcpSynthesisOutcome("completed", None, None, Decimal(0), (_icp("clinical-ops"),))

        async def launch_persona(self, **kw: Any) -> SynthesisOutcome:
            order.append("persona")
            gate.set()
            return SynthesisOutcome("completed", None, None, Decimal(0))

    products = [
        {"name": f"P{index}", "short_description": "d", "offering_kind": "product"}
        for index in range(4)
    ]
    exa = GatedExa(
        {
            "overview": _agent(OVERVIEW),
            "reviews": _agent(REVIEWS),
            "product_research": _agent(PRODUCT),
        },
        _deep(products),
    )

    async def fake_sync(conn: Any, **kw: Any) -> tuple[ProductLink, ...]:
        del conn, kw
        return tuple(
            ProductLink(f"prd_{index}", f"P{index}", "created", 0, uuid4()) for index in range(4)
        )

    handler = _handler(
        exa,
        FakeStore(),
        synthesis=Synth(),
        links=fake_sync,
        settings_overrides={"onboarding_max_parallel_runs": 8},
    )

    asyncio.run(handler.handle(_context(uuid4())))

    assert order[0] == "persona", "the persona turn started before any product report finished"
    assert order[1:] == ["product:True"] * 4, "no product report waited out the gate"


def test_a_hung_icp_turn_lands_the_step_failed_and_opens_no_persona_steps(
    monkeypatch: Any,
) -> None:
    """Containment for the execution-substrate hang (a refused governed call under the recipe gate
    spins forever inside ``RecipeExecutor.execute``): the turn is bounded by the driver's own hard
    timeout, the step says so, and the run finishes."""
    monkeypatch.setattr(onboarding_driver, "SYNTHESIS_TURN_HARD_TIMEOUT_S", 0.05)

    class Hung:
        async def launch_icps(self, **kw: Any) -> IcpSynthesisOutcome:
            await asyncio.Event().wait()
            raise AssertionError("unreachable")

        async def launch_persona(self, **kw: Any) -> SynthesisOutcome:
            raise AssertionError("no persona turn may run without a registered ICP")

    store = GapAwareStore()
    handler = _handler(_all_answers(), store, synthesis=Hung(), links=_one_link)

    result = asyncio.run(handler.handle(_context(uuid4())))

    assert result.outcome == "completed_with_gaps"
    landed = store.landed("synthesis")
    assert landed["status"] == "failed"
    assert landed["failure_code"] == "turn_hung"
    assert "0.05" in str(landed["failure_message"])
    assert not [event for event in store.events if event[:2] == ("start_step", "persona")]


def test_a_hung_persona_turn_lands_that_step_failed_and_the_run_keeps_going(
    monkeypatch: Any,
) -> None:
    """One hung persona turn takes only its own step down; its sibling and the run still land."""
    monkeypatch.setattr(onboarding_driver, "SYNTHESIS_TURN_HARD_TIMEOUT_S", 0.05)
    icps = (_icp("clinical-ops"), _icp("revenue-cycle"))

    class Hung:
        async def launch_icps(self, **kw: Any) -> IcpSynthesisOutcome:
            return IcpSynthesisOutcome("completed", None, None, Decimal("0.2"), icps)

        async def launch_persona(self, *, icp: IcpRef, **kw: Any) -> SynthesisOutcome:
            if icp.icp_key == "revenue-cycle":
                await asyncio.Event().wait()
            return SynthesisOutcome("completed", None, None, Decimal("0.1"))

    store = GapAwareStore()
    handler = _handler(_all_answers(), store, synthesis=Hung(), links=_one_link)

    result = asyncio.run(handler.handle(_context(uuid4())))

    assert result.outcome == "completed_with_gaps"
    assert store.landed("persona", "clinical-ops")["status"] == "completed"
    hung = store.landed("persona", "revenue-cycle")
    assert (hung["status"], hung["failure_code"]) == ("failed", "turn_hung")
    assert store.landed("synthesis")["status"] == "completed"


def test_two_icps_under_one_key_open_one_persona_step_rather_than_colliding() -> None:
    """A persona step's identity IS ``(run, 'persona', icp_key)`` — the step id and the O1 index.

    Two ICPs registered under the same key would therefore write the same row twice, before the
    per-step containment, failing the whole run. The first one wins and the repeat is dropped.
    """
    first = _icp("clinical-ops")
    repeat = IcpRef(
        document_id=uuid4(), icp_key="clinical-ops", version=2, path="audience/icp-clinical-ops.md"
    )
    seen: list[IcpRef] = []

    class Synth:
        async def launch_icps(self, **kw: Any) -> IcpSynthesisOutcome:
            return IcpSynthesisOutcome("completed", None, None, Decimal(0), (first, repeat))

        async def launch_persona(self, *, icp: IcpRef, **kw: Any) -> SynthesisOutcome:
            seen.append(icp)
            return SynthesisOutcome("completed", None, None, Decimal(0))

    store = GapAwareStore()
    handler = _handler(_all_answers(), store, synthesis=Synth(), links=_one_link)

    result = asyncio.run(handler.handle(_context(uuid4())))

    assert result.outcome == "completed"
    assert seen == [first]
    personas = [event for event in store.events if event[:2] == ("start_step", "persona")]
    assert personas == [("start_step", "persona", "clinical-ops")]
