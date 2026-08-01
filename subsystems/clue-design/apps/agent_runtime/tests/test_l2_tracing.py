"""L2 adoption tests: agent-runtime observability wiring (structlog-tracing plan §5, L2).

Covers the L2 deliverables end-to-end against the offline FakeCoreClient:
- per-run ``logs/run.jsonl`` is written with events on a fake run;
- ``cli.py`` defaults the log mode to debug while an explicit env still wins;
- ``run_id`` is bound onto every event once the substrate builds its run dir;
- a tool call emits a ``log_span`` with a duration;
- fs-backend path resolution logs at debug — absent from the info console, present
  in the always-full run file.

These exercise ONLY agent_runtime code + the shared ``py_lumen_obs`` public surface
(configure, capture_events, LogMode); they never touch py_lumen_obs internals.
"""
from __future__ import annotations

import json
import logging

import pytest

import py_lumen_obs as obs
from py_lumen_obs import LogMode
from py_lumen_obs.testing import capture_events

from agent_fixtures import FakeCoreClient, runtime_config


@pytest.fixture(autouse=True)
def _restore_logging():
    """Isolate global logging/structlog/contextvar state per test — the substrate
    binds run_id into contextvars and configure() mutates the root logger."""
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


def _build_tools(tmp_path, monkeypatch, prompt="design a launch poster"):
    monkeypatch.setattr("lumen_agent.tools.substrate.CoreClient", FakeCoreClient)
    from lumen_agent.tools.substrate import LumenDesignTools

    return LumenDesignTools(runtime_config(tmp_path), prompt)


# --- per-run run.jsonl -----------------------------------------------------


def test_run_jsonl_created_with_events_on_fake_run(tmp_path, monkeypatch):
    with capture_events(mode=LogMode.DEBUG):
        # Substrate build binds run_id and creates the run dir; the chokepoint
        # then attaches the per-run file exactly as run_deepagent_turn does.
        tools = _build_tools(tmp_path, monkeypatch)
        run_log = tools.trace_dir / "logs" / "run.jsonl"
        obs.configure(mode=LogMode.DEBUG, run_log_path=run_log)
        tools.compile_dsl_block('page Test\n  text "Plan"')

    assert run_log.exists(), "run.jsonl must be created under run_<id>/logs/"
    events = [
        json.loads(line)
        for line in run_log.read_text().splitlines()
        if line.strip()
    ]
    names = {e.get("event") for e in events}
    # The tool span AND the single-seam core-helper span both landed in the file.
    assert "tool_compile_dsl_block_started" in names
    assert "tool_compile_dsl_block_completed" in names
    assert "helper_call_started" in names
    assert "helper_call_completed" in names
    # Every event carries the bound run_id.
    assert all(e.get("run_id") == tools.run_id for e in events)


# --- cli debug default (explicit env wins) ---------------------------------


def _run_cli_main(monkeypatch, argv_prompt="hello"):
    import sys

    import lumen_agent.cli as cli

    monkeypatch.setattr(sys, "argv", ["lumen-cli", argv_prompt])
    monkeypatch.setattr(cli, "assert_model_supports_image_input", lambda *a, **k: None)
    monkeypatch.setattr(cli, "load_dotenv_if_available", lambda *a, **k: None)
    monkeypatch.setattr(cli, "run_deepagent_turn", lambda *a, **k: ({}, None))
    cli.main()


def test_cli_defaults_to_debug_mode(tmp_path, monkeypatch):
    monkeypatch.delenv("LUMEN_LOG_MODE", raising=False)
    _run_cli_main(monkeypatch)
    # setdefault installed the debug default, and configure() honoured it → root
    # logger captures DEBUG.
    assert __import__("os").environ.get("LUMEN_LOG_MODE") == "debug"
    assert logging.getLogger().level == logging.DEBUG


def test_cli_explicit_env_mode_wins(tmp_path, monkeypatch):
    monkeypatch.setenv("LUMEN_LOG_MODE", "info")
    _run_cli_main(monkeypatch)
    # setdefault must NOT override an explicit choice; info stays info.
    assert __import__("os").environ.get("LUMEN_LOG_MODE") == "info"
    assert logging.getLogger().level == logging.INFO


# --- run_id bound after substrate construction -----------------------------


def test_run_id_bound_on_events_after_substrate_built(tmp_path, monkeypatch):
    with capture_events(mode=LogMode.INFO) as cap:
        tools = _build_tools(tmp_path, monkeypatch)
        obs.get_logger("test.after_build").info("post_construct_event")
    entry = cap.first("post_construct_event")
    assert entry is not None
    assert entry["run_id"] == tools.run_id


# --- tool span with duration -----------------------------------------------


def test_tool_call_emits_span_with_duration(tmp_path, monkeypatch):
    with capture_events(mode=LogMode.INFO) as cap:
        tools = _build_tools(tmp_path, monkeypatch)
        tools.inspect("summary")
    completed = cap.first("tool_inspect_completed")
    assert completed is not None
    assert isinstance(completed["duration_ms"], (int, float))
    # The compact arg summary rides the span fields.
    assert completed.get("view") == "summary"


# --- fs-backend debug detail (console vs run file) -------------------------


def _resolve_once(root_dir):
    from lumen_agent.fs_backend import AgentWorkspaceBackend

    backend = AgentWorkspaceBackend(root_dir=str(root_dir))
    return backend._resolve_path("notes/plan.txt")


def test_fs_resolve_debug_absent_at_info_console_present_in_run_file(tmp_path, monkeypatch):
    run_log = tmp_path / "logs" / "run.jsonl"
    with capture_events(mode=LogMode.INFO, run_log_path=run_log) as cap:
        _resolve_once(tmp_path)
    # Console (info) mirror never sees the debug op event...
    assert not cap.has("fs_resolve")
    # ...but the always-full run file does.
    file_events = {
        json.loads(line).get("event")
        for line in run_log.read_text().splitlines()
        if line.strip()
    }
    assert "fs_resolve" in file_events


def test_fs_resolve_debug_visible_on_console_in_debug_mode(tmp_path, monkeypatch):
    with capture_events(mode=LogMode.DEBUG) as cap:
        _resolve_once(tmp_path)
    entry = cap.first("fs_resolve")
    assert entry is not None
    assert entry["key"] == "notes/plan.txt"
    assert "normalized_key" in entry
    assert "resolved" in entry
