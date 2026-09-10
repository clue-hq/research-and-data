"""One discovery run driven end to end against the real rows: candidates, accounts, fit, money.

The only double is the transport — :class:`~clue_api.arv2.transport.ScriptedTransport`, the lane's
one permitted one — so the **real** Exa and Websets clients build the real requests, the real
:class:`~clue_api.arv2.calls.ProviderCaller` records the real ledger rows and raw bodies, and the
real store, the real claim gate and the real account writer land everything below them.

The scenario is the one the proof of concept produced: the long list gives two companies, one of
which the workspace already owns under the domain the long list got *wrong* (``probook.com`` for
``probook.ai``) — so it costs the one website answer that identified it and not a single gate —
and the other passes every gate and becomes a ``candidate`` account whose fit reads High 100 on
the accounts list.
"""

from __future__ import annotations

import asyncio
import json
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
from clue_api.arv2.discovery_store import list_candidates, read_discovery_run
from clue_api.arv2.exa_client import ExaClient
from clue_api.arv2.exa_websets_client import ExaWebsetsClient
from clue_api.arv2.transport import HttpResponse, ScriptedTransport
from clue_api.frontend_read.v1_shared import fit_score_100
from clue_config import Secrets, Settings
from clue_fleet import FleetTaskKind
from clue_fleet.lease import LeaseGeneration
from clue_fleet.work_worker import WorkContext
from clue_research.claimstore import load_core_pack
from clue_storage.fs import FsStorage
from tests.arv2.icp_fixture import USER_ID, IcpFixture, seed_icp_fixture, settings_for
from tests.arv2.test_discovery_driver import GEOGRAPHY_RULE, STAGE_RULE, _clock, _no_sleep

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
PATIENTDESK_QUOTE = (
    "Patientdesk closed a $9M Series A in March 2025 and is hiring go-to-market staff in Boston."
)


def _json(payload: dict[str, Any]) -> HttpResponse:
    return HttpResponse(
        status=200,
        headers={"content-type": "application/json"},
        body=json.dumps(payload).encode(),
    )


def _search_body(*, status: str, found: int, analyzed: int) -> dict[str, Any]:
    return {
        "id": "srch-strict",
        "object": "webset_search",
        "status": status,
        "count": 35,
        "recall": {"estimate": 240},
        "progress": {"found": found, "analyzed": analyzed},
        "criteria": [
            {"description": GEOGRAPHY_RULE, "successRate": 0.78},
            {"description": STAGE_RULE, "successRate": 0.11},
        ],
    }


def _webset_body(*, status: str, found: int, analyzed: int) -> dict[str, Any]:
    return {
        "id": "ws-db-1",
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
) -> dict[str, Any]:
    company: dict[str, Any] = {
        "name": name,
        "headquarters": {"city": "Austin", "state": "TX", "countryCode": "US"},
        "financials": {},
    }
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


#: The nine requests this run makes, in the order it makes them. Written out rather than routed by
#: URL on purpose: the ORDER is part of the contract — the website answer comes before the dedupe,
#: and the duplicate never reaches a gate — so a step that moves fails this test loudly.
def _script() -> list[HttpResponse]:
    patientdesk = "https://patientdesk.com/news"
    return [
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
                    ),
                ],
                "hasMore": False,
            }
        ),
        # Probook's own site is probook.ai — the long list's probook.com was wrong, and the
        # workspace already owns probook.ai, so this candidate ends here.
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
            run_id = await _launch(conn, storage, fixture)

            transports = _OneCallPerHop(_script())
            handler = Arv2DiscoveryWorkHandler(
                settings=Settings(_env_file=None, arv2_discovery_enabled=True),
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
            assert run.webset_id == "ws-db-1"
            assert (run.asked, run.found_strict, run.found_relaxed, run.analyzed) == (35, 2, 0, 311)
            assert run.recall_estimate == 240
            assert run.receipt is not None
            assert run.receipt["duplicates"] == 1
            assert run.receipt["shown"] == 1
            assert run.receipt["guards"] == {"ok": 4}
            assert run.receipt["criteria_relaxed"] is None

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
                            "SELECT canonical_name, primary_domain, status, workspace_id "
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
