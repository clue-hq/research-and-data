"""Tests for the shared observability package `py_lumen_obs` (L1).

Covers: configure idempotence, the stdlib bridge, the redaction table,
mode-aware truncation, the untruncated run-file, log_span lifecycle, context
binding, and the rich-absence tolerance guarantee.
"""
from __future__ import annotations

import json
import logging
import sys

import pytest

import py_lumen_obs as obs
from py_lumen_obs import LogMode
from py_lumen_obs.redact import is_secret_key, mask_blob, redact_value
from py_lumen_obs.testing import capture_events


@pytest.fixture(autouse=True)
def _restore_logging():
    """Isolate global logging/structlog state per test."""
    import structlog

    root = logging.getLogger()
    saved_handlers = root.handlers[:]
    saved_level = root.level
    try:
        yield
    finally:
        for h in list(root.handlers):
            if getattr(h, "_lumen_obs_handler", False):
                h.close()
        root.handlers[:] = saved_handlers
        root.setLevel(saved_level)
        structlog.reset_defaults()
        structlog.contextvars.clear_contextvars()


# --- configure idempotence ------------------------------------------------


def _owned_handlers():
    return [h for h in logging.getLogger().handlers if getattr(h, "_lumen_obs_handler", False)]


def test_configure_is_idempotent(tmp_path):
    obs.configure(mode=LogMode.INFO)
    obs.configure(mode=LogMode.INFO)
    # Two calls, one console handler — the second replaced the first cleanly.
    owned = _owned_handlers()
    assert len(owned) == 1
    assert all(isinstance(h, logging.StreamHandler) for h in owned)

    # Reconfigure with a run file: replaces cleanly, now console + file.
    obs.configure(mode=LogMode.DEBUG, run_log_path=tmp_path / "logs" / "run.jsonl")
    owned = _owned_handlers()
    assert len(owned) == 2
    assert logging.getLogger().level == logging.DEBUG


# --- stdlib bridge --------------------------------------------------------


def test_stdlib_logger_flows_through_bridge():
    with capture_events(mode=LogMode.INFO) as cap:
        std = logging.getLogger("uvicorn.error")
        std.warning("foreign warning here")
    entry = cap.first("foreign warning here")
    assert entry is not None
    assert entry["level"] == "warning"
    assert entry["logger"] == "uvicorn.error"
    assert "timestamp" in entry


def test_bridge_carries_structured_context():
    with capture_events(mode=LogMode.INFO) as cap:
        obs.bind_context(run_id="run_xyz")
        logging.getLogger("lumen_api.core").info("bridged event")
    entry = cap.first("bridged event")
    assert entry is not None
    assert entry["run_id"] == "run_xyz"


# --- redaction table ------------------------------------------------------


@pytest.mark.parametrize(
    "key,secret",
    [
        ("api_key", True),
        ("openrouter_api_key", True),
        ("Authorization", True),
        ("session_token", True),
        ("access_token", True),
        ("cookie", True),
        ("client_secret", True),
        ("password", True),
        ("run_id", False),
        ("message", False),
        ("content", False),
        ("block", False),
    ],
)
def test_is_secret_key_table(key, secret):
    assert is_secret_key(key) is secret


def test_redact_processor_masks_secrets_and_blobs_but_not_content():
    with capture_events(mode=LogMode.DEBUG) as cap:  # debug: no truncation muddying the check
        log = obs.get_logger("test.redact")
        log.info(
            "auth_attempt",
            api_key="sk-verysecretvalue",
            authorization="Bearer abc123",
            content="this is normal readable content",
            message="also normal",
            nested={"session_token": "tok_xyz", "note": "fine"},
        )
    e = cap.first("auth_attempt")
    assert e["api_key"] == "***"
    assert e["authorization"] == "***"
    assert e["content"] == "this is normal readable content"
    assert e["message"] == "also normal"
    assert e["nested"]["session_token"] == "***"
    assert e["nested"]["note"] == "fine"


def test_base64_blob_masked_with_size():
    # ~3KB of base64 payload under a non-secret key -> size+kind placeholder.
    png_magic = b"\x89PNG\r\n\x1a\n" + b"\x00" * 3000
    import base64

    b64 = base64.b64encode(png_magic).decode()
    with capture_events(mode=LogMode.DEBUG) as cap:
        obs.get_logger("test.blob").info("upload", image_data=b64)
    e = cap.first("upload")
    assert e["image_data"].startswith("<base64 png ~")
    assert e["image_data"].endswith("KB>")


def test_data_uri_masked():
    assert mask_blob("data:image/jpeg;base64," + "A" * 4000).startswith("<base64 jpeg ~")


def test_redact_value_is_pure():
    assert redact_value("plain") == "plain"
    assert redact_value("secret", "api_key") == "***"
    assert redact_value({"cookie": "x", "ok": 1}) == {"cookie": "***", "ok": 1}


# --- truncation -----------------------------------------------------------


