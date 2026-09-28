"""One discovery run driven end to end against the real rows: candidates, accounts, fit, money.

The only double is the transport — :class:`~clue_api.arv2.transport.ScriptedTransport`, the lane's
one permitted one — so the **real** Exa and Websets clients build the real requests, the real
:class:`~clue_api.arv2.calls.ProviderCaller` records the real ledger rows and raw bodies, and the
real store, the real claim gate and the real account writer land everything below them.

The scenario is the one the proof of concept produced: the long list gives two companies, one of
which this project already holds under the domain the long list got *wrong* (``probook.com`` for
``probook.ai``) — so it costs the one website answer that identified it and not a single gate —
and the other passes every gate and becomes a ``candidate`` account whose fit reads High 100 on
the accounts list. Exa filled the first search, so the duplicate leaves the run one short and a
strict top-up — a second webset, excluding the first — asks for the one missing (rulings
2026-09-28); the market has no more, and the run lands honestly short.
"""

from __future__ import annotations

import asyncio
import json
import threading
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any
from uuid import UUID

import pytest
from pydantic import SecretStr
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from clue_api.agent_turn_wiring import DurableAgentArtifactStore
from clue_api.arv2.catalog_seed import load_arv2_pack
from clue_api.arv2.claim_writer import LenientClaimWriter
from clue_api.arv2.discovery_driver import (
    Arv2DiscoveryWorkHandler,
    arv2_discovery_work_id,
    build_arv2_discovery_handler,
)
from clue_api.arv2.discovery_launch import (
    Arv2DiscoveryRequest,
    launch_arv2_discovery,
)
from clue_api.arv2.discovery_store import list_candidates, list_searches, read_discovery_run
from clue_api.arv2.exa_client import ExaClient
from clue_api.arv2.exa_websets_client import ExaWebsetsClient
from clue_api.arv2.transport import HttpResponse, ScriptedTransport
from clue_api.frontend_read.v1_shared import fit_score_100
from clue_config import Secrets, Settings
from clue_fleet import FleetTaskKind
from clue_fleet.lease import LeaseGeneration
from clue_fleet.work_worker import WorkContext
from clue_research.claimstore import load_core_pack
from clue_research.membership import ensure_project_accounts
from clue_storage.fs import FsStorage
from tests.arv2.icp_fixture import USER_ID, IcpFixture, seed_icp_fixture, settings_for
from tests.arv2.test_discovery_driver import (
    _RULES,
    GEOGRAPHY_RULE,
    STAGE_RULE,
    _clock,
    _no_sleep,
)

# The claim-store harness lives in a sibling test package; a fixture is only visible to a module
# that imports it, so re-export both (``require_claimstore_db`` depends on ``migrated_db``).
from tests.claimstore.conftest import (  # noqa: F401
    migrated_db,
    require_claimstore_db,
    rollback_conn,
)
from tests.db.conftest import run_async

pytestmark = pytest.mark.usefixtures("require_claimstore_db")

#: No live provider is reached: every request lands on the scripted transport.
_SECRET = SecretStr("exa-test-key")

PROBOOK_QUOTE = "Probook raised a $12M Series A led by Amplify and is hiring in Austin, Texas."
PATIENTDESK_MARK = (
    "https://media.licdn.com/dms/image/v2/D560BAQHi-klal6mKkQ/company-logo_200_200/0?e=2147483647"
)
PATIENTDESK_QUOTE = (
    "Patientdesk closed a $9M Series A in March 2025 and is hiring go-to-market staff in Boston."
)


def _json(payload: dict[str, Any]) -> HttpResponse:
    return HttpResponse(
        status=200,
        headers={"content-type": "application/json"},
        body=json.dumps(payload).encode(),
    )


def _not_found() -> HttpResponse:
    """Exa's answer to a lookup by an external id it has never seen."""
    return HttpResponse(
        status=404,
        headers={"content-type": "application/json"},
        body=b'{"message": "Webset not found", "statusCode": 404}',
    )


