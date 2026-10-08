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
import contextlib
import hashlib
import json
import re
import time
from collections.abc import Awaitable, Callable, Mapping, Sequence
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal, Protocol, cast
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
from sqlalchemy import text

from clue_api.arv2 import research_operations as operations
from clue_api.arv2.account_exa_brief import (
    account_exa_arguments,
    uses_account_discovery,
    uses_account_exa_brief,
)
from clue_api.arv2.account_research_catalog import has_capability
from clue_api.arv2.account_research_claims import (
    COMMITTEE_FIELD,
    PUBLIC_APPEARANCES_FIELD,
    ClaimInput,
    JobScope,
    agent_claims,
    ai_ark_company_claims,
    ai_ark_person_claims,
    ats_posting_claims,
    committee_candidate_claims,
    email_export_claim,
    fit_verdict_claims,
    media_index_claim,
    negative_claims,
    person_finalization_claims,
    structured_claims,
    unconfirmed_candidates,
    unique_insight_claims,
)
from clue_api.arv2.account_research_refusals import (
    PERSON_REFUSAL_CODES,
    REFUSAL_CODES,
    RefusalError,
    refusal_json,
)
from clue_api.arv2.account_research_store import (
    AnnotationRow,
    JobStage,
    find_contact_by_name,
    record_annotations,
    set_job_stage,
)
from clue_api.arv2.ai_ark_client import AiArkClient
from clue_api.arv2.ai_ark_research import enrichment_only
from clue_api.arv2.ats_client import (
    BoardFetchFailed,
    BoardNotFound,
    BoardPostings,
    fetch_postings,
    find_board,
)
from clue_api.arv2.calls import CallCost, ProviderCaller
from clue_api.arv2.claim_writer import ClaimDraft, LenientClaimWriter, WriteReceipt
from clue_api.arv2.deepgram_media_client import DeepgramMediaClient
from clue_api.arv2.errors import ProviderHalted, RawParseError
from clue_api.arv2.exa_client import (
    ExaClient,
    deep_reasoning_body,
    is_thin_deep_response,
    report_output_schema,
)
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
    is_youtube,
    reject_native_video,
    youtube_metadata,
    youtube_words,
)
from clue_api.arv2.media_types import TranscriptSource
from clue_api.arv2.person_compliance import apply_person_floor
from clue_api.arv2.person_exa_brief import (
    person_exa_arguments,
    person_search_contents,
    uses_person_exa_brief,
)
from clue_api.arv2.provider_ledger import (
    ArtifactSink,
    BufferedLedger,
    BufferedRawSink,
    HeldDrain,
    LedgerStamp,
    drain_provider_calls,
    hold_drain,
)
from clue_api.arv2.sinks import LedgerSink
from clue_api.arv2.structuring_client import (
    UNIQUE_INSIGHT_MODE,
    AccountSubject,
    FieldCatalog,
    PersonSubject,
    SourceBlock,
    StructuringClient,
    schema_hint,
)
from clue_api.arv2.text import substring_verdict
from clue_api.arv2.transport import HttpxTransport, Transport
from clue_config import Settings
from clue_core import Claim, RunId
from clue_db import ConnFactory
from clue_obs import get_logger
from clue_research.claimstore import WorkspaceScope, claims_for_runs
from clue_storage import StorageBackend

log = get_logger("clue_api.arv2.account_research_tools")

