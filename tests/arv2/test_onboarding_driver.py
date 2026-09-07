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
from clue_api.arv2.calls import CallCost
from clue_api.arv2.exa_client import ExaAgentRun, ExaDeepResult
from clue_api.arv2.onboarding_driver import (
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
        del system_prompt, query, output_schema
        with self.guard:
            self.threads.add(threading.get_ident())
            self.calls.append(label)
        return self.deep_answer


@dataclass
class FakeStore:
    """Records every transition the driver makes, in order."""

    events: list[tuple[Any, ...]] = field(default_factory=list)
    documents: dict[Any, Any] = field(default_factory=dict)

    async def create_run(self, conn: Any, **kw: Any) -> None:
        self.events.append(("create_run", kw))

    async def mark_run_running(self, conn: Any, *, run_id: Any) -> None:
        self.events.append(("run_running", run_id))

    async def start_step(self, conn: Any, **kw: Any) -> None:
        self.events.append(("start_step", kw["kind"], kw.get("subject_ref")))

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

    async def finish_run(self, conn: Any, *, run_id: Any) -> str:
        self.events.append(("finish_run", run_id))
        return "completed"

    async def fail_run(self, conn: Any, *, run_id: Any) -> None:
        self.events.append(("fail_run", run_id))


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


def _handler(
    exa: FakeExa,
    store: FakeStore,
    *,
    synthesis: Any = None,
    links: Any = None,
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
    )


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

    outcome = SynthesisOutcome(
        status="completed", failure_code=None, failure_message=None, cost_usd=Decimal("0.2")
    )

    class Synth:
        async def launch(self, **kw: Any) -> SynthesisOutcome:
            store.events.append(("synthesis", kw["step_id"] is not None))
            return outcome

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
    assert kinds[-1] == "product_research"  # background fan-out after synthesis started
    assert seen["products"][0].name == "MagicFlow"
    assert ("finish_run", run_id) in store.events
    publishes = [event for event in store.events if event[0] == "publish"]
    assert len(publishes) == 4  # overview, catalog, reviews, one product


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
