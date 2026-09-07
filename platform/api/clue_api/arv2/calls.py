"""The one wrapper every ARV2 provider call goes through — Appendix A laws 1 and 2, once.

A provider client's job is to build a request and read a body. Everything a *paid* call needs
around that — the pre-spend estimate, the raw record for every attempt, the retry arithmetic, the
halt latch, the cost row — is implemented here and nowhere else. That is what makes "did this run
gate this call before spending?" and "what did this account cost?" queries rather than folklore.

Two rules the ordering encodes:

* **Law 1** — the raw response is saved *before* anything parses it, including the cost reader.
  A body that crashes a parser is still on disk, still replayable.
* **Law 2** — the estimate row is written *before* the wire. A process that dies mid-call leaves
  a reservation behind, so spend is never silently unaccounted.

Money caps only *record*: a ceiling sets ``over_ceiling`` on both rows and the call proceeds
(master plan §2 item 3). Money *truth* blocks: a halt rule latches the provider and raises.
"""

from __future__ import annotations

import json
import time
import uuid
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from email.utils import parsedate_to_datetime

from clue_api.arv2.errors import (
    ProviderHalted,
    ProviderTransportError,
    RawParseError,
    RawScrubFailed,
)
from clue_api.arv2.sinks import (
    CallOutcome,
    LedgerPhase,
    LedgerRow,
    LedgerSink,
    RawRecord,
    RawRequest,
    RawResponse,
    RawSink,
    SpendTotals,
    redact_headers,
    redact_url,
    sha256_hex,
)
from clue_api.arv2.transport import HttpRequest, HttpResponse, Transport, TransportFailure

#: The statuses Appendix A law 2 retries with the ``12·(n+1)`` s (or ``Retry-After``) backoff.
DEFAULT_RETRY_STATUSES: frozenset[int] = frozenset({429, 500, 502, 503, 504})

#: Appendix A law 2's attempt count. A named constant rather than a literal on ``CallSpec``,
#: because the expensive calls override it and their reasoning reads better against a name.
DEFAULT_MAX_ATTEMPTS = 4

#: Above this many decoded characters a request body is content-addressed in the raw record
#: instead of inlined. A raw record exists to make an attempt *replayable and auditable*, and a
#: sha256 plus a byte count does that for a body whose content is already on disk anyway — while
#: inlining, say, a base64-encoded ten-minute MP3 writes ~13 MB per attempt, up to four attempts,
#: for one call. Chosen well above any prompt or JSON payload the lane sends and well below any
#: encoded-media body, so the threshold never has to be reasoned about per call site.
MAX_INLINE_REQUEST_CHARS = 64_000


@dataclass(frozen=True)
class SpendEstimate:
    """What a call is expected to cost, raised *before* the wire (law 2)."""

    usd: Decimal = Decimal(0)
    credits: Decimal = Decimal(0)
    media_seconds: int = 0


@dataclass(frozen=True)
class Ceilings:
    """Record-only spend caps. Exceeding one flags the ledger row; it never stops the call."""

    usd: Decimal | None = None
    credits: Decimal | None = None
    media_seconds: int | None = None


@dataclass(frozen=True)
class CostReading:
    """What a call actually cost, read from the provider's own metering (law 1).

    Every field is optional because "the provider did not tell us" is a real answer that must not
    be rounded to zero — the caller falls back to the estimate and the row says it did.

    ``extras`` carries whatever else the provider's metering said that does not fit the four
    numbers above — a per-component cost breakdown, most often. It is merged into the **result**
    row's ``extras`` (never the estimate row, which is written before the wire), so "which part of
    this call was expensive" stays a query. Values must be JSON-safe: the row is serialised by the
    ledger sink, which knows only ``Decimal`` and ``datetime`` beyond the JSON primitives.
    """

    cost_usd: Decimal | None = None
    credits: Decimal | None = None
    provider_request_id: str | None = None
    media_seconds: int | None = None
    extras: Mapping[str, object] = field(default_factory=dict)


#: Returns a reason code when the response proves the provider will not sell (402/403, a body
#: naming "credit", an unknown-spend state), else ``None``. A reason latches the provider.
HaltRule = Callable[[HttpResponse], str | None]

#: Reads the provider's own metering off the response. Exceptions are caught by the wrapper.
CostReader = Callable[[HttpResponse], CostReading]

#: Appendix A law 3's hook: "sensitive keys are dropped inside the provider client, before
#: persistence". Applied to the parsed JSON body the moment the response arrives, and its output
#: **replaces** the response for the rest of the call — the raw record, the cost reader, the halt
#: rule and the returned ``CallResult`` all see the scrubbed body, so a dropped key is on no path.
#: Skipped when the body is binary or does not parse as JSON, in which case it is saved as-is.
RawScrubber = Callable[[object], object]


