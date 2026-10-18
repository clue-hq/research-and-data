"""The R4 discovery driver, offline: the run's steps, the money law, and the receipt it lands.

Nothing here reaches a provider, a model or a database. The store is doubled (it records every
transition in order), the two clients are scripted, and the three reads the driver makes through
other packages — the pinned ICP, the account writer, the ledger drain — are patched at the
driver's own module names. What is asserted is therefore the driver's own contract:

* **every candidate is verified before it is written**, and the verdicts the guards produced are
  what the fit is computed from;
* **the first round asks for exactly the target**, a top-up round asks the SAME brief only for
  the shortfall, and every webset round excludes the websets before it (spec 2026-09-30 §4);
* **no money is spent on a company this project already has or already found** — a duplicate and
  a ``found_before`` cost the one website answer that identified them and not a single gate — while
  an account of ANOTHER project is verified against this ICP and joins this project on its own row;
* **a gate's role decides**: a failed ``must`` or a passed ``must_not`` excludes the company, an
  unclear never does, and the fit is over the ``must`` and ``prefer`` gates;
* **every ending runs one end block**: the summary is written and either handed to the launching
  thread's wake turn (the run stays held) or the run is released at once;
* **``handle`` never raises**: a wall-clock overrun and a provider that refuses to sell both land
  the run ``needs_review`` with a named reason, and the ledger is drained either way.
"""

from __future__ import annotations

import asyncio
import threading
import time
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
from clue_api.arv2.discovery_store import CandidateRow, DiscoveryRunRow, SearchRow
from clue_api.arv2.errors import ProviderHalted
from clue_api.arv2.exa_client import ExaAnswerResult, ExaCitation
from clue_api.arv2.exa_websets_client import (
    ImportHandle,
    ImportStatus,
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


#: The brief the Head of ABM wrote for these runs: the ICP's four gates, each a ``prefer`` — so no
#: gate excludes and the fit is over all four, the shape every scenario below was written for. The
#: roles' own behaviour is exercised by the scenarios that set a ``must`` or a ``must_not``.
def _brief_json(**roles: str) -> dict[str, Any]:
    return {
        "source": "websets",
        "query": BUYER_SENTENCE,
        "criteria": [GEOGRAPHY_RULE, STAGE_RULE, BUYER_SENTENCE],
        "gates": [
            {**gate, "role": roles.get(gate["key"], "prefer")} for gate in ICP_FRONT["hard_gates"]
        ],
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
        "relaxed_enabled": False,
        "criteria_gate_keys": (),
        "status": "in_progress",
        "source": "websets",
        "brief": _brief_json(),
    }
    payload.update(overrides)
    return DiscoveryRunRow(**payload)


class _Store:
    """Every discovery transition, recorded in order, with no SQL behind it."""

    def __init__(
        self,
        run: DiscoveryRunRow | None,
        *,
        found_before: frozenset[str] = frozenset(),
        prior_websets: Sequence[str] = (),
        candidates: Sequence[CandidateRow] = (),
        searches: Sequence[SearchRow] = (),
        seller_domain: str | None = None,
    ) -> None:
        self.run = run
        self.seller = seller_domain
        self.found_before = found_before
        self.prior_websets = tuple(prior_websets)
        self.candidates = list(candidates)
        self.searches = {search.ordinal: search for search in searches}
        self.events: list[tuple[str, dict[str, Any]]] = []
        #: A human's Stop, as the driver reads it: ``None`` never; ``n`` from the read after the
        #: first ``n`` reads on.
        self.stop_after: int | None = None
        self.stop_reads = 0

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

    async def create_search(self, conn: Any, row: SearchRow) -> SearchRow:
        del conn
        self.events.append(("create_search", {"row": row}))
        return self.searches.setdefault(row.ordinal, row)

    async def record_search_webset(self, conn: Any, **kwargs: Any) -> None:
        del conn
        self.events.append(("record_search_webset", kwargs))
        held = self.searches[kwargs["ordinal"]]
        self.searches[held.ordinal] = replace(held, webset_id=kwargs["webset_id"])

    async def finish_search(self, conn: Any, **kwargs: Any) -> None:
        del conn
        self.events.append(("finish_search", kwargs))
        held = self.searches[kwargs["ordinal"]]
        self.searches[held.ordinal] = replace(held, found=kwargs["found"], finished_at=NOW)

    async def list_searches(self, conn: Any, *, run_id: UUID) -> tuple[SearchRow, ...]:
        del conn
        return tuple(search for _, search in sorted(self.searches.items()))

    async def record_discovery_progress(self, conn: Any, **kwargs: Any) -> None:
        del conn
        self.events.append(("record_discovery_progress", kwargs))

    async def finish_discovery_run(self, conn: Any, **kwargs: Any) -> None:
        del conn
        self.events.append(("finish_discovery_run", kwargs))

    async def stop_requested(self, conn: Any, *, run_id: UUID) -> bool:
        del conn, run_id
        self.stop_reads += 1
        return self.stop_after is not None and self.stop_reads > self.stop_after

    async def end_discovery_run(self, conn: Any, **kwargs: Any) -> None:
        del conn
        self.events.append(("end_discovery_run", kwargs))

    async def record_wake_turn(self, conn: Any, **kwargs: Any) -> None:
        del conn
        self.events.append(("record_wake_turn", kwargs))

    async def upsert_candidate(self, conn: Any, row: CandidateRow) -> UUID:
        del conn
        self.events.append(("upsert_candidate", {"row": row}))
        self.candidates.append(row)
        return row.candidate_id

    async def record_verdicts(self, conn: Any, **kwargs: Any) -> None:
        del conn
        self.events.append(("record_verdicts", kwargs))

    async def seller_domain(self, conn: Any, *, workspace_id: str, brand_id: str) -> str | None:
        del conn
        self.events.append(("seller_domain", {"workspace_id": workspace_id, "brand_id": brand_id}))
        return self.seller

    async def list_candidates(self, conn: Any, *, run_id: UUID) -> tuple[CandidateRow, ...]:
        del conn
        self.events.append(("list_candidates", {"run_id": run_id}))
        return tuple(row for row in self.candidates if row.run_id == run_id)

    async def project_found_domains(
        self, conn: Any, *, workspace_id: str, project_id: str, before_run_id: UUID
    ) -> frozenset[str]:
        del conn
        self.events.append(
            (
                "project_found_domains",
                {
                    "workspace_id": workspace_id,
                    "project_id": project_id,
                    "before_run_id": before_run_id,
                },
            )
        )
        return self.found_before

    async def project_webset_ids(
        self, conn: Any, *, workspace_id: str, project_id: str, before_run_id: UUID
    ) -> tuple[str, ...]:
        del conn, workspace_id, project_id, before_run_id
        return self.prior_websets

    def named(self, name: str) -> list[dict[str, Any]]:
        return [payload for event, payload in self.events if event == name]


class _Rows(list):
    """A list that also answers ``first()`` — the two shapes the driver reads off a result."""

    def first(self) -> Any:
        return self[0] if self else None


class _Conn:
    """A connection that answers the driver's three account reads: the workspace's accounts by
    domain, this project's account domains, and "is this requester a platform user" (yes for
    ``usr-*`` ids, no for a service principal)."""

    def __init__(
        self, project_domains: Sequence[str] = (), workspace_accounts: Mapping[str, UUID] = {}
    ) -> None:
        self.project_domains = list(project_domains)
        # A project's accounts are accounts of the workspace too.
        self.workspace_accounts = {
            **{domain: uuid4() for domain in project_domains},
            **dict(workspace_accounts),
        }
        self.statements: list[str] = []

    async def execute(self, statement: Any, parameters: Any = None) -> Any:
        sql = str(statement)
        self.statements.append(sql)
        if "platform_user" in sql:
            user_id = str((parameters or {}).get("user_id", ""))
            return _Rows([(1,)] if user_id.startswith("usr") else [])
        if "project_account" in sql:
            return _Rows([(domain,) for domain in self.project_domains])
        return _Rows(list(self.workspace_accounts.items()))

    @asynccontextmanager
    async def begin_nested(self) -> AsyncIterator[None]:
        yield


class _ConnFactory:
    def __init__(
        self, project_domains: Sequence[str] = (), workspace_accounts: Mapping[str, UUID] = {}
    ) -> None:
        self.conn = _Conn(project_domains, workspace_accounts)
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
    """Scripted ``find``/``create``/``get``/``items``/``cancel``, each recording what it was asked.

    One webset by default (``ws-1``): ``get_views`` and ``items_results`` script it, the last entry
    repeating. A test with several searches scripts one webset per search in ``websets`` — the
    create views are handed out in order, and each webset id has its own views and items.
    """

    def __init__(
        self,
        *,
        create_view: WebsetView | None = None,
        get_views: Sequence[WebsetView] = (),
        items_results: Sequence[WebsetItemsResult] = (),
        create_error: Exception | None = None,
        items_after_cancel: WebsetItemsResult | None = None,
        websets: Mapping[str, tuple[Sequence[WebsetView], Sequence[WebsetItemsResult]]] = {},
        found: Mapping[str, WebsetView] = {},
        import_statuses: Sequence[str | ImportStatus] = ("completed",),
    ) -> None:
        self._import_statuses = list(import_statuses)
        self._create_views = (
            [_view(webset_id=webset_id, status="running") for webset_id in websets]
            if websets
            else [create_view or _view(status="running")]
        )
        self._get_views = {"": list(get_views) or [_view()]}
        self._items = {"": list(items_results) or [_items()]}
        for webset_id, (views, items) in websets.items():
            self._get_views[webset_id] = list(views) or [_view(webset_id=webset_id)]
            self._items[webset_id] = list(items) or [_items()]
        self._found = dict(found)
        self._create_error = create_error
        #: What Exa holds once the webset is cancelled — the rows it found after the run stopped
        #: reading, which only the read after the cancel can put on the ledger.
        self._items_after_cancel = items_after_cancel
        self.calls: list[tuple[str, dict[str, Any]]] = []
        #: What each ``items`` read actually priced, in order — the fake's money trail.
        self.returned_items: list[WebsetItemsResult] = []

    @staticmethod
    def _next(scripted: dict[str, list[Any]], webset_id: str) -> Any:
        queue = scripted.get(webset_id) or scripted[""]
        value = queue[0]
        if len(queue) > 1:
            queue.pop(0)
        return value

    def find(self, external_id: str) -> WebsetView | None:
        self.calls.append(("find", {"external_id": external_id}))
        return self._found.get(external_id)

    def create(self, **kwargs: Any) -> WebsetView:
        self.calls.append(("create", kwargs))
        if self._create_error is not None:
            raise self._create_error
        view = self._create_views[0]
        if len(self._create_views) > 1:
            self._create_views.pop(0)
        return view

    def get(self, webset_id: str) -> WebsetView:
        self.calls.append(("get", {"webset_id": webset_id}))
        return self._next(self._get_views, webset_id)

    def items(
        self, webset_id: str, *, priced_item_ids: frozenset[str] = frozenset()
    ) -> WebsetItemsResult:
        self.calls.append(
            ("items", {"webset_id": webset_id, "priced_item_ids": frozenset(priced_item_ids)})
        )
        if self._items_after_cancel is not None and self.named("cancel"):
            result = self._items_after_cancel
        else:
            result = self._next(self._items, webset_id)
        repriced = _repriced(result, frozenset(priced_item_ids))
        self.returned_items.append(repriced)
        return repriced

    def cancel(self, webset_id: str) -> WebsetView:
        self.calls.append(("cancel", {"webset_id": webset_id}))
        return _view(webset_id=webset_id, status="idle")

    def create_import(self, *, csv_bytes: bytes, count: int, title: str) -> ImportHandle:
        self.calls.append(("create_import", {"csv_bytes": csv_bytes, "count": count}))
        return ImportHandle(import_id="i1", upload_url="https://up.example/i1")

    def upload_import(self, *, upload_url: str, csv_bytes: bytes) -> None:
        self.calls.append(("upload_import", {"upload_url": upload_url, "csv_bytes": csv_bytes}))

    def get_import(self, import_id: str) -> ImportStatus:
        self.calls.append(("get_import", {"import_id": import_id}))
        status = self._import_statuses[0]
        if len(self._import_statuses) > 1:
            self._import_statuses.pop(0)
        if isinstance(status, ImportStatus):
            return status
        # A completed Import read every row it was sent unless a test says otherwise.
        sent = self.named("create_import")[-1]["count"] if self.named("create_import") else 0
        return ImportStatus(status=status, count=sent if status == "completed" else None)

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

    def __init__(
        self, respond: Callable[[str], ExaAnswerResult], *, search_hits: Sequence[Any] = ()
    ) -> None:
        self._respond = respond
        self.search_hits = list(search_hits)
        self.searches: list[dict[str, Any]] = []
        self.queries: list[str] = []
        self.labels: list[str] = []
        self.models: list[str] = []

    def answer(self, query: str, **kwargs: Any) -> ExaAnswerResult:
        self.queries.append(query)
        self.labels.append(str(kwargs.get("label", "")))
        self.models.append(str(kwargs.get("model", "")))
        return self._respond(query)

    def search(self, query: str, **kwargs: Any) -> Any:
        del query
        self.searches.append(kwargs)
        return SimpleNamespace(status=200, results=self.search_hits)

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
    project_domains: Sequence[str] = (),
    workspace_accounts: Mapping[str, UUID] = {},
    settings: Settings | None = None,
    clock: Callable[[], datetime] | None = None,
    account_writes_fail_on: frozenset[str] = frozenset(),
) -> tuple[Arv2DiscoveryWorkHandler, _ConnFactory, _Writer, _DrainRecorder, _Accounts]:
    conn_factory = _ConnFactory(project_domains, workspace_accounts)
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

    # One search unless a scenario says otherwise: most scenarios are about what ONE webset does,
    # and a run short of its target would otherwise buy top-up rounds of the same brief. The
    # rounds themselves are the subject of the scenarios that set ``arv2_discovery_max_topups``.
    handler = Arv2DiscoveryWorkHandler(
        settings=settings or Settings(_env_file=None, arv2_discovery_max_topups=0),
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
        store,
        exa=exa,
        websets=websets,
        monkeypatch=monkeypatch,
        # Cap 1: this test's subject is the serial contract, not the pool — the order it pins is
        # the document order. Under the shipped cap of 4 the candidates verify concurrently and
        # the order below would be decided by which thread finished first.
        settings=Settings(
            _env_file=None, arv2_discovery_verify_concurrency=1, arv2_discovery_max_topups=0
        ),
    )

    result = asyncio.run(handler.handle(_context(run.run_id)))

    assert handler.kind is FleetTaskKind.ARV2_DISCOVERY
    assert result.outcome == "completed"
    assert result.references == {"run_id": str(run.run_id)}

    # The first search asked Exa for exactly the number the human wanted (ruling 2026-09-28).
    assert websets.named("find") == [{"external_id": f"arv2-discovery:{run.run_id}:1"}]
    created = websets.named("create")[0]
    assert created["count"] == 20
    assert created["criteria"] == (GEOGRAPHY_RULE, STAGE_RULE, BUYER_SENTENCE)
    assert created["external_id"] == f"arv2-discovery:{run.run_id}:1"
    assert created["exclude_webset_ids"] == ()
    assert created["recall"] is True
    # The search row was written before the webset was bought, then given its webset.
    order = [name for name, _ in store.events]
    assert order.index("create_search") < order.index("record_search_webset")
    assert store.named("create_search")[0]["row"].asked == 20
    assert store.named("record_search_webset")[0]["webset_id"] == "ws-1"
    assert store.named("finish_search")[0]["found"] == 2
    # This scenario allows no top-up round: one search, one webset.
    assert len(websets.named("create")) == 1
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
    assert receipt["asked"] == 20
    assert receipt["recall_estimate"] == 180
    assert receipt["shown"] == 2
    assert receipt["target_count"] == 20
    assert receipt["criteria"] == [GEOGRAPHY_RULE, STAGE_RULE, BUYER_SENTENCE]
    searches = [(row["kind"], row["asked"], row["found"]) for row in receipt["searches"]]
    assert searches == [("round", 20, 2)]
    assert receipt["source"] == "websets"
    assert receipt["end_reason"] == "round_cap"
    assert receipt["guards"] == {"ok": 8}
    assert receipt["duplicates"] == 0
    assert receipt["found_before"] == 0
    assert receipt["from_other_projects"] == 0
    assert receipt["unresolvable_domain"] == 0
    # Every hop's money landed under this run's own stamp.
    assert receipt["cost_usd"] == str(drain.cost_usd * len(drain.stamps))
    assert {stamp.job_id for stamp in drain.stamps} == {run.run_id}
    assert {stamp.project_id for stamp in drain.stamps} == {PROJECT}