__all__ = [
    "ACCOUNT_TOOL_NAMES",
    "EVIDENCE_RULES",
    "LOCK_TEMPLATE",
    "PERSON_LOCK_TEMPLATE",
    "PERSON_TOOL_NAMES",
    "ProviderClients",
    "SourceInput",
    "ToolRuntime",
    "WriteFailure",
    "build_account_tools",
    "build_person_tools",
    "fold_identity",
    "marked",
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

#: The eleven tools one **person** job runs on, in the order its manual lists them. Four account
#: tools are deliberately absent — ``read_account_state``, ``read_ats_board``, ``lookup_company``
#: and ``lookup_people`` belong to the account job, whose results reach this one through its
#: already-established block — and two are new: ``lookup_person`` (the identity lock plus the email
#: export) and ``unique_insight`` (the one-question pass).
PERSON_TOOL_NAMES: tuple[str, ...] = (
    "read_person_state",
    "fetch_page",
    "search_web",
    "lookup_person",
    "read_media_feeds",
    "research_deep",
    "structure_material",
    "unique_insight",
    "write_claims",
    "verify_links",
    "finalize_research",
)

#: Providers whose calls are serialised job-wide. AI Ark paces itself per client instance (a second
#: concurrent call would defeat the pacing and earn a 429), and media work is measured in minutes of
#: audio against one enforced ceiling, so two at once would race the reservation.
_SERIAL_PROVIDERS: frozenset[str] = frozenset({"ai_ark", "media"})


@dataclass
class _Dispatched:
    """One provider call's buffers and outcome, between dispatch and landing (W1-7)."""

    raw: BufferedRawSink
    ledger: BufferedLedger
    result: Any = None
    error_code: str | None = None
    error: BaseException | None = None


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

#: Characters of the "already established" block one deep call carries. The block tells Exa what
#: not to re-derive; past a few thousand characters it is the query, and the re-run's Zafran call
#: spent its budget re-reading an AI Ark record instead of researching (34k-char query vs 2.9k).
_DEEP_ESTABLISHED_MAX_CHARS = 6000


def _clip_lines(block: str, max_chars: int) -> str:
    """Whole lines from the top of ``block`` up to ``max_chars``, then one line saying how many
    were left out and where they are. A block within the cap is returned unchanged."""
    if len(block) <= max_chars:
        return block
    kept: list[str] = []
    used = 0
    lines = block.split("\n")
    for line in lines:
        if used + len(line) + 1 > max_chars:
            break
        kept.append(line)
        used += len(line) + 1
    omitted = len(lines) - len(kept)
    kept.append(
        f'… ({omitted} lines omitted; read_account_state(section="already_established") '
        "has them all)"
    )
    return "\n".join(kept)


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

#: The person constitution's §2, as the deep call's system prompt. The lock is the **employment
#: history**, not the name: two people share a name, but nobody shares a career, and same-name
#: contamination is the single recurring failure of person research. The history is stated to the
#: provider in its own words for the same reason the account lock is — left implicit in the query,
#: it is the first thing a long dossier call forgets.
PERSON_LOCK_TEMPLATE = """You research exactly ONE person and nothing else.

TARGET LOCK
  person: {name}
  title: {title}
  company: {company}
  linkedin: {linkedin}
  known roles:
{history}
Anyone with the same or a similar name whose employment history does not match this lock is a
DIFFERENT person. When you meet one, name them, give the URL, and discard them with the reason.
A company account's post about this person is a company source, not their voice. Excluded
same-name people for this run: {exclusions}."""

#: Constitution §3, as the deep call's evidence law. The sentence shape was chosen on the
#: 2026-09-08 Exa experiment: a claims-shaped output schema lifted quote fidelity to 94-95% but
#: cost two-thirds of the assertions, so asking the *report* for quote-first sentences keeps the
#: budget on coverage while still giving the structuring pass clean spans.
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
    DENIED or UNRESOLVED, by whom, with the quote.
  * One assertion per sentence: the verbatim quote first, then the URL in parentheses, then at
    most one clause of your own reading. A sentence never carries two facts, and a quote never
    supports more than the sentence it sits in.
  * A NOT FOUND item is its own sentence naming exactly what was looked for (the tool, the
    person, the number), so that absence is recorded as precisely as presence."""


class ProviderClients(Protocol):
    """The four clients a tool may use, each built around the hop's own caller.

    A client is constructed **per invocation** rather than held on the runtime, because a client
    binds to one :class:`ProviderCaller`, and one caller owns one hop's buffered raw sink and
    ledger. Sharing a client across hops would mean sharing a caller, and the ledger rows of two
    concurrent calls would drain into whichever transaction finished first.
    """

    def exa(self, caller: ProviderCaller) -> ExaClient: ...

    def ai_ark(self, caller: ProviderCaller) -> AiArkClient: ...

    def transcription(self, caller: ProviderCaller) -> DeepgramMediaClient: ...

    def media(self, caller: ProviderCaller, ledger: LedgerSink) -> GeminiMediaClient: ...

    def structuring(self, caller: ProviderCaller) -> StructuringClient: ...


@dataclass(frozen=True)
class WriteFailure:
    """One draft the claim gate would not take, reported beside the ones it did.

    It is a *result*, not an exception, because the alternative was losing a whole model-produced
    batch to one unwritable value (see :meth:`ToolRuntime.write_each`).
    """

    field_key: str
    error: str


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
        storage: StorageBackend | None = None,
        pacing_conn_factory: ConnFactory | None = None,
    ) -> None:
        self.storage = storage
        self.scope = scope
        self.person_seed: dict[str, Any] | None = None
        self.channel_states: dict[str, str] = {}
        self.settings = settings
        self.clients = clients
        self.catalog = catalog
        self.media_budget = media_budget
        self._conn_factory = conn_factory
        # Pacing holds its transaction across the hop and cooldown. It must not hold the
        # driver's serialized data-connection lock: the hop checks authority and drains
        # receipts through that same data connection before it can finish.
        self._pacing_conn_factory = pacing_conn_factory or conn_factory
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

        #: Every source block this job has structured, in the order it structured them. It is the
        #: material ``unique_insight`` asks its one question over: the pass is a *second reading*
        #: of what the job already retrieved, not a new retrieval, so it must not need the agent to
        #: paste the same pages back in. Deduplicated on append, because the manual tells the agent
        #: to resend the same material once after ``structuring_unparseable``.
        self.person_sources: list[SourceBlock] = []

        #: Every action the coded compliance pass (§5) took on this job's person claims, in order.
        #: It accumulates across every write the job makes and lands whole on the finalize receipt,
        #: so the display can say a thing was removed and why without ever showing the thing.
        self.compliance_log: list[dict[str, str]] = []

        #: Every entity this job asked the writer to write a claim about (lane 3 slice 4): the
        #: ending tags the job's trace with them, so "which traces carried contact X" is a query.
        self.entities_touched: set[str] = set()

        self._refusals: dict[str, str] = {}
        self._semaphores: dict[str, asyncio.Semaphore] = {}
        self._inflight: set[asyncio.Task[Any]] = set()
        self._ledgers: dict[int, BufferedLedger] = {}
        #: URL → page text for the link audit, so a claim set citing one page reads it once.
        self._page_cache: dict[str, str] = {}

    # -- the one path to a provider ---------------------------------------------------------------

    async def call_provider[T](
        self,
        provider: str,
        fn: Callable[[ProviderCaller], T],
        *,
        operation: operations.Operation | None = None,
    ) -> T:
        """Run one synchronous provider hop off the loop, then land its money trail.

        The hop is shielded from the awaiting tool's cancellation on purpose: the runtime cap can
        fire while a call is in flight, and a cancelled drain would lose the raw bodies and ledger
        rows of a call that already happened — the one thing money truth cannot tolerate. The
        driver waits for the survivors through :meth:`wait_for_inflight` before it finalizes.
        """
        latched = self.halted.get(provider)
        if latched is not None:
            raise RefusalError(f"provider_halted:{provider}", latched)
        hop: asyncio.Task[T] = asyncio.create_task(self._hop(provider, fn, operation))
        self._inflight.add(hop)
        hop.add_done_callback(self._forget_hop)
        return await asyncio.shield(hop)

    def _forget_hop(self, hop: asyncio.Task[Any]) -> None:
        self._inflight.discard(hop)
        if not hop.cancelled():
            # Retrieve the exception of a hop whose awaiter was cancelled, so a shielded failure is
            # never reported as an unretrieved task exception.
            hop.exception()

    async def _hop[T](
        self,
        provider: str,
        fn: Callable[[ProviderCaller], T],
        operation: operations.Operation | None = None,
    ) -> T:
        token = getattr(self.clients, "ai_ark_token_scope", None)
        if provider != "ai_ark" or not token:
            return await self._perform_hop(provider, fn, operation)
        started = asyncio.get_running_loop().time()
        gap = self.settings.arv2_ai_ark_min_gap_s
        while True:
            async with self._pacing_conn_factory() as pacing_conn:
                won = (
                    await pacing_conn.execute(
                        text("SELECT pg_try_advisory_xact_lock(hashtextextended(:token,0))"),
                        {"token": f"ai-ark:{token}"},
                    )
                ).scalar_one()
                if won:
                    log.info(
                        "arv2.provider_pacing_acquired",
                        job_id=str(self.scope.job_id),
                        provider=provider,
                        wait_ms=round((asyncio.get_running_loop().time() - started) * 1000),
                        cooldown_s=gap,
                    )
                    if self.settings.arv2_drain_outside_slot:
                        # The gap runs from the provider's answer; indexing happens inside it.
                        return await self._perform_hop(provider, fn, operation, cooldown_s=gap)
                    try:
                        return await self._perform_hop(provider, fn, operation)
                    finally:
                        await asyncio.sleep(gap)
            await asyncio.sleep(0.1)

    async def _perform_hop[T](
        self,
        provider: str,
        fn: Callable[[ProviderCaller], T],
        operation: operations.Operation | None = None,
        *,
        cooldown_s: float | None = None,
    ) -> T:
        """Dispatch under the provider's slot, then land the money trail and the evidence.

        With ``arv2_drain_outside_slot`` the slot is freed as soon as the provider answers, so the
        next call does not wait for this one's indexing (W1-7); otherwise both run inside it.
        """
        slot = self._semaphore(provider)
        await slot.acquire()
        held = True
        try:
            dispatched = await self._dispatch(provider, fn, operation)
            if self.settings.arv2_drain_outside_slot:
                slot.release()
                held = False
            if cooldown_s is None:
                await self._land(provider, dispatched, operation)
            else:
                landed, _ = await asyncio.gather(
                    self._land(provider, dispatched, operation),
                    asyncio.sleep(cooldown_s),
                    return_exceptions=True,
                )
                if isinstance(landed, BaseException):
                    raise landed
        finally:
            if held:
                slot.release()
        if dispatched.error is not None:
            raise dispatched.error
        return cast(T, dispatched.result)

    async def _dispatch[T](
        self,
        provider: str,
        fn: Callable[[ProviderCaller], T],
        operation: operations.Operation | None,
    ) -> _Dispatched:
        """Call the provider once. Never raises: the outcome, or the error, rides the result."""
        raw, ledger = BufferedRawSink(), BufferedLedger()
        transport = self._transport_factory()
        if provider == "media_public" and isinstance(transport, HttpxTransport):
            from clue_api.arv2.media_resolution import PublicMediaTransport

            transport = PublicMediaTransport()
        if provider == "media_youtube" and isinstance(transport, HttpxTransport):
            from clue_api.arv2.media_recording import YouTubeAudioTransport

            transport = YouTubeAudioTransport()
        caller = ProviderCaller(
            transport=transport,
            raw_sink=raw,
            ledger=ledger,
            now=self._now,
        )
        self._ledgers[id(caller)] = ledger
        dispatched = _Dispatched(raw=raw, ledger=ledger)
        try:
            if has_capability(self.scope.catalog_version, "committee_discovery"):
                async with self._conn_factory() as conn:
                    available = await operations.job_available(
                        conn, self.operation_scope, operation.kind if operation else None
                    )
                if not available:
                    dispatched.error_code = "privacy_stopped"
                    raise RefusalError("tool_error", "research authority was withdrawn")
            if provider in self.halted:
                dispatched.error_code = "provider_halted_pre_dispatch"
                raise RefusalError(f"provider_halted:{provider}", self.halted[provider])
            dispatched.result = await asyncio.to_thread(fn, caller)
        except ProviderHalted as halted:
            dispatched.error_code = "provider_halted"
            detail = str(halted)
            self.halted[provider] = detail
            # Latch the *wire* provider as well as the tool's label for it. One media hop can
            # spend on OpenRouter, so "OpenRouter is out of credit" learned inside a media call
            # must also stop the structuring calls, which reach the same account under their
            # own label. Money truth blocks whoever meets it first.
            self.halted.setdefault(halted.provider, detail)
            refusal = RefusalError(f"provider_halted:{provider}", detail)
            refusal.__cause__ = halted
            dispatched.error = refusal
        except BaseException as error:
            dispatched.error_code = dispatched.error_code or type(error).__name__
            dispatched.error = error
        finally:
            self._ledgers.pop(id(caller), None)
        return dispatched

    async def _land(
        self, provider: str, dispatched: _Dispatched, operation: operations.Operation | None
    ) -> None:
        """Drain one dispatched call's raw bodies and ledger rows, then index its evidence."""
        result = dispatched.result
        cost = getattr(result, "cost", None)
        await self._drain(
            dispatched.raw,
            dispatched.ledger,
            provider=provider,
            operation=operation,
            error=dispatched.error_code,
            preferred_row=getattr(cost, "ledger_row_id", None),
            semantic_empty=(
                provider == "ai_ark"
                and result is not None
                and (
                    (hasattr(result, "people") and not result.people)
                    or (hasattr(result, "numbers") and not result.numbers)
                    or (hasattr(result, "found") and not result.found)
                )
            ),
        )

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

    async def _drain(
        self,
        raw: BufferedRawSink,
        ledger: BufferedLedger,
        *,
        provider: str | None = None,
        operation: operations.Operation | None = None,
        error: str | None = None,
        preferred_row: str | None = None,
        semantic_empty: bool = False,
    ) -> None:
        # W2-20: time the money trail and the evidence indexing that follow every provider call.
        started = time.monotonic()
        drain_ms: float | None = None
        index_ms: float | None = None
        index_started: float | None = None
        early_ms: float | None = None
        stamp = LedgerStamp(
            workspace_id=self.scope.workspace_id,
            project_id=self.scope.project_id,
            project_run_id=str(self.scope.project_run_id),
            job_id=self.scope.job_id,
        )
        held: HeldDrain | None = None
        uploaded: frozenset[str] = frozenset()
        try:
            if self.settings.arv2_upload_outside_lock:
                # W2-15 option B: store the raw response and the source files BEFORE taking the
                # worker's database connection, so the lock below covers database work only.
                held = await hold_drain(
                    raw=raw, ledger=ledger, artifacts=self._artifacts, stamp=stamp
                )
                if (
                    has_capability(self.scope.catalog_version, "research_quality")
                    and self.storage is not None
                ):
                    from clue_api.arv2.quality_acquisition import upload_sources_early

                    uploaded = await upload_sources_early(
                        self._pacing_conn_factory,
                        self.storage,
                        self.operation_scope,
                        held.result_rows,
                        held.raw_artifact_keys,
                        held.raw_bodies,
                    )
                early_ms = (time.monotonic() - started) * 1000
            async with self._conn_factory() as conn:
                report = await drain_provider_calls(
                    conn,
                    raw=raw,
                    ledger=ledger,
                    artifacts=self._artifacts,
                    stamp=stamp,
                    held=held,
                )

                if (
                    has_capability(self.scope.catalog_version, "committee_discovery")
                    and self.storage is not None
                ):
                    # Register every attempt, including unselected people and unsuccessful
                    # responses.
                    from clue_api.arv2.committee_discovery import index_provider_artifacts

                    await index_provider_artifacts(
                        self, conn, report.raw_artifact_keys.values(), report.raw_bodies
                    )
                if has_capability(
                    self.scope.catalog_version, "committee_discovery"
                ) and not await operations.job_available(
                    conn, self.operation_scope, operation.kind if operation else None
                ):
                    await conn.execute(
                        text(
                            "UPDATE artifact SET "
                            "privacy_erased=true,erasure_reason='privacy',"
                            "erased_at=now(),source_url=NULL WHERE "
                            "workspace_id=:ws AND storage_key=ANY(:keys)"
                        ),
                        {
                            "ws": self.scope.workspace_id,
                            "keys": list(report.raw_artifact_keys.values()),
                        },
                    )
                if has_capability(self.scope.catalog_version, "media_research"):
                    from clue_api.arv2.media_operations import attach_receipts
                    from clue_api.arv2.provider_ledger import ledger_id_for

                    if operation is not None and operation.kind == "media_discovery":
                        from clue_api.arv2.media_store import subjects

                        for key in report.raw_artifact_keys.values():
                            await subjects(self, conn, key, [])
                    await attach_receipts(
                        self,
                        conn,
                        list(report.raw_artifact_keys.values()),
                        [ledger_id_for(r.row_id) for r in report.result_rows],
                        error,
                    )
                if operation is not None:
                    await operations.finish(
                        conn,
                        self.operation_scope,
                        operation,
                        report.result_rows,
                        error=error,
                        preferred_row=preferred_row,
                        semantic_empty=semantic_empty,
                    )
            drain_ms = (time.monotonic() - started) * 1000
            # A failed evidence normalization must never roll back the paid provider ledger.
            # The separate transaction still completes before a source handle reaches an agent.
            index_started = time.monotonic()
            if has_capability(self.scope.catalog_version, "research_quality"):
                async with self._conn_factory() as conn:
                    from clue_api.arv2.quality_acquisition import index_acquisition

                    if self.storage is None:
                        raise RuntimeError("quality research requires durable source storage")
                    if not await operations.job_available(conn, self.operation_scope):
                        return
                    await index_acquisition(
                        conn,
                        self.storage,
                        self.operation_scope,
                        report,
                        operation_id=operation.operation_id if operation else None,
                        uploaded=uploaded,
                    )
        finally:
            finished = time.monotonic()
            if index_started is not None:
                index_ms = (finished - index_started) * 1000
            log.info(
                "arv2.drain_completed",
                job_id=str(self.scope.job_id),
                provider=provider,
                operation=operation.kind if operation else None,
                early_ms=None if early_ms is None else round(early_ms, 1),
                drain_ms=None if drain_ms is None else round(drain_ms, 1),
                index_ms=None if index_ms is None else round(index_ms, 1),
                total_ms=round((finished - started) * 1000, 1),
            )

    @property
    def operation_scope(self) -> operations.OperationScope:
        return operations.OperationScope(
            self.scope.workspace_id,
            self.scope.run_id,
            self.scope.job_id,
            UUID(str(self.scope.account_id)),
        )

    async def operate(
        self,
        provider: str,
        kind: str,
        request: Mapping[str, Any],
        fn: Callable[[ProviderCaller], Any],
    ) -> tuple[operations.Operation, dict[str, Any]]:
        if self.storage is None:
            raise RuntimeError("v2 research requires verified artifact storage")
        async with self._conn_factory() as conn:
            operation, won = await operations.begin(conn, self.operation_scope, kind, request)
        if won:
            if provider in self.halted:
                async with self._conn_factory() as conn:
                    await operations.finish(
                        conn,
                        self.operation_scope,
                        operation,
                        (),
                        error="provider_halted_pre_dispatch",
                    )
                raise RefusalError(f"provider_halted:{provider}", self.halted[provider])
            await self.call_provider(provider, fn, operation=operation)
        async with self._conn_factory() as conn:
            # W2-17: a call that won its operation has just indexed its own result, so the check
            # only runs on a replay (or when the setting asks); the job's settle runs it once.
            if has_capability(self.scope.catalog_version, "research_quality") and (
                not won or self.settings.arv2_recover_on_success
            ):
                from clue_api.arv2.quality_acquisition import recover_acquisitions

                started = time.monotonic()
                await recover_acquisitions(conn, self.storage, self.operation_scope)
                log.info(
                    "arv2.acquisition_recovered",
                    job_id=str(self.scope.job_id),
                    operation=kind,
                    replayed=not won,
                    recover_ms=round((time.monotonic() - started) * 1000, 1),
                )
            return await operations.body(
                conn, self.storage, self.operation_scope, operation.operation_id
            )

    # -- the one path to a claim ------------------------------------------------------------------

    def compliance_pass(self, drafts: Sequence[ClaimDraft]) -> list[ClaimDraft]:
        """The §5 floor, at the one place every person claim passes: just before it is written.

        Account jobs never run it — the floor is about a *person*, and an account claim has no
        subject it could be personal about. For a person job it is unconditional: both write paths
        go through here, so there is no way for a tool to reach the store around it.
        """
        if self.scope.subject_kind != "person":
            return list(drafts)
        kept, actions = apply_person_floor(
            drafts, purge_unevidenced=self.settings.unevidenced_row_purge_enabled
        )
        self.compliance_log.extend(actions)
        return kept

    async def write(self, drafts: Sequence[ClaimDraft]) -> list[WriteReceipt]:
        """Write every draft through the lenient gate, in one transaction."""
        drafts = self.compliance_pass(drafts)
        if not drafts:
            return []
        # Recorded before the write, exactly as ``write_each`` does: a provider-built batch names
        # people too (``lookup_people``), and erasure has to find them whether the store took them
        # or the transaction rolled back.
        self.entities_touched.update(str(draft.entity_id) for draft in drafts)
        async with self._conn_factory() as conn:
            if has_capability(self.scope.catalog_version, "media_research"):
                from clue_api.arv2.media_claims import guard_draft

                drafts = [await guard_draft(self, conn, draft) for draft in drafts]
            return [await self._writer.write(conn, draft) for draft in drafts]

    async def write_each(
        self, drafts: Sequence[ClaimDraft]
    ) -> list[tuple[ClaimDraft, WriteReceipt | WriteFailure]]:
        """Write every draft in a transaction of its own, and report the ones that failed.

        :meth:`write` is one transaction for the batch, which is right for a batch the *code*
        built (an ATS board, a provider record): those drafts stand or fall together. It is wrong
        for a batch a **model** produced. One unwritable value there — a key the registry refuses,
        a value the store rejects — aborts the transaction and takes every other claim in the call
        with it, so a run loses fifteen good claims to one bad one and the model is told only that
        the tool errored.

        Here each draft gets its own transaction, and a failure becomes a :class:`WriteFailure` in
        the result rather than an exception: the model sees exactly which field did not land, and
        the rest of the batch is already written.

        Each result carries **the draft it belongs to**, because the batch that comes out is not
        always the batch that went in: on a person job the compliance floor
        (:meth:`compliance_pass`) drops and rewrites drafts before any of them is written, so a
        caller must never pair a result with an input by position.
        """
        results: list[tuple[ClaimDraft, WriteReceipt | WriteFailure]] = []
        for draft in self.compliance_pass(drafts):
            # Recorded before the write, not after: a draft the store refuses is still an entity
            # this job worked on, and the trace should say so.
            self.entities_touched.add(str(draft.entity_id))
            try:
                async with self._conn_factory() as conn:
                    if has_capability(self.scope.catalog_version, "media_research"):
                        from clue_api.arv2.media_claims import guard_draft

                        draft = await guard_draft(self, conn, draft)
                    results.append((draft, await self._writer.write(conn, draft)))
            except Exception as error:  # noqa: BLE001 — one draft's failure is a row, never a stop
                log.warning("arv2.claim_write_failed", field_key=draft.field_key, error=str(error))
                results.append(
                    (draft, WriteFailure(field_key=draft.field_key, error=str(error)[:300]))
                )
        return results

    async def job_claims(self) -> Sequence[Claim]:
        """This job's own claims: written by this run, about this job's subject.

        The subject is the account on an account job and the person on a person job — the same
        entity ``account_research_claims._draft`` stamps every draft to — so the state reader, the
        media cap and the link audit all see exactly the claims this job wrote and no others.
        """
        subject = self.scope.person_subject_id or self.scope.account_id
        async with self._conn_factory() as conn:
            claims = await claims_for_runs(
                conn,
                [RunId(self.scope.run_id)],
                scope=WorkspaceScope.for_workspace(self.scope.workspace_id),
            )
        return [claim for claim in claims if claim.entity_id == subject]

    async def resolve_contact(self, name: str) -> UUID | None:
        """The contact under this job's account that ``name`` resolves to, or ``None``."""
        async with self._conn_factory() as conn:
            return await find_contact_by_name(
                conn,
                workspace_id=self.scope.workspace_id,
                account_id=UUID(str(self.scope.account_id)),
                name=name,
            )

    def remember_sources(self, blocks: Sequence[SourceBlock]) -> None:
        """Add this call's material to what ``unique_insight`` will read, without duplicates."""
        seen = {(block.url, block.kind, block.text) for block in self.person_sources}
        for block in blocks:
            key = (block.url, block.kind, block.text)
            if key not in seen:
                seen.add(key)
                self.person_sources.append(block)

    async def record_link_audit(self, rows: Sequence[AnnotationRow]) -> int:
        """Write one link-audit annotation per claim — verdict *and* the reason behind it. An
        annotation is a check result beside the claim, never an edit to append-only history."""
        async with self._conn_factory() as conn:
            return await record_annotations(conn, job_id=self.scope.job_id, rows=rows)

    async def stamp_stage(self, stage: JobStage) -> None:
        """Say where the job is (spec 2026-09-12 §1), and never let that cost the job.

        The stamp is a progress pixel: the card reads it and nothing else does. Every tool body
        runs under a wrapper that turns ANY exception into ``tool_error``, so an unguarded
        ``UPDATE`` here — a pool timeout, a lock wait, a statement timeout — would be reported to
        the model as a failed finalization and could leave the job short or in ``needs_review``.
        A display column is never worth that, so the failure is logged and swallowed.
        """
        try:
            async with self._conn_factory() as conn:
                await set_job_stage(conn, job_id=self.scope.job_id, stage=stage)
        except Exception as error:  # noqa: BLE001 — a progress pixel never costs a finalization
            log.warning(
                "arv2.stage_stamp_failed",
                job_id=str(self.scope.job_id),
                stage=stage,
                error=str(error),
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


def _receipt_json(
    receipt: WriteReceipt, draft: ClaimDraft, catalog: FieldCatalog
) -> dict[str, Any]:
    row: dict[str, Any] = {
        "claim_id": str(receipt.claim_id),
        "field_key": receipt.field_key,
        "value": draft.value_json,
        "quote": draft.evidence_span,
        "url": draft.source_url,
        "priority": draft.signal_priority,
        "outreach_safe": draft.outreach_safe,
        "markers": receipt.markers,
    }
    if receipt.markers.get("schema_valid") is False:
        # The claim is stored and visible with its marker (founder ruling 2026-09-08); the receipt
        # is the one place the model learns, in the same turn, what shape the field wanted.
        spec = catalog.spec(receipt.field_key)
        if spec is None:
            # This job's catalog is account-only, but ``write_claims`` admits any registered key,
            # so a contact field can fail its DB schema here. Saying "any" would be a lie about a
            # value that just failed a schema; the honest answer is that we cannot see the shape.
            row["expected_shape"] = "not in this job's catalog"
        else:
            row["expected_shape"] = schema_hint(spec.value_schema)
            row["hint"] = (
                "rewrite the value in this shape and write it again with "
                f"corrects_claim_id={receipt.claim_id}"
            )
    return row


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
    section: Literal[
        "all", "claims", "open_fields", "icp", "persona", "already_established", "media"
    ] = "all"


class ReadPersonStateArgs(_Args):
    section: Literal[
        "all", "claims", "open_fields", "icp", "persona", "already_established", "lock", "media"
    ] = "all"


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


class LookupPersonArgs(_Args):
    """The one argument the person lookup takes: whose LinkedIn page this is.

    The name to search and the account to scope the search to are the **job's**, not the model's:
    a person job exists for exactly one person at exactly one account, and letting the call name a
    different one would be a second, competing lock. The URL is what the record is matched against,
    because it is the identity the committee step confirmed the person on.
    """

    linkedin_url: str = Field(min_length=4)


class UniqueInsightArgs(_Args):
    """``subject`` is the person the caller believes it is asking about.

    It is recorded and echoed back, and it decides nothing: the subject of the call is the job's
    locked person, so a name variant here can never repoint the pass at somebody else. The argument
    exists because the manual and the dossier skill both call the tool ``unique_insight(subject)``,
    and a closed schema without it would refuse the call the skills instruct.
    """

    subject: str | None = None


class ReadMediaFeedsArgs(_Args):
    person_name: str = Field(min_length=2)
    person_role: str = ""
    feed_url: HttpUrl | None = None
    youtube_url: HttpUrl | None = None
    #: More places the same appearance may load from — the podcast's other feed host, the
    #: YouTube upload of the episode — tried in order only when the source before it would not
    #: load. Each is a feed or a watch URL, told apart by host. Two runs produced no media because
    #: one 429 and one dead feed were each the only URL the call carried.
    alternate_urls: list[HttpUrl] = Field(default_factory=list, max_length=4)
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


class AccountResearchDeepArgs(_Args):
    charter: str = Field(
        min_length=200,
        description="Self-contained Exa assignment, including account-specific probes once.",
    )
    same_name_exclusions: list[str] = Field(default_factory=list)
    additional_queries: list[str] = Field(
        default_factory=list,
        max_length=10,
        description="Complementary searches from this account's brief and known leads; usually 3–5."
        " Use names only when known. These guide the same Exa call, not separate deep calls.",
    )
    num_results: int = Field(40, ge=10, le=40)


class PersonResearchDeepArgs(_Args):
    charter: str = Field(
        min_length=200,
        description="Self-contained person assignment with explicit charter subquestions and "
        "acquired leads, or concrete questions for a substantial follow-up investigation.",
    )
    additional_queries: list[str] = Field(
        default_factory=list,
        max_length=10,
        description="Complementary person-specific searches, including earlier career and "
        "personal interests where useful. These complement actual preliminary search calls.",
    )
    highlights_query: str = Field(default="", description="Optional targeted excerpt emphasis.")
    same_name_exclusions: list[str] = Field(default_factory=list)
    num_results: int = Field(20, ge=1, le=40)


class SourceInput(_Args):
    """One retrieved thing, with the URL it came from.

    ``text`` is the material as retrieved; it is never the model's summary of it, because a
    summary quoted verbatim is a quote of the model, not of the source.
    """

    url: HttpUrl | None = None
    kind: Literal["page", "posting", "report", "transcript", "provider"] = "page"
    text: str = Field(min_length=20, max_length=60_000)
    title: str | None = None


class _StructureMaterialFields(_Args):
    """One structuring call's arguments.

    The free ``material`` string this used to take is **gone**, deliberately and breakingly: one
    string held the evidence and the caller's own framing together, so the model could quote the
    framing as a verbatim span and the claim then cited whichever URL was nearest. Sources carry
    their URLs; ``notes`` is the framing, and nothing in it may ever be quoted.
    """

    subject_kind: Literal["account", "person"]
    subject_name: str = Field(min_length=2)
    subject_domain_or_company: str = Field(min_length=2)
    linkedin_url: str | None = None
    notes: str | None = None
    mode: Literal["broad", "intent_sweep"] = "broad"
    already_known: str | None = None


class StructureMaterialArgs(_StructureMaterialFields):
    sources: list[SourceInput] = Field(min_length=1, max_length=12)


class WriteClaimsArgs(_Args):
    claims: list[ClaimInput] = Field(min_length=1, max_length=50)


class MediaStructureMaterialArgs(_StructureMaterialFields):
    sources: list[SourceInput | TranscriptSource] = Field(min_length=1, max_length=12)


class MediaClaimInput(ClaimInput):
    transcript_source: TranscriptSource | None = None


class MediaWriteClaimsArgs(_Args):
    claims: list[MediaClaimInput] = Field(min_length=1, max_length=50)


class VerifyLinksArgs(_Args):
    claim_ids: list[str] | None = None


class FitVerdict(_Args):
    gate: str = Field(min_length=1)
    verdict: Literal["pass", "likely", "unclear", "fail"]
    rationale: str = Field(min_length=1)
    claim_ids: list[str] = Field(default_factory=list)


class CommitteeCandidate(_Args):
    """One seat on the buying committee, as the account agent resolved it.

    ``rationale`` and ``influence`` are optional and are the *why* behind the seat: the mapper
    writes them into the member's own ``contact.role_on_committee`` claim, which is what the
    contact page's "why they matter" reads. Absent, the claim carries the role alone and the page
    falls back to its default line — an honest empty, never an invention.
    """

    name: str | None = None
    title: str | None = None
    persona: Literal["economic_buyer", "champion", "user", "technical_evaluator", "blocker"]
    linkedin_url: str | None = None
    confirmed_by: str | None = None
    vacant_seat: bool = False
    evidence_span: str | None = None
    rationale: str | None = None
    influence: Literal["High", "Medium", "Low"] | None = None
    evidence_kind: Literal["provider_candidate", "web_candidate", "unfilled_role"] = "web_candidate"
    candidate_ref: str | None = None
    role_key: str | None = None
    gap_reason: str | None = None


class FinalizeResearchArgs(_Args):
    summary: str = Field(min_length=20)
    fit_verdicts: list[FitVerdict] = Field(default_factory=list)
    gaps: list[str] = Field(default_factory=list)
    committee_candidates: list[CommitteeCandidate] = Field(default_factory=list)


class Opener(_Args):
    """One grounded opener: the sentence, the hook it rests on, and the evidence behind it."""

    text: str = Field(min_length=1)
    hook: str = ""
    #: The verbatim quote the hook rests on. An opener without one is **dropped** at finalization
    #: (dossier skill §3) rather than written unevidenced, and named in the receipt.
    quote: str = ""
    url: str | None = None


class SameNameEntry(_Args):
    """One same-name person met and discarded — the row that proves the identity lock held."""

    name_or_url: str = Field(min_length=1)
    why_excluded: str = Field(min_length=1)


class ReportsTo(_Args):
    """Who this person reports to, admitted only from an ATS reporting line or their own words.

    ``quote`` and ``url`` are what make the claim admissible at all (founder ruling 2026-09-09);
    without both, the reporting line is not written and the receipt says so. ``contact_id`` is the
    registered field's *required* key — the agent rarely knows it, so ``finalize_research``
    resolves the name against the account's own contacts when it is absent.
    """

    name: str = Field(min_length=1)
    contact_id: str | None = None
    quote: str = ""
    url: str | None = None


class FinalizePersonResearchArgs(_Args):
    """The person receipt. No fit verdicts and no committee candidates: constitution rule 11 gives
    both to the account job, and a schema that admitted them would invite the person job to
    re-decide the account's ICP from one employee's material."""

    summary: str = Field(min_length=20)
    openers: list[Opener] = Field(default_factory=list)
    hooks: list[str] = Field(default_factory=list)
    not_found: list[str] = Field(default_factory=list)
    same_name_log: list[SameNameEntry] = Field(default_factory=list)
    reports_to: ReportsTo | None = None
    gaps: list[str] = Field(default_factory=list)


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
    if has_capability(scope.catalog_version, "media_research"):
        from clue_api.arv2.media_store import state as media_state

        async with runtime._conn_factory() as conn:
            state["media"] = await media_state(runtime, conn)
    if args.section == "all":
        return state
    return {args.section: state[args.section]}


async def _read_person_state(runtime: ToolRuntime, args: ReadPersonStateArgs) -> dict[str, Any]:
    """What this job knows about its person, in the sections ``read_account_state`` serves.

    The one section the account reader has no equivalent of is ``lock``: the name, title, LinkedIn
    URL and verified employment history that rule out every same-name person. It is served on
    demand for the same reason the ICP is — the lock arrives in the system prompt, and a long job
    is exactly where a model stops re-reading its own preamble.
    """
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
        "lock": {
            "person_name": scope.person_name,
            "person_title": scope.person_title,
            "person_linkedin_url": scope.person_linkedin_url,
            "contact_id": str(scope.contact_id) if scope.contact_id else None,
            "employment_history": list(scope.employment_history),
        },
    }
    if has_capability(scope.catalog_version, "committee_discovery"):
        async with runtime._conn_factory() as conn:
            state["channels"] = await operations.operation_states(conn, runtime.operation_scope)
        state["channels"].update(runtime.channel_states)
        state["profile_seed"] = runtime.person_seed
    if has_capability(scope.catalog_version, "media_research"):
        from clue_api.arv2.media_store import state as media_state

        async with runtime._conn_factory() as conn:
            state["media"] = await media_state(runtime, conn)
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

    drafts = ats_posting_claims(postings, runtime.scope)
    if has_capability(runtime.scope.catalog_version, "research_quality"):
        from clue_api.arv2.provider_ledger import ledger_id_for

        drafts = [
            replace(
                d,
                markers={
                    **d.markers,
                    "quality_ledger_id": str(ledger_id_for(postings.ledger_row_id)),
                    "quality_board": {
                        "kind": postings.board.kind,
                        "slug": postings.board.slug,
                        "source_url": postings.board.source_url,
                    },
                },
            )
            for d in drafts
        ]
    receipts = await runtime.write(drafts)
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

    if uses_person_exa_brief(runtime.scope) or uses_account_discovery(runtime.scope):
        from clue_api.arv2.exa_client import contents_body

        kwargs: dict[str, Any] = {"text_max_chars": args.max_chars}
        if uses_person_exa_brief(runtime.scope):
            kwargs["extras"] = person_search_contents()["extras"]
        operation, raw = await runtime.operate(
            "exa",
            "person_page" if uses_person_exa_brief(runtime.scope) else "account_page",
            contents_body([url], **kwargs),
            lambda caller: runtime.clients.exa(caller).contents([url], **kwargs),
        )
        return {
            "result_ref": str(operation.operation_id),
            "results": raw.get("results", []),
            "statuses": raw.get("statuses", []),
        }

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
    if uses_person_exa_brief(runtime.scope) or uses_account_discovery(runtime.scope):
        from clue_api.arv2.exa_client import search_body

        kwargs: dict[str, Any] = {
            "num_results": args.num_results,
            "include_domains": args.include_domains,
            "start_published_date": args.start_published_date,
        }
        if uses_person_exa_brief(runtime.scope):
            contents = person_search_contents()
            kwargs.update(
                text_max_chars=contents["text"]["maxCharacters"], extras=contents["extras"]
            )
        operation, raw = await runtime.operate(
            "exa",
            "person_search" if uses_person_exa_brief(runtime.scope) else "account_search",
            search_body(args.query, **kwargs),
            lambda caller: runtime.clients.exa(caller).search(
                args.query,
                **kwargs,
                label="exa-search"
                if uses_person_exa_brief(runtime.scope)
                else f"search-{runtime.scope.account_domain}",
            ),
        )
        return {"result_ref": str(operation.operation_id), "n_results": len(raw.get("results", []))}

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
    if has_capability(runtime.scope.catalog_version, "committee_discovery"):
        from clue_api.arv2.committee_discovery import company_lock

        return await company_lock(runtime)

    def hop(caller: ProviderCaller) -> Any:
        return runtime.clients.ai_ark(caller).company_by_domain(args.domain)

    company = await runtime.call_provider("ai_ark", hop)
    if company is None:
        raise RefusalError("company_not_found", f"AI Ark holds no record for {args.domain}")

    receipts = await runtime.write(
        ai_ark_company_claims(company, runtime.scope, catalog=runtime.catalog)
    )
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
        # ``financial.funding`` is the record's own funding block. The two *amounts* it states are
        # claimed in code (``account.total_funding`` / ``account.recent_funding``); the rest —
        # investors, round dates, round count — has no registered home, so the whole block is still
        # returned as context and the agent quotes it into a claim with the evidence it finds
        # elsewhere.
        "funding": enrichment_only(funding) if isinstance(funding, Mapping) else None,
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
                "linkedin_url": person.linkedin_url,
                "current_company": person.current_company,
                "current_company_domain": person.current_company_domain,
            }
            for person in people.people
        ],
        "cost": _cost_json(people.cost),
    }


