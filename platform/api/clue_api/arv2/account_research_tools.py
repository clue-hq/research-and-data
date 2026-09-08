"""The twelve governed tools one account-research job runs on, and the runtime behind them.

Every tool is a LangChain :class:`~langchain_core.tools.StructuredTool` whose result is a **JSON
string**, and the two laws below are structural rather than remembered:

* **A tool never raises into the graph** (master plan Appendix A law 12). Every failure — a typed
  refusal, an argument the schema rejects, an exception nobody predicted — comes back as the
  refusal envelope from :mod:`clue_api.arv2.account_research_refusals`, which spends nothing,
  suspends nothing and ends nothing. The model reads the manual's reaction for that code inside the
  envelope. The wrapper is the only place a tool result is produced, so there is no path around it.
* **A provider is reached only through** :meth:`ToolRuntime.call_provider`. It holds the per-job
  halt latch, the per-provider semaphore, the fresh :class:`~clue_api.arv2.calls.ProviderCaller`
  with buffered sinks, and the drain that lands the raw bodies and ledger rows in the database
  right after the synchronous hop. A tool body that called a client directly would spend money the
  ledger never sees, so no tool body holds a client — it asks the runtime for the hop.

Claims are written only through :meth:`ToolRuntime.write`, which is the lenient claim gate: the
mappers in :mod:`clue_api.arv2.account_research_claims` decide what a record means, and this module
decides nothing about a value it is handed.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import re
from collections.abc import Awaitable, Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal, Protocol
from uuid import UUID

from langchain_core.messages import ToolMessage
from langchain_core.tools import StructuredTool
from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    HttpUrl,
    ValidationError,
    model_validator,
)

from clue_api.arv2.account_research_claims import (
    COMMITTEE_FIELD,
    ClaimInput,
    JobScope,
    agent_claims,
    ai_ark_company_claims,
    ats_posting_claims,
    committee_candidate_claims,
    fit_verdict_claims,
    media_index_claim,
    negative_claims,
    structured_claims,
    unconfirmed_candidates,
)
from clue_api.arv2.account_research_refusals import RefusalError, refusal_json
from clue_api.arv2.account_research_store import record_annotations
from clue_api.arv2.ai_ark_client import AiArkClient
from clue_api.arv2.ats_client import (
    BoardFetchFailed,
    BoardNotFound,
    BoardPostings,
    fetch_postings,
    find_board,
)
from clue_api.arv2.calls import CallCost, ProviderCaller
from clue_api.arv2.claim_writer import ClaimDraft, LenientClaimWriter, WriteReceipt
from clue_api.arv2.errors import ProviderHalted, RawParseError
from clue_api.arv2.exa_client import ExaClient, is_thin_deep_response, report_output_schema
from clue_api.arv2.gemini_media_client import (
    GeminiMediaClient,
    MediaBudget,
    MediaCeilingExceeded,
    SpeakerContext,
    transcription_input_from_enclosure,
    verify_speaker,
)
from clue_api.arv2.media_feeds_client import (
    EnclosureTooLarge,
    MediaFetchError,
    UnsupportedMediaHost,
    download_enclosure,
    fetch_feed,
    find_episode,
    reject_native_video,
    youtube_metadata,
    youtube_words,
)
from clue_api.arv2.provider_ledger import (
    ArtifactSink,
    BufferedLedger,
    BufferedRawSink,
    LedgerStamp,
    drain_provider_calls,
)
from clue_api.arv2.sinks import LedgerSink
from clue_api.arv2.structuring_client import (
    AccountSubject,
    FieldCatalog,
    StructuringClient,
)
from clue_api.arv2.text import substring_verdict
from clue_api.arv2.transport import HttpxTransport, Transport
from clue_config import Settings
from clue_core import Claim, RunId
from clue_db import ConnFactory
from clue_obs import get_logger
from clue_research.claimstore import WorkspaceScope, claims_for_runs

log = get_logger("clue_api.arv2.account_research_tools")

__all__ = [
    "ACCOUNT_TOOL_NAMES",
    "EVIDENCE_RULES",
    "LOCK_TEMPLATE",
    "ProviderClients",
    "ToolRuntime",
    "build_account_tools",
]

#: The twelve tools, in the order the manual lists them — free instruments first, the paid deep
#: call in the middle, the write gate and the finalizer last.
ACCOUNT_TOOL_NAMES: tuple[str, ...] = (
    "read_account_state",
    "read_ats_board",
    "fetch_page",
    "search_web",
    "lookup_company",
    "lookup_people",
    "read_media_feeds",
    "research_deep",
    "structure_material",
    "write_claims",
    "verify_links",
    "finalize_research",
)

#: Providers whose calls are serialised job-wide. AI Ark paces itself per client instance (a second
#: concurrent call would defeat the pacing and earn a 429), and media work is measured in minutes of
#: audio against one enforced ceiling, so two at once would race the reservation.
_SERIAL_PROVIDERS: frozenset[str] = frozenset({"ai_ark", "media"})

#: How much of a job posting's body the model is shown inline. Enough to judge whether the role is
#: an ABM/GTM signal; the whole description is on the claim.
_DESCRIPTION_HEAD_CHARS = 600

#: How much of a search hit's text the model is shown. A search is for *finding a URL*; reading it
#: is ``fetch_page``'s job, and paying twice for the same text is how a run's cost doubles.
_SEARCH_TEXT_HEAD_CHARS = 600

#: How much of a transcript comes back inline. The quotes are the product; this is the context
#: around them.
_TRANSCRIPT_EXCERPT_CHARS = 4000

#: The page text a link audit reads. Long enough that a quote late in a long page is still found.
_VERIFY_TEXT_MAX_CHARS = 20000

#: Constitution §2, as the deep call's system prompt. Same-name contamination is the single
#: recurring failure of this work, so the lock is stated to the provider in its own words rather
#: than left implicit in the query.
LOCK_TEMPLATE = """You research exactly ONE company and nothing else.

TARGET LOCK
  company: {name}
  domain: {domain}
