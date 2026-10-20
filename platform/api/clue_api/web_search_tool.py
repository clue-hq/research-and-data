"""``web_search@1`` — one open-web search for Head-of-ABM and the design agents, used LAST
(spec ``docs/superpowers/specs/archive/2026-09-22-web-search-tool-design.md``).

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
from typing import ClassVar, Protocol

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
    query: str = Field(
        min_length=1,
        max_length=400,
        description="The question or topic to search for, in plain words. Up to 400 characters.",
    )
    num_results: int = Field(
        default=_MAX_RESULTS,
        ge=1,
        le=_MAX_RESULTS,
        description="How many results to read back, 1 to 10. Ten is the default.",
    )
    include_domains: list[str] = Field(
        default_factory=list,
        max_length=10,
        description="Only these sites, up to ten. Leave empty to search the whole web.",
    )
    exclude_domains: list[str] = Field(
        default_factory=list,
        max_length=10,
        description="Never these sites, up to ten. Leave empty to exclude nothing.",
    )
    start_published_date: str | None = Field(
        default=None,
        max_length=32,
        description=(
            "Only pages published on or after this date, as a plain ISO date such as "
            "2026-01-01. Leave empty for no lower bound."
        ),
    )
    end_published_date: str | None = Field(
        default=None,
        max_length=32,
        description=(
            "Only pages published on or before this date, as a plain ISO date. Leave empty "
            "for no upper bound."
        ),
    )


class WebSearchResultItem(ToolOutput):
    """One search result: what the page is called, where it is, when it was published, and the
    passages that matched."""

    title: str | None = Field(description="The page's title, when Exa reported one.")
    url: str | None = Field(description="The page's address.")
    published_date: str | None = Field(description="When the page was published, when known.")
    highlights: list[str] = Field(description="The passages from the page that matched the query.")


class WebSearchOutput(ToolOutput):
    answer: str | None = Field(
        description=("The short written answer the search produced, or null when it produced none.")
    )
    results: list[WebSearchResultItem] = Field(
        description="Up to ten results, most relevant first."
    )
    rendered: str = Field(
        description=(
            "The whole result as one text: the answer, then one numbered block per result. "
            "This is what you read."
        )
    )
    cost_usd: str = Field(description="What the search cost, as Exa metered it.")
    request_id: str | None = Field(description="Exa's id for this request, for the ledger.")


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
    refuses ``exa_not_configured`` before any spend), exactly as
    ``build_onboarding_evidence_tools``."""
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