def _search_body(
    *, status: str, found: int, analyzed: int, search_id: str = "srch-strict"
) -> dict[str, Any]:
    return {
        "id": search_id,
        "object": "webset_search",
        "status": status,
        "count": 2,
        "recall": {"expected": {"total": 240, "confidence": "medium"}},
        "progress": {"found": found, "analyzed": analyzed},
        "criteria": [
            {"description": GEOGRAPHY_RULE, "successRate": 0.78},
            {"description": STAGE_RULE, "successRate": 0.11},
        ],
    }


def _webset_body(
    *, status: str, found: int, analyzed: int, webset_id: str = "ws-db-1"
) -> dict[str, Any]:
    return {
        "id": webset_id,
        "status": status,
        "searches": [_search_body(status=status, found=found, analyzed=analyzed)],
    }


def _item_body(
    item_id: str,
    *,
    name: str,
    url: str,
    employees: int | None = None,
    revenue_annual: int | None = None,
    logo_url: str | None = None,
) -> dict[str, Any]:
    company: dict[str, Any] = {
        "name": name,
        "headquarters": {"city": "Austin", "state": "TX", "countryCode": "US"},
        "financials": {},
    }
    if logo_url is not None:
        company["logoUrl"] = logo_url
    if employees is not None:
        company["employees"] = employees
    if revenue_annual is not None:
        company["financials"]["revenueAnnual"] = revenue_annual
    return {
        "id": item_id,
        "sourceId": "srch-strict",
        "properties": {"url": url, "description": f"{name} sells software.", "company": company},
        "evaluations": [{"criterion": GEOGRAPHY_RULE, "satisfied": "yes"}],
    }


def _answer_body(
    answer: dict[str, str], *, citation_url: str, citation_text: str
) -> dict[str, Any]:
    return {
        "answer": answer,
        "citations": [
            {"url": citation_url, "title": "Announcement", "text": citation_text},
        ],
        "costDollars": {"total": 0.005},
    }


def _gate_answer(rule_quote: str, url: str) -> dict[str, Any]:
    return _answer_body(
        {
            "verdict": "pass",
            "reasoning": "The announcement states it.",
            "evidence_quote": rule_quote,
            "evidence_url": url,
            "evidence_date": "2025-03-04",
        },
        citation_url=url,
        citation_text=rule_quote,
    )


#: The fourteen requests this run makes, in the order it makes them. Written out rather than routed
#: by URL on purpose: the ORDER is part of the contract — every webset is looked up by its external
#: id before it is bought, the website answer comes before the dedupe, the duplicate never reaches
#: a gate, and the top-up is bought only after the first search is done — so a step that moves
#: fails this test loudly.
def _script() -> list[HttpResponse]:
    patientdesk = "https://patientdesk.com/news"
    return [
        _not_found(),
        _json(_webset_body(status="running", found=0, analyzed=0)),
        _json(_webset_body(status="idle", found=2, analyzed=311)),
        _json(
            {
                "data": [
                    _item_body(
                        "itm-probook",
                        name="Probook",
                        url="https://probook.com",
                        employees=90,
                    ),
                    _item_body(
                        "itm-patientdesk",
                        name="Patientdesk",
                        url="https://patientdesk.com",
                        employees=140,
                        revenue_annual=8_000_000,
                        logo_url=PATIENTDESK_MARK,
                    ),
                ],
                "hasMore": False,
            }
        ),
        # Probook's own site is probook.ai — the long list's probook.com was wrong, and this
        # project already holds probook.ai, so this candidate ends here.
        _json(
            _answer_body(
                {"website_domain": "probook.ai", "evidence_url": "https://probook.ai/news"},
                citation_url="https://probook.ai/news",
                citation_text=PROBOOK_QUOTE,
            )
        ),
        _json(
            _answer_body(
                {"website_domain": "patientdesk.com", "evidence_url": patientdesk},
                citation_url=patientdesk,
                citation_text=PATIENTDESK_QUOTE,
            )
        ),
        _json(_gate_answer(PATIENTDESK_QUOTE, patientdesk)),
        _json(_gate_answer(PATIENTDESK_QUOTE, patientdesk)),
        _json(_gate_answer(PATIENTDESK_QUOTE, patientdesk)),
        _json(_gate_answer(PATIENTDESK_QUOTE, patientdesk)),
        # Exa filled search 1 (2 of 2) and the duplicate left the run one short: the strict
        # top-up, a new webset for the one missing, which finds nothing more.
        _not_found(),
        _json(_webset_body(status="running", found=0, analyzed=0, webset_id="ws-db-2")),
        _json(_webset_body(status="idle", found=0, analyzed=40, webset_id="ws-db-2")),
        _json({"data": [], "hasMore": False}),
    ]


