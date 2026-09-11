"""The R4 discovery driver, offline: the run's steps, the money law, and the receipt it lands.

Nothing here reaches a provider, a model or a database. The store is doubled (it records every
transition in order), the two clients are scripted, and the three reads the driver makes through
other packages — the pinned ICP, the account writer, the ledger drain — are patched at the
driver's own module names. What is asserted is therefore the driver's own contract:

* **every candidate is verified before it is written**, and the verdicts the guards produced are
  what the fit is computed from;
* **no money is spent on a company we already have or already showed** — a duplicate and a
  ``not_chosen_before`` cost the one website answer that identified them and not a single gate;
* **the relaxed pass runs only when the run is short** and it drops the criterion the strict
  search proved was starving it;
* **``handle`` never raises**: a wall-clock overrun and a provider that refuses to sell both land
  the run ``needs_review`` with a named reason, and the ledger is drained either way.
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Callable, Mapping, Sequence
from contextlib import asynccontextmanager
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from types import SimpleNamespace
from typing import Any
from uuid import UUID, uuid4

import pytest

from clue_api.arv2 import discovery_driver as driver
from clue_api.arv2.calls import CallCost
from clue_api.arv2.claim_writer import ClaimDraft, WriteReceipt
from clue_api.arv2.discovery_driver import (
    Arv2DiscoveryWorkHandler,
    build_arv2_discovery_handler,
)
from clue_api.arv2.discovery_launch import Arv2DiscoveryRefused, PinnedIcpDocument
from clue_api.arv2.discovery_store import CandidateRow, DiscoveryRunRow
from clue_api.arv2.errors import ProviderHalted
from clue_api.arv2.exa_client import ExaAnswerResult, ExaCitation
from clue_api.arv2.exa_websets_client import (
    WebsetItem,
    WebsetItemsResult,
    WebsetSearchView,
    WebsetView,
)
from clue_api.arv2.fleet_task import arv2_discovery_work_id
from clue_api.arv2.provider_ledger import DrainReport
from clue_api.arv2.transport import ScriptedTransport
from clue_config import Secrets, Settings
from clue_core import ClaimId, EntityId
from clue_fleet import FleetTaskKind
from clue_fleet.lease import LeaseGeneration
from clue_fleet.work_worker import WorkContext
from clue_research.identity.normalize import registrable_domain

WORKSPACE = "ws-r4-driver"
PROJECT = "prj-r4"
NOW = datetime(2026, 9, 10, 12, 0, tzinfo=UTC)

GEOGRAPHY_RULE = "US-headquartered"
STAGE_RULE = "A named, priced round of Series A or later, announced within the last 36 months"
HIRING_RULE = "Actively hiring now, with at least one open go-to-market role"
INTENT_RULE = "At least one citable, dated buying-intent signal"
BUYER_SENTENCE = (
    "US B2B vertical SaaS companies with a priced round behind them, thirty to three hundred "
    "people, selling to a named list of accounts rather than a funnel."
)

ICP_FRONT: dict[str, Any] = {
    "icp_key": "clue-abm-buyers",
    "version": 1,
    "hard_gates": [
        {"key": "geography", "rule": GEOGRAPHY_RULE, "test": "The HQ city on the company's site."},
        {"key": "stage", "rule": STAGE_RULE, "test": "A dated announcement naming the round."},
        {"key": "hiring", "rule": HIRING_RULE, "test": "A requisition listed today."},
        {"key": "intent", "rule": INTENT_RULE, "test": "A dated, quoted intent signal."},
    ],
    "exclusions": ["Sells to consumers (B2C)"],
}
ICP_BODY = f"# Who we sell to\n\n{BUYER_SENTENCE}\n"

#: The rule of each gate, so a scripted answer can be keyed by the gate it belongs to.
_RULES = {
    "geography": GEOGRAPHY_RULE,
    "stage": STAGE_RULE,
    "hiring": HIRING_RULE,
    "intent": INTENT_RULE,
}


# -- the doubles ---------------------------------------------------------------------------------


def _run_row(**overrides: Any) -> DiscoveryRunRow:
    payload: dict[str, Any] = {
        "run_id": uuid4(),
        "workspace_id": WORKSPACE,
        "project_id": PROJECT,
        "brand_id": "brd-1",
        "project_run_id": uuid4(),
        "icp_artifact_key": f"{WORKSPACE}/icp",
        "icp_artifact_sha256": "d" * 64,
        "icp_key": "clue-abm-buyers",
        "icp_version": 1,
        "requested_by_user_id": "usr-1",
        "request_sha256": "c" * 64,
        "target_count": 20,
        "strict_count": 35,
        "relaxed_enabled": False,
        "criteria_gate_keys": ("geography", "stage"),
        "status": "in_progress",
    }
    payload.update(overrides)
    return DiscoveryRunRow(**payload)


class _Store:
    """Every discovery transition, recorded in order, with no SQL behind it."""

    def __init__(
        self,
        run: DiscoveryRunRow | None,
        *,
        unapproved: frozenset[str] = frozenset(),
        candidates: Sequence[CandidateRow] = (),
    ) -> None:
        self.run = run
        self.unapproved = unapproved
        self.candidates = list(candidates)
        self.events: list[tuple[str, dict[str, Any]]] = []

    async def begin_discovery_run(self, conn: Any, *, run_id: UUID) -> DiscoveryRunRow | None:
        del conn
        self.events.append(("begin_discovery_run", {"run_id": run_id}))
        return self.run

    async def read_discovery_run(self, conn: Any, *, run_id: UUID) -> DiscoveryRunRow | None:
        del conn
        self.events.append(("read_discovery_run", {"run_id": run_id}))
        return self.run

    async def suspend_discovery_run(self, conn: Any, *, run_id: UUID) -> None:
        del conn
        self.events.append(("suspend_discovery_run", {"run_id": run_id}))

    async def record_webset(self, conn: Any, **kwargs: Any) -> None:
        del conn
        self.events.append(("record_webset", kwargs))

    async def record_relaxed_search(self, conn: Any, **kwargs: Any) -> None:
        del conn
        self.events.append(("record_relaxed_search", kwargs))

    async def finish_discovery_run(self, conn: Any, **kwargs: Any) -> None:
        del conn
        self.events.append(("finish_discovery_run", kwargs))

    async def upsert_candidate(self, conn: Any, row: CandidateRow) -> UUID:
        del conn
        self.events.append(("upsert_candidate", {"row": row}))
        self.candidates.append(row)
        return row.candidate_id

    async def record_verdicts(self, conn: Any, **kwargs: Any) -> None:
        del conn
        self.events.append(("record_verdicts", kwargs))

    async def list_candidates(self, conn: Any, *, run_id: UUID) -> tuple[CandidateRow, ...]:
        del conn
        self.events.append(("list_candidates", {"run_id": run_id}))
        return tuple(row for row in self.candidates if row.run_id == run_id)

    async def unapproved_domains(
        self, conn: Any, *, workspace_id: str, project_id: str, before_run_id: UUID
    ) -> frozenset[str]:
        del conn
        self.events.append(
            (
                "unapproved_domains",
                {
                    "workspace_id": workspace_id,
                    "project_id": project_id,
                    "before_run_id": before_run_id,
                },
            )
        )
        return self.unapproved

    def named(self, name: str) -> list[dict[str, Any]]:
        return [payload for event, payload in self.events if event == name]


class _Rows(list):
    """A list that also answers ``first()`` — the two shapes the driver reads off a result."""

    def first(self) -> Any:
        return self[0] if self else None


class _Conn:
    """A connection that answers two queries: the workspace's existing account domains, and
    "is this requester a platform user" (yes for ``usr-*`` ids, no for a service principal)."""

    def __init__(self, domains: Sequence[str] = ()) -> None:
        self.domains = list(domains)
        self.statements: list[str] = []

    async def execute(self, statement: Any, parameters: Any = None) -> Any:
        self.statements.append(str(statement))
        if "platform_user" in str(statement):
            user_id = str((parameters or {}).get("user_id", ""))
            return _Rows([(1,)] if user_id.startswith("usr") else [])
        return _Rows([(domain,) for domain in self.domains])


class _ConnFactory:
    def __init__(self, domains: Sequence[str] = ()) -> None:
        self.conn = _Conn(domains)
        self.opened = 0

    def __call__(self) -> Any:
        return self._open()

    @asynccontextmanager
    async def _open(self) -> AsyncIterator[Any]:
        self.opened += 1
        yield self.conn


class _Writer:
    def __init__(self) -> None:
        self.drafts: list[ClaimDraft] = []

    async def write(self, conn: Any, draft: ClaimDraft) -> WriteReceipt:
        del conn
        self.drafts.append(draft)
        return WriteReceipt(
            claim_id=ClaimId(uuid4()),
            field_key=draft.field_key,
            markers=dict(draft.markers),
            registered_field=False,
        )

    def by_field(self, field_key: str) -> list[ClaimDraft]:
        return [draft for draft in self.drafts if draft.field_key == field_key]


def _search(
    search_id: str = "srch-strict",
    *,
    status: str = "completed",
    count: int = 35,
    found: int = 2,
    analyzed: int = 300,
    recall_estimate: int | None = 180,
    rates: Sequence[tuple[str, float | None]] = (),
) -> WebsetSearchView:
    return WebsetSearchView(
        search_id=search_id,
        status=status,
        count=count,
        found=found,
        analyzed=analyzed,
        recall_estimate=recall_estimate,
        criteria_success_rates=tuple(rates),
    )


#: The success rates the strict search reports: the stage criterion is the one starving it.
STRICT_RATES: tuple[tuple[str, float | None], ...] = (
    (GEOGRAPHY_RULE, 0.81),
    (STAGE_RULE, 0.12),
    (BUYER_SENTENCE, 0.44),
)


def _view(
    *, webset_id: str = "ws-1", status: str = "idle", searches: Sequence[WebsetSearchView] = ()
) -> WebsetView:
    return WebsetView(
        webset_id=webset_id,
        status=status,
        searches=tuple(searches) or (_search(rates=STRICT_RATES),),
        raw_ref="raw-1",
        ledger_row_id="led-1",
    )


def _item(
    name: str,
    url: str,
    *,
    item_id: str | None = None,
    search_id: str = "srch-strict",
    employees: int | None = None,
    revenue_annual: int | None = None,
    logo_url: str | None = None,
) -> WebsetItem:
    return WebsetItem(
        item_id=item_id or f"itm-{name.lower()}",
        search_id=search_id,
        url=url,
        name=name,
        description=f"{name} does things.",
        hq_city="Austin",
        hq_state="TX",
        hq_country_code="US",
        employees=employees,
        revenue_annual=revenue_annual,
        funding_total=None,
        evaluations=(),
        raw={"id": item_id or f"itm-{name.lower()}", "properties": {"url": url, "name": name}},
        logo_url=logo_url,
    )


#: What one all-green webset row costs in these fakes — the real client's ten credits at the
#: default rate. Spelled once so a re-read that prices nothing is visibly worth this much less.
ITEM_COST = Decimal("0.0449")


def _items(*items: WebsetItem) -> WebsetItemsResult:
    """A first read of a fresh webset: every row is all-green, and every row is priced."""
    return WebsetItemsResult(
        items=tuple(items),
        all_green=len(items),
        credits_est=10 * len(items),
        cost_usd=ITEM_COST * len(items),
        raw_refs=("raw-items",),
        ledger_row_ids=("led-items",),
        priced_item_ids=tuple(item.item_id for item in items),
    )


def _repriced(result: WebsetItemsResult, already: frozenset[str]) -> WebsetItemsResult:
    """The scripted read as the real client would return it to a caller that has already paid.

    Every row is still returned; only the rows this run has not been charged for are priced. This
    is the fake's half of the "a webset row is billed once per run" contract — without it the
    offline tests could not tell a second read that costs nothing from one that costs full price.
    """
    fresh = tuple(item_id for item_id in result.priced_item_ids if item_id not in already)
    return replace(
        result,
        all_green=len(fresh),
        credits_est=10 * len(fresh),
        cost_usd=ITEM_COST * len(fresh),
        priced_item_ids=fresh,
    )


class _FakeWebsets:
    """Scripted ``create``/``get``/``items``/``add_search``, each recording what it was asked."""

    def __init__(
        self,
        *,
        create_view: WebsetView | None = None,
        get_views: Sequence[WebsetView] = (),
        items_results: Sequence[WebsetItemsResult] = (),
        add_search_view: WebsetView | None = None,
        create_error: Exception | None = None,
    ) -> None:
        self._create_view = create_view or _view(status="running")
        self._get_views = list(get_views) or [_view()]
        self._items = list(items_results) or [_items()]
        self._add_search_view = add_search_view
        self._create_error = create_error
        self.calls: list[tuple[str, dict[str, Any]]] = []
        #: What each ``items`` read actually priced, in order — the fake's money trail.
        self.returned_items: list[WebsetItemsResult] = []

    def create(self, **kwargs: Any) -> WebsetView:
        self.calls.append(("create", kwargs))
        if self._create_error is not None:
            raise self._create_error
        return self._create_view

    def get(self, webset_id: str) -> WebsetView:
        self.calls.append(("get", {"webset_id": webset_id}))
        view = self._get_views[0]
        if len(self._get_views) > 1:
            self._get_views.pop(0)
        return view

    def items(
        self, webset_id: str, *, priced_item_ids: frozenset[str] = frozenset()
    ) -> WebsetItemsResult:
        self.calls.append(
            ("items", {"webset_id": webset_id, "priced_item_ids": frozenset(priced_item_ids)})
        )
        result = self._items[0]
        if len(self._items) > 1:
            self._items.pop(0)
        repriced = _repriced(result, frozenset(priced_item_ids))
        self.returned_items.append(repriced)
        return repriced

    def add_search(self, webset_id: str, **kwargs: Any) -> WebsetView:
        self.calls.append(("add_search", {"webset_id": webset_id, **kwargs}))
        if self._add_search_view is None:
            raise AssertionError("add_search was not scripted for this test")
        return self._add_search_view

    def named(self, name: str) -> list[dict[str, Any]]:
        return [payload for call, payload in self.calls if call == name]


def _answer(payload: object, *, citations: Sequence[ExaCitation] = ()) -> ExaAnswerResult:
    return ExaAnswerResult(
        answer=payload,
        citations=tuple(citations),
        status=200,
        cost_usd=Decimal("0.005"),
        request_id="req-1",
        raw_ref="raw-answer",
        ledger_row_id="led-answer",
        cost=CallCost(
            cost_usd=Decimal("0.005"),
            credits=None,
            media_seconds=None,
            cost_source="metered",
            ledger_row_id="led-answer",
            raw_ref="raw-answer",
            provider="exa",
            operation="answer",
        ),
    )


class _FakeExa:
    """``answer`` scripted by the *question*: the website ask, or the gate whose rule it quotes."""

    def __init__(self, respond: Callable[[str], ExaAnswerResult]) -> None:
        self._respond = respond
        self.queries: list[str] = []
        self.labels: list[str] = []
        self.models: list[str] = []

    def answer(self, query: str, **kwargs: Any) -> ExaAnswerResult:
        self.queries.append(query)
        self.labels.append(str(kwargs.get("label", "")))
        self.models.append(str(kwargs.get("model", "")))
        return self._respond(query)

    def gate_queries(self) -> list[str]:
        return [query for query in self.queries if "Test to verify:" in query]


class _Clients:
    def __init__(self, exa: _FakeExa, websets: _FakeWebsets) -> None:
        self._exa = exa
        self._websets = websets
        self.callers: list[Any] = []

    def exa(self, caller: Any) -> Any:
        self.callers.append(caller)
        return self._exa

    def websets(self, caller: Any) -> Any:
        self.callers.append(caller)
        return self._websets


def _cite(url: str, text: str) -> ExaCitation:
    return ExaCitation(url=url, title=None, published_date=None, text=text)


def _verdict_payload(
    verdict: str, *, quote: str, url: str, date: str = "2025-03-01"
) -> dict[str, str]:
    return {
        "verdict": verdict,
        "reasoning": "The cited source decides it.",
        "evidence_quote": quote,
        "evidence_url": url,
        "evidence_date": date,
    }


def _company_answers(
    company: str, domain: str, verdicts: Mapping[str, str]
) -> dict[str, ExaAnswerResult]:
    """One company's scripted answers: its website, then one per gate, keyed by the gate's rule."""
    quote = f"{company} closed a Series A and is hiring in the United States."
    citation = _cite(f"https://{domain}/news", quote)
    answers = {
        "website": _answer(
            {"website_domain": domain, "evidence_url": f"https://{domain}/news"},
            citations=(citation,),
        )
    }
    for key, verdict in verdicts.items():
        answers[_RULES[key]] = _answer(
            _verdict_payload(verdict, quote=quote, url=f"https://{domain}/news"),
            citations=(citation,),
        )
    return answers


def _responder(script: Mapping[str, Mapping[str, ExaAnswerResult]]) -> Callable[[str], Any]:
    """Route a question to its answer: which company it names, and which gate it asks."""

    def respond(query: str) -> ExaAnswerResult:
        for company, answers in script.items():
            if company not in query:
                continue
            if "registrable domain" in query:
                return answers["website"]
            for rule, answer in answers.items():
                if rule != "website" and rule in query:
                    return answer
        raise AssertionError(f"no scripted answer for {query!r}")

    return respond


class _DrainRecorder:
    """Stands in for ``drain_provider_calls``: records the stamp and reports a fixed cost."""

    def __init__(self, cost_usd: Decimal = Decimal("0.01")) -> None:
        self.cost_usd = cost_usd
        self.stamps: list[Any] = []

    async def __call__(self, conn: Any, *, raw: Any, ledger: Any, artifacts: Any, stamp: Any):
        del conn, raw, ledger, artifacts
        self.stamps.append(stamp)
        return DrainReport(
            rows=1,
            artifacts=1,
            cost_usd=self.cost_usd,
            credits=Decimal(0),
            media_seconds=0,
        )


class _Accounts:
    """Stands in for ``insert_account_entity``: records the arguments, mints a fresh id.

    ``fail_on`` makes the writer raise for one domain, which is how the per-candidate containment
    is exercised — a strong-key clash on one company is exactly the shape of failure it exists for.
    """

    def __init__(self, fail_on: frozenset[str] = frozenset()) -> None:
        self.created: list[dict[str, Any]] = []
        self.fail_on = fail_on

    async def __call__(self, conn: Any, **kwargs: Any) -> EntityId:
        del conn
        if str(kwargs.get("primary_domain")) in self.fail_on:
            raise RuntimeError("account_entity_primary_domain_key already holds that domain")
        self.created.append(kwargs)
        return EntityId(uuid4())


class _Memberships:
    """Stands in for ``ensure_project_accounts``: records every (project, account) the driver adds.

    Founder ruling 2026-09-11 (supersedes 6′): a discovered account belongs to the project that
    launched the run, so the driver adds each verified candidate's account to ``run.project_id``.
    """

    def __init__(self) -> None:
        self.added: list[tuple[str, str, tuple[str, ...], str]] = []

    async def __call__(self, conn: Any, **kwargs: Any) -> frozenset[Any]:
        del conn
        ids = tuple(str(account_id) for account_id in kwargs["account_entity_ids"])
        self.added.append((kwargs["workspace_id"], kwargs["project_id"], ids, kwargs["added_via"]))
        return frozenset(kwargs["account_entity_ids"])


def _clock(step_s: float = 0.0) -> Callable[[], datetime]:
    """A clock that advances ``step_s`` on every read — 0 for a run that never times out."""
    state = {"reads": 0}

    def now() -> datetime:
        elapsed = state["reads"] * step_s
        state["reads"] += 1
        return NOW + timedelta(seconds=elapsed)

    return now


def _handler(
    store: _Store,
    *,
    exa: _FakeExa,
    websets: _FakeWebsets,
    monkeypatch: pytest.MonkeyPatch,
    domains: Sequence[str] = (),
    settings: Settings | None = None,
    clock: Callable[[], datetime] | None = None,
    account_writes_fail_on: frozenset[str] = frozenset(),
) -> tuple[Arv2DiscoveryWorkHandler, _ConnFactory, _Writer, _DrainRecorder, _Accounts]:
    conn_factory = _ConnFactory(domains)
    writer = _Writer()
    drain = _DrainRecorder()
    accounts = _Accounts(account_writes_fail_on)
    memberships = _Memberships()
    #: Every argument set the driver read its ICP with — the pin it verified against.
    icp_reads: list[dict[str, str]] = []

    async def fake_read_icp_document(
        conn: Any, storage: Any, *, workspace_id: str, artifact_key: str, artifact_sha256: str
    ) -> PinnedIcpDocument:
        del conn, storage, workspace_id
        icp_reads.append({"artifact_key": artifact_key, "artifact_sha256": artifact_sha256})
        return PinnedIcpDocument(
            front=ICP_FRONT,
            body=ICP_BODY,
            artifact_key=artifact_key,
            artifact_sha256=artifact_sha256,
            icp_key="clue-abm-buyers",
            icp_version=1,
        )

    monkeypatch.setattr(driver, "read_icp_document", fake_read_icp_document)
    monkeypatch.setattr(driver, "drain_provider_calls", drain)
    monkeypatch.setattr(driver, "insert_account_entity", accounts)
    monkeypatch.setattr(driver, "ensure_project_accounts", memberships)

    handler = Arv2DiscoveryWorkHandler(
        settings=settings or Settings(_env_file=None),
        conn_factory=conn_factory,
        storage=object(),
        artifacts=SimpleNamespace(),
        clients=_Clients(exa, websets),
        writer=writer,
        store=store,
        transport_factory=lambda: ScriptedTransport([]),
        clock=clock or _clock(),
        sleep=_no_sleep,
    )
    handler.icp_reads = icp_reads  # type: ignore[attr-defined]
    handler.memberships = memberships  # type: ignore[attr-defined]
    return handler, conn_factory, writer, drain, accounts


async def _no_sleep(seconds: float) -> None:
    del seconds


def _context(run_id: UUID) -> WorkContext:
    return WorkContext(
        task_id=uuid4(),
        work_id=arv2_discovery_work_id(run_id),
        worker_id="w1",
        lease_generation=LeaseGeneration(1),
        payload={"run_id": str(run_id), "workspace_id": WORKSPACE},
        stop_requested=asyncio.Event(),
        lease_lost=asyncio.Event(),
    )


# -- the tests -----------------------------------------------------------------------------------


def test_strict_pass_verifies_every_candidate_writes_fit_and_records_the_receipt(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    run = _run_row()
    store = _Store(run)
    exa = _FakeExa(
        _responder(
            {
                "Probook": _company_answers(
                    "Probook",
                    "probook.ai",
                    {"geography": "pass", "stage": "pass", "hiring": "pass", "intent": "pass"},
                ),
                "Patientdesk": _company_answers(
                    "Patientdesk",
                    "patientdesk.com",
                    {"geography": "pass", "stage": "fail", "hiring": "pass", "intent": "fail"},
                ),
            }
        )
    )
    websets = _FakeWebsets(
        items_results=[
            _items(
                _item(
                    "Probook",
                    "https://probook.com",
                    employees=120,
                    revenue_annual=8_000_000,
                ),
                _item("Patientdesk", "https://patientdesk.com"),
            )
        ]
    )
    handler, _, writer, drain, accounts = _handler(
        store, exa=exa, websets=websets, monkeypatch=monkeypatch
    )

    result = asyncio.run(handler.handle(_context(run.run_id)))

    assert handler.kind is FleetTaskKind.ARV2_DISCOVERY
    assert result.outcome == "completed"
    assert result.references == {"run_id": str(run.run_id)}

    # The long list was asked for exactly what the run was launched with.
    created = websets.named("create")[0]
    assert created["count"] == 35
    assert created["criteria"] == (GEOGRAPHY_RULE, STAGE_RULE, BUYER_SENTENCE)
    assert created["external_id"] == f"arv2-discovery:{run.run_id}"
    assert store.named("record_webset")[0]["asked"] == 35
    assert store.named("record_webset")[0]["recall_estimate"] == 180
    # The strict search is durable from the first write, so no later attempt has to guess it.
    assert store.named("record_webset")[0]["strict_search_id"] == "srch-strict"
    # And the document the run was pinned to is the one it verified against.
    assert handler.icp_reads == [  # type: ignore[attr-defined]
        {"artifact_key": run.icp_artifact_key, "artifact_sha256": run.icp_artifact_sha256}
    ]

    # Every candidate was verified: one website answer plus one answer per gate, twice over.
    assert len(exa.gate_queries()) == 8
    assert exa.models == ["exa"] * 10

    verdicts = {call["candidate_id"]: call for call in store.named("record_verdicts")}
    landed = list(verdicts.values())
    assert [call["disposition"] for call in landed] == ["pass", "partial"]
    assert [call["fit"] for call in landed] == [1.0, 0.5]
    assert all(call["account_entity_id"] is not None for call in landed)

    # The verified domain — not the long list's — is the account's, and the mismatch is recorded.
    assert [created["primary_domain"] for created in accounts.created] == [
        "probook.ai",
        "patientdesk.com",
    ]
    # Ruling 2026-09-11: every verified candidate's account joins the launching project, marked
    # as discovered — one membership per account, in the run's own workspace and project.
    memberships = handler.memberships  # type: ignore[attr-defined]
    assert [(ws, project, via) for ws, project, _ids, via in memberships.added] == [
        (WORKSPACE, PROJECT, "discovered")
    ] * len(accounts.created)
    snapshot = store.named("upsert_candidate")[0]["row"].provider_snapshot
    assert snapshot["websets_domain"] == "probook.com"
    assert snapshot["verified_domain"] == "probook.ai"

    fits = writer.by_field("account.scoring.fit")
    assert [draft.value_json for draft in fits] == [{"value": 1.0}, {"value": 0.5}]
    assert fits[0].confidence == 1.0
    assert fits[0].markers["pass"] == "strict"
    assert fits[0].markers["discovery_run_id"] == str(run.run_id)
    assert fits[0].markers["gates"] == {
        "geography": "pass",
        "stage": "pass",
        "hiring": "pass",
        "intent": "pass",
    }
    assert fits[0].evidence_span
    assert writer.by_field("core.employee_count")[0].value_json == 120
    assert writer.by_field("core.revenue_band")[0].value_json == "1m_10m"

    finished = store.named("finish_discovery_run")[0]
    assert finished["status"] == "completed"
    assert finished["found_strict"] == 2
    assert finished["found_relaxed"] == 0
    assert finished["analyzed"] == 300
    receipt = finished["receipt"]
    assert receipt["asked"] == 35
    assert receipt["recall_estimate"] == 180
    assert receipt["shown"] == 2
    assert receipt["target_count"] == 20
    assert receipt["criteria"] == [GEOGRAPHY_RULE, STAGE_RULE, BUYER_SENTENCE]
    assert receipt["criteria_relaxed"] is None
    assert receipt["guards"] == {"ok": 8}
    assert receipt["duplicates"] == 0
    assert receipt["not_chosen_before"] == 0
    assert receipt["unresolvable_domain"] == 0
    # Every hop's money landed under this run's own stamp.
    assert receipt["cost_usd"] == str(drain.cost_usd * len(drain.stamps))
    assert {stamp.job_id for stamp in drain.stamps} == {run.run_id}
    assert {stamp.project_id for stamp in drain.stamps} == {PROJECT}


def test_a_candidate_matching_an_existing_account_is_a_duplicate_with_no_spend(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    run = _run_row()
    store = _Store(run)
    exa = _FakeExa(
        _responder({"Probook": _company_answers("Probook", "probook.ai", {"geography": "pass"})})
    )
    websets = _FakeWebsets(items_results=[_items(_item("Probook", "https://probook.com"))])
    handler, _, writer, _, accounts = _handler(
        store,
        exa=exa,
        websets=websets,
        monkeypatch=monkeypatch,
        # The workspace already owns the *verified* domain, which the long list did not give.
        domains=["probook.ai"],
    )

    result = asyncio.run(handler.handle(_context(run.run_id)))

    assert result.outcome == "completed"
    # One website answer identified it; not one gate was asked.
    assert len(exa.queries) == 1
    assert exa.gate_queries() == []
    candidate = store.named("upsert_candidate")[0]["row"]
    assert candidate.domain == "probook.ai"
    assert candidate.disposition == "duplicate_of_existing"
    assert store.named("record_verdicts") == []
    assert accounts.created == []
    assert writer.drafts == []
    finished = store.named("finish_discovery_run")[0]
    assert finished["receipt"]["duplicates"] == 1
    assert finished["receipt"]["shown"] == 0


def test_an_earlier_unapproved_candidate_of_the_project_is_not_chosen_before_and_not_re_verified(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    run = _run_row()
    store = _Store(run, unapproved=frozenset({"probook.ai"}))
    exa = _FakeExa(
        _responder({"Probook": _company_answers("Probook", "probook.ai", {"geography": "pass"})})
    )
    websets = _FakeWebsets(items_results=[_items(_item("Probook", "https://probook.com"))])
    handler, _, writer, _, accounts = _handler(
        store, exa=exa, websets=websets, monkeypatch=monkeypatch
    )

    result = asyncio.run(handler.handle(_context(run.run_id)))

    assert result.outcome == "completed"
    assert store.named("unapproved_domains")[0]["before_run_id"] == run.run_id
    assert exa.gate_queries() == []
    candidate = store.named("upsert_candidate")[0]["row"]
    assert candidate.disposition == "not_chosen_before"
    assert accounts.created == []
    assert writer.drafts == []
    assert store.named("finish_discovery_run")[0]["receipt"]["not_chosen_before"] == 1


def test_the_relaxed_pass_runs_when_short_and_drops_the_lowest_success_criterion(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    run = _run_row(target_count=3, relaxed_enabled=True)
    store = _Store(run)
    passes = {"geography": "pass", "stage": "pass", "hiring": "pass", "intent": "pass"}
    exa = _FakeExa(
        _responder(
            {
                "Probook": _company_answers("Probook", "probook.ai", passes),
                "Patientdesk": _company_answers("Patientdesk", "patientdesk.com", passes),
            }
        )
    )
    relaxed_search = _search(search_id="srch-relaxed", found=1, analyzed=120, rates=())
    websets = _FakeWebsets(
        items_results=[
            _items(_item("Probook", "https://probook.com")),
            _items(
                _item("Probook", "https://probook.com"),
                _item(
                    "Patientdesk",
                    "https://patientdesk.com",
                    search_id="srch-relaxed",
                ),
            ),
        ],
        get_views=[
            _view(),
            _view(searches=(_search(rates=STRICT_RATES), relaxed_search)),
        ],
        add_search_view=_view(
            status="running", searches=(_search(rates=STRICT_RATES), relaxed_search)
        ),
    )
    handler, _, _, _, accounts = _handler(store, exa=exa, websets=websets, monkeypatch=monkeypatch)

    result = asyncio.run(handler.handle(_context(run.run_id)))

    assert result.outcome == "completed"
    added = websets.named("add_search")[0]
    assert added["count"] == 2  # the shortfall, never the whole target again
    assert added["criteria"] == (GEOGRAPHY_RULE, BUYER_SENTENCE)  # the 12% criterion is gone
    assert added["exclude_search_ids"] == ["srch-strict"]

    passes_by_domain = {
        row["row"].domain: row["row"].pass_ for row in store.named("upsert_candidate")
    }
    assert passes_by_domain == {"probook.ai": "strict", "patientdesk.com": "relaxed"}
    # The strict item the second items page repeats is skipped, not re-verified or re-written.
    assert len(accounts.created) == 2
    finished = store.named("finish_discovery_run")[0]
    assert finished["found_strict"] == 1
    assert finished["found_relaxed"] == 1
    assert finished["analyzed"] == 420
    assert finished["receipt"]["criteria_relaxed"] == [GEOGRAPHY_RULE, BUYER_SENTENCE]
    assert finished["receipt"]["shown"] == 2


def test_no_relaxed_pass_when_disabled_and_not_requested(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    run = _run_row(target_count=3, relaxed_enabled=False)
    store = _Store(run)
    exa = _FakeExa(
        _responder(
            {
                "Probook": _company_answers(
                    "Probook",
                    "probook.ai",
                    {"geography": "pass", "stage": "pass", "hiring": "pass", "intent": "pass"},
                )
            }
        )
    )
    websets = _FakeWebsets(items_results=[_items(_item("Probook", "https://probook.com"))])
    handler, _, _, _, _ = _handler(store, exa=exa, websets=websets, monkeypatch=monkeypatch)

    result = asyncio.run(handler.handle(_context(run.run_id)))

    assert result.outcome == "completed"
    assert websets.named("add_search") == []
    finished = store.named("finish_discovery_run")[0]
    assert finished["receipt"]["shown"] == 1  # short of 3, and honestly so
    assert finished["receipt"]["criteria_relaxed"] is None


def test_a_requested_relaxed_pass_on_a_finished_run_skips_the_strict_pass(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    run = _run_row(
        target_count=3,
        relaxed_enabled=False,
        relaxed_requested=True,
        webset_id="ws-1",
        asked=35,
        found_strict=1,
        recall_estimate=180,
    )
    already = CandidateRow(
        candidate_id=uuid4(),
        run_id=run.run_id,
        workspace_id=WORKSPACE,
        project_id=PROJECT,
        pass_="strict",
        domain="probook.ai",
        websets_url="https://probook.com",
        name="Probook",
        provider_snapshot={"verified_domain": "probook.ai"},
        fit=1.0,
        disposition="pass",
    )
    store = _Store(run, candidates=[already])
    exa = _FakeExa(
        _responder(
            {
                "Patientdesk": _company_answers(
                    "Patientdesk",
                    "patientdesk.com",
                    {"geography": "pass", "stage": "pass", "hiring": "pass", "intent": "pass"},
                )
            }
        )
    )
    relaxed_search = _search(search_id="srch-relaxed", found=1, analyzed=120)
    websets = _FakeWebsets(
        get_views=[
            _view(),
            _view(searches=(_search(rates=STRICT_RATES), relaxed_search)),
        ],
        items_results=[
            _items(_item("Patientdesk", "https://patientdesk.com", search_id="srch-relaxed"))
        ],
        add_search_view=_view(
            status="running", searches=(_search(rates=STRICT_RATES), relaxed_search)
        ),
    )
    handler, _, _, _, _ = _handler(store, exa=exa, websets=websets, monkeypatch=monkeypatch)

    result = asyncio.run(handler.handle(_context(run.run_id)))

    assert result.outcome == "completed"
    # No second long list was bought: the run reads the webset it already paid for.
    assert websets.named("create") == []
    assert store.named("record_webset") == []
    added = websets.named("add_search")[0]
    assert added["webset_id"] == "ws-1"
    assert added["count"] == 2
    assert added["exclude_search_ids"] == ["srch-strict"]
    # The widening was recorded before a single one of its rows was read.
    assert store.named("record_relaxed_search")[0] == {
        "run_id": run.run_id,
        "relaxed_search_id": "srch-relaxed",
    }
    finished = store.named("finish_discovery_run")[0]
    assert finished["found_strict"] == 1  # carried from the earlier attempt, not recounted
    assert finished["found_relaxed"] == 1
    assert finished["receipt"]["shown"] == 2


def test_the_wall_clock_ends_the_run_needs_review_with_the_reason(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    run = _run_row()
    store = _Store(run)
    exa = _FakeExa(_responder({}))
    websets = _FakeWebsets(get_views=[_view(status="running")])
    handler, _, _, _, _ = _handler(
        store,
        exa=exa,
        websets=websets,
        monkeypatch=monkeypatch,
        settings=Settings(_env_file=None, arv2_discovery_wall_s=60),
        clock=_clock(step_s=45.0),
    )

    result = asyncio.run(handler.handle(_context(run.run_id)))

    assert result.outcome == "needs_review"
    assert websets.named("items") == []  # nothing was read, so nothing was billed
    finished = store.named("finish_discovery_run")[0]
    assert finished["status"] == "needs_review"
    assert finished["receipt"]["failure"] == "webset_wall_exceeded"


def test_a_provider_failure_is_contained_as_needs_review_and_the_ledger_is_still_drained(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    run = _run_row()
    store = _Store(run)
    exa = _FakeExa(_responder({}))
    websets = _FakeWebsets(
        create_error=ProviderHalted("exa_websets", "payment_required", http_status=402)
    )
    handler, _, _, drain, _ = _handler(store, exa=exa, websets=websets, monkeypatch=monkeypatch)

    result = asyncio.run(handler.handle(_context(run.run_id)))

    assert result.outcome == "needs_review"
    finished = store.named("finish_discovery_run")[0]
    assert finished["status"] == "needs_review"
    assert finished["receipt"]["failure"] == "provider_halted"
    assert "payment_required" in finished["receipt"]["message"]
    # The hop that failed still drained: a call that happened is money truth even when it halted.
    assert len(drain.stamps) == 1


def test_a_redelivered_task_for_a_run_nobody_can_claim_completes_without_spending(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store = _Store(None)
    exa = _FakeExa(_responder({}))
    websets = _FakeWebsets()
    handler, _, _, _, _ = _handler(store, exa=exa, websets=websets, monkeypatch=monkeypatch)

    result = asyncio.run(handler.handle(_context(uuid4())))

    assert result.outcome == "completed"
    assert result.requeue is False
    assert websets.calls == []
    assert store.named("finish_discovery_run") == []


def test_a_stop_request_suspends_the_run_and_asks_for_a_requeue(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    run = _run_row()
    store = _Store(run)
    exa = _FakeExa(_responder({}))
    websets = _FakeWebsets()
    handler, _, _, _, _ = _handler(store, exa=exa, websets=websets, monkeypatch=monkeypatch)
    context = _context(run.run_id)
    context.stop_requested.set()

    result = asyncio.run(handler.handle(context))

    assert result.outcome == "stopped"
    assert result.requeue is True
    assert store.named("suspend_discovery_run")[0]["run_id"] == run.run_id
    assert websets.calls == []


def test_an_unreadable_payload_fails_the_task_without_inventing_a_run(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store = _Store(None)
    handler, _, _, _, _ = _handler(
        store, exa=_FakeExa(_responder({})), websets=_FakeWebsets(), monkeypatch=monkeypatch
    )
    context = replace(_context(uuid4()), payload={"workspace_id": WORKSPACE})

    result = asyncio.run(handler.handle(context))

    assert result.outcome == "failed"
    assert result.requeue is False
    assert store.events == []


def test_the_handler_is_not_composed_without_the_flag_or_the_key(tmp_path: Any) -> None:
    del tmp_path
    keyless = Secrets(_env_file=None)  # type: ignore[call-arg]
    settings = Settings(_env_file=None, arv2_discovery_enabled=True)

    assert (
        build_arv2_discovery_handler(
            Settings(_env_file=None), keyless, storage=object(), artifacts=SimpleNamespace()
        )
        is None
    )
    assert (
        build_arv2_discovery_handler(
            settings, keyless, storage=object(), artifacts=SimpleNamespace()
        )
        is None
    )


def test_the_dropped_criterion_is_the_least_satisfied_one_and_ties_drop_the_last() -> None:
    """The relaxed pass's one choice, pinned: which criterion the run stops filtering on.

    A criterion Exa reported no rate for is the one we know least about, so it counts as lowest;
    two criteria at the same rate drop the *last*, so the choice cannot depend on ordering luck.
    """
    a, b, c = "alpha", "beta", "gamma"

    assert driver.relaxed_criteria((a, b, c), ((a, 0.8), (b, 0.1), (c, 0.4))) == (a, c)
    # An unrated criterion outranks every rated one as the thing to drop.
    assert driver.relaxed_criteria((a, b, c), ((a, 0.8), (b, 0.1), (c, None))) == (a, b)
    # A criterion Exa never mentioned at all is unrated too.
    assert driver.relaxed_criteria((a, b, c), ((a, 0.8), (b, 0.1))) == (a, b)
    # A tie drops the last of the tied criteria.
    assert driver.relaxed_criteria((a, b, c), ((a, 0.2), (b, 0.9), (c, 0.2))) == (a, b)
    assert driver.relaxed_criteria((), ()) == ()


def test_a_revenue_band_is_arithmetic_over_the_registered_vocabulary() -> None:
    bands = [
        driver.revenue_band(amount)
        for amount in (999_999, 8_000_000, 40_000_000, 90_000_000, 400_000_000, 900_000_000, 4e9)
    ]
    assert bands == [
        "under_1m",
        "1m_10m",
        "10m_50m",
        "50m_100m",
        "100m_500m",
        "500m_1b",
        "1b_plus",
    ]


def test_a_refused_icp_lands_the_run_needs_review_under_the_refusals_own_name(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A prerequisite failure is contained, and it is recorded by the word the human knows."""
    run = _run_row()
    store = _Store(run)
    websets = _FakeWebsets()
    handler, _, _, _, _ = _handler(
        store, exa=_FakeExa(_responder({})), websets=websets, monkeypatch=monkeypatch
    )

    async def refuse(conn: Any, storage: Any, **kwargs: Any) -> Any:
        del conn, storage, kwargs
        raise Arv2DiscoveryRefused("project_icp_not_pinned", "no confirmed ICP is pinned")

    monkeypatch.setattr(driver, "read_icp_document", refuse)

    result = asyncio.run(handler.handle(_context(run.run_id)))

    assert result.outcome == "needs_review"
    assert websets.calls == []  # refused before a cent was spent
    finished = store.named("finish_discovery_run")[0]
    assert finished["status"] == "needs_review"
    assert finished["receipt"]["failure"] == "project_icp_not_pinned"