def test_a_company_already_in_this_project_is_a_duplicate_with_no_spend(
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
        # This project already holds the *verified* domain, which the long list did not give.
        project_domains=["probook.ai"],
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


def test_a_company_an_earlier_discovery_of_the_project_found_is_found_before_and_not_re_verified(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Even when the human has since removed it from the project: discovery never brings back a
    company the project's own discoveries already found (ruling 2026-09-28)."""
    run = _run_row()
    store = _Store(run, found_before=frozenset({"probook.ai"}))
    exa = _FakeExa(
        _responder({"Probook": _company_answers("Probook", "probook.ai", {"geography": "pass"})})
    )
    websets = _FakeWebsets(items_results=[_items(_item("Probook", "https://probook.com"))])
    handler, _, writer, _, accounts = _handler(
        store, exa=exa, websets=websets, monkeypatch=monkeypatch
    )

    result = asyncio.run(handler.handle(_context(run.run_id)))

    assert result.outcome == "completed"
    assert store.named("project_found_domains")[0]["before_run_id"] == run.run_id
    assert exa.gate_queries() == []
    candidate = store.named("upsert_candidate")[0]["row"]
    assert candidate.disposition == "found_before"
    assert accounts.created == []
    assert writer.drafts == []
    assert store.named("finish_discovery_run")[0]["receipt"]["found_before"] == 1


def test_an_account_of_another_project_is_verified_against_this_icp_and_joins_this_project(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Founder ruling 2026-09-28: a company the workspace already has in ANOTHER project is checked
    against this project's gates and added here on its own account row — never a second account."""
    run = _run_row()
    store = _Store(run)
    passes = {"geography": "pass", "stage": "pass", "hiring": "pass", "intent": "pass"}
    exa = _FakeExa(_responder({"Probook": _company_answers("Probook", "probook.ai", passes)}))
    websets = _FakeWebsets(items_results=[_items(_item("Probook", "https://probook.com"))])
    existing = uuid4()
    handler, _, writer, _, accounts = _handler(
        store,
        exa=exa,
        websets=websets,
        monkeypatch=monkeypatch,
        workspace_accounts={"probook.ai": existing},
    )

    result = asyncio.run(handler.handle(_context(run.run_id)))

    assert result.outcome == "completed"
    assert len(exa.gate_queries()) == 4
    assert accounts.created == []
    verdict = store.named("record_verdicts")[0]
    assert verdict["account_entity_id"] == existing
    assert verdict["disposition"] == "pass"
    memberships = handler.memberships  # type: ignore[attr-defined]
    assert memberships.added == [(WORKSPACE, PROJECT, (str(existing),), "discovered")]
    fit = writer.by_field("account.scoring.fit")[0]
    assert str(fit.entity_id) == str(existing)
    receipt = store.named("finish_discovery_run")[0]["receipt"]
    assert receipt["from_other_projects"] == 1
    assert receipt["shown"] == 1


_ALL_PASS = {"geography": "pass", "stage": "pass", "hiring": "pass", "intent": "pass"}


def test_a_short_run_asks_again_with_the_same_brief_for_the_shortfall(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Round 1 found 3 for a target of 3, but one was a company this project already has. Round 2
    asks the SAME brief — the same query and criteria — for the one missing, skipping round 1's
    webset; once the run holds its number it buys nothing more (spec 2026-09-30 §4)."""
    run = _run_row(target_count=3)
    store = _Store(run)
    exa = _FakeExa(
        _responder(
            {
                "Probook": _company_answers("Probook", "probook.ai", _ALL_PASS),
                "Patientdesk": _company_answers("Patientdesk", "patientdesk.com", _ALL_PASS),
                "Globex": _company_answers("Globex", "globex.com", _ALL_PASS),
                "Initech": _company_answers("Initech", "initech.com", _ALL_PASS),
            }
        )
    )
    websets = _FakeWebsets(
        websets={
            "ws-1": (
                [_view(webset_id="ws-1")],
                [
                    _items(
                        _item("Probook", "https://probook.com"),
                        _item("Patientdesk", "https://patientdesk.com"),
                        _item("Globex", "https://globex.com"),
                    )
                ],
            ),
            "ws-2": (
                [_view(webset_id="ws-2", searches=(_search("srch-2", found=1),))],
                [_items(_item("Initech", "https://initech.com", search_id="srch-2"))],
            ),
        }
    )
    handler, _, _, _, _ = _handler(
        store,
        exa=exa,
        websets=websets,
        monkeypatch=monkeypatch,
        project_domains=["globex.com"],
        settings=Settings(_env_file=None, arv2_discovery_max_topups=3),
    )

    result = asyncio.run(handler.handle(_context(run.run_id)))

    assert result.outcome == "completed"
    first, topup = websets.named("create")
    assert first["count"] == 3
    assert topup["count"] == 1
    assert (topup["query"], topup["criteria"]) == (first["query"], first["criteria"])
    assert topup["criteria"] == (GEOGRAPHY_RULE, STAGE_RULE, BUYER_SENTENCE)
    assert topup["exclude_webset_ids"] == ("ws-1",)
    assert [call["row"].kind for call in store.named("create_search")] == ["round", "round"]
    finished = store.named("finish_discovery_run")[0]
    assert finished["receipt"]["shown"] == 3
    assert finished["receipt"]["duplicates"] == 1
    assert finished["found_strict"] == 4
    assert finished["found_relaxed"] == 0
    ended = store.named("end_discovery_run")[0]
    assert (ended["status"], ended["end_reason"]) == ("completed", "filled")


def test_a_run_holding_its_number_after_the_first_search_buys_nothing_more(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    run = _run_row(target_count=1)
    store = _Store(run)
    exa = _FakeExa(_responder({"Probook": _company_answers("Probook", "probook.ai", _ALL_PASS)}))
    websets = _FakeWebsets(items_results=[_items(_item("Probook", "https://probook.com"))])
    handler, _, _, _, _ = _handler(
        store,
        exa=exa,
        websets=websets,
        monkeypatch=monkeypatch,
        settings=Settings(_env_file=None, arv2_discovery_max_topups=3),
    )

    asyncio.run(handler.handle(_context(run.run_id)))

    assert [call["count"] for call in websets.named("create")] == [1]
    assert store.named("finish_discovery_run")[0]["receipt"]["shown"] == 1
    assert store.named("end_discovery_run")[0]["end_reason"] == "filled"


def test_find_more_skips_every_webset_the_projects_earlier_discoveries_bought(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Ruling 2026-09-28: a new ask is a new run, and it never finds (or pays for) a company this
    project's earlier discoveries found — Exa is told to skip their websets outright."""
    run = _run_row(target_count=2)
    store = _Store(run, prior_websets=("ws-old-1", "ws-old-2"))
    exa = _FakeExa(_responder({"Probook": _company_answers("Probook", "probook.ai", _ALL_PASS)}))
    websets = _FakeWebsets(items_results=[_items(_item("Probook", "https://probook.com"))])
    handler, _, _, _, _ = _handler(store, exa=exa, websets=websets, monkeypatch=monkeypatch)

    asyncio.run(handler.handle(_context(run.run_id)))

    assert websets.named("create")[0]["exclude_webset_ids"] == ("ws-old-1", "ws-old-2")
    assert store.named("create_search")[0]["row"].exclude_webset_ids == ("ws-old-1", "ws-old-2")


def test_a_search_recorded_before_its_create_answered_is_found_by_external_id_not_bought_again(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An attempt died between asking Exa for the webset and recording its id. The next attempt
    looks it up by the external id it sent and reads it — the webset is never bought twice."""
    run = _run_row()
    recorded = SearchRow(
        run_id=run.run_id,
        ordinal=1,
        kind="strict",
        external_id=f"arv2-discovery:{run.run_id}:1",
        asked=20,
        criteria=(GEOGRAPHY_RULE, STAGE_RULE, BUYER_SENTENCE),
    )
    store = _Store(run, searches=[recorded])
    exa = _FakeExa(_responder({"Probook": _company_answers("Probook", "probook.ai", _ALL_PASS)}))
    websets = _FakeWebsets(
        items_results=[_items(_item("Probook", "https://probook.com"))],
        found={recorded.external_id: _view(status="running")},
    )
    handler, _, _, _, _ = _handler(store, exa=exa, websets=websets, monkeypatch=monkeypatch)

    result = asyncio.run(handler.handle(_context(run.run_id)))

    assert result.outcome == "completed"
    assert websets.named("create") == []
    assert store.named("create_search") == []
    assert store.named("record_search_webset")[0]["webset_id"] == "ws-1"
    assert store.named("finish_discovery_run")[0]["receipt"]["shown"] == 1


def test_a_refused_websets_call_lands_the_run_needs_review_under_its_own_name(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The old widening search was refused with a 400 on every run and read as "found nobody".
    A refusal now ends the run by name."""
    run = _run_row()
    store = _Store(run)
    exa = _FakeExa(_responder({}))
    refused = replace(_view(), error="http 400: exclude.0.source: Invalid option")
    websets = _FakeWebsets(create_view=refused)
    handler, *_ = _handler(store, exa=exa, websets=websets, monkeypatch=monkeypatch)

    result = asyncio.run(handler.handle(_context(run.run_id)))

    assert result.outcome == "needs_review"
    finished = store.named("finish_discovery_run")[0]
    assert finished["receipt"]["failure"] == "websets_request_refused"
    assert "Invalid option" in finished["receipt"]["message"]


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
        settings=Settings(_env_file=None, arv2_discovery_wall_s=60, arv2_discovery_max_topups=0),
        clock=_clock(step_s=45.0),
    )

    result = asyncio.run(handler.handle(_context(run.run_id)))

    assert result.outcome == "needs_review"
    # Behaviour change 2026-09-12: every tick lists the webset, so a run that never reaches idle
    # DOES read it — but this webset holds no rows, so the wall clock still costs nothing. What
    # the assertion keeps is the money, not the call: not one row was billed.
    assert all(read.priced_item_ids == () for read in websets.returned_items)
    finished = store.named("finish_discovery_run")[0]
    assert finished["status"] == "needs_review"
    assert finished["receipt"]["failure"] == "webset_wall_exceeded"


def test_a_run_out_of_time_cancels_its_webset_and_prices_what_exa_had_found(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Exa bills a company when it finds it, the ledger when the run reads it. A webset left
    running after the run gave up would go on finding — and billing — companies nobody reads."""
    run = _run_row()
    store = _Store(run)
    exa = _FakeExa(_responder({}))
    websets = _FakeWebsets(
        get_views=[_view(status="running")],
        items_after_cancel=_items(
            _item("Acme", "https://acme.com"), _item("Globex", "https://globex.com")
        ),
    )
    handler, _, _, _, _ = _handler(
        store,
        exa=exa,
        websets=websets,
        monkeypatch=monkeypatch,
        settings=Settings(_env_file=None, arv2_discovery_wall_s=60, arv2_discovery_max_topups=0),
        clock=_clock(step_s=45.0),
    )

    asyncio.run(handler.handle(_context(run.run_id)))

    assert websets.named("cancel") == [{"webset_id": "ws-1"}]
    order = [name for name, _ in websets.calls]
    assert order[-2:] == ["cancel", "items"]
    # The read after the cancel is the one that put both rows on the ledger.
    assert websets.returned_items[-1].priced_item_ids == ("itm-acme", "itm-globex")
    finished = store.named("finish_discovery_run")[0]
    assert finished["receipt"]["failure"] == "webset_wall_exceeded"
    assert finished["receipt"]["webset_stopped"] is True
    assert finished["receipt"]["rows_priced_at_stop"] == 2
    assert finished["found_strict"] == 2
    # Found and paid for, never verified: no gate was asked about either company.
    assert exa.gate_queries() == []


def test_a_halt_while_the_webset_is_still_running_cancels_it_before_the_run_lands(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Run ``ee79d837``: Exa Answer ran out of credit after 7 companies and the webset went on to
    find all 35. The halt now stops the webset, and the rows found after it reach the ledger."""
    run = _run_row()
    store = _Store(run)

    def out_of_credit(query: str) -> ExaAnswerResult:
        raise ProviderHalted("exa", "payment_required", http_status=402)

    exa = _FakeExa(out_of_credit)
    acme = _item("Acme", "https://acme.com")
    websets = _FakeWebsets(
        get_views=[_view(status="running")],
        items_results=[_items(acme)],
        items_after_cancel=_items(
            acme, _item("Globex", "https://globex.com"), _item("Initech", "https://initech.com")
        ),
    )
    handler, *_ = _handler(store, exa=exa, websets=websets, monkeypatch=monkeypatch)
    drain = _WatchingDrain(events=store.events)
    monkeypatch.setattr(driver, "drain_provider_calls", drain)

    result = asyncio.run(handler.handle(_context(run.run_id)))

    assert result.outcome == "needs_review"
    assert len(websets.named("cancel")) == 1
    finished = store.named("finish_discovery_run")[0]
    assert finished["receipt"]["failure"] == "provider_halted"
    assert finished["receipt"]["webset_stopped"] is True
    # Acme was priced on the first read; Globex and Initech only by the read after the cancel.
    assert finished["receipt"]["rows_priced_at_stop"] == 2
    assert finished["found_strict"] == 3
    # Every drain, the cancel and the last read included, lands before the receipt does.
    order = [name for name, _ in store.events]
    assert order.index("finish_discovery_run") > max(
        index for index, name in enumerate(order) if name == "drain"
    )


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
    # (The first hop is the free lookup by external id that precedes every create.)
    assert [name for name, _ in websets.calls] == ["find", "create"]
    assert len(drain.stamps) == 2


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
        # Discovery is on by default since 2026-10-04, so the flag-off case says so explicitly.
        build_arv2_discovery_handler(
            Settings(_env_file=None, arv2_discovery_enabled=False),
            keyless,
            storage=object(),
            artifacts=SimpleNamespace(),
        )
        is None
    )
    assert (
        build_arv2_discovery_handler(
            settings, keyless, storage=object(), artifacts=SimpleNamespace()
        )
        is None
    )


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

    The run's search row carries the webset it paid for, so the redelivered task polls and reads
    *that* webset and verifies only the companies its earlier attempt never finished.
    """
    run = _run_row(asked=20, recall_estimate=180, relaxed_enabled=False)
    bought = SearchRow(
        run_id=run.run_id,
        ordinal=1,
        kind="strict",
        external_id=f"arv2-discovery:{run.run_id}:1",
        asked=20,
        criteria=(GEOGRAPHY_RULE, STAGE_RULE, BUYER_SENTENCE),
        webset_id="ws-1",
    )
    store = _Store(
        run,
        candidates=[_verified_candidate(run, "Probook", "probook.ai", "https://probook.com")],
        searches=[bought],
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
    # Not one cent of a second long list: no lookup, no create, the recorded webset is read.
    assert websets.named("find") == []
    assert websets.named("create") == []
    assert store.named("create_search") == []
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
        # Cap 1: this test's subject is the serial contract, not the pool — the order it pins is
        # the document order. Under the shipped cap of 4 the three candidates verify concurrently
        # and the order below would be decided by which thread finished first.
        settings=Settings(
            _env_file=None, arv2_discovery_verify_concurrency=1, arv2_discovery_max_topups=0
        ),
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


def test_a_webset_row_is_priced_once_per_run_across_polls(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Every poll re-reads the WHOLE webset; a row already paid for is not billed again (I4).

    Without the already-priced set every row lands on ``provider_call_ledger`` — and in
    ``receipt.cost_usd`` — once per poll. §8's exit gate divides by that number.
    """
    run = _run_row(target_count=3)
    store = _Store(run)
    exa = _FakeExa(
        _responder(
            {
                "Probook": _company_answers("Probook", "probook.ai", _ALL_PASS),
                "Patientdesk": _company_answers("Patientdesk", "patientdesk.com", _ALL_PASS),
            }
        )
    )
    websets = _two_tick_websets(
        _item("Probook", "https://probook.com"), _item("Patientdesk", "https://patientdesk.com")
    )
    handler, _, _, _, _ = _handler(store, exa=exa, websets=websets, monkeypatch=monkeypatch)

    result = asyncio.run(handler.handle(_context(run.run_id)))

    assert result.outcome == "completed"
    reads = websets.named("items")
    # The first read pays for nothing before it; the second names the row it already paid.
    assert [call["priced_item_ids"] for call in reads] == [
        frozenset(),
        frozenset({"itm-probook"}),
    ]
    first, second = websets.returned_items
    assert first.priced_item_ids == ("itm-probook",)
    assert first.cost_usd == ITEM_COST
    assert [item.name for item in second.items] == ["Probook", "Patientdesk"]
    assert second.priced_item_ids == ("itm-patientdesk",)
    assert second.cost_usd == ITEM_COST  # one row, not two — the first row is not re-billed
    assert store.named("finish_discovery_run")[0]["receipt"]["credits_priced_once"] is True


def test_a_resumed_run_does_not_re_price_the_rows_an_earlier_attempt_already_paid_for(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The other half of I4: a plain resume re-reads the same webset and must not re-bill it.

    The item ids come off the candidate rows the earlier attempt wrote — the raw Websets record is
    kept whole on each snapshot — so "already paid for" survives a worker restart.
    """
    run = _run_row(asked=20, recall_estimate=180, relaxed_enabled=False)
    bought = SearchRow(
        run_id=run.run_id,
        ordinal=1,
        kind="strict",
        external_id=f"arv2-discovery:{run.run_id}:1",
        asked=20,
        criteria=(GEOGRAPHY_RULE, STAGE_RULE, BUYER_SENTENCE),
        webset_id="ws-1",
    )
    already = _verified_candidate(run, "Probook", "probook.ai", "https://probook.com")
    store = _Store(
        run,
        candidates=[
            replace(
                already,
                provider_snapshot={**already.provider_snapshot, "item": {"id": "itm-probook"}},
            )
        ],
        searches=[bought],
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


class _CountingExa(_FakeExa):
    """``answer`` that measures how many calls overlap — the pool's observable.

    ``_hop`` runs the provider call on a worker thread, so the hold below is a real overlap
    window: with one cap of N, at most N of these can be inside ``answer`` at once.
    """

    def __init__(self, respond: Callable[[str], ExaAnswerResult], *, hold_s: float = 0.05) -> None:
        super().__init__(respond)
        self._lock = threading.Lock()
        self._in_flight = 0
        self.max_in_flight = 0
        self._hold_s = hold_s

    def answer(self, query: str, **kwargs: Any) -> ExaAnswerResult:
        with self._lock:
            self._in_flight += 1
            self.max_in_flight = max(self.max_in_flight, self._in_flight)
        try:
            time.sleep(self._hold_s)
            return super().answer(query, **kwargs)
        finally:
            with self._lock:
                self._in_flight -= 1


def _one_company_run_under_cap(
    monkeypatch: pytest.MonkeyPatch, *, concurrency: int
) -> tuple[_CountingExa, _Store]:
    """A strict pass over one all-pass company, driven to completion under a named hop cap."""
    run = _run_row(criteria_gate_keys=("geography", "stage"))
    store = _Store(run)
    exa = _CountingExa(
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
        get_views=[_view()],
        items_results=[_items(_item("Acme", "https://acme.com"))],
    )
    handler, *_ = _handler(
        store,
        exa=exa,
        websets=websets,
        monkeypatch=monkeypatch,
        settings=Settings(
            _env_file=None,
            arv2_discovery_verify_concurrency=concurrency,
            arv2_discovery_max_topups=0,
        ),
    )
    asyncio.run(handler.handle(_context(run.run_id)))
    return exa, store


def test_a_candidates_gates_are_asked_together_under_the_cap(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    exa, store = _one_company_run_under_cap(monkeypatch, concurrency=4)
    # Four gates, one website ask; the gates overlapped (the website ask ran alone, first).
    assert len(exa.gate_queries()) == 4
    assert exa.max_in_flight >= 2
    landed = store.named("finish_discovery_run")[0]
    assert landed["status"] == "completed"


def test_a_cap_of_one_keeps_the_serial_order(monkeypatch: pytest.MonkeyPatch) -> None:
    exa, _store = _one_company_run_under_cap(monkeypatch, concurrency=1)
    assert exa.max_in_flight == 1
    # Website first, then the gates in the ICP document's own order (``ICP_FRONT["hard_gates"]``,
    # which ``compile_brief`` keeps as written) — the R4 DB proof's positional script.
    assert "registrable domain" in exa.queries[0]
    assert [_RULES[key] for key in ("geography", "stage", "hiring", "intent")] == [
        next(rule for rule in _RULES.values() if rule in query) for query in exa.gate_queries()
    ]


class _WatchingDrain(_DrainRecorder):
    """A drain that also says WHEN it ran: whether the wire call had already returned, and where
    it falls in the store's own event order."""

    def __init__(
        self,
        finished: threading.Event | None = None,
        events: list[tuple[str, dict[str, Any]]] | None = None,
    ) -> None:
        super().__init__()
        self._finished = finished
        self._events = events
        #: ``True`` for each drain that ran after the provider call's thread had returned.
        self.after_the_call: list[bool] = []

    async def __call__(self, conn: Any, **kwargs: Any) -> DrainReport:
        if self._finished is not None:
            self.after_the_call.append(self._finished.is_set())
        if self._events is not None:
            self._events.append(("drain", {}))
        return await super().__call__(conn, **kwargs)


def test_a_cancelled_hop_still_lands_the_money_trail_of_the_call_it_bought(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Ruling R8: a thread cannot be interrupted, so a cancelled hop waits for the call it already
    put on the wire before draining. Without the wait the drain lands an empty trail and the run's
    receipt under-reports money that was genuinely spent."""
    run = _run_row()
    store = _Store(run)
    handler, _, _, _, _ = _handler(
        store, exa=_FakeExa(_responder({})), websets=_FakeWebsets(), monkeypatch=monkeypatch
    )
    returned = threading.Event()
    drain = _WatchingDrain(finished=returned)
    monkeypatch.setattr(driver, "drain_provider_calls", drain)

    def on_the_wire(caller: Any) -> str:
        del caller
        time.sleep(0.05)
        returned.set()
        return "bought"

    async def cancel_it_mid_call() -> None:
        # ``_hop`` is what is under test, so it is driven directly; ``_compose`` builds the
        # real state it needs (run, brief, semaphore) through the same fakes.
        state = await handler._compose(run)
        hop = asyncio.create_task(handler._hop(state, on_the_wire))
        await asyncio.sleep(0.01)
        hop.cancel()
        with pytest.raises(asyncio.CancelledError):
            await hop

    asyncio.run(cancel_it_mid_call())

    # Drained exactly once, and only after the call it was buying had actually come back.
    assert drain.after_the_call == [True]
    assert len(drain.stamps) == 1


class _HaltingExa(_CountingExa):
    """Exa refuses the stage gate at once while every other ask is slow — so the halt arrives with
    its sibling gates still on the wire, which is the case ruling R8 exists for."""

    def answer(self, query: str, **kwargs: Any) -> ExaAnswerResult:
        if STAGE_RULE in query:
            self.queries.append(query)
            raise ProviderHalted("exa", "rate_limited", http_status=429)
        return super().answer(query, **kwargs)


def test_a_halt_on_one_gate_drains_its_siblings_before_the_run_lands(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Ruling R8: the failing gate's siblings are cancelled AND awaited before the halt leaves the
    verifier, so every Answer call that reached the wire is on the ledger before the receipt is
    written. Letting them run on would land the run first and add their cost to it afterwards."""
    run = _run_row(criteria_gate_keys=("geography", "stage"))
    store = _Store(run)
    exa = _HaltingExa(
        _responder(
            {
                "Acme": _company_answers(
                    "Acme",
                    "acme.com",
                    {"geography": "pass", "stage": "pass", "hiring": "pass", "intent": "pass"},
                )
            }
        ),
        hold_s=0.15,
    )
    websets = _FakeWebsets(
        get_views=[_view()],
        items_results=[_items(_item("Acme", "https://acme.com"))],
    )
    handler, *_ = _handler(
        store,
        exa=exa,
        websets=websets,
        monkeypatch=monkeypatch,
        settings=Settings(
            _env_file=None, arv2_discovery_verify_concurrency=4, arv2_discovery_max_topups=0
        ),
    )
    drain = _WatchingDrain(events=store.events)
    monkeypatch.setattr(driver, "drain_provider_calls", drain)

    result = asyncio.run(handler.handle(_context(run.run_id)))

    assert result.outcome == "needs_review"
    finished = store.named("finish_discovery_run")[0]
    assert finished["status"] == "needs_review"
    assert finished["receipt"]["failure"] == "provider_halted"
    assert "rate_limited" in finished["receipt"]["message"]
    # The website ask plus all four gates reached the wire, and every provider call this run made
    # — those five, plus the webset's create/poll/read — drained.
    assert len(exa.queries) == 5
    assert len(drain.stamps) == len(websets.calls) + len(exa.queries)
    # The webset had already gone idle and its last read priced every row: nothing to cancel.
    assert websets.named("cancel") == []
    assert finished["receipt"]["webset_stopped"] is False
    # And every drain is recorded before the run is landed — no money arrives after the receipt.
    order = [name for name, _ in store.events]
    assert order.index("finish_discovery_run") > max(
        index for index, name in enumerate(order) if name == "drain"
    )


# --- verify as items arrive: the watch loop and the pool (spec 2026-09-12 §2) ------------------


def _two_tick_websets(first: WebsetItem, second: WebsetItem) -> _FakeWebsets:
    """Tick 1: running, one item listed. Tick 2: idle, both items listed (the first re-listed)."""
    return _FakeWebsets(
        get_views=[_view(status="running"), _view(status="idle")],
        items_results=[_items(first), _items(first, second)],
    )


def _all_pass(company: str, domain: str) -> dict[str, ExaAnswerResult]:
    return _company_answers(
        company, domain, {"geography": "pass", "stage": "pass", "hiring": "pass", "intent": "pass"}
    )


def test_items_verify_as_they_arrive_and_a_relisted_item_is_never_verified_twice(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The run does not wait for ``idle`` to start buying: every tick lists and dispatches.

    The webset is listed on the running tick AND on the idle one, and the item both lists carry is
    claimed at dispatch — so it is verified exactly once, and the run row's counters climb while
    the search is still going rather than all at once at the end.
    """
    run = _run_row(criteria_gate_keys=("geography", "stage"))
    store = _Store(run)
    exa = _FakeExa(
        _responder({"Acme": _all_pass("Acme", "acme.com"), "Bolt": _all_pass("Bolt", "bolt.com")})
    )
    acme, bolt = _item("Acme", "https://acme.com"), _item("Bolt", "https://bolt.com")
    websets = _two_tick_websets(acme, bolt)
    handler, _conn, _writer, _drain, accounts = _handler(
        store, exa=exa, websets=websets, monkeypatch=monkeypatch
    )

    asyncio.run(handler.handle(_context(run.run_id)))

    # Items were read on BOTH ticks (the running one and the idle one), not only after idle.
    assert [call for call, _ in websets.calls] == [
        "find",
        "create",
        "get",
        "items",
        "get",
        "items",
    ]
    # Acme was verified once although it was listed twice; Bolt once.
    assert [w["primary_domain"] for w in accounts.created] == ["acme.com", "bolt.com"]
    assert len(store.named("record_verdicts")) == 2
    # And it was claimed at DISPATCH, so the re-listed row cost nothing: two companies, each one
    # website ask plus one answer per gate, and not an eleventh answer for the repeat.
    assert len(exa.queries) == 10
    # Progress was recorded on every tick, before the run landed.
    progress = store.named("record_discovery_progress")
    assert [p["found_strict"] for p in progress] == [1, 2]
    landed = store.named("finish_discovery_run")[0]
    assert (landed["found_strict"], landed["status"]) == (2, "completed")


def test_two_long_list_rows_that_verify_to_one_company_are_one_account_and_one_gate_set(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """R4(c): the cross-item guard, the one claiming rule the long list cannot enforce.

    Two websets rows with *different* registrable domains (``acme-corp.com``, ``acme-inc.com``)
    both turn out to be ``acme.com`` once their own websites are asked. Dispatch cannot know that,
    so both are claimed and both buy their website ask; the post-``_verify_website`` check is what
    stops the second from buying a full gate set and then colliding on the account strong key.

    Either row may win the race under the default cap, so the assertions are about the *company*,
    not about which row got there: one account, one set of verdicts, and six Answer calls — two
    website asks and exactly one gate set.
    """
    run = _run_row()
    store = _Store(run)
    # Both companies are scripted all-pass to the SAME domain: whichever task wins the claim, the
    # gates it then buys are answerable, and the loser's website ask is the last thing it buys.
    exa = _FakeExa(
        _responder(
            {
                "Acme Corp": _all_pass("Acme Corp", "acme.com"),
                "Acme Inc": _all_pass("Acme Inc", "acme.com"),
            }
        )
    )
    websets = _FakeWebsets(
        get_views=[_view()],
        items_results=[
            _items(
                _item("Acme Corp", "https://acme-corp.com"),
                _item("Acme Inc", "https://acme-inc.com"),
            )
        ],
    )
    handler, *_rest, accounts = _handler(store, exa=exa, websets=websets, monkeypatch=monkeypatch)

    result = asyncio.run(handler.handle(_context(run.run_id)))

    # One company, so one account and one set of verdicts — never two rows racing the strong key.
    assert [created["primary_domain"] for created in accounts.created] == ["acme.com"]
    assert len(store.named("record_verdicts")) == 1
    # The second row bought its website ask and nothing more: 1 website + 4 gates + 1 website.
    assert len(exa.queries) == 6
    assert len(exa.gate_queries()) == 4
    # And the run lands normally: a row that turns out to be a company already taken is not a
    # failure, it is a row with nothing left to buy.
    assert result.outcome == "completed"
    assert store.named("finish_discovery_run")[0]["status"] == "completed"


def test_the_pool_never_exceeds_the_cap(monkeypatch: pytest.MonkeyPatch) -> None:
    """Five companies verify at once, and the one semaphore still bounds every Answer call."""
    run = _run_row(criteria_gate_keys=("geography", "stage"))
    store = _Store(run)
    names = ["Acme", "Bolt", "Cove", "Dune", "Echo"]
    exa = _CountingExa(
        _responder({n: _all_pass(n, f"{n.lower()}.com") for n in names}), hold_s=0.02
    )
    websets = _FakeWebsets(
        get_views=[_view()],
        items_results=[_items(*(_item(n, f"https://{n.lower()}.com") for n in names))],
    )
    handler, *_ = _handler(
        store,
        exa=exa,
        websets=websets,
        monkeypatch=monkeypatch,
        settings=Settings(
            _env_file=None, arv2_discovery_verify_concurrency=2, arv2_discovery_max_topups=0
        ),
    )

    asyncio.run(handler.handle(_context(run.run_id)))

    assert exa.max_in_flight == 2
    assert len(store.named("record_verdicts")) == 5


def test_a_provider_halt_in_one_task_suspends_the_whole_pool(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Containment is per candidate, but a halted provider is the run's: it leaves the pool."""
    run = _run_row(criteria_gate_keys=("geography", "stage"))
    store = _Store(run)

    def respond(query: str) -> ExaAnswerResult:
        if "Bolt" in query:
            raise ProviderHalted("exa", "rate_limited", http_status=429)
        return _responder({"Acme": _all_pass("Acme", "acme.com")})(query)

    exa = _FakeExa(respond)
    websets = _FakeWebsets(
        get_views=[_view()],
        items_results=[
            _items(_item("Acme", "https://acme.com"), _item("Bolt", "https://bolt.com"))
        ],
    )
    handler, *_ = _handler(store, exa=exa, websets=websets, monkeypatch=monkeypatch)

    result = asyncio.run(handler.handle(_context(run.run_id)))

    landed = store.named("finish_discovery_run")[0]
    assert landed["status"] == "needs_review"
    assert landed["receipt"]["failure"] == "provider_halted"
    assert result.outcome == "needs_review"


class _SlowListing(_FakeWebsets):
    """Lists the webset slowly, so the tasks the PREVIOUS tick dispatched have finished by the
    time this tick reaps them — which is how ``_reap``, not ``_drain_pool``, sees their failures."""

    def items(
        self, webset_id: str, *, priced_item_ids: frozenset[str] = frozenset()
    ) -> WebsetItemsResult:
        time.sleep(0.2)
        return super().items(webset_id, priced_item_ids=priced_item_ids)


def test_reap_retrieves_every_finished_tasks_failure_before_it_raises_the_first() -> None:
    """Two candidates halting in the same tick is two exceptions, and ``_reap`` raises one of them.

    It must still READ the other off its task: an exception nobody retrieved makes asyncio log
    "Task exception was never retrieved" when the task is collected — noise in a run whose real
    story (the provider refused to sell) is already on the receipt.
    """

    async def halt() -> None:
        raise ProviderHalted("exa", "rate_limited", http_status=429)

    async def drive() -> None:
        tasks = {asyncio.create_task(halt()) for _ in range(2)}
        await asyncio.wait(tasks)
        reaped = set(tasks)
        with pytest.raises(ProviderHalted):
            await Arv2DiscoveryWorkHandler._reap(tasks)
        # Both failures were read off their tasks, so neither is left to be logged at collection.
        assert [task._log_traceback for task in reaped] == [False, False]
        # And a reaped task leaves the pool, so nothing waits for it again.
        assert tasks == set()

    asyncio.run(drive())


def test_two_candidates_halting_on_the_same_tick_land_the_run_needs_review(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The whole-run shape of the case above: both website asks halt while the webset is still
    running, so the failures are surfaced by ``_reap`` on the next tick rather than by the final
    ``_drain_pool``, and the run still lands ``needs_review`` naming the provider."""
    run = _run_row(criteria_gate_keys=("geography", "stage"))
    store = _Store(run)

    def halt(query: str) -> ExaAnswerResult:
        del query
        raise ProviderHalted("exa", "rate_limited", http_status=429)

    acme, bolt = _item("Acme", "https://acme.com"), _item("Bolt", "https://bolt.com")
    websets = _SlowListing(
        get_views=[_view(status="running"), _view(status="running"), _view(status="idle")],
        items_results=[_items(acme, bolt), _items(acme, bolt)],
    )
    handler, *_ = _handler(store, exa=_FakeExa(halt), websets=websets, monkeypatch=monkeypatch)

    result = asyncio.run(handler.handle(_context(run.run_id)))

    assert result.outcome == "needs_review"
    landed = store.named("finish_discovery_run")[0]
    assert landed["status"] == "needs_review"
    assert landed["receipt"]["failure"] == "provider_halted"
    # Both website asks reached the wire before either failure left the pool.
    assert len(store.named("record_verdicts")) == 0


# -- the agent's brief: roles, rounds, stop, the summary and the end block (spec 2026-09-30) -----


def test_the_summary_message_matches_the_spec_shape() -> None:
    """Spec §6.3, for one fixed summary: the text the wake turn hands the Head of ABM."""
    run_id = UUID("11111111-2222-3333-4444-555555555555")
    summary = {
        "asked": 20,
        "added": 12,
        "excluded": 7,
        "unclear": 3,
        "excluded_by": [
            {"gate": "sells_product", "role": "must_not", "count": 5, "example": "Acme"},
            {"gate": "is_buyer", "role": "must", "count": 2, "example": "Globex"},
        ],
        "criteria_rates": [
            {"criterion": "The company runs clinics.", "rate": 83.39},
            {"criterion": "Unrated yet.", "rate": None},
            {"criterion": "It hires nurses.", "rate": 8.31},
        ],
        "searches": 4,
        "end_reason": "round_cap",
        "spend_usd": "3.456",
    }

    assert driver.summary_message(run_id, summary) == (
        "Discovery finished (run 11111111-2222-3333-4444-555555555555). Asked for 20, added 12, "
        "excluded 7, unclear 3.\n"
        "Ended: round cap (4 searches).\n"
        "Excluded by: sells_product (must_not) 5 — e.g. Acme; is_buyer (must) 2 — e.g. Globex.\n"
        'Criteria pass rates, last search: "The company runs clinics." 83%; '
        '"It hires nurses." 8%.\n'
        "Spend: $3.46."
    )


def test_a_summary_with_nothing_excluded_and_no_rates_leaves_those_lines_out() -> None:
    summary = {
        "asked": 5,
        "added": 5,
        "excluded": 0,
        "unclear": 0,
        "excluded_by": [],
        "criteria_rates": [],
        "searches": 1,
        "end_reason": "wall_clock",
        "spend_usd": "0.2",
    }

    assert driver.summary_message(UUID(int=1), summary).splitlines() == [
        f"Discovery finished (run {UUID(int=1)}). Asked for 5, added 5, excluded 0, unclear 0.",
        "Ended: wall clock.",
        "Spend: $0.20.",
    ]


def test_a_failed_must_and_a_passed_must_not_exclude_while_an_unclear_never_does(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Code applies the brief's roles: Acme fails its ``must`` (geography), Globex passes its
    ``must_not`` (intent), Initech is unclear on the ``must`` — and only Initech joins the project,
    with a fit over its ``must`` and ``prefer`` gates alone."""
    run = _run_row(target_count=5, brief=_brief_json(geography="must", intent="must_not"))
    store = _Store(run)
    exa = _FakeExa(
        _responder(
            {
                "Acme": _company_answers(
                    "Acme",
                    "acme.com",
                    {"geography": "fail", "stage": "pass", "hiring": "pass", "intent": "fail"},
                ),
                "Globex": _company_answers(
                    "Globex",
                    "globex.com",
                    {"geography": "pass", "stage": "pass", "hiring": "pass", "intent": "pass"},
                ),
                "Initech": _company_answers(
                    "Initech",
                    "initech.com",
                    {"geography": "unclear", "stage": "pass", "hiring": "fail", "intent": "fail"},
                ),
            }
        )
    )
    websets = _FakeWebsets(
        items_results=[
            _items(
                _item("Acme", "https://acme.com"),
                _item("Globex", "https://globex.com"),
                _item("Initech", "https://initech.com"),
            )
        ]
    )
    handler, _, writer, _, accounts = _handler(
        store, exa=exa, websets=websets, monkeypatch=monkeypatch
    )

    result = asyncio.run(handler.handle(_context(run.run_id)))

    assert result.outcome == "completed"
    recorded = {call["candidate_id"]: call for call in store.named("record_verdicts")}.values()
    by_disposition = sorted(
        (call["disposition"], call.get("excluded_by_gate"), call["fit"]) for call in recorded
    )
    assert by_disposition == [
        ("excluded", "geography", None),
        ("excluded", "intent", None),
        # Initech: unclear geography (½), stage pass (1), hiring fail (0) — intent is a must_not.
        ("partial", None, 0.5),
    ]
    excluded = [call for call in recorded if call["disposition"] == "excluded"]
    assert all(call["account_entity_id"] is None for call in excluded)
    assert all(len(call["verdicts"]) == 4 for call in excluded)
    assert [created["primary_domain"] for created in accounts.created] == ["initech.com"]
    assert [draft.value_json for draft in writer.by_field("account.scoring.fit")] == [
        {"value": 0.5}
    ]
    ended = store.named("end_discovery_run")[0]
    summary = ended["summary"]
    assert (summary["added"], summary["excluded"], summary["unclear"]) == (1, 2, 0)
    assert sorted(
        (entry["gate"], entry["role"], entry["count"], entry["example"])
        for entry in summary["excluded_by"]
    ) == [("geography", "must", 1, "Acme"), ("intent", "must_not", 1, "Globex")]
    assert finished_receipt(store)["excluded"] == {"geography": 1, "intent": 1}


def finished_receipt(store: _Store) -> dict[str, Any]:
    return store.named("finish_discovery_run")[0]["receipt"]


class _Wake:
    """A :class:`~clue_api.arv2.discovery_driver.DiscoveryWake` that records what it was handed."""

    def __init__(self, turn_id: UUID | None = None, error: Exception | None = None) -> None:
        self.turn_id = turn_id
        self.error = error
        self.queued: list[tuple[UUID, dict[str, Any], str]] = []

    async def queue(
        self, conn: Any, run: DiscoveryRunRow, summary: Mapping[str, Any], message: str
    ) -> UUID | None:
        del conn
        self.queued.append((run.run_id, dict(summary), message))
        if self.error is not None:
            raise self.error
        return self.turn_id


def _one_pass_run(
    monkeypatch: pytest.MonkeyPatch, run: DiscoveryRunRow, wake: _Wake | None
) -> tuple[_Store, Any]:
    store = _Store(run)
    exa = _FakeExa(_responder({"Probook": _company_answers("Probook", "probook.ai", _ALL_PASS)}))
    websets = _FakeWebsets(items_results=[_items(_item("Probook", "https://probook.com"))])
    handler, *_ = _handler(store, exa=exa, websets=websets, monkeypatch=monkeypatch)
    handler._wake = wake  # the constructor's seam, set after the shared harness built it
    return store, asyncio.run(handler.handle(_context(run.run_id)))


def test_a_threadless_run_is_released_as_it_ends_and_wakes_nobody(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    wake = _Wake(turn_id=uuid4())
    store, result = _one_pass_run(monkeypatch, _run_row(target_count=1), wake)

    assert result.outcome == "completed"
    assert wake.queued == []
    (ended,) = store.named("end_discovery_run")
    assert (ended["status"], ended["end_reason"], ended["release"]) == ("completed", "filled", True)
    assert store.named("record_wake_turn") == []


def test_a_threaded_run_hands_its_summary_to_the_wake_and_stays_held(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    turn_id = uuid4()
    wake = _Wake(turn_id=turn_id)
    run = _run_row(target_count=1, launched_thread_id="thr-1")
    store, _ = _one_pass_run(monkeypatch, run, wake)

    ((run_id, summary, message),) = wake.queued
    assert run_id == run.run_id
    assert message == driver.summary_message(run.run_id, summary)
    (ended,) = store.named("end_discovery_run")
    assert ended["release"] is False
    assert ended["summary"] == summary
    assert store.named("record_wake_turn") == [{"run_id": run.run_id, "wake_turn_id": turn_id}]
    # The run ended — its summary written — before the wake was asked to carry it.
    order = [name for name, _ in store.events]
    assert order.index("finish_discovery_run") < order.index("end_discovery_run")


@pytest.mark.parametrize(
    "wake", [_Wake(turn_id=None), _Wake(error=RuntimeError("no thread")), None]
)
def test_a_threaded_run_whose_wake_queues_nothing_is_released_at_once(
    monkeypatch: pytest.MonkeyPatch, wake: _Wake | None
) -> None:
    """A lock nobody will ever release would block every later discovery of the project."""
    store, result = _one_pass_run(
        monkeypatch, _run_row(target_count=1, launched_thread_id="thr-1"), wake
    )

    assert result.outcome == "completed"
    assert store.named("end_discovery_run")[-1]["release"] is True
    assert store.named("record_wake_turn") == []


def test_a_run_without_a_brief_is_refused_by_name_before_a_cent_is_spent_and_still_ends(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    wake = _Wake(turn_id=uuid4())
    run = _run_row(brief=None, launched_thread_id="thr-1")
    store, result = _one_pass_run(monkeypatch, run, wake)

    assert result.outcome == "needs_review"
    assert store.named("create_search") == []
    assert finished_receipt(store)["failure"] == "brief_missing"
    (ended,) = store.named("end_discovery_run")
    assert (ended["status"], ended["end_reason"]) == ("needs_review", "failed")
    # A failed run still wakes the agent, which is told why.
    ((_, summary, message),) = wake.queued
    assert summary["failure"] == "brief_missing"
    assert "Ended: failed (brief_missing)." in message


def test_a_failure_mid_round_lands_its_counters_and_still_wakes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    run = _run_row(launched_thread_id="thr-1")
    store = _Store(run)
    refused = replace(_view(), error="http 400: bad criteria")
    handler, *_ = _handler(
        store,
        exa=_FakeExa(_responder({})),
        websets=_FakeWebsets(create_view=refused),
        monkeypatch=monkeypatch,
    )
    wake = _Wake(turn_id=uuid4())
    handler._wake = wake

    result = asyncio.run(handler.handle(_context(run.run_id)))

    assert result.outcome == "needs_review"
    receipt = finished_receipt(store)
    assert receipt["failure"] == "websets_request_refused"
    assert receipt["end_reason"] == "failed"
    assert [row["ordinal"] for row in receipt["searches"]] == [1]
    (ended,) = store.named("end_discovery_run")
    assert (ended["status"], ended["end_reason"], ended["release"]) == (
        "needs_review",
        "failed",
        False,
    )
    assert len(wake.queued) == 1


def test_the_wall_clock_ends_the_run_with_its_own_reason(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    run = _run_row()
    store = _Store(run)
    handler, *_ = _handler(
        store,
        exa=_FakeExa(_responder({})),
        websets=_FakeWebsets(get_views=[_view(status="running")]),
        monkeypatch=monkeypatch,
        settings=Settings(_env_file=None, arv2_discovery_wall_s=60, arv2_discovery_max_topups=0),
        clock=_clock(step_s=45.0),
    )

    asyncio.run(handler.handle(_context(run.run_id)))

    (ended,) = store.named("end_discovery_run")
    assert (ended["status"], ended["end_reason"]) == ("needs_review", "wall_clock")


def test_rounds_stop_at_the_cap_when_every_round_finds_only_excluded_companies(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    run = _run_row(target_count=2, brief=_brief_json(geography="must"))
    store = _Store(run)
    fails = {"geography": "fail", "stage": "pass", "hiring": "pass", "intent": "pass"}
    exa = _FakeExa(
        _responder(
            {
                "Acme": _company_answers("Acme", "acme.com", fails),
                "Bolt": _company_answers("Bolt", "bolt.com", fails),
            }
        )
    )
    websets = _FakeWebsets(
        websets={
            "ws-1": ([_view(webset_id="ws-1")], [_items(_item("Acme", "https://acme.com"))]),
            "ws-2": ([_view(webset_id="ws-2")], [_items(_item("Bolt", "https://bolt.com"))]),
        }
    )
    handler, _, _, _, accounts = _handler(
        store,
        exa=exa,
        websets=websets,
        monkeypatch=monkeypatch,
        settings=Settings(_env_file=None, arv2_discovery_max_topups=1),
    )

    asyncio.run(handler.handle(_context(run.run_id)))

    assert [call["count"] for call in websets.named("create")] == [2, 2]
    assert accounts.created == []
    (ended,) = store.named("end_discovery_run")
    assert ended["end_reason"] == "round_cap"
    assert ended["summary"]["searches"] == 2
    assert "Ended: round cap (2 searches)." in driver.summary_message(run.run_id, ended["summary"])


def test_a_round_that_finds_nothing_new_ends_the_run_dry(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    run = _run_row(target_count=5)
    store = _Store(run)
    exa = _FakeExa(_responder({"Acme": _company_answers("Acme", "acme.com", _ALL_PASS)}))
    websets = _FakeWebsets(
        websets={
            "ws-1": ([_view(webset_id="ws-1")], [_items(_item("Acme", "https://acme.com"))]),
            "ws-2": ([_view(webset_id="ws-2")], [_items()]),
        }
    )
    handler, *_ = _handler(
        store,
        exa=exa,
        websets=websets,
        monkeypatch=monkeypatch,
        settings=Settings(_env_file=None, arv2_discovery_max_topups=3),
    )

    asyncio.run(handler.handle(_context(run.run_id)))

    assert len(websets.named("create")) == 2
    (ended,) = store.named("end_discovery_run")
    assert (ended["status"], ended["end_reason"]) == ("completed", "dry")


def test_stop_before_a_round_buys_nothing_and_ends_the_run_stopped(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    run = _run_row()
    store = _Store(run)
    store.stop_after = 0
    websets = _FakeWebsets()
    handler, *_ = _handler(
        store, exa=_FakeExa(_responder({})), websets=websets, monkeypatch=monkeypatch
    )

    result = asyncio.run(handler.handle(_context(run.run_id)))

    assert result.outcome == "stopped"
    assert websets.calls == []
    (ended,) = store.named("end_discovery_run")
    assert (ended["status"], ended["end_reason"]) == ("stopped", "stopped")


def test_stop_mid_webset_cancels_it_reads_it_once_more_and_keeps_what_was_verified(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The webset is still running on the first poll, whose tick verifies Acme; the human's Stop
    is read before the second poll — the webset is cancelled, read once more (Globex reaches the
    ledger, unverified), and Acme is kept."""
    run = _run_row(target_count=5)
    store = _Store(run)
    # Read 1: before round 1 opens. Read 2: before the first poll. Stop from read 3 on.
    store.stop_after = 2
    acme = _item("Acme", "https://acme.com")
    exa = _FakeExa(_responder({"Acme": _company_answers("Acme", "acme.com", _ALL_PASS)}))
    websets = _FakeWebsets(
        get_views=[_view(status="running")],
        items_results=[_items(acme)],
        items_after_cancel=_items(acme, _item("Globex", "https://globex.com")),
    )
    handler, _, _, _, accounts = _handler(
        store,
        exa=exa,
        websets=websets,
        monkeypatch=monkeypatch,
        settings=Settings(_env_file=None, arv2_discovery_max_topups=3),
    )

    result = asyncio.run(handler.handle(_context(run.run_id)))

    assert result.outcome == "stopped"
    assert websets.named("cancel") == [{"webset_id": "ws-1"}]
    assert [name for name, _ in websets.calls][-2:] == ["cancel", "items"]
    assert [created["primary_domain"] for created in accounts.created] == ["acme.com"]
    assert len(websets.named("create")) == 1  # no round after the Stop
    receipt = finished_receipt(store)
    assert receipt["webset_stopped"] is True
    assert receipt["rows_priced_at_stop"] == 1
    (ended,) = store.named("end_discovery_run")
    assert (ended["status"], ended["end_reason"]) == ("stopped", "stopped")
    assert ended["summary"]["added"] == 1


# -- the brief's exclude list (spec 2026-10-16-discovery-excludes-seller-customers §4.6) ---------


def _excluding(*entries: tuple[str, str], **roles: str) -> dict[str, Any]:
    return {
        **_brief_json(**roles),
        "exclude": [{"name": name, "domains": [domain]} for name, domain in entries],
    }


def _brief_excluded(store: _Store) -> list[CandidateRow]:
    return [
        event["row"]
        for event in store.named("upsert_candidate")
        if event["row"].disposition == "excluded_by_brief"
    ]


_PASSES = {"geography": "pass", "stage": "pass", "hiring": "pass", "intent": "pass"}


def test_a_webset_item_on_the_exclude_list_is_recorded_and_never_verified(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    run = _run_row(brief=_excluding(("Marriott", "marriott.com")))
    store = _Store(run)
    exa = _FakeExa(_responder({"Probook": _company_answers("Probook", "probook.ai", _PASSES)}))
    websets = _FakeWebsets(
        items_results=[
            _items(
                _item("Marriott", "https://www.marriott.com"),
                _item("Probook", "https://probook.ai"),
            )
        ]
    )
    handler, *_ = _handler(store, exa=exa, websets=websets, monkeypatch=monkeypatch)

    asyncio.run(handler.handle(_context(run.run_id)))

    (excluded,) = _brief_excluded(store)
    assert (excluded.domain, excluded.excluded_by_entry, excluded.name) == (
        "marriott.com",
        "Marriott",
        "Marriott",
    )
    # Not one paid question about Marriott: no website answer and no gate.
    assert not any("Marriott" in query for query in exa.queries)
    assert store.named("finish_discovery_run")[0]["receipt"]["excluded_by_brief"] == 1


def test_a_search_hit_on_the_exclude_list_is_recorded_before_any_spend(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    brief = {**_excluding(("Marriott", "marriott.com")), "source": "search"}
    run = _run_row(brief=brief, source="search", target_count=1)
    store = _Store(run)
    hits = [SimpleNamespace(url="https://www.marriott.com/", title="Marriott", text="")]
    exa = _FakeExa(_responder({}), search_hits=hits)
    handler, *_ = _handler(store, exa=exa, websets=_FakeWebsets(), monkeypatch=monkeypatch)

    asyncio.run(handler.handle(_context(run.run_id)))

    (excluded,) = _brief_excluded(store)
    assert excluded.domain == "marriott.com"
    assert exa.queries == []


def test_a_verified_domain_on_the_list_is_caught_after_a_redirecting_url(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    run = _run_row(brief=_excluding(("Probook", "probook.ai")))
    store = _Store(run)
    exa = _FakeExa(_responder({"Probook": _company_answers("Probook", "probook.ai", _PASSES)}))
    websets = _FakeWebsets(items_results=[_items(_item("Probook", "https://probook.com"))])
    handler, *_ = _handler(store, exa=exa, websets=websets, monkeypatch=monkeypatch)

    asyncio.run(handler.handle(_context(run.run_id)))

    (excluded,) = _brief_excluded(store)
    assert excluded.domain == "probook.ai"
    # The one website answer that found the real domain; no gate.
    assert len(exa.queries) == 1
    assert exa.gate_queries() == []


def test_the_sellers_onboarding_domain_is_skipped_without_any_exclude(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    run = _run_row()
    store = _Store(run, seller_domain="conduit.ai")
    exa = _FakeExa(_responder({}))
    websets = _FakeWebsets(items_results=[_items(_item("Conduit", "https://conduit.ai"))])
    handler, *_ = _handler(store, exa=exa, websets=websets, monkeypatch=monkeypatch)

    asyncio.run(handler.handle(_context(run.run_id)))

    (excluded,) = _brief_excluded(store)
    assert (excluded.domain, excluded.excluded_by_entry) == ("conduit.ai", "seller")
    assert store.named("seller_domain")[0] == {"workspace_id": WORKSPACE, "brand_id": "brd-1"}


def test_no_onboarding_run_means_only_the_brief_excludes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    run = _run_row()
    store = _Store(run, seller_domain=None)
    exa = _FakeExa(_responder({"Probook": _company_answers("Probook", "probook.ai", _PASSES)}))
    websets = _FakeWebsets(items_results=[_items(_item("Probook", "https://probook.ai"))])
    handler, *_ = _handler(store, exa=exa, websets=websets, monkeypatch=monkeypatch)

    result = asyncio.run(handler.handle(_context(run.run_id)))

    assert result.outcome == "completed"
    assert _brief_excluded(store) == []


def test_a_resumed_run_recounts_its_brief_exclusions_once(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    run = _run_row(brief=_excluding(("Marriott", "marriott.com")))
    earlier = CandidateRow(
        candidate_id=uuid4(),
        run_id=run.run_id,
        workspace_id=WORKSPACE,
        project_id=PROJECT,
        pass_="strict",
        domain="marriott.com",
        websets_url="https://www.marriott.com",
        name="Marriott",
        provider_snapshot={"websets_domain": "marriott.com"},
        disposition="excluded_by_brief",
        excluded_by_entry="Marriott",
    )
    store = _Store(run, candidates=[earlier])
    exa = _FakeExa(_responder({}))
    websets = _FakeWebsets(items_results=[_items(_item("Marriott", "https://www.marriott.com"))])
    handler, *_ = _handler(store, exa=exa, websets=websets, monkeypatch=monkeypatch)

    asyncio.run(handler.handle(_context(run.run_id)))

    assert _brief_excluded(store) == []
    assert store.named("finish_discovery_run")[0]["receipt"]["excluded_by_brief"] == 1


def test_an_old_run_without_exclude_resumes_unchanged(monkeypatch: pytest.MonkeyPatch) -> None:
    brief = _brief_json()
    assert "exclude" not in brief
    run = _run_row(brief=brief)
    store = _Store(run)
    exa = _FakeExa(_responder({"Probook": _company_answers("Probook", "probook.ai", _PASSES)}))
    websets = _FakeWebsets(items_results=[_items(_item("Probook", "https://probook.ai"))])
    handler, *_ = _handler(store, exa=exa, websets=websets, monkeypatch=monkeypatch)

    result = asyncio.run(handler.handle(_context(run.run_id)))

    assert result.outcome == "completed"
    assert store.named("finish_discovery_run")[0]["receipt"]["excluded_by_brief"] == 0


def test_the_summary_counts_brief_exclusions(monkeypatch: pytest.MonkeyPatch) -> None:
    run = _run_row(brief=_excluding(("Marriott", "marriott.com"), ("Hilton", "hilton.com")))
    store = _Store(run)
    exa = _FakeExa(_responder({}))
    websets = _FakeWebsets(
        items_results=[
            _items(
                _item("Marriott", "https://www.marriott.com"),
                _item("Hilton", "https://hilton.com"),
            )
        ]
    )
    handler, *_ = _handler(store, exa=exa, websets=websets, monkeypatch=monkeypatch)

    asyncio.run(handler.handle(_context(run.run_id)))

    (ended,) = store.named("end_discovery_run")
    summary = ended["summary"]
    assert summary["excluded_by_brief"] == 2
    assert summary["excluded_by_brief_example"] == "Marriott"
    assert (
        "Excluded by the brief (existing customers or the seller): 2 — e.g. Marriott."
        in driver.summary_message(run.run_id, summary)
    )


def test_websets_rounds_exclude_the_brief_through_one_import(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    run = _run_row(target_count=2, brief=_excluding(("Marriott", "marriott.com"), geography="must"))
    store = _Store(run)
    fails = {"geography": "fail", "stage": "pass", "hiring": "pass", "intent": "pass"}
    exa = _FakeExa(
        _responder(
            {
                "Acme": _company_answers("Acme", "acme.com", fails),
                "Bolt": _company_answers("Bolt", "bolt.com", fails),
            }
        )
    )
    websets = _FakeWebsets(
        websets={
            "ws-1": ([_view(webset_id="ws-1")], [_items(_item("Acme", "https://acme.com"))]),
            "ws-2": ([_view(webset_id="ws-2")], [_items(_item("Bolt", "https://bolt.com"))]),
        },
        import_statuses=("processing", "completed"),
    )
    handler, *_ = _handler(
        store,
        exa=exa,
        websets=websets,
        monkeypatch=monkeypatch,
        settings=Settings(_env_file=None, arv2_discovery_max_topups=1),
    )

    asyncio.run(handler.handle(_context(run.run_id)))

    (made,) = websets.named("create_import")
    assert made["csv_bytes"] == b"url\nhttps://marriott.com\n"
    assert websets.named("upload_import")[0]["csv_bytes"] == made["csv_bytes"]
    creates = websets.named("create")
    assert len(creates) == 2
    assert all(call["exclude_import_ids"] == ("i1",) for call in creates)
    # The person sees the exclusion working even when the Import kept everyone out upfront.
    (ended,) = store.named("end_discovery_run")
    assert ended["summary"]["import_domains"] == 1
    assert (
        "The Exa import kept 1 excluded domain out of every search upfront."
        in driver.summary_message(run.run_id, ended["summary"])
    )


def test_an_import_still_processing_at_the_deadline_is_skipped_and_the_domain_skip_still_applies(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    run = _run_row(brief=_excluding(("Marriott", "marriott.com")))
    store = _Store(run)
    exa = _FakeExa(_responder({}))
    websets = _FakeWebsets(
        items_results=[_items(_item("Marriott", "https://www.marriott.com"))],
        import_statuses=("processing",),
    )
    handler, *_ = _handler(
        store,
        exa=exa,
        websets=websets,
        monkeypatch=monkeypatch,
        settings=Settings(_env_file=None, arv2_discovery_import_wait_s=0),
    )

    asyncio.run(handler.handle(_context(run.run_id)))

    assert websets.named("create")[0]["exclude_import_ids"] == ()
    assert [row.domain for row in _brief_excluded(store)] == ["marriott.com"]
    receipt = store.named("finish_discovery_run")[0]["receipt"]
    assert receipt["guards"].get("brief_import_unavailable") == 1
    (ended,) = store.named("end_discovery_run")
    assert ended["summary"]["import_domains"] == 0
    assert ended["summary"]["import_unavailable"] is True
    assert (
        "The Exa import of the excluded domains could not be used; they were skipped as they came."
        in driver.summary_message(run.run_id, ended["summary"])
    )


def test_a_completed_import_exa_read_no_rows_from_is_not_used(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Live 2026-10-16: Exa marked the Import ``completed`` having read 0 of its 24 rows, the
    search excluded nothing through it, and the summary still said it kept 24 domains out. An
    empty Import is no exclusion: it is never attached, and the summary says so."""
    run = _run_row(brief=_excluding(("Marriott", "marriott.com")))
    store = _Store(run)
    exa = _FakeExa(_responder({}))
    websets = _FakeWebsets(
        items_results=[_items(_item("Marriott", "https://www.marriott.com"))],
        import_statuses=(ImportStatus(status="completed", count=0),),
    )
    handler, *_ = _handler(store, exa=exa, websets=websets, monkeypatch=monkeypatch)

    asyncio.run(handler.handle(_context(run.run_id)))

    assert websets.named("create")[0]["exclude_import_ids"] == ()
    assert [row.domain for row in _brief_excluded(store)] == ["marriott.com"]
    receipt = store.named("finish_discovery_run")[0]["receipt"]
    assert receipt["guards"].get("brief_import_unavailable") == 1
    (ended,) = store.named("end_discovery_run")
    assert ended["summary"]["import_domains"] == 0
    assert ended["summary"]["import_unavailable"] is True
    message = driver.summary_message(run.run_id, ended["summary"])
    assert "kept" not in message
    assert (
        "The Exa import of the excluded domains could not be used; they were skipped as they came."
        in message
    )


def test_the_summary_counts_the_rows_exa_read_not_the_rows_sent(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    run = _run_row(brief=_excluding(("Marriott", "marriott.com"), ("Nobu Hotel", "nobuhotels.com")))
    store = _Store(run)
    exa = _FakeExa(_responder({}))
    websets = _FakeWebsets(
        items_results=[_items()],
        import_statuses=(ImportStatus(status="completed", count=1),),
    )
    handler, *_ = _handler(store, exa=exa, websets=websets, monkeypatch=monkeypatch)

    asyncio.run(handler.handle(_context(run.run_id)))

    assert websets.named("create_import")[0]["count"] == 2
    assert websets.named("create")[0]["exclude_import_ids"] == ("i1",)
    (ended,) = store.named("end_discovery_run")
    assert ended["summary"]["import_domains"] == 1


def test_no_exclusions_means_no_import(monkeypatch: pytest.MonkeyPatch) -> None:
    run = _run_row()
    store = _Store(run)
    websets = _FakeWebsets()
    handler, *_ = _handler(
        store, exa=_FakeExa(_responder({})), websets=websets, monkeypatch=monkeypatch
    )

    asyncio.run(handler.handle(_context(run.run_id)))

    assert websets.named("create_import") == []
    assert websets.named("create")[0]["exclude_import_ids"] == ()


def test_a_search_round_makes_room_for_the_excluded_domains_exa_still_returns(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A seller with many customers matching the ICP: the search asks for one more result per
    excluded domain, as it does per known one, so the customers do not crowd out new companies."""
    entries = [(f"Customer {n}", f"customer{n}.com") for n in range(3)]
    brief = {**_excluding(*entries), "source": "search"}
    run = _run_row(brief=brief, source="search", target_count=1)
    store = _Store(run)
    exa = _FakeExa(_responder({}))
    handler, *_ = _handler(store, exa=exa, websets=_FakeWebsets(), monkeypatch=monkeypatch)

    asyncio.run(handler.handle(_context(run.run_id)))

    assert exa.searches[0]["num_results"] == 2 * 1 + 3