class _OneCallPerHop:
    """A fresh :class:`ScriptedTransport` per hop, each holding that hop's one response."""

    def __init__(self, script: list[HttpResponse]) -> None:
        self._script = list(script)
        self.transports: list[ScriptedTransport] = []

    def __call__(self) -> ScriptedTransport:
        if not self._script:
            raise AssertionError("the discovery run made more provider calls than were scripted")
        transport = ScriptedTransport([self._script.pop(0)])
        self.transports.append(transport)
        return transport

    @property
    def remaining(self) -> int:
        return len(self._script)


class _LiveClientsForTest:
    """The **real** clients, built per hop around the caller the driver hands them."""

    def exa(self, caller: Any) -> ExaClient:
        return ExaClient(caller, api_key=_SECRET)

    def websets(self, caller: Any) -> ExaWebsetsClient:
        return ExaWebsetsClient(
            caller,
            api_key=_SECRET,
            usd_per_credit=Settings(_env_file=None).arv2_discovery_websets_usd_per_credit,
        )


def _conn_factory(conn: AsyncConnection) -> Any:
    """A ``ConnFactory`` handing the driver the test's own rolled-back connection."""

    @asynccontextmanager
    async def factory() -> AsyncIterator[AsyncConnection]:
        yield conn

    return factory


async def _launch(conn: AsyncConnection, storage: FsStorage, fixture: IcpFixture) -> UUID:
    receipt = await launch_arv2_discovery(
        conn,
        Arv2DiscoveryRequest(
            workspace_id=fixture.workspace_id,
            project_id=fixture.project_id,
            requested_by_user_id=USER_ID,
            request_key="turn-action:db-ask",
            target_count=2,
            # The relaxed pass is its own scenario; this one is the strict pass end to end.
            relaxed_enabled=False,
        ),
        settings=settings_for(arv2_discovery_enabled=True),
        storage=storage,
    )
    return receipt.run_id