def test_a_resumed_run_skips_what_it_verified_and_re_verifies_what_it_only_started(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An attempt that died BEFORE it recorded a webset, between a candidate row and its verdicts.

    A candidate that already carries a disposition is never re-asked (it was paid for), but a
    ``pending`` one bought nothing that survived — so the resumed run verifies it rather than
    leaving a row on the list for ever with no verdict and no account.
    """
    run = _run_row()
    verified_already = CandidateRow(
        candidate_id=uuid4(),
        run_id=run.run_id,
        workspace_id=WORKSPACE,
        project_id=PROJECT,
        pass_="strict",
        domain="probook.ai",
        websets_url="https://probook.com",
        name="Probook",
        provider_snapshot={"websets_domain": "probook.com", "verified_domain": "probook.ai"},
        fit=1.0,
        disposition="pass",
    )
    stranded = CandidateRow(
        candidate_id=uuid4(),
        run_id=run.run_id,
        workspace_id=WORKSPACE,
        project_id=PROJECT,
        pass_="strict",
        domain="patientdesk.com",
        websets_url="https://patientdesk.com",
        name="Patientdesk",
        provider_snapshot={
            "websets_domain": "patientdesk.com",
            "verified_domain": "patientdesk.com",
        },
        disposition="pending",
    )
    store = _Store(run, candidates=[verified_already, stranded])
    exa = _FakeExa(
        _responder(
            {
                "Patientdesk": _company_answers(
                    "Patientdesk",
                    "patientdesk.com",
                    {"geography": "pass", "stage": "pass", "hiring": "pass", "intent": "pass"},
                )
            }
        )
    )
    websets = _FakeWebsets(
        items_results=[
            _items(
                _item("Probook", "https://probook.com"),
                _item("Patientdesk", "https://patientdesk.com"),
            )
        ]
    )
    handler, _, _, _, accounts = _handler(store, exa=exa, websets=websets, monkeypatch=monkeypatch)

    result = asyncio.run(handler.handle(_context(run.run_id)))

    assert result.outcome == "completed"
    # Probook was verified before and is not asked again; Patientdesk is finished properly.
    assert [name for name in ("Probook",) if any(name in q for q in exa.queries)] == []
    assert len(exa.gate_queries()) == 4
    assert [created["primary_domain"] for created in accounts.created] == ["patientdesk.com"]
    landed = store.named("record_verdicts")
    assert len(landed) == 1
    assert landed[0]["disposition"] == "pass"
    # The earlier attempt's verified candidate still counts toward what the human is being shown.
    assert store.named("finish_discovery_run")[0]["receipt"]["shown"] == 2


def _verified_candidate(run: DiscoveryRunRow, name: str, domain: str, url: str) -> CandidateRow:
    return CandidateRow(
        candidate_id=uuid4(),
        run_id=run.run_id,
        workspace_id=WORKSPACE,
        project_id=PROJECT,
        pass_="strict",
        domain=domain,
        websets_url=url,
        name=name,
        provider_snapshot={
            "websets_domain": registrable_domain(url),
            "verified_domain": domain,
        },
        fit=1.0,
        disposition="pass",
    )


def test_a_resumed_run_reads_the_webset_it_already_bought_instead_of_creating_another(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A stop, a lost lease or a restart must not buy the long list a second time.

    The run row carries the webset it paid for, so the redelivered task polls and reads *that*
    webset and verifies only the companies its earlier attempt never finished.
    """
    run = _run_row(webset_id="ws-1", asked=35, recall_estimate=180, relaxed_enabled=False)
    store = _Store(
        run,
        candidates=[_verified_candidate(run, "Probook", "probook.ai", "https://probook.com")],
    )
    exa = _FakeExa(
        _responder(
            {
                "Patientdesk": _company_answers(
                    "Patientdesk",
                    "patientdesk.com",
                    {"geography": "pass", "stage": "pass", "hiring": "pass", "intent": "pass"},
                )
            }
        )
    )
    websets = _FakeWebsets(
        items_results=[
            _items(
                _item("Probook", "https://probook.com"),
                _item("Patientdesk", "https://patientdesk.com"),
            )
        ]
    )
    handler, _, _, _, accounts = _handler(store, exa=exa, websets=websets, monkeypatch=monkeypatch)

    result = asyncio.run(handler.handle(_context(run.run_id)))

    assert result.outcome == "completed"
    # Not one cent of a second long list: no create, and the recorded webset is what is read.
    assert websets.named("create") == []
    assert store.named("record_webset") == []
    assert [call["webset_id"] for call in websets.named("get")] == ["ws-1"]
    assert [call["webset_id"] for call in websets.named("items")] == ["ws-1"]
    # Only the company the earlier attempt never finished is verified.
    assert len(exa.gate_queries()) == 4
    assert [created["primary_domain"] for created in accounts.created] == ["patientdesk.com"]
    finished = store.named("finish_discovery_run")[0]
    # The counters report what the list HELD, not what this attempt happened to do.
    assert finished["found_strict"] == 2
    assert finished["found_relaxed"] == 0
    assert finished["receipt"]["shown"] == 2


def test_a_failing_candidate_is_contained_and_named_while_its_neighbours_still_land(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """One company going wrong is one company, never the run: the others were paid for too."""
    run = _run_row()
    store = _Store(run)
    passes = {"geography": "pass", "stage": "pass", "hiring": "pass", "intent": "pass"}
    exa = _FakeExa(
        _responder(
            {
                "Probook": _company_answers("Probook", "probook.ai", passes),
                "Zafran": _company_answers("Zafran", "zafran.io", passes),
                "Patientdesk": _company_answers("Patientdesk", "patientdesk.com", passes),
            }
        )
    )
    websets = _FakeWebsets(
        items_results=[
            _items(
                _item("Probook", "https://probook.com"),
                _item("Zafran", "https://zafran.io"),
                _item("Patientdesk", "https://patientdesk.com"),
            )
        ]
    )
    handler, _, _, _, accounts = _handler(
        store,
        exa=exa,
        websets=websets,
        monkeypatch=monkeypatch,
        account_writes_fail_on=frozenset({"zafran.io"}),
    )

    result = asyncio.run(handler.handle(_context(run.run_id)))

    assert result.outcome == "needs_review"
    assert [created["primary_domain"] for created in accounts.created] == [
        "probook.ai",
        "patientdesk.com",
    ]
    landed = store.named("record_verdicts")
    assert len(landed) == 2
    finished = store.named("finish_discovery_run")[0]
    assert finished["status"] == "needs_review"
    # Every counter survives the containment — the run is a finished run minus one company.
    assert finished["found_strict"] == 3
    assert finished["receipt"]["shown"] == 2
    assert finished["receipt"]["candidate_failures"] == [
        {"domain": "zafran.io", "code": "RuntimeError"}
    ]
    # The failed company keeps its row at ``pending``, so a later attempt re-verifies it.
    zafran = [
        row["row"] for row in store.named("upsert_candidate") if row["row"].domain == "zafran.io"
    ]
    assert [row.disposition for row in zafran] == ["pending"]


def test_a_task_whose_work_id_disagrees_with_its_run_is_refused_before_it_spends(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    run = _run_row()
    store = _Store(run)
    websets = _FakeWebsets()
    handler, _, _, _, _ = _handler(
        store, exa=_FakeExa(_responder({})), websets=websets, monkeypatch=monkeypatch
    )
    context = replace(_context(run.run_id), work_id=arv2_discovery_work_id(uuid4()))

    result = asyncio.run(handler.handle(context))

    assert result.outcome == "needs_review"
    assert websets.calls == []
    assert store.named("begin_discovery_run") == []
    finished = store.named("finish_discovery_run")[0]
    assert finished["status"] == "needs_review"
    assert finished["receipt"]["failure"] == "invalid_task_payload"


def test_a_run_whose_pinned_icp_bytes_moved_is_refused_before_a_provider_is_touched(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The run verifies against its OWN pin, not the project's current one (final review I1).

    A human confirms a new ICP version and repins the project while this run is queued. The run
    row still names the bytes the human authorized, so the document read refuses on the digest and
    the run lands ``needs_review`` — rather than compiling a brief from the *new* document's gates
    and grading the rest of its candidates against questions the first half never faced.
    """
    run = _run_row()
    store = _Store(run)
    websets = _FakeWebsets()
    handler, _, _, _, _ = _handler(
        store, exa=_FakeExa(_responder({})), websets=websets, monkeypatch=monkeypatch
    )

    asked: list[dict[str, str]] = []

    async def moved(conn: Any, storage: Any, **kwargs: Any) -> Any:
        del conn, storage
        asked.append({str(key): str(value) for key, value in kwargs.items()})
        raise Arv2DiscoveryRefused(
            "icp_digest_mismatch",
            f"document does not hold the bytes it was pinned to: stored {'e' * 64}, "
            f"pinned {run.icp_artifact_sha256}",
        )

    monkeypatch.setattr(driver, "read_icp_document", moved)

    result = asyncio.run(handler.handle(_context(run.run_id)))

    assert result.outcome == "needs_review"
    # It asked for the RUN's pinned artifact, by key and by sha — not for the project's pin.
    assert asked == [
        {
            "workspace_id": WORKSPACE,
            "artifact_key": run.icp_artifact_key,
            "artifact_sha256": run.icp_artifact_sha256,
        }
    ]
    assert websets.calls == []  # refused before a cent was spent
    finished = store.named("finish_discovery_run")[0]
    assert finished["status"] == "needs_review"
    assert finished["receipt"]["failure"] == "icp_digest_mismatch"


def test_a_resumed_relaxed_pass_reads_the_search_it_bought_instead_of_buying_a_second(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The widening is bought once per run (final review I2, scenario A).

    The first attempt added the relaxed search and died before it finished verifying its results.
    ``relaxed_requested`` is still true, so this attempt runs the relaxed pass again — and must
    poll and read the search that is already paid for. A second ``add_search`` would exclude only
    the *strict* search, so Exa would re-find and re-charge for everything the first widening
    returned, once per retry.
    """
    run = _run_row(
        target_count=3,
        relaxed_enabled=False,
        relaxed_requested=True,
        webset_id="ws-1",
        strict_search_id="srch-strict",
        relaxed_search_id="srch-relaxed",
        asked=35,
        found_strict=1,
        recall_estimate=180,
    )
    store = _Store(
        run,
        candidates=[_verified_candidate(run, "Probook", "probook.ai", "https://probook.com")],
    )
    exa = _FakeExa(
        _responder(
            {
                "Patientdesk": _company_answers(
                    "Patientdesk",
                    "patientdesk.com",
                    {"geography": "pass", "stage": "pass", "hiring": "pass", "intent": "pass"},
                )
            }
        )
    )
    relaxed_search = _search(search_id="srch-relaxed", found=1, analyzed=120)
    websets = _FakeWebsets(
        get_views=[_view(searches=(_search(rates=STRICT_RATES), relaxed_search))],
        items_results=[
            _items(
                _item("Probook", "https://probook.com"),
                _item("Patientdesk", "https://patientdesk.com", search_id="srch-relaxed"),
            )
        ],
    )
    handler, _, _, _, accounts = _handler(store, exa=exa, websets=websets, monkeypatch=monkeypatch)

    result = asyncio.run(handler.handle(_context(run.run_id)))

    assert result.outcome == "completed"
    # Not a second widening, and not a second webset: only the free read of what was bought.
    assert websets.named("add_search") == []
    assert websets.named("create") == []
    assert store.named("record_relaxed_search") == []
    receipt = store.named("finish_discovery_run")[0]["receipt"]
    # This attempt sent no criteria, and says so — but it still names the widening that happened.
    assert receipt["criteria_relaxed"] is None
    assert receipt["relaxed_search_id"] == "srch-relaxed"
    # Two free reads of the same webset — the relaxed resume's, then the poll's — and no third id.
    assert [call["webset_id"] for call in websets.named("get")] == ["ws-1", "ws-1"]
    assert [call["webset_id"] for call in websets.named("items")] == ["ws-1"]
    # Only the company the earlier attempt never verified is verified, and as a relaxed one.
    assert len(exa.gate_queries()) == 4
    assert [created["primary_domain"] for created in accounts.created] == ["patientdesk.com"]
    landed = store.named("upsert_candidate")
    assert [(row["row"].domain, row["row"].pass_) for row in landed] == [
        ("patientdesk.com", "relaxed")
    ]


def test_the_strict_search_is_found_by_id_even_when_the_relaxed_one_is_listed_first(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Array position is not a provider contract (final review I2, scenario B).

    Exa returns this webset's searches newest-first. The run recorded which search is the strict
    one, so the exclusion still names it, every strict item is still labelled ``strict``, and the
    dropped criterion is still chosen from the *strict* search's success rates.
    """
    run = _run_row(
        target_count=3,
        relaxed_enabled=True,
        webset_id="ws-1",
        strict_search_id="srch-strict",
        asked=35,
        recall_estimate=180,
    )
    store = _Store(run)
    passes = {"geography": "pass", "stage": "pass", "hiring": "pass", "intent": "pass"}
    exa = _FakeExa(
        _responder(
            {
                "Probook": _company_answers("Probook", "probook.ai", passes),
                "Patientdesk": _company_answers("Patientdesk", "patientdesk.com", passes),
            }
        )
    )
    relaxed_search = _search(search_id="srch-relaxed", found=1, analyzed=120, rates=())
    # The relaxed search is listed FIRST — ``searches[0]`` would be the wrong answer everywhere.
    newest_first = _view(searches=(relaxed_search, _search(rates=STRICT_RATES)))
    websets = _FakeWebsets(
        get_views=[newest_first],
        items_results=[
            _items(_item("Probook", "https://probook.com")),
            _items(
                _item("Probook", "https://probook.com"),
                _item("Patientdesk", "https://patientdesk.com", search_id="srch-relaxed"),
            ),
        ],
        add_search_view=newest_first,
    )
    handler, _, _, _, _ = _handler(store, exa=exa, websets=websets, monkeypatch=monkeypatch)

    result = asyncio.run(handler.handle(_context(run.run_id)))

    assert result.outcome == "completed"
    added = websets.named("add_search")[0]
    assert added["exclude_search_ids"] == ["srch-strict"]
    # The strict search's own rates chose the dropped criterion — the relaxed one reported none.
    assert added["criteria"] == (GEOGRAPHY_RULE, BUYER_SENTENCE)
    assert store.named("record_relaxed_search")[0]["relaxed_search_id"] == "srch-relaxed"
    passes_by_domain = {
        row["row"].domain: row["row"].pass_ for row in store.named("upsert_candidate")
    }
    assert passes_by_domain == {"probook.ai": "strict", "patientdesk.com": "relaxed"}


def test_a_webset_with_two_searches_and_no_recorded_strict_id_refuses_rather_than_guesses(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The one case a guess would be silently wrong: refuse it by name."""
    run = _run_row(webset_id="ws-1", asked=35, relaxed_enabled=False)
    store = _Store(run)
    websets = _FakeWebsets(
        get_views=[_view(searches=(_search(search_id="srch-relaxed"), _search(rates=STRICT_RATES)))]
    )
    handler, _, _, _, _ = _handler(
        store, exa=_FakeExa(_responder({})), websets=websets, monkeypatch=monkeypatch
    )

    result = asyncio.run(handler.handle(_context(run.run_id)))

    assert result.outcome == "needs_review"
    assert websets.named("items") == []  # nothing was read, so nothing was billed
    finished = store.named("finish_discovery_run")[0]
    assert finished["receipt"]["failure"] == "webset_search_ambiguous"


def test_a_webset_row_is_priced_once_per_run_across_the_relaxed_re_read(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The relaxed pass re-reads the WHOLE webset; the strict rows are not billed again (I4).

    Every ``items`` read returns every row, so without the already-priced set the strict pass's
    rows land on ``provider_call_ledger`` — and in ``receipt.cost_usd`` — twice. §8's exit gate
    divides by that number.
    """
    run = _run_row(target_count=3, relaxed_enabled=True)
    store = _Store(run)
    passes = {"geography": "pass", "stage": "pass", "hiring": "pass", "intent": "pass"}
    exa = _FakeExa(
        _responder(
            {
                "Probook": _company_answers("Probook", "probook.ai", passes),
                "Patientdesk": _company_answers("Patientdesk", "patientdesk.com", passes),
            }
        )
    )
    relaxed_search = _search(search_id="srch-relaxed", found=1, analyzed=120, rates=())
    websets = _FakeWebsets(
        items_results=[
            _items(_item("Probook", "https://probook.com")),
            _items(
                _item("Probook", "https://probook.com"),
                _item("Patientdesk", "https://patientdesk.com", search_id="srch-relaxed"),
            ),
        ],
        get_views=[_view(), _view(searches=(_search(rates=STRICT_RATES), relaxed_search))],
        add_search_view=_view(
            status="running", searches=(_search(rates=STRICT_RATES), relaxed_search)
        ),
    )
    handler, _, _, _, _ = _handler(store, exa=exa, websets=websets, monkeypatch=monkeypatch)

    result = asyncio.run(handler.handle(_context(run.run_id)))

    assert result.outcome == "completed"
    reads = websets.named("items")
    # The first read pays for nothing before it; the second names the strict row it already paid.
    assert [call["priced_item_ids"] for call in reads] == [
        frozenset(),
        frozenset({"itm-probook"}),
    ]
    # Both rows came back the second time; only the new one was billed.
    first, second = websets.returned_items
    assert first.priced_item_ids == ("itm-probook",)
    assert first.cost_usd == ITEM_COST
    assert [item.name for item in second.items] == ["Probook", "Patientdesk"]
    assert second.priced_item_ids == ("itm-patientdesk",)
    assert second.cost_usd == ITEM_COST  # one row, not two — the strict row is not re-billed
    assert store.named("finish_discovery_run")[0]["receipt"]["credits_priced_once"] is True


def test_a_resumed_run_does_not_re_price_the_rows_an_earlier_attempt_already_paid_for(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The other half of I4: a plain resume re-reads the same webset and must not re-bill it.

    The item ids come off the candidate rows the earlier attempt wrote — the raw Websets record is
    kept whole on each snapshot — so "already paid for" survives a worker restart.
    """
    run = _run_row(webset_id="ws-1", asked=35, recall_estimate=180, relaxed_enabled=False)
    already = _verified_candidate(run, "Probook", "probook.ai", "https://probook.com")
    store = _Store(
        run,
        candidates=[
            replace(
                already,
                provider_snapshot={**already.provider_snapshot, "item": {"id": "itm-probook"}},
            )
        ],
    )
    exa = _FakeExa(
        _responder(
            {
                "Patientdesk": _company_answers(
                    "Patientdesk",
                    "patientdesk.com",
                    {"geography": "pass", "stage": "pass", "hiring": "pass", "intent": "pass"},
                )
            }
        )
    )
    websets = _FakeWebsets(
        items_results=[
            _items(
                _item("Probook", "https://probook.com"),
                _item("Patientdesk", "https://patientdesk.com"),
            )
        ]
    )
    handler, _, _, _, _ = _handler(store, exa=exa, websets=websets, monkeypatch=monkeypatch)

    result = asyncio.run(handler.handle(_context(run.run_id)))

    assert result.outcome == "completed"
    assert websets.named("items")[0]["priced_item_ids"] == frozenset({"itm-probook"})
    (read,) = websets.returned_items
    assert [item.name for item in read.items] == ["Probook", "Patientdesk"]
    assert read.priced_item_ids == ("itm-patientdesk",)
    assert read.cost_usd == ITEM_COST


# --- the mark-type logo and creator-as-owner (founder rulings 2026-09-11) ---------------------

LINKEDIN_MARK = (
    "https://media.licdn.com/dms/image/v2/C560BAQGQ7Cv/company-logo_200_200/0?e=2147483647&v=beta"
)


def _one_company_run(
    monkeypatch: pytest.MonkeyPatch, *, logo_url: str | None
) -> tuple[_Writer, _Accounts]:
    """One strict run over one all-passing company, ``Acme`` at ``acme.com``."""
    run = _run_row()
    store = _Store(run)
    exa = _FakeExa(
        _responder(
            {
                "Acme": _company_answers(
                    "Acme",
                    "acme.com",
                    {"geography": "pass", "stage": "pass", "hiring": "pass", "intent": "pass"},
                )
            }
        )
    )
    websets = _FakeWebsets(
        items_results=[_items(_item("Acme", "https://acme.com", logo_url=logo_url))]
    )
    handler, _, writer, _, accounts = _handler(
        store, exa=exa, websets=websets, monkeypatch=monkeypatch
    )
    result = asyncio.run(handler.handle(_context(run.run_id)))
    assert result.outcome == "completed"
    return writer, accounts


def _logo_drafts(writer: _Writer) -> list[tuple[Any, str]]:
    return [(d.value_json, d.source_key) for d in writer.drafts if d.field_key == "core.logo_url"]


def test_a_linkedin_company_mark_from_websets_is_stored_as_the_accounts_logo(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    writer, _ = _one_company_run(monkeypatch, logo_url=LINKEDIN_MARK)
    assert _logo_drafts(writer) == [(LINKEDIN_MARK, "exa_websets")]


def test_a_site_hosted_websets_image_is_not_stored_and_nothing_else_is_fetched(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A social banner from the company's own site is not a mark (proof of concept, 2026-09-11):
    no claim is written; the reads fall back to Brandfetch's embed-only Logo API URL at display
    time, which the driver never fetches."""
    writer, _ = _one_company_run(monkeypatch, logo_url="https://acme.com/img/opengraph.jpg")
    assert _logo_drafts(writer) == []


def test_the_requesting_human_is_the_creator_and_the_owner_of_a_discovered_account(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _, accounts = _one_company_run(monkeypatch, logo_url=None)
    [created] = accounts.created
    assert created["owner_user_id"] == "usr-1"
    assert created["created_by_user_id"] == "usr-1"


def test_a_run_requested_by_the_fleets_service_principal_stamps_no_owner(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A deepagent-launched run records ``svc_execution_worker`` as its requester; that is nobody's
    owner and no FK target, so the account is created unowned rather than the run failing."""
    run = _run_row(requested_by_user_id="svc_execution_worker")
    store = _Store(run)
    exa = _FakeExa(
        _responder(
            {
                "Acme": _company_answers(
                    "Acme",
                    "acme.com",
                    {"geography": "pass", "stage": "pass", "hiring": "pass", "intent": "pass"},
                )
            }
        )
    )
    websets = _FakeWebsets(items_results=[_items(_item("Acme", "https://acme.com"))])
    handler, _, _, _, accounts = _handler(store, exa=exa, websets=websets, monkeypatch=monkeypatch)
    assert asyncio.run(handler.handle(_context(run.run_id))).outcome == "completed"
    [created] = accounts.created
    assert created["owner_user_id"] is None and created["created_by_user_id"] is None
