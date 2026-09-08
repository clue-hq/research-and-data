"""The twelve governed account tools, over in-memory doubles of the four R1 clients.

Global Constraint 3 forbids mocked *provider bodies*; what stands in here are the **clients**
themselves — objects that return the same dataclasses the real clients return, so what is under
test is the tool's own logic (which claims it writes, which refusal it emits, what JSON it hands
back) and never a pretend HTTP conversation. The clients' own behaviour is proven live in their
own test files.

Two laws are asserted everywhere: **a tool never raises into the graph** (every failure comes back
as a refusal envelope) and **a provider is only ever reached through**
:meth:`ToolRuntime.call_provider`, so the halt latch, the ledger drain and the semaphore cannot be
bypassed by a tool body.
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator, Coroutine, Mapping, Sequence
from contextlib import asynccontextmanager
from dataclasses import replace
from datetime import UTC, date, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

import pytest

from clue_api.arv2 import account_research_tools as tools
from clue_api.arv2.account_research_claims import JobScope
from clue_api.arv2.account_research_store import AnnotationRow
from clue_api.arv2.account_research_tools import (
    ACCOUNT_TOOL_NAMES,
    ToolRuntime,
    build_account_tools,
)
from clue_api.arv2.ai_ark_client import AiArkCompany, AiArkPeople, AiArkPerson
from clue_api.arv2.ats_client import AtsBoard, BoardFetchFailed, BoardPostings, JobPosting
from clue_api.arv2.calls import CallCost
from clue_api.arv2.claim_writer import ClaimDraft, WriteReceipt
from clue_api.arv2.errors import ProviderHalted
from clue_api.arv2.exa_client import (
    ExaContentsResult,
    ExaDeepResult,
    ExaHit,
    ExaSearchResult,
)
from clue_api.arv2.gemini_media_client import (
    AudioFile as TranscriptionInput,
)
from clue_api.arv2.gemini_media_client import (
    MediaBudget,
    MinedQuotes,
    QuoteCandidate,
    SpeakerVerdict,
    Transcript,
)
from clue_api.arv2.media_feeds_client import (
    AudioFile,
    EnclosureTooLarge,
    Episode,
    Podcast,
    YouTubeMeta,
    YouTubeWords,
)
from clue_api.arv2.structuring_client import (
    FieldCatalog,
    FieldSpec,
    NegativeOrRisk,
    ProposedField,
    StructuredClaim,
    StructuredOutput,
)
from clue_api.arv2.transport import ScriptedTransport
from clue_config import Settings
from clue_core import (
    Claim,
    ClaimId,
    EntityId,
    EntityType,
    ExtractionMethod,
    ResearchMode,
    ReuseScope,
    RunId,
)

# -- the job under research ----------------------------------------------------------------------

ACCOUNT_ID = EntityId(uuid4())
RUN_ID = uuid4()

SCOPE = JobScope(
    workspace_id="ws-1",
    project_id="prj-1",
    project_run_id=uuid4(),
    run_id=RUN_ID,
    job_id=uuid4(),
    account_id=ACCOUNT_ID,
    account_name="Probook",
    account_domain="probook.ai",
    icp_markdown="# icp\nSeries A US SaaS.",
    persona_markdown="# personas\nchampion: VP Marketing",
    already_established="Founded 2021.",
    effort="high",
    committee_cap=4,
    today=date(2026, 9, 8),
)

CATALOG = FieldCatalog(
    account=(
        FieldSpec("account.named_customers", "Customers the company names.", {"type": "array"}),
        FieldSpec("account.gtm_tooling_stack", "GTM tools present and absent."),
        FieldSpec("core.industry", "Industry."),
        # Registered with its real schema (``packs.py``): the HQ is translated into this shape and
        # checked against it before a claim exists, so a menu without it writes no HQ claim.
        FieldSpec(
            "core.hq_location",
            "Headquarters.",
            {
                "type": "object",
                "required": ["raw"],
                "properties": {"raw": {"type": "string"}, "city": {"type": "string"}},
            },
        ),
    )
)


def _run[T](coro: Coroutine[Any, Any, T]) -> T:
    return asyncio.run(coro)


def _cost(provider: str = "exa", operation: str = "search") -> CallCost:
    return CallCost(
        cost_usd=Decimal("0.005"),
        credits=None,
        media_seconds=None,
        cost_source="metered",
        ledger_row_id="row-1",
        raw_ref="raw:abc",
        provider=provider,
        operation=operation,
    )


# -- the doubles ---------------------------------------------------------------------------------


class FakeExa:
    """Only the three methods the tools call, returning the real client's own result types."""

    def __init__(self) -> None:
        self.contents_calls: list[tuple[tuple[str, ...], int]] = []
        self.search_calls: list[dict[str, Any]] = []
        self.deep_calls: list[dict[str, Any]] = []
        self.text_by_url: dict[str, str] = {}
        self.raise_on_contents: Exception | None = None
        self.deep_report: str | None = "A long report about Probook. " * 200
        self.deep_cost_usd: Decimal = Decimal("0.60")

    def contents(
        self, urls: Sequence[str], *, text_max_chars: int = 8000, **_: Any
    ) -> ExaContentsResult:
        self.contents_calls.append((tuple(urls), text_max_chars))
        if self.raise_on_contents is not None:
            raise self.raise_on_contents
        return ExaContentsResult(
            results=tuple(
                ExaHit(
                    url=url,
                    title="A page",
                    published_date=None,
                    author=None,
                    text=self.text_by_url.get(url, "page text about Probook"),
                    highlights=(),
                )
                for url in urls
            ),
            statuses=(),
            status=200,
            cost_usd=Decimal("0.004"),
            request_id="req-1",
            raw_ref="raw:contents",
            ledger_row_id="row-c",
            cost=_cost(operation="contents"),
        )

    def search(self, query: str, **kwargs: Any) -> ExaSearchResult:
        self.search_calls.append({"query": query, **kwargs})
        return ExaSearchResult(
            results=(
                ExaHit(
                    url="https://probook.ai/blog/abm",
                    title="How we do ABM",
                    published_date="2026-05-01",
                    author=None,
                    text="we still build target lists by hand",
                    highlights=(),
                ),
            ),
            status=200,
            cost_usd=Decimal("0.005"),
            request_id="req-2",
            raw_ref="raw:search",
            ledger_row_id="row-s",
            cost=_cost(),
        )

    def deep_reasoning(self, **kwargs: Any) -> ExaDeepResult:
        self.deep_calls.append(kwargs)
        return ExaDeepResult(
            output_text=self.deep_report or "",
            output_object=None,
            report_text=self.deep_report,
            grounding=None,
            results=(),
            status=200,
            cost_usd=self.deep_cost_usd,
            request_id="req-3",
            raw_ref="raw:deep",
            ledger_row_id="row-d",
            cost=_cost(operation="research"),
            retried=False,
        )


