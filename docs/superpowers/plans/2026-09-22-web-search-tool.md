# `web_search@1` Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Give Head-of-ABM and both design agents one governed open-web search tool, `web_search@1`, over the existing Exa client, used last and returning text that is never a claim.

**Architecture:** One `Tool` in `platform/api/clue_api/web_search_tool.py`, shaped on `exa_search_evidence@1` but calling `ExaClient.search` with `type="deep-lite"`, a text `outputSchema` and highlights. It is registered ungranted in the toolbelt, then granted by two reviewed profile bumps: `head-of-abm@v61` (prompt v14, recipe0-stage0@31, manual v8) and `design@v3`. Design reaches it through the PR #67 platform-reads seam: a fourth method on `DesignPlatformReads` and a fourth LangChain tool in `make_platform_read_tools`, so both harnesses get it from one addition.

**Tech Stack:** Python 3.12 / uv workspace (`uv run pytest`), pydantic tool models (`clue_toolbelt`), the ARV2 `ProviderCaller` + `provider_call_ledger`, YAML profile catalog with sha256 pins, JSON recipe revisions, the generated operating manual (`make manual`), LangChain `@tool` in the design runtime, one TypeScript label map in the frontend.

**Spec:** `docs/superpowers/specs/2026-09-22-web-search-tool-design.md`

## Global Constraints