def _long_prose(n: int) -> str:
    # spaces + punctuation so it is NOT mistaken for a base64 blob.
    return ("lorem ipsum dolor sit amet, " * ((n // 28) + 1))[:n]


def test_truncation_at_info_full_at_debug():
    body = _long_prose(900)
    with capture_events(mode=LogMode.INFO) as cap:
        obs.get_logger("test.trunc").info("tool_result", body=body)
    e = cap.first("tool_result")
    assert len(e["body"]) < 900
    assert e["body"].endswith(" chars)")
    assert "… (+" in e["body"]

    with capture_events(mode=LogMode.DEBUG) as cap:
        obs.get_logger("test.trunc").info("tool_result", body=body)
    e = cap.first("tool_result")
    assert e["body"] == body


def test_run_file_full_while_console_truncates(tmp_path):
    run_log = tmp_path / "logs" / "run.jsonl"
    body = _long_prose(900)
    with capture_events(mode=LogMode.INFO, run_log_path=run_log) as cap:
        obs.get_logger("test.runfile").info("tool_result", body=body)
    # console-mirrored capture: truncated
    console_entry = cap.first("tool_result")
    assert len(console_entry["body"]) < 900
    # run file: full detail, untruncated
    lines = [json.loads(line) for line in run_log.read_text().splitlines() if line.strip()]
    file_entry = next(x for x in lines if x.get("event") == "tool_result")
    assert file_entry["body"] == body


def test_run_file_captures_debug_records_in_info_mode(tmp_path):
    run_log = tmp_path / "run.jsonl"
    with capture_events(mode=LogMode.INFO, run_log_path=run_log):
        obs.get_logger("test.debuglevel").debug("verbose_detail", x=1)
    lines = [json.loads(line) for line in run_log.read_text().splitlines() if line.strip()]
    assert any(x.get("event") == "verbose_detail" for x in lines)


# --- log_span -------------------------------------------------------------


def test_log_span_success_emits_started_and_completed_with_duration():
    with capture_events(mode=LogMode.INFO) as cap:
        with obs.log_span("compile_dsl", block="hero"):
            pass
    assert cap.has("compile_dsl_started")
    completed = cap.first("compile_dsl_completed")
    assert completed is not None
    assert completed["block"] == "hero"
    assert isinstance(completed["duration_ms"], (int, float))
    assert not cap.has("compile_dsl_failed")


def test_log_span_failure_emits_failed_and_reraises():
    with capture_events(mode=LogMode.INFO) as cap:
        with pytest.raises(ValueError, match="boom"):
            with obs.log_span("risky_op"):
                raise ValueError("boom")
    assert cap.has("risky_op_started")
    failed = cap.first("risky_op_failed")
    assert failed is not None
    assert failed["error_type"] == "ValueError"
    assert "duration_ms" in failed
    assert not cap.has("risky_op_completed")


def test_log_span_works_as_decorator():
    @obs.log_span("wrapped_call")
    def do_work(a, b):
        return a + b

    with capture_events(mode=LogMode.INFO) as cap:
        result = do_work(2, 3)
    assert result == 5
    assert cap.has("wrapped_call_started")
    assert cap.has("wrapped_call_completed")


# --- context binding ------------------------------------------------------


def test_context_binding_visible_on_events():
    with capture_events(mode=LogMode.INFO) as cap:
        obs.bind_run_id("run_ctx")
        obs.bind_role("author")
        obs.bind_round(2)
        obs.get_logger("test.ctx").info("turn_started")
    e = cap.first("turn_started")
    assert e["run_id"] == "run_ctx"
    assert e["role"] == "author"
    assert e["round"] == 2


def test_clear_context_removes_fields():
    with capture_events(mode=LogMode.INFO) as cap:
        obs.bind_context(run_id="r1")
        obs.clear_context()
        obs.get_logger("test.ctx").info("after_clear")
    e = cap.first("after_clear")
    assert "run_id" not in e


def test_bound_context_scoped():
    with capture_events(mode=LogMode.INFO) as cap:
        log = obs.get_logger("test.scoped")
        with obs.bound_context(turn=1):
            log.info("inside")
        log.info("outside")
    assert cap.first("inside")["turn"] == 1
    assert "turn" not in cap.first("outside")


# --- rich absence tolerated -----------------------------------------------


def test_module_does_not_import_rich():
    # L1 must never hard-depend on rich (that is the L3 viewer's concern).
    #
    # We assert the real invariant — that no py_lumen_obs source file imports
    # rich — rather than `"rich" not in sys.modules`. Since L3's ratified §6.1
    # makes rich a dependency, it is now installed, and `structlog.dev`
    # (imported by py_lumen_obs.processors for ConsoleRenderer) opportunistically
    # imports rich when present. That is structlog's choice, not a py_lumen_obs
    # dependency: the package still imports and configures with zero direct rich
    # use, which is what "must never hard-depend on rich" actually means.
    import pathlib

    pkg_dir = pathlib.Path(obs.__file__).resolve().parent
    for src in pkg_dir.glob("*.py"):
        text = src.read_text(encoding="utf-8")
        assert "import rich" not in text, f"{src.name} directly imports rich"
    # And the package imported/configured fine (this test running proves it).
    assert obs.configure is not None
