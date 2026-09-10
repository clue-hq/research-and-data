"""The Websets client's request shapes, its cursor walk, and how it prices a page of results.

Global Constraint 3 keeps provider *behaviour* live. What is unit-tested here is what a live
webset cannot show on demand: that ``entity``/``criteria``/``recall`` reach the wire in the shape
Exa documents, that the items walk actually follows ``nextCursor`` and stops on ``hasMore``, that
a page of results is priced at ten credits per *all-green* row (the only rows Websets charges
for), and that a refusal latches the provider instead of being retried into a bigger bill.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

import pytest
from pydantic import SecretStr

from clue_api.arv2.calls import ProviderCaller
from clue_api.arv2.errors import ProviderHalted
from clue_api.arv2.exa_websets_client import (
    CREDITS_PER_MATCH,
    WEBSETS_BASE_PATH,
    ExaWebsetsClient,
    websets_halt_rule,
    websets_items_cost,
)
from clue_api.arv2.provider_ledger import BufferedLedger, BufferedRawSink
from clue_api.arv2.transport import HttpResponse, ScriptedTransport

USD_PER_CREDIT = Decimal("0.00449")


def _caller(responses: list[HttpResponse]) -> tuple[ProviderCaller, ScriptedTransport]:
    """A caller over the lane's one permitted double, with in-memory raw and ledger sinks."""
    transport = ScriptedTransport(list(responses))
    caller = ProviderCaller(
        transport=transport,
        raw_sink=BufferedRawSink(),
        ledger=BufferedLedger(),
        now=lambda: datetime(2026, 9, 10, tzinfo=UTC),
    )
    return caller, transport


def _client(responses: list[HttpResponse]) -> tuple[ExaWebsetsClient, ScriptedTransport]:
    caller, transport = _caller(responses)
    return ExaWebsetsClient(caller, SecretStr("k"), usd_per_credit=USD_PER_CREDIT), transport


def _item(item_id: str, url: str, name: str, *, yes: bool) -> dict[str, Any]:
    """One ``webset_item``, in the shape ``hybrid_webset_items.json`` recorded from the wire."""
    return {
        "id": item_id,
        "object": "webset_item",
        "source": "search",
        "sourceId": "wsearch_1",
        "websetId": "webset_1",
        "properties": {
            "type": "company",
            "url": url,
            "description": f"{name} sells software to independent small businesses.",
            "company": {
                "name": name,
                "location": "San Francisco, United States",
                "employees": 52,
                "foundedYear": 2023,
                "headquarters": {
                    "address": None,
                    "city": "San Francisco",
                    "state": "California",
                    "postalCode": None,
                    "country": "United States",
                    "countryCode": "US",
                },
                "financials": {
                    "revenueAnnual": 4000000,
                    "fundingTotal": 12000000,
                    "fundingLatestRound": None,
                },
            },
        },
        "evaluations": [
            {
                "criterion": "Company is headquartered in the United States",
                "reasoning": "The profile lists San Francisco, United States.",
                "satisfied": "yes",
                "references": [{"title": name, "snippet": "San Francisco", "url": url}],
            },
            {
                "criterion": "Company raised a Series A within the last 24 months",
                "reasoning": "The most recent announced round.",
                "satisfied": "yes" if yes else "no",
                "references": [],
            },
        ],
        "enrichments": [],
        "createdAt": "2026-09-10T11:09:45.397Z",
        "updatedAt": "2026-09-10T11:09:45.397Z",
    }


def _response(body: dict[str, Any], *, status: int = 200) -> HttpResponse:
    return HttpResponse(status=status, body=json.dumps(body).encode())


# -- creating a webset --------------------------------------------------------------------------


def test_create_posts_company_entity_criteria_and_recall() -> None:
    body = {
        "id": "webset_1",
        "status": "running",
        "searches": [
            {
                "id": "ws_1",
                "status": "running",
                "count": 35,
                "criteria": [{"description": "US", "successRate": None}],
                "progress": {"found": 0, "analyzed": 0},
            }
        ],
    }
    client, transport = _client([_response(body, status=201)])

    view = client.create(
        query="ICP", count=35, criteria=["US", "Series A"], external_id="run-1", title="R4 run-1"
    )

    sent = json.loads(transport.requests[0].body)
    assert sent["search"] == {
        "query": "ICP",
        "count": 35,
        "entity": {"type": "company"},
        "criteria": [{"description": "US"}, {"description": "Series A"}],
        "recall": True,
    }
    assert sent["externalId"] == "run-1" and view.webset_id == "webset_1"
    assert view.searches[0].count == 35
    assert view.searches[0].search_id == "ws_1" and view.searches[0].status == "running"
    assert view.searches[0].criteria_success_rates == (("US", None),)
    assert transport.requests[0].url.endswith(WEBSETS_BASE_PATH)