def fold_identity(value: str) -> str:
    """The form two URLs or two domains are compared in: lower-case, no scheme, no ``www.``, no
    trailing slash.

    One helper for both, because the two comparisons the person lock makes — "is this the LinkedIn
    page the committee confirmed?" and "is this employer the account?" — differ only in what they
    are handed. ``https://WWW.LinkedIn.com/in/Nick/`` and ``linkedin.com/in/nick`` are the same
    page; ``www.probook.ai`` and ``probook.ai`` are the same company. Nothing else is folded: a
    different path is a different person, and a different domain is a different employer.
    """
    folded = value.strip().lower().rstrip("/")
    for scheme in ("https://", "http://"):
        folded = folded.removeprefix(scheme)
    return folded.removeprefix("www.")


def marked(draft: ClaimDraft, markers: Mapping[str, Any]) -> ClaimDraft:
    """One draft with extra markers folded in. No markers is the draft itself, untouched.

    Public because the repair script writes the same claims outside this module and must stamp them
    the way the tool does — one helper rather than a second spelling that can drift.
    """
    return replace(draft, markers={**draft.markers, **markers}) if markers else draft


async def _lookup_person(runtime: ToolRuntime, args: LookupPersonArgs) -> dict[str, Any]:
    """One provider record for this job's person, their email export, and the claims behind both.

    Three locks, in order, and none is a scored match (law 10):

    1. **The argument against the job.** The URL the record is matched on must be the URL the
       *committee step* confirmed (``scope.person_linkedin_url``), not merely the one the model
       typed. Without this the model's argument is the whole identity, and a same-name colleague
       at the same company would pass the other two locks and be written onto this contact. The
       check runs before the provider hop, so a mismatched call also costs nothing.

       A job carrying **no** confirmed URL has no anchor at all, so all three locks are refused
       together: lock 2 would match whatever candidate carries the URL the model typed, and lock 3
       passes for every colleague at this account. The three locks below therefore run **only for
       URL-anchored jobs**, and a job without one gets ``subject_lock_failed`` before the hop
       rather than a lookup that reads locked and is not. The person dossier's rung 2 already tells
       the agent to skip the call and say so in ``not_found`` when the lock carries no URL.
    2. **The LinkedIn URL.** The name-scoped search returns up to three candidates; the one this
       job is about is the one whose ``linkedin_url`` folds equal to that URL. No candidate
       matching is ``subject_lock_failed``, and the refusal names the companies the candidates
       *do* work for, so the agent can log them as lookalikes rather than guess why the call
       failed.
    3. **The employer, as corroboration.** A record with the right LinkedIn URL whose
       ``current_company_domain`` is a *different* company than this account is the same person at
       another employer — the account job's committee is stale, and researching them here would
       file another company's employee under this account. That is ``subject_lock_failed`` too,
       and it names both domains. An employer the record cannot state (no domain at all) is a
       different answer: the identity is already anchored on the confirmed URL, so the lookup
       **proceeds** and every claim it writes carries ``employer_unverified`` — an unstated fact is
       recorded as unstated, never read as a contradiction. The live Cogent records were refused
       here for a spelling of the employer's name, and three confirmed members lost their whole
       lookup to it.

    Only past all three locks is the email export bought. An export that finds nothing is a
    **result**, never a refusal: no mailbox is a fact about the mailbox, and the member is still
    researched.

    The record's own claims are written **before** the export hop, not after: the export is a
    second paid call that can fail on transport, and losing the title, headline, location, badges
    and career history to it would send the model back to re-buy the name search for facts this
    call already had.
    """
    if has_capability(runtime.scope.catalog_version, "committee_discovery"):
        from clue_api.arv2.committee_discovery import lookup_bound_person

        return await lookup_bound_person(runtime, args)
    scope = runtime.scope
    wanted = fold_identity(args.linkedin_url)
    locked = fold_identity(scope.person_linkedin_url or "")
    if not locked:
        raise RefusalError(
            "subject_lock_failed",
            f"this job carries no confirmed LinkedIn URL for {scope.person_name}, so no provider "
            "record can be locked to them; skip the lookup and say so in not_found",
        )
    if wanted != locked:
        raise RefusalError(
            "subject_lock_failed",
            f"this job is locked to {scope.person_linkedin_url}, and the call asked for "
            f"{args.linkedin_url}. Look up the person this job is about, or record the other "
            "one as a same-name lookalike.",
        )

    def hop(caller: ProviderCaller) -> Any:
        return runtime.clients.ai_ark(caller).people_by_name(
            [scope.person_name], scope.account_domain, size=3
        )

    people = await runtime.call_provider("ai_ark", hop)
    record = next(
        (
            person
            for person in people.people
            if person.linkedin_url and fold_identity(person.linkedin_url) == wanted
        ),
        None,
    )
    if record is None:
        companies = [
            f"{person.full_name or '?'} at {person.current_company or 'an unnamed company'}"
            for person in people.people
        ] or ["nobody at all"]
        raise RefusalError(
            "subject_lock_failed",
            f"no candidate for {scope.person_name!r} at {scope.account_domain} carries the "
            f"LinkedIn URL {args.linkedin_url}; the provider returned {companies}",
        )
    employer = fold_identity(record.current_company_domain or "")
    account_domain = fold_identity(scope.account_domain)
    if employer and employer != account_domain:
        raise RefusalError(
            "subject_lock_failed",
            f"the record for {args.linkedin_url} says this person's current employer is "
            f"{employer}, and this job's account is {account_domain}",
        )
    # An employer the record does not state is unknown, not wrong. The claims are still written,
    # and they say so themselves rather than leaving a reader to assume the domain was checked.
    employer_verified = bool(employer)
    unverified: Mapping[str, Any] = {} if employer_verified else {"employer_unverified": True}

    # The record's own claims first, before a second paid call can fail: one transaction per draft,
    # because the record's fields are independent facts and a value the store will not take must
    # cost its own claim rather than the whole lookup.
    floor_from = len(runtime.compliance_log)
    results = await runtime.write_each(
        [marked(draft, unverified) for draft in ai_ark_person_claims(record, scope)]
    )

    def export(caller: ProviderCaller) -> Any:
        return runtime.clients.ai_ark(caller).export_email(args.linkedin_url)

    exported = await runtime.call_provider("ai_ark", export)
    email_draft = email_export_claim(exported, scope)
    if email_draft is not None:
        results.extend(await runtime.write_each([marked(email_draft, unverified)]))
    return {
        "person": {
            "full_name": record.full_name,
            "title": record.title,
            "linkedin_url": record.linkedin_url,
            "current_company": record.current_company,
            "current_company_domain": record.current_company_domain,
        },
        # Whether the third lock corroborated the employer or the record simply did not state it.
        # The claims carry the same fact as a marker, so a reader of either surface knows which.
        "employer_verified": employer_verified,
        "email": (
            {
                "address": exported.address,
                "verdict": exported.verdict,
                "status": exported.status,
                "domain_type": exported.domain_type,
            }
            if exported.found and exported.address
            else None
        ),
        # A result field, never a refusal: the manual's row says the member is still researched.
        "email_export_empty": not (exported.found and exported.address),
        "written": [
            _receipt_json(result, draft, runtime.catalog)
            for draft, result in results
            if isinstance(result, WriteReceipt)
        ],
        "write_failures": [
            {"field_key": result.field_key, "error": result.error}
            for _, result in results
            if isinstance(result, WriteFailure)
        ],
        # What the compliance floor did to THIS call's drafts. Without it an empty ``written``
        # reads the same whether the record answered nothing or the floor removed what it did
        # answer, and the model cannot tell a gap from a rule.
        "compliance": runtime.compliance_log[floor_from:],
        "cost": [_cost_json(cost) for cost in (people.cost, exported.cost) if cost is not None],
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


def _discard_audio(path: Path) -> None:
    """Delete a downloaded episode, then its job folder if that left it empty."""
    path.unlink(missing_ok=True)
    with contextlib.suppress(OSError):
        path.parent.rmdir()


def _podcast_hop(
    runtime: ToolRuntime, args: ReadMediaFeedsArgs, feed_url: str
) -> Callable[[ProviderCaller], _MediaItem]:
    """The whole podcast chain as one synchronous hop: feed → episode → audio → words → quotes.

    The feed to read is passed in, not taken off ``args``: one call may carry several candidate
    sources and the caller decides which one this hop is for.
    """
    scope = runtime.scope
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
        # The audio is only transcription's input — the transcript and quotes are what is kept —
        # so it never outlives the hop, whatever happens in between (a fleet worker's disk
        # would otherwise gain an episode per lookup, forever).
        try:
            transcribable = transcription_input_from_enclosure(
                audio, display_name=_safe_name(f"{args.person_name}-{episode.title}")
            )
            named = (
                args.person_name.lower() in f"{episode.title} {episode.description or ''}".lower()
            )
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
                mined = media.mine_quotes(
                    transcript.text, context=context, n=6, speaker_verified=True
                )
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
        finally:
            _discard_audio(audio.path)

    return hop


def _youtube_hop(
    runtime: ToolRuntime, args: ReadMediaFeedsArgs, watch_url: str
) -> Callable[[ProviderCaller], _MediaItem]:
    """The words path: metadata plus an indexed copy of the page. Nothing is transcribed.

    The watch page is passed in for the same reason the feed is: the caller owns the candidate
    order, the hop owns one URL.
    """

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


def _attempts_note(attempts: Sequence[Mapping[str, str]]) -> str:
    return "; ".join(f"{attempt['url']} ({attempt['error']})" for attempt in attempts)


def _with_attempts(detail: str, attempts: Sequence[Mapping[str, str]]) -> str:
    """Fold the sources that would not load into a refusal a *later* candidate raised.

    Without this the agent learns only that candidate N answered, never that candidates 1..N-1
    were dead — so it hands a dead URL straight back on the next call and pays for it again.
    """
    if not attempts:
        return detail
    return f"{detail}; earlier sources that would not load: {_attempts_note(attempts)}"


async def _read_media_feeds(runtime: ToolRuntime, args: ReadMediaFeedsArgs) -> dict[str, Any]:
    if runtime.scope.subject_kind == "person":
        # The per-person item cap, counted off the claims this job actually wrote rather than off a
        # counter in memory, so a resumed job cannot re-buy the items it already has. It is checked
        # *before* any source is chosen: media is the most expensive thing in the job, and a cap of
        # zero (media off for this workspace) must cost nothing at all.
        cap = runtime.settings.arv2_person_media_max_items
        held = sum(
            1 for claim in await runtime.job_claims() if claim.field_key == PUBLIC_APPEARANCES_FIELD
        )
        if held >= cap:
            raise RefusalError(
                "media_cap_reached",
                f"{runtime.scope.person_name} already has {held} media item(s) and the configured "
                f"cap is {cap}",
            )
    # The primary first (feed before watch page when both are given: a transcript beats indexed
    # page words), then the alternates in the order the model gave them. A source that will not
    # LOAD hands over to the next; a source that loaded and answered (no matching episode, over
    # the ceiling, a walled host) is the answer, and is not second-guessed by trying another URL.
    candidates = [str(url) for url in (args.feed_url, args.youtube_url) if url is not None]
    candidates.extend(str(url) for url in args.alternate_urls)
    # One URL is one candidate: a model that hands the primary back in alternate_urls pays one
    # fetch and one ledger row, not two. Order is the model's, first mention wins.
    candidates = list(dict.fromkeys(candidates))
    attempts: list[dict[str, str]] = []
    item: _MediaItem | None = None
    for url in candidates:
        try:
            # Before the hop is even chosen, so a walled host is refused with no request built no
            # matter which argument carried it (media_feeds_client's law-11 clause: the direction
            # to be wrong in is "refused something fetchable", never "fetched something walled").
            reject_native_video(url)
            hop = (
                _youtube_hop(runtime, args, url)
                if is_youtube(url)
                else _podcast_hop(runtime, args, url)
            )
            item = await runtime.call_provider("media", hop)
            break
        except MediaCeilingExceeded as ceiling:
            raise RefusalError(
                "media_ceiling_reached", _with_attempts(str(ceiling), attempts)
            ) from ceiling
        except EnclosureTooLarge as oversized:
            raise RefusalError(
                "enclosure_too_large", _with_attempts(str(oversized), attempts)
            ) from oversized
        except UnsupportedMediaHost as walled:
            raise RefusalError(
                "native_video_rejected", _with_attempts(str(walled), attempts)
            ) from walled
        except RefusalError as answered:
            # A refusal from inside the hop (episode_not_found, provider_halted:media) is this
            # source's *answer*, so the loop still stops here — but the earlier sources that would
            # not load ride along, or the agent hands a dead URL straight back next call.
            raise RefusalError(
                answered.refusal.code, _with_attempts(answered.refusal.detail, attempts)
            ) from answered
        except (MediaFetchError, RawParseError) as unreachable:
            attempts.append({"url": url, "error": str(unreachable)})
    if item is None:
        raise RefusalError("feed_not_found", "no source loaded: " + _attempts_note(attempts))

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
                title=item.title,
                catalog=runtime.catalog,
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
        # The sources that would not load before this one did; empty when the first one answered.
        "source_attempts": attempts,
        "cost": [_cost_json(cost) for cost in item.costs if cost is not None],
    }