Every same-name entity is excluded. When you meet one, name it and discard it with the reason: if
a source is about a laptop line, a bookkeeping tool or a spice brand rather than this company, say
so and drop it. Excluded same-name entities for this run: {exclusions}."""

#: Constitution §3, as the deep call's evidence law.
EVIDENCE_RULES = """EVIDENCE LAW
  * Every factual assertion carries a VERBATIM quote and the URL it came from.
  * NOT FOUND is a correct answer. Never estimate, never infer a number, never fill a gap with a
    plausible guess.
  * Distinguish what the company claims about itself from what a third party reports. A LinkedIn,
    Tracxn or CB-Insights auto-estimate is an ESTIMATE and is labelled as one, never as fact.
  * Name every person with the exact title and the URL that names them. Never invent a person.
  * Prefer primary sources: the company's own pages, its job postings, the funding wire release,
    the investors' announcement posts, the founders' own writing.
  * For any acquisition, rumour or contested item, state explicitly whether it is CONFIRMED,
    DENIED or UNRESOLVED, by whom, with the quote."""


class ProviderClients(Protocol):
    """The four clients a tool may use, each built around the hop's own caller.

    A client is constructed **per invocation** rather than held on the runtime, because a client
    binds to one :class:`ProviderCaller`, and one caller owns one hop's buffered raw sink and
    ledger. Sharing a client across hops would mean sharing a caller, and the ledger rows of two
    concurrent calls would drain into whichever transaction finished first.
    """

    def exa(self, caller: ProviderCaller) -> ExaClient: ...

    def ai_ark(self, caller: ProviderCaller) -> AiArkClient: ...

    def media(self, caller: ProviderCaller, ledger: LedgerSink) -> GeminiMediaClient: ...

    def structuring(self, caller: ProviderCaller) -> StructuringClient: ...


def _utcnow() -> datetime:
    return datetime.now(UTC)


class ToolRuntime:
    """Everything the twelve tools share: the job, the providers, the write path, the latches.

    It is deliberately not a tool itself and holds no model state. What it owns is the small set of
    facts that must be true across *all* the tools in one job — the provider halt latch, the
    refusal memory, the finalization flag, the call counter — because each of those is a rule about
    the job rather than about a call, and a per-tool copy of any of them would drift.
    """

    def __init__(
        self,
        *,
        scope: JobScope,
        settings: Settings,
        clients: ProviderClients,
        conn_factory: ConnFactory,
        artifacts: ArtifactSink,
        writer: LenientClaimWriter,
        catalog: FieldCatalog,
        media_budget: MediaBudget,
        transport_factory: Callable[[], Transport] = HttpxTransport,
        now: Callable[[], datetime] = _utcnow,
    ) -> None:
        self.scope = scope
        self.settings = settings
        self.clients = clients
        self.catalog = catalog
        self.media_budget = media_budget
        self._conn_factory = conn_factory
        self._artifacts = artifacts
        self._writer = writer
        self._transport_factory = transport_factory
        self._now = now

        #: provider → why it stopped selling. Job-level: once a provider halts, every later call to
        #: it is refused without a wire (master plan §2 item 3 — money truth blocks).
        self.halted: dict[str, str] = {}
        #: What ``finalize_research`` accepted. Set once; every other tool is closed afterwards.
        self.finalization: dict[str, Any] | None = None
        #: Tool calls this job has made, for the stop policy the driver enforces.
        self.tool_calls = 0
        #: Envelopes for tool calls the per-round ceiling dropped; the driver (Task 5) delivers
        #: them as the round's results.
        self.pending_refusals: list[ToolMessage] = []
        #: The agent's own model rounds, buffered here and drained onto ``provider_call_ledger``
        #: by the driver at settlement. A provider hop drains inside its own hop; a model call
        #: happens on the loop's thread with no connection of its own, and the loop must not open
        #: one per round — so the rounds ride here until the job settles.
        self.model_ledger = BufferedLedger()

        self._refusals: dict[str, str] = {}
        self._semaphores: dict[str, asyncio.Semaphore] = {}
        self._inflight: set[asyncio.Task[Any]] = set()
        self._ledgers: dict[int, BufferedLedger] = {}
        #: URL → page text for the link audit, so a claim set citing one page reads it once.
        self._page_cache: dict[str, str] = {}

    # -- the one path to a provider ---------------------------------------------------------------

    async def call_provider[T](self, provider: str, fn: Callable[[ProviderCaller], T]) -> T:
        """Run one synchronous provider hop off the loop, then land its money trail.

        The hop is shielded from the awaiting tool's cancellation on purpose: the runtime cap can
        fire while a call is in flight, and a cancelled drain would lose the raw bodies and ledger
        rows of a call that already happened — the one thing money truth cannot tolerate. The
        driver waits for the survivors through :meth:`wait_for_inflight` before it finalizes.
        """
        latched = self.halted.get(provider)
        if latched is not None:
            raise RefusalError(f"provider_halted:{provider}", latched)
        hop: asyncio.Task[T] = asyncio.create_task(self._hop(provider, fn))
        self._inflight.add(hop)
        hop.add_done_callback(self._forget_hop)
        return await asyncio.shield(hop)

    def _forget_hop(self, hop: asyncio.Task[Any]) -> None:
        self._inflight.discard(hop)
        if not hop.cancelled():
            # Retrieve the exception of a hop whose awaiter was cancelled, so a shielded failure is
            # never reported as an unretrieved task exception.
            hop.exception()

    async def _hop[T](self, provider: str, fn: Callable[[ProviderCaller], T]) -> T:
        async with self._semaphore(provider):
            raw, ledger = BufferedRawSink(), BufferedLedger()
            caller = ProviderCaller(
                transport=self._transport_factory(),
                raw_sink=raw,
                ledger=ledger,
                now=self._now,
            )
            self._ledgers[id(caller)] = ledger
            try:
                return await asyncio.to_thread(fn, caller)
            except ProviderHalted as halted:
                detail = str(halted)
                self.halted[provider] = detail
                # Latch the *wire* provider as well as the tool's label for it. One media hop can
                # spend on OpenRouter, so "OpenRouter is out of credit" learned inside a media call
                # must also stop the structuring calls, which reach the same account under their
                # own label. Money truth blocks whoever meets it first.
                self.halted.setdefault(halted.provider, detail)
                raise RefusalError(f"provider_halted:{provider}", detail) from halted
            finally:
                self._ledgers.pop(id(caller), None)
                await self._drain(raw, ledger)

    def _semaphore(self, provider: str) -> asyncio.Semaphore:
        if provider not in self._semaphores:
            limit = (
                1
                if provider in _SERIAL_PROVIDERS
                else self.settings.arv2_account_provider_concurrency
            )
            self._semaphores[provider] = asyncio.Semaphore(limit)
        return self._semaphores[provider]

    def ledger_of(self, caller: ProviderCaller) -> LedgerSink:
        """The buffered ledger belonging to one in-flight caller.

        The media client writes rows of its own (a ceiling refusal happens before any request, so
        the wrapper never sees it), which means it needs the same ledger the hop will drain — and
        ``fn`` is handed the caller, not the sinks. This is that lookup, and it exists so the media
        client's rows land in the hop's own transaction rather than in a second one.
        """
        ledger = self._ledgers.get(id(caller))
        if ledger is None:  # pragma: no cover - only reachable outside a hop
            raise RuntimeError("ledger_of was called with a caller that is not in a hop")
        return ledger

    async def wait_for_inflight(self, *, timeout_s: float) -> None:
        """Wait, bounded, for hops still running so their drains land. Never raises."""
        pending = [hop for hop in self._inflight if not hop.done()]
        if pending:
            await asyncio.wait(pending, timeout=timeout_s)

    async def _drain(self, raw: BufferedRawSink, ledger: BufferedLedger) -> None:
        async with self._conn_factory() as conn:
            await drain_provider_calls(
                conn,
                raw=raw,
                ledger=ledger,
                artifacts=self._artifacts,
                stamp=LedgerStamp(
                    workspace_id=self.scope.workspace_id,
                    project_id=self.scope.project_id,
                    project_run_id=str(self.scope.project_run_id),
                    job_id=self.scope.job_id,
                ),
            )

    # -- the one path to a claim ------------------------------------------------------------------

    async def write(self, drafts: Sequence[ClaimDraft]) -> list[WriteReceipt]:
        """Write every draft through the lenient gate, in one transaction."""
        if not drafts:
            return []
        async with self._conn_factory() as conn:
            return [await self._writer.write(conn, draft) for draft in drafts]

    async def job_claims(self) -> Sequence[Claim]:
        """This job's own claims: written by this run, about this account."""
        async with self._conn_factory() as conn:
            claims = await claims_for_runs(
                conn,
                [RunId(self.scope.run_id)],
                scope=WorkspaceScope.for_workspace(self.scope.workspace_id),
            )
        return [claim for claim in claims if claim.entity_id == self.scope.account_id]

    async def record_link_audit(self, claim_ids_by_verdict: Mapping[str, Sequence[UUID]]) -> int:
        """Write one link-audit annotation per claim. An annotation is a check result beside the
        claim, never an edit to append-only history."""
        async with self._conn_factory() as conn:
            return await record_annotations(
                conn, job_id=self.scope.job_id, claim_ids_by_verdict=claim_ids_by_verdict
            )

    def now(self) -> datetime:
        """The job's clock, injected so a finalization timestamp is testable."""
        return self._now()

    # -- the refusal memory -----------------------------------------------------------------------

    def remember_refusal(self, tool: str, args: Mapping[str, Any], envelope: str) -> None:
        """Record that this exact call was refused, so the identical retry costs nothing."""
        self._refusals[_call_key(tool, args)] = envelope

    def repeated_refusal(self, tool: str, args: Mapping[str, Any]) -> str | None:
        """The ``identical_call_repeated`` envelope for a call already refused, or ``None``.

        It names the earlier refusal rather than repeating it: the model's three admissible moves
        (change the arguments, make the call the earlier refusal named, or finalize honestly) are
        the same for every repeat, and a verbatim replay of the original refusal reads as new
        information when it is not.
        """
        previous = self._refusals.get(_call_key(tool, args))
        if previous is None:
            return None
        earlier = json.loads(previous)
        return refusal_json(
            "identical_call_repeated",
            f"this exact call was already refused {earlier['code']}: {earlier['detail']}",
        )

    # -- the link-audit page cache -----------------------------------------------------------------

    def cached_page(self, url: str) -> str | None:
        return self._page_cache.get(url)

    def cache_page(self, url: str, text: str) -> None:
        self._page_cache[url] = text


