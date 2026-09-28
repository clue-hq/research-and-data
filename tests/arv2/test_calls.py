"""The wrapper's retry, halt and raw/ledger-ordering arithmetic.

Global Constraint 3 allows exactly one test double in the ARV2 lane, and this is where it is
spent: a live provider cannot be made to return four consecutive 429s on demand, nor to prove
that the raw record was written *before* the cost reader looked at the body. Every other ARV2
test calls the real service.
"""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

import pytest

from clue_api.arv2.calls import (
    MAX_INLINE_REQUEST_CHARS,
    CallSpec,
    Ceilings,
    CostReading,
    ProviderCaller,
    SpendEstimate,
)
from clue_api.arv2.errors import (
    ProviderHalted,
    ProviderTransportError,
    RawParseError,
    RawScrubFailed,
)
from clue_api.arv2.sinks import MemoryLedger, MemoryRawSink, sha256_hex
from clue_api.arv2.transport import (
    HttpRequest,
    HttpResponse,
    ScriptedTransport,
    TransportFailure,
)

_NOW = datetime(2026, 9, 7, 12, 0, 0, tzinfo=UTC)


class FakeClock:
    """Records what the wrapper slept and advances a monotonic clock 250 ms per read."""

    def __init__(self) -> None:
        self.sleeps: list[float] = []
        self._elapsed = 0.0

    def sleep(self, seconds: float) -> None:
        self.sleeps.append(seconds)

    def monotonic(self) -> float:
        self._elapsed += 0.25
        return self._elapsed

    def now(self) -> datetime:
        return _NOW


def _request(url: str = "https://provider.test/v1/thing") -> HttpRequest:
    return HttpRequest(method="POST", url=url, headers={"Accept": "application/json"}, body=b"{}")


def _request_with_body(body: bytes) -> HttpRequest:
    return HttpRequest(method="POST", url="https://provider.test/v1/thing", body=body)


def _spec(**overrides: object) -> CallSpec:
    base: dict[str, object] = {
        "provider": "prov",
        "operation": "v1/thing",
        "label": "unit",
        "request": _request(),
        "estimate": SpendEstimate(usd=Decimal("0.01")),
    }
    base.update(overrides)
    return CallSpec(**base)  # type: ignore[arg-type]


def _caller(
    script: list[HttpResponse | TransportFailure],
    *,
    ceilings: Ceilings | None = None,
) -> tuple[ProviderCaller, ScriptedTransport, MemoryRawSink, MemoryLedger, FakeClock]:
    transport = ScriptedTransport(script)
    raw = MemoryRawSink()
    ledger = MemoryLedger()
    clock = FakeClock()
    caller = ProviderCaller(
        transport=transport,
        raw_sink=raw,
        ledger=ledger,
        ceilings=ceilings,
        sleep=clock.sleep,
        monotonic=clock.monotonic,
        now=clock.now,
    )
    return caller, transport, raw, ledger, clock


def test_success_writes_the_estimate_row_before_the_wire_and_saves_raw_before_parsing() -> None:
    """(a) Laws 1 and 2 in one call: estimate row, then wire, then raw, then the cost reader."""
    caller, _transport, raw, ledger, _clock = _caller(
        [HttpResponse(200, {"Content-Type": "application/json"}, b'{"ok":true}')]
    )
    saved_when_cost_was_read: list[int] = []

    def reader(_response: HttpResponse) -> CostReading:
        saved_when_cost_was_read.append(len(raw.records))
        return CostReading(
            cost_usd=Decimal("0.02"), credits=Decimal("3"), provider_request_id="req-1"
        )

    result = caller.call(_spec(cost_reader=reader))

    assert saved_when_cost_was_read == [1], "law 1: the raw record precedes any parse of the body"
    estimate, outcome = ledger.rows
    assert (estimate.phase, estimate.outcome) == ("estimate", "estimate")
    assert estimate.estimate_usd == Decimal("0.01")
    assert estimate.raw_ref is None
    assert (outcome.phase, outcome.outcome, outcome.http_status) == ("result", "ok", 200)
    assert outcome.call_id == estimate.call_id
    assert outcome.attempts == 1
    assert outcome.cost_usd == Decimal("0.02")
    assert outcome.credits == Decimal("3")
    assert outcome.provider_request_id == "req-1"
    assert outcome.raw_ref == result.raw_ref == "memory:0"
    assert outcome.latency_ms is not None and outcome.latency_ms > 0
    assert outcome.extras["cost_source"] == "metered", "the reader answered, so the row says so"
    assert result.over_ceiling is False and outcome.over_ceiling is False
    assert result.ledger_row_id == outcome.row_id
    assert result.json() == {"ok": True}
    assert caller.totals().usd == Decimal("0.02")
    assert caller.totals().credits == Decimal("3")