class FakeAiArk:
    def __init__(self) -> None:
        self.company_calls: list[str] = []
        self.people_calls: list[tuple[tuple[str, ...], str, int]] = []
        self.company: AiArkCompany | None = AiArkCompany(
            name="Probook",
            domain="probook.ai",
            linkedin="https://www.linkedin.com/company/probook",
            industry="Software",
            employee_count=42,
            revenue="1000000-5000000",
            technologies=("HubSpot",),
            location={"country": "US", "raw_address": "New York, New York, United States"},
            raw={
                "financial": {
                    "revenue": {
                        "annual": {
                            "start": 1_000_000,
                            "end": 5_000_000,
                            "amount": "1000000-5000000",
                        }
                    },
                    "funding": {
                        "type": "SERIES_A",
                        "total_amount": 12_000_000,
                        "rounds": [
                            {
                                "announced_at": "2025-12-02",
                                "raised_amount": 12_000_000,
                                "type": "SERIES_A",
                                "investors": ["Sequoia Capital"],
                            }
                        ],
                    },
                }
            },
            cost=_cost(provider="ai_ark", operation="v1/companies"),
        )

    def company_by_domain(self, domain: str) -> AiArkCompany | None:
        self.company_calls.append(domain)
        return self.company

    def people_by_name(
        self, name_variants: Sequence[str], domain: str, *, size: int = 3
    ) -> AiArkPeople:
        self.people_calls.append((tuple(name_variants), domain, size))
        return AiArkPeople(
            people=(
                AiArkPerson(
                    full_name="Nick Fisher",
                    title="VP Marketing",
                    headline="Demand gen",
                    linkedin_url="https://www.linkedin.com/in/nick",
                    location={"country": "US"},
                    current_company="Probook",
                    current_company_domain="probook.ai",
                    department={"name": "marketing"},
                    ark_id="ark-1",
                    raw={},
                ),
            ),
            cost=_cost(provider="ai_ark", operation="v1/people"),
        )


class FakeStructuring:
    def __init__(self) -> None:
        self.account_calls: list[dict[str, Any]] = []
        self.raise_with: Exception | None = None
        self.output = StructuredOutput(
            claims=(
                StructuredClaim(
                    field_key="account.named_customers",
                    value=["Acme"],
                    evidence_span="Acme trusts Probook",
                    source_url="https://probook.ai/customers",
                    source_kind="company_primary",
                    confidence="high",
                    use_class="business_public",
                    outreach_safe=True,
                    priority=2,
                    media_timestamp=None,
                    evidence_verbatim="EXACT",
                    schema_valid=True,
                ),
            ),
            proposed=(
                ProposedField(
                    suggested_key="account.pricing_shape",
                    why="three tiers",
                    value={"tiers": 3},
                    evidence_span="Starter, Growth, Scale",
                    source_url="https://probook.ai/pricing",
                ),
            ),
            negatives=(
                NegativeOrRisk(
                    what="a rumoured down round",
                    status="UNRESOLVED",
                    evidence_span="reports of a flat round",
                    source_url="https://news.test/probook",
                    outreach_safe=False,
                ),
            ),
            model="m",
            mode="broad",
        )

    def structure_account(
        self,
        subject: Any,
        bundle: str,
        catalog: FieldCatalog,
        *,
        mode: str = "broad",
        sources: Any = None,
        notes: str | None = None,
    ) -> StructuredOutput:
        self.account_calls.append(
            {
                "subject": subject,
                "bundle": bundle,
                "mode": mode,
                "sources": list(sources or []),
                "notes": notes,
            }
        )
        if self.raise_with is not None:
            raise self.raise_with
        return self.output


class FakeMedia:
    """The transcription half of the media path (the feed half is module functions)."""

    def __init__(self) -> None:
        self.short_calls: list[TranscriptionInput] = []
        self.long_calls: list[TranscriptionInput] = []
        self.quote_calls: list[str] = []

    def transcribe_short(self, audio: TranscriptionInput, *, context: Any) -> Transcript:
        self.short_calls.append(audio)
        return Transcript(
            model="short-model",
            text="I still build my target lists by hand.",
            lines=(),
            meta={"guest_identity_evidence": "I'm Nick Fisher"},
            cost=_cost(provider="openrouter", operation="chat/completions"),
        )

    def transcribe_long(self, audio: TranscriptionInput, *, context: Any) -> Transcript:
        self.long_calls.append(audio)
        return self.transcribe_short(audio, context=context)

    def mine_quotes(
        self,
        transcript_text: str,
        *,
        context: Any,
        n: int = 6,
        speaker_verified: bool | None = None,
    ) -> MinedQuotes:
        self.quote_calls.append(transcript_text)
        return MinedQuotes(
            quotes=(
                QuoteCandidate(
                    text="I still build my target lists by hand.",
                    ts_s=125,
                    why="names the pain",
                    verdict="EXACT",
                    usable=bool(speaker_verified),
                ),
            ),
            cost=_cost(provider="openrouter", operation="chat/completions"),
        )


class FakeClients:
    def __init__(self) -> None:
        self.exa_client = FakeExa()
        self.ai_ark_client = FakeAiArk()
        self.structuring_client = FakeStructuring()
        self.media_client = FakeMedia()
        self.callers: list[Any] = []

    def exa(self, caller: Any) -> Any:
        self.callers.append(caller)
        return self.exa_client

    def ai_ark(self, caller: Any) -> Any:
        self.callers.append(caller)
        return self.ai_ark_client

    def media(self, caller: Any, ledger: Any) -> Any:
        self.callers.append(caller)
        return self.media_client

    def structuring(self, caller: Any) -> Any:
        self.callers.append(caller)
        return self.structuring_client


class FakeWriter:
    """Records every draft the runtime writes and hands back a receipt, as the real gate does."""

    def __init__(self) -> None:
        self.drafts: list[ClaimDraft] = []
        #: field keys this writer refuses, the way the real gate raises on an unwritable value.
        self.raise_on: set[str] = set()
        #: field keys this writer stores but marks ``schema_valid=False``, as the real gate does
        #: when the value misses the field's registered schema.
        self.schema_invalid: set[str] = set()

    async def write(self, conn: Any, draft: ClaimDraft) -> WriteReceipt:
        if draft.field_key in self.raise_on:
            raise ValueError(f"cannot write {draft.field_key}")
        markers = dict(draft.markers)
        if draft.field_key in self.schema_invalid:
            markers["schema_valid"] = False
        self.drafts.append(draft)
        return WriteReceipt(
            claim_id=ClaimId(uuid4()),
            field_key=draft.field_key,
            markers=markers,
            registered_field=False,
        )


class FakeArtifacts:
    async def persist_body(self, *, workspace_id: str, data: bytes, media_type: str) -> Any:
        raise AssertionError("no raw body is buffered by an in-memory client double")


class MemoryConnFactory:
    """A connection factory whose connection is never spoken to (nothing here touches SQL)."""

    def __init__(self) -> None:
        self.opened = 0

    def __call__(self) -> Any:
        return self._open()

    @asynccontextmanager
    async def _open(self) -> AsyncIterator[Any]:
        self.opened += 1
        yield object()


def _runtime(
    scope: JobScope = SCOPE,
) -> tuple[ToolRuntime, FakeClients, FakeWriter, MemoryConnFactory]:
    clients = FakeClients()
    writer = FakeWriter()
    conn_factory = MemoryConnFactory()
    runtime = ToolRuntime(
        scope=scope,
        settings=Settings(),
        clients=clients,  # type: ignore[arg-type]
        conn_factory=conn_factory,
        artifacts=FakeArtifacts(),
        writer=writer,  # type: ignore[arg-type]
        catalog=CATALOG,
        media_budget=MediaBudget(9000),
        transport_factory=lambda: ScriptedTransport([]),
        now=lambda: datetime(2026, 9, 8, tzinfo=UTC),
    )
    return runtime, clients, writer, conn_factory