def test_a_discovery_run_lands_candidates_a_candidate_account_its_fit_and_its_ledger(
    tmp_path: Any,
) -> None:
    async def scenario() -> None:
        async with rollback_conn() as conn:
            storage = FsStorage(tmp_path)
            await load_core_pack(conn)
            await load_arv2_pack(conn)
            fixture = await seed_icp_fixture(conn, storage)
            # Probook is already one of THIS project's accounts: the duplicate that costs no gate.
            await ensure_project_accounts(
                conn,
                workspace_id=fixture.workspace_id,
                project_id=fixture.project_id,
                account_entity_ids=[UUID(str(fixture.accounts[0]))],
                added_via="manual",
            )
            run_id = await _launch(conn, storage, fixture)

            transports = _OneCallPerHop(_script())
            handler = Arv2DiscoveryWorkHandler(
                # The script below is positional (its docstring says why). One hop in flight keeps
                # the order it pins; the concurrent path is proven by the routed scenario further
                # down.
                settings=Settings(
                    _env_file=None,
                    arv2_discovery_enabled=True,
                    arv2_discovery_verify_concurrency=1,
                ),
                conn_factory=_conn_factory(conn),
                storage=storage,
                # The production sink, injected from outside the lane exactly as ``fleet_main``
                # injects it: ARV2 opens no second write path into the artifact table.
                artifacts=DurableAgentArtifactStore(
                    storage=storage,  # type: ignore[arg-type]
                    conn_factory=_conn_factory(conn),
                ),
                clients=_LiveClientsForTest(),
                writer=LenientClaimWriter(lenient=True),
                transport_factory=transports,
                clock=_clock(),
                sleep=_no_sleep,
            )
            context = WorkContext(
                task_id=UUID(int=7),
                work_id=arv2_discovery_work_id(run_id),
                worker_id="w1",
                lease_generation=LeaseGeneration(1),
                payload={"run_id": str(run_id), "workspace_id": fixture.workspace_id},
                stop_requested=asyncio.Event(),
                lease_lost=asyncio.Event(),
            )

            result = await handler.handle(context)

            assert result.outcome == "completed"
            assert transports.remaining == 0  # every scripted call was made, in order

            run = await read_discovery_run(conn, run_id=run_id)
            assert run is not None
            assert run.status == "completed"
            first, topup = await list_searches(conn, run_id=run_id)
            assert (first.kind, first.webset_id, first.asked, first.found) == (
                "strict",
                "ws-db-1",
                2,
                2,
            )
            assert (topup.kind, topup.webset_id, topup.asked, topup.found) == (
                "strict_topup",
                "ws-db-2",
                1,
                0,
            )
            assert topup.exclude_webset_ids == ("ws-db-1",)
            assert first.finished_at is not None and topup.finished_at is not None
            assert (run.asked, run.found_strict, run.found_relaxed, run.analyzed) == (3, 2, 0, 351)
            assert run.recall_estimate == 240
            assert run.receipt is not None
            assert run.receipt["duplicates"] == 1
            assert run.receipt["shown"] == 1
            assert run.receipt["guards"] == {"ok": 4}

            candidates = {row.domain: row for row in await list_candidates(conn, run_id=run_id)}
            assert set(candidates) == {"probook.ai", "patientdesk.com"}
            duplicate = candidates["probook.ai"]
            assert duplicate.disposition == "duplicate_of_existing"
            assert duplicate.account_entity_id is None
            assert duplicate.verdicts == ()
            assert duplicate.provider_snapshot["websets_domain"] == "probook.com"

            verified = candidates["patientdesk.com"]
            assert verified.disposition == "pass"
            assert verified.fit == 1.0
            assert verified.pass_ == "strict"
            assert verified.account_entity_id is not None
            # Ruling 2026-09-11 (supersedes 6′): the verified candidate's account is a member of
            # the launching project by default, recorded as discovered, without any approval.
            membership = (
                await conn.execute(
                    text(
                        "SELECT project_id, added_via FROM project_account "
                        "WHERE account_entity_id = :id"
                    ),
                    {"id": verified.account_entity_id},
                )
            ).all()
            assert [(row[0], row[1]) for row in membership] == [(run.project_id, "discovered")]
            assert len(verified.verdicts) == 4
            assert {verdict["gate_key"] for verdict in verified.verdicts} == {
                "geography",
                "stage",
                "hiring",
                "intent",
            }
            assert all(verdict["guard"] == "ok" for verdict in verified.verdicts)

            account = (
                (
                    await conn.execute(
                        text(
                            "SELECT canonical_name, primary_domain, status, workspace_id, "
                            " owner_user_id, created_by_user_id "
                            "FROM account_entity WHERE id = :id"
                        ),
                        {"id": verified.account_entity_id},
                    )
                )
                .mappings()
                .one()
            )
            assert account["canonical_name"] == "Patientdesk"
            assert account["primary_domain"] == "patientdesk.com"
            assert account["status"] == "candidate"
            assert account["workspace_id"] == fixture.workspace_id
            # Founder ruling 2026-09-11: the human who launched the discovery created the account
            # and owns it by default.
            assert account["created_by_user_id"] == run.requested_by_user_id
            assert account["owner_user_id"] == run.requested_by_user_id

            # The fit as the accounts list reads it: the live claim joined to its project through
            # ``run_lineage`` (``account.scoring.*`` is project-relative), banded to 0-100.
            scored = (
                (
                    await conn.execute(
                        text(
                            "SELECT c.value_json->>'value' AS value, c.evidence_span, "
                            " c.source_key, c.write_markers, l.project_id "
                            "FROM claim c JOIN run_lineage l ON l.run_id = c.run_id "
                            "WHERE c.entity_id = :entity_id AND c.field_key = 'account.scoring.fit'"
                            " AND c.superseded_by IS NULL"
                        ),
                        {"entity_id": verified.account_entity_id},
                    )
                )
                .mappings()
                .one()
            )
            assert fit_score_100(float(scored["value"])) == 100
            assert scored["project_id"] == fixture.project_id
            assert scored["source_key"] == "exa_answer"
            assert scored["evidence_span"] == PATIENTDESK_QUOTE
            markers = scored["write_markers"]
            assert markers["discovery_run_id"] == str(run_id)
            assert markers["pass"] == "strict"
            assert markers["gates"]["stage"] == "pass"

            # The mark (founder ruling 2026-09-11): Websets' LinkedIn company mark, kept as a
            # ``core.logo_url`` claim the accounts screens serve through the platform's logo route.
            logo = (
                (
                    await conn.execute(
                        text(
                            "SELECT value_json #>> '{}' AS url, source_key FROM claim "
                            "WHERE entity_id = :entity_id AND field_key = 'core.logo_url' "
                            "AND superseded_by IS NULL"
                        ),
                        {"entity_id": verified.account_entity_id},
                    )
                )
                .mappings()
                .one()
            )
            assert (logo["url"], logo["source_key"]) == (PATIENTDESK_MARK, "exa_websets")

            rows = (
                (
                    await conn.execute(
                        text(
                            "SELECT field_key, value_json FROM claim "
                            "WHERE entity_id = :entity_id AND field_key IN "
                            "('core.employee_count', 'core.revenue_band')"
                        ),
                        {"entity_id": verified.account_entity_id},
                    )
                )
                .mappings()
                .all()
            )
            facts = {row["field_key"]: row["value_json"] for row in rows}
            assert facts["core.employee_count"] == 140
            assert facts["core.revenue_band"] == "1m_10m"

            ledger = (
                (
                    await conn.execute(
                        text(
                            "SELECT provider, operation, phase, project_id, project_run_id "
                            "FROM provider_call_ledger WHERE entity_research_job_id = :run_id"
                        ),
                        {"run_id": run_id},
                    )
                )
                .mappings()
                .all()
            )
            assert ledger, "every provider call this run made is on the ledger"
            assert {(row["provider"], row["operation"]) for row in ledger} >= {
                ("exa_websets", "create"),
                ("exa_websets", "get"),
                ("exa_websets", "items"),
                ("exa", "answer"),
            }
            assert {row["project_id"] for row in ledger} == {fixture.project_id}
            assert {row["project_run_id"] for row in ledger} == {str(run.project_run_id)}
            # Six answers were bought: one website apiece, and four gates for the ONE candidate
            # the dedupe did not stop. The duplicate never reached a gate.
            answers = [
                row for row in ledger if row["provider"] == "exa" and row["phase"] == "result"
            ]
            assert len(answers) == 6

    run_async(scenario())