def test_a_readings_extras_land_on_the_result_row_and_not_on_the_estimate_row() -> None:
    """A cost reader reports side facts by *returning* them, never by mutating the frozen spec.

    The estimate row is written before the wire, so it cannot carry anything the reader learned;
    the result row is written after, so it must. Both halves are asserted, and the spec's own
    ``extras`` (set by the caller before the call) must survive the merge rather than be replaced.
    """
    caller, _transport, _raw, ledger, _clock = _caller(
        [HttpResponse(200, {}, b'{"costDollars":{"total":0.007}}')]
    )
    breakdown = {"search": {"neural": 0.007}, "total": 0.007}

    def reader(_response: HttpResponse) -> CostReading:
        return CostReading(cost_usd=Decimal("0.007"), extras={"cost_breakdown": breakdown})

    caller.call(_spec(cost_reader=reader, extras={"account": "zafran"}))

    estimate, outcome = ledger.rows
    assert estimate.extras == {"account": "zafran"}
    assert "cost_breakdown" not in estimate.extras
    assert outcome.extras == {
        "account": "zafran",
        "cost_breakdown": breakdown,
        "cost_source": "metered",
    }
    assert outcome.cost_usd == Decimal("0.007")


def test_an_unmetered_reading_still_files_its_extras_alongside_the_estimate_marker() -> None:
    """A reader that read a breakdown but no total told us nothing about the amount.

    The row falls back to the estimate and says so — and still keeps what the reader did read, so
    the two facts do not have to be reconstructed from the raw body later.
    """
    caller, _transport, _raw, ledger, _clock = _caller([HttpResponse(200, {}, b"{}")])

    def reader(_response: HttpResponse) -> CostReading:
        return CostReading(extras={"cost_breakdown": {"total": None}})

    caller.call(_spec(cost_reader=reader))

    outcome = ledger.rows[1]
    assert outcome.extras["cost_source"] == "estimate"
    assert outcome.extras["cost_breakdown"] == {"total": None}
    assert outcome.cost_usd == Decimal("0.01"), "the estimate stands in for the unread cost"


def test_a_metered_call_hands_back_the_settled_cost_as_one_call_cost() -> None:
    """The uniform provision: what a client passes to its caller, and what the row holds, agree.

    ``CallResult.cost`` is the *reading* (``None`` where the provider said nothing);
    ``CallResult.call_cost`` is what the ledger ended up holding, self-describing enough that a
    caller summing a run by provider never has to re-read the ledger to learn whose number it is.
    """
    caller, _transport, _raw, ledger, _clock = _caller([HttpResponse(200, {}, b"{}")])

    def reader(_response: HttpResponse) -> CostReading:
        return CostReading(cost_usd=Decimal("0.02"), provider_request_id="req-1")

    result = caller.call(_spec(cost_reader=reader))

    outcome = ledger.rows[1]
    cost = result.call_cost
    assert cost.cost_source == "metered"
    assert (cost.cost_usd, cost.credits, cost.media_seconds) == (Decimal("0.02"), Decimal(0), 0)
    assert (cost.cost_usd, cost.credits, cost.media_seconds) == (
        outcome.cost_usd,
        outcome.credits,
        outcome.media_seconds,
    ), "the CallCost is the result row's own money view, not a second opinion"
    assert cost.ledger_row_id == outcome.row_id == result.ledger_row_id
    assert cost.raw_ref == outcome.raw_ref == result.raw_ref == "memory:0"
    assert (cost.provider, cost.operation) == ("prov", "v1/thing")