def _tools(runtime: ToolRuntime) -> dict[str, Any]:
    return {tool.name: tool for tool in build_account_tools(runtime)}


def _call(runtime: ToolRuntime, name: str, **args: Any) -> Mapping[str, Any]:
    """Invoke a tool the way the agent does — through LangChain — and read its JSON result."""
    result = _run(_tools(runtime)[name].ainvoke(args))
    assert isinstance(result, str), "every account tool returns a JSON string"
    parsed = json.loads(result)
    assert isinstance(parsed, dict)
    return parsed


# -- the shape of the toolbelt --------------------------------------------------------------------


def test_the_twelve_tools_are_built_in_the_manual_order_with_descriptions() -> None:
    runtime, _, _, _ = _runtime()
    built = build_account_tools(runtime)
    assert tuple(tool.name for tool in built) == ACCOUNT_TOOL_NAMES
    assert all(tool.description for tool in built)
    assert len(ACCOUNT_TOOL_NAMES) == 12


def test_an_argument_the_schema_forbids_comes_back_as_an_invalid_arguments_refusal() -> None:
    runtime, clients, _, _ = _runtime()
    refused = _call(runtime, "fetch_page", url="not-a-url")
    assert refused["code"] == "invalid_arguments" and refused["recoverable"] is True
    assert clients.exa_client.contents_calls == [], "no provider is touched by a bad argument"


# -- read_account_state ---------------------------------------------------------------------------


def _claim(
    field_key: str,
    *,
    url: str | None,
    span: str | None,
    source_key: str | None = None,
    markers: Mapping[str, Any] | None = None,
) -> Claim:
    return Claim(
        entity_id=ACCOUNT_ID,
        entity_type=EntityType.ACCOUNT,
        field_key=field_key,
        value_json=["Acme"],
        source_tier=4,
        extraction_method=ExtractionMethod.LLM_SYNTHESIS,
        run_id=RunId(RUN_ID),
        research_mode=ResearchMode.ACCOUNT_PROFILING,
        confidence=0.6,
        reuse_scope=ReuseScope.TENANT_PRIVATE,
        workspace_id="ws-1",
        source_url=url,
        evidence_span=span,
        source_key=source_key,
        write_markers=dict(markers) if markers else None,
    )


def _stub_claims(monkeypatch: pytest.MonkeyPatch, claims: Sequence[Claim]) -> None:
    async def _claims_for_runs(conn: Any, run_ids: Any, *, scope: Any) -> Sequence[Claim]:
        return list(claims)

    monkeypatch.setattr(tools, "claims_for_runs", _claims_for_runs)