def _deep_lock(scope: JobScope, exclusions: str) -> str:
    """The target lock this job's deep call runs under — one account, or one person."""
    if scope.subject_kind == "person":
        history = (
            "\n".join(f"    - {line}" for line in scope.employment_history)
            or "    - (none recorded; the account job confirmed them on the URL above)"
        )
        return PERSON_LOCK_TEMPLATE.format(
            name=scope.person_name,
            title=scope.person_title or "(not stated)",
            company=scope.account_name,
            linkedin=scope.person_linkedin_url or "(not stated)",
            history=history,
            exclusions=exclusions,
        )
    return LOCK_TEMPLATE.format(
        name=scope.account_name, domain=scope.account_domain, exclusions=exclusions
    )


async def _research_deep(
    runtime: ToolRuntime, args: ResearchDeepArgs | AccountResearchDeepArgs | PersonResearchDeepArgs
) -> dict[str, Any]:
    scope = runtime.scope
    if uses_person_exa_brief(scope):
        assert isinstance(args, PersonResearchDeepArgs)
        person_args = person_exa_arguments(**args.model_dump())
        operation, raw = await runtime.operate(
            "exa",
            "person_deep",
            deep_reasoning_body(**person_args),
            lambda caller: runtime.clients.exa(caller).deep_reasoning(
                **person_args, label=f"person-deep-{scope.account_domain}"
            ),
        )
        from clue_api.arv2.exa_client import read_deep_report

        report = read_deep_report(raw, text_output=True) or ""
        return {
            "report": report,
            "result_ref": str(operation.operation_id),
            "n_results": len(raw.get("results", [])),
            "source_artifact_key": operation.artifact_key,
            "source_from_saved_response": True,
            "gaps": [] if report.strip() else ["deep_report_empty_review_returned_sources"],
        }
    exclusions = ", ".join(args.same_name_exclusions) or "none named"
    system_prompt = _deep_lock(scope, exclusions) + "\n\n" + EVIDENCE_RULES
    query_parts = [args.charter]
    if isinstance(args, ResearchDeepArgs) and args.probes:
        query_parts.append("SPECIAL PROBES\n" + "\n".join(f"- {probe}" for probe in args.probes))
    query_parts.append(
        "ALREADY ESTABLISHED (do not re-derive; find what is NOT here)\n"
        + _clip_lines(scope.already_established or "(nothing yet)", _DEEP_ESTABLISHED_MAX_CHARS)
    )
    query = "\n\n".join(query_parts)
    provider_args: dict[str, Any] = {
        "system_prompt": system_prompt,
        "query": query,
        "output_schema": report_output_schema(),
        "num_results": args.num_results,
    }
    operation_input: dict[str, Any] = {
        "system": system_prompt,
        "query": query,
        "num_results": args.num_results,
    }
    if uses_account_exa_brief(scope):
        assert isinstance(args, AccountResearchDeepArgs)
        provider_args = account_exa_arguments(
            charter=args.charter,
            additional_queries=args.additional_queries,
            num_results=args.num_results,
            same_name_exclusions=args.same_name_exclusions,
        )
        # The entire wire request identifies this operation and is retained in the provider ledger.
        # Different additional queries/content settings must never reuse an old purchase receipt.
        operation_input = deep_reasoning_body(**provider_args)

    def hop(caller: ProviderCaller) -> Any:
        return runtime.clients.exa(caller).deep_reasoning(
            **provider_args,
            label=f"deep-{scope.account_domain}",
        )

    if (
        has_capability(scope.catalog_version, "committee_discovery")
        and scope.subject_kind == "account"
    ):
        from clue_api.arv2.committee_discovery import deep_result

        operation, raw = await runtime.operate(
            "exa",
            "account_deep",
            operation_input,
            hop,
        )
        try:
            return deep_result(operation, raw, text_output=uses_account_exa_brief(scope))
        except RefusalError:
            async with runtime._conn_factory() as conn:
                await conn.execute(
                    text(
                        "UPDATE arv2_research_operation SET "
                        "state='empty',error_code='deep_thin_response' WHERE operation_id=:id "
                        "AND workspace_id=:ws"
                    ),
                    {"id": operation.operation_id, "ws": scope.workspace_id},
                )
            raise
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


