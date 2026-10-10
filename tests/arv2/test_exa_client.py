"""The Exa client's pure parts: request shaping, the law-4 guard, and the two output schemas.

Global Constraint 3 keeps provider *behaviour* live — nothing here fakes an Exa response. What is
unit-tested is what a live call cannot demonstrate: that an option the caller did not pass is
absent from the wire (a live 200 looks identical either way), that the silent-fail guard's
arithmetic is right at its boundaries (a real thin response cannot be summoned on demand), and
that the shipped schemas still match the contracts they were copied from.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

import pytest
from pydantic import SecretStr

from clue_api.arv2.calls import CallCost, ProviderCaller
from clue_api.arv2.errors import ProviderHalted
from clue_api.arv2.exa_client import (
    ANSWER_ESTIMATE_USD,
    THIN_MAX_COST_USD,
    THIN_MAX_RESULTS,
    THIN_MIN_REPORT_CHARS,
    ExaClient,
    ExaDeepResult,
    ExaHit,
    _is_richer,
    answer_body,
    contents_body,
    deep_reasoning_body,
    exa_halt_rule,
    is_thin_deep_response,
    product_catalog_output_schema,
    report_output_schema,
    search_body,
)
from clue_api.arv2.provider_ledger import BufferedLedger, BufferedRawSink
from clue_api.arv2.transport import HttpResponse, ScriptedTransport


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


def _count_properties(schema: Any) -> int:
    """Every property declared anywhere in a JSON schema, at any depth."""
    total = 0
    if isinstance(schema, dict):
        properties = schema.get("properties")
        if isinstance(properties, dict):
            total += len(properties)
        for value in schema.values():
            total += _count_properties(value)
    elif isinstance(schema, list):
        for item in schema:
            total += _count_properties(item)
    return total


def _deep(output_text: str, n_results: int) -> ExaDeepResult:
    return ExaDeepResult(
        output_text=output_text,
        output_object=None,
        report_text=None,
        grounding=None,
        results=tuple(
            ExaHit(
                url=f"https://example.test/{i}",
                title=None,
                published_date=None,
                author=None,
                text=None,
                highlights=(),
            )
            for i in range(n_results)
        ),
        status=200,
        cost_usd=Decimal("0.05"),
        request_id="req",
        raw_ref=None,
        ledger_row_id="row",
        cost=CallCost(
            cost_usd=Decimal("0.05"),
            credits=Decimal(0),
            media_seconds=0,
            cost_source="metered",
            ledger_row_id="row",
            raw_ref=None,
            provider="exa",
            operation="deep-reasoning",
        ),
        retried=False,
    )


# -- request shaping ---------------------------------------------------------------------------


def test_optional_link_and_image_extras_reach_search_and_contents_without_changing_defaults():
    extras = {"links": 10, "imageLinks": 3}
    search = search_body("public interviews", extras=extras)
    contents = contents_body(["https://example.test/interview"], extras=extras)
    assert search["contents"]["extras"] == contents["extras"] == extras
    extras["links"] = 99
    assert search["contents"]["extras"]["links"] == contents["extras"]["links"] == 10
    assert "extras" not in search_body("public interviews")["contents"]
    assert "extras" not in contents_body(["https://example.test/interview"])


def test_a_search_body_carries_only_the_options_the_caller_passed() -> None:
    """No module-level default may narrow a search the caller did not ask to narrow."""
    body = search_body("zafran security funding")

    assert set(body) == {"query", "type", "numResults", "contents"}
    assert body["type"] == "auto"
    assert body["numResults"] == 8
    assert body["contents"] == {"text": {"maxCharacters": 1500}}
    for absent in (
        "includeDomains",
        "includeText",
        "startPublishedDate",
        "endPublishedDate",
        "category",
    ):
        assert absent not in body


def test_a_search_body_puts_every_option_on_the_wire_when_it_is_passed() -> None:
    body = search_body(
        "zafran security abm manager",
        type="keyword",
        num_results=25,
        include_domains=["jobs.ashbyhq.com"],
        include_text=["Zafran"],
        start_published_date="2025-01-01",
        end_published_date="2026-09-01",
        category="company",
        text_max_chars=2500,
        highlights={"query": "abm", "maxCharacters": 500},
    )

    assert body["type"] == "keyword"
    assert body["numResults"] == 25
    assert body["includeDomains"] == ["jobs.ashbyhq.com"]
    assert body["includeText"] == ["Zafran"]
    assert body["startPublishedDate"] == "2025-01-01"
    assert body["endPublishedDate"] == "2026-09-01"
    assert body["category"] == "company"
    assert body["contents"] == {
        "text": {"maxCharacters": 2500},
        "highlights": {"query": "abm", "maxCharacters": 500},
    }


def test_a_search_body_omits_exclude_domains_and_output_schema_unless_passed() -> None:
    body = search_body("acme conference 2026")
    assert "excludeDomains" not in body
    assert "outputSchema" not in body


def test_a_search_body_carries_exclude_domains_and_output_schema_when_passed() -> None:
    body = search_body(
        "acme conference 2026",
        type="deep-lite",
        exclude_domains=["pinterest.com"],
        output_schema={"type": "text"},
        highlights={},
    )
    assert body["type"] == "deep-lite"
    assert body["excludeDomains"] == ["pinterest.com"]
    assert body["outputSchema"] == {"type": "text"}
    assert body["contents"]["highlights"] == {}


def test_a_search_result_carries_the_written_answer_when_exa_returns_one() -> None:
    """``/search`` with ``type=deep-lite`` and an ``outputSchema`` answers with ``output``."""
    from clue_api.arv2.exa_client import ExaSearchResult, _search_result

    body = {
        "results": [{"url": "https://a.example", "title": "A", "highlights": ["h1"]}],
        "output": "Acme runs its conference in May.",
    }
    result = _search_result(
        body,
        status=200,
        cost=CallCost(
            cost_usd=Decimal("0.01"),
            credits=Decimal(0),
            media_seconds=0,
            cost_source="metered",
            provider="exa",
            operation="search",
            raw_ref="raw/s",
            ledger_row_id="row-s",
        ),
        request_id="req_s",
    )
    assert isinstance(result, ExaSearchResult)
    assert result.output_text == "Acme runs its conference in May."
    assert result.results[0].highlights == ("h1",)
    assert (
        _search_result({"results": []}, status=200, cost=result.cost, request_id=None).output_text
        is None
    )


def test_an_empty_include_domains_list_is_still_sent() -> None:
    """``[]`` is a caller decision, not an absence — only ``None`` means "do not filter"."""
    assert search_body("q", include_domains=[])["includeDomains"] == []


def test_a_contents_body_omits_livecrawl_unless_it_was_asked_for() -> None:
    """Absent ``livecrawl`` is the indexed copy: the cheap answer and the reproducible one."""
    body = contents_body(["https://zafran.io"])

    assert set(body) == {"urls", "text"}
    assert body["text"] == {"maxCharacters": 8000}
    assert contents_body(["https://zafran.io"], livecrawl="always")["livecrawl"] == "always"
    assert contents_body(["https://zafran.io"], highlights={"query": "x"})["highlights"] == {
        "query": "x"
    }


def test_a_deep_reasoning_body_pins_the_type_and_disables_streaming() -> None:
    """``stream`` false is load-bearing: law 1 saves a whole body, and a stream has none."""
    schema = report_output_schema()
    body = deep_reasoning_body(system_prompt="sys", query="charter", output_schema=schema)

    assert body["type"] == "deep-reasoning"
    assert body["stream"] is False
    assert body["systemPrompt"] == "sys"
    assert body["numResults"] == 20
    assert body["contents"] == {"text": {"maxCharacters": 10000}}
    assert body["outputSchema"] == schema
    assert "additionalQueries" not in body
    assert "includeDomains" not in body
    assert "highlights" not in body["contents"]


def test_a_deep_reasoning_body_carries_the_optional_passes_when_asked() -> None:
    body = deep_reasoning_body(
        system_prompt="sys",
        query="charter",
        output_schema=product_catalog_output_schema(),
        num_results=40,
        additional_queries=["zafran platform"],
        include_domains=["zafran.io"],
        text_max_chars=5000,
        highlights_query="products",
        highlights_max_chars=1500,
    )

    assert body["numResults"] == 40
    assert body["additionalQueries"] == ["zafran platform"]
    assert body["includeDomains"] == ["zafran.io"]
    assert body["contents"] == {
        "text": {"maxCharacters": 5000},
        "highlights": {"query": "products", "maxCharacters": 1500},
    }


def test_the_output_schema_is_copied_not_aliased() -> None:
    """A caller mutating the body must not reach the schema object it passed in."""
    schema = report_output_schema()
    body = deep_reasoning_body(system_prompt="s", query="q", output_schema=schema)

    body["outputSchema"]["required"] = ["something-else"]

    assert schema["required"] == ["report"]


# -- the silent-fail guard (Appendix A law 4) --------------------------------------------------


@pytest.mark.parametrize(
    ("n_results", "cost", "report_chars", "expected"),
    [
        # The proof-of-concept's signature: few results AND a floor-level cost.
        (9, Decimal("0.016"), None, True),
        (2, Decimal("0.004"), None, True),
        # One tell alone is not the signature.
        (10, Decimal("0.016"), None, False),
        (9, Decimal("0.017"), None, False),
        (20, Decimal("0.052"), None, False),
        # A report schema adds an independent tell that overrides a healthy result count.
        (20, Decimal("0.052"), THIN_MIN_REPORT_CHARS - 1, True),
        (20, Decimal("0.052"), THIN_MIN_REPORT_CHARS, False),
        (20, Decimal("0.052"), 42000, False),
        # An unmetered call counts as free: unknown cost must not hide the failure.
        (5, None, None, True),
        (30, None, None, False),
    ],
)
def test_the_guard_recognises_the_silent_fail_signature(
    n_results: int, cost: Decimal | None, report_chars: int | None, expected: bool
) -> None:
    assert (
        is_thin_deep_response(n_results=n_results, cost_usd=cost, report_chars=report_chars)
        is expected
    )


def test_the_guard_boundaries_are_the_documented_constants() -> None:
    """The thresholds a reader sees in the docstring are the ones the arithmetic uses."""
    assert is_thin_deep_response(
        n_results=THIN_MAX_RESULTS, cost_usd=THIN_MAX_COST_USD, report_chars=None
    )
    assert not is_thin_deep_response(
        n_results=THIN_MAX_RESULTS + 1, cost_usd=THIN_MAX_COST_USD, report_chars=None
    )


def test_a_retry_is_kept_only_when_it_actually_bought_more() -> None:
    """A tie keeps the incumbent — it is already paid for, and a coin-flip is not an improvement."""
    incumbent = _deep("x" * 1000, 12)

    assert _is_richer(_deep("x" * 5000, 20), incumbent)
    assert _is_richer(_deep("x" * 1000, 13), incumbent)
    assert not _is_richer(_deep("x" * 1000, 12), incumbent)
    assert not _is_richer(_deep("x" * 200, 30), incumbent)


# -- the shipped output schemas ----------------------------------------------------------------


def test_the_report_schema_is_the_one_required_string_property_shape() -> None:
    """One property, exactly: a multi-property schema splits the model's budget off the dossier."""
    schema = report_output_schema()

    assert json.loads(json.dumps(schema)) == schema
    assert _count_properties(schema) == 1
    assert schema["required"] == ["report"]
    assert schema["properties"]["report"]["type"] == "string"
    assert report_output_schema() is not schema, "a fresh dict per call, never a shared constant"