def test_a_free_call_is_labelled_free_and_not_left_to_be_inferred() -> None:
    """A public source reserves nothing and meters nothing — and the row says exactly that.

    Before ``free`` existed, an unpaid ATS fetch and a paid call whose provider went silent were
    both unlabelled, so "what did this account really cost" could not be answered without knowing
    off-hand which providers meter. The two are now different values.
    """
    caller, _transport, _raw, ledger, _clock = _caller([HttpResponse(200, {}, b"[]")])

    result = caller.call(_spec(estimate=SpendEstimate()))

    outcome = ledger.rows[1]
    assert outcome.extras["cost_source"] == "free"
    assert result.call_cost.cost_source == "free"
    assert (outcome.cost_usd, outcome.credits, outcome.media_seconds) == (Decimal(0), Decimal(0), 0)
    assert caller.totals().usd == Decimal(0)


def test_a_reserved_call_with_no_reader_is_estimated_not_free() -> None:
    """``free`` is decided on the spec, not the amounts: a reservation admits an expected bill.

    Money was reserved, so somebody expected to be charged; nothing read it back. That is the
    honest ``estimate`` state, and calling it ``free`` would quietly write off real spend.
    """
    caller, _transport, _raw, ledger, _clock = _caller([HttpResponse(200, {}, b"{}")])

    result = caller.call(_spec())  # estimate 0.01 USD, no cost reader

    assert ledger.rows[1].extras["cost_source"] == "estimate"
    assert result.call_cost.cost_source == "estimate"
    assert result.call_cost.cost_usd == Decimal("0.01"), "the estimate stands in for the unread"


def test_a_metered_call_that_cost_nothing_is_still_metered() -> None:
    """A provider that answered "zero" told us something; a free call was never going to bill.

    Deciding ``free`` on the numbers instead of the spec would collapse the two, and the second
    fact — "this provider meters, and this particular call was on the house" — is the one a cost
    dashboard needs to see when a paid source suddenly starts reporting zeroes.
    """
    caller, _transport, _raw, ledger, _clock = _caller([HttpResponse(200, {}, b"{}")])

    result = caller.call(
        _spec(estimate=SpendEstimate(), cost_reader=lambda _r: CostReading(cost_usd=Decimal(0)))
    )

    assert ledger.rows[1].extras["cost_source"] == "metered"
    assert result.call_cost.cost_source == "metered"
    assert result.call_cost.cost_usd == Decimal(0)


def test_retry_after_header_is_honoured_verbatim() -> None:
    """(b) ``Retry-After: 7`` beats the 12·(n+1) default — the provider's own pacing wins."""
    caller, _transport, _raw, _ledger, clock = _caller(
        [
            HttpResponse(429, {"Retry-After": "7"}, b"slow down"),
            HttpResponse(200, {}, b"{}"),
        ]
    )
    result = caller.call(_spec())
    assert clock.sleeps == [7.0]
    assert result.attempts == 2
    assert result.raw_refs == ("memory:0", "memory:1")


def test_retry_backoff_defaults_to_twelve_seconds_times_the_attempt() -> None:
    """(b) Four 429s: sleeps 12/24/36, one raw record per attempt, then retry_exhausted."""
    script = [HttpResponse(429, {}, b"no") for _ in range(4)]
    caller, _transport, raw, ledger, clock = _caller(list(script))
    result = caller.call(_spec())
    assert clock.sleeps == [12.0, 24.0, 36.0]
    assert len(raw.records) == 4
    assert result.attempts == 4
    assert ledger.rows[-1].outcome == "retry_exhausted"
    assert ledger.rows[-1].http_status == 429


def test_unparseable_retry_after_falls_back_to_the_default_backoff() -> None:
    """A ``Retry-After`` we cannot read is treated as absent, never as zero (no hot loop)."""
    caller, _transport, _raw, _ledger, clock = _caller(
        [HttpResponse(503, {"Retry-After": "soon"}, b""), HttpResponse(200, {}, b"{}")]
    )
    caller.call(_spec())
    assert clock.sleeps == [12.0]


