"""L3 message-tracing tests: TraceCallbackHandler + the CLI trace viewer.

Handler tests use the same approach as the usage extractor's (a stubbed LLMResult driven
through a real callback method, asserting on the emitted structured events via
py_lumen_obs's capture fixture). Viewer tests render a synthetic run.jsonl
fixture through the colourless plain-ANSI path — deterministic, no rich needed.
"""
from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from py_lumen_obs import LogMode, capture_events

from lumen_agent import trace as viewer
from lumen_agent.trace_callbacks import (
    TraceCallbackHandler,
    attach_trace_callback,
)


# --------------------------------------------------------------------------- #
# LLMResult builders (reuse the RIDER-2 pattern)
# --------------------------------------------------------------------------- #
def _llm_result_with_usage(text="ok", input_tokens=120, output_tokens=48, total=168):
    from langchain_core.messages import AIMessage
    from langchain_core.outputs import ChatGeneration, LLMResult

    usage = {
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "total_tokens": total,
    }
    message = AIMessage(content=text, usage_metadata=usage)
    gen = ChatGeneration(message=message, generation_info={"finish_reason": "stop"})
    return LLMResult(generations=[[gen]])


def _chat_messages_with_image():
    from langchain_core.messages import HumanMessage, SystemMessage

    # A real PNG header + padding, base64-encoded, long enough to be a "blob".
    import base64

    png = b"\x89PNG\r\n\x1a\n" + b"\x00\x00\x00\rIHDR" + (0).to_bytes(4, "big")
    png = png + (16).to_bytes(4, "big") + b"\x00" * 400  # fake 16x0 header + bulk
    b64 = base64.b64encode(png).decode()
    return [
        [
            SystemMessage(content="You are a designer."),
            HumanMessage(
                content=[
                    {"type": "text", "text": "make it pop"},
                    {
                        "type": "image_url",
                        "image_url": {"url": f"data:image/png;base64,{b64}"},
                    },
                ]
            ),
        ]
    ]


# --------------------------------------------------------------------------- #
# 1. started/completed emit with usage + duration
# --------------------------------------------------------------------------- #
def test_started_and_completed_emit_usage_and_duration():
    with capture_events(mode=LogMode.DEBUG) as cap:
        handler = TraceCallbackHandler(role="author")
        rid = "run-1"
        handler.on_chat_model_start(
            {"kwargs": {"model": "openai:x"}}, [[]], run_id=rid
        )
        handler.on_llm_end(_llm_result_with_usage(), run_id=rid)

    started = cap.first("llm_call_started")
    assert started is not None
    assert started["role"] == "author"
    assert started["model"] == "openai:x"

    completed = cap.first("llm_call_completed")
    assert completed is not None
    assert completed["role"] == "author"
    assert completed["input_tokens"] == 120
    assert completed["output_tokens"] == 48
    assert completed["total_tokens"] == 168
    assert completed["finish_reason"] == "stop"
    assert completed["completion"] == "ok"
    assert isinstance(completed["duration_ms"], int)


# --------------------------------------------------------------------------- #
# 2. images placeholdered — no raw base64 in the logged event
# --------------------------------------------------------------------------- #
def test_image_content_is_placeholdered(monkeypatch):
    monkeypatch.setenv("LUMEN_LOG_MODE", "debug")  # so messages are attached
    with capture_events(mode=LogMode.DEBUG) as cap:
        handler = TraceCallbackHandler(role="reviewer")
        handler.on_chat_model_start(
            {}, _chat_messages_with_image(), run_id="r"
        )
    started = cap.first("llm_call_started")
    assert started is not None
    blob = json.dumps(started)
    # The data-URI base64 payload must NOT survive into the event.
    assert "iVBOR" not in blob  # PNG base64 magic prefix
    assert "base64," not in blob
    assert "<image" in blob
    # The text content is preserved (never redacted).
    assert "make it pop" in blob


