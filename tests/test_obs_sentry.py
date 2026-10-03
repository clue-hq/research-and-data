"""Lane 3 slice 2, Task 3: Sentry with the ruled posture — ids as tags, never customer text."""

from __future__ import annotations

from typing import Any

import sentry_sdk
from sentry_sdk.transport import Transport

from clue_obs import bound_context
from clue_obs.otel import collect_spans, traced_step
from clue_obs.otel.trace_ids import remember_trace
from clue_obs.sentry import capture, install_sentry, sentry_is_installed
from tests._langfuse import langfuse_installed


class StubTransport(Transport):
    def __init__(self, options: Any = None) -> None:
        super().__init__(options)
        self.envelopes: list[Any] = []

    def capture_envelope(self, envelope: Any) -> None:
        self.envelopes.append(envelope)


def test_no_dsn_installs_nothing_and_capture_is_a_noop() -> None:
    assert install_sentry(dsn=None, environment="t", release=None, process_name="p") is False
    assert install_sentry(dsn="  ", environment="t", release=None, process_name="p") is False
    capture(RuntimeError("ignored"))  # must not raise


def test_an_event_carries_the_bound_ids_as_tags_no_locals_and_redacted_extras() -> None:
    transport = StubTransport()
    assert install_sentry(
        dsn="https://public@o0.ingest.sentry.io/1",
        environment="lane-test",
        release="abc123",
        process_name="clue-test",
        transport=transport,
    )
    assert sentry_is_installed()
    try:
        with (
            bound_context(workspace_id="ws_1", turn_id="turn_1", api_key="sk-secret"),
            sentry_sdk.new_scope() as scope,
        ):
            scope.set_extra("api_key", "sk-secret")
            scope.set_extra("count", 3)
            try:
                raise RuntimeError("boom")
            except RuntimeError as exc:
                capture(exc)
        sentry_sdk.flush(timeout=5)
        events = [env.get_event() for env in transport.envelopes if env.get_event() is not None]
        assert len(events) == 1
        event = events[0]
        assert event["environment"] == "lane-test" and event["release"] == "abc123"
        assert event["tags"]["workspace_id"] == "ws_1" and event["tags"]["turn_id"] == "turn_1"
        assert "api_key" not in event["tags"]
        assert event["extra"]["api_key"] != "sk-secret"
        assert event["extra"]["count"] == 3
        frames = event["exception"]["values"][0]["stacktrace"]["frames"]
        assert all("vars" not in frame for frame in frames)
    finally:
        sentry_sdk.get_client().close()


def _install_with_langfuse(transport: StubTransport) -> None:
    assert install_sentry(
        dsn="https://public@o0.ingest.sentry.io/1",
        environment="lane-test",
        release=None,
        process_name="clue-test",
        transport=transport,
        langfuse_host="https://us.cloud.langfuse.com/",
    )


def _events(transport: StubTransport) -> list[Any]:
    sentry_sdk.flush(timeout=5)
    return [env.get_event() for env in transport.envelopes if env.get_event() is not None]


def test_an_event_carries_the_opentelemetry_trace_id_and_a_langfuse_link() -> None:
    """R5 (2026-10-03 spec): the trace id on a Sentry event is the one in the logs and Langfuse."""
    transport = StubTransport()
    _install_with_langfuse(transport)
    try:
        with langfuse_installed(), collect_spans(), traced_step("fleet.task") as span:
            try:
                raise RuntimeError("boom")
            except RuntimeError as exc:
                capture(exc)
        (event,) = _events(transport)
        trace_id = format(span.get_span_context().trace_id, "032x")
        assert event["contexts"]["trace"]["trace_id"] == trace_id
        assert event["contexts"]["trace"]["span_id"] == format(
            span.get_span_context().span_id, "016x"
        )
        assert event["tags"]["trace_id"] == trace_id
        assert event["contexts"]["langfuse"] == {
            "trace_url": f"https://us.cloud.langfuse.com/trace/{trace_id}"
        }
    finally:
        sentry_sdk.get_client().close()


def test_an_error_reported_after_its_span_closed_carries_the_remembered_trace() -> None:
    transport = StubTransport()
    _install_with_langfuse(transport)
    try:
        with collect_spans(), traced_step("fleet.task") as span:
            error = RuntimeError("boom")
            remember_trace(error)
        try:
            raise error
        except RuntimeError as exc:
            capture(exc)
        (event,) = _events(transport)
        trace_id = format(span.get_span_context().trace_id, "032x")
        assert event["contexts"]["trace"]["trace_id"] == trace_id
        assert event["tags"]["trace_id"] == trace_id
    finally:
        sentry_sdk.get_client().close()


def test_no_langfuse_link_when_langfuse_is_not_installed() -> None:
    """A deployment with Langfuse switched on but keyless installs no client; its events keep the
    trace id and get no link to a trace that was never exported."""
    transport = StubTransport()
    _install_with_langfuse(transport)
    try:
        with collect_spans(), traced_step("fleet.task") as span:
            capture(RuntimeError("boom"))
        (event,) = _events(transport)
        assert event["tags"]["trace_id"] == format(span.get_span_context().trace_id, "032x")
        assert "langfuse" not in event.get("contexts", {})
    finally:
        sentry_sdk.get_client().close()


def test_an_event_with_no_trace_has_no_trace_tag_or_link() -> None:
    transport = StubTransport()
    _install_with_langfuse(transport)
    try:
        capture(RuntimeError("boom"))
        (event,) = _events(transport)
        assert "trace_id" not in event.get("tags", {})
        assert "langfuse" not in event.get("contexts", {})
    finally:
        sentry_sdk.get_client().close()