def test_create_reserves_ten_credits_per_requested_result_and_records_no_cost_of_its_own() -> None:
    """Law 2's reservation is the whole webset; the bill itself is read on the items page.

    Recording the estimate as spend here as well would double-count every match — once when the
    search was asked for and once when its results were read.
    """
    ledger = BufferedLedger()
    transport = ScriptedTransport([_response({"id": "webset_1", "status": "running"})])
    caller = ProviderCaller(
        transport=transport,
        raw_sink=BufferedRawSink(),
        ledger=ledger,
        now=lambda: datetime(2026, 9, 10, tzinfo=UTC),
    )
    client = ExaWebsetsClient(caller, SecretStr("k"), usd_per_credit=USD_PER_CREDIT)

    client.create(query="ICP", count=25, criteria=["US"], external_id="run-1", title="t")

    rows = ledger.drain()
    assert [row.phase for row in rows] == ["estimate", "result"]
    assert rows[0].estimate_usd == Decimal(25 * CREDITS_PER_MATCH) * USD_PER_CREDIT
    assert rows[1].cost_usd == Decimal(0)


def test_recall_is_absent_from_the_wire_when_it_was_not_asked_for() -> None:
    client, transport = _client([_response({"id": "webset_1", "status": "running"})])

    client.create(
        query="ICP", count=10, criteria=["US"], external_id="run-1", title="t", recall=False
    )

    assert "recall" not in json.loads(transport.requests[0].body)["search"]


# -- reading a webset ---------------------------------------------------------------------------


def test_get_sends_no_body_and_reads_the_search_progress() -> None:
    """A GET with a JSON body would put the literal ``null`` on the wire."""
    body = {
        "id": "webset_1",
        "status": "idle",
        "searches": [
            {
                "id": "ws_1",
                "status": "completed",
                "count": 35,
                "criteria": [
                    {"description": "US", "successRate": 83.39},
                    {"description": "Series A", "successRate": 8.31},
                ],
                "progress": {"found": 15, "analyzed": 333, "completion": 100},
                "recall": None,
            }
        ],
    }
    client, transport = _client([_response(body)])

    view = client.get("webset_1")

    assert transport.requests[0].method == "GET" and transport.requests[0].body is None
    assert transport.requests[0].url.endswith(f"{WEBSETS_BASE_PATH}/webset_1")
    assert view.status == "idle"
    search = view.searches[0]
    assert (search.found, search.analyzed) == (15, 333)
    assert search.recall_estimate is None
    assert search.criteria_success_rates == (("US", 83.39), ("Series A", 8.31))


def test_a_recall_estimate_is_read_wherever_exa_reports_it() -> None:
    """The estimate is newer than any shape we recorded, so it is read defensively."""
    client, _ = _client(
        [
            _response(
                {
                    "id": "webset_1",
                    "status": "idle",
                    "searches": [
                        {"id": "ws_1", "status": "completed", "count": 35, "recall": 1200},
                        {
                            "id": "ws_2",
                            "status": "completed",
                            "count": 35,
                            "recall": {"estimate": 480, "confidence": "medium"},
                        },
                    ],
                }
            )
        ]
    )

    view = client.get("webset_1")

    assert [search.recall_estimate for search in view.searches] == [1200, 480]


# -- the items page -----------------------------------------------------------------------------