@dataclass(frozen=True)
class CallSpec:
    """One provider call, fully described: the request plus every policy the wrapper applies."""

    provider: str
    operation: str
    label: str
    request: HttpRequest
    estimate: SpendEstimate = field(default_factory=SpendEstimate)
    max_attempts: int = DEFAULT_MAX_ATTEMPTS
    retry_statuses: frozenset[int] = DEFAULT_RETRY_STATUSES
    halt_rule: HaltRule | None = None
    cost_reader: CostReader | None = None
    raw_scrubber: RawScrubber | None = None
    binary: bool = False
    #: The *request* body is bytes that must never be inlined into a raw record — an uploaded
    #: media file, or JSON carrying a base64-encoded one. ``binary`` governs the response only;
    #: this governs the request, and the record then carries its sha256 and byte count instead.
    #: A body over :data:`MAX_INLINE_REQUEST_CHARS` is treated the same way without the flag.
    binary_request: bool = False
    extras: Mapping[str, object] = field(default_factory=dict)


@dataclass(frozen=True)
class CallResult:
    """The outcome of a completed call, with the references that make it auditable."""

    response: HttpResponse
    latency_ms: int
    attempts: int
    raw_ref: str | None
    raw_refs: tuple[str, ...]
    ledger_row_id: str
    cost: CostReading
    over_ceiling: bool

    def text(self) -> str:
        """The response body decoded as UTF-8 (undecodable bytes replaced, never raising)."""
        return self.response.body.decode("utf-8", "replace")

    def json(self) -> object:
        """The response body parsed as JSON, or :class:`RawParseError` naming the saved record."""
        try:
            return json.loads(self.response.body)
        except ValueError as exc:
            raise RawParseError(self.raw_ref, f"raw body is not JSON: {exc}") from exc