def test_the_product_catalog_schema_matches_the_contract() -> None:
    """``ARV2-PRODUCT-CATALOG-CONTRACT.md`` §3, copied exactly: depth 2, no citation fields.

    §3's prose says "nine properties" but the JSON block directly underneath it declares **eight**
    (``coverage_note`` and ``products`` at the top, six inside ``products.items``). The JSON is
    what the contract instructs be copied exactly, so eight is asserted here and the prose's count
    is recorded as a documentation discrepancy rather than reconciled by inventing a property.
    Either count sits under Exa's documented cap of ten.
    """
    schema = product_catalog_output_schema()

    assert json.loads(json.dumps(schema)) == schema
    assert _count_properties(schema) == 8
    assert schema["required"] == ["products"]
    item = schema["properties"]["products"]["items"]
    assert item["required"] == ["name", "short_description", "offering_kind"]
    assert set(item["properties"]) == {
        "name",
        "short_description",
        "offering_kind",
        "family",
        "lifecycle",
        "official_url",
    }
    assert item["properties"]["offering_kind"]["enum"] == [
        "product",
        "platform",
        "integration",
        "partner_program",
        "service",
    ]
    assert item["properties"]["lifecycle"]["enum"] == ["active", "beta", "sunset", "unknown"]
    # The identity ladder reads ``official_url`` as evidence and ``name`` as the page's own
    # spelling, so §3's two descriptions are the request's half of that contract (2026-09-09).
    assert item["properties"]["name"]["description"] == (
        "The offering's name exactly as its official_url page writes it, keeping that page's "
        "spelling, spacing and capitalisation."
    )
    assert item["properties"]["official_url"]["description"] == (
        "The page on the company's own domain where this offering is presented; a page may "
        "present several offerings. Not the homepage, a pricing page or a blog post. Omit only "
        "if no such page exists."
    )
    flat = json.dumps(schema)
    for citation_field in ("citation", "grounding", "source_url", "quote"):
        assert citation_field not in flat, "§3: citation fields must not appear in the schema"