def test_transport_failures_back_off_and_then_raise() -> None:
    """(c) Law 2's 2·(n+1) s transport backoff; the last failure is a typed error, not a body."""
    caller, _transport, raw, ledger, clock = _caller(
        [TransportFailure("connection reset") for _ in range(4)]
    )
    with pytest.raises(ProviderTransportError) as excinfo:
        caller.call(_spec())
    assert clock.sleeps == [2.0, 4.0, 6.0]
    assert excinfo.value.attempts == 4
    assert "connection reset" in excinfo.value.last_error
    assert raw.records == [], "no response ever arrived, so there is nothing raw to save"
    assert ledger.rows[-1].outcome == "transport_error"
    assert ledger.rows[-1].http_status is None


def test_a_halt_latches_the_provider_until_it_is_reset() -> None:
    """(d) Money truth blocks: a halt raises, latches, and costs the next call no request."""
    caller, transport, _raw, ledger, _clock = _caller(
        [HttpResponse(402, {}, b'{"error":"credit exhausted"}'), HttpResponse(200, {}, b"{}")]
    )

    def halt_rule(response: HttpResponse) -> str | None:
        return "credit_exhausted" if response.status in (402, 403) else None

    spec = _spec(halt_rule=halt_rule)
    with pytest.raises(ProviderHalted) as first:
        caller.call(spec)
    assert first.value.reason_code == "credit_exhausted"
    assert first.value.http_status == 402
    assert first.value.latched is False
    assert first.value.ledger_row_id == ledger.rows[-1].row_id
    assert ledger.rows[-1].outcome == "halted"
    assert caller.halted("prov") == "credit_exhausted"

    requests_before, rows_before = len(transport.requests), len(ledger.rows)
    with pytest.raises(ProviderHalted) as second:
        caller.call(spec)
    assert second.value.latched is True
    assert second.value.reason_code == "latched:credit_exhausted"
    assert second.value.ledger_row_id is None
    assert len(transport.requests) == requests_before, "a latched call never touches the wire"
    assert len(ledger.rows) == rows_before, "a latched call writes no ledger row"

    caller.reset_halt("prov")
    assert caller.halted("prov") is None
    assert caller.call(spec).response.status == 200


def test_credentials_are_redacted_in_the_raw_record() -> None:
    """(e) Constraint 5: no header value and no ``?key=`` reaches a durable record."""
    request = HttpRequest(
        method="POST",
        url="https://provider.test/v1/models/m:generate?key=SUPERSECRET&alt=json&upload_id=UPLOADSECRET",
        headers={
            "Authorization": "Bearer sk-live-000",
            "X-TOKEN": "ark-000",
            "x-api-key": "exa-000",
            "X-Goog-Api-Key": "goog-000",
            "Accept": "application/json",
        },
        body=b'{"q":1}',
    )
    caller, _transport, raw, _ledger, _clock = _caller([HttpResponse(200, {}, b"{}")])
    caller.call(_spec(request=request))

    record, _body = raw.records[0]
    assert record.request.url == (
        "https://provider.test/v1/models/m:generate?key=***&alt=json&upload_id=***"
    )
    assert record.request.headers == {
        "Authorization": "***",
        "X-TOKEN": "***",
        "x-api-key": "***",
        "X-Goog-Api-Key": "***",
        "Accept": "application/json",
    }
    serialized = repr(record)
    for secret in ("SUPERSECRET", "UPLOADSECRET", "sk-live-000", "ark-000", "exa-000", "goog-000"):
        assert secret not in serialized


def test_the_scrubber_output_is_the_only_body_that_survives() -> None:
    """(g) Law 3: a dropped key exists on no path — not on disk, not in what the caller reads."""

    def drop_birth_date(body: object) -> object:
        assert isinstance(body, dict)
        return {key: value for key, value in body.items() if key != "birth_date"}

    caller, _transport, raw, _ledger, _clock = _caller(
        [HttpResponse(200, {}, b'{"name":"Sanaz","birth_date":"1979-01-01"}')]
    )
    result = caller.call(_spec(raw_scrubber=drop_birth_date))

    record, stored = raw.records[0]
    assert record.response.body_text is not None
    assert "birth_date" not in record.response.body_text
    assert b"birth_date" not in stored
    assert record.response.body_sha256 == sha256_hex(stored)

    assert result.json() == {"name": "Sanaz"}
    assert b"birth_date" not in result.response.body
    assert "birth_date" not in result.text()
    assert result.response.body == stored, "the caller and the record read the same bytes"