def _call_key(tool: str, args: Mapping[str, Any]) -> str:
    """A stable identity for one call: the tool plus its arguments, canonically serialised."""
    canonical = json.dumps(dict(args), sort_keys=True, default=str)
    return hashlib.sha256(f"{tool}\x00{canonical}".encode()).hexdigest()


# -- serialisation helpers -------------------------------------------------------------------------


def _cost_json(cost: CallCost | None) -> dict[str, Any] | None:
    """One call's money view, in the shape the model and the dossier both read."""
    if cost is None:
        return None
    return {
        "usd": str(cost.cost_usd) if cost.cost_usd is not None else None,
        "credits": str(cost.credits) if cost.credits is not None else None,
        "media_seconds": cost.media_seconds,
        "source": cost.cost_source,
        "provider": cost.provider,
        "operation": cost.operation,
    }


def _claim_json(claim: Claim) -> dict[str, Any]:
    return {
        "claim_id": str(claim.id),
        "field_key": claim.field_key,
        "value": claim.value_json,
        "quote": claim.evidence_span,
        "url": claim.source_url,
        "priority": claim.signal_priority,
        "outreach_safe": claim.outreach_safe,
        "source_key": claim.source_key,
    }


def _receipt_json(receipt: WriteReceipt, draft: ClaimDraft) -> dict[str, Any]:
    return {
        "claim_id": str(receipt.claim_id),
        "field_key": receipt.field_key,
        "value": draft.value_json,
        "quote": draft.evidence_span,
        "url": draft.source_url,
        "priority": draft.signal_priority,
        "outreach_safe": draft.outreach_safe,
        "markers": receipt.markers,
    }