# -- money truth (master plan §2 item 3) -------------------------------------------------------


def test_only_a_refusal_latches_the_provider() -> None:
    """A pure predicate over a status and a body — no transport, no replayed Exa behaviour.

    Worth pinning because the dangerous direction is a *false* latch: "credit" appears constantly
    in the successful output of a dossier about a fintech account, so a naive body scan would take
    the whole provider offline on the strength of a research answer. The word only condemns a
    response that already failed.
    """
    assert exa_halt_rule(HttpResponse(status=402, body=b"{}")) == "payment_required"
    assert exa_halt_rule(HttpResponse(status=403, body=b"{}")) == "forbidden"
    assert exa_halt_rule(HttpResponse(status=400, body=b'{"error":"out of credits"}')) == (
        "credit_exhausted"
    )
    assert exa_halt_rule(HttpResponse(status=400, body=b'{"error":"bad schema"}')) is None
    assert exa_halt_rule(HttpResponse(status=429, body=b"slow down")) is None
    assert (
        exa_halt_rule(HttpResponse(status=200, body=b'{"report":"they sell credit cards"}')) is None
    )


# -- the answer surface (R4's per-gate verifier) ------------------------------------------------


def test_answer_body_carries_prompt_schema_and_text() -> None:
    body = answer_body("Q?", system_prompt="S", output_schema={"type": "object"}, model="exa")
    assert body == {
        "query": "Q?",
        "model": "exa",
        "text": True,
        "systemPrompt": "S",
        "outputSchema": {"type": "object"},
    }