class _RoutedTransport:
    """A :class:`ScriptedTransport` per hop that picks its one response by what the request asks.

    Under a cap above one the order of provider calls is not a contract any more, so a positional
    script cannot describe the run: two candidates' website asks are in flight together, and eight
    gate asks are answered in whatever order four-at-a-time finishes in. Each route is
    ``(company, needle, response)``; ``send`` consumes the first unconsumed route whose company
    tag *and* needle both appear in the request body (or, for a bodiless GET, in the URL). The
    webset routes carry the empty company tag — which is in every haystack — so the poll sequence
    is consumed in the order it is listed while every Answer is matched by its content.

    ``send`` runs on a worker thread (``_hop`` calls the provider through ``asyncio.to_thread``),
    so the scan-and-consume is done under a lock: two threads reading the same route would
    otherwise hand the same response to both.
    """

    def __init__(self, routes: list[tuple[str, str, HttpResponse]]) -> None:
        self._routes = list(routes)
        self._lock = threading.Lock()

    def __call__(self) -> ScriptedTransport:
        routes = self._routes
        lock = self._lock

        class _Transport(ScriptedTransport):
            def __init__(self) -> None:
                super().__init__([])

            def send(self, request: Any) -> HttpResponse:
                self.requests.append(request)
                haystack = (request.body or b"").decode() + str(request.url)
                with lock:
                    for index, (company, needle, response) in enumerate(routes):
                        if company in haystack and needle in haystack:
                            del routes[index]
                            return response
                raise AssertionError(f"no routed response for {haystack[:200]!r}")

        return _Transport()

    @property
    def remaining(self) -> int:
        return len(self._routes)