def _head(text: str | None, limit: int) -> str:
    return (text or "")[:limit]


def _safe_name(text: str) -> str:
    """A filesystem-safe stem for a downloaded enclosure."""
    return re.sub(r"[^a-zA-Z0-9._-]+", "-", text).strip("-")[:80] or "episode"


# -- tool arguments ----------------------------------------------------------------------------


class _Args(BaseModel):
    """Every tool's arguments are closed: an invented argument is a refusal, never a silent drop."""

    model_config = ConfigDict(extra="forbid")


class ReadAccountStateArgs(_Args):
    section: Literal["all", "claims", "open_fields", "icp", "persona", "already_established"] = (
        "all"
    )


class ReadAtsBoardArgs(_Args):
    company_url: str = Field(min_length=4)


class FetchPageArgs(_Args):
    url: HttpUrl
    max_chars: int = Field(8000, ge=500, le=20000)


class SearchWebArgs(_Args):
    query: str = Field(min_length=3)
    num_results: int = Field(8, ge=1, le=10)
    include_domains: list[str] | None = None
    start_published_date: str | None = None


class LookupCompanyArgs(_Args):
    domain: str = Field(min_length=3)


class LookupPeopleArgs(_Args):
    name_variants: list[str] = Field(min_length=1, max_length=4)
    domain: str = Field(min_length=3)
    size: int = Field(3, ge=1, le=3)


class ReadMediaFeedsArgs(_Args):
    person_name: str = Field(min_length=2)
    person_role: str = ""
    feed_url: HttpUrl | None = None
    youtube_url: HttpUrl | None = None
    episode_title_contains: str | None = None
    episode_number: int | None = None

    @model_validator(mode="after")
    def _needs_one_source(self) -> ReadMediaFeedsArgs:
        if self.feed_url is None and self.youtube_url is None:
            raise ValueError("read_media_feeds needs a feed_url or a youtube_url; it finds neither")
        return self


class ResearchDeepArgs(_Args):
    charter: str = Field(min_length=200)
    probes: list[str] = Field(default_factory=list, max_length=6)
    same_name_exclusions: list[str] = Field(default_factory=list)
    num_results: int = Field(20, ge=10, le=25)


class StructureMaterialArgs(_Args):
    subject_kind: Literal["account", "person"]
    subject_name: str = Field(min_length=2)
    subject_domain_or_company: str = Field(min_length=2)
    linkedin_url: str | None = None
    material: str = Field(min_length=50, max_length=120_000)
    mode: Literal["broad", "intent_sweep"] = "broad"
    already_known: str | None = None


class WriteClaimsArgs(_Args):
    claims: list[ClaimInput] = Field(min_length=1, max_length=50)


class VerifyLinksArgs(_Args):
    claim_ids: list[str] | None = None


class FitVerdict(_Args):
    gate: str = Field(min_length=1)
    verdict: Literal["pass", "likely", "unclear", "fail"]
    rationale: str = Field(min_length=1)
    claim_ids: list[str] = Field(default_factory=list)


class CommitteeCandidate(_Args):
    name: str | None = None
    title: str | None = None
    persona: Literal["economic_buyer", "champion", "user", "technical_evaluator", "blocker"]
    linkedin_url: str | None = None
    confirmed_by: str | None = None
    vacant_seat: bool = False
    evidence_span: str | None = None


class FinalizeResearchArgs(_Args):
    summary: str = Field(min_length=20)
    fit_verdicts: list[FitVerdict] = Field(default_factory=list)
    gaps: list[str] = Field(default_factory=list)
    committee_candidates: list[CommitteeCandidate] = Field(default_factory=list)


# -- the tool bodies ---------------------------------------------------------------------------


async def _read_account_state(runtime: ToolRuntime, args: ReadAccountStateArgs) -> dict[str, Any]:
    scope = runtime.scope
    claims = await runtime.job_claims()
    written_keys = {claim.field_key for claim in claims}
    state: dict[str, Any] = {
        "account": {
            "name": scope.account_name,
            "domain": scope.account_domain,
            "id": str(scope.account_id),
        },
        "claims": [_claim_json(claim) for claim in claims],
        "open_fields": sorted(runtime.catalog.keys() - written_keys),
        "icp": scope.icp_markdown,
        "persona": scope.persona_markdown,
        "already_established": scope.already_established,
    }
    if args.section == "all":
        return state
    return {args.section: state[args.section]}


async def _read_ats_board(runtime: ToolRuntime, args: ReadAtsBoardArgs) -> dict[str, Any]:
    def hop(caller: ProviderCaller) -> BoardPostings:
        board = find_board(args.company_url, caller)
        if board is None:
            raise RefusalError(
                "board_not_found",
                f"no page under {args.company_url} names an ATS board; the slug is never guessed",
            )
        return fetch_postings(board, caller)

    try:
        postings = await runtime.call_provider("ats", hop)
    except BoardNotFound as missing:
        raise RefusalError("board_not_found", str(missing)) from missing
    except BoardFetchFailed as failed:
        raise RefusalError("board_fetch_failed", str(failed)) from failed

    receipts = await runtime.write(ats_posting_claims(postings, runtime.scope))
    return {
        "board": {
            "kind": postings.board.kind,
            "slug": postings.board.slug,
            "read_from": postings.board.source_url,
            "url": postings.url,
        },
        "postings": [
            {
                "title": posting.title,
                "department": posting.department,
                "location": posting.location,
                "published_at": posting.published_at.isoformat() if posting.published_at else None,
                "days_open": posting.days_open,
                "url": posting.url,
                "description_head": _head(posting.description_plain, _DESCRIPTION_HEAD_CHARS),
            }
            for posting in postings.postings
        ],
        "claim_ids": [str(receipt.claim_id) for receipt in receipts],
        "cost": _cost_json(postings.cost),
    }


