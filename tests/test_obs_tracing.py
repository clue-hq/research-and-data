"""M0.5 acceptance: traced_step emits named spans with redacted attributes."""

from __future__ import annotations

from opentelemetry.sdk.trace import TracerProvider

from clue_core import new_entity_id, new_run_id
from clue_research.obs import (
    SPAN_MERGE_CURRENT_VALUE,
    collect_spans,
    configure_tracing,
    traced,
    traced_step,
)


def test_traced_step_emits_named_span_with_attributes() -> None:
    eid = new_entity_id()
    with (
        collect_spans() as exporter,
        traced_step(
            SPAN_MERGE_CURRENT_VALUE,
            entity_id=eid,
            field_key="account.recent_funding",
            source_tier=1,
        ),
    ):
        pass
    spans = exporter.get_finished_spans()
    assert len(spans) == 1
    span = spans[0]
    assert span.name == "merge.current_value"
    assert span.attributes is not None
    assert span.attributes["entity_id"] == str(eid)  # UUID, present + unmasked
    assert span.attributes["field_key"] == "account.recent_funding"
    assert span.attributes["source_tier"] == 1  # int kept native


def test_secret_attribute_is_redacted_but_uuid_id_is_not() -> None:
    rid = new_run_id()
    with (
        collect_spans() as exporter,
        traced_step("step", api_key="anything", note="sk-live-abcdef0123456789", run_id=rid),
    ):
        pass
    attrs = exporter.get_finished_spans()[0].attributes
    assert attrs is not None
    assert attrs["api_key"] == "***REDACTED***"  # masked by secret-named key
    assert attrs["note"] == "***REDACTED***"  # masked by value shape (key-ish prefix)
    assert attrs["run_id"] == str(rid)  # standard UUID attr NOT mistaken for a token


def test_secret_nested_in_container_attribute_is_redacted() -> None:
    # an extra attribute carrying a container with an embedded secret must not leak
    with (
        collect_spans() as exporter,
        traced_step("step", payload=["safe", "sk-live-secret-abcdef0123"]),
    ):
        pass
    attrs = exporter.get_finished_spans()[0].attributes
    assert attrs is not None
    rendered = str(attrs["payload"])
    assert "sk-live-secret" not in rendered
    assert "***REDACTED***" in rendered


def test_traced_decorator_emits_span() -> None:
    @traced("decorated.op")
    def double(x: int) -> int:
        return x * 2

    with collect_spans() as exporter:
        assert double(3) == 6
    assert exporter.get_finished_spans()[0].name == "decorated.op"


def test_configure_tracing_returns_provider() -> None:
    provider = configure_tracing(console=True)
    assert isinstance(provider, TracerProvider)
    configure_tracing()  # reset to the silent default so later tests are unaffected