def test_a_scrubber_leaves_a_non_json_body_alone() -> None:
    """Law 3's hook only applies to a JSON body; anything else is saved and returned as-is."""

    def explode(_body: object) -> object:
        raise AssertionError("the scrubber must not be called for a non-JSON body")

    caller, _transport, raw, _ledger, _clock = _caller(
        [HttpResponse(200, {"Content-Type": "text/html"}, b"<html>plain</html>")]
    )
    result = caller.call(_spec(raw_scrubber=explode))

    _record, stored = raw.records[0]
    assert stored == b"<html>plain</html>"
    assert result.response.body == b"<html>plain</html>"


def test_a_ceiling_flags_the_rows_but_never_stops_the_call() -> None:
    """(f) Money caps only record (master plan §2 item 3)."""
    caller, _transport, _raw, ledger, _clock = _caller(
        [HttpResponse(200, {}, b"{}")], ceilings=Ceilings(usd=Decimal("0.001"))
    )
    result = caller.call(_spec())
    assert result.response.status == 200
    assert result.over_ceiling is True
    assert [row.over_ceiling for row in ledger.rows] == [True, True]


def test_a_call_the_estimate_cleared_is_still_flagged_when_the_real_cost_blows_the_ceiling() -> (
    None
):
    """The result row's flag is about ACTUAL spend; the estimate row's is about the estimate.

    A ceiling computed only from the pre-wire estimate under-reports exactly the case the cost
    dashboard exists to catch: a call that looked affordable and was not.
    """
    caller, _transport, _raw, ledger, _clock = _caller(
        [HttpResponse(200, {}, b"{}")], ceilings=Ceilings(usd=Decimal("0.05"))
    )

    def expensive(_response: HttpResponse) -> CostReading:
        return CostReading(cost_usd=Decimal("0.90"))

    result = caller.call(_spec(cost_reader=expensive))

    estimate, outcome = ledger.rows
    assert estimate.over_ceiling is False, "$0.01 estimated was under the $0.05 ceiling"
    assert outcome.over_ceiling is True, "$0.90 actually spent was not"
    assert result.over_ceiling is True, "CallResult reports the result row's flag"


def test_the_actual_cost_flag_clears_when_the_real_cost_came_in_under_the_ceiling() -> None:
    """The re-evaluation runs both ways: an over-estimate must not leave a false flag behind."""
    caller, _transport, _raw, ledger, _clock = _caller(
        [HttpResponse(200, {}, b"{}")], ceilings=Ceilings(usd=Decimal("0.005"))
    )

    def cheap(_response: HttpResponse) -> CostReading:
        return CostReading(cost_usd=Decimal("0.001"))

    result = caller.call(_spec(cost_reader=cheap))

    estimate, outcome = ledger.rows
    assert estimate.over_ceiling is True, "$0.01 estimated was over the $0.005 ceiling"
    assert outcome.over_ceiling is False, "$0.001 actually spent was not"
    assert result.over_ceiling is False


def test_a_response_header_carrying_a_capability_url_is_redacted_in_the_saved_record() -> None:
    """Constraint 5 is about credentials, not only about API keys.

    The Files API answers ``files.start`` with ``x-goog-upload-url`` — a pre-authorised URL whose
    holder can push bytes into our storage on our billing. Redacting only the *request* URL of the
    next call leaves that capability verbatim in a record that becomes an ``artifact`` row at A7.
    """
    upload_url = "https://upload.googleapis.com/upload/v1beta/files?upload_id=CAP_TOKEN&upl=raw"
    caller, _transport, raw, _ledger, _clock = _caller(
        [HttpResponse(200, {"X-Goog-Upload-URL": upload_url, "x-request-id": "r-1"}, b"{}")]
    )
    result = caller.call(_spec())

    record, _body = raw.records[0]
    assert "CAP_TOKEN" not in repr(record)
    assert "upload_id=" not in repr(record.response.headers)
    assert record.response.headers["x-request-id"] == "r-1", "ordinary headers are untouched"
    assert result.response.headers["x-goog-upload-url"] == upload_url, (
        "the client still needs the real URL to upload to; only the durable record is redacted"
    )