def test_answer_returns_the_structured_object_and_citations_with_text() -> None:
    payload = {
        "requestId": "r1",
        "answer": {
            "verdict": "fail",
            "reasoning": "Series B",
            "evidence_quote": "our Series B",
            "evidence_url": "https://avoca.ai/blog",
            "evidence_date": "2026-04-27",
        },
        "citations": [
            {
                "url": "https://avoca.ai/blog",
                "title": "Why",
                "publishedDate": "2026-04-27T00:00:00.000Z",
                "text": "Today, we announced our Series B",
            }
        ],
        "costDollars": {"total": 0.005},
    }
    caller, transport = _caller([HttpResponse(status=200, body=json.dumps(payload).encode())])

    result = ExaClient(caller, SecretStr("k")).answer(
        "Q?", system_prompt="S", output_schema={"type": "object"}
    )

    assert result.answer == payload["answer"]
    assert result.citations[0].url == "https://avoca.ai/blog"
    assert result.citations[0].text is not None and result.citations[0].text.startswith("Today")
    assert result.citations[0].published_date == "2026-04-27T00:00:00.000Z"
    assert result.cost_usd == Decimal("0.005") and result.request_id == "r1"
    sent = json.loads(transport.requests[0].body)
    assert sent["outputSchema"] == {"type": "object"} and transport.requests[0].url.endswith(
        "/answer"
    )


def test_an_answer_that_is_prose_or_absent_is_reported_as_it_came() -> None:
    """A schema-less answer is a string and a missing one is ``None`` — neither is rounded."""
    prose_caller, _ = _caller(
        [HttpResponse(status=200, body=json.dumps({"answer": "Series B, April 2026"}).encode())]
    )
    prose = ExaClient(prose_caller, SecretStr("k")).answer(
        "Q?", system_prompt="S", output_schema={"type": "object"}
    )
    assert prose.answer == "Series B, April 2026"
    assert prose.citations == () and prose.cost_usd is None

    empty_caller, _ = _caller([HttpResponse(status=200, body=b"{}")])
    empty = ExaClient(empty_caller, SecretStr("k")).answer(
        "Q?", system_prompt="S", output_schema={"type": "object"}
    )
    assert empty.answer is None