async def _fetch_page(runtime: ToolRuntime, args: FetchPageArgs) -> dict[str, Any]:
    url = str(args.url)

    def hop(caller: ProviderCaller) -> Any:
        return runtime.clients.exa(caller).contents([url], text_max_chars=args.max_chars)

    result = await runtime.call_provider("exa", hop)
    hit = result.results[0] if result.results else None
    if hit is None or not (hit.text or "").strip():
        raise RefusalError("page_unavailable", f"{url} came back with no text")
    return {
        "url": hit.url or url,
        "title": hit.title,
        "text": hit.text,
        "raw_ref": result.raw_ref,
        "cost": _cost_json(result.cost),
    }


async def _search_web(runtime: ToolRuntime, args: SearchWebArgs) -> dict[str, Any]:
    def hop(caller: ProviderCaller) -> Any:
        return runtime.clients.exa(caller).search(
            args.query,
            num_results=args.num_results,
            include_domains=args.include_domains,
            start_published_date=args.start_published_date,
            label=f"search-{runtime.scope.account_domain}",
        )

    result = await runtime.call_provider("exa", hop)
    return {
        "hits": [
            {
                "url": hit.url,
                "title": hit.title,
                "published": hit.published_date,
                "text_head": _head(hit.text, _SEARCH_TEXT_HEAD_CHARS),
            }
            for hit in result.results
        ],
        "cost": _cost_json(result.cost),
    }


async def _lookup_company(runtime: ToolRuntime, args: LookupCompanyArgs) -> dict[str, Any]:
    def hop(caller: ProviderCaller) -> Any:
        return runtime.clients.ai_ark(caller).company_by_domain(args.domain)

    company = await runtime.call_provider("ai_ark", hop)
    if company is None:
        raise RefusalError("company_not_found", f"AI Ark holds no record for {args.domain}")

    receipts = await runtime.write(ai_ark_company_claims(company, runtime.scope))
    raw = company.raw if isinstance(company.raw, Mapping) else {}
    financial = raw.get("financial") if isinstance(raw.get("financial"), Mapping) else {}
    funding = financial.get("funding") if isinstance(financial, Mapping) else None
    return {
        "company": {
            "name": company.name,
            "domain": company.domain,
            "linkedin": company.linkedin,
            "industry": company.industry,
            "employee_count": company.employee_count,
            "revenue": company.revenue,
            "hq_location": dict(company.location) if company.location else None,
        },
        "technologies": list(company.technologies),
        # ``financial.funding`` is the record's own funding block (rounds, investors, totals). It is
        # returned as context rather than written: no registered field carries it yet, and the
        # agent quotes it into a claim only with the evidence it finds elsewhere.
        "funding": funding if isinstance(funding, Mapping) else None,
        "claim_ids": [str(receipt.claim_id) for receipt in receipts],
        "cost": _cost_json(company.cost),
    }


async def _lookup_people(runtime: ToolRuntime, args: LookupPeopleArgs) -> dict[str, Any]:
    def hop(caller: ProviderCaller) -> Any:
        return runtime.clients.ai_ark(caller).people_by_name(
            args.name_variants, args.domain, size=args.size
        )

    people = await runtime.call_provider("ai_ark", hop)
    # No claim is written here, deliberately: a provider record confirms an identity, it does not
    # establish that this person sits on the buying committee. That judgement is the agent's, and
    # it becomes a claim through ``write_claims`` or ``finalize_research`` with a confirming URL.
    return {
        "people": [
            {
                "full_name": person.full_name,
                "title": person.title,
                "headline": person.headline,
                "linkedin_url": person.linkedin_url,
                "current_company": person.current_company,
                "current_company_domain": person.current_company_domain,
            }
            for person in people.people
        ],
        "cost": _cost_json(people.cost),
    }


@dataclass(frozen=True)
class _MediaItem:
    """What one media hop resolved, before anything is written or refused."""

    kind: str
    url: str
    title: str | None
    duration_s: int | None
    transcript_model: str | None
    transcript_text: str
    speaker_verified: bool
    speaker_evidence: str
    quotes: tuple[dict[str, Any], ...]
    words: str | None
    costs: tuple[CallCost | None, ...]


def _podcast_hop(
    runtime: ToolRuntime, args: ReadMediaFeedsArgs
) -> Callable[[ProviderCaller], _MediaItem]:
    """The whole podcast chain as one synchronous hop: feed → episode → audio → words → quotes."""
    scope = runtime.scope
    feed_url = str(args.feed_url)
    max_bytes = runtime.settings.arv2_account_media_max_enclosure_mb * 1024 * 1024
    destination_root = Path(runtime.settings.arv2_raw_root) / "media" / str(scope.job_id)

    def hop(caller: ProviderCaller) -> _MediaItem:
        podcast = fetch_feed(feed_url, caller)
        episode = find_episode(
            podcast,
            number=args.episode_number,
            # With neither a number nor a title fragment given, the person's own name is the
            # substring test — an exact match, never a fuzzy score (law 10: the proof-of-concept's
            # scored matcher confidently handed back the wrong episode).
            title_contains=args.episode_title_contains
            or (None if args.episode_number is not None else args.person_name),
        )
        if episode is None:
            raise RefusalError(
                "episode_not_found",
                f"{podcast.title} has no episode matching "
                f"{args.episode_number or args.episode_title_contains or args.person_name!r}",
            )
        audio = download_enclosure(
            episode,
            destination_root / f"{_safe_name(episode.title)}.mp3",
            caller,
            max_bytes=max_bytes,
        )
        transcribable = transcription_input_from_enclosure(
            audio, display_name=_safe_name(f"{args.person_name}-{episode.title}")
        )
        named = args.person_name.lower() in f"{episode.title} {episode.description or ''}".lower()
        context = SpeakerContext(
            person_name=args.person_name,
            person_role=args.person_role,
            organisation=scope.account_name,
            named_in_metadata=named,
        )
        media = runtime.clients.media(caller, runtime.ledger_of(caller))
        transcript = (
            media.transcribe_short(transcribable, context=context)
            if transcribable.duration_s <= runtime.settings.arv2_media_short_max_seconds
            else media.transcribe_long(transcribable, context=context)
        )
        verdict = verify_speaker(transcript, context)
        costs: list[CallCost | None] = [podcast.cost, audio.cost, transcript.cost]
        costs.extend(transcript.upload_costs)
        quotes: tuple[dict[str, Any], ...] = ()
        if verdict.verified:
            mined = media.mine_quotes(transcript.text, context=context, n=6, speaker_verified=True)
            costs.append(mined.cost)
            quotes = tuple(
                {
                    "text": quote.text,
                    "timestamp": quote.ts_s,
                    "why": quote.why,
                    "verbatim": quote.verdict,
                    "usable": quote.usable,
                }
                for quote in mined.quotes
            )
        return _MediaItem(
            kind="podcast",
            url=episode.enclosure_url or episode.link or feed_url,
            title=episode.title,
            duration_s=transcribable.duration_s,
            transcript_model=transcript.model,
            transcript_text=transcript.text,
            speaker_verified=verdict.verified,
            speaker_evidence=verdict.evidence,
            quotes=quotes,
            words=None,
            costs=tuple(costs),
        )

    return hop