def test_a_credential_bearing_url_in_any_other_header_value_is_redacted_too() -> None:
    """The fix closes the class, not the one instance: every value goes through ``redact_url``."""
    caller, _transport, raw, _ledger, _clock = _caller(
        [HttpResponse(200, {"Location": "https://provider.test/next?key=LEAKED&page=2"}, b"{}")]
    )
    caller.call(_spec())

    record, _body = raw.records[0]
    assert record.response.headers["location"] == "https://provider.test/next?key=***&page=2"


def test_a_binary_request_body_is_stored_by_hash_and_size_not_inlined() -> None:
    """``binary_request`` governs the REQUEST body, which is the biggest one the lane sends.

    ``transcribe_short`` base64-encodes a whole audio clip into a JSON body, so it decodes as
    UTF-8 perfectly well and would otherwise be copied into every attempt's record.
    """
    audio_json = b'{"data":"' + b"A" * 200 + b'"}'
    caller, _transport, raw, _ledger, _clock = _caller([HttpResponse(200, {}, b"{}")])
    caller.call(_spec(request=_request_with_body(audio_json), binary_request=True))

    record, _body = raw.records[0]
    assert record.request.body_text is None
    assert record.request.body_sha256 == sha256_hex(audio_json)
    assert record.request.body_bytes == len(audio_json)


def test_an_oversized_request_body_is_content_addressed_even_without_the_flag() -> None:
    """The cap is the backstop: a call site that forgets the flag still cannot write megabytes."""
    big = b'{"d":"' + b"B" * (MAX_INLINE_REQUEST_CHARS + 1) + b'"}'
    small = b'{"d":"' + b"C" * 10 + b'"}'
    caller, _transport, raw, _ledger, _clock = _caller(
        [HttpResponse(200, {}, b"{}"), HttpResponse(200, {}, b"{}")]
    )

    caller.call(_spec(request=_request_with_body(big)))
    caller.call(_spec(request=_request_with_body(small)))

    oversized, _ = raw.records[0]
    assert oversized.request.body_text is None
    assert oversized.request.body_sha256 == sha256_hex(big)
    assert oversized.request.body_bytes == len(big)

    inlined, _ = raw.records[1]
    assert inlined.request.body_text == small.decode(), "an ordinary body is still inlined"


def test_a_scrubber_that_raises_still_leaves_the_attempt_and_the_cost_in_the_trail() -> None:
    """Law 3 forbids keeping the body; law 1 still requires the attempt to exist.

    The scrubber is a public extension point, and the module's own promise is that a body which
    crashes a parser is still on disk and still replayable. A scrubber failure must therefore not
    escape before anything was written — that would leave an orphan estimate row for a call that
    was made and paid for.
    """

    def explode(_body: object) -> object:
        raise RuntimeError("scrubber blew up on an unexpected shape")

    caller, _transport, raw, ledger, _clock = _caller(
        [HttpResponse(200, {}, b'{"name":"Sanaz","birth_date":"1979-01-01"}')]
    )

    with pytest.raises(RawScrubFailed) as excinfo:
        caller.call(_spec(raw_scrubber=explode))

    assert excinfo.value.raw_ref == "memory:0"
    assert excinfo.value.provider == "prov"

    record, stored = raw.records[0]
    assert stored == b"", "the unscrubbed bytes are on no path"
    assert record.response.body_text is None
    assert "birth_date" not in repr(record)
    assert record.response.body_sha256 == sha256_hex(
        b'{"name":"Sanaz","birth_date":"1979-01-01"}'
    ), "the attempt is still identified by what actually came back"
    assert record.response.body_bytes == 42

    estimate, outcome = ledger.rows
    assert estimate.phase == "estimate"
    assert (outcome.phase, outcome.error_code) == ("result", "raw_scrub_failed")
    assert outcome.http_status == 200
    assert outcome.cost_usd == Decimal("0.01"), "the call happened, so it is in the money trail"
    assert caller.totals().usd == Decimal("0.01")