def test_read_account_state_reports_the_job_claims_and_the_open_catalog_fields(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runtime, _, _, _ = _runtime()
    _stub_claims(
        monkeypatch,
        [_claim("account.named_customers", url="https://probook.ai/customers", span="Acme")],
    )

    state = _call(runtime, "read_account_state")

    assert state["account"]["domain"] == "probook.ai"
    assert [c["field_key"] for c in state["claims"]] == ["account.named_customers"]
    assert "account.gtm_tooling_stack" in state["open_fields"]
    assert "account.named_customers" not in state["open_fields"]
    assert state["icp"].startswith("# icp")
    assert state["already_established"] == "Founded 2021."


def test_read_account_state_serves_one_section_when_one_is_asked_for(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runtime, _, _, _ = _runtime()
    _stub_claims(monkeypatch, [])
    state = _call(runtime, "read_account_state", section="icp")
    assert set(state) == {"icp"}


# -- read_ats_board -------------------------------------------------------------------------------


BOARD = AtsBoard(kind="ashby", slug="probook", source_url="https://probook.ai/careers")


def _postings() -> BoardPostings:
    return BoardPostings(
        board=BOARD,
        url="https://api.ashbyhq.com/posting-api/job-board/probook",
        postings=(
            JobPosting(
                title="Senior Manager, ABM",
                department="Marketing",
                team=None,
                location="USA",
                published_at=date(2026, 6, 17),
                days_open=83,
                is_listed=True,
                compensation=None,
                description_plain="Own ABM " * 200,
                url="https://jobs.ashbyhq.com/probook/abc",
                apply_url=None,
            ),
        ),
        raw_ref="raw:board",
        ledger_row_id="row-b",
        cost=_cost(provider="ashby", operation="board"),
    )


def test_read_ats_board_writes_one_claim_per_posting_and_returns_them(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runtime, _, writer, conn_factory = _runtime()
    monkeypatch.setattr(tools, "find_board", lambda url, caller: BOARD)
    monkeypatch.setattr(tools, "fetch_postings", lambda board, caller: _postings())

    result = _call(runtime, "read_ats_board", company_url="https://probook.ai")

    assert result["board"]["slug"] == "probook"
    assert result["postings"][0]["title"] == "Senior Manager, ABM"
    assert len(result["postings"][0]["description_head"]) == 600
    assert len(result["claim_ids"]) == 1
    assert [d.field_key for d in writer.drafts] == ["account.open_requisitions"]
    assert conn_factory.opened >= 1, "the hop drained its ledger under a connection"


def test_read_ats_board_refuses_board_not_found_without_raising(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runtime, _, writer, _ = _runtime()
    monkeypatch.setattr(tools, "find_board", lambda url, caller: None)

    refused = _call(runtime, "read_ats_board", company_url="https://probook.ai")

    assert refused["code"] == "board_not_found"
    assert refused["reaction"].startswith("Fetch the careers page itself")
    assert writer.drafts == []


def test_read_ats_board_refuses_board_fetch_failed_when_the_board_will_not_answer(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runtime, _, _, _ = _runtime()

    def _fetch(board: AtsBoard, caller: Any) -> BoardPostings:
        raise BoardFetchFailed(board.kind, board.slug, "https://board.test", 503)

    monkeypatch.setattr(tools, "find_board", lambda url, caller: BOARD)
    monkeypatch.setattr(tools, "fetch_postings", _fetch)

    assert _call(runtime, "read_ats_board", company_url="https://probook.ai")["code"] == (
        "board_fetch_failed"
    )


# -- fetch_page / search_web ----------------------------------------------------------------------


def test_fetch_page_returns_the_page_text_it_was_given() -> None:
    runtime, clients, _, _ = _runtime()
    clients.exa_client.text_by_url["https://probook.ai/pricing"] = "Starter, Growth, Scale"

    page = _call(runtime, "fetch_page", url="https://probook.ai/pricing", max_chars=2000)

    assert page["text"] == "Starter, Growth, Scale"
    assert page["url"] == "https://probook.ai/pricing"
    assert clients.exa_client.contents_calls == [(("https://probook.ai/pricing",), 2000)]


def test_fetch_page_refuses_page_unavailable_when_the_fetch_returns_no_text() -> None:
    runtime, clients, _, _ = _runtime()
    clients.exa_client.text_by_url["https://probook.ai/ghost"] = ""

    refused = _call(runtime, "fetch_page", url="https://probook.ai/ghost")

    assert refused["code"] == "page_unavailable"


def test_search_web_returns_bounded_hits() -> None:
    runtime, clients, _, _ = _runtime()

    found = _call(runtime, "search_web", query="Probook ABM", num_results=5)

    assert found["hits"][0]["url"] == "https://probook.ai/blog/abm"
    assert clients.exa_client.search_calls[0]["num_results"] == 5


# -- lookup_company / lookup_people ---------------------------------------------------------------


def test_lookup_company_writes_the_five_mapped_fields_and_returns_the_rest() -> None:
    runtime, _, writer, _ = _runtime()

    found = _call(runtime, "lookup_company", domain="probook.ai")

    assert {d.field_key for d in writer.drafts} == {
        "core.company_linkedin_url",
        "core.industry",
        "core.employee_count",
        "core.revenue_band",
        "core.hq_location",
    }
    assert found["technologies"] == ["HubSpot"]
    assert len(found["claim_ids"]) == 5
    assert found["funding"]["rounds"][0]["investors"] == ["Sequoia Capital"]
    assert found["funding"]["total_amount"] == 12_000_000


def test_lookup_company_refuses_company_not_found() -> None:
    runtime, clients, writer, _ = _runtime()
    clients.ai_ark_client.company = None

    assert _call(runtime, "lookup_company", domain="probook.ai")["code"] == "company_not_found"
    assert writer.drafts == []


def test_lookup_people_confirms_identity_and_writes_no_claims() -> None:
    runtime, clients, writer, _ = _runtime()

    people = _call(
        runtime, "lookup_people", name_variants=["Nick Fisher"], domain="probook.ai", size=2
    )

    assert people["people"][0]["linkedin_url"] == "https://www.linkedin.com/in/nick"
    assert writer.drafts == [], "committee membership becomes a claim only through write_claims"
    assert clients.ai_ark_client.people_calls == [(("Nick Fisher",), "probook.ai", 2)]


# -- the halt latch and the repeated-call refusal --------------------------------------------------


def test_provider_halt_latches_for_the_job_and_every_later_call_is_refused_identically() -> None:
    runtime, clients, _, _ = _runtime()
    clients.exa_client.raise_on_contents = ProviderHalted("exa", "exa_credit_exhausted")

    first = _call(runtime, "fetch_page", url="https://probook.ai/pricing")
    assert first["code"] == "provider_halted:exa"

    calls_before = len(clients.exa_client.search_calls)
    second = _call(runtime, "search_web", query="anything at all")
    assert second["code"] == "provider_halted:exa"
    assert len(clients.exa_client.search_calls) == calls_before, "the latch precedes the hop"
    assert runtime.halted["exa"]


def test_identical_call_after_a_refusal_is_refused_without_a_provider_hop() -> None:
    runtime, clients, _, _ = _runtime()
    clients.exa_client.text_by_url["https://probook.ai/ghost"] = ""

    first = _call(runtime, "fetch_page", url="https://probook.ai/ghost")
    assert first["code"] == "page_unavailable"

    second = _call(runtime, "fetch_page", url="https://probook.ai/ghost")

    assert second["code"] == "identical_call_repeated"
    assert "page_unavailable" in second["detail"], "the earlier refusal is named"
    assert len(clients.exa_client.contents_calls) == 1, "the repeat never reached the provider"


# -- write_claims ---------------------------------------------------------------------------------


def _claim_input(index: int) -> dict[str, Any]:
    return {
        "field_key": "account.named_customers",
        "value": [f"Customer {index}"],
        "evidence_span": f"Customer {index} trusts Probook",
        "source_url": "https://probook.ai/customers",
        "priority": 2,
    }


def test_write_claims_caps_at_fifty_and_marks_the_rest_refused() -> None:
    runtime, _, writer, _ = _runtime()

    fifty = _call(runtime, "write_claims", claims=[_claim_input(i) for i in range(50)])
    assert len(fifty["written"]) == 50

    refused = _call(runtime, "write_claims", claims=[_claim_input(i) for i in range(51)])

    assert refused["code"] == "invalid_arguments"
    assert len(writer.drafts) == 50, "nothing beyond the ceiling was written"


def test_write_claims_writes_each_claim_alone_so_one_bad_value_costs_only_itself() -> None:
    """A model-produced batch of fifty must not lose forty-nine claims to one unwritable value."""
    runtime, _, writer, conn_factory = _runtime()
    writer.raise_on = {"account.gtm_tooling_stack"}
    claims = [_claim_input(0), _claim_input(1), _claim_input(2)]
    claims[1]["field_key"] = "account.gtm_tooling_stack"

    result = _call(runtime, "write_claims", claims=claims)

    assert "code" not in result, "one refused value is a reported failure, never a tool_error"
    assert len(result["written"]) == 2
    assert result["write_failures"] == [
        {
            "field_key": "account.gtm_tooling_stack",
            "error": "cannot write account.gtm_tooling_stack",
        }
    ]
    assert [draft.field_key for draft in writer.drafts] == [
        "account.named_customers",
        "account.named_customers",
    ], "the two writable claims landed"
    assert conn_factory.opened == 3, "one transaction per claim"


def test_write_claims_forces_the_two_never_outreach_safe_fields() -> None:
    runtime, _, writer, _ = _runtime()

    _call(
        runtime,
        "write_claims",
        claims=[
            {
                "field_key": "account.reputation_risk",
                "value": {"what": "a layoff round"},
                "evidence_span": "laid off 20%",
                "source_url": "https://news.test/probook",
                "priority": 2,
                "outreach_safe": True,
            }
        ],
    )

    assert writer.drafts[0].outreach_safe is False


def test_write_claims_refuses_a_named_committee_candidate_with_no_confirming_url() -> None:
    runtime, _, writer, _ = _runtime()

    refused = _call(
        runtime,
        "write_claims",
        claims=[
            {
                "field_key": "account.committee_candidate",
                "value": {"name": "Nick Fisher", "persona": "champion"},
                "evidence_span": "VP Marketing at Probook",
                "source_url": "https://probook.ai/about",
                "priority": 2,
            }
        ],
    )

    assert refused["code"] == "invalid_arguments" and "confirmed_by" in refused["detail"]
    assert writer.drafts == []


def test_write_claims_reports_the_expected_shape_when_a_value_missed_its_schema() -> None:
    """The model wrote a string into an object field; the receipt says what shape was wanted."""
    runtime, _, writer, _ = _runtime()
    writer.schema_invalid = {"core.hq_location"}
    claim = _claim_input(0)
    claim["field_key"] = "core.hq_location"
    claim["value"] = "New York, NY"

    result = _call(runtime, "write_claims", claims=[claim])

    (row,) = result["written"]
    assert row["markers"]["schema_valid"] is False
    assert row["expected_shape"] == "object{raw: string, city?: string}"
    assert row["hint"].startswith(
        "rewrite the value in this shape and write it again with corrects_claim_id="
    )
    assert row["claim_id"] in row["hint"]


def test_write_claims_receipts_carry_no_shape_when_the_value_fit() -> None:
    runtime, _, _, _ = _runtime()

    result = _call(runtime, "write_claims", claims=[_claim_input(0)])

    (row,) = result["written"]
    assert "expected_shape" not in row and "hint" not in row


# -- structure_material ---------------------------------------------------------------------------


MATERIAL = "Probook's customers page names Acme. " * 5
SOURCES = [{"url": "https://probook.ai/customers", "kind": "page", "text": MATERIAL}]


def test_structure_material_writes_claims_negatives_and_returns_ids() -> None:
    runtime, clients, writer, _ = _runtime()

    structured = _call(
        runtime,
        "structure_material",
        subject_kind="account",
        subject_name="Probook",
        subject_domain_or_company="probook.ai",
        sources=SOURCES,
        notes="my own read: they are scaling",
        mode="intent_sweep",
    )

    # A proposed field is *written* too (the lenient gate registers it), and it is also listed
    # under "proposed" so the model can see which of its rows had no registered home.
    assert [w["field_key"] for w in structured["written"]] == [
        "account.named_customers",
        "account.pricing_shape",
    ]
    assert structured["negatives_written"] == 1
    assert structured["proposed"][0]["suggested_key"] == "account.pricing_shape"
    written = {d.field_key for d in writer.drafts}
    assert written == {
        "account.named_customers",
        "account.pricing_shape",
        "account.reputation_risk",
    }
    assert clients.structuring_client.account_calls[0]["mode"] == "intent_sweep"
    risk = next(d for d in writer.drafts if d.field_key == "account.reputation_risk")
    assert risk.outreach_safe is False


def test_structure_material_hands_the_client_the_blocks_and_the_notes_apart() -> None:
    runtime, clients, _, _ = _runtime()

    _call(
        runtime,
        "structure_material",
        subject_kind="account",
        subject_name="Probook",
        subject_domain_or_company="probook.ai",
        sources=[
            {"url": "https://probook.ai/customers", "kind": "page", "text": MATERIAL},
            {"kind": "provider", "text": "AI Ark holds 36 staff for probook.ai. " * 2},
        ],
        notes="my own read: dispatch is the wedge",
    )

    [call] = clients.structuring_client.account_calls
    assert [block.kind for block in call["sources"]] == ["page", "provider"]
    assert call["sources"][0].url == "https://probook.ai/customers"
    assert call["sources"][1].url is None
    assert call["notes"] == "my own read: dispatch is the wedge"


def test_structure_material_refuses_the_old_free_material_argument() -> None:
    runtime, clients, _, _ = _runtime()

    refused = _call(
        runtime,
        "structure_material",
        subject_kind="account",
        subject_name="Probook",
        subject_domain_or_company="probook.ai",
        material=MATERIAL,
    )

    assert refused["code"] == "invalid_arguments"
    assert clients.structuring_client.account_calls == []


def test_structure_material_needs_at_least_one_source() -> None:
    runtime, _, _, _ = _runtime()

    refused = _call(
        runtime,
        "structure_material",
        subject_kind="account",
        subject_name="Probook",
        subject_domain_or_company="probook.ai",
        sources=[],
    )

    assert refused["code"] == "invalid_arguments"


def test_structure_material_reports_a_failed_draft_instead_of_losing_the_batch() -> None:
    runtime, _, writer, _ = _runtime()
    writer.raise_on = {"account.pricing_shape"}

    structured = _call(
        runtime,
        "structure_material",
        subject_kind="account",
        subject_name="Probook",
        subject_domain_or_company="probook.ai",
        sources=SOURCES,
    )

    assert [w["field_key"] for w in structured["written"]] == ["account.named_customers"]
    assert structured["write_failures"] == [
        {"field_key": "account.pricing_shape", "error": "cannot write account.pricing_shape"}
    ]
    # the draft after the failure still landed: one transaction per draft
    assert {d.field_key for d in writer.drafts} == {
        "account.named_customers",
        "account.reputation_risk",
    }


def test_structure_material_reports_the_rows_a_mode_cap_dropped() -> None:
    runtime, clients, _, _ = _runtime()
    clients.structuring_client.output = replace(
        clients.structuring_client.output, dropped_rows=3, mode="intent_sweep"
    )

    structured = _call(
        runtime,
        "structure_material",
        subject_kind="account",
        subject_name="Probook",
        subject_domain_or_company="probook.ai",
        sources=SOURCES,
        mode="intent_sweep",
    )

    assert structured["dropped_rows"] == 3


def test_write_each_isolates_every_draft_in_its_own_transaction() -> None:
    runtime, _, writer, conn_factory = _runtime()
    writer.raise_on = {"account.gtm_tooling_stack"}
    drafts = [
        _draft_for("account.named_customers"),
        _draft_for("account.gtm_tooling_stack"),
        _draft_for("core.industry"),
    ]

    results = _run(runtime.write_each(drafts))

    assert isinstance(results[0], WriteReceipt)
    assert results[1] == tools.WriteFailure(
        field_key="account.gtm_tooling_stack", error="cannot write account.gtm_tooling_stack"
    )
    assert isinstance(results[2], WriteReceipt)
    assert conn_factory.opened == 3, "one transaction per draft"


def _draft_for(field_key: str) -> ClaimDraft:
    return ClaimDraft(
        entity_id=ACCOUNT_ID,
        entity_type=EntityType.ACCOUNT,
        field_key=field_key,
        value_json=["Acme"],
        extraction_method=ExtractionMethod.LLM_SYNTHESIS,
        run_id=RunId(RUN_ID),
        research_mode=ResearchMode.ACCOUNT_PROFILING,
        workspace_id="ws-1",
    )


def test_structure_material_refuses_a_person_subject_until_r3() -> None:
    runtime, clients, _, _ = _runtime()

    refused = _call(
        runtime,
        "structure_material",
        subject_kind="person",
        subject_name="Nick Fisher",
        subject_domain_or_company="Probook",
        sources=SOURCES,
    )

    assert refused["code"] == "invalid_arguments" and "person" in refused["detail"]
    assert clients.structuring_client.account_calls == []


def test_structure_material_refuses_structuring_unparseable() -> None:
    runtime, clients, _, _ = _runtime()
    clients.structuring_client.raise_with = tools.RawParseError("raw:x", "not JSON")

    refused = _call(
        runtime,
        "structure_material",
        subject_kind="account",
        subject_name="Probook",
        subject_domain_or_company="probook.ai",
        sources=SOURCES,
    )

    assert refused["code"] == "structuring_unparseable"


# -- research_deep --------------------------------------------------------------------------------


CHARTER = "Research Probook's ABM programme, its GTM stack and its buying committee. " * 4


def test_research_deep_returns_the_report_and_the_lock() -> None:
    runtime, clients, _, _ = _runtime()

    report = _call(
        runtime,
        "research_deep",
        charter=CHARTER,
        probes=["who owns ABM"],
        same_name_exclusions=["HP ProBook"],
    )

    assert report["thin"] is False and report["report"].startswith("A long report about")
    sent = clients.exa_client.deep_calls[0]
    assert "HP ProBook" in sent["system_prompt"] and "Probook" in sent["system_prompt"]
    assert "who owns ABM" in sent["query"] and "Founded 2021." in sent["query"]


def test_research_deep_marks_thin_reports() -> None:
    runtime, clients, _, _ = _runtime()
    clients.exa_client.deep_report = "too short"

    report = _call(runtime, "research_deep", charter=CHARTER)

    assert report["thin"] is True and report["report"] == "too short"


def test_research_deep_refuses_only_when_the_report_is_empty() -> None:
    runtime, clients, _, _ = _runtime()
    clients.exa_client.deep_report = ""

    assert _call(runtime, "research_deep", charter=CHARTER)["code"] == "deep_thin_response"


def test_research_deep_clips_the_already_established_block_and_says_where_the_rest_is() -> None:
    lines = "\n".join(f"- account.field_{i}: {'x' * 90} (https://s.test/{i})" for i in range(200))
    scope = replace(SCOPE, already_established=lines)
    runtime, clients, _, _ = _runtime(scope)

    _call(runtime, "research_deep", charter=CHARTER)

    query = clients.exa_client.deep_calls[-1]["query"]
    established = query.split("ALREADY ESTABLISHED", 1)[1]
    assert len(established) <= 6000 + 200, "whole lines up to the cap, plus the omission note"
    assert "lines omitted" in established
    assert 'read_account_state(section="already_established")' in established
    assert "- account.field_0:" in established and "- account.field_199:" not in established


def test_research_deep_passes_a_short_established_block_through_untouched() -> None:
    runtime, clients, _, _ = _runtime()
    _call(runtime, "research_deep", charter=CHARTER)
    query = clients.exa_client.deep_calls[-1]["query"]
    assert query.endswith(
        "ALREADY ESTABLISHED (do not re-derive; find what is NOT here)\nFounded 2021."
    )


# -- read_media_feeds -----------------------------------------------------------------------------


EPISODE = Episode(
    number=42,
    title="Nick Fisher on ABM",
    enclosure_url="https://media.test/42.mp3",
    enclosure_bytes=1024,
    duration_s=300,
    published_at=None,
    link="https://pod.test/42",
    description="with Nick Fisher",
)


def _stub_podcast(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    podcast = Podcast(title="The GTM Show", feed_url="https://pod.test/feed", episodes=(EPISODE,))
    downloaded = AudioFile(
        path=tmp_path / "42.mp3",
        bytes=1024,
        sha256="a" * 64,
        duration_s=300,
        content_type="audio/mpeg",
        cost=_cost(provider="rss", operation="enclosure"),
    )
    monkeypatch.setattr(tools, "fetch_feed", lambda url, caller: podcast)
    monkeypatch.setattr(
        tools, "download_enclosure", lambda episode, dest, caller, *, max_bytes: downloaded
    )


def test_read_media_feeds_transcribes_a_short_episode_and_writes_the_index_claim(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    runtime, clients, writer, _ = _runtime()
    _stub_podcast(monkeypatch, tmp_path)

    found = _call(
        runtime,
        "read_media_feeds",
        person_name="Nick Fisher",
        person_role="VP Marketing",
        feed_url="https://pod.test/feed",
        episode_number=42,
    )

    assert found["speaker_verified"] is True
    assert found["quotes"][0]["text"].startswith("I still build")
    assert clients.media_client.short_calls and not clients.media_client.long_calls
    assert [d.field_key for d in writer.drafts] == ["account.media_layer_index"]
    assert writer.drafts[0].value_json[0]["speaker_verified"] is True


def test_read_media_feeds_refuses_episode_not_found(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    runtime, _, writer, _ = _runtime()
    _stub_podcast(monkeypatch, tmp_path)

    refused = _call(
        runtime,
        "read_media_feeds",
        person_name="Nick Fisher",
        feed_url="https://pod.test/feed",
        episode_number=99,
    )

    assert refused["code"] == "episode_not_found" and writer.drafts == []


def test_read_media_feeds_refuses_an_enclosure_over_the_ceiling(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    runtime, _, _, _ = _runtime()
    _stub_podcast(monkeypatch, tmp_path)

    def _too_big(episode: Any, dest: Any, caller: Any, *, max_bytes: int) -> AudioFile:
        raise EnclosureTooLarge("https://media.test/42.mp3", 999, max_bytes, declared=True)

    monkeypatch.setattr(tools, "download_enclosure", _too_big)

    refused = _call(
        runtime,
        "read_media_feeds",
        person_name="Nick Fisher",
        feed_url="https://pod.test/feed",
        episode_number=42,
    )
    assert refused["code"] == "enclosure_too_large"


def test_read_media_feeds_records_the_item_then_refuses_when_the_speaker_is_unverified(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    runtime, clients, writer, _ = _runtime()
    _stub_podcast(monkeypatch, tmp_path)
    monkeypatch.setattr(
        tools, "verify_speaker", lambda transcript, context: SpeakerVerdict(False, "")
    )

    refused = _call(
        runtime,
        "read_media_feeds",
        person_name="Nick Fisher",
        feed_url="https://pod.test/feed",
        episode_number=42,
    )

    assert refused["code"] == "speaker_unverified"
    assert [d.field_key for d in writer.drafts] == ["account.media_layer_index"]
    assert writer.drafts[0].value_json[0]["speaker_verified"] is False
    assert clients.media_client.quote_calls == [], "nothing is quoted off an unverified speaker"


def test_read_media_feeds_needs_one_of_the_two_urls() -> None:
    runtime, _, _, _ = _runtime()
    refused = _call(runtime, "read_media_feeds", person_name="Nick Fisher")
    assert refused["code"] == "invalid_arguments"


def test_read_media_feeds_takes_the_youtube_words_path_without_transcribing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runtime, clients, writer, _ = _runtime()
    monkeypatch.setattr(
        tools,
        "youtube_metadata",
        lambda url, caller: YouTubeMeta(
            video_id="v1", title="Nick on ABM", length_s=900, cost=_cost(provider="youtube")
        ),
    )
    monkeypatch.setattr(
        tools,
        "youtube_words",
        lambda url, page_text, *, title=None, cost=None: YouTubeWords(
            url=url, title=title, text="indexed words about ABM", cost=cost
        ),
    )

    found = _call(
        runtime,
        "read_media_feeds",
        person_name="Nick Fisher",
        youtube_url="https://www.youtube.com/watch?v=abcdefghijk",
    )

    assert found["words"] == "indexed words about ABM"
    assert clients.media_client.short_calls == [], "the words path never transcribes"
    assert [d.field_key for d in writer.drafts] == ["account.media_layer_index"]


# -- verify_links ---------------------------------------------------------------------------------


def _recorder(monkeypatch: pytest.MonkeyPatch) -> list[AnnotationRow]:
    """Capture the annotation rows ``verify_links`` writes, instead of writing them."""
    recorded: list[AnnotationRow] = []

    async def _record(conn: Any, *, job_id: UUID, rows: Sequence[AnnotationRow]) -> int:
        recorded.extend(rows)
        return len(rows)

    monkeypatch.setattr(tools, "record_annotations", _record)
    return recorded


def test_verify_links_records_annotations_per_verdict(monkeypatch: pytest.MonkeyPatch) -> None:
    runtime, clients, _, _ = _runtime()
    exact = _claim("account.named_customers", url="https://probook.ai/a", span="page text about")
    missing = _claim("account.named_customers", url="https://probook.ai/b", span="never written")
    _stub_claims(monkeypatch, [exact, missing])
    recorded = _recorder(monkeypatch)

    audit = _call(runtime, "verify_links")

    assert audit["EXACT"] == 1
    assert audit["NOT_FOUND"] == [str(missing.id)]
    assert {row.verdict for row in recorded} == {"EXACT", "NOT_FOUND"}
    assert len(clients.exa_client.contents_calls) == 2


def test_verify_links_reports_a_failed_fetch_rather_than_refusing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runtime, clients, _, _ = _runtime()
    _stub_claims(
        monkeypatch, [_claim("account.named_customers", url="https://probook.ai/a", span="Acme")]
    )
    _recorder(monkeypatch)
    clients.exa_client.raise_on_contents = RuntimeError("boom")

    audit = _call(runtime, "verify_links")

    assert audit["fetch_failed"] == ["https://probook.ai/a"]
    assert audit["EXACT"] == 0


_PARTIAL_PAGE = "The company runs an account-based marketing programme across Europe."
_PARTIAL_SPAN = "The company runs an account-based marketing programme across Mars."


def test_verify_links_records_why_each_claim_got_its_verdict(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Five claims, five different reasons — the audit says *why*, not only *what*.

    A verdict alone cannot be acted on: ``fetch_failed`` on a page that returned no text is a
    broken source, ``fetch_failed`` on a page that would not load is a dead link, and NOT_FOUND on
    a quote the model took from a *report about* the account is second-hand rather than invented.
    Each of those wants a different repair, so each is recorded under its own reason.
    """
    runtime, clients, _, _ = _runtime()
    exa = clients.exa_client
    exa.text_by_url["https://probook.ai/exact"] = "page text about Probook and its customers"
    exa.text_by_url["https://probook.ai/partial"] = _PARTIAL_PAGE
    exa.text_by_url["https://probook.ai/empty"] = ""
    exa.text_by_url["https://probook.ai/report"] = "a page that never says any of that"
    delegate = exa.contents

    def _contents(urls: Sequence[str], **kwargs: Any) -> Any:
        if "https://probook.ai/dead" in urls:
            raise RuntimeError("connection reset")
        return delegate(urls, **kwargs)

    monkeypatch.setattr(exa, "contents", _contents)

    on_page = _claim(
        "account.named_customers",
        url="https://probook.ai/exact",
        span="page text about Probook",
        source_key="exa_contents",
    )
    partial = _claim(
        "account.named_customers", url="https://probook.ai/partial", span=_PARTIAL_SPAN
    )
    empty = _claim("account.named_customers", url="https://probook.ai/empty", span="Acme")
    dead = _claim("account.named_customers", url="https://probook.ai/dead", span="Acme")
    second_hand = _claim(
        "account.named_customers",
        url="https://probook.ai/report",
        span="Probook counts Acme among its customers",
        markers={"source_kind_block": "report"},
    )
    _stub_claims(monkeypatch, [on_page, partial, empty, dead, second_hand])
    recorded = _recorder(monkeypatch)

    audit = _call(runtime, "verify_links")

    assert audit["by_reason"] == {
        "EXACT/on_page": 1,
        "PARTIAL/partial_on_page": 1,
        "fetch_failed/page_empty": 1,
        "fetch_failed/page_unreachable": 1,
        "NOT_FOUND/second_hand_from_report": 1,
    }
    assert audit["EXACT"] == 1 and audit["PARTIAL"] == 1
    assert audit["NOT_FOUND"] == [str(second_hand.id)]
    assert sorted(audit["fetch_failed"]) == ["https://probook.ai/dead", "https://probook.ai/empty"]

    by_claim = {str(row.claim_id): row for row in recorded}
    assert len(by_claim) == 5, "every claim carries its own annotation"
    assert by_claim[str(on_page.id)].detail == {
        "reason": "on_page",
        "url": "https://probook.ai/exact",
        "origin": "exa_contents",
        "structuring_mode": None,
    }
    assert by_claim[str(second_hand.id)].detail["structuring_mode"] == "report"
    assert by_claim[str(dead.id)].verdict == "fetch_failed"
    assert by_claim[str(dead.id)].detail["reason"] == "page_unreachable"


def test_verify_links_marks_a_quote_from_the_agents_own_notes_without_fetching(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A quote that sat in the agent's notes rather than in a source cannot be on any page.

    Fetching to prove that would spend a contents call to learn nothing, so the claim is recorded
    NOT_FOUND with the reason that already explains it.
    """
    runtime, clients, _, _ = _runtime()
    noted = _claim(
        "account.named_customers",
        url="https://probook.ai/a",
        span="page text about Probook",
        markers={"quoted_context": True},
    )
    _stub_claims(monkeypatch, [noted])
    recorded = _recorder(monkeypatch)

    audit = _call(runtime, "verify_links")

    assert audit["by_reason"] == {"NOT_FOUND/quoted_context": 1}
    assert audit["NOT_FOUND"] == [str(noted.id)]
    assert clients.exa_client.contents_calls == [], "no page is bought to check a note"
    assert recorded[0].detail["reason"] == "quoted_context"


# -- finalize_research ----------------------------------------------------------------------------


def _finalize_args() -> dict[str, Any]:
    return {
        "summary": "Probook is a Series A GTM tool with an evidenced ABM programme.",
        "fit_verdicts": [
            {"gate": "stage", "verdict": "fail", "rationale": "nothing found", "claim_ids": []}
        ],
        "gaps": ["no funding wire found"],
        "committee_candidates": [
            {
                "name": "Nick Fisher",
                "title": "VP Marketing",
                "persona": "champion",
                "confirmed_by": "https://probook.ai/about",
            },
            {"name": "Unconfirmed Person", "title": "CFO", "persona": "economic_buyer"},
        ],
    }


def test_finalize_writes_the_verdicts_and_the_confirmed_candidates_only() -> None:
    runtime, _, writer, _ = _runtime()

    accepted = _call(runtime, "finalize_research", **_finalize_args())

    assert accepted["accepted"] is True
    assert accepted["dropped_candidates"] == ["Unconfirmed Person"]
    verdict = next(d for d in writer.drafts if d.field_key == "account.icp_fit_verdict")
    assert verdict.value_json["verdict"] == "unclear", "a fail with no evidence is downgraded"
    assert [
        d.value_json["name"] for d in writer.drafts if d.field_key == "account.committee_candidate"
    ] == ["Nick Fisher"]
    assert runtime.finalization is not None and runtime.finalization["gaps"] == [
        "no funding wire found"
    ]


def test_a_verdict_on_a_gate_the_icp_never_named_is_refused_and_names_the_admitted_keys() -> None:
    """Verdicts are keyed to the ICP's hard gates, so receipts compare across accounts."""
    gated = replace(SCOPE, icp_gate_keys=("stage", "geography"))
    runtime, _, writer, _ = _runtime(gated)

    refused = _call(
        runtime,
        "finalize_research",
        **{
            **_finalize_args(),
            "fit_verdicts": [{"gate": "vibes", "verdict": "pass", "rationale": "they feel right"}],
        },
    )

    assert refused["code"] == "invalid_arguments"
    assert "vibes" in refused["detail"]
    assert "stage" in refused["detail"] and "geography" in refused["detail"]
    assert runtime.finalization is None, "a refused finalization does not close the job"
    assert writer.drafts == [], "nothing is written for a verdict the ICP cannot key"


def test_an_icp_gate_the_agent_did_not_assess_is_filled_unclear_by_the_tool() -> None:
    gated = replace(SCOPE, icp_gate_keys=("stage", "geography"))
    runtime, _, writer, _ = _runtime(gated)

    accepted = _call(
        runtime,
        "finalize_research",
        **{
            **_finalize_args(),
            "fit_verdicts": [
                {
                    "gate": "stage",
                    "verdict": "pass",
                    "rationale": "Series A announced",
                    "claim_ids": ["11111111-1111-1111-1111-111111111111"],
                }
            ],
        },
    )

    assert accepted["accepted"] is True
    assert runtime.finalization is not None
    verdicts = runtime.finalization["fit_verdicts"]
    assert [verdict["gate"] for verdict in verdicts] == ["stage", "geography"]
    assert verdicts[1] == {
        "gate": "geography",
        "verdict": "unclear",
        "rationale": "not assessed",
        "claim_ids": [],
    }
    filled = [
        draft
        for draft in writer.drafts
        if draft.field_key == "account.icp_fit_verdict" and draft.value_json["gate"] == "geography"
    ]
    assert len(filled) == 1
    assert filled[0].markers == {"filled_by_tool": True}, "the claim says who wrote the verdict"


def test_a_second_verdict_for_one_gate_is_dropped_and_reported_never_refused() -> None:
    """A duplicate is noise, not a lie: the first answer stands and the call still lands."""
    gated = replace(SCOPE, icp_gate_keys=("stage", "geography"))
    runtime, _, writer, _ = _runtime(gated)

    accepted = _call(
        runtime,
        "finalize_research",
        **{
            **_finalize_args(),
            "fit_verdicts": [
                {"gate": "stage", "verdict": "pass", "rationale": "Series A announced"},
                {"gate": "stage", "verdict": "fail", "rationale": "on second thoughts"},
                {"gate": "geography", "verdict": "pass", "rationale": "NYC HQ"},
            ],
        },
    )

    assert accepted["accepted"] is True
    assert accepted["duplicate_gates"] == ["stage"]
    assert runtime.finalization is not None
    verdicts = runtime.finalization["fit_verdicts"]
    assert [verdict["gate"] for verdict in verdicts] == ["stage", "geography"]
    assert verdicts[0]["verdict"] == "pass", "the first answer for a gate is the one kept"
    written = [d for d in writer.drafts if d.field_key == "account.icp_fit_verdict"]
    assert len(written) == 2, "one claim per gate, whatever the model sent"


def test_a_gate_label_differing_only_in_case_is_the_gate_the_icp_named() -> None:
    """Folding a near-miss label costs nothing; refusing it costs the run its only finalization."""
    gated = replace(SCOPE, icp_gate_keys=("stage", "geography"))
    runtime, _, writer, _ = _runtime(gated)

    accepted = _call(
        runtime,
        "finalize_research",
        **{
            **_finalize_args(),
            "fit_verdicts": [
                {"gate": "Geography", "verdict": "pass", "rationale": "NYC HQ", "claim_ids": []}
            ],
        },
    )

    assert accepted["accepted"] is True
    assert runtime.finalization is not None
    verdicts = runtime.finalization["fit_verdicts"]
    assert [verdict["gate"] for verdict in verdicts] == ["geography", "stage"]
    assert verdicts[0]["verdict"] == "pass", "the model's answer was kept, only its key rewritten"
    geography = [
        draft
        for draft in writer.drafts
        if draft.field_key == "account.icp_fit_verdict" and draft.value_json["gate"] == "geography"
    ]
    assert len(geography) == 1, "the claim carries the ICP's spelling of the key"
    assert geography[0].markers == {}, "an answered gate is not marked filled_by_tool"


def test_a_gate_label_with_trailing_whitespace_is_the_gate_the_icp_named() -> None:
    gated = replace(SCOPE, icp_gate_keys=("stage", "geography"))
    runtime, _, writer, _ = _runtime(gated)

    accepted = _call(
        runtime,
        "finalize_research",
        **{
            **_finalize_args(),
            "fit_verdicts": [
                {"gate": "stage ", "verdict": "pass", "rationale": "Series A", "claim_ids": []}
            ],
        },
    )

    assert accepted["accepted"] is True
    assert runtime.finalization is not None
    assert [v["gate"] for v in runtime.finalization["fit_verdicts"]] == ["stage", "geography"]
    assert [
        draft.value_json["gate"]
        for draft in writer.drafts
        if draft.field_key == "account.icp_fit_verdict"
    ] == ["stage", "geography"]


def test_a_transient_tool_error_is_not_remembered_so_the_identical_retry_runs_again() -> None:
    """``tool_error`` is the socket failing, not a judgement: it must not foreclose the retry."""
    runtime, clients, _, _ = _runtime()
    clients.exa_client.raise_on_contents = RuntimeError("the socket melted")

    first = _call(runtime, "fetch_page", url="https://probook.ai/pricing")
    clients.exa_client.raise_on_contents = None
    second = _call(runtime, "fetch_page", url="https://probook.ai/pricing")

    assert first["code"] == "tool_error:RuntimeError"
    assert "code" not in second, "the identical retry runs rather than replaying the failure"
    assert len(clients.exa_client.contents_calls) == 2


def test_finalize_twice_is_refused_finalization_already_proposed() -> None:
    runtime, _, _, _ = _runtime()
    _call(runtime, "finalize_research", **_finalize_args())

    refused = _call(runtime, "finalize_research", **_finalize_args())

    assert refused["code"] == "finalization_already_proposed"


def test_every_other_tool_is_closed_once_the_decision_is_made() -> None:
    runtime, clients, _, _ = _runtime()
    _call(runtime, "finalize_research", **_finalize_args())

    refused = _call(runtime, "fetch_page", url="https://probook.ai/pricing")

    assert refused["code"] == "finalization_already_proposed"
    assert clients.exa_client.contents_calls == []


# -- the failure law ------------------------------------------------------------------------------


def test_every_tool_wraps_unexpected_exceptions_as_tool_error_refusals(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runtime, clients, _, _ = _runtime()
    clients.exa_client.raise_on_contents = RuntimeError("the socket melted")

    refused = _call(runtime, "fetch_page", url="https://probook.ai/pricing")

    assert refused["code"] == "tool_error:RuntimeError"
    assert refused["recoverable"] is True and "melted" in refused["detail"]


def test_a_tool_counts_its_calls_for_the_stop_policy() -> None:
    runtime, _, _, _ = _runtime()
    _call(runtime, "fetch_page", url="https://probook.ai/pricing")
    assert runtime.tool_calls == 1


def test_a_halt_met_inside_one_hop_also_latches_the_wire_provider() -> None:
    """One media hop spends on OpenRouter, so a credit halt there must stop structuring too."""
    runtime, clients, _, _ = _runtime()
    clients.exa_client.raise_on_contents = ProviderHalted("openrouter", "credit_exhausted")

    assert _call(runtime, "fetch_page", url="https://probook.ai/pricing")["code"] == (
        "provider_halted:exa"
    )

    refused = _call(
        runtime,
        "structure_material",
        subject_kind="account",
        subject_name="Probook",
        subject_domain_or_company="probook.ai",
        sources=SOURCES,
    )

    assert refused["code"] == "provider_halted:openrouter"
    assert clients.structuring_client.account_calls == []