- Every optional Exa option is ABSENT from the request body unless the caller passed it (client rule: "only what the caller asked for goes on the wire").
- Request shape is fixed: `type="deep-lite"`, `outputSchema={"type": "text"}`, `contents.highlights` on, `numResults ≤ 10`. Nothing else exposed (no `category`, `livecrawl`, text-length knob).
- Search output is text for the agent. No claim is written, no artifact is promoted, no raw-body artifact is kept. The ledger row is the record.
- Effect class `spend`, replay `AT_LEAST_ONCE`, `operation_id_required=True`, `pin_requirements=("project",)` like every other Head-of-ABM tool, NO skill-pin guard, NO per-turn search budget.
- Refusals before spend: `exa_not_configured` (no `CLUE_EXA_API_KEY`), `query_empty` (blank query).
- Ledger stamp is `LedgerStamp(workspace_id=ctx.workspace_id)` on both roles: the invoker's `ToolContext` carries no project id (spec §2.2, corrected 2026-09-22).
- A grant is a reviewed profile bump, never a dict edit: `build_agent_profile_registry` refuses when a role's authority and its profile's pins disagree, and the registry refuses a grant no profile pins.
- Catalog versions are immutable: never edit `head-of-abm/v60`, `design/v2`, prompt `v13`, `manual-*/v7`, or `recipe0-stage0-v30.json`. Mint new versions beside them.
- A catalog `sha256` is the sha256 of the file's raw bytes (`shasum -a 256 <file>`). A tool pin's `input_schema_sha256` / `output_schema_sha256` are read off the live descriptor.
- No new env key or flag. `CLUE_EXA_API_KEY` already exists in `.env.example`.
- Commit messages carry no AI attribution. Local commits only; never push.
- Do not run `make check` or broad suites with a real key in `.env`; run the focused files named in each task (the lane `.env` holds real keys — `tests/api` DB tests need `CLUE_DATABASE_URL` pointing at a throwaway DB, never the lane's `clue_lome`).
- Plain language in every agent-facing sentence (prompt, skill, manual notes, tool description): clear, not condensed.

---

## File map

| File | Responsibility | Task |
| --- | --- | --- |
| `platform/api/clue_api/arv2/exa_client.py` | `search_body` / `ExaClient.search` gain `exclude_domains`, `output_schema`; `ExaSearchResult.output_text` | 1 |
| `tests/arv2/test_exa_client.py` | body-shape tests for the two keys | 1 |
| `platform/api/clue_api/web_search_tool.py` (new) | `WebSearchInput`, `WebSearchResultItem`, `WebSearchOutput`, `WebSearchTool`, `build_web_search_tools`, `render_web_search` | 2 |
| `tests/api/test_web_search_tool.py` (new) | descriptor, refusals, request shape, rendering, ledger drain | 2 |
| `platform/api/clue_api/toolbelt_wiring.py` | register the tool (ungranted) beside the evidence tool | 2 |
| `platform/api/clue_api/agent_registry_wiring.py` | `"web_search": ()` → then `(HEAD_OF_ABM,)` → then `(HEAD_OF_ABM, DESIGN)`; profile versions | 2, 4, 5 |
| `tests/api/test_toolbelt_wiring.py`, `tests/agents/test_tool_authority_audit.py`, `tests/api/test_agent_registry_wiring.py` | counts and grants | 2, 4, 5 |
| `platform/execution/recipes/recipe0-stage0-v31.json` (new) | v30 + `web_search@1` | 3 |
| `platform/api/clue_api/recipe_contracts.py`, `recipe_wiring.py`, `conversation_turns.py`, `stage0_recipe.py` | admit the address, pin the revision, project pin | 3 |
| `tests/api/test_recipe_contracts.py` | v31 test, operation-bound set | 3 |
| `platform/agents/catalog/prompts/head-of-abm/v14/SYSTEM.md` (new) | v13 + the last-resort paragraph | 4 |
| `platform/agents/catalog/profiles/head-of-abm/v61/profile.yaml` (new) | v60 + `web_search@1` pin, prompt v14, manual v8 | 4 |
| `platform/agents/catalog/manual/tool_notes.yaml` | the `web_search` entry | 4 |
| `platform/agents/clue_agents/manual/build.py` | `MANUAL_VERSION="v8"`, `PROFILE_VERSION="v61"` | 4 |
| `platform/agents/catalog/skills/manual-*/v8/SKILL.md` (15 new) | 4 generated by `make manual`, 11 hand-written re-minted | 4 |
| `apps/frontend/src/features/projects/model/chat-tool-presentation.ts` | `web_search: "Search the web"` | 4 |
| `platform/api/clue_api/chat/composer_context.py` | `head-of-abm@v61` | 4 |
| `tests/agents/test_catalog.py`, `test_manual_builder.py`, `test_manual_drift.py`, `tests/api/test_c8_trial_surface.py`, `test_comprehensive_research_contract.py`, `test_client_knowledge_privacy_s4e.py` | version pins | 4 |
| `platform/agents/catalog/profiles/design/v3/profile.yaml` (new) | v2 + `web_search@1` pin | 5 |
| `platform/api/clue_api/design_platform_reads.py` | `DesignPlatformReads.web_search` | 6 |
| `subsystems/clue-design/apps/agent_runtime/lumen_agent/platform_reads.py` | fourth LangChain tool | 6 |
| `tests/api/test_design_platform_reads_db.py`, `subsystems/clue-design/apps/agent_runtime/tests/test_platform_reads.py` | both halves | 6 |
| `subsystems/clue-design/apps/agent_runtime/knowledge_docs/views/scene/skills/tools/SKILL.md`, `lumen_agent/prompts.py` | the design-side words | 7 |
| `docs/specs/M8B-…roadmap.md`, `docs/specs/ARV2-MASTER-PLAN.md`, `_memory/` | the record | 8 |

---

### Task 1: Two optional keys on the Exa search body

**Files:**
- Modify: `platform/api/clue_api/arv2/exa_client.py:130-150` (`ExaSearchResult`), `:400-437` (`search_body`), `:839-884` (`ExaClient.search`)
- Test: `tests/arv2/test_exa_client.py`

**Interfaces:**
- Produces: `search_body(query, *, ..., exclude_domains: Sequence[str] | None = None, output_schema: Mapping[str, object] | None = None)`; `ExaClient.search(..., exclude_domains=None, output_schema=None)`; `ExaSearchResult.output_text: str | None` (the deep-lite written answer, `None` when Exa sent none).

- [ ] **Step 1: Write the failing tests**

Append to `tests/arv2/test_exa_client.py` (next to `test_a_search_body_puts_every_option_on_the_wire_when_it_is_passed`):

```python
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
    assert _search_result({"results": []}, status=200, cost=result.cost, request_id=None).output_text is None
```

- [ ] **Step 2: Run to verify they fail**

Run: `uv run pytest tests/arv2/test_exa_client.py -q -k "exclude_domains or output_schema or written_answer"`
Expected: FAIL (`search_body() got an unexpected keyword argument 'exclude_domains'`, `ImportError: _search_result`).

- [ ] **Step 3: Implement**

In `exa_client.py`, add the field to `ExaSearchResult` (after `cost: CallCost`):

```python
    #: The written answer a ``type="deep-lite"`` search returns under ``output`` when the caller
    #: sent an ``outputSchema``; ``None`` for every other search. Read with :func:`_read_output`.
    output_text: str | None = None
```

Extend `search_body`'s signature and body:

```python
def search_body(
    query: str,
    *,
    type: str = "auto",
    num_results: int = 8,
    include_domains: Sequence[str] | None = None,
    exclude_domains: Sequence[str] | None = None,
    include_text: Sequence[str] | None = None,
    start_published_date: str | None = None,
    end_published_date: str | None = None,
    category: str | None = None,
    text_max_chars: int = 1500,
    highlights: Mapping[str, object] | None = None,
    output_schema: Mapping[str, object] | None = None,
) -> dict[str, Any]:
    ...
    if exclude_domains is not None:
        body["excludeDomains"] = list(exclude_domains)
    ...
    if output_schema is not None:
        # Copied, never aliased: the same rule ``agent_run_body`` keeps for its schema.
        body["outputSchema"] = dict(output_schema)
    return body
```

Add a pure result builder above `ExaClient` and make `search` use it:

```python
def _search_result(
    body: Mapping[str, Any], *, status: int, cost: CallCost, request_id: str | None,
    raw_ref: str | None = None, ledger_row_id: str = "",
) -> ExaSearchResult:
    """Shape a ``/search`` body. ``output`` is present only for a deep-lite search that sent an
    ``outputSchema``; an empty string is reported as ``None`` so callers test one thing."""
    text, _parsed, _grounding = _read_output(body)
    return ExaSearchResult(
        results=_hits(body.get("results")),
        status=status,
        cost_usd=cost.cost_usd,
        request_id=request_id,
        raw_ref=raw_ref,
        ledger_row_id=ledger_row_id,
        cost=cost,
        output_text=text or None,
    )
```

In `ExaClient.search`, add the two keyword parameters (`exclude_domains: Sequence[str] | None = None`, `output_schema: Mapping[str, object] | None = None`), pass them to `search_body`, and replace the trailing `return ExaSearchResult(...)` with:

```python
        return _search_result(
            body,
            status=result.response.status,
            cost=result.call_cost,
            request_id=result.cost.provider_request_id,
            raw_ref=result.raw_ref,
            ledger_row_id=result.ledger_row_id,
        )
```

(`result.cost.cost_usd` was what `cost_usd` read before; `result.call_cost.cost_usd` is the same number — check `CallResult` in `calls.py` if unsure and keep whichever field the existing code read.)

- [ ] **Step 4: Run the file**

Run: `uv run pytest tests/arv2/test_exa_client.py -q`
Expected: all PASS (the two existing `search_body` tests still pass: the new keys are absent by default).

- [ ] **Step 5: Commit**

```bash
git add platform/api/clue_api/arv2/exa_client.py tests/arv2/test_exa_client.py
git commit -m "feat(exa): excludeDomains and outputSchema on /search, absent unless passed; deep-lite answer on the result"
```

---

### Task 2: The tool, registered ungranted

**Files:**
- Create: `platform/api/clue_api/web_search_tool.py`
- Create: `tests/api/test_web_search_tool.py`
- Modify: `platform/api/clue_api/toolbelt_wiring.py:3120-3135` (register after the evidence tool)
- Modify: `platform/api/clue_api/agent_registry_wiring.py:229-290` (`"web_search": ()`)
- Modify: `tests/api/test_toolbelt_wiring.py` (`_MATRIX`, `_bodies`, counts 141→142 and 161→162), `tests/agents/test_tool_authority_audit.py:164` (141→142), `tests/api/test_agent_registry_wiring.py:291,404` (161→162; `web_search@1` ROLE_UNAVAILABLE)

**Interfaces:**
- Consumes: `ExaClient.search(query, *, type, num_results, include_domains, exclude_domains, start_published_date, end_published_date, highlights, output_schema, label)` → `ExaSearchResult` (Task 1).
- Produces: `WEB_SEARCH_TOOL_NAME = "web_search"`; `WebSearchInput(query, num_results=10, include_domains=[], exclude_domains=[], start_published_date=None, end_published_date=None)`; `WebSearchOutput(answer: str | None, results: list[WebSearchResultItem], rendered: str, cost_usd: str, request_id: str | None)`; `WebSearchTool(client_factory=...)`; `build_web_search_tools(*, secrets: Secrets | None) -> tuple[Tool, ...]`; `render_web_search(answer, results) -> str`.

- [ ] **Step 1: Write the failing tests**

`tests/api/test_web_search_tool.py`:

```python
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

        configured = WebSearchTool(client_factory=lambda label, raw, ledger: FakeExa(_result(output_text=None, hits=())))
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
            WebSearchResultItem(title=None, url="https://b.example", published_date=None, highlights=[]),
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
```

- [ ] **Step 2: Run to verify it fails**

Run: `uv run pytest tests/api/test_web_search_tool.py -q`
Expected: FAIL with `ModuleNotFoundError: clue_api.web_search_tool`.

- [ ] **Step 3: Write the module**

`platform/api/clue_api/web_search_tool.py`:

```python
"""``web_search@1`` — one open-web search for Head-of-ABM and the design agents, used LAST
(spec ``docs/superpowers/specs/2026-09-22-web-search-tool-design.md``).

The model authors a query, a result count and optional domain / date filters. Everything else that
shapes the request is fixed here — ``type="deep-lite"``, a text ``outputSchema``, highlights on —
so there is exactly one request shape to review. The tool writes no domain state and keeps no
raw-body artifact; its only durable trace is the row on ``provider_call_ledger``. What it returns
is text for the agent to read in the turn: never a claim, never verified, never presented as
research the platform did.

It refuses before any spend when Exa is not configured or the query is blank, and it registers
unconditionally so the C6 authority audit sees the same registry shape in every process.
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable, Sequence
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any, ClassVar, Protocol

from pydantic import Field, SecretStr

from clue_api.arv2.calls import ProviderCaller
from clue_api.arv2.exa_client import ExaClient, ExaSearchResult
from clue_api.arv2.provider_ledger import (
    BufferedLedger,
    BufferedRawSink,
    LedgerStamp,
    drain_provider_calls,
)
from clue_api.arv2.sinks import LedgerSink, RawSink
from clue_api.arv2.transport import HttpxTransport
from clue_config import Secrets
from clue_toolbelt import (
    ExternalReplayBoundary,
    JournalParameterPolicy,
    PreconditionFailure,
    ReplayPolicy,
    ReplaySafety,
    Tool,
    ToolContext,
    ToolEffectClass,
    ToolEstimate,
    ToolInput,
    ToolOutput,
    ToolResult,
)

__all__ = [
    "WEB_SEARCH_TOOL_NAME",
    "WebSearchInput",
    "WebSearchOutput",
    "WebSearchResultItem",
    "WebSearchTool",
    "build_web_search_tools",
    "render_web_search",
]

WEB_SEARCH_TOOL_NAME = "web_search"
_ESTIMATE_CENTS = Decimal("1")
_SEARCH_TYPE = "deep-lite"
_OUTPUT_SCHEMA: dict[str, object] = {"type": "text"}
_HIGHLIGHTS: dict[str, object] = {}
_MAX_RESULTS = 10


class ExaSearchSurface(Protocol):
    def search(
        self,
        query: str,
        *,
        type: str = "auto",
        num_results: int = 8,
        include_domains: Sequence[str] | None = None,
        exclude_domains: Sequence[str] | None = None,
        start_published_date: str | None = None,
        end_published_date: str | None = None,
        highlights: dict[str, object] | None = None,
        output_schema: dict[str, object] | None = None,
        label: str = "exa-search",
    ) -> ExaSearchResult: ...


class WebSearchInput(ToolInput):
    query: str = Field(min_length=1, max_length=400)
    num_results: int = Field(default=_MAX_RESULTS, ge=1, le=_MAX_RESULTS)
    include_domains: list[str] = Field(default_factory=list, max_length=10)
    exclude_domains: list[str] = Field(default_factory=list, max_length=10)
    start_published_date: str | None = Field(default=None, max_length=32)
    end_published_date: str | None = Field(default=None, max_length=32)


class WebSearchResultItem(ToolOutput):
    title: str | None
    url: str | None
    published_date: str | None
    highlights: list[str]


class WebSearchOutput(ToolOutput):
    answer: str | None
    results: list[WebSearchResultItem]
    rendered: str
    cost_usd: str
    request_id: str | None


def render_web_search(answer: str | None, results: Sequence[WebSearchResultItem]) -> str:
    """The text the agent reads: the written answer, then one block per hit."""
    blocks: list[str] = []
    if answer:
        blocks.append(answer.strip() + "\n")
    lines: list[str] = []
    for index, item in enumerate(results, start=1):
        head = f"{index}. {item.title or '(untitled)'} — {item.url or '(no url)'}"
        if item.published_date:
            head += f" ({item.published_date})"
        lines.append(head)
        lines.extend(f"   - {passage}" for passage in item.highlights)
    if lines:
        blocks.append("\n".join(lines) + "\n")
    return "\n".join(blocks) if blocks else "No results."


def _fail(code: str, message: str) -> tuple[PreconditionFailure, ...]:
    return (PreconditionFailure(reason_code=code, message=message),)


class WebSearchTool(Tool):
    name = WEB_SEARCH_TOOL_NAME
    version = "1"
    model_description = (
        "Search the open web and read back what it found: a short written answer, then up to ten "
        "results with title, URL, date and highlighted passages. Use this last. What the platform "
        "has already researched is in the claim store and in the seller's knowledge files, and "
        "those come first, every time. Reach for this only when you have looked there and what "
        "you need is not there, or is vague or inconclusive, or when the human has brought you "
        "something the platform never researched, like an event, a workshop or a topic outside "
        "the seller's products. What it returns is text for you to read and use now. It is not a "
        "claim, it is not verified, and it must not be presented as research the platform did."
    )
    input_model: ClassVar[type[ToolInput]] = WebSearchInput
    output_model: ClassVar[type[ToolOutput]] = WebSearchOutput
    effect_class = ToolEffectClass.SPEND
    replay = ReplaySafety(
        policy=ReplayPolicy.AT_LEAST_ONCE,
        durable_identity=(
            "ARV2 ledger row on provider_call_ledger keyed on the call; the tool writes no "
            "domain state"
        ),
        operation_id_required=True,
        external_boundary=ExternalReplayBoundary.AT_LEAST_ONCE,
        notes=(
            "A retry may repeat one Exa search and land a second ledger row for it — money spent "
            "twice is recorded twice; no domain row is written, so nothing converges."
        ),
    )
    parameter_policy = JournalParameterPolicy(
        safe_display_fields=(
            "query",
            "num_results",
            "include_domains",
            "exclude_domains",
            "start_published_date",
            "end_published_date",
        )
    )
    # The same project pin every other head-of-abm tool declares (the execution's own project,
    # added by `Stage0StepPinProvider`); NO skill pin — the profile grant and the prompt govern
    # when this is used, and the design role has no skill catalog to pin.
    pin_requirements = ("project",)

    def __init__(
        self,
        *,
        client_factory: Callable[[str, RawSink, LedgerSink], ExaSearchSurface] | None,
    ) -> None:
        self._client_factory = client_factory

    async def preconditions(
        self, inputs: ToolInput, ctx: ToolContext
    ) -> Sequence[PreconditionFailure]:
        del ctx
        assert isinstance(inputs, WebSearchInput)
        if self._client_factory is None:
            return _fail("exa_not_configured", "CLUE_EXA_API_KEY is not configured in this process")
        if not inputs.query.strip():
            return _fail("query_empty", "write the question you want the web searched for")
        return ()

    def estimate(self, inputs: ToolInput) -> ToolEstimate:
        del inputs
        return ToolEstimate(cost_cents=_ESTIMATE_CENTS, detail={"basis": "exa_search_deep_lite"})

    async def invoke(self, inputs: ToolInput, ctx: ToolContext) -> ToolResult:
        assert isinstance(inputs, WebSearchInput)
        assert self._client_factory is not None
        label = f"{self.name}:{ctx.operation_id}"
        raw, ledger = BufferedRawSink(), BufferedLedger()
        client = self._client_factory(label, raw, ledger)
        try:
            result = await asyncio.to_thread(
                lambda: client.search(
                    inputs.query.strip(),
                    type=_SEARCH_TYPE,
                    num_results=inputs.num_results,
                    include_domains=list(inputs.include_domains) or None,
                    exclude_domains=list(inputs.exclude_domains) or None,
                    start_published_date=inputs.start_published_date,
                    end_published_date=inputs.end_published_date,
                    highlights=dict(_HIGHLIGHTS),
                    output_schema=dict(_OUTPUT_SCHEMA),
                    label=label,
                )
            )
        finally:
            # The call's rows are money whatever its outcome. No artifact store: the raw body is
            # not kept (spec §2.1), so ``artifacts=None`` and the rows cite nothing. The context
            # carries no project, so this is workspace spend (spec §2.2).
            async with ctx.conn_factory() as conn:
                await drain_provider_calls(
                    conn,
                    raw=raw,
                    ledger=ledger,
                    artifacts=None,
                    stamp=LedgerStamp(workspace_id=ctx.workspace_id),
                )
        items = [
            WebSearchResultItem(
                title=hit.title,
                url=hit.url,
                published_date=hit.published_date,
                highlights=list(hit.highlights),
            )
            for hit in result.results
        ]
        output = WebSearchOutput(
            answer=result.output_text,
            results=items,
            rendered=render_web_search(result.output_text, items),
            cost_usd=str(result.cost_usd) if result.cost_usd is not None else "0",
            request_id=result.request_id,
        )
        return ToolResult(
            tool=self.name, version=self.version, references=output.model_dump(mode="json")
        )


def build_web_search_tools(*, secrets: Secrets | None) -> tuple[Tool, ...]:
    """Compose the tool. ``secrets=None`` means *no provider credentials* (fail-closed: the tool
    refuses ``exa_not_configured`` before any spend), exactly as ``build_onboarding_evidence_tools``."""
    key = secrets.exa_api_key if secrets is not None else None
    factory: Callable[[str, RawSink, LedgerSink], ExaSearchSurface] | None = None
    if key is not None and key.get_secret_value().strip():
        secret = SecretStr(key.get_secret_value())

        def build_client(label: str, raw: RawSink, ledger: LedgerSink) -> ExaSearchSurface:
            del label  # the label rides the rows; the sinks are the invocation's
            caller = ProviderCaller(
                transport=HttpxTransport(),
                raw_sink=raw,
                ledger=ledger,
                now=lambda: datetime.now(UTC),
            )
            return ExaClient(caller, secret)

        factory = build_client
    return (WebSearchTool(client_factory=factory),)
```

Check `drain_provider_calls` accepts `artifacts=None` (its docstring says the design lane passes `None`); if the parameter is typed `ArtifactSink | None` it does. If `highlights={}` makes `search_body` emit `"highlights": {}` and Exa rejects an empty object, use `{"maxCharacters": 2000}` instead and update the test's `assert call["highlights"] == {}` accordingly — decide from the live proof, not by guessing; `{}` is what the founder's `highlights: True` maps to in the HTTP API.

- [ ] **Step 4: Run the tool tests**

Run: `uv run pytest tests/api/test_web_search_tool.py -q`
Expected: PASS.

- [ ] **Step 5: Register it ungranted**

In `toolbelt_wiring.py`, next to the `build_onboarding_evidence_tools` import add `from clue_api.web_search_tool import build_web_search_tools`, and after the evidence-tool `for` loop (line ~3131) add:

```python
    # web_search@1 (spec 2026-09-22). Registers in EVERY composition like its neighbour above —
    # the C6 authority audit needs one registry shape — and a missing Exa key is refused in
    # `preconditions`, never by absence. Registered UNGRANTED here: the grants are the reviewed
    # `head-of-abm@v61` and `design@v3` bumps, never a dict edit.
    for tool in build_web_search_tools(secrets=secrets):
        registry.register(tool, make_default=True)
```

In `agent_registry_wiring.py`, in `C6_AGENT_TOOL_AUTHORITY` after the `"run_python": (AgentRole.HEAD_OF_ABM,),` entry add:

```python
    # web_search@1 (spec 2026-09-22): one open-web search, used LAST — after the claim store and
    # the seller's knowledge files — and answering text that is never a claim. Registered
    # UNGRANTED here on the terms every new spend surface arrives on: `build_agent_profile_registry`
    # refuses to compose when a role's authority and its profile's tool list disagree, so the
    # grants are the reviewed `head-of-abm@v61` and `design@v3` bumps, not an edit to this dict.
    "web_search": (),
```

In `tests/api/test_toolbelt_wiring.py`: add to `_MATRIX` (next to `"exa_search_evidence"`):

```python
    # web_search@1: no credentials are handed to the default composition, so the SPEND tool's Exa
    # path is never reached here.
    "web_search": ("precondition", ("exa_not_configured",)),
```

add to `_bodies()`: `"web_search": {"query": "acme summit 2026"},` and bump the four count asserts (lines ~1443, 1484, 1526, 1554): `141 → 142` and `161 → 162`, with a one-line comment `# web_search@1 (2026-09-22), ungranted (141 -> 142 / 161 -> 162).`

In `tests/agents/test_tool_authority_audit.py:164`: `141 → 142` and add:

```python
    # web_search@1 (2026-09-22): registered UNGRANTED; the grants are the reviewed bumps in the
    # tasks that follow (141 -> 142).
    assert C6_AGENT_TOOL_AUTHORITY["web_search"] == ()
    assert c6_roles_for_tool("web_search@1") == ()
```

In `tests/api/test_agent_registry_wiring.py`: both `assert len(by_address) == 161` → `162`, each followed by `assert by_address["web_search@1"].status is AgentCapabilityStatus.ROLE_UNAVAILABLE`.

- [ ] **Step 6: Run the three gate files**

Run: `uv run pytest tests/api/test_toolbelt_wiring.py tests/agents/test_tool_authority_audit.py tests/api/test_agent_registry_wiring.py tests/api/test_recipe_contracts.py tests/architecture/test_provider_tool_schema_gate.py -q`
Expected: PASS. If `test_recipe_contracts.py::test_operation_id_requirements_are_explicit` fails because `web_search@1` is operation-bound, that is Task 3's step; do it there, not here, unless it blocks — then add `"web_search@1"` to `operation_bound` and to the `exactly_operation_idempotent` exclusion set now with the Task 3 comment.

- [ ] **Step 7: Commit**

```bash
git add platform/api/clue_api/web_search_tool.py tests/api/test_web_search_tool.py platform/api/clue_api/toolbelt_wiring.py platform/api/clue_api/agent_registry_wiring.py tests/api/test_toolbelt_wiring.py tests/agents/test_tool_authority_audit.py tests/api/test_agent_registry_wiring.py
git commit -m "feat(toolbelt): web_search@1 — one deep-lite Exa search, text out, registered ungranted"
```

---

### Task 3: Recipe revision 31 admits `web_search@1`

**Files:**
- Create: `platform/execution/recipes/recipe0-stage0-v31.json`
- Modify: `platform/api/clue_api/recipe_contracts.py:~106-116` (`RECIPE_0_TOOL_ADDRESSES`), `platform/api/clue_api/recipe_wiring.py:~135-144` (`SYSTEM_RECIPE_FILENAMES`), `platform/api/clue_api/conversation_turns.py:192` (`CONVERSATION_RECIPE_VERSION`), `platform/api/clue_api/stage0_recipe.py:~475-483` (project-pin set)
- Test: `tests/api/test_recipe_contracts.py`

**Interfaces:**
- Produces: `recipe0-stage0@31` = v30 plus `web_search@1` in `graph.tool_allowlist`, the `stage0_interactions` slot's `dynamic_tool_allowlist` and `requirements`, and `compatibility.nodes.stage0_interactions`. `CONVERSATION_RECIPE_VERSION == 31`.

- [ ] **Step 1: Write the failing tests**

In `tests/api/test_recipe_contracts.py`, change `assert CONVERSATION_RECIPE_VERSION == 30` → `31`, and add after the v30 test:

```python
def test_web_search_mints_recipe_v31_without_rewriting_v30() -> None:
    root = Path(__file__).resolve().parents[2] / "platform" / "execution" / "recipes"
    v30 = json.loads((root / "recipe0-stage0-v30.json").read_text())
    v31 = json.loads((root / "recipe0-stage0-v31.json").read_text())
    # One address JOINS and none leaves: `web_search@1`, granted for the first time at
    # `head-of-abm@v61`. The tool has one version, so v31 is v30 plus exactly this address, and
    # v30 stays the exact replay input for a turn pinned to it.
    added = {"web_search@1"}

    v30_index = SYSTEM_RECIPE_FILENAMES.index("recipe0-stage0-v30.json")
    assert SYSTEM_RECIPE_FILENAMES[v30_index : v30_index + 2] == (
        "recipe0-stage0-v30.json",
        "recipe0-stage0-v31.json",
    )
    assert added.isdisjoint(v30["graph"]["tool_allowlist"])
    assert added <= set(v31["graph"]["tool_allowlist"])
    slot = next(node for node in v31["graph"]["nodes"] if node["node_key"] == "stage0_interactions")
    assert added <= set(slot["dynamic_tool_allowlist"])
    slot_requirements = {
        (item["key"], item["version"]) for item in slot["requirements"] if item["kind"] == "tool"
    }
    node_compatibility = {
        (item["key"], item["version"])
        for item in v31["compatibility"]["nodes"]["stage0_interactions"]
        if item["kind"] == "tool"
    }
    joined = {tuple(address.split("@")) for address in added}
    assert joined <= slot_requirements
    assert joined <= node_compatibility
    assert [item for item in slot_requirements if item[0] == "web_search"] == [("web_search", "1")]
    v30_slot = next(node for node in v30["graph"]["nodes"] if node["node_key"] == "stage0_interactions")
    assert set(v30["graph"]["tool_allowlist"]) | added == set(v31["graph"]["tool_allowlist"])
    assert set(v30_slot["dynamic_tool_allowlist"]) | added == set(slot["dynamic_tool_allowlist"])
    v30_requirements = {
        (item["key"], item["version"]) for item in v30_slot["requirements"] if item["kind"] == "tool"
    }
    v30_compatibility = {
        (item["key"], item["version"])
        for item in v30["compatibility"]["nodes"]["stage0_interactions"]
        if item["kind"] == "tool"
    }
    assert v30_requirements | joined == slot_requirements
    assert v30_compatibility | joined == node_compatibility
    assert added <= set(RECIPE_0_TOOL_ADDRESSES)
    assert v30["version"] == 30
    assert v31["version"] == 31
    assert slot["dynamic_pin_kinds"] == v30_slot["dynamic_pin_kinds"]
```

In `test_operation_id_requirements_are_explicit`, add to `operation_bound`:

```python
        # web_search@1 (2026-09-22): operation-bound because its ledger row is keyed on the
        # operation; AT_LEAST_ONCE like `exa_search_evidence@1`, since a retried search cannot
        # converge on one provider call.
        "web_search@1",
```

and add `"web_search@1"` to the set subtracted in the `exactly_operation_idempotent` assertion (beside `"exa_search_evidence@1"`).

- [ ] **Step 2: Run to verify it fails**

Run: `uv run pytest tests/api/test_recipe_contracts.py -q`
Expected: FAIL (v31 file missing; version 30).

- [ ] **Step 3: Mint v31**

```bash
cp platform/execution/recipes/recipe0-stage0-v30.json platform/execution/recipes/recipe0-stage0-v31.json
```

Then edit `recipe0-stage0-v31.json` exactly as v29 was minted from v28 (`diff` the two to see the four sites): `"version": 30` → `31`; in `graph.tool_allowlist` and in the `stage0_interactions` node's `dynamic_tool_allowlist`, after `"run_python@1"` add `"web_search@1"`; in that node's `requirements` and in `compatibility.nodes.stage0_interactions`, after `{"kind": "tool", "key": "run_python", "version": "1"}` add `{"kind": "tool", "key": "web_search", "version": "1"}`. Verify with `diff platform/execution/recipes/recipe0-stage0-v30.json platform/execution/recipes/recipe0-stage0-v31.json` — exactly five hunks (version + four insertions).

In `recipe_contracts.py`, after `"run_python@1",` in `RECIPE_0_TOOL_ADDRESSES`:

```python
    # web_search@1 (recipe0-stage0@31): one deep-lite open-web search, used last, answering text
    # that is never a claim. Granted for the first time at `head-of-abm@v61` and admitted to the
    # interaction slot in the same revision. A SPEND like the launches, AT_LEAST_ONCE on replay,
    # and it declares the same ``project`` pin as its siblings.
    "web_search@1",
```

In `recipe_wiring.py`, after `"recipe0-stage0-v30.json",`:

```python
    # web_search@1 joins the interaction slot, granted for the first time at `head-of-abm@v61`.
    # Nothing leaves — one address ADDED, not a re-pin — so v31 is v30 plus that address and v30
    # stays the exact replay input for turns pinned to it.
    "recipe0-stage0-v31.json",
```

In `conversation_turns.py`: `CONVERSATION_RECIPE_VERSION = 31` with a comment line: `# Revision 31 (web search, 2026-09-22) admits one address and removes none: ``web_search@1``.`

In `stage0_recipe.py`, in the set that lists `"run_python"`, add `"web_search",` with the comment `# ``web_search`` joins at recipe0-stage0@31: its body names no project either; the pin is the execution's own.`

- [ ] **Step 4: Run**

Run: `uv run pytest tests/api/test_recipe_contracts.py tests/api/test_toolbelt_wiring.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add platform/execution/recipes/recipe0-stage0-v31.json platform/api/clue_api/recipe_contracts.py platform/api/clue_api/recipe_wiring.py platform/api/clue_api/conversation_turns.py platform/api/clue_api/stage0_recipe.py tests/api/test_recipe_contracts.py
git commit -m "feat(recipe): recipe0-stage0@31 admits web_search@1; conversation runtime pins 31"
```

---

### Task 4: `head-of-abm@v61` — prompt v14, the grant, manual v8

This is the reviewed bump. Do the steps in this order; the sha pins depend on the files written before them.

**Files:**
- Create: `platform/agents/catalog/prompts/head-of-abm/v14/SYSTEM.md`
- Create: `platform/agents/catalog/profiles/head-of-abm/v61/profile.yaml`
- Create: `platform/agents/catalog/skills/manual-{index,turn,workspace,claims,accounts-research,discovery,documents-decisions,gates-authority,humans-screens,siblings,glossary}/v8/SKILL.md` (11 hand-written re-mints) and `manual-{tools,fields,errors,limits}/v8/SKILL.md` (4 generated)
- Modify: `platform/agents/catalog/manual/tool_notes.yaml` (new `web_search` entry, alphabetical position between `submit_ingestion`/`synthesize_icps`… — put it after `run_python`)
- Modify: `platform/agents/clue_agents/manual/build.py:74,78` (`MANUAL_VERSION = "v8"`, `PROFILE_VERSION = "v61"`)
- Modify: `apps/frontend/src/features/projects/model/chat-tool-presentation.ts:44` (add `web_search: "Search the web",` after `read_artifact`)
- Modify: `platform/api/clue_api/agent_registry_wiring.py` (`AgentRole.HEAD_OF_ABM: "v61"`; `"web_search": (AgentRole.HEAD_OF_ABM,)`)
- Modify: `platform/api/clue_api/chat/composer_context.py:65` (`head-of-abm@v61`)
- Tests: `tests/agents/test_catalog.py`, `tests/agents/test_manual_builder.py:48`, `tests/agents/test_manual_drift.py`, `tests/api/test_agent_registry_wiring.py`, `tests/agents/test_tool_authority_audit.py`, `tests/api/test_c8_trial_surface.py:352`, `tests/api/test_comprehensive_research_contract.py:469-470`, `tests/api/test_client_knowledge_privacy_s4e.py:161`

**Interfaces:**
- Consumes: `web_search@1` descriptor (Task 2), `recipe0-stage0@31` (Task 3).
- Produces: `head-of-abm@v61` active; prompt `head-of-abm@v14`; `manual-*@v8` ×15.

- [ ] **Step 1: Prompt v14**

```bash
mkdir -p platform/agents/catalog/prompts/head-of-abm/v14
cp platform/agents/catalog/prompts/head-of-abm/v13/SYSTEM.md platform/agents/catalog/prompts/head-of-abm/v14/SYSTEM.md
```

Open `v14/SYSTEM.md`. If its frontmatter carries a `version:` line, set it to `v14`. Insert this paragraph immediately after the paragraph that ends `...open the chapter whose summary matches your need before you guess.` (line ~39) and before `Preserve the user's exact statements...`:

```markdown
Look things up in this order. A question about a target account or a contact goes to the claims
first, through `read_account_research` and `read_claims`. A question about the seller — its
products, customers, proof, positioning — goes to the knowledge files under `brand/knowledge/`
first. Only when those come back empty, vague or inconclusive do you turn to `web_search`, and it
is the right tool when the user brings you something the platform never researched: an event the
seller is running, a workshop, a topic outside its products. When part of an answer came from a
web search, say so plainly, so the user knows which facts came from the platform's research and
which from a search you made just now. A search result is text you read; it is never a claim and
never presented as research the platform did.
```

- [ ] **Step 2: The manual notes entry and the frontend label**

In `platform/agents/catalog/manual/tool_notes.yaml`, after the `run_python:` block add:

```yaml
web_search:
  afterwards: >-
    Nothing changes on the platform. You hold the written answer and up to ten results with their
    highlighted passages, and one search has been charged to the workspace. Read it as what a
    search found today, not as a fact the platform verified: quote it as "a search found", never
    as a claim, and never write it into a project document as if research had established it.
    If the search did not settle the question, say so rather than searching again with the same
    words.
  skill_section: head-of-abm prompt v14, the paragraph "Look things up in this order".
  see_also: [claims, accounts-research]
  refusals:
    exa_not_configured: Tell the human web search is not available on this deployment; do not answer the question from memory instead.
    query_empty: Write the question you want searched, in plain words, then call again.
```

In `apps/frontend/src/features/projects/model/chat-tool-presentation.ts`, after `read_artifact: "Open an artifact",` add `web_search: "Search the web",`.

- [ ] **Step 3: Profile v61 with placeholder digests**

```bash
mkdir -p platform/agents/catalog/profiles/head-of-abm/v61
cp platform/agents/catalog/profiles/head-of-abm/v60/profile.yaml platform/agents/catalog/profiles/head-of-abm/v61/profile.yaml
```

Edit `v61/profile.yaml`:
1. `version: v60` → `version: v61`.
2. Replace the v60 header comment (the lines starting `# v60 (...)` down to the next blank-comment boundary) with a v61 comment, keeping the v59/v58 history lines below it:

```yaml
# v61 (web search, spec 2026-09-22): v60's surface with ONE address ADDED — `web_search@1`, one
# deep-lite open-web search granted for the first time — and the prompt that says when it is
# used: pin v13→v14 adds the paragraph "Look things up in this order" (claims first for an
# account or a contact, the seller's knowledge files first for the seller, the web only when
# those come back empty, vague or inconclusive, and the answer says which facts came from a
# search). Its result is text, never a claim. No skill pin: the grant and the prompt govern.
# The conversation recipe moves 30 → 31 (the address joins the interaction slot). The manual
# re-mints at `manual-*@v8` because the grant moved; every hand-written chapter is
# byte-identical to v7 but for its version and paths.
```

3. `prompt:` block: `version: v13` → `version: v14`, `sha256:` → the output of `shasum -a 256 platform/agents/catalog/prompts/head-of-abm/v14/SYSTEM.md`.
4. In `tools:`, after the `submit_ingestion` pin (the list is alphabetical; `web_search` sorts last) add:

```yaml
  # web_search@1 (spec 2026-09-22): one open-web search, used LAST — after the claims and the
  # seller's knowledge files — for what the platform never researched. Text out, never a claim.
  # Digests read off the live descriptor.
  - name: web_search
    version: "1"
    input_schema_sha256: <fill in Step 5>
    output_schema_sha256: <fill in Step 5>
```

5. In `skills:`, every `manual-*` pin: `version: v7` → `version: v8` (15 pins); leave their `sha256:` values for Step 5. Update the comment above them: `They are at v8 because the GRANT moved — web_search@1 joins it, so the generated tools, errors and limits chapters all move — and a catalog version is immutable: v60 keeps the v7 chapters. Every hand-written body is byte-identical to v7 but for its version line and its chapter paths.`

- [ ] **Step 4: Manual v8 — builder constants, hand-written re-mint, generated chapters**

In `platform/agents/clue_agents/manual/build.py`: `MANUAL_VERSION = "v8"`, `PROFILE_VERSION = "v61"`.

Re-mint the eleven hand-written chapters exactly as v6→v7 did (version line + chapter paths, nothing else):

```bash
for c in index turn workspace claims accounts-research discovery documents-decisions gates-authority humans-screens siblings glossary; do
  mkdir -p platform/agents/catalog/skills/manual-$c/v8
  sed -e 's/^version: v7$/version: v8/' -e 's#/manual-\([a-z-]*\)/v7/SKILL.md#/manual-\1/v8/SKILL.md#g' \
    platform/agents/catalog/skills/manual-$c/v7/SKILL.md > platform/agents/catalog/skills/manual-$c/v8/SKILL.md
  diff platform/agents/catalog/skills/manual-$c/v7/SKILL.md platform/agents/catalog/skills/manual-$c/v8/SKILL.md | grep '^[<>]' | grep -v 'v7\|v8' && echo "UNEXPECTED DIFF in $c"
done
```

Every reported diff line must mention v7/v8 and nothing else. Then generate the four chapters:

```bash
make manual
```

Expected: `wrote .../manual-tools/v8/SKILL.md`, `manual-fields/v8`, `manual-errors/v8`, `manual-limits/v8`. If the builder fails with `tool_notes.yaml has no entry for 'web_search'`, Step 2 was skipped. If it fails loading profile v61 on a digest, the profile catalog validated a sha early — put the real digests in (Step 5) and re-run.

Confirm the tools chapter carries the new section and title: `grep -n '^## web_search@1\|head-of-abm@v61' platform/agents/catalog/skills/manual-tools/v8/SKILL.md` — both present, and the tools table row reads `| \`web_search@1\` | spend | yes | no | Search the web |`.

- [ ] **Step 5: Fill every digest**

Tool digests:

```bash
uv run python -c "
from clue_api.toolbelt_wiring import build_toolbelt
d = build_toolbelt(storage=None).descriptor('web_search', '1')
print(d.input_schema_sha256); print(d.output_schema_sha256)"
```

Paste them into the `web_search` pin. Manual digests:

```bash
for c in index turn workspace tools fields claims accounts-research discovery documents-decisions gates-authority humans-screens siblings errors limits glossary; do
  printf '%s ' "manual-$c"; shasum -a 256 platform/agents/catalog/skills/manual-$c/v8/SKILL.md | cut -d' ' -f1
done
```

Paste each into the matching `manual-*` pin in `v61/profile.yaml`. Then `make manual-check` must exit 0 (the generated chapters are current) — note `manual-limits` renders the profile's numbers, which v61 does not change.

- [ ] **Step 6: Flip the registry, the grant and the composer pin**

`agent_registry_wiring.py`: `AgentRole.HEAD_OF_ABM: "v60"` → `"v61"` with this comment above it:

```python
    # v61 (web search, 2026-09-22): v60's surface with `web_search@1` GRANTED — one deep-lite
    # open-web search, used last, text out and never a claim — and prompt pin v13→v14 for the
    # paragraph that orders the lookups (claims, then the seller's files, then the web). The
    # conversation recipe moves 30 → 31; the manual re-mints at `manual-*@v8`.
```

`"web_search": ()` → `"web_search": (AgentRole.HEAD_OF_ABM,)` and amend its comment: `GRANTED at head-of-abm@v61 (2026-09-22); the design role joins at design@v3.`

`composer_context.py`: `PROJECT_CONVERSATION_AGENT_PROFILE_ID = "head-of-abm@v61"` with one comment line: `# v61 grants web_search@1 and pins the prompt that says it comes last.`

- [ ] **Step 7: Move the tests with it**

- `tests/agents/test_catalog.py`: add `"profile:head-of-abm@v61",` after `"profile:head-of-abm@v60",` with a one-line comment (`# web_search@1 granted; prompt v14; manual v8.`), and add `"skill:manual-<name>@v8",` after each `@v7` line for all 15 chapters (lexical order within each chapter's block). Add `"prompt:head-of-abm@v14"` wherever the prompt addresses are enumerated (grep `prompt:head-of-abm@v13`).
- `tests/agents/test_manual_builder.py:48`: `21` → `22` with `# 22 since head-of-abm@v61 granted web_search@1.`
- `tests/agents/test_manual_drift.py`: the `SKILLS_BLOCK_MAX_BYTES` comment gains a line `#: Unmoved at head-of-abm@v61: no disclosed resource joins (a tool grant is not a resource).` — change the number only if `test_the_resolved_system_prompt_size_is_reported_against_the_identity_budget` fails, and then by the smallest 512-byte step, recording the measured bytes in the comment as the precedent does.
- `tests/api/test_agent_registry_wiring.py`: `"profile:head-of-abm@v60"` → `v61` (line ~579); `manual-{name}@v7` → `@v8` (lines ~694, 875); `prompts/head-of-abm/v13/SYSTEM.md` → `v14` (line ~905); add `"web_search@1",` to the head `available == {...}` set (line ~495, alphabetical end); the `AgentRole.HEAD_OF_ABM` manifest digest (line ~164): run the test once, copy the measured digest from the assertion message into the constant and extend its comment with `v61 moves it: one address ADDED (web_search@1), prompt v14 and the re-minted manual-*@v8. Digest measured off this tree.`
- `tests/agents/test_tool_authority_audit.py`: the Task 2 asserts become `== (AgentRole.HEAD_OF_ABM,)` for both, comment `GRANTED at head-of-abm@v61 (2026-09-22).`
- `tests/api/test_c8_trial_surface.py:352`: `@v7` → `@v8`.
- `tests/api/test_comprehensive_research_contract.py:469-470`: `v60` → `v61` (both).
- `tests/api/test_client_knowledge_privacy_s4e.py:161`: `v60` → `v61`.

- [ ] **Step 8: Run the gates**

Run: `uv run pytest tests/agents/test_catalog.py tests/agents/test_manual_builder.py tests/agents/test_manual_drift.py tests/api/test_agent_registry_wiring.py tests/agents/test_tool_authority_audit.py tests/api/test_c8_trial_surface.py tests/api/test_comprehensive_research_contract.py tests/api/test_client_knowledge_privacy_s4e.py tests/api/test_recipe_contracts.py tests/api/test_toolbelt_wiring.py tests/architecture/test_provider_tool_schema_gate.py tests/agents/test_governed_tool_arguments.py -q`
Expected: PASS. Also `make manual-check` exits 0. Frontend: `cd apps/frontend && npm run lint` (run `npm ci` first if `node_modules` is absent on this lane).

- [ ] **Step 9: Commit**

```bash
git add platform/agents/catalog/prompts/head-of-abm/v14 platform/agents/catalog/profiles/head-of-abm/v61 platform/agents/catalog/skills/manual-*/v8 platform/agents/catalog/manual/tool_notes.yaml platform/agents/clue_agents/manual/build.py apps/frontend/src/features/projects/model/chat-tool-presentation.ts platform/api/clue_api/agent_registry_wiring.py platform/api/clue_api/chat/composer_context.py tests/agents/test_catalog.py tests/agents/test_manual_builder.py tests/agents/test_manual_drift.py tests/api/test_agent_registry_wiring.py tests/agents/test_tool_authority_audit.py tests/api/test_c8_trial_surface.py tests/api/test_comprehensive_research_contract.py tests/api/test_client_knowledge_privacy_s4e.py
git commit -m "feat(head-of-abm): v61 grants web_search@1 — prompt v14 orders the lookups; recipe 31; manual v8"
```

---

### Task 5: `design@v3` — the design role holds the tool

**Files:**
- Create: `platform/agents/catalog/profiles/design/v3/profile.yaml`
- Modify: `platform/api/clue_api/agent_registry_wiring.py` (`AgentRole.DESIGN: "v3"`; `"web_search": (AgentRole.HEAD_OF_ABM, AgentRole.DESIGN)`)
- Tests: `tests/agents/test_catalog.py` (`"profile:design@v3"`), `tests/api/test_agent_registry_wiring.py:958-959` (`v3`, `54`), `tests/agents/test_tool_authority_audit.py`

- [ ] **Step 1: Write the failing test changes**

`tests/api/test_agent_registry_wiring.py` in `test_design_profile_resolves_with_the_full_granted_write_surface`: `resolved.profile.version == "v3"`, `len(resolved.profile.tools) == 54`, and extend the `for address in (...)` loop tuple with `"web_search@1"`; docstring line: `2026-09-22 adds the fourth: web_search@1, the open-web search, used last.`

`tests/agents/test_tool_authority_audit.py`: `C6_AGENT_TOOL_AUTHORITY["web_search"] == (AgentRole.HEAD_OF_ABM, AgentRole.DESIGN)` and the same for `c6_roles_for_tool("web_search@1")`.

`tests/agents/test_catalog.py`: add `"profile:design@v3",` after `"profile:design@v2",` with the comment `# web_search@1: v2 plus the open-web search. Nothing else moves.`

- [ ] **Step 2: Run to verify they fail**

Run: `uv run pytest tests/api/test_agent_registry_wiring.py -q -k design_profile`
Expected: FAIL (`v2 != v3`).

- [ ] **Step 3: Mint design v3**

```bash
mkdir -p platform/agents/catalog/profiles/design/v3
cp platform/agents/catalog/profiles/design/v2/profile.yaml platform/agents/catalog/profiles/design/v3/profile.yaml
```

Edit: the header comment `# v2 (2026-09-19): v1 plus the three account reads. Nothing else moves.` → keep it and add `# v3 (2026-09-22): v2 plus web_search@1 — the open-web search, used last, text out and never a claim; reached through the platform-reads seam on a chat-opened session. Nothing else moves.`; `version: v2` → `v3`; in `tools:` after the `read_claims` pin add:

```yaml
  - name: web_search
    version: "1"
    input_schema_sha256: <same digest as head-of-abm/v61>
    output_schema_sha256: <same digest as head-of-abm/v61>
```

(the tools comment `and at v2 the three effect-free account reads` → append `, and at v3 web_search@1`.)

`agent_registry_wiring.py`: `AgentRole.DESIGN: "v2"` → `"v3"` with comment `# v3 (2026-09-22): v2 plus web_search@1 (spec 2026-09-22). Nothing else moves.`; `"web_search": (AgentRole.HEAD_OF_ABM,)` → `(AgentRole.HEAD_OF_ABM, AgentRole.DESIGN)`.

- [ ] **Step 4: Run**

Run: `uv run pytest tests/api/test_agent_registry_wiring.py tests/agents/test_tool_authority_audit.py tests/agents/test_catalog.py tests/architecture/test_provider_tool_schema_gate.py -q`
Expected: PASS. If the registry test pins a DESIGN manifest digest, re-measure it the same way as Task 4.

- [ ] **Step 5: Commit**

```bash
git add platform/agents/catalog/profiles/design/v3 platform/api/clue_api/agent_registry_wiring.py tests/api/test_agent_registry_wiring.py tests/agents/test_tool_authority_audit.py tests/agents/test_catalog.py
git commit -m "feat(registry): design@v3 pins web_search@1; the design role may search the web, last"
```

---

### Task 6: The design injection, both halves

**Files:**
- Modify: `platform/api/clue_api/design_platform_reads.py` (docstring paragraph; `DesignPlatformReads.web_search`)
- Modify: `subsystems/clue-design/apps/agent_runtime/lumen_agent/platform_reads.py:60-119` (`make_platform_read_tools`)
- Test: `tests/api/test_design_platform_reads_db.py`, `subsystems/clue-design/apps/agent_runtime/tests/test_platform_reads.py`

**Interfaces:**
- Produces (platform): `DesignPlatformReads.web_search(*, query: str, num_results: int = 10, include_domains: list[str] | None = None, exclude_domains: list[str] | None = None, start_published_date: str | None = None, end_published_date: str | None = None) -> dict[str, Any]` — the `WebSearchOutput` dict; a refusal raises `DesignPlatformReadError("refused:<codes>")` like the reads.
- Produces (runtime): `make_platform_read_tools(tools, reads)` returns FOUR tools, the fourth named `web_search`; it calls `reads.web_search(**kwargs)` and returns the JSON string of the payload (the agent reads `rendered`).

- [ ] **Step 1: Runtime test (design side)**

In `subsystems/clue-design/apps/agent_runtime/tests/test_platform_reads.py`, give `_Reads` a method:

```python
    def web_search(self, **kw):
        self.calls.append(("search", kw))
        return {"answer": "Acme's summit is in May.", "results": [], "rendered": "Acme's summit is in May.\n"}
```

Change every `accounts, research, claims = make_platform_read_tools(tools, reads)` to `accounts, research, claims, search = ...` and `_, research, _ = ...` to `_, research, _, _ = ...`. In `test_tools_return_json_and_errors_as_strings_and_record` extend:

```python
    assert search.name == "web_search"
    assert json.loads(search.invoke({"query": "acme summit 2026"}))["rendered"].startswith("Acme")
    assert reads.calls[-1] == (
        "search",
        {
            "query": "acme summit 2026",
            "num_results": 10,
            "include_domains": None,
            "exclude_domains": None,
            "start_published_date": None,
            "end_published_date": None,
        },
    )
```

and the `[True, False, True]` ok-list becomes `[True, False, True, True]`. Add:

```python
def test_a_refused_search_reaches_the_agent_as_its_reason_code(tmp_path, monkeypatch) -> None:
    tools = _tools(tmp_path, monkeypatch)
    reads = _Reads()
    reads.web_search = lambda **kw: (_ for _ in ()).throw(_ReadError("refused:exa_not_configured"))
    *_, search = make_platform_read_tools(tools, reads)
    assert json.loads(search.invoke({"query": "acme"})) == {
        "error": "refused",
        "reasons": ["exa_not_configured"],
    }
```

Run: `cd subsystems/clue-design/apps/agent_runtime && uv run pytest tests/test_platform_reads.py -q` (the design runtime has its own toolchain — see `subsystems/clue-design/AGENTS.md` for the exact invocation if `uv run` is not it). Expected: FAIL (three tools unpacked into four).

- [ ] **Step 2: Runtime implementation**

In `lumen_agent/platform_reads.py`, inside `make_platform_read_tools` after `read_claims`, add:

```python
    @tool
    def web_search(
        query: str,
        num_results: int = 10,
        include_domains: list[str] | None = None,
        exclude_domains: list[str] | None = None,
        start_published_date: str | None = None,
        end_published_date: str | None = None,
    ) -> str:
        """Search the open web and read back what it found: a short written answer, then up to
        ten results with title, URL, date and highlighted passages (the `rendered` field is the
        text to read). Use this last: the account reads and the seller's files under seller/
        come first, every time. It is for the brief's subject when the platform has nothing on
        it — an event the seller is running, a workshop, a topic outside its products. What it
        returns is text you may use in the design now; it is not a claim, it is not verified,
        and it must not be presented as research the platform did."""
        return _call(
            tools,
            reads,
            "web_search",
            query=query,
            num_results=num_results,
            include_domains=include_domains,
            exclude_domains=exclude_domains,
            start_published_date=start_published_date,
            end_published_date=end_published_date,
        )

    return [read_project_accounts, read_account_research, read_claims, web_search]
```

Update the module docstring's first line: `Three tools` → `Four tools — the three account reads head-of-abm has, and web_search, the open-web search used last`. Re-run the runtime test file: PASS.

- [ ] **Step 3: Platform DB test**

In `tests/api/test_design_platform_reads_db.py`, in `_seeded` after the paged reads are registered, register the search tool with a fake client:

```python
    from clue_api.web_search_tool import build_web_search_tools  # noqa: PLC0415
    from tests.api.test_web_search_tool import HIT, FakeExa, _result  # noqa: PLC0415

    fake_exa = FakeExa(_result(output_text="Acme's summit is in May.", hits=(HIT,)))
    search_tool = build_web_search_tools(secrets=None)[0]
    search_tool._client_factory = lambda label, raw, ledger: fake_exa  # the offline double
    registry.register(search_tool, make_default=True)
```

and return `"fake_exa": fake_exa` in the dict. Add the test:

```python
def test_a_leg_may_search_the_web_through_the_governed_tool(tmp_path: Path, migrated_db: bool) -> None:
    if not migrated_db:
        pytest.skip("database not reachable")
    from clue_api.design_platform_reads import build_design_platform_reads_factory

    async def scenario() -> None:
        async with rollback_conn() as conn:
            seeds = await _seeded(conn, tmp_path, label="search")
            factory = build_design_platform_reads_factory(
                invoker=seeds["invoker"], storage=seeds["storage"], conn_factory=seeds["conn_factory"]
            )
            reads = await asyncio.to_thread(
                factory, _leg_envelope(seeds["workspace_id"], seeds["project"].project_id, seeds["opening_turn"])
            )
            assert reads is not None

            found = await asyncio.to_thread(reads.web_search, query="acme summit 2026", num_results=3)
            assert found["answer"] == "Acme's summit is in May."
            assert found["rendered"].startswith("Acme's summit is in May.")
            assert seeds["fake_exa"].calls[0]["type"] == "deep-lite"
            assert seeds["fake_exa"].calls[0]["num_results"] == 3

            second = await asyncio.to_thread(reads.web_search, query="acme summit 2026", num_results=3)
            assert second == found
            # Two calls, two operations, two journal rows — a search is never replayed from the
            # previous search's receipt (the same rule the paged reads follow).
            rows = (
                await conn.execute(
                    text("SELECT tool_name FROM tool_invocation WHERE workspace_id = :ws ORDER BY created_at"),
                    {"ws": seeds["workspace_id"]},
                )
            ).all()
            assert [str(row[0]) for row in rows] == ["web_search@1", "web_search@1"]
            assert len(seeds["fake_exa"].calls) == 2

    run_async(scenario())
```

Run: `uv run pytest tests/api/test_design_platform_reads_db.py -q -k search` (against a throwaway DB: `CLUE_DATABASE_URL` for a `clue_lome_test` clone, never the lane DB). Expected: FAIL (`DesignPlatformReads has no attribute web_search`).

- [ ] **Step 4: Platform implementation**

In `design_platform_reads.py`, after `read_claims` add:

```python
    # --- the one spend tool on this seam --------------------------------------------------------

    def web_search(
        self,
        *,
        query: str,
        num_results: int = 10,
        include_domains: list[str] | None = None,
        exclude_domains: list[str] | None = None,
        start_published_date: str | None = None,
        end_published_date: str | None = None,
    ) -> dict[str, Any]:
        """One open-web search (``web_search@1``), used last. The first SPEND tool on this seam:
        the ledger row it lands is workspace spend under the turn's identity, and — like the reads —
        every call is its own operation, so a second search is never answered by the first's
        receipt."""

        body: dict[str, Any] = {"query": query, "num_results": num_results}
        for key, value in (
            ("include_domains", include_domains),
            ("exclude_domains", exclude_domains),
            ("start_published_date", start_published_date),
            ("end_published_date", end_published_date),
        ):
            if value is not None:
                body[key] = value
        return self._invoke("web_search", body)
```

Add to the module docstring after the "Three of the four reads..." paragraph:

```
Since 2026-09-22 the seam also carries ONE spend tool, ``web_search@1`` — the open-web search both
roles hold, used last. It rides the same invoker and the same fresh-operation-id rule; its ledger
row is workspace spend because the invoker's context carries no project.
```

Run: `uv run pytest tests/api/test_design_platform_reads_db.py -q`. Expected: PASS (all existing tests still green: the reads test asserts exactly three journal rows for its own label's workspace).

- [ ] **Step 5: Commit**

```bash
git add platform/api/clue_api/design_platform_reads.py subsystems/clue-design/apps/agent_runtime/lumen_agent/platform_reads.py tests/api/test_design_platform_reads_db.py subsystems/clue-design/apps/agent_runtime/tests/test_platform_reads.py
git commit -m "feat(design): web_search rides the platform-reads seam — fourth tool in both harnesses"
```

---

### Task 7: The design-side words

**Files:**
- Modify: `subsystems/clue-design/apps/agent_runtime/knowledge_docs/views/scene/skills/tools/SKILL.md:14-22` (after the "Platform reads" paragraph)
- Modify: `subsystems/clue-design/apps/agent_runtime/lumen_agent/prompts.py:1207-1209` and `:1326-1328` (the two "When the brief names a target company…" sentences)
- Test: `subsystems/clue-design/apps/agent_runtime/tests/test_platform_reads.py`

- [ ] **Step 1: Failing test**

Append to the runtime test file:

```python
def test_the_scene_tools_skill_and_the_web_prompt_teach_web_search_as_the_last_resort() -> None:
    root = Path(__file__).resolve().parents[1]
    skill = (root / "knowledge_docs/views/scene/skills/tools/SKILL.md").read_text(encoding="utf-8")
    prompts = (root / "lumen_agent/prompts.py").read_text(encoding="utf-8")
    assert "## Web search" in skill
    assert "`web_search`" in skill and "comes after the account reads" in skill
    assert prompts.count("web_search is the last resort") == 2
```

Run the file; expected: FAIL.

- [ ] **Step 2: The skill paragraph**

In the scene tools `SKILL.md`, after the "Platform reads" paragraph (ends `...lists the brand's knowledge documents written into this workspace.`) add:

```markdown
## Web search

`web_search` searches the open web and answers JSON like the reads: a short written answer,
then up to ten results with title, URL, date and highlighted passages, with the text to read in
`rendered`. It is present on a chat-opened design session and absent in the editor's own agent
box and the CLI. It comes after the account reads and after the seller's files in `seller/`,
every time: use it only when those have nothing on the brief's subject, or what they have is
vague — an event the seller is running, a workshop, a topic outside its products. What it
returns is text you may design from now; it is not a claim, it is not verified, and it is never
presented as research the platform did. A refusal (`{"error": "refused", "reasons": [...]}`)
means no search happened; design from what you have and say what was missing.
```

- [ ] **Step 3: The web-lane prompt sentences**

In `prompts.py` at BOTH sites, replace the sentence
`When the brief names a target company, the account reads (read_project_accounts, read_account_research, read_claims) are how you learn what research found about it; the account-adaptation skill says how.`
with:
`When the brief names a target company, the account reads (read_project_accounts, read_account_research, read_claims) are how you learn what research found about it; the account-adaptation skill says how. web_search is the last resort, after those reads and the seller's files: use it only for what the platform never researched, such as an event the seller is running, and treat what it returns as text to design from, never as a verified claim.`

Keep the line wrapping style of the surrounding text (the file wraps at ~80 columns).

- [ ] **Step 4: Run**

Run: `cd subsystems/clue-design/apps/agent_runtime && uv run pytest tests/test_platform_reads.py -q`. Expected: PASS. Also run the prompt tests if a `tests/test_prompts*.py` exists there (grep for one) to catch a byte-length or snapshot assertion on the prompt text.

- [ ] **Step 5: Commit**

```bash
git add subsystems/clue-design/apps/agent_runtime/knowledge_docs/views/scene/skills/tools/SKILL.md subsystems/clue-design/apps/agent_runtime/lumen_agent/prompts.py subsystems/clue-design/apps/agent_runtime/tests/test_platform_reads.py
git commit -m "docs(design-agent): web search is the last resort — scene tools skill and web-lane prompt"
```

---

### Task 8: The record

**Files:**
- Modify: `docs/specs/M8B-exa-sumble-account-deep-integration-roadmap.md:105-106`
- Modify: `docs/specs/ARV2-MASTER-PLAN.md:489`
- Modify: `docs/superpowers/specs/2026-09-22-web-search-tool-design.md` (status line → implemented; §4 offline items ticked)
- Modify: `_memory/2026-09-22-web-search-tool-design.md` (closing entry), `_memory/README.md` (index line)

- [ ] **Step 1: M8B item 15**

Append to the item 15 paragraph (keep the original two sentences):

```
    **Superseded 2026-09-22** by `docs/superpowers/specs/2026-09-22-web-search-tool-design.md`
    (`web_search@1`, granted to head-of-abm@v61 and design@v3, used last, text never a claim);
    M8B's target-locked acquisition is untouched.
```

- [ ] **Step 2: Master plan**

In `ARV2-MASTER-PLAN.md` line 489, after `the Exa MCP search tool on the main agent,` insert ` (landed 2026-09-22 as the direct governed tool ``web_search@1``, not MCP — spec ``docs/superpowers/specs/2026-09-22-web-search-tool-design.md``),`.

- [ ] **Step 3: Spec status and memory**

Spec header `**Status:** founder-approved in chat (2026-09-22)` → `**Status:** implemented on `research-streaming-v3` (2026-09-22; live proofs §4.5–4.6 owed, founder-triggered)`. In `_memory/2026-09-22-web-search-tool-design.md` add a `## Closing entry` naming the eight commits, the gate files run and their result, the digests measured, and the two owed live proofs. Update the `_memory/README.md` index line to say the tool LANDED and the live proofs are owed.

- [ ] **Step 4: Full focused gate**

Run every file named in Tasks 1–7 once more in one invocation, plus `make manual-check`:

```bash
uv run pytest tests/arv2/test_exa_client.py tests/api/test_web_search_tool.py tests/api/test_toolbelt_wiring.py tests/agents/test_tool_authority_audit.py tests/api/test_agent_registry_wiring.py tests/api/test_recipe_contracts.py tests/agents/test_catalog.py tests/agents/test_manual_builder.py tests/agents/test_manual_drift.py tests/api/test_c8_trial_surface.py tests/api/test_comprehensive_research_contract.py tests/api/test_client_knowledge_privacy_s4e.py tests/architecture/test_provider_tool_schema_gate.py tests/agents/test_governed_tool_arguments.py tests/api/test_design_platform_reads_db.py -q && make manual-check
```

Expected: all PASS, `manual-check` exit 0. Report any red honestly with its output.

- [ ] **Step 5: Commit**

```bash
git add docs/specs/M8B-exa-sumble-account-deep-integration-roadmap.md docs/specs/ARV2-MASTER-PLAN.md docs/superpowers/specs/2026-09-22-web-search-tool-design.md _memory/2026-09-22-web-search-tool-design.md _memory/README.md
git commit -m "docs: web_search@1 supersedes M8B item 15; master plan Track O says direct tool, not MCP; spec status"
```

---

## Live proof (founder-triggered, NOT part of the executable plan)

After the eight commits, on this lane's stack (`./scripts/dev_stack_lome.sh up`, DB `clue_lome`, real `CLUE_EXA_API_KEY`):

1. Head-of-ABM turn in a project chat: "We're hosting a GI practice-manager workshop in Austin this May — what should the invite say?" Expect a `web_search` receipt in the journal, one `provider_call_ledger` row with `provider='exa'`, `operation='search'`, workspace-stamped, and a reply that says which facts came from the search.
2. Open a design leg for an event page on the same subject. Expect `platform_reads_attached` to list four tools, a `platform_read` trace event with `tool: web_search`, and a `web_search@1` row in `tool_invocation` under the leg's workspace.

Record both in `_memory/2026-09-22-web-search-tool-design.md`.
