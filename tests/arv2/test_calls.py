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
    CallSpec,
    Ceilings,
    CostReading,
    ProviderCaller,
    SpendEstimate,
)
from clue_api.arv2.errors import ProviderHalted, ProviderTransportError, RawParseError
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
    assert "cost_source" not in outcome.extras
    assert result.over_ceiling is False and outcome.over_ceiling is False
    assert result.ledger_row_id == outcome.row_id
    assert result.json() == {"ok": True}
    assert caller.totals().usd == Decimal("0.02")
    assert caller.totals().credits == Decimal("3")


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
        url="https://provider.test/v1/models/m:generate?key=SUPERSECRET&alt=json",
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
    assert record.request.url == "https://provider.test/v1/models/m:generate?key=***&alt=json"
    assert record.request.headers == {
        "Authorization": "***",
        "X-TOKEN": "***",
        "x-api-key": "***",
        "X-Goog-Api-Key": "***",
        "Accept": "application/json",
    }
    serialized = repr(record)
    for secret in ("SUPERSECRET", "sk-live-000", "ark-000", "exa-000", "goog-000"):
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