def _youtube_hop(
    runtime: ToolRuntime, args: ReadMediaFeedsArgs
) -> Callable[[ProviderCaller], _MediaItem]:
    """The words path: metadata plus an indexed copy of the page. Nothing is transcribed."""
    watch_url = str(args.youtube_url)

    def hop(caller: ProviderCaller) -> _MediaItem:
        reject_native_video(watch_url)
        meta = youtube_metadata(watch_url, caller)
        exa = runtime.clients.exa(caller)

        def page_text(urls: Sequence[str]) -> Mapping[str, str]:
            fetched = exa.contents(list(urls), text_max_chars=_VERIFY_TEXT_MAX_CHARS)
            return {hit.url: hit.text or "" for hit in fetched.results if hit.url}

        words = youtube_words(watch_url, page_text, title=meta.title)
        return _MediaItem(
            kind="youtube",
            url=watch_url,
            title=meta.title,
            duration_s=meta.length_s,
            transcript_model=None,
            transcript_text="",
            # Indexed page text is not attributed speech: nothing here proves the subject said any
            # of it, so the item is recorded unverified and quotes must come from elsewhere.
            speaker_verified=False,
            speaker_evidence="page text is not attributed speech",
            quotes=(),
            words=words.text,
            costs=(meta.cost,),
        )

    return hop


async def _read_media_feeds(runtime: ToolRuntime, args: ReadMediaFeedsArgs) -> dict[str, Any]:
    podcast_first = args.feed_url is not None
    hop = _podcast_hop(runtime, args) if podcast_first else _youtube_hop(runtime, args)
    try:
        item = await runtime.call_provider("media", hop)
    except MediaCeilingExceeded as ceiling:
        raise RefusalError("media_ceiling_reached", str(ceiling)) from ceiling
    except EnclosureTooLarge as oversized:
        raise RefusalError("enclosure_too_large", str(oversized)) from oversized
    except UnsupportedMediaHost as walled:
        raise RefusalError("native_video_rejected", str(walled)) from walled
    except (MediaFetchError, RawParseError) as unreachable:
        raise RefusalError("feed_not_found", str(unreachable)) from unreachable

    await runtime.write(
        [
            media_index_claim(
                person=args.person_name,
                item_url=item.url,
                kind=item.kind,
                duration_s=item.duration_s,
                transcript_model=item.transcript_model,
                speaker_verified=item.speaker_verified,
                scope=runtime.scope,
            )
        ]
    )
    if item.kind == "podcast" and not item.speaker_verified:
        # The item is on the record; what is refused is *quoting* it.
        raise RefusalError(
            "speaker_unverified",
            f"nothing in {item.title!r} identifies the speaker as {args.person_name}",
        )
    return {
        "item": {
            "kind": item.kind,
            "url": item.url,
            "title": item.title,
            "duration_s": item.duration_s,
            "transcript_model": item.transcript_model,
        },
        "speaker_verified": item.speaker_verified,
        "speaker_evidence": item.speaker_evidence,
        "quotes": [{"text": q["text"], "timestamp": q["timestamp"]} for q in item.quotes],
        "transcript_excerpt": _head(item.transcript_text, _TRANSCRIPT_EXCERPT_CHARS),
        "words": item.words,
        "cost": [_cost_json(cost) for cost in item.costs if cost is not None],
    }


async def _research_deep(runtime: ToolRuntime, args: ResearchDeepArgs) -> dict[str, Any]:
    scope = runtime.scope
    exclusions = ", ".join(args.same_name_exclusions) or "none named"
    system_prompt = (
        LOCK_TEMPLATE.format(
            name=scope.account_name, domain=scope.account_domain, exclusions=exclusions
        )
        + "\n\n"
        + EVIDENCE_RULES
    )
    query_parts = [args.charter]
    if args.probes:
        query_parts.append("SPECIAL PROBES\n" + "\n".join(f"- {probe}" for probe in args.probes))
    query_parts.append(
        "ALREADY ESTABLISHED (do not re-derive; find what is NOT here)\n"
        + (scope.already_established or "(nothing yet)")
    )
    query = "\n\n".join(query_parts)

    def hop(caller: ProviderCaller) -> Any:
        return runtime.clients.exa(caller).deep_reasoning(
            system_prompt=system_prompt,
            query=query,
            output_schema=report_output_schema(),
            num_results=args.num_results,
            label=f"deep-{scope.account_domain}",
        )

    result = await runtime.call_provider("exa", hop)
    report = result.report_text or ""
    if not report.strip():
        raise RefusalError(
            "deep_thin_response", "the deep call returned an empty report after its own retry"
        )
    return {
        "report": report,
        # A thin report is *returned*, not refused: it is still evidence, and the manual's row
        # tells the model what to do with one. Only an empty report is a refusal.
        "thin": is_thin_deep_response(
            n_results=result.n_results, cost_usd=result.cost_usd, report_chars=len(report)
        ),
        "n_results": result.n_results,
        "retried": result.retried,
        "raw_ref": result.raw_ref,
        "cost": _cost_json(result.cost),
    }


