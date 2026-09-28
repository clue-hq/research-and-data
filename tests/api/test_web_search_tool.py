"""web_search@1: the fixed deep-lite request, text out, refusals before spend (spec 2026-09-22)."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from decimal import Decimal

import pytest

from clue_api.arv2.calls import CallCost
from clue_api.arv2.exa_client import ExaHit, ExaSearchResult
from clue_api.web_search_tool import (
    WEB_SEARCH_TOOL_NAME,
    WebSearchInput,
    WebSearchOutput,
    WebSearchTool,
    build_web_search_tools,
    render_web_search,
)
from clue_core import operation_id_from_key
from clue_toolbelt import ToolContext, ToolEffectClass


@asynccontextmanager
async def _no_db() -> AsyncIterator[None]:
    yield None


def _ctx() -> ToolContext:
    return ToolContext(
        workspace_id="ws-search",
        actor="agent",
        conn_factory=_no_db,  # type: ignore[arg-type]
        operation_id=operation_id_from_key("web-search-test", "test"),
    )


def _result(*, output_text: str | None, hits: tuple[ExaHit, ...]) -> ExaSearchResult:
    cost = CallCost(
        cost_usd=Decimal("0.011"),
        credits=Decimal(0),
        media_seconds=0,
        cost_source="metered",
        provider="exa",
        operation="search",
        raw_ref="raw/s",
        ledger_row_id="row-s",
    )
    return ExaSearchResult(
        results=hits,
        status=200,
        cost_usd=Decimal("0.011"),
        request_id="req_s",
        raw_ref="raw/s",
        ledger_row_id="row-s",
        cost=cost,
        output_text=output_text,
    )


class FakeExa:
    def __init__(self, result: ExaSearchResult) -> None:
        self.result = result
        self.calls: list[dict] = []

    def search(self, query: str, **kw: object) -> ExaSearchResult:
        self.calls.append({"query": query, **kw})
        return self.result


HIT = ExaHit(
    url="https://acme.example/summit",
    title="Acme Summit 2026",
    published_date="2026-03-01",
    author=None,
    text=None,
    highlights=("Two days in Austin.", "Tracks for GI practice managers."),
)


def test_descriptor_is_spend_typed_replay_at_least_once_and_unpinned_to_a_skill() -> None:
    tool = WebSearchTool(client_factory=None)
    d = tool.descriptor
    assert d.name == WEB_SEARCH_TOOL_NAME and d.version == "1"
    assert d.effect_class is ToolEffectClass.SPEND
    assert d.recipe_safe and d.replay.operation_id_required
    assert d.pin_requirements == ("project",)
    assert d.parameter_policy.safe_display_fields == (
        "query",
        "num_results",
        "include_domains",
        "exclude_domains",
        "start_published_date",
        "end_published_date",
    )
    assert "Use this last" in d.model_description


def test_it_refuses_before_spend_without_a_key_or_with_a_blank_query() -> None:
    async def scenario() -> None:
        unconfigured = WebSearchTool(client_factory=None)
        failures = await unconfigured.preconditions(WebSearchInput(query="acme summit"), _ctx())
        assert [f.reason_code for f in failures] == ["exa_not_configured"]

        configured = WebSearchTool(
            client_factory=lambda label, raw, ledger: FakeExa(_result(output_text=None, hits=()))
        )
        failures = await configured.preconditions(WebSearchInput(query="   "), _ctx())
        assert [f.reason_code for f in failures] == ["query_empty"]
        assert await configured.preconditions(WebSearchInput(query="acme summit"), _ctx()) == ()

    asyncio.run(scenario())


def test_it_sends_the_fixed_deep_lite_shape_and_only_the_filters_passed() -> None:
    async def scenario() -> None:
        fake = FakeExa(_result(output_text="Acme's summit is in May.", hits=(HIT,)))
        tool = WebSearchTool(client_factory=lambda label, raw, ledger: fake)
        ctx = _ctx()

        plain = WebSearchInput(query="acme summit 2026")
        result = await tool.invoke(plain, ctx)
        call = fake.calls[0]
        assert call["type"] == "deep-lite"
        assert call["output_schema"] == {"type": "text"}
        assert call["highlights"] == {}
        assert call["num_results"] == 10
        assert call["include_domains"] is None and call["exclude_domains"] is None
        assert call["start_published_date"] is None and call["end_published_date"] is None
        assert call["label"].startswith("web_search:")

        filtered = WebSearchInput(
            query="acme summit 2026",
            num_results=3,
            include_domains=["acme.example"],
            exclude_domains=["pinterest.com"],
            start_published_date="2026-01-01",
            end_published_date="2026-06-30",
        )
        await tool.invoke(filtered, ctx)
        call = fake.calls[1]
        assert call["num_results"] == 3
        assert call["include_domains"] == ["acme.example"]
        assert call["exclude_domains"] == ["pinterest.com"]
        assert call["start_published_date"] == "2026-01-01"
        assert call["end_published_date"] == "2026-06-30"

        output = WebSearchOutput.model_validate(result.references)
        assert output.answer == "Acme's summit is in May."
        assert output.results[0].url == HIT.url
        assert output.results[0].highlights == list(HIT.highlights)
        assert output.cost_usd == "0.011" and output.request_id == "req_s"
        assert output.rendered == render_web_search(output.answer, output.results)

    asyncio.run(scenario())


def test_the_rendering_is_the_answer_then_one_block_per_hit() -> None:
    from clue_api.web_search_tool import WebSearchResultItem

    text = render_web_search(
        "Acme's summit is in May.",
        [
            WebSearchResultItem(
                title="Acme Summit 2026",
                url="https://acme.example/summit",
                published_date="2026-03-01",
                highlights=["Two days in Austin."],
            ),
            WebSearchResultItem(
                title=None, url="https://b.example", published_date=None, highlights=[]
            ),
        ],
    )
    assert text == (
        "Acme's summit is in May.\n\n"
        "1. Acme Summit 2026 — https://acme.example/summit (2026-03-01)\n"
        "   - Two days in Austin.\n"
        "2. (untitled) — https://b.example\n"
    )
    assert render_web_search(None, []) == "No results."


def test_an_answerless_search_renders_results_only() -> None:
    async def scenario() -> None:
        fake = FakeExa(_result(output_text=None, hits=(HIT,)))
        tool = WebSearchTool(client_factory=lambda label, raw, ledger: fake)
        result = await tool.invoke(WebSearchInput(query="acme summit"), _ctx())
        output = WebSearchOutput.model_validate(result.references)
        assert output.answer is None
        assert output.rendered.startswith("1. Acme Summit 2026")

    asyncio.run(scenario())


def test_input_bounds_are_enforced_by_the_schema() -> None:
    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        WebSearchInput(query="x" * 401)
    with pytest.raises(ValidationError):
        WebSearchInput(query="q", num_results=11)
    with pytest.raises(ValidationError):
        WebSearchInput(query="q", num_results=0)
    with pytest.raises(ValidationError):
        WebSearchInput(query="q", include_domains=["a"] * 11)
    with pytest.raises(ValidationError):
        WebSearchInput(query="q", exclude_domains=["a"] * 11)


def test_the_builder_is_fail_closed_without_secrets() -> None:
    (tool,) = build_web_search_tools(secrets=None)
    assert isinstance(tool, WebSearchTool)

    async def scenario() -> None:
        failures = await tool.preconditions(WebSearchInput(query="q"), _ctx())
        assert [f.reason_code for f in failures] == ["exa_not_configured"]

    asyncio.run(scenario())