class ProviderCaller:
    """Sends one :class:`CallSpec` at a time, applying laws 1 and 2 in a fixed order."""

    def __init__(
        self,
        *,
        transport: Transport,
        raw_sink: RawSink,
        ledger: LedgerSink,
        ceilings: Ceilings | None = None,
        sleep: Callable[[float], None] = time.sleep,
        monotonic: Callable[[], float] = time.monotonic,
        now: Callable[[], datetime],
    ) -> None:
        self._transport = transport
        self._raw_sink = raw_sink
        self._ledger = ledger
        self._ceilings = ceilings or Ceilings()
        self._sleep = sleep
        self._monotonic = monotonic
        self._now = now
        self._halted: dict[str, str] = {}
        self._totals = SpendTotals()

    def halted(self, provider: str) -> str | None:
        """The latched halt reason for a provider, or ``None`` when it is free to be called."""
        return self._halted.get(provider)

    def reset_halt(self, provider: str) -> None:
        """Clear a provider's latch (an operator decision — credit was topped up, say)."""
        self._halted.pop(provider, None)

    def totals(self) -> SpendTotals:
        """Running spend recorded by this caller across every completed call."""
        return self._totals

    def call(self, spec: CallSpec) -> CallResult:
        """Send one call under Appendix A laws 1 and 2, in this exact order.

        1. A latched provider raises immediately — no wire, no ledger row.
        2. The estimate row is written **before** the wire (law 2).
        3. Each attempt saves its raw record **before** anything parses it (law 1), then honours
           ``Retry-After`` or the ``12·(n+1)`` s / ``2·(n+1)`` s backoffs. A scrubber that raises
           still leaves a body-less record and a result row behind (law 3 vs law 1).
        4. The cost reader runs, then the halt rule; a halt latches the provider and raises.
        5. The result row is written and the running totals are updated.
        """
        latched_reason = self._halted.get(spec.provider)
        if latched_reason is not None:
            raise ProviderHalted(spec.provider, f"latched:{latched_reason}", latched=True)

        call_id = str(uuid.uuid4())
        over_ceiling = self._exceeds_ceilings(spec.estimate)
        self._record(
            spec,
            call_id=call_id,
            phase="estimate",
            outcome="estimate",
            over_ceiling=over_ceiling,
        )

        raw_refs: list[str] = []
        response: HttpResponse | None = None
        attempts = 0
        latency_ms = 0
        for index in range(spec.max_attempts):
            attempts = index + 1
            is_last = index == spec.max_attempts - 1
            started = self._monotonic()
            try:
                response = self._transport.send(spec.request)
            except TransportFailure as exc:
                latency_ms = self._elapsed_ms(started)
                if not is_last:
                    self._sleep(2.0 * (index + 1))
                    continue
                self._record(
                    spec,
                    call_id=call_id,
                    phase="result",
                    outcome="transport_error",
                    over_ceiling=over_ceiling,
                    attempts=attempts,
                    latency_ms=latency_ms,
                    error_code="transport_error",
                    extras={"last_error": str(exc)},
                )
                raise ProviderTransportError(spec.provider, attempts, str(exc)) from exc
            latency_ms = self._elapsed_ms(started)
            try:
                response = self._scrub(spec, response)
            except Exception as exc:
                raw_refs.append(
                    self._save_raw(spec, call_id, index, latency_ms, response, persist_body=False)
                )
                self._settle(
                    spec,
                    call_id=call_id,
                    outcome="client_error",
                    attempts=attempts,
                    latency_ms=latency_ms,
                    status=response.status,
                    cost=CostReading(),
                    error_code="raw_scrub_failed",
                    raw_ref=raw_refs[-1],
                )
                raise RawScrubFailed(spec.provider, raw_refs[-1], str(exc)) from exc
            raw_refs.append(self._save_raw(spec, call_id, index, latency_ms, response))
            if response.status in spec.retry_statuses and not is_last:
                self._sleep(self._retry_delay(response, index))
                continue
            break

        if response is None:  # pragma: no cover - max_attempts is always >= 1
            raise ProviderTransportError(spec.provider, attempts, "no attempt was made")

        cost = CostReading()
        error_code: str | None = None
        if spec.cost_reader is not None:
            try:
                cost = spec.cost_reader(response)
            except Exception:
                # An unreadable cost is "the provider did not tell us", never zero: the row falls
                # back to the estimate and says so, and the call still returns its body.
                cost = CostReading()
                error_code = "cost_unreadable"

        halt_reason = spec.halt_rule(response) if spec.halt_rule is not None else None
        if halt_reason is not None:
            self._halted[spec.provider] = halt_reason
            row_id, _ = self._settle(
                spec,
                call_id=call_id,
                outcome="halted",
                attempts=attempts,
                latency_ms=latency_ms,
                status=response.status,
                cost=cost,
                error_code=halt_reason,
                raw_ref=raw_refs[-1] if raw_refs else None,
            )
            raise ProviderHalted(
                spec.provider,
                halt_reason,
                http_status=response.status,
                ledger_row_id=row_id,
            )

        row_id, actual_over_ceiling = self._settle(
            spec,
            call_id=call_id,
            outcome=self._outcome(response.status, spec.retry_statuses),
            attempts=attempts,
            latency_ms=latency_ms,
            status=response.status,
            cost=cost,
            error_code=error_code,
            raw_ref=raw_refs[-1] if raw_refs else None,
        )
        return CallResult(
            response=response,
            latency_ms=latency_ms,
            attempts=attempts,
            raw_ref=raw_refs[-1] if raw_refs else None,
            raw_refs=tuple(raw_refs),
            ledger_row_id=row_id,
            cost=cost,
            over_ceiling=actual_over_ceiling,
        )

    # -- internals ---------------------------------------------------------------------------

    def _elapsed_ms(self, started: float) -> int:
        return max(0, int((self._monotonic() - started) * 1000))

    @staticmethod
    def _outcome(status: int, retry_statuses: frozenset[int]) -> CallOutcome:
        """Label the final status. A retryable status that survived every attempt is exhaustion.

        Any other non-2xx lands on ``client_error``: the ledger's outcome vocabulary is fixed
        (master plan §4), and "the provider refused this request" is the closest honest member.
        """
        if 200 <= status < 300:
            return "ok"
        if status in retry_statuses:
            return "retry_exhausted"
        return "client_error"

    def _exceeds_ceilings(self, spend: SpendEstimate) -> bool:
        """Would this spend push the running totals past a ceiling? Record-only (§2 item 3).

        Called twice per call against the same totals-so-far: once with the pre-wire *estimate*
        (the flag the estimate row carries) and once in :meth:`_settle` with what the call
        **actually** cost (the flag the result row carries). A call whose estimate was under a
        ceiling but whose real cost was over is exactly the case a cost dashboard needs to see.
        """
        ceilings = self._ceilings
        totals = self._totals
        if ceilings.usd is not None and totals.usd + spend.usd > ceilings.usd:
            return True
        if ceilings.credits is not None and totals.credits + spend.credits > ceilings.credits:
            return True
        return (
            ceilings.media_seconds is not None
            and totals.media_seconds + spend.media_seconds > ceilings.media_seconds
        )

    def _retry_delay(self, response: HttpResponse, index: int) -> float:
        """``Retry-After`` when the provider gave a readable one, else law 2's ``12·(n+1)`` s."""
        stated = self._parse_retry_after(response.headers.get("retry-after"))
        return stated if stated is not None else 12.0 * (index + 1)

    def _parse_retry_after(self, value: str | None) -> float | None:
        """Integer seconds or an HTTP-date. Anything else is treated as absent, never as zero."""
        if not value:
            return None
        text = value.strip()
        try:
            return max(0.0, float(int(text)))
        except ValueError:
            pass
        try:
            when = parsedate_to_datetime(text)
        except (TypeError, ValueError):
            return None
        now = self._now()
        if now.tzinfo is None and when.tzinfo is not None:
            when = when.replace(tzinfo=None)
        elif now.tzinfo is not None and when.tzinfo is None:
            when = when.replace(tzinfo=now.tzinfo)
        return max(0.0, (when - now).total_seconds())

    def _scrub(self, spec: CallSpec, response: HttpResponse) -> HttpResponse:
        """Appendix A law 3: drop sensitive keys inside the client, before anything else sees them.

        The scrubbed serialisation **replaces** the response for the rest of the call, so the raw
        record on disk, the cost reader, the halt rule and the ``CallResult`` the caller reads all
        carry the same bytes. A key the scrubber drops therefore exists on no path at all, which is
        the whole point of the law — a body that is scrubbed only on the way to disk is still a
        body the pipeline can read a birth date out of.

        A non-JSON or undecodable body, or a spec with no scrubber, is returned untouched.

        Exceptions are **not** caught here. ``RawScrubber`` is a public extension point, and a
        scrubber that raises has told us it cannot make this body safe — so :meth:`call` turns the
        failure into a body-less raw record plus a ``raw_scrub_failed`` result row and raises
        :class:`~clue_api.arv2.errors.RawScrubFailed`. Falling back to the unscrubbed body would
        persist exactly what law 3 exists to drop.
        """
        if spec.raw_scrubber is None or spec.binary:
            return response
        try:
            decoded = response.body.decode("utf-8")
        except UnicodeDecodeError:
            return response
        try:
            parsed = json.loads(decoded)
        except ValueError:
            return response  # not JSON: law 3's hook does not apply
        scrubbed = json.dumps(
            spec.raw_scrubber(parsed), separators=(",", ":"), sort_keys=True
        ).encode()
        return HttpResponse(status=response.status, headers=response.headers, body=scrubbed)

    def _save_raw(
        self,
        spec: CallSpec,
        call_id: str,
        attempt: int,
        latency_ms: int,
        response: HttpResponse,
        *,
        persist_body: bool = True,
    ) -> str:
        """Law 1: persist this attempt before anything reads it. Credentials never get here.

        The body is already scrubbed by the time it gets here (:meth:`_scrub` ran the moment the
        response arrived), so the persisted copy and the copy the caller reads are the same bytes.

        ``persist_body=False`` writes the attempt *without* its bytes — status, redacted headers,
        sha256 and byte count only. That is the scrubber-failure path: law 3 forbids keeping the
        body, law 1 still requires the attempt to exist in the trail, and a content address plus a
        size satisfies both.
        """
        body = response.body
        body_text: str | None = None
        if persist_body and not spec.binary:
            try:
                body_text = body.decode("utf-8")
            except UnicodeDecodeError:
                body_text = None

        request_body = spec.request.body
        request_text = self._inline_request_text(spec, request_body)

        record = RawRecord(
            call_id=call_id,
            provider=spec.provider,
            operation=spec.operation,
            label=spec.label,
            attempt=attempt,
            recorded_at=self._now(),
            latency_ms=latency_ms,
            request=RawRequest(
                method=spec.request.method,
                url=redact_url(spec.request.url),
                headers=redact_headers(spec.request.headers),
                body_text=request_text,
                body_sha256=sha256_hex(request_body) if request_body is not None else None,
                body_bytes=len(request_body) if request_body is not None else 0,
            ),
            response=RawResponse(
                status=response.status,
                headers=redact_headers(response.headers),
                body_text=body_text,
                body_sha256=sha256_hex(body),
                body_bytes=len(body),
            ),
        )
        return self._raw_sink.save(record, body if persist_body else b"")

    @staticmethod
    def _inline_request_text(spec: CallSpec, request_body: bytes | None) -> str | None:
        """The request body as text, when inlining it is small enough to be worth the disk.

        ``spec.binary`` governs the *response*; a request body needs its own answer, because the
        biggest bodies the lane sends are requests — ``transcribe_short`` base64-encodes a whole
        audio clip into a JSON body, which decodes as UTF-8 perfectly well and would otherwise be
        copied into every attempt's record. Above :data:`MAX_INLINE_REQUEST_CHARS`, or when the
        spec declares the request binary, the record keeps the sha256 and the byte count instead.
        """
        if request_body is None or spec.binary_request:
            return None
        if len(request_body) > MAX_INLINE_REQUEST_CHARS:
            return None
        try:
            text = request_body.decode("utf-8")
        except UnicodeDecodeError:
            return None
        return text if len(text) <= MAX_INLINE_REQUEST_CHARS else None

    def _settle(
        self,
        spec: CallSpec,
        *,
        call_id: str,
        outcome: CallOutcome,
        attempts: int,
        latency_ms: int,
        status: int,
        cost: CostReading,
        error_code: str | None,
        raw_ref: str | None,
    ) -> tuple[str, bool]:
        """Update the running totals from the reading, then write the result row.

        When the reader reported nothing at all, the estimate stands in for the cost and the row
        marks the substitution — an unmetered call must still appear in the money trail.

        ``over_ceiling`` is re-evaluated here against what the call **actually** cost, added to
        the totals as they stood before it. The estimate row keeps the estimate-based flag (it was
        written before the wire and cannot know better); the result row, which is what a cost
        dashboard reads, says whether real spend crossed a ceiling. Returns the row id and that
        flag.

        A reading's own ``extras`` land on this row too, between the spec's (which a caller set
        before the wire) and the ``cost_source`` marker (which the wrapper owns). A reader
        therefore reports what it read by *returning* it, and never by mutating the frozen spec it
        was called under.
        """
        told_us_nothing = (
            cost.cost_usd is None and cost.credits is None and cost.media_seconds is None
        )
        usd = spec.estimate.usd if told_us_nothing else (cost.cost_usd or Decimal(0))
        credits = spec.estimate.credits if told_us_nothing else (cost.credits or Decimal(0))
        media_seconds = (
            spec.estimate.media_seconds if told_us_nothing else (cost.media_seconds or 0)
        )
        over_ceiling = self._exceeds_ceilings(
            SpendEstimate(usd=usd, credits=credits, media_seconds=media_seconds)
        )
        self._totals = SpendTotals(
            usd=self._totals.usd + usd,
            credits=self._totals.credits + credits,
            media_seconds=self._totals.media_seconds + media_seconds,
        )
        row_id = self._record(
            spec,
            call_id=call_id,
            phase="result",
            outcome=outcome,
            over_ceiling=over_ceiling,
            attempts=attempts,
            latency_ms=latency_ms,
            http_status=status,
            cost_usd=usd,
            credits=credits,
            media_seconds=media_seconds,
            provider_request_id=cost.provider_request_id,
            error_code=error_code,
            raw_ref=raw_ref,
            extras={
                **cost.extras,
                **({"cost_source": "estimate"} if told_us_nothing else {}),
            },
        )
        return row_id, over_ceiling

    def _record(
        self,
        spec: CallSpec,
        *,
        call_id: str,
        phase: LedgerPhase,
        outcome: CallOutcome,
        over_ceiling: bool,
        attempts: int = 0,
        latency_ms: int | None = None,
        http_status: int | None = None,
        cost_usd: Decimal | None = None,
        credits: Decimal | None = None,
        media_seconds: int | None = None,
        provider_request_id: str | None = None,
        error_code: str | None = None,
        raw_ref: str | None = None,
        extras: Mapping[str, object] | None = None,
    ) -> str:
        """Write one ledger row. The estimate phase carries no cost and cites no raw record."""
        row = LedgerRow(
            row_id=str(uuid.uuid4()),
            call_id=call_id,
            phase=phase,
            provider=spec.provider,
            operation=spec.operation,
            label=spec.label,
            recorded_at=self._now(),
            http_status=http_status,
            latency_ms=latency_ms,
            attempts=attempts,
            estimate_usd=spec.estimate.usd,
            estimate_credits=spec.estimate.credits,
            estimate_media_seconds=spec.estimate.media_seconds,
            cost_usd=cost_usd,
            credits=credits,
            media_seconds=media_seconds,
            over_ceiling=over_ceiling,
            outcome=outcome,
            error_code=error_code,
            provider_request_id=provider_request_id,
            raw_ref=raw_ref,
            extras={**spec.extras, **(extras or {})},
        )
        return self._ledger.record(row)