async def _structure_material(runtime: ToolRuntime, args: StructureMaterialArgs) -> dict[str, Any]:
    if args.subject_kind == "person":
        raise RefusalError(
            "invalid_arguments",
            "R2 researches one account: a person subject is admitted in R3, when contact entities "
            "are composed. Structure the person's material as an account subject instead.",
        )
    subject = AccountSubject(
        name=args.subject_name,
        domain=args.subject_domain_or_company,
        already_known=args.already_known,
    )

    def hop(caller: ProviderCaller) -> Any:
        return runtime.clients.structuring(caller).structure_account(
            subject, args.material, runtime.catalog, mode=args.mode
        )

    try:
        output = await runtime.call_provider("openrouter", hop)
    except RawParseError as unparseable:
        raise RefusalError("structuring_unparseable", str(unparseable)) from unparseable

    drafts = structured_claims(output, scope=runtime.scope, subject_url_hint=None)
    negatives = negative_claims(output.negatives, runtime.scope)
    receipts = await runtime.write([*drafts, *negatives])
    written = [
        _receipt_json(receipt, draft)
        for receipt, draft in zip(receipts[: len(drafts)], drafts, strict=False)
    ]
    return {
        "written": written,
        "proposed": [
            {
                "suggested_key": proposed.suggested_key,
                "why": proposed.why,
                "origin": proposed.origin,
            }
            for proposed in output.proposed
        ],
        "negatives_written": len(negatives),
        "mode": output.mode,
        "cost": _cost_json(output.cost),
    }


async def _write_claims(runtime: ToolRuntime, args: WriteClaimsArgs) -> dict[str, Any]:
    unconfirmed = [
        item.field_key
        for item in args.claims
        if item.field_key == COMMITTEE_FIELD
        and isinstance(item.value, Mapping)
        and item.value.get("name")
        and not item.value.get("confirmed_by")
    ]
    if unconfirmed:
        raise RefusalError(
            "invalid_arguments",
            f"a named {COMMITTEE_FIELD} needs a confirmed_by URL naming the person "
            f"({len(unconfirmed)} claim(s) in this call have none)",
        )
    drafts = agent_claims(args.claims, runtime.scope)
    receipts = await runtime.write(drafts)
    return {
        "written": [
            _receipt_json(receipt, draft) for receipt, draft in zip(receipts, drafts, strict=True)
        ]
    }


async def _verify_links(runtime: ToolRuntime, args: VerifyLinksArgs) -> dict[str, Any]:
    claims = [claim for claim in await runtime.job_claims() if claim.source_url]
    if args.claim_ids is not None:
        wanted = set(args.claim_ids)
        claims = [claim for claim in claims if str(claim.id) in wanted]

    verdicts: dict[str, list[UUID]] = {"EXACT": [], "PARTIAL": [], "NOT_FOUND": []}
    failed: list[str] = []
    costs: list[dict[str, Any] | None] = []
    for claim in claims:
        url = claim.source_url or ""
        if url in failed:
            continue
        text = runtime.cached_page(url)
        if text is None:
            try:
                text = await _fetch_for_audit(runtime, url, costs)
            except RefusalError:
                raise
            except Exception as unreachable:  # noqa: BLE001 — a dead link is a finding, not a stop
                log.info("arv2.verify_links_fetch_failed", url=url, error=str(unreachable))
                failed.append(url)
                continue
        if not text.strip():
            # A page that came back empty proves nothing about the quote. Calling that NOT_FOUND
            # would report an unreadable link as a fabricated one, which is the wrong accusation.
            failed.append(url)
            continue
        verdicts[substring_verdict(claim.evidence_span or "", text)].append(UUID(str(claim.id)))

    await runtime.record_link_audit(verdicts)
    return {
        "EXACT": len(verdicts["EXACT"]),
        "PARTIAL": len(verdicts["PARTIAL"]),
        "NOT_FOUND": [str(claim_id) for claim_id in verdicts["NOT_FOUND"]],
        "fetch_failed": failed,
        "cost": costs,
    }


async def _fetch_for_audit(
    runtime: ToolRuntime, url: str, costs: list[dict[str, Any] | None]
) -> str:
    """One page read for the audit, cached for the job: claims citing one page read it once."""

    def hop(caller: ProviderCaller) -> Any:
        return runtime.clients.exa(caller).contents(
            [url], text_max_chars=_VERIFY_TEXT_MAX_CHARS, label="verify-links"
        )

    result = await runtime.call_provider("exa", hop)
    costs.append(_cost_json(result.cost))
    hit = result.results[0] if result.results else None
    text = (hit.text if hit else "") or ""
    runtime.cache_page(url, text)
    return text


async def _finalize_research(runtime: ToolRuntime, args: FinalizeResearchArgs) -> dict[str, Any]:
    if runtime.finalization is not None:
        raise RefusalError("finalization_already_proposed", "this job is already finalized")

    verdicts = [verdict.model_dump() for verdict in args.fit_verdicts]
    candidates = [candidate.model_dump() for candidate in args.committee_candidates]
    drafts = [
        *fit_verdict_claims(verdicts, runtime.scope),
        *committee_candidate_claims(candidates, runtime.scope),
    ]
    receipts = await runtime.write(drafts)
    dropped = [str(candidate.get("name")) for candidate in unconfirmed_candidates(candidates)]
    runtime.finalization = {
        "summary": args.summary,
        "fit_verdicts": verdicts,
        "gaps": list(args.gaps),
        "proposed_at": runtime.now().isoformat(),
    }
    return {
        "accepted": True,
        "claim_ids": [str(receipt.claim_id) for receipt in receipts],
        "dropped_candidates": dropped,
    }


# -- the governed wrapper ------------------------------------------------------------------------