def _source_blocks(sources: Sequence[SourceInput]) -> tuple[SourceBlock, ...]:
    return tuple(
        SourceBlock(
            url=str(source.url) if source.url else None,
            kind=source.kind,
            text=source.text,
            title=source.title,
        )
        for source in sources
    )


async def _structure_material(
    runtime: ToolRuntime, args: StructureMaterialArgs | MediaStructureMaterialArgs
) -> dict[str, Any]:
    """One structuring call, on whichever subject this job is about.

    The **job** decides which subject kind is admitted, not the call: an account job that asked for
    a person had no contact entity to stamp the claims to (R2's refusal, kept word for word), and a
    person job that asks for an account would file company facts on one employee, where no reader
    of the account looks. Either way it is ``invalid_arguments``, because the fix is one argument.
    """
    person_job = runtime.scope.subject_kind == "person"
    if args.subject_kind == "person" and not person_job:
        raise RefusalError(
            "invalid_arguments",
            "R2 researches one account: a person subject is admitted in R3, when contact entities "
            "are composed. Structure the person's material as an account subject instead.",
        )
    if args.subject_kind == "account" and person_job:
        raise RefusalError(
            "invalid_arguments",
            "a person job structures its person: every claim it writes is stamped to the contact, "
            f"so an account subject would file {runtime.scope.account_name}'s facts on "
            f"{runtime.scope.person_name}. Call it with subject_kind='person'.",
        )
    media_sources: list[tuple[TranscriptSource, dict[str, Any]]] = []
    source_blocks: list[SourceBlock] = []
    for source in args.sources:
        if isinstance(source, TranscriptSource):
            from clue_api.arv2.media_claims import resolve_source

            block, saved = await resolve_source(runtime, source)
            source_blocks.append(block)
            media_sources.append((source, saved))
        else:
            source_blocks.extend(_source_blocks([source]))
    blocks = tuple(source_blocks)

    def person_hop(caller: ProviderCaller) -> Any:
        subject = PersonSubject(
            name=runtime.scope.person_name,
            company=runtime.scope.account_name,
            linkedin_url=runtime.scope.person_linkedin_url,
        )
        return runtime.clients.structuring(caller).structure_person(
            subject, "", runtime.catalog, mode=args.mode, sources=blocks, notes=args.notes
        )

    def account_hop(caller: ProviderCaller) -> Any:
        # The bundle is built inside the client from these blocks, so the fence, the quoting rule
        # and the post-parse attribution can never disagree; there is no free bundle to pass.
        subject = AccountSubject(
            name=args.subject_name,
            domain=args.subject_domain_or_company,
            already_known=args.already_known,
        )
        return runtime.clients.structuring(caller).structure_account(
            subject, "", runtime.catalog, mode=args.mode, sources=blocks, notes=args.notes
        )

    try:
        output = await runtime.call_provider(
            "openrouter", person_hop if person_job else account_hop
        )
    except RawParseError as unparseable:
        raise RefusalError("structuring_unparseable", str(unparseable)) from unparseable
    if person_job:
        # What ``unique_insight`` will read. Kept only once the call came back, so material the
        # provider never saw is not counted as a channel the one-question pass checked.
        runtime.remember_sources(blocks)

    drafts = structured_claims(
        output, scope=runtime.scope, subject_url_hint=None, catalog=runtime.catalog
    )
    if has_capability(runtime.scope.catalog_version, "media_research"):
        from clue_api.arv2.media_claims import annotate_drafts

        drafts = await annotate_drafts(runtime, drafts, media_sources)
    negatives = negative_claims(output.negatives, runtime.scope)
    # One transaction per draft: a value the store will not take costs its own claim and nothing
    # else. The claims and the negatives are written as two batches so the two counts stay their
    # own — the compliance floor may remove a draft, so a single batch could not be split by index.
    floor_from = len(runtime.compliance_log)
    claim_results = await runtime.write_each(drafts)
    negative_results = await runtime.write_each(negatives)
    written = [
        _receipt_json(result, draft, runtime.catalog)
        for draft, result in claim_results
        if isinstance(result, WriteReceipt)
    ]
    failures = [
        result
        for _, result in [*claim_results, *negative_results]
        if isinstance(result, WriteFailure)
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
        "negatives_written": sum(
            1 for _, result in negative_results if isinstance(result, WriteReceipt)
        ),
        # Rows the mode's cap discarded after the parse, and drafts the claim gate would not take:
        # both are things that happened to this call's output, and both are reported rather than
        # swallowed (a sweep that keeps drifting broad, or a value that has no writable home).
        "dropped_rows": output.dropped_rows,
        "write_failures": [
            {"field_key": failure.field_key, "error": failure.error} for failure in failures
        ],
        # What the compliance floor did to THIS call's drafts (person jobs only; an account job's
        # claims never meet it). A claim the floor dropped would otherwise be indistinguishable
        # from a claim the structuring pass never produced.
        "compliance": runtime.compliance_log[floor_from:],
        "mode": output.mode,
        "cost": _cost_json(output.cost),
    }