def test_items_follow_the_cursor_map_the_company_record_and_price_the_all_green_rows() -> None:
    page1 = {
        "data": [_item("witem_1", "https://probook.com", "Probook", yes=True)],
        "hasMore": True,
        "nextCursor": "c2",
    }
    page2 = {"data": [_item("witem_2", "https://lassie.ai", "Lassie", yes=False)], "hasMore": False}
    client, transport = _client([_response(page1), _response(page2)])

    result = client.items("webset_1")

    assert [item.name for item in result.items] == ["Probook", "Lassie"]
    assert result.items[0].hq_country_code == "US" and result.items[0].employees == 52
    assert result.items[0].hq_city == "San Francisco" and result.items[0].hq_state == "California"
    assert result.items[0].revenue_annual == 4000000
    assert result.items[0].funding_total == 12000000
    assert result.items[0].search_id == "wsearch_1"
    assert result.items[0].url == "https://probook.com"
    assert result.all_green == 1 and result.credits_est == 10
    assert result.cost_usd == Decimal("0.0449")
    assert "cursor=c2" in transport.requests[1].url
    assert "limit=100" in transport.requests[0].url and "cursor" not in transport.requests[0].url
    assert len(result.raw_refs) == 2 and len(result.ledger_row_ids) == 2
    assert result.items[0].evaluations[0]["satisfied"] == "yes"
    assert result.items[1].raw["id"] == "witem_2"


def test_a_single_page_is_one_request_and_its_items_are_priced_once() -> None:
    page = {
        "data": [
            _item("witem_1", "https://probook.com", "Probook", yes=True),
            _item("witem_2", "https://digs.com", "Digs", yes=True),
        ],
        "hasMore": False,
    }
    client, transport = _client([_response(page)])

    result = client.items("webset_1")

    assert len(transport.requests) == 1
    assert result.all_green == 2
    assert result.credits_est == 20
    assert result.cost_usd == websets_items_cost(2, USD_PER_CREDIT)


def test_the_items_cost_is_ten_credits_for_each_row_that_satisfied_every_criterion() -> None:
    assert websets_items_cost(0, USD_PER_CREDIT) == Decimal(0)
    assert websets_items_cost(15, USD_PER_CREDIT) == Decimal(150) * USD_PER_CREDIT
    assert CREDITS_PER_MATCH == 10


# -- adding a search to a live webset -----------------------------------------------------------


def test_add_search_excludes_the_searches_that_already_ran() -> None:
    """A second pass must not be charged again for the companies the first pass already found."""
    client, transport = _client(
        [
            _response(
                {
                    "id": "wsearch_2",
                    "object": "webset_search",
                    "websetId": "webset_1",
                    "status": "running",
                    "count": 20,
                },
                status=201,
            )
        ]
    )

    view = client.add_search(
        "webset_1", query="ICP again", count=20, criteria=["US"], exclude_search_ids=["ws_1"]
    )

    sent = json.loads(transport.requests[0].body)
    assert sent == {
        "query": "ICP again",
        "count": 20,
        "entity": {"type": "company"},
        "criteria": [{"description": "US"}],
        "exclude": [{"source": "search", "id": "ws_1"}],
    }
    assert transport.requests[0].url.endswith(f"{WEBSETS_BASE_PATH}/webset_1/searches")
    assert view.webset_id == "webset_1" and view.searches[0].search_id == "wsearch_2"


# -- money truth --------------------------------------------------------------------------------


def test_a_402_halts_the_provider() -> None:
    caller, _ = _caller(
        [HttpResponse(status=402, body=b'{"error": "You have exceeded your credits limit"}')]
    )
    client = ExaWebsetsClient(caller, SecretStr("k"), usd_per_credit=USD_PER_CREDIT)

    with pytest.raises(ProviderHalted):
        client.get("webset_1")

    assert caller.halted("exa_websets")


def test_only_a_refusal_to_sell_latches_the_provider() -> None:
    assert websets_halt_rule(HttpResponse(status=402, body=b'{"error": "no credits"}')) == (
        "exa websets: no credits"
    )
    assert websets_halt_rule(HttpResponse(status=401, body=b'{"message": "bad key"}')) == (
        "exa websets: bad key"
    )
    assert websets_halt_rule(HttpResponse(status=401, body=b"not json")) == (
        "exa websets: http 401"
    )
    assert websets_halt_rule(HttpResponse(status=404, body=b'{"error": "no such webset"}')) is None
    assert websets_halt_rule(HttpResponse(status=429, body=b"slow down")) is None
    assert websets_halt_rule(_response({"id": "webset_1", "status": "idle"})) is None
