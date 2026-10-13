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
import structlog.testing

from clue_api.arv2 import account_research_tools as tools
from clue_api.arv2.account_research_claims import JobScope
from clue_api.arv2.account_research_store import AnnotationRow
from clue_api.arv2.account_research_tools import (
    ACCOUNT_TOOL_NAMES,
    PERSON_TOOL_NAMES,
    ToolRuntime,
    build_account_tools,
    build_person_tools,
)
from clue_api.arv2.ai_ark_client import (
    AiArkCompany,
    AiArkEmailExport,
    AiArkPeople,
    AiArkPerson,
)
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
    MediaFetchError,
    Podcast,
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
    IdentityBinding,
    ResearchMode,
    ReuseScope,
    RunId,
    UseClass,
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

#: The one person a person job researches, at the account above. The lock's employment history is
#: the job's own context — never evidence — exactly as ``JobScope`` documents it.
CONTACT_ID = EntityId(uuid4())

PERSON_SCOPE = replace(
    SCOPE,
    subject_kind="person",
    contact_id=CONTACT_ID,
    person_name="Nick Fisher",
    person_title="VP of Marketing",
    person_linkedin_url="https://www.linkedin.com/in/nicholastfisher",
    employment_history=("VP Product Marketing @ Sysdig (2021–2024)",),
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


_STR_LIST: Mapping[str, Any] = {"type": "array", "items": {"type": "string"}}
#: The registry's own shape for the two appearance-shaped facets: a list of ``{title, url?, date?,
#: venue?}`` objects with ``title`` required.
_APPEARANCES: Mapping[str, Any] = {
    "type": "array",
    "items": {
        "type": "object",
        "required": ["title"],
        "properties": {
            "url": {"type": "string"},
            "date": {"type": "string"},
            "title": {"type": "string"},
            "venue": {"type": "string"},
        },
    },
}

#: The person-side menu as ``read_person_catalog`` serves it, with each field's **real** registry
#: schema and ``use_class_hint`` (read out of ``field_definition`` on 2026-09-09). A person job
#: writes contact fields and the work email, and no ``account.*`` key at all.
PERSON_CATALOG = FieldCatalog(
    contact=(
        FieldSpec("contact.current_title", "Current professional title.", {"type": "string"}),
        FieldSpec("contact.headline", "LinkedIn headline.", {"type": "string"}),
        FieldSpec(
            "contact.reports_to",
            "Who this person reports to.",
            {
                "type": "object",
                "required": ["contact_id"],
                "properties": {
                    "name": {"type": "string"},
                    "contact_id": {"type": "string"},
                },
            },
        ),
        FieldSpec("core.work_email", "Professional email address.", {"type": "string"}),
    ),
    facet=(
        FieldSpec(
            "contact.facet.hobby",
            "Hobbies the person states publicly.",
            _STR_LIST,
            use_class_hint="personal-public-non-sensitive",
        ),
        FieldSpec(
            "contact.facet.publications",
            "Articles, books and bylines they published.",
            _APPEARANCES,
            use_class_hint="professional-public",
        ),
        FieldSpec(
            "contact.facet.voice_quote",
            "Something the person said, verbatim.",
            {
                "type": "object",
                "required": ["text"],
                "properties": {
                    "text": {"type": "string"},
                    "media_url": {"type": "string"},
                    "source_title": {"type": "string"},
                    "media_timestamp": {"type": "string"},
                },
            },
            use_class_hint="professional-public",
        ),
        FieldSpec(
            "contact.facet.hooks",
            "Grounded outreach hooks.",
            _STR_LIST,
            use_class_hint="professional-public",
        ),
        FieldSpec(
            "contact.facet.openers",
            "The openers the research supports.",
            _STR_LIST,
            use_class_hint="professional-public",
        ),
        FieldSpec(
            "contact.facet.excluded_lookalike",
            "A same-name person met and discarded.",
            {
                "type": "object",
                "properties": {
                    "title": {"type": "string"},
                    "reason": {"type": "string"},
                    "discarded_media": {"type": "string"},
                },
            },
            use_class_hint="professional-public",
        ),
        FieldSpec(
            "contact.facet.public_appearances",
            "Podcasts, talks and panels the person appeared in.",
            _APPEARANCES,
            use_class_hint="professional-public",
        ),
    ),
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


def _ark_person(
    *,
    linkedin_url: str = "https://www.linkedin.com/in/nick",
    current_company: str = "Probook",
    current_company_domain: str | None = "probook.ai",
    headline: str = "Demand gen",
) -> AiArkPerson:
    return AiArkPerson(
        full_name="Nick Fisher",
        title="VP Marketing",
        headline=headline,
        linkedin_url=linkedin_url,
        location={"country": "US"},
        current_company=current_company,
        current_company_domain=current_company_domain,
        department={"name": "marketing"},
        ark_id="ark-1",
        raw={"profile": {"title": "VP Marketing", "headline": headline}},
    )


def _email_export(*, found: bool = True) -> AiArkEmailExport:
    return AiArkEmailExport(
        address="nick@probook.ai" if found else None,
        status="VALID" if found else "INVALID",
        domain_type="not_catchall",
        sub_status=None,
        mx_record="probook-ai.mail.protection.outlook.com",
        mx_provider="Outlook",
        mx_found=True,
        mx_google=False,
        free=False,
        generic=False,
        found=found,
        checked_at="2026-09-09T00:00:00Z",
        verdict="verified_smtp" if found else "not_found",
        full_name="Nick Fisher",
        title="VP of Marketing",
        current_company="Probook",
        certifications=(),
        raw_email_block={"status": "VALID"},
        cost=_cost(provider="ai_ark", operation="v1/people/export/single"),
    )


class FakeAiArk:
    def __init__(self) -> None:
        self.company_calls: list[str] = []
        self.people_calls: list[tuple[tuple[str, ...], str, int]] = []
        self.export_calls: list[str] = []
        #: What ``people_by_name`` answers. Settable, so a person test can put the same-name
        #: stranger and the real subject in one page the way the provider does.
        self.people: tuple[AiArkPerson, ...] = (_ark_person(),)
        self.export: AiArkEmailExport = _email_export()
        #: What the export hop raises instead of answering — a transport failure with its retries
        #: spent, which is the shape that used to cost the record's own claims.
        self.raise_on_export: Exception | None = None
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
        return AiArkPeople(people=self.people, cost=_cost(provider="ai_ark", operation="v1/people"))

    def export_email(self, linkedin_url: str) -> AiArkEmailExport:
        self.export_calls.append(linkedin_url)
        if self.raise_on_export is not None:
            raise self.raise_on_export
        return self.export


def _structured(field_key: str, value: Any, *, priority: int = 2, span: str, url: str) -> Any:
    return StructuredClaim(
        field_key=field_key,
        value=value,
        evidence_span=span,
        source_url=url,
        source_kind="personal_primary",
        confidence="high",
        use_class="professional-public",
        outreach_safe=True,
        priority=priority,
        media_timestamp=None,
        evidence_verbatim="EXACT",
        schema_valid=True,
    )


class FakeStructuring:
    def __init__(self) -> None:
        self.account_calls: list[dict[str, Any]] = []
        self.person_calls: list[dict[str, Any]] = []
        self.raise_with: Exception | None = None
        #: What a broad ``structure_person`` answers: one contact facet on the person's own words.
        self.person_output = StructuredOutput(
            claims=(
                _structured(
                    "contact.facet.hobby",
                    ["ultramarathons"],
                    span="I run ultramarathons at the weekend",
                    url="https://nickfisher.dev/about",
                ),
            ),
            proposed=(),
            negatives=(),
            model="m",
            mode="broad",
        )
        #: What the one-question pass answers. A test blanks its claims to prove the refusal.
        self.insight_output = StructuredOutput(
            claims=(
                _structured(
                    "contact.facet.publications",
                    [{"title": "The Pipeline Book"}],
                    priority=3,
                    span="I wrote The Pipeline Book",
                    url="https://nickfisher.dev/book",
                ),
            ),
            proposed=(),
            negatives=(),
            model="m",
            mode="unique_insight",
        )
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

    def structure_person(
        self,
        subject: Any,
        bundle: str,
        catalog: FieldCatalog,
        *,
        mode: str = "broad",
        sources: Any = None,
        notes: str | None = None,
    ) -> StructuredOutput:
        self.person_calls.append(
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
        return self.insight_output if mode == "unique_insight" else self.person_output


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


class MemoryConn:
    """A connection that records the statements a tool writes itself, and answers nothing.

    Only the stage stamp reaches it today: every other tool body here goes through the writer or a
    client double, so a returned ``None`` is a truthful answer to the one statement that lands.
    """

    def __init__(self) -> None:
        self.statements: list[tuple[str, Any]] = []

    async def execute(self, statement: Any, parameters: Any = None) -> None:
        self.statements.append((str(statement), parameters))
        return None


class MemoryConnFactory:
    """A connection factory whose one connection records what was executed on it."""

    def __init__(self) -> None:
        self.opened = 0
        self.conn = MemoryConn()

    def __call__(self) -> Any:
        return self._open()

    @asynccontextmanager
    async def _open(self) -> AsyncIterator[Any]:
        self.opened += 1
        yield self.conn


class RaisingConn:
    """A connection that fails every statement, the way an exhausted pool or a lock wait does."""

    async def execute(self, statement: Any, parameters: Any = None) -> None:
        del statement, parameters
        raise RuntimeError("connection pool exhausted")


class RaisingConnFactory:
    def __call__(self) -> Any:
        return self._open()

    @asynccontextmanager
    async def _open(self) -> AsyncIterator[Any]:
        yield RaisingConn()


def _runtime(
    scope: JobScope = SCOPE,
    *,
    settings: Settings | None = None,
    conn_factory: Any | None = None,
    early_gate: asyncio.Semaphore | None = None,
) -> tuple[ToolRuntime, FakeClients, FakeWriter, Any]:
    clients = FakeClients()
    writer = FakeWriter()
    conn_factory = conn_factory or MemoryConnFactory()
    runtime = ToolRuntime(
        scope=scope,
        settings=settings or Settings(),
        clients=clients,  # type: ignore[arg-type]
        conn_factory=conn_factory,
        artifacts=FakeArtifacts(),
        writer=writer,  # type: ignore[arg-type]
        # The job's subject decides its menu, exactly as the driver composes it: an account job
        # writes account fields, a person job writes contact fields and the work email.
        catalog=PERSON_CATALOG if scope.subject_kind == "person" else CATALOG,
        media_budget=MediaBudget(9000),
        transport_factory=lambda: ScriptedTransport([]),
        now=lambda: datetime(2026, 9, 8, tzinfo=UTC),
        early_gate=early_gate,
    )
    return runtime, clients, writer, conn_factory


def _tools(runtime: ToolRuntime) -> dict[str, Any]:
    """The toolbelt this job actually runs on — the subject decides which of the two it is."""
    built = (
        build_person_tools(runtime)
        if runtime.scope.subject_kind == "person"
        else build_account_tools(runtime)
    )
    return {tool.name: tool for tool in built}


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


def test_write_claims_says_so_when_the_failing_field_is_not_in_this_jobs_catalog() -> None:
    """The account job's catalog is account-only; a contact key can still fail its DB schema.

    ``schema_hint(None)`` renders "any", which would tell the model any shape was fine about a
    value that just failed a schema — and the rewrite hint would be unfollowable.
    """
    runtime, _, writer, _ = _runtime()
    writer.schema_invalid = {"contact.facet.hobby"}
    claim = _claim_input(0)
    claim["field_key"] = "contact.facet.hobby"

    result = _call(runtime, "write_claims", claims=[claim])

    (row,) = result["written"]
    assert row["markers"]["schema_valid"] is False
    assert row["expected_shape"] == "not in this job's catalog"
    assert "hint" not in row


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

    assert [draft for draft, _ in results] == drafts, "each result names the draft it belongs to"
    assert isinstance(results[0][1], WriteReceipt)
    assert results[1][1] == tools.WriteFailure(
        field_key="account.gtm_tooling_stack", error="cannot write account.gtm_tooling_stack"
    )
    assert isinstance(results[2][1], WriteReceipt)
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


def test_the_deep_call_evidence_law_asks_for_one_assertion_per_sentence_quote_first() -> None:
    runtime, clients, _, _ = _runtime()
    _call(runtime, "research_deep", charter=CHARTER)
    system_prompt = clients.exa_client.deep_calls[-1]["system_prompt"]  # the fake's attribute
    assert "One assertion per sentence" in system_prompt
    assert "the verbatim quote first, then the URL in parentheses" in system_prompt
    assert "A NOT FOUND item is its own sentence" in system_prompt


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


def _download_for_real(written: list[Path]) -> Any:
    """A ``download_enclosure`` stand-in that writes the file where asked, as the real one does."""

    def download(episode: Any, dest: Path, caller: Any, *, max_bytes: int) -> AudioFile:
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(b"\x00" * 1024)
        written.append(dest)
        return AudioFile(
            path=dest,
            bytes=1024,
            sha256="a" * 64,
            duration_s=300,
            content_type="audio/mpeg",
            cost=_cost(provider="rss", operation="enclosure"),
        )

    return download


def test_read_media_feeds_downloads_under_the_raw_root_and_deletes_the_audio_once_used(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """The audio is a temporary input to transcription: the transcript and quotes are what is
    kept. Left behind, every podcast lookup would add an episode to the worker's disk forever."""
    root = tmp_path / "arv2-raw"
    runtime, _, _, _ = _runtime(settings=Settings(arv2_raw_root=str(root)))
    _stub_podcast(monkeypatch, tmp_path)
    written: list[Path] = []
    monkeypatch.setattr(tools, "download_enclosure", _download_for_real(written))

    found = _call(
        runtime,
        "read_media_feeds",
        person_name="Nick Fisher",
        feed_url="https://pod.test/feed",
        episode_number=42,
    )

    assert found["speaker_verified"] is True
    assert len(written) == 1
    assert written[0].parent == root / "media" / str(SCOPE.job_id)
    assert not written[0].exists(), "the downloaded audio must not outlive the hop"
    assert not written[0].parent.exists(), "the job's empty media folder goes with it"


def test_read_media_feeds_deletes_the_audio_when_transcription_fails(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    root = tmp_path / "arv2-raw"
    runtime, clients, _, _ = _runtime(settings=Settings(arv2_raw_root=str(root)))
    _stub_podcast(monkeypatch, tmp_path)
    written: list[Path] = []
    monkeypatch.setattr(tools, "download_enclosure", _download_for_real(written))

    def _fails(*_args: Any, **_kwargs: Any) -> Any:
        raise RuntimeError("transcription provider fell over")

    monkeypatch.setattr(clients.media_client, "transcribe_short", _fails)

    failed = _call(
        runtime,
        "read_media_feeds",
        person_name="Nick Fisher",
        feed_url="https://pod.test/feed",
        episode_number=42,
    )

    assert "speaker_verified" not in failed, failed
    assert len(written) == 1 and not written[0].exists()


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


def test_read_media_feeds_falls_through_to_an_alternate_when_the_first_source_will_not_load(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Probook's YouTube page answered 429 and the run had nowhere to try next."""
    _stub_podcast(monkeypatch, tmp_path)
    good_feed = "https://pod.test/feed"
    calls: list[str] = []
    real_fetch = tools.fetch_feed

    def fetch(url: str, caller: Any) -> Any:
        calls.append(url)
        if url == "https://dead.test/feed":
            raise MediaFetchError(url, 429, None)
        return real_fetch(url, caller)

    monkeypatch.setattr(tools, "fetch_feed", fetch)
    runtime, _, writer, _ = _runtime()

    result = _call(
        runtime,
        "read_media_feeds",
        person_name="Nick Fisher",
        feed_url="https://dead.test/feed",
        alternate_urls=[good_feed],
        episode_number=42,
    )

    assert "code" not in result, result
    assert calls == ["https://dead.test/feed", good_feed]
    assert result["source_attempts"] == [
        {
            "url": "https://dead.test/feed",
            "error": "https://dead.test/feed returned HTTP 429 (raw_ref=None)",
        }
    ]
    assert result["item"]["kind"] == "podcast"
    assert any(d.field_key == "account.media_layer_index" for d in writer.drafts)


def test_read_media_feeds_refuses_feed_not_found_naming_every_url_it_tried(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fetch(url: str, caller: Any) -> Any:
        raise MediaFetchError(url, 404, None)

    monkeypatch.setattr(tools, "fetch_feed", fetch)
    runtime, _, writer, _ = _runtime()

    refused = _call(
        runtime,
        "read_media_feeds",
        person_name="Nick Fisher",
        feed_url="https://a.test/feed",
        alternate_urls=["https://b.test/feed"],
    )

    assert refused["code"] == "feed_not_found"
    # The envelope's free-text field is ``detail`` (``refusal_json``); it must name both URLs.
    assert "https://a.test/feed" in refused["detail"]
    assert "https://b.test/feed" in refused["detail"]
    assert writer.drafts == []


def test_read_media_feeds_does_not_fall_through_past_a_feed_that_loaded_but_had_no_episode(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """A feed that loaded and has no matching episode is an answer, not a load failure."""
    _stub_podcast(monkeypatch, tmp_path)
    # ``_stub_podcast`` answers every URL with the same podcast, so the refusal code alone cannot
    # tell a stop from a fall-through: the second candidate would refuse identically. The URLs
    # fetched are what proves the loop stopped.
    calls: list[str] = []
    stubbed_fetch = tools.fetch_feed

    def fetch(url: str, caller: Any) -> Any:
        calls.append(url)
        return stubbed_fetch(url, caller)

    monkeypatch.setattr(tools, "fetch_feed", fetch)
    runtime, _, _, _ = _runtime()
    refused = _call(
        runtime,
        "read_media_feeds",
        person_name="Nobody",
        feed_url="https://pod.test/feed",
        alternate_urls=["https://never.test/feed"],
        episode_title_contains="no such episode",
    )
    assert refused["code"] == "episode_not_found"
    assert calls == ["https://pod.test/feed"], "the answered feed ended the loop"


def test_read_media_feeds_refuses_a_walled_host_before_any_request_is_built(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Routing is by host, so the walled guard must run before the hop is chosen, not inside it.

    A LinkedIn post URL handed in as ``youtube_url`` is not a YouTube URL, so it takes the podcast
    hop — and would be fetched for real if ``reject_native_video`` only lived in the YouTube hop.
    """

    def never(url: str, caller: Any) -> Any:
        raise AssertionError("must not fetch")

    monkeypatch.setattr(tools, "fetch_feed", never)
    runtime, _, writer, _ = _runtime()

    refused = _call(
        runtime,
        "read_media_feeds",
        person_name="Nick Fisher",
        youtube_url="https://www.linkedin.com/posts/someone_activity-1",
    )

    assert refused["code"] == "native_video_rejected"
    assert writer.drafts == []


def test_read_media_feeds_prefers_the_feed_over_the_watch_page_when_both_are_given(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """New behaviour: ``youtube_url`` used to be ignored whenever ``feed_url`` was present."""
    _stub_podcast(monkeypatch, tmp_path)
    calls: list[str] = []
    stubbed_fetch = tools.fetch_feed

    def fetch(url: str, caller: Any) -> Any:
        calls.append(url)
        return stubbed_fetch(url, caller)

    monkeypatch.setattr(tools, "fetch_feed", fetch)
    runtime, _, _, _ = _runtime()

    found = _call(
        runtime,
        "read_media_feeds",
        person_name="Nick Fisher",
        feed_url="https://pod.test/feed",
        youtube_url="https://www.youtube.com/watch?v=abcdefghijk",
        episode_number=42,
    )

    assert found["item"]["kind"] == "podcast"
    assert calls == ["https://pod.test/feed"]


def test_read_media_feeds_fetches_a_url_repeated_in_alternate_urls_only_once(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _stub_podcast(monkeypatch, tmp_path)
    calls: list[str] = []

    def fetch(url: str, caller: Any) -> Any:
        calls.append(url)
        raise MediaFetchError(url, 404, None)

    monkeypatch.setattr(tools, "fetch_feed", fetch)
    runtime, _, _, _ = _runtime()

    refused = _call(
        runtime,
        "read_media_feeds",
        person_name="Nick Fisher",
        feed_url="https://pod.test/feed",
        alternate_urls=["https://pod.test/feed"],
    )

    assert refused["code"] == "feed_not_found"
    assert calls == ["https://pod.test/feed"], "a repeated URL is one candidate, one fetch"


def test_read_media_feeds_names_the_dead_earlier_sources_in_a_later_refusal(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Candidate 1 would not load, candidate 2 answered: the agent must learn both facts."""
    _stub_podcast(monkeypatch, tmp_path)
    stubbed_fetch = tools.fetch_feed

    def fetch(url: str, caller: Any) -> Any:
        if url == "https://dead.test/feed":
            raise MediaFetchError(url, 429, None)
        return stubbed_fetch(url, caller)

    monkeypatch.setattr(tools, "fetch_feed", fetch)
    runtime, _, _, _ = _runtime()

    refused = _call(
        runtime,
        "read_media_feeds",
        person_name="Nick Fisher",
        feed_url="https://dead.test/feed",
        alternate_urls=["https://pod.test/feed"],
        episode_title_contains="no such episode",
    )

    assert refused["code"] == "episode_not_found"
    assert "earlier sources that would not load" in refused["detail"]
    assert "https://dead.test/feed" in refused["detail"]
    assert "429" in refused["detail"]


def test_read_media_feeds_needs_one_of_the_two_urls() -> None:
    runtime, _, _, _ = _runtime()
    refused = _call(runtime, "read_media_feeds", person_name="Nick Fisher")
    assert refused["code"] == "invalid_arguments"


def test_read_media_feeds_no_longer_reads_youtube_pages() -> None:
    """Spec 2026-10-13 §2: the legacy tool's watch-page scrape is retired; it refuses instead."""
    runtime, clients, writer, transport = _runtime()

    refused = _call(
        runtime,
        "read_media_feeds",
        person_name="Nick Fisher",
        youtube_url="https://www.youtube.com/watch?v=abcdefghijk",
    )

    assert refused["code"] == "youtube_read_retired"
    assert clients.media_client.short_calls == []
    assert writer.drafts == []


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


def test_finalize_stamps_the_synthesis_stage_before_writing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Spec 2026-09-12 §1: the agent's last act is the synthesis of its findings, and the job row
    says so *before* the finalization's claims land."""
    stamped: list[tuple[UUID, str, int]] = []
    runtime, _, writer, _ = _runtime()

    async def fake_set_job_stage(conn: Any, *, job_id: UUID, stage: str) -> None:
        del conn
        # The draft count at stamp time is what proves "before writing".
        stamped.append((job_id, stage, len(writer.drafts)))

    monkeypatch.setattr(tools, "set_job_stage", fake_set_job_stage)

    accepted = _call(runtime, "finalize_research", **_finalize_args())

    assert accepted["accepted"] is True
    assert stamped == [(runtime.scope.job_id, "synthesis", 0)]
    assert writer.drafts, "and the claims did land after it"


def test_the_stage_stamp_is_the_only_sql_a_finalize_issues_itself() -> None:
    """The recording double accepts any statement, so this is the guard that used to be implicit
    in a conn that accepted none: one finalize writes exactly one statement of its own, and it is
    the stage UPDATE. Everything else a tool body writes goes through the claim writer."""
    runtime, _, _, factory = _runtime()

    accepted = _call(runtime, "finalize_research", **_finalize_args())

    assert accepted["accepted"] is True
    assert len(factory.conn.statements) == 1
    statement, parameters = factory.conn.statements[0]
    assert "UPDATE arv2_research_job SET stage" in statement
    assert parameters == {"stage": "synthesis", "job_id": runtime.scope.job_id}


def test_a_failing_stage_stamp_never_costs_the_finalization() -> None:
    """A progress pixel is not worth a job: the stamp's failure is logged and swallowed, and the
    finalization lands exactly as it would have (I2)."""
    runtime, _, _, _ = _runtime(conn_factory=RaisingConnFactory())

    with structlog.testing.capture_logs() as events:
        accepted = _call(runtime, "finalize_research", **_finalize_args())

    assert accepted["accepted"] is True, "the finalization is unharmed"
    assert runtime.finalization is not None
    warned = [event for event in events if event["event"] == "arv2.stage_stamp_failed"]
    assert len(warned) == 1
    assert warned[0]["log_level"] == "warning"
    assert warned[0]["stage"] == "synthesis"
    assert warned[0]["job_id"] == str(runtime.scope.job_id)
    assert "connection pool exhausted" in warned[0]["error"]


def test_finalize_does_not_stamp_the_stage_when_it_refuses_a_second_finalization(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The refusal comes first: a job already finalized is not walked back to ``synthesis``."""
    stamped: list[tuple[UUID, str]] = []

    async def fake_set_job_stage(conn: Any, *, job_id: UUID, stage: str) -> None:
        del conn
        stamped.append((job_id, stage))

    monkeypatch.setattr(tools, "set_job_stage", fake_set_job_stage)
    runtime, _, _, _ = _runtime()
    _call(runtime, "finalize_research", **_finalize_args())

    refused = _call(runtime, "finalize_research", **_finalize_args())

    assert refused["code"] == "finalization_already_proposed"
    assert stamped == [(runtime.scope.job_id, "synthesis")], "the first call's stamp, and only it"


def test_finalize_admits_the_candidate_rationale_and_influence_and_writes_them() -> None:
    """``CommitteeCandidate`` forbids extra keys, so the two optional ones have to be declared for
    the agent to be able to send them at all — and the mapper carries them onto the claim the
    contact page's "why they matter" reads."""
    runtime, _, writer, _ = _runtime()
    args = _finalize_args()
    args["committee_candidates"] = [
        {
            **args["committee_candidates"][0],
            "rationale": "owns the ABM programme and the agency budget",
            "influence": "High",
        }
    ]

    accepted = _call(runtime, "finalize_research", **args)

    assert accepted["accepted"] is True
    [candidate] = [d for d in writer.drafts if d.field_key == "account.committee_candidate"]
    assert candidate.value_json["rationale"] == "owns the ABM programme and the agency budget"
    assert candidate.value_json["influence"] == "High"
    assert runtime.finalization is not None
    seated = runtime.finalization["committee_candidates"][0]
    assert seated["rationale"] and seated["influence"] == "High", (
        "the committee step reads the finalization, so the why must survive into it"
    )


def test_finalize_refuses_an_influence_that_is_not_one_of_the_three_bands() -> None:
    runtime, _, writer, _ = _runtime()
    args = _finalize_args()
    args["committee_candidates"] = [{**args["committee_candidates"][0], "influence": "quite a lot"}]

    refused = _call(runtime, "finalize_research", **args)

    assert refused["code"] == "invalid_arguments"
    assert writer.drafts == []


def test_a_candidate_with_no_rationale_is_unchanged_and_writes_neither_key() -> None:
    """The account agent's behaviour with the two keys absent is exactly what it was."""
    runtime, _, writer, _ = _runtime()

    _call(runtime, "finalize_research", **_finalize_args())

    [candidate] = [d for d in writer.drafts if d.field_key == "account.committee_candidate"]
    assert "rationale" not in candidate.value_json
    assert "influence" not in candidate.value_json


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


# ================================================================================================
# The person toolbelt
# ================================================================================================
#
# One job, one person. Every claim it writes lands on the contact entity, not on the account, and
# the five tools that differ from the account belt are the ones asserted here: ``lookup_person``
# (the employer lock and the email export), ``structure_material``'s person branch,
# ``unique_insight``, the per-person media cap, and the person finalization.


def _contact_claim(
    field_key: str,
    *,
    url: str | None = "https://nickfisher.dev/about",
    span: str | None = "I run ultramarathons at the weekend",
    markers: Mapping[str, Any] | None = None,
) -> Claim:
    return Claim(
        entity_id=CONTACT_ID,
        entity_type=EntityType.CONTACT,
        field_key=field_key,
        value_json=["ultramarathons"],
        source_tier=4,
        extraction_method=ExtractionMethod.LLM_SYNTHESIS,
        run_id=RunId(RUN_ID),
        research_mode=ResearchMode.CONTACT_PROFILING,
        confidence=0.6,
        reuse_scope=ReuseScope.TENANT_PRIVATE,
        workspace_id="ws-1",
        source_url=url,
        evidence_span=span,
        source_key="structuring",
        # The substrate requires both on a ``contact.facet.*`` claim, and the claim path stamps
        # them for every contact claim (Task 3) — so a hand-built one carries them too.
        identity_binding=IdentityBinding.STRONG,
        use_class=UseClass.PROFESSIONAL_PUBLIC,
        write_markers=dict(markers) if markers else None,
    )


PERSON_SOURCES = [
    {
        "url": "https://nickfisher.dev/about",
        "kind": "page",
        "text": "I run ultramarathons at the weekend, and I wrote The Pipeline Book. " * 3,
    }
]


# -- the shape of the toolbelt --------------------------------------------------------------------


def test_the_eleven_person_tools_are_built_in_the_manual_order_with_descriptions() -> None:
    runtime, _, _, _ = _runtime(PERSON_SCOPE)

    built = build_person_tools(runtime)

    assert tuple(tool.name for tool in built) == PERSON_TOOL_NAMES
    assert all(tool.description for tool in built)
    assert len(PERSON_TOOL_NAMES) == 11
    # The four account-only tools the manual says are deliberately absent.
    assert not {
        "read_account_state",
        "read_ats_board",
        "lookup_company",
        "lookup_people",
    } & set(PERSON_TOOL_NAMES)


# -- read_person_state ----------------------------------------------------------------------------


def test_read_person_state_reports_the_person_claims_the_open_fields_and_the_lock(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runtime, _, _, _ = _runtime(PERSON_SCOPE)
    _stub_claims(monkeypatch, [_contact_claim("contact.facet.hobby")])

    state = _call(runtime, "read_person_state")

    assert [claim["field_key"] for claim in state["claims"]] == ["contact.facet.hobby"]
    assert "contact.facet.hooks" in state["open_fields"]
    assert "contact.facet.hobby" not in state["open_fields"]
    assert state["account"]["domain"] == "probook.ai"
    assert state["icp"].startswith("# icp")
    assert state["lock"]["person_name"] == "Nick Fisher"
    assert state["lock"]["employment_history"] == ["VP Product Marketing @ Sysdig (2021–2024)"]


def test_read_person_state_serves_the_lock_section_on_its_own(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runtime, _, _, _ = _runtime(PERSON_SCOPE)
    _stub_claims(monkeypatch, [])

    state = _call(runtime, "read_person_state", section="lock")

    assert set(state) == {"lock"}
    assert state["lock"]["person_title"] == "VP of Marketing"
    assert state["lock"]["person_linkedin_url"] == "https://www.linkedin.com/in/nicholastfisher"


def test_a_person_job_has_no_read_account_state() -> None:
    runtime, _, _, _ = _runtime(PERSON_SCOPE)
    assert "read_account_state" not in _tools(runtime)


# -- lookup_person --------------------------------------------------------------------------------


def _lock_record() -> AiArkPerson:
    return _ark_person(linkedin_url="https://www.linkedin.com/in/nicholastfisher")


def test_lookup_person_refuses_a_url_the_committee_step_did_not_confirm() -> None:
    """The lock is the JOB's URL, not the model's argument.

    A same-name colleague at the same company clears both provider-side locks — the record carries
    the URL the call asked for, and the employer is this account — so the only thing that keeps
    the research on the confirmed person is comparing the argument to the confirmed URL first. The
    check is before the provider hop, so a mismatched call costs nothing.
    """
    runtime, clients, writer, _ = _runtime(PERSON_SCOPE)
    clients.ai_ark_client.people = (_lock_record(),)

    refused = _call(
        runtime, "lookup_person", linkedin_url="https://www.linkedin.com/in/nick-fisher-2"
    )

    assert refused["code"] == "subject_lock_failed"
    assert "nicholastfisher" in refused["detail"] and "nick-fisher-2" in refused["detail"]
    assert clients.ai_ark_client.people_calls == [], "nothing is bought for the wrong person"
    assert clients.ai_ark_client.export_calls == []
    assert writer.drafts == []


def test_lookup_person_refuses_a_job_that_carries_no_confirmed_linkedin_url() -> None:
    """No confirmed URL is no anchor, so the lookup is refused rather than run unlocked.

    A member confirmed on a team page that linked nothing has nothing for lock 1 to compare, and
    the two provider-side locks do not stand on their own: lock 2 matches whatever candidate
    carries the URL the *model* typed, and lock 3 passes for every colleague at this account. The
    refusal is before the hop, so it costs nothing, and it names the skip the dossier asks for.
    """
    runtime, clients, writer, _ = _runtime(replace(PERSON_SCOPE, person_linkedin_url=""))
    clients.ai_ark_client.people = (_lock_record(),)

    refused = _call(
        runtime, "lookup_person", linkedin_url="https://www.linkedin.com/in/nicholastfisher"
    )

    assert refused["code"] == "subject_lock_failed"
    assert "no confirmed LinkedIn URL for Nick Fisher" in refused["detail"]
    assert "not_found" in refused["detail"]
    assert clients.ai_ark_client.people_calls == [], "no provider record is bought unlocked"
    assert clients.ai_ark_client.export_calls == []
    assert writer.drafts == []


def test_lookup_person_reports_no_compliance_rows_when_the_floor_did_nothing() -> None:
    runtime, clients, _, _ = _runtime(PERSON_SCOPE)
    clients.ai_ark_client.people = (_lock_record(),)

    found = _call(
        runtime, "lookup_person", linkedin_url="https://www.linkedin.com/in/nicholastfisher"
    )

    assert found["compliance"] == [], (
        "a provider record carries no page quote by design and rule 6 exempts it"
    )


def test_lookup_person_refuses_subject_lock_failed_naming_the_candidate_companies() -> None:
    runtime, clients, writer, _ = _runtime(PERSON_SCOPE)
    clients.ai_ark_client.people = (
        _ark_person(
            linkedin_url="https://www.linkedin.com/in/nick-fisher-plumbing",
            current_company="Fisher Plumbing",
            current_company_domain="fisherplumbing.co.uk",
        ),
    )

    refused = _call(
        runtime, "lookup_person", linkedin_url="https://www.linkedin.com/in/nicholastfisher"
    )

    assert refused["code"] == "subject_lock_failed"
    assert "Fisher Plumbing" in refused["detail"]
    assert clients.ai_ark_client.export_calls == [], "no export is bought for the wrong person"
    assert writer.drafts == []


def test_lookup_person_refuses_subject_lock_failed_when_the_employer_is_not_the_account() -> None:
    """The record is the right LinkedIn URL, but the provider says they have moved on."""
    runtime, clients, writer, _ = _runtime(PERSON_SCOPE)
    clients.ai_ark_client.people = (
        _ark_person(
            linkedin_url="https://www.linkedin.com/in/nicholastfisher",
            current_company="Sysdig",
            current_company_domain="sysdig.com",
        ),
    )

    refused = _call(
        runtime, "lookup_person", linkedin_url="https://www.linkedin.com/in/nicholastfisher"
    )

    assert refused["code"] == "subject_lock_failed"
    assert "sysdig.com" in refused["detail"] and "probook.ai" in refused["detail"]
    assert clients.ai_ark_client.export_calls == []
    assert writer.drafts == []


def test_lookup_person_marks_nothing_when_the_employer_is_the_account() -> None:
    runtime, clients, writer, _ = _runtime(PERSON_SCOPE)
    clients.ai_ark_client.people = (_lock_record(),)

    found = _call(
        runtime, "lookup_person", linkedin_url="https://www.linkedin.com/in/nicholastfisher"
    )

    assert found["employer_verified"] is True
    assert all("employer_unverified" not in draft.markers for draft in writer.drafts)


# -- structure_material, the person branch ---------------------------------------------------------


def test_structure_material_on_a_person_job_writes_contact_scoped_drafts() -> None:
    runtime, clients, writer, _ = _runtime(PERSON_SCOPE)

    structured = _call(
        runtime,
        "structure_material",
        subject_kind="person",
        subject_name="Nick Fisher",
        subject_domain_or_company="Probook",
        linkedin_url="https://www.linkedin.com/in/nicholastfisher",
        sources=PERSON_SOURCES,
        notes="my own read: he is a runner",
    )

    assert [row["field_key"] for row in structured["written"]] == ["contact.facet.hobby"]
    assert clients.structuring_client.account_calls == [], (
        "a person job never structures an account"
    )
    [call] = clients.structuring_client.person_calls
    assert call["subject"].name == "Nick Fisher"
    assert call["subject"].company == "Probook", "the account name, from the scope"
    assert call["subject"].linkedin_url == "https://www.linkedin.com/in/nicholastfisher"
    assert call["notes"] == "my own read: he is a runner"
    hobby = writer.drafts[0]
    assert hobby.entity_id == CONTACT_ID and hobby.entity_type is EntityType.CONTACT
    assert hobby.use_class is not None and hobby.identity_binding is not None


def test_structure_material_reports_what_the_compliance_floor_removed() -> None:
    """The floor sits between the structuring pass and the store, so a claim it drops leaves an
    empty ``written`` that reads exactly like "the pass found nothing". The rows say which."""
    runtime, clients, writer, _ = _runtime(PERSON_SCOPE)
    clients.structuring_client.person_output = replace(
        clients.structuring_client.person_output,
        claims=(
            _structured(
                "contact.facet.hobby",
                ["ultramarathons"],
                span="He was diagnosed with cancer in 2019. I run ultramarathons at the weekend",
                url="https://nickfisher.dev/about",
            ),
        ),
    )

    structured = _call(
        runtime,
        "structure_material",
        subject_kind="person",
        subject_name="Nick Fisher",
        subject_domain_or_company="Probook",
        sources=PERSON_SOURCES,
    )

    assert [(row["action"], row["rule"]) for row in structured["compliance"]] == [
        ("redacted", "health")
    ]
    assert "diagnosed" not in writer.drafts[0].evidence_span


def test_structure_material_on_an_account_job_reports_no_compliance_rows() -> None:
    """The floor is about a person; an account job's claims never meet it, so the key is empty
    rather than absent — one shape for both subjects."""
    runtime, _, _, _ = _runtime()

    structured = _call(
        runtime,
        "structure_material",
        subject_kind="account",
        subject_name="Probook",
        subject_domain_or_company="probook.ai",
        sources=SOURCES,
    )

    assert structured["compliance"] == []


def test_structure_material_on_a_person_job_takes_the_intent_sweep_mode_too() -> None:
    runtime, clients, _, _ = _runtime(PERSON_SCOPE)

    _call(
        runtime,
        "structure_material",
        subject_kind="person",
        subject_name="Nick Fisher",
        subject_domain_or_company="Probook",
        sources=PERSON_SOURCES,
        mode="intent_sweep",
    )

    assert clients.structuring_client.person_calls[0]["mode"] == "intent_sweep"


def test_structure_material_refuses_an_account_subject_on_a_person_job() -> None:
    runtime, clients, writer, _ = _runtime(PERSON_SCOPE)

    refused = _call(
        runtime,
        "structure_material",
        subject_kind="account",
        subject_name="Probook",
        subject_domain_or_company="probook.ai",
        sources=PERSON_SOURCES,
    )

    assert refused["code"] == "invalid_arguments"
    assert "a person job structures its person" in refused["detail"]
    assert clients.structuring_client.person_calls == [] and writer.drafts == []


def test_structure_material_keeps_the_sources_for_the_unique_insight_pass() -> None:
    runtime, _, _, _ = _runtime(PERSON_SCOPE)

    _call(
        runtime,
        "structure_material",
        subject_kind="person",
        subject_name="Nick Fisher",
        subject_domain_or_company="Probook",
        sources=PERSON_SOURCES,
    )

    assert [block.url for block in runtime.person_sources] == ["https://nickfisher.dev/about"]


# -- unique_insight -------------------------------------------------------------------------------


def _structure_once(runtime: ToolRuntime) -> None:
    _call(
        runtime,
        "structure_material",
        subject_kind="person",
        subject_name="Nick Fisher",
        subject_domain_or_company="Probook",
        sources=PERSON_SOURCES,
    )


def test_unique_insight_writes_one_priority_one_claim_carrying_the_marker() -> None:
    runtime, clients, writer, _ = _runtime(PERSON_SCOPE)
    _structure_once(runtime)

    found = _call(runtime, "unique_insight", subject="Nick Fisher")

    insight = clients.structuring_client.person_calls[-1]
    assert insight["mode"] == "unique_insight"
    assert [block.url for block in insight["sources"]] == ["https://nickfisher.dev/about"], (
        "the one-question pass reads the material the job has already structured"
    )
    written = [draft for draft in writer.drafts if draft.field_key == "contact.facet.publications"]
    assert len(written) == 1
    assert written[0].signal_priority == 1, "the fact the outreach opens with"
    assert written[0].markers["unique_insight"] is True
    assert written[0].entity_id == CONTACT_ID
    assert found["written"][0]["field_key"] == "contact.facet.publications"


def test_unique_insight_drops_a_row_written_to_an_outreach_field_and_names_the_key() -> None:
    """``contact.facet.hooks`` is the argument the finalization builds from facts, not a fact.

    The live run answered there, so the insight landed as an unquoted line in the field the openers
    are drawn from. The row is dropped, and the result names the key — otherwise a dropped row and
    a thin public footprint are the same empty ``written``.
    """
    runtime, clients, writer, _ = _runtime(PERSON_SCOPE)
    _structure_once(runtime)
    clients.structuring_client.insight_output = replace(
        clients.structuring_client.insight_output,
        claims=(
            _structured(
                "contact.facet.hooks",
                ["he cares about pipeline hygiene"],
                span="I wrote The Pipeline Book",
                url="https://nickfisher.dev/book",
            ),
        ),
    )
    before = {draft.field_key for draft in writer.drafts}

    found = _call(runtime, "unique_insight", subject="Nick Fisher")

    assert found["written"] == []
    assert found["dropped_off_target"] == ["contact.facet.hooks"]
    assert found["dropped_rows"] == 1
    assert {draft.field_key for draft in writer.drafts} == before, "nothing reached the store"


def test_unique_insight_writes_a_fact_facet_at_priority_one_with_the_marker() -> None:
    runtime, clients, writer, _ = _runtime(PERSON_SCOPE)
    _structure_once(runtime)
    clients.structuring_client.insight_output = replace(
        clients.structuring_client.insight_output,
        claims=(
            _structured(
                "contact.facet.hobby",
                ["ultramarathons"],
                priority=3,
                span="I run ultramarathons at the weekend",
                url="https://nickfisher.dev/about",
            ),
        ),
    )

    found = _call(runtime, "unique_insight", subject="Nick Fisher")

    written = [
        draft
        for draft in writer.drafts
        if draft.field_key == "contact.facet.hobby" and draft.markers.get("unique_insight")
    ]
    assert len(written) == 1
    assert written[0].signal_priority == 1
    assert found["dropped_off_target"] == []


def test_unique_insight_says_when_the_floor_took_the_one_claim_it_found() -> None:
    """The insight is at most one claim: without the rows, "the floor removed it" and "there was
    nothing distinctive" are the same empty answer, and the agent would record the wrong finding."""
    runtime, clients, writer, _ = _runtime(PERSON_SCOPE)
    _structure_once(runtime)
    clients.structuring_client.insight_output = replace(
        clients.structuring_client.insight_output,
        claims=(
            _structured(
                "contact.facet.publications",
                [{"title": "The Pipeline Book"}],
                span="Call the author on +1 (415) 555-0132 for a copy",
                url="https://nickfisher.dev/book",
            ),
        ),
    )
    before = len(writer.drafts)

    found = _call(runtime, "unique_insight", subject="Nick Fisher")

    assert found["written"] == []
    assert [(row["action"], row["rule"]) for row in found["compliance"]] == [
        ("dropped", "personal_contact_detail")
    ]
    assert len(writer.drafts) == before, "the dropped draft never reached the store"


def test_unique_insight_refuses_insight_not_found_naming_the_channels_checked() -> None:
    runtime, clients, writer, _ = _runtime(PERSON_SCOPE)
    _structure_once(runtime)
    clients.structuring_client.insight_output = replace(
        clients.structuring_client.insight_output, claims=()
    )
    before = len(writer.drafts)

    refused = _call(runtime, "unique_insight", subject="Nick Fisher")

    assert refused["code"] == "insight_not_found"
    assert "page" in refused["detail"], "the source kinds seen are the channels checked"
    assert refused["reaction"].startswith('Record "thin public footprint"')
    assert len(writer.drafts) == before, "an empty answer writes nothing"


def test_unique_insight_before_any_material_is_structured_is_refused_invalid_arguments() -> None:
    runtime, clients, _, _ = _runtime(PERSON_SCOPE)

    refused = _call(runtime, "unique_insight", subject="Nick Fisher")

    assert refused["code"] == "invalid_arguments"
    assert "structure_material" in refused["detail"]
    assert clients.structuring_client.person_calls == [], "no material, no call, no spend"


def test_unique_insight_keeps_at_most_one_row_whatever_the_reply_holds() -> None:
    runtime, clients, writer, _ = _runtime(PERSON_SCOPE)
    _structure_once(runtime)
    clients.structuring_client.insight_output = replace(
        clients.structuring_client.insight_output,
        claims=(
            *clients.structuring_client.insight_output.claims,
            _structured(
                "contact.facet.hobby",
                ["sourdough"],
                span="I bake sourdough",
                url="https://nickfisher.dev/about",
            ),
        ),
    )

    _call(runtime, "unique_insight", subject="Nick Fisher")

    insight_drafts = [draft for draft in writer.drafts if draft.markers.get("unique_insight")]
    assert [draft.field_key for draft in insight_drafts] == ["contact.facet.publications"]


# -- read_media_feeds, the per-person cap ----------------------------------------------------------


def test_read_media_feeds_writes_the_appearance_on_the_contact_for_a_person_job(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    runtime, _, writer, _ = _runtime(PERSON_SCOPE)
    _stub_claims(monkeypatch, [])
    _stub_podcast(monkeypatch, tmp_path)

    found = _call(
        runtime,
        "read_media_feeds",
        person_name="Nick Fisher",
        person_role="VP of Marketing",
        feed_url="https://pod.test/feed",
        episode_number=42,
    )

    assert found["speaker_verified"] is True
    assert [draft.field_key for draft in writer.drafts] == ["contact.facet.public_appearances"]
    appearance = writer.drafts[0]
    assert appearance.entity_id == CONTACT_ID
    assert appearance.value_json == [
        {"title": "Nick Fisher on ABM", "url": "https://media.test/42.mp3"}
    ]
    assert appearance.markers["speaker_verified"] is True
    assert appearance.markers["media_kind"] == "podcast"


def test_read_media_feeds_refuses_media_cap_reached_at_the_configured_number(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    runtime, _, writer, _ = _runtime(PERSON_SCOPE, settings=Settings(arv2_person_media_max_items=2))
    _stub_claims(
        monkeypatch,
        [
            _contact_claim("contact.facet.public_appearances"),
            _contact_claim("contact.facet.public_appearances"),
        ],
    )
    _stub_podcast(monkeypatch, tmp_path)

    refused = _call(
        runtime,
        "read_media_feeds",
        person_name="Nick Fisher",
        feed_url="https://pod.test/feed",
        episode_number=42,
    )

    assert refused["code"] == "media_cap_reached"
    assert "2" in refused["detail"]
    assert writer.drafts == []


def test_a_person_media_cap_of_zero_refuses_before_any_provider_is_touched(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runtime, clients, writer, _ = _runtime(
        PERSON_SCOPE, settings=Settings(arv2_person_media_max_items=0)
    )
    _stub_claims(monkeypatch, [])

    refused = _call(
        runtime,
        "read_media_feeds",
        person_name="Nick Fisher",
        feed_url="https://pod.test/feed",
        episode_number=42,
    )

    assert refused["code"] == "media_cap_reached"
    assert writer.drafts == [] and clients.callers == []


def test_the_account_media_index_claim_is_untouched_by_the_person_cap(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """An account job counts nothing and still writes ``account.media_layer_index``."""
    runtime, _, writer, _ = _runtime(settings=Settings(arv2_person_media_max_items=0))
    _stub_podcast(monkeypatch, tmp_path)

    _call(
        runtime,
        "read_media_feeds",
        person_name="Nick Fisher",
        feed_url="https://pod.test/feed",
        episode_number=42,
    )

    assert [draft.field_key for draft in writer.drafts] == ["account.media_layer_index"]


# -- research_deep, the person lock ----------------------------------------------------------------


def test_research_deep_on_a_person_job_locks_the_system_prompt_to_the_person() -> None:
    runtime, clients, _, _ = _runtime(PERSON_SCOPE)

    _call(
        runtime,
        "research_deep",
        charter=CHARTER,
        same_name_exclusions=["Nick Fisher the plumber"],
    )

    system_prompt = clients.exa_client.deep_calls[-1]["system_prompt"]
    assert "You research exactly ONE person" in system_prompt
    assert "Nick Fisher" in system_prompt and "VP of Marketing" in system_prompt
    assert "https://www.linkedin.com/in/nicholastfisher" in system_prompt
    assert "VP Product Marketing @ Sysdig (2021–2024)" in system_prompt
    assert "Nick Fisher the plumber" in system_prompt
    assert "EVIDENCE LAW" in system_prompt
    assert "Founded 2021." in clients.exa_client.deep_calls[-1]["query"]


# -- finalize_research, the person receipt ---------------------------------------------------------


def _person_finalize_args(**overrides: Any) -> dict[str, Any]:
    return {
        "summary": "Nick Fisher runs marketing at Probook and writes about pipeline.",
        "openers": [
            {
                "text": "Saw you wrote The Pipeline Book.",
                "hook": "his own book",
                "quote": "I wrote The Pipeline Book",
                "url": "https://nickfisher.dev/book",
            },
            {
                "text": "Your ultramarathon posts are something else.",
                "hook": "ultramarathons",
                "quote": "I run ultramarathons at the weekend",
                "url": "https://nickfisher.dev/about",
            },
            {
                "text": "You must be busy with the new team.",
                "hook": "hiring",
                "quote": "",
                "url": None,
            },
        ],
        "hooks": ["his own book", "ultramarathons"],
        "not_found": ["alma mater (checked alumni pages and LinkedIn)"],
        "same_name_log": [
            {
                "name_or_url": "https://www.linkedin.com/in/nick-fisher-plumbing",
                "why_excluded": "a plumber in Leeds; no Probook role in his history",
            }
        ],
        "gaps": ["no podcast appearance found"],
        **overrides,
    }


def test_person_finalize_stamps_the_synthesis_stage_before_writing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The person tool stamps the same stage as the account one — a person job's last act is its
    synthesis too, and the progress card reads one column for both subjects."""
    stamped: list[tuple[UUID, str]] = []

    async def fake_set_job_stage(conn: Any, *, job_id: UUID, stage: str) -> None:
        del conn
        stamped.append((job_id, stage))

    monkeypatch.setattr(tools, "set_job_stage", fake_set_job_stage)
    runtime, _, _, _ = _runtime(PERSON_SCOPE)
    _stub_claims(monkeypatch, [])

    accepted = _call(runtime, "finalize_research", **_person_finalize_args())

    assert accepted["accepted"] is True
    assert stamped == [(runtime.scope.job_id, "synthesis")]


def test_person_finalize_writes_the_openers_hooks_and_lookalikes_and_drops_the_quoteless_opener(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runtime, _, writer, _ = _runtime(PERSON_SCOPE)
    _stub_claims(monkeypatch, [])

    accepted = _call(runtime, "finalize_research", **_person_finalize_args())

    assert accepted["accepted"] is True
    openers = [d for d in writer.drafts if d.field_key == "contact.facet.openers"]
    assert [d.value_json for d in openers] == [
        ["Saw you wrote The Pipeline Book."],
        ["Your ultramarathon posts are something else."],
    ], "one claim per opener, so each carries its own quote and URL"
    assert openers[0].evidence_span == "I wrote The Pipeline Book"
    assert openers[0].source_url == "https://nickfisher.dev/book"
    assert accepted["openers_written"] == 2
    assert accepted["openers_dropped"] == ["You must be busy with the new team."]

    hooks = [d for d in writer.drafts if d.field_key == "contact.facet.hooks"]
    assert [d.value_json for d in hooks] == [["his own book", "ultramarathons"]]

    lookalikes = [d for d in writer.drafts if d.field_key == "contact.facet.excluded_lookalike"]
    assert [d.value_json for d in lookalikes] == [
        {
            "title": "https://www.linkedin.com/in/nick-fisher-plumbing",
            "reason": "a plumber in Leeds; no Probook role in his history",
        }
    ]
    assert all(d.entity_id == CONTACT_ID for d in writer.drafts)

    receipt = runtime.finalization
    assert receipt is not None
    assert receipt["summary"].startswith("Nick Fisher runs marketing")
    assert receipt["hooks_written"] == 1
    assert receipt["not_found"] == ["alma mater (checked alumni pages and LinkedIn)"]
    assert receipt["gaps"] == ["no podcast appearance found"]
    assert receipt["insight_found"] is False
    assert receipt["reports_to_written"] is False


def test_a_person_finalization_has_no_fit_verdicts_and_no_committee_candidates() -> None:
    """Constitution rule 11: those belong to the account job, not to this one."""
    runtime, _, writer, _ = _runtime(PERSON_SCOPE)

    refused = _call(
        runtime,
        "finalize_research",
        **_person_finalize_args(
            fit_verdicts=[{"gate": "stage", "verdict": "pass", "rationale": "Series A"}]
        ),
    )

    assert refused["code"] == "invalid_arguments"
    assert writer.drafts == [] and runtime.finalization is None


def test_person_finalize_records_the_unique_insight_it_found(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runtime, _, _, _ = _runtime(PERSON_SCOPE)
    _stub_claims(
        monkeypatch,
        [_contact_claim("contact.facet.publications", markers={"unique_insight": True})],
    )

    accepted = _call(runtime, "finalize_research", **_person_finalize_args())

    assert accepted["insight_found"] is True
    assert runtime.finalization is not None and runtime.finalization["insight_found"] is True


def test_person_finalize_writes_reports_to_when_it_carries_a_quote_and_a_url(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runtime, _, writer, _ = _runtime(PERSON_SCOPE)
    _stub_claims(monkeypatch, [])
    manager = str(uuid4())

    accepted = _call(
        runtime,
        "finalize_research",
        **_person_finalize_args(
            reports_to={
                "name": "Dana Reyes",
                "contact_id": manager,
                "quote": "I report to Dana Reyes, our CMO",
                "url": "https://podcast.test/42",
            }
        ),
    )

    assert accepted["reports_to_written"] is True
    (claim,) = [d for d in writer.drafts if d.field_key == "contact.reports_to"]
    assert claim.value_json == {"name": "Dana Reyes", "contact_id": manager}
    assert claim.evidence_span == "I report to Dana Reyes, our CMO"
    assert claim.source_url == "https://podcast.test/42"


def test_person_finalize_skips_reports_to_with_no_quote_and_says_why(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runtime, _, writer, _ = _runtime(PERSON_SCOPE)
    _stub_claims(monkeypatch, [])

    accepted = _call(
        runtime,
        "finalize_research",
        **_person_finalize_args(
            reports_to={"name": "Dana Reyes", "contact_id": str(uuid4()), "url": "https://x.test"}
        ),
    )

    assert accepted["reports_to_written"] is False
    assert "quote" in accepted["reports_to_skipped"]
    assert [d for d in writer.drafts if d.field_key == "contact.reports_to"] == []


def test_person_finalize_resolves_the_reports_to_contact_by_name(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """``contact_id`` is the field's required key, so a name the store can resolve is resolved."""
    runtime, _, writer, _ = _runtime(PERSON_SCOPE)
    _stub_claims(monkeypatch, [])
    manager = uuid4()

    async def _find(conn: Any, **kwargs: Any) -> Any:
        assert kwargs["name"] == "Dana Reyes"
        assert kwargs["account_id"] == ACCOUNT_ID and kwargs["workspace_id"] == "ws-1"
        return manager

    monkeypatch.setattr(tools, "find_contact_by_name", _find)

    accepted = _call(
        runtime,
        "finalize_research",
        **_person_finalize_args(
            reports_to={
                "name": "Dana Reyes",
                "quote": "I report to Dana Reyes",
                "url": "https://podcast.test/42",
            }
        ),
    )

    assert accepted["reports_to_written"] is True
    (claim,) = [d for d in writer.drafts if d.field_key == "contact.reports_to"]
    assert claim.value_json == {"name": "Dana Reyes", "contact_id": str(manager)}


def test_person_finalize_skips_reports_to_when_no_contact_resolves(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runtime, _, writer, _ = _runtime(PERSON_SCOPE)
    _stub_claims(monkeypatch, [])

    async def _find(conn: Any, **kwargs: Any) -> Any:
        return None

    monkeypatch.setattr(tools, "find_contact_by_name", _find)

    accepted = _call(
        runtime,
        "finalize_research",
        **_person_finalize_args(
            reports_to={
                "name": "Dana Reyes",
                "quote": "I report to Dana Reyes",
                "url": "https://podcast.test/42",
            }
        ),
    )

    assert accepted["reports_to_written"] is False
    assert "Dana Reyes" in accepted["reports_to_skipped"]
    assert [d for d in writer.drafts if d.field_key == "contact.reports_to"] == []


def test_a_person_job_finalizes_only_once_and_closes_the_other_tools(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runtime, _, _, _ = _runtime(PERSON_SCOPE)
    _stub_claims(monkeypatch, [])
    _call(runtime, "finalize_research", **_person_finalize_args())

    assert (
        _call(runtime, "finalize_research", **_person_finalize_args())["code"]
        == "finalization_already_proposed"
    )
    assert (
        _call(runtime, "unique_insight", subject="Nick Fisher")["code"]
        == "finalization_already_proposed"
    )


# -- the coded compliance pass (Task 5) ------------------------------------------------------


def _person_draft(**overrides: Any) -> ClaimDraft:
    base: dict[str, Any] = {
        "entity_id": CONTACT_ID,
        "entity_type": EntityType.CONTACT,
        "field_key": "contact.facet.hobby",
        "value_json": "He runs ultras. He coaches his daughter's team on Sundays.",
        "extraction_method": ExtractionMethod.LLM_SYNTHESIS,
        "run_id": RunId(RUN_ID),
        "research_mode": ResearchMode.CONTACT_PROFILING,
        "workspace_id": "ws-1",
        "source_url": "https://nickfisher.dev/about",
        "evidence_span": "I run ultras.",
    }
    base.update(overrides)
    return ClaimDraft(**base)


def test_a_person_job_runs_the_floor_on_every_write_and_the_log_reaches_the_receipt(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The pass sits at the write path, so no tool can reach the store around it."""
    runtime, _, writer, _ = _runtime(PERSON_SCOPE)
    _stub_claims(monkeypatch, [])

    _run(runtime.write_each([_person_draft()]))

    [written] = writer.drafts
    assert written.value_json == "He runs ultras.", "the sentence about a child is gone"
    assert written.markers["redacted"] == "minors"
    assert runtime.compliance_log[0] == {
        "action": "redacted",
        "field_key": "contact.facet.hobby",
        "rule": "minors",
        "detail": "the matching sentence was removed",
    }

    accepted = _call(runtime, "finalize_research", **_person_finalize_args())

    assert accepted["compliance_log"] == runtime.compliance_log
    assert accepted["compliance_log"][0]["rule"] == "minors"
    assert runtime.finalization is not None
    assert runtime.finalization["compliance_log"][0]["rule"] == "minors"


def test_the_one_transaction_write_path_runs_the_floor_too() -> None:
    runtime, _, writer, _ = _runtime(PERSON_SCOPE)

    _run(runtime.write([_person_draft(value_json="Reach him on +1 (415) 555-0132.")]))

    assert writer.drafts == [], "a personal contact detail never reaches the gate"
    assert [row["rule"] for row in runtime.compliance_log] == ["personal_contact_detail"]


def test_write_each_pairs_its_results_with_the_drafts_the_floor_left() -> None:
    """The batch out is not the batch in, so the caller is handed the draft each result is about."""
    runtime, _, writer, _ = _runtime(PERSON_SCOPE)

    results = _run(
        runtime.write_each(
            [
                _person_draft(value_json="Reach him on +1 (415) 555-0132."),
                _person_draft(field_key="contact.headline", value_json="VP Marketing at Probook."),
            ]
        )
    )

    assert [draft.field_key for draft, _ in results] == ["contact.headline"]
    assert [draft.field_key for draft in writer.drafts] == ["contact.headline"]
    assert [row["rule"] for row in runtime.compliance_log] == ["personal_contact_detail"]


def test_an_account_job_never_runs_the_compliance_pass() -> None:
    """The floor is about a person; an account claim has no subject it could be personal about."""
    runtime, _, writer, _ = _runtime()

    _run(
        runtime.write_each(
            [
                _person_draft(
                    entity_id=ACCOUNT_ID,
                    entity_type=EntityType.ACCOUNT,
                    field_key="account.gtm_tooling_stack",
                    value_json="Support answers on +1 (415) 555-0132. Their kids use it too.",
                )
            ]
        )
    )

    assert [draft.value_json for draft in writer.drafts] == [
        "Support answers on +1 (415) 555-0132. Their kids use it too."
    ]
    assert runtime.compliance_log == []


# -- the refusal-code guard ------------------------------------------------------------------


def test_a_person_tool_emitting_a_code_outside_the_person_set_is_a_tool_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A code the person manual carries no row for is a programming error, never a crash.

    The envelope's ``reaction`` is the manual's row; a code outside the person set would hand the
    model a reaction its own manual never states, so the assertion fires and the failure law turns
    it into a ``tool_error`` like any other unexpected exception.
    """
    runtime, _, _, _ = _runtime(PERSON_SCOPE)

    async def _boom(runtime: Any, args: Any) -> Mapping[str, Any]:
        raise tools.RefusalError("company_not_found", "a code no person manual row covers")

    monkeypatch.setattr(tools, "_fetch_page", _boom)

    refused = _call(runtime, "fetch_page", url="https://nickfisher.dev/about")

    assert refused["code"] == "tool_error:AssertionError"
    assert refused["recoverable"] is True


# -- the provider slot is freed when the provider answers (W1-7) ----------------------------------


class _Timeline:
    """Monotonic timestamps of each hop's dispatch and drain, shared with the provider thread."""

    def __init__(self) -> None:
        import threading
        import time

        self.lock, self.clock = threading.Lock(), time.monotonic
        self.events: list[tuple[str, int, float]] = []

    def mark(self, what: str, call: int) -> None:
        with self.lock:
            self.events.append((what, call, self.clock()))

    def at(self, what: str, call: int) -> float:
        return next(t for w, c, t in self.events if w == what and c == call)


def _timed_runtime(*, outside: bool, drain_s: float = 0.2, **settings: Any) -> Any:
    runtime, _, _, _ = _runtime(
        settings=Settings(
            _env_file=None,  # type: ignore[call-arg]
            arv2_drain_outside_slot=outside,
            **settings,
        )
    )
    timeline = _Timeline()
    drains: list[str | None] = []

    async def drain(raw: Any, ledger: Any, **kwargs: Any) -> None:
        call = len(drains)
        drains.append(kwargs.get("error"))
        await asyncio.sleep(drain_s)
        timeline.mark("drain_end", call)

    runtime._drain = drain
    return runtime, timeline, drains


def _provider_call(timeline: _Timeline, call: int, *, raise_error: bool = False) -> Any:
    import time

    def fn(caller: Any) -> str:
        timeline.mark("dispatch_start", call)
        time.sleep(0.01)
        timeline.mark("dispatch_end", call)
        if raise_error:
            raise RuntimeError("provider exploded")
        return f"result-{call}"

    return fn


@pytest.mark.parametrize("outside", [True, False])
def test_a_free_slot_is_handed_on_before_the_previous_result_is_indexed(outside: bool) -> None:
    runtime, timeline, drains = _timed_runtime(outside=outside, arv2_account_provider_concurrency=2)

    async def five() -> list[Any]:
        return await asyncio.gather(
            *(runtime.call_provider("exa", _provider_call(timeline, i)) for i in range(5))
        )

    assert _run(five()) == [f"result-{i}" for i in range(5)]
    assert len(drains) == 5  # every call is indexed exactly once
    first_indexed = min(timeline.at("drain_end", i) for i in range(5))
    third_started = sorted(t for w, _, t in timeline.events if w == "dispatch_start")[2]
    if outside:
        assert third_started < first_indexed
    else:  # the old order: both slots are held through indexing
        assert third_started >= first_indexed


@pytest.mark.parametrize("outside", [True, False])
def test_a_failed_call_is_still_indexed_and_its_error_still_raised(outside: bool) -> None:
    runtime, timeline, drains = _timed_runtime(outside=outside, drain_s=0.01)

    with pytest.raises(RuntimeError, match="provider exploded"):
        _run(runtime.call_provider("exa", _provider_call(timeline, 0, raise_error=True)))
    assert drains == ["RuntimeError"]
    # The slot was given back: the next call goes through.
    assert _run(runtime.call_provider("exa", _provider_call(timeline, 1))) == "result-1"


class _AdvisoryConnFactory:
    """One process-wide advisory lock, as ``pg_try_advisory_xact_lock`` behaves across jobs."""

    def __init__(self) -> None:
        self.holder: object | None = None

    def __call__(self) -> Any:
        return self._open()

    @asynccontextmanager
    async def _open(self) -> AsyncIterator[Any]:
        factory, me = self, object()

        class Conn:
            async def execute(self, statement: Any, parameters: Any = None) -> Any:
                won = factory.holder is None
                if won:
                    factory.holder = me

                class Result:
                    def scalar_one(self) -> bool:
                        return won

                return Result()

        try:
            yield Conn()
        finally:
            if self.holder is me:
                self.holder = None


@pytest.mark.parametrize("outside", [True, False])
def test_ai_ark_pacing_gap_runs_from_the_answer_and_indexing_overlaps_it(outside: bool) -> None:
    # The gap outlasts the indexing, as in production (10.5 s vs ~1 s), and the two are far apart,
    # so a loaded test machine cannot blur the two orders. While the gap runs the pacing lock is
    # held, so the next call starts at max(gap, indexing) from the answer (review M-1).
    gap, drain_s = 1.0, 0.5
    runtime, timeline, drains = _timed_runtime(
        outside=outside, drain_s=drain_s, arv2_ai_ark_min_gap_s=gap
    )
    runtime.clients.ai_ark_token_scope = "token-1"
    runtime._pacing_conn_factory = _AdvisoryConnFactory()

    async def two() -> list[Any]:
        return await asyncio.gather(
            *(runtime.call_provider("ai_ark", _provider_call(timeline, i)) for i in range(2))
        )

    assert sorted(_run(two())) == ["result-0", "result-1"]
    assert len(drains) == 2
    starts = sorted((t, c) for w, c, t in timeline.events if w == "dispatch_start")
    first, second = starts[0][1], starts[1][1]
    waited = timeline.at("dispatch_start", second) - timeline.at("dispatch_end", first)
    if outside:  # the gap starts at the answer; the indexing runs inside it (+ 0.1 s polling)
        assert gap <= waited < gap + drain_s - 0.1
    else:  # the old order: indexing, then the whole gap
        assert waited >= gap + drain_s


def test_ai_ark_subject_registration_skips_a_held_non_ai_ark_response_without_storage() -> None:
    """W2-16: an Exa response is not downloaded just to learn it is not AI Ark."""
    import clue_api.arv2.committee_discovery as discovery

    class NoStorage:
        async def get(self, key: str) -> bytes:
            raise AssertionError("storage was read")

    runtime, _, _, _ = _runtime()
    runtime.storage = NoStorage()  # type: ignore[assignment]
    body = json.dumps({"record": {"provider": "exa", "operation": "search"}}).encode()
    _run(
        discovery.index_provider_artifacts(
            runtime, MemoryConn(), ["ws-1/abc"], bodies={"ws-1/abc": body}
        )
    )


def test_early_uploads_are_limited_across_every_job_of_a_worker_process(monkeypatch) -> None:
    """W2-15 option B: the work done before the worker lock (store the response, check privacy,
    upload the source files) is bounded per process by one shared limit, so a burst of finished
    evidence calls cannot exhaust the process's connection pool or flood storage."""
    import clue_api.arv2.account_research_tools as tools_module
    from clue_api.arv2.provider_ledger import BufferedLedger, BufferedRawSink, HeldDrain
    from clue_spend.ledger import DrainReport

    running = peak = 0

    async def slow_hold(**_: Any) -> HeldDrain:
        nonlocal running, peak
        running += 1
        peak = max(peak, running)
        await asyncio.sleep(0.05)
        running -= 1
        return HeldDrain((), {}, {}, 0)

    async def drained(conn: Any, **_: Any) -> DrainReport:
        return DrainReport(
            rows=0, artifacts=0, cost_usd=Decimal(0), credits=Decimal(0), media_seconds=0
        )

    monkeypatch.setattr(tools_module, "hold_drain", slow_hold)
    monkeypatch.setattr(tools_module, "drain_provider_calls", drained)
    monkeypatch.setattr(tools_module, "has_capability", lambda *_: False)
    gate = asyncio.Semaphore(2)
    settings = Settings(_env_file=None, arv2_upload_outside_lock=True)  # type: ignore[call-arg]
    jobs = [_runtime(settings=settings, early_gate=gate)[0] for _ in range(3)]

    async def burst() -> None:
        await asyncio.gather(
            *(job._drain(BufferedRawSink(), BufferedLedger()) for job in jobs for _ in range(2))
        )

    _run(burst())
    assert peak == 2


def test_the_orphan_sweep_waits_far_longer_than_an_early_upload_waits_to_be_recorded() -> None:
    """Review M-3: with option B a source file exists without its artifact row while its call
    waits for the worker lock (seconds to minutes). The orphan sweep deletes row-less files only
    after its grace, so the grace must stay far longer than that wait."""
    from datetime import timedelta

    from clue_api.storage_wiring import DEFAULT_ORPHAN_SWEEP_GRACE

    assert timedelta(hours=24) <= DEFAULT_ORPHAN_SWEEP_GRACE
