"""clue-obs (Doc R R0) — setup idempotence, capture, redaction, spans, truncation."""

from __future__ import annotations

import logging

from clue_obs import (
    bound_context,
    capture_events,
    get_logger,
    is_claim_value_key,
    is_secret_key,
    log_span,
    mask_blob,
    redact_value,
    setup,
)


def test_setup_is_idempotent() -> None:
    """A second setup() replaces the first — never accumulates handlers."""
    setup(mode="info")
    first = [h for h in logging.getLogger().handlers if getattr(h, "_clue_obs_handler", False)]
    setup(mode="debug")
    second = [h for h in logging.getLogger().handlers if getattr(h, "_clue_obs_handler", False)]
    assert len(first) == len(second) == 1


def test_capture_records_events_with_bound_context() -> None:
    with capture_events(mode="info") as cap:
        log = get_logger("clue_research.test")
        with bound_context(workspace_id="ws_1", actor="agent"):
            log.info("thing_happened", detail="ok")
    event = cap.first("thing_happened")
    assert event is not None
    assert event["workspace_id"] == "ws_1"
    assert event["actor"] == "agent"
    assert event["detail"] == "ok"


def test_stdlib_records_flow_through_the_bridge() -> None:
    """Foreign logging.getLogger records get the identical chain treatment."""
    with capture_events(mode="info") as cap:
        logging.getLogger("uvicorn.error").warning("foreign_event")
    assert cap.has("foreign_event")


def test_secret_keys_masked_even_in_debug() -> None:
    with capture_events(mode="debug") as cap:
        get_logger("t").info("call_made", api_key="sk-12345", authorization="Bearer x")
    event = cap.first("call_made")
    assert event is not None
    assert event["api_key"] == "***"
    assert event["authorization"] == "***"


def test_claim_values_masked_ids_only_rule() -> None:
    """Personal-claim values never land in logs — ids only (Doc R §4 DSAR rule)."""
    with capture_events(mode="debug") as cap:
        get_logger("t").info(
            "claim_written",
            claim_id="clm_1",
            field_key="contact.facet.faith",
            value_json='"observant"',
            evidence_span="he mentioned his faith in the interview",
        )
    event = cap.first("claim_written")
    assert event is not None
    assert event["claim_id"] == "clm_1"  # ids survive
    assert "observant" not in str(event["value_json"])
    assert "faith in the interview" not in str(event["evidence_span"])


def test_redact_value_pure_helpers() -> None:
    assert is_secret_key("CLUE_OPENROUTER_API_KEY")
    assert not is_secret_key("message")
    assert is_claim_value_key("value_json")
    assert redact_value({"password": "hunter2"})["password"] == "***"
    blob = "data:image/png;base64," + "A" * 400
    assert mask_blob(blob).startswith("<base64 png")


def test_log_span_emits_started_completed_with_duration() -> None:
    with capture_events(mode="info") as cap, log_span("unit_of_work", field_key="client.industry"):
        pass
    assert cap.has("unit_of_work_started")
    done = cap.first("unit_of_work_completed")
    assert done is not None
    assert done["duration_ms"] >= 0
    assert done["field_key"] == "client.industry"


def test_log_span_failure_emits_failed_and_reraises() -> None:
    with capture_events(mode="info") as cap:
        try:
            with log_span("doomed"):
                raise ValueError("boom")
        except ValueError:
            pass
        else:  # pragma: no cover
            raise AssertionError("exception must re-raise")
    failed = cap.first("doomed_failed")
    assert failed is not None
    assert failed["error_type"] == "ValueError"


def test_log_span_logs_an_expected_refusal_at_warning_and_anything_else_at_error() -> None:
    """R6 (2026-10-03 spec): a refusal the caller expects (a tool precondition the agent repairs)
    is a warning, so Sentry's logging integration (which reports error and above) never pages on
    it; an unexpected exception stays an error with its traceback."""

    class Refused(RuntimeError):
        pass

    with capture_events(mode="info") as cap:
        for exc in (Refused("no_discovery_run"), ValueError("boom")):
            try:
                with log_span("tool", expected=(Refused,)):
                    raise exc
            except (Refused, ValueError):
                pass
    refused, crashed = cap.events("tool_failed")
    assert refused["level"] == "warning" and refused["error_type"] == "Refused"
    assert refused["error"] == "no_discovery_run" and "exception" not in refused
    assert crashed["level"] == "error" and crashed["error_type"] == "ValueError"


def test_info_mode_truncates_long_strings() -> None:
    with capture_events(mode="info") as cap:
        get_logger("t").info("big_payload", body="long prose word " * 100)
    event = cap.first("big_payload")
    assert event is not None
    assert len(event["body"]) < 1000
    assert "chars)" in event["body"]