async def _unique_insight(runtime: ToolRuntime, args: UniqueInsightArgs) -> dict[str, Any]:
    """The one-question pass: what a generic enrichment tool would never surface about this person.

    It is a **second reading of material this job already retrieved**, so it takes no sources of
    its own — the runtime carries every block ``structure_material`` structured, and asking the
    agent to paste them back would be paying twice for the same bytes. With nothing structured yet
    there is nothing to read, and that is ``invalid_arguments`` with the call to make instead: it
    is an ordering mistake, not a finding about the person.

    An empty answer is ``insight_not_found``, which is a **finding** — the manual's row tells the
    agent to record "thin public footprint" with the channels checked — so the refusal names the
    source kinds it read, which is what "the channels checked" means here.

    The answer may only land on a **fact** facet (``UNIQUE_INSIGHT_TARGET_KEYS``); a row on
    ``contact.facet.hooks`` or any other outreach field is dropped and named in
    ``dropped_off_target``, never written.
    """
    scope = runtime.scope
    sources = tuple(runtime.person_sources)
    if not sources:
        raise RefusalError(
            "invalid_arguments",
            "unique_insight reads the material this job has already structured, and this job has "
            "structured none. Call structure_material first, then ask this once.",
        )
    subject = PersonSubject(
        name=scope.person_name,
        company=scope.account_name,
        linkedin_url=scope.person_linkedin_url,
    )

    def hop(caller: ProviderCaller) -> Any:
        return runtime.clients.structuring(caller).structure_person(
            subject, "", runtime.catalog, mode=UNIQUE_INSIGHT_MODE, sources=sources, notes=None
        )

    try:
        output = await runtime.call_provider("openrouter", hop)
    except RawParseError as unparseable:
        raise RefusalError("structuring_unparseable", str(unparseable)) from unparseable

    if not output.claims:
        kinds = sorted({block.kind for block in sources})
        raise RefusalError(
            "insight_not_found",
            f"nothing beyond a standard profile in the {len(sources)} source(s) this job has "
            f"structured (kinds checked: {', '.join(kinds)})",
        )
    insight = unique_insight_claims(output, scope=scope, catalog=runtime.catalog)
    floor_from = len(runtime.compliance_log)
    results = await runtime.write_each(insight.drafts)
    return {
        "written": [
            _receipt_json(result, draft, runtime.catalog)
            for draft, result in results
            if isinstance(result, WriteReceipt)
        ],
        "write_failures": [
            {"field_key": result.field_key, "error": result.error}
            for _, result in results
            if isinstance(result, WriteFailure)
        ],
        # The insight is at most one claim, so "the floor took it" and "there was nothing" are the
        # same empty ``written`` without this: the rows say which happened.
        "compliance": runtime.compliance_log[floor_from:],
        "sources_read": len(sources),
        # Rows the reply lost after the parse: the mode's own cap, plus the ones written to a key
        # that may not carry an insight. ``dropped_off_target`` names those keys, because "the
        # answer was on the wrong field" and "there was nothing to find" are otherwise the same
        # empty ``written`` and the agent would record the wrong finding.
        "dropped_rows": output.dropped_rows + len(insight.off_target),
        "dropped_off_target": list(insight.off_target),
        "cost": _cost_json(output.cost),
    }


async def _write_claims(
    runtime: ToolRuntime, args: WriteClaimsArgs | MediaWriteClaimsArgs
) -> dict[str, Any]:
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
    drafts = agent_claims(args.claims, runtime.scope, catalog=runtime.catalog)
    if has_capability(runtime.scope.catalog_version, "media_research"):
        from clue_api.arv2.media_claims import attach, resolve_source

        for index, item in enumerate(args.claims):
            source = getattr(item, "transcript_source", None)
            if source is not None:
                _, saved = await resolve_source(runtime, source)
                drafts[index] = attach(drafts[index], source, saved, runtime)
    # One transaction per draft. This is the largest model-produced batch in the toolbelt (cap
    # fifty), so a single value the store will not take must cost its own claim and nothing else —
    # never forty-nine good claims, and never a whole-batch ``tool_error`` the model retries
    # identically. ``write_each`` returns one result per draft, in order.
    results = await runtime.write_each(drafts)
    return {
        "written": [
            _receipt_json(result, draft, runtime.catalog)
            for draft, result in results
            if isinstance(result, WriteReceipt)
        ],
        "write_failures": [
            {"field_key": result.field_key, "error": result.error}
            for _, result in results
            if isinstance(result, WriteFailure)
        ],
    }