def _company_routes(name: str, domain: str) -> list[tuple[str, str, HttpResponse]]:
    """One website answer and one answer per hard gate, tagged with the company they belong to.

    The website ask is the only question carrying the words "registrable domain" (they are in
    :data:`WEBSITE_SCHEMA`, never in the gate schema), and each gate ask quotes its own rule — so
    the ICP's four gates need four routes, one per rule, and no two questions can be confused.
    """
    quote = f"{name} closed a Series A in March 2025 and is hiring in Boston."
    news = f"https://{domain}/news"
    website = _json(
        _answer_body(
            {"website_domain": domain, "evidence_url": news}, citation_url=news, citation_text=quote
        )
    )
    routes: list[tuple[str, str, HttpResponse]] = [(name, "registrable domain", website)]
    routes.extend((name, rule, _json(_gate_answer(quote, news))) for rule in _RULES.values())
    return routes


def _locked_conn_factory(conn: AsyncConnection) -> Any:
    """The test's one connection, handed out one caller at a time.

    ``_conn_factory`` hands *every* caller the same :class:`AsyncConnection`, and asyncpg refuses
    two operations on one connection at once — so under a cap of four the driver's concurrent
    candidates would fail or flake on the connection rather than on anything they assert. The lock
    serialises them. It is for the DRIVER's ``conn_factory`` only: the artifact store keeps the
    plain factory because it is only ever used inside the ledger drain, which already holds the
    lock, and a locked factory there would deadlock on itself.

    What this scenario proves is therefore: under a cap of four with content-routed answers both
    candidates land, with their verdicts, and the run completes. Per-connection isolation is the
    *production* factory's property (``clue_db.transaction`` opens ``engine.begin()`` per ``async
    with``) and is NOT proven here.

    The driver never nests ``_connection()`` and never hops while holding one, so this lock cannot
    deadlock. If this scenario ever hangs, that assumption has broken — report it rather than
    papering over it with a re-entrant lock.
    """
    lock = asyncio.Lock()

    @asynccontextmanager
    async def factory() -> AsyncIterator[AsyncConnection]:
        async with lock:
            yield conn

    return factory


