"""The buffered sinks the worker thread writes into, before the async side drains them."""

from __future__ import annotations

import threading
from datetime import UTC, datetime
from decimal import Decimal

from clue_api.arv2.provider_ledger import BufferedLedger, BufferedRawSink, artifact_payload
from clue_api.arv2.sinks import (
    LedgerRow,
    LedgerSink,
    RawRecord,
    RawRequest,
    RawResponse,
    RawSink,
    sha256_hex,
)


def _record(now: datetime) -> RawRecord:
    return RawRecord(
        call_id="7b1c2e4a-0f3d-4c7e-9a1b-2d3e4f5a6b7c",
        provider="exa",
        operation="search",
        label="t",
        attempt=1,
        recorded_at=now,
        latency_ms=5,
        request=RawRequest(
            method="POST",
            url="https://api.exa.ai/search",
            headers={},
            body_text='{"q":1}',
            body_sha256=sha256_hex(b'{"q":1}'),
            body_bytes=7,
        ),
        response=RawResponse(
            status=200, headers={}, body_text="{}", body_sha256=sha256_hex(b"{}"), body_bytes=2
        ),
    )


def test_the_buffers_are_the_sinks_the_caller_takes() -> None:
    """Typed here rather than asserted: the caller is constructed with these two, so a signature
    drift has to fail the type gate, not surface as a runtime error mid-run."""
    raw: RawSink = BufferedRawSink()
    ledger: LedgerSink = BufferedLedger()
    assert raw.save(_record(datetime.now(UTC)), b"{}").startswith("raw:")
    assert (
        ledger.record(
            LedgerRow(
                row_id="r1",
                call_id="c1",
                phase="estimate",
                provider="exa",
                operation="search",
                label="t",
                recorded_at=datetime.now(UTC),
            )
        )
        == "r1"
    )


def test_raw_sink_ref_is_content_addressed_and_drain_clears() -> None:
    sink = BufferedRawSink()
    ref = sink.save(_record(datetime.now(UTC)), b"{}")
    assert ref == f"raw:{sha256_hex(b'{}')}"
    drained = sink.drain()
    assert [d[0] for d in drained] == [ref]
    assert sink.drain() == []


def test_ledger_buffers_rows_in_order() -> None:
    ledger = BufferedLedger()
    row = LedgerRow(
        row_id="r1",
        call_id="c1",
        phase="estimate",
        provider="exa",
        operation="search",
        label="t",
        recorded_at=datetime.now(UTC),
        estimate_usd=Decimal("0.01"),
    )
    assert ledger.record(row) == "r1"
    assert [r.row_id for r in ledger.drain()] == ["r1"]
    assert ledger.drain() == []


def test_both_buffers_keep_every_row_written_from_many_threads() -> None:
    """The caller runs in ``asyncio.to_thread``; two account steps can share one buffer."""
    sink, ledger = BufferedRawSink(), BufferedLedger()
    now = datetime.now(UTC)

    def write(index: int) -> None:
        for step in range(20):
            body = f"body-{index}-{step}".encode()
            sink.save(_record(now), body)
            ledger.record(
                LedgerRow(
                    row_id=f"r{index}-{step}",
                    call_id="c1",
                    phase="result",
                    provider="exa",
                    operation="search",
                    label="t",
                    recorded_at=now,
                )
            )

    threads = [threading.Thread(target=write, args=(i,)) for i in range(8)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    assert len(sink.drain()) == 8 * 20
    assert len({row.row_id for row in ledger.drain()}) == 8 * 20


def test_artifact_payload_inlines_utf8_and_base64s_everything_else() -> None:
    now = datetime.now(UTC)
    text_payload = artifact_payload(_record(now), b'{"ok":true}')
    assert b'"body_utf8": "{\\"ok\\":true}"' in text_payload
    assert b'"body_base64": null' in text_payload
    assert now.isoformat().encode() in text_payload

    binary_payload = artifact_payload(_record(now), b"\xff\xfe\x00")
    assert b'"body_utf8": null' in binary_payload
    assert b'"body_base64": "//4A"' in binary_payload