async def _verify_links(runtime: ToolRuntime, args: VerifyLinksArgs) -> dict[str, Any]:
    """Check every cited quote against the page it cites, and record *why* each verdict is what
    it is.

    A verdict on its own is not something a reader can act on. ``fetch_failed`` covers both a page
    that returned no text and a page that would not load; ``NOT_FOUND`` covers both a quote the
    model invented and a quote it lifted verbatim from a *report about* the account (real words,
    wrong page). Those want different repairs, so each claim's annotation carries the reason —
    ``on_page`` / ``partial_on_page`` / ``page_empty`` / ``page_unreachable`` / ``not_on_page`` /
    ``second_hand_from_report`` / ``quoted_context`` — beside the verdict the CHECK admits.
    """
    claims = [claim for claim in await runtime.job_claims() if claim.source_url]
    if args.claim_ids is not None:
        wanted = set(args.claim_ids)
        claims = [claim for claim in claims if str(claim.id) in wanted]

    rows: list[AnnotationRow] = []
    by_reason: dict[str, int] = {}
    not_found: list[str] = []
    failed: list[str] = []
    unreachable_urls: set[str] = set()
    counts = {"EXACT": 0, "PARTIAL": 0}
    costs: list[dict[str, Any] | None] = []

    def record(
        claim: Claim, url: str, verdict: str, reason: str, extra: dict[str, Any] | None = None
    ) -> None:
        markers = claim.write_markers or {}
        block = markers.get("source_kind_block")
        rows.append(
            AnnotationRow(
                claim_id=UUID(str(claim.id)),
                verdict=verdict,
                detail={
                    "reason": reason,
                    "url": url,
                    "origin": claim.source_key,
                    **(extra or {}),
                    "structuring_mode": block if isinstance(block, str) else None,
                },
            )
        )
        key = f"{verdict}/{reason}"
        by_reason[key] = by_reason.get(key, 0) + 1
        if verdict in counts:
            counts[verdict] += 1
        elif verdict == "NOT_FOUND":
            not_found.append(str(claim.id))
        elif url not in failed:
            failed.append(url)

    for claim in claims:
        url = claim.source_url or ""
        markers = claim.write_markers or {}
        if markers.get("media") or markers.get("source_kind_block") == "transcript":
            from clue_api.arv2.media_claims import audit

            verdict, reason, extra = await audit(runtime, claim)
            record(claim, url, verdict, reason, extra)
            continue
        if markers.get("quoted_context") is True:
            # Task 3 saw this quote sitting in the agent's own notes rather than in any source
            # block. No page can contain it, so buying a fetch to discover that spends a contents
            # call to learn nothing already known.
            record(claim, url, "NOT_FOUND", "quoted_context")
            continue
        if url in unreachable_urls:
            record(claim, url, "fetch_failed", "page_unreachable")
            continue
        text = runtime.cached_page(url)
        if text is None:
            try:
                text = await _fetch_for_audit(runtime, url, costs)
            except RefusalError:
                raise
            except Exception as unreachable:  # noqa: BLE001 — a dead link is a finding, not a stop
                log.info("arv2.verify_links_fetch_failed", url=url, error=str(unreachable))
                unreachable_urls.add(url)
                record(claim, url, "fetch_failed", "page_unreachable")
                continue
        if not text.strip():
            # A page that came back empty proves nothing about the quote. Calling that NOT_FOUND
            # would report an unreadable link as a fabricated one, which is the wrong accusation.
            record(claim, url, "fetch_failed", "page_empty")
            continue
        verdict = substring_verdict(claim.evidence_span or "", text)
        if verdict == "EXACT":
            reason = "on_page"
        elif verdict == "PARTIAL":
            reason = "partial_on_page"
        elif markers.get("source_kind_block") == "report":
            # The words are real and were read out of a report about this account; they are simply
            # not on the page the claim points at. That is a citation to repair, not a fabrication.
            reason = "second_hand_from_report"
        else:
            reason = "not_on_page"
        record(claim, url, verdict, reason)

    await runtime.record_link_audit(rows)
    return {
        "EXACT": counts["EXACT"],
        "PARTIAL": counts["PARTIAL"],
        "NOT_FOUND": not_found,
        "fetch_failed": failed,
        "by_reason": by_reason,
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


@dataclass(frozen=True)
class _KeyedVerdicts:
    """The finalization's verdicts once they are keyed to the ICP: one per gate, and what moved."""

    verdicts: list[dict[str, Any]]
    filled: tuple[str, ...]
    duplicates: tuple[str, ...]


def _fold_gate_key(label: str) -> str:
    """The form two gate labels are compared in: case-folded, outer whitespace gone."""
    return label.strip().casefold()


def _key_verdicts_to_icp_gates(
    admitted: tuple[str, ...], verdicts: list[dict[str, Any]]
) -> _KeyedVerdicts:
    """One verdict per ICP gate: unknown labels refused, second answers dropped, silence filled.

    A run whose model invents its own gate labels produces a receipt no reviewer can compare with
    the next account's, so a label the ICP does not name is refused rather than recorded. The
    inverse — a gate the model simply never mentioned — is filled here as ``unclear`` / "not
    assessed", because "we did not look" and "we looked and could not tell" are different answers
    and silence reads as the second one.

    The match folds case and surrounding whitespace first, and the accepted verdict is rewritten to
    the ICP's own spelling of the key. ``"Geography"`` and ``"stage "`` are the gate the ICP named,
    not new gates, and the failure here is asymmetric: folding a near-miss label costs nothing,
    refusing it costs the run its only path to a finalized ending. A label that still resolves to
    no gate after folding is refused exactly as before.

    A **second** verdict for a gate already answered is dropped, never refused: it is noise rather
    than a falsehood, the first answer is the one the agent reasoned to, and refusing the whole
    call would throw away a finalization (summary, committee, gaps) over a repeated line. The
    dropped labels are reported back so the model can see what happened.

    An ICP with no hard gates keys to nothing, so every label it admits stays as the model wrote it
    — the one-verdict-per-gate rule still holds, there is simply no list to check it against.
    """
    if admitted:
        by_fold = {_fold_gate_key(key): key for key in admitted}
        unknown = sorted(
            {
                str(verdict.get("gate") or "")
                for verdict in verdicts
                if _fold_gate_key(str(verdict.get("gate") or "")) not in by_fold
            }
        )
        if unknown:
            raise RefusalError(
                "invalid_arguments",
                f"fit verdicts are keyed to this ICP's hard gates; {unknown} name no gate of it. "
                f"The admitted gate keys are {list(admitted)}",
            )
        verdicts = [
            {**verdict, "gate": by_fold[_fold_gate_key(str(verdict.get("gate") or ""))]}
            for verdict in verdicts
        ]
    kept: list[dict[str, Any]] = []
    answered: list[str] = []
    duplicates: list[str] = []
    for verdict in verdicts:
        gate = str(verdict.get("gate") or "")
        if gate in answered:
            duplicates.append(gate)
            continue
        answered.append(gate)
        kept.append(verdict)
    missing = tuple(key for key in admitted if key not in answered)
    kept.extend(
        {"gate": key, "verdict": "unclear", "rationale": "not assessed", "claim_ids": []}
        for key in missing
    )
    return _KeyedVerdicts(kept, missing, tuple(dict.fromkeys(duplicates)))


async def _finalize_research(runtime: ToolRuntime, args: FinalizeResearchArgs) -> dict[str, Any]:
    if runtime.finalization is not None:
        raise RefusalError("finalization_already_proposed", "this job is already finalized")

    # Spec 2026-09-12 §1: the agent's last act is the synthesis of its findings, so the row says
    # so before a single finalization claim lands.
    await runtime.stamp_stage("synthesis")

    keyed = _key_verdicts_to_icp_gates(
        runtime.scope.icp_gate_keys, [verdict.model_dump() for verdict in args.fit_verdicts]
    )
    verdicts = keyed.verdicts
    candidates = [candidate.model_dump() for candidate in args.committee_candidates]
    if has_capability(runtime.scope.catalog_version, "committee_discovery"):
        from clue_api.arv2.committee_discovery import finalize_committee

        return await finalize_committee(runtime, args, verdicts, keyed, candidates)
    drafts = [
        *fit_verdict_claims(verdicts, runtime.scope, filled_by_tool=keyed.filled),
        *committee_candidate_claims(candidates, runtime.scope),
    ]
    receipts = await runtime.write(drafts)
    dropped = [str(candidate.get("name")) for candidate in unconfirmed_candidates(candidates)]
    runtime.finalization = {
        "summary": args.summary,
        "fit_verdicts": verdicts,
        "gaps": list(args.gaps),
        # The committee the job confirmed, in the order the agent named it. The driver's committee
        # step reads it here rather than off the claim rows this call just wrote: the rows carry
        # every field but no order, and the order is what the run's committee cap truncates. It is
        # deliberately NOT copied onto the durable receipt (``account_research_driver._receipt``) —
        # the members are already claims, and a second at-rest copy of a person's name and title
        # inside ``finalization_json`` is a copy no DSAR erasure would reach.
        "committee_candidates": candidates,
        "proposed_at": runtime.now().isoformat(),
    }
    return {
        "accepted": True,
        "claim_ids": [str(receipt.claim_id) for receipt in receipts],
        "dropped_candidates": dropped,
        # The gates you answered twice: the first answer stands, the repeats were dropped.
        "duplicate_gates": list(keyed.duplicates),
    }


async def _finalize_person_research(
    runtime: ToolRuntime, args: FinalizePersonResearchArgs
) -> dict[str, Any]:
    """Finish one person job once: the openers, the hooks, the lock's proof, and the receipt.

    Nothing here re-decides the account. There are no fit verdicts and no committee candidates
    (constitution rule 11 — a human launched this person, and the account job owns the ICP), and
    the only judgement the tool itself makes is the one the code owns: an opener with no quote
    behind it is dropped and named.

    ``insight_found`` is read off the **rows**, not off what the model says it did: any claim this
    job wrote carrying the ``unique_insight`` marker means the one-question pass landed something.
    """
    if runtime.finalization is not None:
        raise RefusalError("finalization_already_proposed", "this job is already finalized")

    # Spec 2026-09-12 §1: the agent's last act is the synthesis of its findings, so the row says
    # so before a single finalization claim lands.
    await runtime.stamp_stage("synthesis")

    reports_to = args.reports_to.model_dump() if args.reports_to is not None else None
    if reports_to is not None and not reports_to.get("contact_id"):
        # ``contact_id`` is the registered field's required key and the agent has no way to know
        # it, so the name it *does* know is resolved against this account's own contacts. An
        # unresolved or ambiguous name leaves it absent, and the mapper skips the claim with the
        # reason rather than inventing an id.
        resolved = await runtime.resolve_contact(str(reports_to.get("name") or ""))
        reports_to["contact_id"] = str(resolved) if resolved is not None else None

    finalization = person_finalization_claims(
        openers=[opener.model_dump() for opener in args.openers],
        hooks=list(args.hooks),
        same_name_log=[row.model_dump() for row in args.same_name_log],
        reports_to=reports_to,
        scope=runtime.scope,
        catalog=runtime.catalog,
    )
    # One transaction per draft: this whole batch is model-produced, and a value the store will not
    # take must not cost the job its only finalization.
    results = await runtime.write_each(finalization.drafts)
    insight_found = any(
        (claim.write_markers or {}).get("unique_insight") is True
        for claim in await runtime.job_claims()
    )
    receipt: dict[str, Any] = {
        "summary": args.summary,
        "openers_written": len(finalization.openers_written),
        "openers_dropped": list(finalization.openers_dropped),
        "hooks_written": finalization.hooks_written,
        "not_found": list(args.not_found),
        "same_name_log": [row.model_dump() for row in args.same_name_log],
        "insight_found": insight_found,
        "reports_to_written": finalization.reports_to_written,
        # The refusal rides the DURABLE receipt, not only the model's answer: "we did not write a
        # reporting line, and here is why" is exactly what a reviewer of the job row needs.
        "reports_to_skipped": finalization.reports_to_skipped,
        "gaps": list(args.gaps),
        # The whole job's compliance actions, in order — the finalization's own writes included,
        # because they went through the same pass a moment ago.
        "compliance_log": list(runtime.compliance_log),
        "proposed_at": runtime.now().isoformat(),
    }
    runtime.finalization = receipt
    return {
        "accepted": True,
        **{key: value for key, value in receipt.items() if key != "proposed_at"},
        "lookalikes_written": finalization.lookalikes_written,
        "claim_ids": [
            str(result.claim_id) for _, result in results if isinstance(result, WriteReceipt)
        ],
        "write_failures": [
            {"field_key": result.field_key, "error": result.error}
            for _, result in results
            if isinstance(result, WriteFailure)
        ],
    }


# -- the governed wrapper ------------------------------------------------------------------------


def _refusal_envelope(refused: RefusalError, codes: frozenset[str]) -> str:
    """One refusal as the envelope the model reads, with the code checked against this belt's set.

    The envelope carries the manual's ``reaction`` for the code, *in the same turn* — a more
    proximate instruction than the manual itself. A code this agent's manual has no row for would
    therefore hand the model a move its own manual never states, so it is asserted rather than
    trusted. The assertion is a programming error, not a research outcome: the caller's outer
    handler turns it into ``tool_error:AssertionError`` under the failure law, and the tool has
    still written nothing and ended nothing.
    """
    base = refused.refusal.code.split(":", 1)[0]
    assert base in codes, (  # noqa: S101 — surfaced as tool_error by the wrapper, never a crash
        f"refusal code {base!r} is not one this agent's manual carries a row for"
    )
    return refusal_json(refused.refusal.code, refused.refusal.detail)


def _governed(
    runtime: ToolRuntime,
    name: str,
    model: type[BaseModel],
    body: Callable[[ToolRuntime, Any], Awaitable[Mapping[str, Any]]],
    codes: frozenset[str],
) -> Callable[..., Awaitable[str]]:
    """Wrap one tool body in the failure law: every exit is a JSON string, never an exception."""

    async def call(**args: Any) -> str:
        if runtime.finalization is not None and name != "finalize_research":
            return refusal_json("finalization_already_proposed", "the decision is made")
        if (previous := runtime.repeated_refusal(name, args)) is not None:
            return previous
        runtime.tool_calls += 1
        try:
            try:
                result = await body(runtime, model(**args))
                if (
                    has_capability(runtime.scope.catalog_version, "media_research")
                    and name == "finalize_research"
                ):
                    from clue_api.arv2.media_store import state as media_state

                    async with runtime._conn_factory() as conn:
                        media = await media_state(runtime, conn)
                    # Durable receipt carries counts and refs, never another personal text copy.
                    coverage = {
                        "attempts": media["attempts"],
                        "coverage": media["coverage"],
                        "exhaustive": False,
                        "item_refs": [str(r["item_id"]) for r in media["recordings"]],
                    }
                    if runtime.finalization is not None:
                        runtime.finalization["media"] = coverage
                    result = {**result, "media": coverage}
                if has_capability(runtime.scope.catalog_version, "media_research"):
                    from clue_api.arv2.media_telemetry import tool_result

                    tool_result(runtime, name, result)
                return json.dumps(result, default=str)
            except RefusalError as refused:
                envelope = _refusal_envelope(refused, codes)
            except ValidationError as invalid:
                envelope = refusal_json("invalid_arguments", str(invalid)[:500])
        except Exception as error:  # noqa: BLE001 — the failure law: never a raise into the graph
            log.exception("arv2.account_tool_failed", tool=name)
            # Deliberately NOT remembered. The refusal memory exists to stop the model paying twice
            # for a call the engine has already judged; a ``tool_error`` is no judgement at all —
            # it is the socket melting, the provider 500ing, a parse blowing up once. Remembering
            # it forecloses the identical retry that would have worked, and the model's only
            # remaining moves are to change a correct call or to finalize short.
            return refusal_json(f"tool_error:{type(error).__name__}", str(error)[:500])
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
    codes: frozenset[str] = REFUSAL_CODES,
) -> StructuredTool:
    """One governed tool. An argument the schema rejects is a refusal, not a LangChain exception."""
    return StructuredTool.from_function(
        coroutine=_governed(runtime, name, model, body, codes),
        name=name,
        description=description,
        args_schema=model,
        handle_validation_error=lambda error: refusal_json("invalid_arguments", str(error)[:500]),
    )