def test_messages_omitted_when_not_debug(monkeypatch):
    monkeypatch.setenv("LUMEN_LOG_MODE", "info")
    with capture_events(mode=LogMode.DEBUG) as cap:
        handler = TraceCallbackHandler(role="author")
        handler.on_chat_model_start({}, _chat_messages_with_image(), run_id="r")
    started = cap.first("llm_call_started")
    assert "messages" not in started
    assert started["message_count"] == 2


# --------------------------------------------------------------------------- #
# 3. handler exception never propagates (warn-once)
# --------------------------------------------------------------------------- #
def test_handler_exception_does_not_propagate():
    handler = TraceCallbackHandler(role="orchestrator")

    class _Boom:
        @property
        def generations(self):
            raise RuntimeError("boom")

    with capture_events(mode=LogMode.DEBUG) as cap:
        # Must not raise even though extraction blows up.
        handler.on_llm_end(_Boom(), run_id="x")
        handler.on_llm_end(_Boom(), run_id="y")

    # Warned exactly once.
    assert len(cap.events("trace_callback_warning")) == 1


def test_tool_and_subagent_events():
    with capture_events(mode=LogMode.DEBUG) as cap:
        h = TraceCallbackHandler(role="orchestrator")
        # A regular tool.
        h.on_tool_start({"name": "compile_dsl_block"}, "src", run_id="t1", inputs={"source": "a"})
        h.on_tool_end("compiled ok", run_id="t1", name="compile_dsl_block")
        # The task delegation tool → subagent boundary events.
        h.on_tool_start(
            {"name": "task"}, "", run_id="t2", inputs={"subagent_type": "lumen-dsl-author"}
        )
        h.on_tool_end("done", run_id="t2")

    assert cap.has("tool_started")
    assert cap.has("tool_completed")
    sub_start = cap.first("subagent_started")
    assert sub_start["subagent"] == "lumen-dsl-author"
    assert cap.first("subagent_completed")["subagent"] == "lumen-dsl-author"


def test_attach_trace_callback_appends_and_is_safe():
    class _Model:
        def __init__(self):
            self.callbacks = None

    m = _Model()
    attach_trace_callback(m, role="author")
    assert any(isinstance(c, TraceCallbackHandler) for c in m.callbacks)
    assert m.callbacks[0]._role == "author"

    # A sentinel without a callbacks field is left untouched (no crash).
    class _Sentinel:
        pass

    s = _Sentinel()
    assert attach_trace_callback(s, role="x") is s


# --------------------------------------------------------------------------- #
# Viewer tests — synthetic run.jsonl, colourless deterministic render
# --------------------------------------------------------------------------- #
_FIXTURE = [
    {
        "event": "llm_call_started",
        "role": "orchestrator",
        "model": "openai:orch",
        "message_count": 2,
        "round": 1,
        "timestamp": "2026-07-10T01:04:30.000000Z",
    },
    {
        "event": "llm_call_completed",
        "role": "orchestrator",
        "model": "openai:orch",
        "completion": "delegating now",
        "tool_calls": [{"name": "task", "args": {"subagent_type": "lumen-dsl-author"}}],
        "input_tokens": 14200,
        "output_tokens": 1800,
        "total_tokens": 16000,
        "duration_ms": 42000,
        "finish_reason": "tool_calls",
        "round": 1,
        "timestamp": "2026-07-10T01:04:32.000000Z",
    },
    {
        "event": "llm_call_completed",
        "role": "author",
        "model": "openai:auth",
        "completion": "wrote the hero block",
        "tool_calls": [],
        "input_tokens": 8000,
        "output_tokens": 500,
        "total_tokens": 8500,
        "duration_ms": 12000,
        "finish_reason": "stop",
        "round": 1,
        "timestamp": "2026-07-10T01:05:10.000000Z",
    },
    {
        "event": "tool_completed",
        "role": "author",
        "name": "compile_dsl_block",
        "result": "ok",
        "duration_ms": 300,
        "round": 1,
        "timestamp": "2026-07-10T01:05:11.000000Z",
    },
]