def test_json_on_a_non_json_body_raises_with_the_raw_reference() -> None:
    """(h) The parse failure names the record on disk, so it is always replayable."""
    caller, _transport, _raw, _ledger, _clock = _caller(
        [HttpResponse(200, {"Content-Type": "text/html"}, b"<html>nope</html>")]
    )
    result = caller.call(_spec())
    with pytest.raises(RawParseError) as excinfo:
        result.json()
    assert excinfo.value.raw_ref == result.raw_ref == "memory:0"


def test_a_binary_body_is_stored_by_hash_and_size_not_as_text() -> None:
    """(i) An audio body has no text form; the record carries its address and length."""
    audio = b"\x00\x01\x02\xff"
    caller, _transport, raw, _ledger, _clock = _caller([HttpResponse(200, {}, audio)])
    caller.call(_spec(binary=True))

    record, stored = raw.records[0]
    assert record.response.body_text is None
    assert record.response.body_sha256 == sha256_hex(audio)
    assert record.response.body_bytes == 4
    assert stored == audio


def test_an_unreadable_cost_falls_back_to_the_estimate_and_says_so() -> None:
    """A cost reader that raises never fails the call; the row records the substitution."""

    def broken(_response: HttpResponse) -> CostReading:
        raise ValueError("usage block missing")

    caller, _transport, _raw, ledger, _clock = _caller([HttpResponse(200, {}, b"{}")])
    result = caller.call(_spec(cost_reader=broken))

    row = ledger.rows[-1]
    assert row.error_code == "cost_unreadable"
    assert row.cost_usd == Decimal("0.01")
    assert row.extras["cost_source"] == "estimate"
    assert result.cost == CostReading()
    assert caller.totals().usd == Decimal("0.01")


def test_a_plain_client_error_is_recorded_and_returned() -> None:
    """A 404 is not retried and not an exception: it is a result the caller must interpret."""
    caller, _transport, _raw, ledger, clock = _caller([HttpResponse(404, {}, b"nope")])
    result = caller.call(_spec())
    assert result.attempts == 1
    assert clock.sleeps == []
    assert ledger.rows[-1].outcome == "client_error"


def test_a_refusal_row_carries_the_classified_provider_failure() -> None:
    body = (
        b"{'error': {'message': 'Key limit exceeded (weekly limit). "
        b"Manage it using https://openrouter.ai/x', 'code': 403}}"
    )
    caller, _, _, ledger, _ = _caller([HttpResponse(403, {}, body)])
    spec = _spec(
        provider="openrouter",
        operation="chat/completions",
        label="display-overview-what-they-do",
        max_attempts=1,
    )
    result = caller.call(spec)
    assert result.response.status == 403
    (row,) = [r for r in ledger.rows if r.phase == "result"]
    assert row.extras["provider_failure"] == {
        "kind": "refusal",
        "reason": "key_limit",
        "message": "Key limit exceeded (weekly limit). Manage it using https://openrouter.ai/x",
    }


def test_a_halt_row_carries_the_classification_too() -> None:
    body = b'{"error":"payment_required"}'
    caller, _, _, ledger, _ = _caller([HttpResponse(402, {}, body)])
    spec = _spec(
        provider="exa_websets",
        operation="websets:create",
        label="websets",
        max_attempts=1,
        halt_rule=lambda r: "payment_required" if r.status == 402 else None,
    )
    with pytest.raises(ProviderHalted):
        caller.call(spec)
    (row,) = [r for r in ledger.rows if r.phase == "result"]
    assert row.outcome == "halted"
    assert row.extras["provider_failure"] == {
        "kind": "refusal",
        "reason": "credits_exhausted",
        "message": "payment_required",
    }