def build_account_tools(runtime: ToolRuntime) -> list[StructuredTool]:
    """The twelve tools for one account job, bound to that job's runtime."""
    tools = [
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
                "Search for facts or people by name, role or team (at most ten results). "
                "People discovery may use web search or AI Ark SMART as appropriate. "
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
                "legal name, founding year, industry, headcount and band, revenue band, HQ, "
                "LinkedIn, socials, languages, technologies and funding. Basic typed facts are "
                "mapped with their record paths. AI Ark descriptions are not mapped; "
                "use Exa and company pages for substantive company findings, "
                "using typed facts as context."
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
                "when the speaker is verified. Give every other place the same appearance may "
                "load from as alternate_urls (another feed host, the YouTube upload); they are "
                "tried in order only if the source before them will not load."
            ),
            model=ReadMediaFeedsArgs,
            body=_read_media_feeds,
        ),
        _tool(
            runtime,
            name="research_deep",
            description=(
                "Read the account-dossier skill. Send a self-contained charter and complementary "
                "additional_queries from the brief and known leads. Integrate probes into the "
                "charter once. One deep call; default 40 results, source highlights "
                "and page links. Exa investigates; you retain seller-fit judgment."
                if uses_account_exa_brief(runtime.scope)
                else "The one paid dossier call: your charter and special probes go in the query, "
                "the "
                "target lock and the evidence law in the system prompt, and what is already "
                "established is named so the provider finds what is NOT there. Use it once."
            ),
            model=AccountResearchDeepArgs
            if uses_account_exa_brief(runtime.scope)
            else ResearchDeepArgs,
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
                "from. A missing URL, an unknown key or a schema miss is recorded as a marker "
                "rather than refused; each claim is written on its own, so a value the store will "
                "not take comes back in write_failures and the rest of the batch is still stored."
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

    if has_capability(runtime.scope.catalog_version, "committee_discovery"):
        from clue_api.arv2.committee_discovery import account_tools

        tools = [tool for tool in tools if tool.name != "lookup_people"]
        tools.extend(account_tools(runtime))
    if has_capability(runtime.scope.catalog_version, "media_research"):
        tools = _with_media_tools(runtime, tools)
    return tools


def build_person_tools(runtime: ToolRuntime) -> list[StructuredTool]:
    """The eleven tools for one person job, bound to that job's runtime.

    Seven bodies are the account job's, unchanged — ``fetch_page``, ``search_web``,
    ``read_media_feeds``, ``research_deep``, ``structure_material``, ``write_claims`` and
    ``verify_links`` all read the job's subject off the scope rather than off the call, which is
    what lets one body serve both agents without a second copy to drift. Four are this belt's own:
    ``read_person_state`` (the account reader plus the identity lock), ``lookup_person``,
    ``unique_insight`` and the person ``finalize_research``.

    Every refusal is checked against :data:`PERSON_REFUSAL_CODES`, so a tool can never hand this
    agent a reaction its own manual does not carry.
    """

    def person_tool(
        *,
        name: str,
        description: str,
        model: type[BaseModel],
        body: Callable[[ToolRuntime, Any], Awaitable[Mapping[str, Any]]],
    ) -> StructuredTool:
        return _tool(
            runtime,
            name=name,
            description=description,
            model=model,
            body=body,
            codes=PERSON_REFUSAL_CODES,
        )

    tools = [
        person_tool(
            name="read_person_state",
            description=(
                "What is already known about this person: the claims this job has written, which "
                "catalog fields are still open, the ICP charter, the persona map, the "
                "already-established block, and the identity lock (name, title, LinkedIn URL and "
                "verified employment history). Free. Sections: all, claims, open_fields, icp, "
                "persona, already_established, lock."
            ),
            model=ReadPersonStateArgs,
            body=_read_person_state,
        ),
        person_tool(
            name="fetch_page",
            description=(
                "Fetch the verbatim text of a URL you already hold (their LinkedIn page as indexed "
                "text, a personal site, a talk page, a byline). A known URL is fetched, never "
                "searched for. Never a LinkedIn-native video."
            ),
            model=FetchPageArgs,
            body=_fetch_page,
        ),
        person_tool(
            name="search_web",
            description=(
                "An ordinary search for this selected person. Choose complementary angles, "
                "including earlier roles, writing, media, background and interests. Read the "
                "returned source overview and complete evidence, not just titles. Domain filters "
                "are optional; use them only for a specific useful source, not every search."
                if uses_person_exa_brief(runtime.scope)
                else "One unrestricted sweep search (at most ten results) for this named person. "
                "Leave "
                "include_domains empty: restricting the domain forces the engine to return "
                "something from that domain, and that something is a same-name stranger."
            ),
            model=SearchWebArgs,
            body=_search_web,
        ),
        person_tool(
            name="lookup_person",
            description=(
                "Confirm this person's identity and pull their deterministic fields plus their "
                "professional email, by their LinkedIn URL. The name and the account are the "
                "job's, so this is never a roster pull. Reuses an acquired candidate profile "
                "when available; a new lookup checks the supplied LinkedIn identity and "
                "employer. Permitted typed enrichment is mapped to claims in code. "
                "Biographies, headlines and promotional prose are excluded from research "
                "inputs. Work email is provider-reported, never synthesized; no paid phones."
            ),
            model=LookupPersonArgs,
            body=_lookup_person,
        ),
        person_tool(
            name="read_media_feeds",
            description=(
                "Read this person's podcast episode (feed_url, by number or title fragment) or a "
                "YouTube appearance (youtube_url, indexed page words — never a video download). A "
                "podcast episode is transcribed, the speaker verified, and quotes mined only when "
                "the speaker is verified. Give every other place the same appearance may load from "
                "as alternate_urls. Bounded by the per-person item cap."
            ),
            model=ReadMediaFeedsArgs,
            body=_read_media_feeds,
        ),
        person_tool(
            name="research_deep",
            description=(
                "Write a self-contained person assignment after complementary preliminary "
                "searches. Carry the full person-depth charter and useful acquired sources into "
                "the initial query; add additional_queries and optional highlights_query. "
                "Read both dossier and returned sources. Use focused follow-up deep research "
                "only for a substantial unresolved investigation; reuse completed work."
                if uses_person_exa_brief(runtime.scope)
                else "The one paid dossier call: your charter and special probes go in the query, "
                "the "
                "person lock (name, title, company, LinkedIn, employment history) and the evidence "
                "law in the system prompt, and what is already established is named so the "
                "provider finds what is NOT there. Use it once."
            ),
            model=PersonResearchDeepArgs
            if uses_person_exa_brief(runtime.scope)
            else ResearchDeepArgs,
            body=_research_deep,
        ),
        person_tool(
            name="structure_material",
            description=(
                "Turn prose into typed claims against the contact field catalog and write them. "
                "One subject per call, and on this job the subject_kind is 'person'. "
                "mode='broad' sweeps everything the catalog can hold; mode='intent_sweep' pulls "
                "only verbatim buying-intent statements."
            ),
            model=StructureMaterialArgs,
            body=_structure_material,
        ),
        person_tool(
            name="unique_insight",
            description=(
                "Ask one question over everything you have already structured: what is the one "
                "thing about this person a generic enrichment tool would never surface? At most "
                "one claim, written to the existing facet field the fact actually is, at priority "
                "1. It registers no field. Ask it once, after the broad structuring pass, even "
                "when that pass found nothing distinctive."
            ),
            model=UniqueInsightArgs,
            body=_unique_insight,
        ),
        person_tool(
            name="write_claims",
            description=(
                "Write up to fifty claims yourself, each with a verbatim quote and the URL it came "
                "from. A missing URL, an unknown key or a schema miss is recorded as a marker "
                "rather than refused; each claim is written on its own, so a value the store will "
                "not take comes back in write_failures and the rest of the batch is still stored."
            ),
            model=WriteClaimsArgs,
            body=_write_claims,
        ),
        person_tool(
            name="verify_links",
            description=(
                "The fabrication audit: re-fetch the pages this job's claims cite and check every "
                "quote against the page text, EXACT / PARTIAL / NOT_FOUND, written as an "
                "annotation beside the claim."
            ),
            model=VerifyLinksArgs,
            body=_verify_links,
        ),
        person_tool(
            name="finalize_research",
            description=(
                "Finish the job once: the depth summary, the three grounded openers (each with its "
                "hook, its verbatim quote and the URL), the hooks, the not-found list with the "
                "channels you checked, the same-name log, who they report to if they said so, and "
                "the honest gaps. An opener with no quote is dropped. Zero yield is a valid "
                "outcome. It can be accepted only once."
            ),
            model=FinalizePersonResearchArgs,
            body=_finalize_person_research,
        ),
    ]

    if has_capability(runtime.scope.catalog_version, "committee_discovery"):
        from clue_api.arv2.committee_discovery import person_tools

        tools.extend(person_tools(runtime))
    if has_capability(runtime.scope.catalog_version, "media_research"):
        tools = _with_media_tools(runtime, tools)
    return tools


def _with_media_tools(runtime: ToolRuntime, tools: list[StructuredTool]) -> list[StructuredTool]:
    from clue_api.arv2 import media_tools as media

    tools = [
        t for t in tools if t.name not in {"read_media_feeds", "structure_material", "write_claims"}
    ]
    for name, model, body, description in (
        (
            "discover_media",
            media.DiscoverMediaArgs,
            media.discover_media,
            (
                "Discover recording candidates for a research question. Results are "
                "untrusted identity candidates. Page saved results with "
                "discovery_ref/offset. Read known URLs directly."
            ),
        ),
        (
            "read_media",
            media.ReadMediaArgs,
            media.read_media,
            (
                "Resolve a public recording, acquire/reuse an immutable transcript and "
                "index it. Supply purpose and an exact episode hint when needed; "
                "alternates fill gaps. Unknown dispatch never repurchases."
            ),
        ),
        (
            "search_transcripts",
            media.SearchTranscriptsArgs,
            media.search_transcripts,
            (
                "Search authorized current transcripts using lexical and semantic "
                "retrieval. Returns exact passage references, quality, attribution and "
                "qualified timing. Search gaps are explicit."
            ),
        ),
        (
            "open_transcript",
            media.OpenTranscriptArgs,
            media.open_transcript,
            (
                "Read exact canonical transcript passages and adjacent context. Follow "
                "next_offset with version_ref for full lossless reading. Null timing is"
                " valid; model speaker labels are not verified people."
            ),
        ),
        (
            "structure_material",
            MediaStructureMaterialArgs,
            _structure_material,
            (
                "Structure retrieved sources into claims. For media use transcript_ref "
                "sources with version_ref/start/end; the server supplies the original "
                "evidence. A pasted transcript cannot assert verified provenance."
            ),
        ),
        (
            "write_claims",
            MediaWriteClaimsArgs,
            _write_claims,
            (
                "Write sourced claims; use transcript_source for media. Keep exact "
                "evidence_span; uncertain speaker attribution remains unsafe for "
                "personal outreach. Invalid quotes are stored with verdicts."
            ),
        ),
    ):
        tools.append(_tool(runtime, name=name, model=model, body=body, description=description))
    return tools