def test_two_candidates_verify_concurrently_each_landing_its_own_verdicts(tmp_path: Any) -> None:
    """Two companies, a cap of four, and not one positional assumption left in the script."""

    async def scenario() -> None:
        async with rollback_conn() as conn:
            storage = FsStorage(tmp_path)
            await load_core_pack(conn)
            await load_arv2_pack(conn)
            fixture = await seed_icp_fixture(conn, storage)
            run_id = await _launch(conn, storage, fixture)

            routes: list[tuple[str, str, HttpResponse]] = [
                # The lookup by external id (its colon escaped in the URL, which the create's body
                # never is) finds nothing, so the webset is bought.
                ("", "arv2-discovery%3A", _not_found()),
                # The poll sequence, in the order the driver makes it — and the one part of this
                # script that is still ordered, because it is one call at a time: the created
                # webset, a first poll that is still running, the empty list that tick reads, the
                # idle poll, and the final list both companies arrive on.
                (
                    "",
                    "/websets/v0/websets",
                    _json(_webset_body(status="running", found=0, analyzed=0)),
                ),
                (
                    "",
                    "/websets/v0/websets",
                    _json(_webset_body(status="running", found=0, analyzed=0)),
                ),
                ("", "/items", _json({"data": [], "hasMore": False})),
                (
                    "",
                    "/websets/v0/websets",
                    _json(_webset_body(status="idle", found=2, analyzed=311)),
                ),
                (
                    "",
                    "/items",
                    _json(
                        {
                            "data": [
                                _item_body(
                                    "itm-a", name="Alpha", url="https://alpha.com", employees=50
                                ),
                                _item_body(
                                    "itm-b", name="Beta", url="https://beta.com", employees=60
                                ),
                            ],
                            "hasMore": False,
                        }
                    ),
                ),
                *_company_routes("Alpha", "alpha.com"),
                *_company_routes("Beta", "beta.com"),
            ]
            transport = _RoutedTransport(routes)
            handler = Arv2DiscoveryWorkHandler(
                settings=Settings(
                    _env_file=None,
                    arv2_discovery_enabled=True,
                    arv2_discovery_verify_concurrency=4,
                ),
                conn_factory=_locked_conn_factory(conn),
                storage=storage,
                artifacts=DurableAgentArtifactStore(
                    storage=storage,  # type: ignore[arg-type]
                    conn_factory=_conn_factory(conn),
                ),
                clients=_LiveClientsForTest(),
                writer=LenientClaimWriter(lenient=True),
                transport_factory=transport,
                clock=_clock(),
                sleep=_no_sleep,
            )
            context = WorkContext(
                task_id=UUID(int=8),
                work_id=arv2_discovery_work_id(run_id),
                worker_id="w1",
                lease_generation=LeaseGeneration(1),
                payload={"run_id": str(run_id), "workspace_id": fixture.workspace_id},
                stop_requested=asyncio.Event(),
                lease_lost=asyncio.Event(),
            )

            result = await handler.handle(context)

            assert result.outcome == "completed"
            assert transport.remaining == 0  # every routed response was asked for

            run = await read_discovery_run(conn, run_id=run_id)
            assert run is not None
            assert run.status == "completed"

            candidates = {row.domain: row for row in await list_candidates(conn, run_id=run_id)}
            assert sorted(candidates) == ["alpha.com", "beta.com"]
            for candidate in candidates.values():
                assert candidate.disposition == "pass"
                assert candidate.account_entity_id is not None
                assert {verdict["gate_key"] for verdict in candidate.verdicts} == {
                    "geography",
                    "stage",
                    "hiring",
                    "intent",
                }
                assert all(verdict["guard"] == "ok" for verdict in candidate.verdicts)

            # Both accounts are real rows of this workspace, each a member of the launching
            # project — the concurrent path writes exactly what the serial one does.
            accounts = (
                (
                    await conn.execute(
                        text(
                            "SELECT a.primary_domain, a.status, p.project_id, p.added_via "
                            "FROM account_entity a JOIN project_account p "
                            "  ON p.account_entity_id = a.id "
                            "WHERE a.id = ANY(:ids)"
                        ),
                        {"ids": [row.account_entity_id for row in candidates.values()]},
                    )
                )
                .mappings()
                .all()
            )
            assert sorted(
                (row["primary_domain"], row["status"], row["project_id"], row["added_via"])
                for row in accounts
            ) == [
                ("alpha.com", "candidate", fixture.project_id, "discovered"),
                ("beta.com", "candidate", fixture.project_id, "discovered"),
            ]

    run_async(scenario())


def test_the_composition_root_builds_the_same_handler_from_a_key(tmp_path: Any) -> None:
    """The production composition path, proved to produce a handler of the right kind."""
    composed = build_arv2_discovery_handler(
        Settings(_env_file=None, arv2_discovery_enabled=True),
        Secrets(_env_file=None, exa_api_key=_SECRET),  # type: ignore[call-arg]
        storage=FsStorage(tmp_path),
        artifacts=DurableAgentArtifactStore(storage=FsStorage(tmp_path)),  # type: ignore[arg-type]
    )
    assert composed is not None
    assert composed.kind is FleetTaskKind.ARV2_DISCOVERY
