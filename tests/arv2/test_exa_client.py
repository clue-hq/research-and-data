"""The Exa client's pure parts: request shaping, the law-4 guard, and the two output schemas.

Global Constraint 3 keeps provider *behaviour* live — nothing here fakes an Exa response. What is
unit-tested is what a live call cannot demonstrate: that an option the caller did not pass is
absent from the wire (a live 200 looks identical either way), that the silent-fail guard's
arithmetic is right at its boundaries (a real thin response cannot be summoned on demand), and
that the shipped schemas still match the contracts they were copied from.
"""

from __future__ import annotations

import json
from decimal import Decimal
from typing import Any

import pytest

from clue_api.arv2.exa_client import (
    THIN_MAX_COST_USD,
    THIN_MAX_RESULTS,
    THIN_MIN_REPORT_CHARS,
    ExaDeepResult,
    ExaHit,
    _is_richer,
    contents_body,
    deep_reasoning_body,
    exa_halt_rule,
    is_thin_deep_response,
    product_catalog_output_schema,
    report_output_schema,
    search_body,
)
from clue_api.arv2.transport import HttpResponse


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
        retried=False,
    )


# -- request shaping ---------------------------------------------------------------------------


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