def _governed(
    runtime: ToolRuntime,
    name: str,
    model: type[BaseModel],
    body: Callable[[ToolRuntime, Any], Awaitable[Mapping[str, Any]]],
) -> Callable[..., Awaitable[str]]:
    """Wrap one tool body in the failure law: every exit is a JSON string, never an exception."""

    async def call(**args: Any) -> str:
        if runtime.finalization is not None and name != "finalize_research":
            return refusal_json("finalization_already_proposed", "the decision is made")
        if (previous := runtime.repeated_refusal(name, args)) is not None:
            return previous
        runtime.tool_calls += 1
        try:
            return json.dumps(await body(runtime, model(**args)), default=str)
        except RefusalError as refused:
            envelope = refusal_json(refused.refusal.code, refused.refusal.detail)
        except ValidationError as invalid:
            envelope = refusal_json("invalid_arguments", str(invalid)[:500])
        except Exception as error:  # noqa: BLE001 — the failure law: never a raise into the graph
            log.exception("arv2.account_tool_failed", tool=name)
            envelope = refusal_json(f"tool_error:{type(error).__name__}", str(error)[:500])
        runtime.remember_refusal(name, args, envelope)
        return envelope

    return call


def _tool(
    runtime: ToolRuntime,
    *,
    name: str,
    description: str,
    model: type[BaseModel],
    body: Callable[[ToolRuntime, Any], Awaitable[Mapping[str, Any]]],
) -> StructuredTool:
    """One governed tool. An argument the schema rejects is a refusal, not a LangChain exception."""
    return StructuredTool.from_function(
        coroutine=_governed(runtime, name, model, body),
        name=name,
        description=description,
        args_schema=model,
        handle_validation_error=lambda error: refusal_json("invalid_arguments", str(error)[:500]),
    )


def build_account_tools(runtime: ToolRuntime) -> list[StructuredTool]:
    """The twelve tools for one account job, bound to that job's runtime."""
    return [
        _tool(
            runtime,
            name="read_account_state",
            description=(
                "What is already known about this account: the claims this job has written, which "
                "catalog fields are still open, the ICP charter, the persona map and the "
                "already-established block. Free. Sections: all, claims, open_fields, icp, "
                "persona, already_established."
            ),
            model=ReadAccountStateArgs,
            body=_read_account_state,
        ),
        _tool(
            runtime,
            name="read_ats_board",
            description=(
                "Read the company's own ATS board (Ashby, Greenhouse or Lever) from the slug its "
                "careers page publishes, and write one claim per open requisition. Free. The slug "
                "is read, never guessed."
            ),
            model=ReadAtsBoardArgs,
            body=_read_ats_board,
        ),
        _tool(
            runtime,
            name="fetch_page",
            description=(
                "Fetch the verbatim text of a URL you already hold (their own site, a careers "
                "page, a funding wire, a case study). A known URL is fetched, never searched for."
            ),
            model=FetchPageArgs,
            body=_fetch_page,
        ),
        _tool(
            runtime,
            name="search_web",
            description=(
                "A bounded gap search (at most ten results) for a named fact or a named person. "
                "Returns URLs and short heads; read a promising hit with fetch_page."
            ),
            model=SearchWebArgs,
            body=_search_web,
        ),
        _tool(
            runtime,
            name="lookup_company",
            description=(
                "Deterministic firmographics for one exact domain from the company database: "
                "industry, headcount, revenue band, HQ, LinkedIn, technologies and funding. The "
                "five mapped fields are written as claims in code, with the record path recorded."
            ),
            model=LookupCompanyArgs,
            body=_lookup_company,
        ),
        _tool(
            runtime,
            name="lookup_people",
            description=(
                "Confirm the identity of a NAMED person at this account (name variants, scoped to "
                "the domain, at most three results). Identity confirmation only — it writes no "
                "claims and it is never a roster search."
            ),
            model=LookupPeopleArgs,
            body=_lookup_people,
        ),
        _tool(
            runtime,
            name="read_media_feeds",
            description=(
                "Read a named leader's podcast episode (feed_url, by number or title fragment) or "
                "a YouTube appearance (youtube_url, indexed page words — never a video download). "
                "A podcast episode is transcribed, the speaker verified, and quotes mined only "
                "when the speaker is verified."
            ),
            model=ReadMediaFeedsArgs,
            body=_read_media_feeds,
        ),
        _tool(
            runtime,
            name="research_deep",
            description=(
                "The one paid dossier call: your charter and special probes go in the query, the "
                "target lock and the evidence law in the system prompt, and what is already "
                "established is named so the provider finds what is NOT there. Use it once."
            ),
            model=ResearchDeepArgs,
            body=_research_deep,
        ),
        _tool(
            runtime,
            name="structure_material",
            description=(
                "Turn prose into typed claims against the field catalog, one subject per call, and "
                "write them. mode='broad' sweeps everything the catalog can hold; "
                "mode='intent_sweep' pulls only verbatim buying-intent statements. In R2 the only "
                "admitted subject_kind is 'account'."
            ),
            model=StructureMaterialArgs,
            body=_structure_material,
        ),
        _tool(
            runtime,
            name="write_claims",
            description=(
                "Write up to fifty claims yourself, each with a verbatim quote and the URL it came "
                "from. Everything is stored; a missing URL, an unknown key or a schema miss is "
                "recorded as a marker rather than refused."
            ),
            model=WriteClaimsArgs,
            body=_write_claims,
        ),
        _tool(
            runtime,
            name="verify_links",
            description=(
                "The fabrication audit: re-fetch the pages this job's claims cite and check every "
                "quote against the page text, EXACT / PARTIAL / NOT_FOUND, written as an "
                "annotation beside the claim."
            ),
            model=VerifyLinksArgs,
            body=_verify_links,
        ),
        _tool(
            runtime,
            name="finalize_research",
            description=(
                "Finish the job once: the summary, one lenient fit verdict per ICP gate with the "
                "claim ids behind it, the honest gaps, and the confirmed committee candidates. "
                "Zero yield is a valid outcome. It can be accepted only once."
            ),
            model=FinalizeResearchArgs,
            body=_finalize_research,
        ),
    ]