def _write_fixture(tmp_path: Path) -> Path:
    p = tmp_path / "run.jsonl"
    p.write_text("\n".join(json.dumps(e) for e in _FIXTURE) + "\n", encoding="utf-8")
    return p


def test_viewer_renders_timeline_and_totals(tmp_path):
    path = _write_fixture(tmp_path)
    events = list(viewer._parse_lines(path.read_text().splitlines()))
    report = viewer.render_report(events)

    # Timeline headers.
    assert "01:04:30 ORCHESTRATOR ▸ llm start · openai:orch · 2 msgs" in report
    assert "01:04:32 ORCHESTRATOR ▸ llm done (in 14.2k / out 1.8k, 42.0s) finish=tool_calls" in report
    assert "→ task(subagent_type=lumen-dsl-author)" in report
    assert "01:05:10 AUTHOR ▸ llm done (in 8.0k / out 500, 12.0s) finish=stop" in report
    assert "tools ▸ tool done · compile_dsl_block (300ms)" in report

    # Totals footer.
    assert "── totals ──" in report
    assert "orchestrator  1 calls · 16.0k tokens · 42.0s" in report
    assert "author        1 calls · 8.5k tokens · 12.0s" in report
    assert "compile_dsl_block×1" in report
    assert "rounds        1" in report


def test_viewer_role_filter(tmp_path):
    path = _write_fixture(tmp_path)
    events = list(viewer._parse_lines(path.read_text().splitlines()))
    report = viewer.render_report(events, role="author")
    assert "AUTHOR" in report
    assert "ORCHESTRATOR" not in report
    # Author's own tool event still shows (it carries role=author).
    assert "compile_dsl_block" in report


def test_viewer_tools_only_and_messages_only(tmp_path):
    path = _write_fixture(tmp_path)
    events = list(viewer._parse_lines(path.read_text().splitlines()))

    tools = viewer.render_report(events, tools_only=True)
    assert "tool done" in tools
    assert "llm done" not in tools

    msgs = viewer.render_report(events, messages_only=True)
    assert "llm done" in msgs
    assert "tool done" not in msgs


def test_viewer_truncation_and_full(tmp_path):
    long = "x" * 900
    ev = {
        "event": "llm_call_completed",
        "role": "author",
        "completion": long,
        "tool_calls": [],
        "total_tokens": 1,
        "duration_ms": 1,
        "timestamp": "2026-07-10T01:00:00.000000Z",
    }
    truncated = viewer.render_report([ev])
    assert "… (+400 chars)" in truncated
    full = viewer.render_report([ev], full=True)
    assert long in full


# --------------------------------------------------------------------------- #
# bare run_id resolution
# --------------------------------------------------------------------------- #
def test_resolve_run_log_bare_id(tmp_path):
    ws = tmp_path / "ws"
    # Primary: <ws>/<run_id>/logs/run.jsonl
    primary_dir = ws / "abc123" / "logs"
    primary_dir.mkdir(parents=True)
    primary = primary_dir / "run.jsonl"
    primary.write_text("{}\n")
    assert viewer.resolve_run_log("abc123", ws) == primary


def test_resolve_run_log_run_prefixed_fallback(tmp_path):
    ws = tmp_path / "ws"
    d = ws / "run_abc123" / "logs"
    d.mkdir(parents=True)
    f = d / "run.jsonl"
    f.write_text("{}\n")
    assert viewer.resolve_run_log("abc123", ws) == f


def test_resolve_run_log_explicit_path(tmp_path):
    p = tmp_path / "somewhere" / "run.jsonl"
    p.parent.mkdir(parents=True)
    p.write_text("{}\n")
    assert viewer.resolve_run_log(str(p), tmp_path / "ws") == p


def test_resolve_run_log_missing_returns_primary_candidate(tmp_path):
    ws = tmp_path / "ws"
    got = viewer.resolve_run_log("neverran", ws)
    assert got == ws / "neverran" / "logs" / "run.jsonl"