def test_the_answer_call_reserves_its_estimate_and_is_ledgered_as_metered() -> None:
    """Law 2's pre-spend row, then law 1's metered settlement off Exa's own ``costDollars``."""
    ledger = BufferedLedger()
    transport = ScriptedTransport(
        [
            HttpResponse(
                status=200,
                body=json.dumps(
                    {"answer": {"verdict": "pass"}, "costDollars": {"total": 0.005}}
                ).encode(),
            )
        ]
    )
    caller = ProviderCaller(
        transport=transport,
        raw_sink=BufferedRawSink(),
        ledger=ledger,
        now=lambda: datetime(2026, 9, 10, tzinfo=UTC),
    )

    result = ExaClient(caller, SecretStr("k")).answer(
        "Q?", system_prompt="S", output_schema={"type": "object"}
    )

    rows = ledger.drain()
    assert [row.phase for row in rows] == ["estimate", "result"]
    assert rows[0].estimate_usd == ANSWER_ESTIMATE_USD
    assert rows[1].cost_usd == Decimal("0.005")
    assert result.cost.cost_source == "metered"
    assert result.ledger_row_id == rows[1].row_id


def test_an_answer_exa_refused_is_ledgered_at_zero_not_at_its_estimate() -> None:
    """Run ``ee79d837``: seven Answer calls refused with 402 were recorded at the one-cent
    estimate each. Exa sold nothing, so the result row says zero."""
    ledger = BufferedLedger()
    caller = ProviderCaller(
        transport=ScriptedTransport(
            [HttpResponse(status=402, body=b'{"error": "You have exceeded your credits limit"}')]
        ),
        raw_sink=BufferedRawSink(),
        ledger=ledger,
        now=lambda: datetime(2026, 9, 10, tzinfo=UTC),
    )

    with pytest.raises(ProviderHalted):
        ExaClient(caller, SecretStr("k")).answer(
            "Q?", system_prompt="S", output_schema={"type": "object"}
        )

    rows = ledger.drain()
    assert rows[0].estimate_usd == ANSWER_ESTIMATE_USD
    assert rows[1].outcome == "halted" and rows[1].cost_usd == Decimal(0)


def test_a_5xx_answer_keeps_the_estimate_because_exa_did_not_say_what_it_did() -> None:
    ledger = BufferedLedger()
    caller = ProviderCaller(
        transport=ScriptedTransport([HttpResponse(status=500, body=b"{}")] * 4),
        raw_sink=BufferedRawSink(),
        ledger=ledger,
        now=lambda: datetime(2026, 9, 10, tzinfo=UTC),
        sleep=lambda seconds: None,
    )

    ExaClient(caller, SecretStr("k")).answer(
        "Q?", system_prompt="S", output_schema={"type": "object"}
    )

    result_row = ledger.drain()[-1]
    assert result_row.cost_usd == ANSWER_ESTIMATE_USD


def test_thin_response_retry_is_logged_separately_from_http_attempts():
    from structlog.testing import capture_logs

    responses = [
        HttpResponse(
            200,
            {},
            json.dumps(
                {
                    "output": {"content": text},
                    "results": [],
                    "costDollars": {"total": 0.05},
                }
            ).encode(),
        )
        for text in ["short", "full report " * 400]
    ]
    caller, transport = _caller(responses)
    client = ExaClient(api_key=SecretStr("test-secret"), caller=caller)
    with capture_logs() as logs:
        result = client.deep_reasoning(
            system_prompt="private system",
            query="private query",
            output_schema={"type": "text"},
            label="person-depth",
        )
    assert result.retried and len(transport.requests) == 2
    retry = next(r for r in logs if r.get("reason") == "thin_response")
    assert retry["label"] == "person-depth" and retry["next_label"] == "person-depth-retry"
    assert retry["report_chars"] == 5 and retry["first_ledger_row_id"]
    assert "private query" not in str(logs) and "test-secret" not in str(logs)


def test_result_rows_keep_rank_order_and_a_short_snippet_per_result() -> None:
    """2026-10-10: search and deep calls return one short row per result, so the receipt preview
    can show what each result says (run 3's preview showed four bare links of ten)."""
    from clue_api.arv2.exa_client import exa_result_rows

    raw = {
        "results": [
            {
                "url": "https://a.test",
                "title": "A",
                "publishedDate": "2026-01-02",
                "highlights": ["First highlight.", "Second highlight."],
                "text": "ignored",
            },
            {"url": "https://b.test", "title": "B", "summary": "A summary.", "text": "ignored"},
            {"url": "https://c.test", "title": "C", "text": "x" * 5000},
            {"title": "No link"},
        ]
    }
    rows = exa_result_rows(raw)
    assert [r["url"] for r in rows] == ["https://a.test", "https://b.test", "https://c.test"]
    assert rows[0] == {
        "url": "https://a.test",
        "title": "A",
        "published": "2026-01-02",
        "text_head": "First highlight. Second highlight.",
    }
    assert rows[1]["text_head"] == "A summary."
    assert len(rows[2]["text_head"]) == 300
    assert exa_result_rows({}) == []