def test_a_transport_error_row_is_a_timeout_failure_and_a_success_row_carries_nothing() -> None:
    caller, _, _, ledger, _ = _caller([TransportFailure("connection reset")])
    with pytest.raises(ProviderTransportError):
        caller.call(_spec(provider="live_http", max_attempts=1))
    (row,) = [r for r in ledger.rows if r.phase == "result"]
    assert row.extras["provider_failure"] == {
        "kind": "failure",
        "reason": "timeout",
        "message": "connection reset",
    }
    caller, _, _, ledger, _ = _caller([HttpResponse(200, {}, b"{}")])
    caller.call(_spec(max_attempts=1))
    (ok,) = [r for r in ledger.rows if r.phase == "result"]
    assert "provider_failure" not in ok.extras


@pytest.mark.parametrize(
    ("first", "reason", "delay"),
    [
        (HttpResponse(429, {"retry-after": "7"}, b"{}"), "http_429", 7.0),
        (TransportFailure("private URL or credential"), "transport_error", 2.0),
    ],
)
def test_attempt_logs_correlate_retries_without_request_or_error_secrets(first, reason, delay):
    from structlog.testing import capture_logs

    caller, transport, _raw, _ledger, clock = _caller([first, HttpResponse(200, {}, b"{}")])
    with capture_logs() as logs:
        caller.call(_spec(provider="exa", max_attempts=2))
    events = [r for r in logs if r["event"].startswith("provider.")]
    assert [r["event"] for r in events] == [
        "provider.attempt.started",
        "provider.attempt.finished",
        "provider.retry.scheduled",
        "provider.attempt.started",
        "provider.attempt.finished",
    ]
    assert len({r["call_id"] for r in events}) == 1
    assert [r["attempt"] for r in events] == [1, 1, 1, 2, 2]
    assert events[2]["reason"] == reason
    assert events[2]["delay_s"] == delay
    assert events[1]["elapsed_ms"] > 0 and events[4]["http_status"] == 200
    assert clock.sleeps == [delay] and len(transport.requests) == 2
    assert "private URL or credential" not in str(events)
    assert all("request" not in r and "body" not in r for r in events)


def test_exhausted_attempt_is_logged_without_scheduling_another_retry():
    from structlog.testing import capture_logs

    caller, _transport, _raw, _ledger, clock = _caller([TransportFailure("secret")])
    with capture_logs() as logs, pytest.raises(ProviderTransportError):
        caller.call(_spec(max_attempts=1))
    assert [r["event"] for r in logs if r["event"].startswith("provider.")] == [
        "provider.attempt.started",
        "provider.attempt.finished",
    ]
    assert logs[-1]["error_type"] == "TransportFailure"
    assert not clock.sleeps


def test_attempt_and_backoff_have_langfuse_spans(monkeypatch):
    from contextlib import contextmanager

    import clue_spend.calls as calls
    from clue_obs.langfuse import NullObservation

    spans = []

    @contextmanager
    def record(name, **fields):
        spans.append((name, fields))
        yield NullObservation(id="observation-id", trace_id="trace-id")

    monkeypatch.setattr(calls, "observation", record)
    caller, _transport, _raw, _ledger, _clock = _caller(
        [
            HttpResponse(503, {}, b"{}"),
            HttpResponse(200, {}, b"{}"),
        ]
    )
    caller.call(_spec(max_attempts=2))
    assert [name for name, _ in spans] == [
        "prov.v1/thing",
        "provider.http_attempt",
        "provider.retry_wait",
        "provider.http_attempt",
    ]
    assert spans[2][1]["metadata"]["reason"] == "http_503"


def test_attempt_start_is_visible_before_transport_and_interruption_is_recorded(monkeypatch):
    from structlog.testing import capture_logs

    caller, transport, _raw, _ledger, clock = _caller([])
    with capture_logs() as logs:

        def interrupt(_request):
            assert logs[-1]["event"] == "provider.attempt.started"
            raise KeyboardInterrupt()

        monkeypatch.setattr(transport, "send", interrupt)
        with pytest.raises(KeyboardInterrupt):
            caller.call(_spec())
    assert logs[-1]["event"] == "provider.attempt.finished"
    assert logs[-1]["outcome"] == "interrupted"
    assert not clock.sleeps
