"""Run files must retain only their own events and close at the runner boundary."""

from __future__ import annotations

import json
import logging
from concurrent.futures import ThreadPoolExecutor
from contextlib import ExitStack
from threading import Event
from types import SimpleNamespace

import py_lumen_obs as obs
import pytest
import structlog
from agent_fixtures import FakeCoreClient, runtime_config
from lumen_agent import harness
from lumen_agent.tools import substrate
from py_lumen_obs.config import run_log


@pytest.fixture(autouse=True)
def restore_logging():
    root = logging.getLogger()
    handlers, level = root.handlers[:], root.level
    config = structlog.get_config()
    context = structlog.contextvars.get_contextvars()
    try:
        yield
    finally:
        for handler in root.handlers[:]:
            if handler not in handlers:
                root.removeHandler(handler)
                handler.close()
        root.handlers[:] = handlers
        root.setLevel(level)
        structlog.configure(**config)
        structlog.contextvars.clear_contextvars()
        structlog.contextvars.bind_contextvars(**context)


def entries(path):
    return [json.loads(line) for line in path.read_text().splitlines() if line]


def test_exiting_one_run_does_not_skip_another_run_in_flight(tmp_path):
    """Removing A must not shift B behind Logger.callHandlers' active iterator."""
    blocked, release = Event(), Event()
    a, b, c = (tmp_path / f"{name}.jsonl" for name in ("a", "b", "c"))
    with ExitStack() as a_scope:
        a_scope.enter_context(run_log("a", a))
        handler = next(h for h in logging.getLogger().handlers if getattr(h, "baseFilename", None) == str(a))

        def pause_b(record):
            if isinstance(record.msg, dict) and record.msg.get("event") == "b_during_a_exit":
                blocked.set()
                assert release.wait(10), "controller never released B's dispatch"
            return True

        handler.filters.insert(0, pause_b)
        with run_log("b", b), run_log("c", c), ThreadPoolExecutor(max_workers=1) as pool:
            future = pool.submit(
                obs.get_logger("lumen_agent.trace", run_id="b").info, "b_during_a_exit",
            )
            try:
                assert blocked.wait(10), "B did not reach A's filter"
                a_scope.close()
            finally:
                release.set()
            future.result(timeout=10)
            obs.get_logger("lumen_agent.trace", run_id="b").info("b_after_a_exit")
    assert [row["event"] for row in entries(b)] == ["b_during_a_exit", "b_after_a_exit"]
    assert entries(a) == entries(c) == []


def test_inflight_record_cannot_reopen_closed_run_file(tmp_path):
    """An append-mode FileHandler otherwise reopens when emit follows close."""
    path = tmp_path / "a.jsonl"
    blocked, release = Event(), Event()
    with ExitStack() as scope:
        scope.enter_context(run_log("a", path))
        handler = next(h for h in logging.getLogger().handlers if getattr(h, "baseFilename", None) == str(path))

        def pause(_record):
            blocked.set()
            assert release.wait(10), "controller never released the pending record"
            return True

        handler.filters.insert(0, pause)
        with ThreadPoolExecutor(max_workers=1) as pool:
            future = pool.submit(
                obs.get_logger("lumen_agent.trace", run_id="a").info, "already_in_flight",
            )
            try:
                assert blocked.wait(10), "record did not reach the run filter"
                scope.close()
                assert handler.stream is None
                frozen = path.read_bytes()
            finally:
                release.set()
            future.result(timeout=10)
        try:
            assert path.read_bytes() == frozen, "detached handler wrote after scope exit"
            assert handler.stream is None, "late emit reopened a detached file descriptor"
        finally:
            handler.close()


def test_overlapping_scene_runners_keep_complete_separate_logs(tmp_path, monkeypatch):
    """A second run must not steal A's events or lose its own sink when A exits."""
    monkeypatch.setattr(substrate, "CoreClient", FakeCoreClient)
    a_ready, b_ready, a_after, release_b = (Event() for _ in range(4))
    by_prompt = {}

    def create(prompt, **kwargs):
        tools = substrate.LumenDesignTools(kwargs["config"], prompt)
        by_prompt[prompt] = tools

        def invoke(*_args, **_kwargs):
            log = obs.get_logger("lumen_agent.trace", run_id=tools.run_id)
            log.debug(f"{prompt}_before", role="orchestrator")
            if prompt == "a":
                a_ready.set()
                assert b_ready.wait(10), "B never entered its graph"
                log.debug("a_after", role="author")
                a_after.set()
            else:
                b_ready.set()
                assert a_after.wait(10), "A never emitted after B attached"
                assert release_b.wait(10), "controller never released B"
                log.debug("b_after", role="author")

        return SimpleNamespace(invoke=invoke), tools

    monkeypatch.setattr(harness, "create_design_deepagent", create)
    config = runtime_config(tmp_path)
    with ThreadPoolExecutor(max_workers=2) as executor:
        a = executor.submit(harness.run_deepagent_turn, "a", config)
        try:
            assert a_ready.wait(10), "A never entered its graph"
            b = executor.submit(harness.run_deepagent_turn, "b", config)
            a.result(timeout=15)
        finally:
            release_b.set()
        b.result(timeout=15)

    for prompt in ("a", "b"):
        tools = by_prompt[prompt]
        path = tools.trace_dir / "logs/run.jsonl"
        rows = entries(path)
        assert {row.get("run_id") for row in rows} == {tools.run_id}
        observed = [row["event"] for row in rows]
        assert f"{prompt}_before" in observed
        assert f"{prompt}_after" in observed
        assert "run_metrics" in observed
        before = path.read_bytes()
        obs.get_logger("lumen_agent.trace", run_id=tools.run_id).info("after_return")
        assert path.read_bytes() == before, "finished run still has an open sink"


@pytest.mark.parametrize("failure", ["graph", "startup", "cancel", "interrupt"])
def test_scene_runner_closes_log_on_failure(tmp_path, monkeypatch, failure):
    monkeypatch.setattr(substrate, "CoreClient", FakeCoreClient)
    tools = substrate.LumenDesignTools(runtime_config(tmp_path), "failure")

    def invoke(*_args, **_kwargs):
        if failure == "interrupt":
            raise KeyboardInterrupt()
        raise RuntimeError("graph failed")

    monkeypatch.setattr(
        harness, "create_design_deepagent",
        lambda *_args, **_kwargs: (SimpleNamespace(invoke=invoke), tools),
    )
    if failure == "interrupt":
        with pytest.raises(KeyboardInterrupt):
            harness.run_deepagent_turn("failure", tools.config)
    elif failure == "startup":
        monkeypatch.setattr(harness, "initial_turn_state", invoke)
        with pytest.raises(RuntimeError, match="graph failed"):
            harness.run_deepagent_turn("failure", tools.config)
    else:
        payload, _ = harness.run_deepagent_turn(
            "failure", tools.config, cancel_requested=lambda: failure == "cancel",
        )
        assert payload["stop_reason"] == (
            "cancelled_by_request" if failure == "cancel" else "orchestrator_did_not_finalize"
        )
    path = tools.trace_dir / "logs/run.jsonl"
    before = path.read_bytes()
    obs.get_logger("lumen_agent.trace", run_id=tools.run_id).warning("after_failure")
    assert path.read_bytes() == before


def test_run_filter_uses_explicit_id_before_ambient_and_excludes_unattributed(tmp_path, capsys):
    """A stale ambient context cannot reassign a bound log or stdlib extra ID."""
    a, b = tmp_path / "a.jsonl", tmp_path / "b.jsonl"
    with run_log("a", a), run_log("b", b):
        with obs.bound_context(run_id="b"):
            obs.get_logger("lumen_agent.trace", run_id="a").info("explicit_a", role="author")
            logging.getLogger("foreign").info("stdlib_a", extra={"run_id": "a"})
            logging.getLogger("foreign").info({"run_id": "a", "event": "dict_a"})
            logging.getLogger("foreign").info("ambient_b")
            obs.get_logger("lumen_agent.trace", run_id=None).warning("explicit_none")
        with obs.bound_context(run_id=None):
            obs.get_logger("lumen_agent.trace").warning("unattributed")
            logging.getLogger("foreign").warning("stdlib_unattributed")
        obs.get_logger("lumen_agent.trace", run_id="other").warning("other_run")

    assert [(r["event"], r["run_id"]) for r in entries(a)] == [
        ("explicit_a", "a"), ("stdlib_a", "a"),
        ("{'run_id': 'a', 'event': 'dict_a'}", "a"),
    ]
    assert [(r["event"], r["run_id"]) for r in entries(b)] == [("ambient_b", "b")]
    console = capsys.readouterr().out
    assert console.count('"event": "unattributed"') == 1


def test_scoped_file_stays_full_and_redacted_while_console_truncates(tmp_path, capsys, monkeypatch):
    monkeypatch.setenv("LUMEN_LOG_MODE", "info")
    monkeypatch.setenv("LUMEN_LOG_FORMAT", "json")
    path = tmp_path / "run.jsonl"
    body = "ordinary prose, " * 80
    with run_log("a", path):
        log = obs.get_logger("lumen_agent.trace", run_id="a")
        log.info("detail", body=body, api_key="test-secret")
        log.debug("debug_detail", role="author")
    assert [(r["event"], r["run_id"]) for r in entries(path)] == [
        ("detail", "a"), ("debug_detail", "a"),
    ]
    assert entries(path)[0]["body"] == body
    assert entries(path)[0]["api_key"] == "***"
    console = [json.loads(line) for line in capsys.readouterr().out.splitlines()]
    assert [r["event"] for r in console] == ["detail"]
    assert len(console[0]["body"]) < len(body)


def test_scoped_sinks_survive_legacy_reconfigure_and_restore_latest_level(tmp_path, monkeypatch):
    monkeypatch.setenv("LUMEN_LOG_MODE", "info")
    a, b, legacy = tmp_path / "a.jsonl", tmp_path / "b.jsonl", tmp_path / "legacy.jsonl"
    with run_log("a", a), run_log("b", b):
        obs.configure(mode="debug", fmt="json", run_log_path=legacy)
        obs.get_logger("lumen_agent.trace", run_id="a").debug("a_during_legacy")
        obs.configure(mode="info", fmt="json")
        obs.get_logger("lumen_agent.trace", run_id="b").debug("b_after_legacy")
        assert logging.getLogger().level == logging.DEBUG
    assert [r["event"] for r in entries(a)] == ["a_during_legacy"]
    assert [r["event"] for r in entries(b)] == ["b_after_legacy"]
    assert [r["event"] for r in entries(legacy)] == ["a_during_legacy"]
    assert logging.getLogger().level == logging.INFO


@pytest.mark.parametrize("mode,level", [("info", logging.INFO), ("debug", logging.DEBUG)])
def test_foreign_console_reconfigure_preserves_run_attribution_and_threshold(tmp_path, mode, level):
    # The platform has a cooperating console configurator but a separate package.
    # It may deliberately raise the root threshold; scoped teardown must not undo it.
    from clue_obs import setup

    a, b = tmp_path / "a.jsonl", tmp_path / "b.jsonl"
    with run_log("a", a), run_log("b", b):
        setup(mode=mode, fmt="json")
        obs.get_logger("lumen_agent.trace", run_id="a").info("a_after_foreign")
        obs.get_logger("lumen_agent.trace", run_id="b").info("b_after_foreign")
    assert logging.getLogger().level == level
    assert [r["event"] for r in entries(a)] == ["a_after_foreign"]
    assert [r["event"] for r in entries(b)] == ["b_after_foreign"]


@pytest.mark.parametrize("reconfigure", [None, "design", "platform"])
@pytest.mark.parametrize("private", [True, False])
def test_scene_preference_echo_stays_in_run_trace_only(
    tmp_path, monkeypatch, capsys, reconfigure, private,
):
    """Real trace callbacks must not copy model echoes into the shared console."""
    from langchain_core.messages import AIMessage
    from langchain_core.outputs import ChatGeneration, LLMResult
    from lumen_agent.trace_callbacks import TraceCallbackHandler

    monkeypatch.setenv("LUMEN_LOG_MODE", "debug")
    monkeypatch.setenv("LUMEN_LOG_FORMAT", "json")
    monkeypatch.setattr(substrate, "CoreClient", FakeCoreClient)
    sentinel = "Use the PRIVATE_PREFERENCE_ECHO in supporting copy."
    tools = substrate.LumenDesignTools(runtime_config(tmp_path), "fixture request")

    def create(_prompt, **kwargs):
        def invoke(*_args, **_kwargs):
            if reconfigure == "design":
                obs.configure(mode="debug", fmt="json")
            elif reconfigure == "platform":
                from clue_obs import setup

                setup(mode="debug", fmt="json")
            advice = kwargs["scoped_preferences"]() if private else sentinel
            callback = TraceCallbackHandler("orchestrator")
            callback.on_llm_end(LLMResult(generations=[[ChatGeneration(message=AIMessage(
                content=advice,
                tool_calls=[{"id": "call_1", "name": "write_file", "args": {"text": advice}}],
            ))]]))
            callback.on_llm_error(RuntimeError(advice))
            logging.getLogger("foreign").error(
                "model echoed %s", advice, exc_info=ValueError(advice),
            )

        return SimpleNamespace(invoke=invoke), tools

    monkeypatch.setattr(harness, "create_design_deepagent", create)
    harness.run_deepagent_turn(
        "fixture request", tools.config,
        **({"scoped_preferences": lambda: sentinel} if private else {}),
    )
    console = capsys.readouterr().out
    trace = (tools.trace_dir / "logs/run.jsonl").read_text()
    assert sentinel in trace, "the actual model echo must remain in removable run custody"
    assert (sentinel in console) is not private
    obs.get_logger("ordinary").info("ordinary_after_private_scope")
    assert "ordinary_after_private_scope" in capsys.readouterr().out


def test_ordinary_nested_scope_cannot_clear_inherited_private_context(tmp_path, capsys):
    with obs.bound_context(run_id=None), ThreadPoolExecutor(max_workers=1) as pool:
        with run_log("private", tmp_path / "outer.jsonl", private_payloads=True):
            with run_log("nested", tmp_path / "nested.jsonl"):
                logging.getLogger("foreign").error("PRIVATE_UNTAGGED_NESTED_ECHO")
                pool.submit(
                    obs.get_logger("trace", run_id="nested").error,
                    "PRIVATE_ATTRIBUTED_NESTED_ECHO",
                ).result(timeout=5)
        logging.getLogger("foreign").info("ordinary_after_nested_scope")

    console = capsys.readouterr().out
    assert "PRIVATE_" not in console
    assert "ordinary_after_nested_scope" in console
    assert "PRIVATE_ATTRIBUTED_NESTED_ECHO" in (tmp_path / "nested.jsonl").read_text()


def test_private_console_scope_isolates_workers_and_nested_lifetimes(tmp_path, capsys):
    from contextvars import copy_context

    with ThreadPoolExecutor(max_workers=1) as pool:
        with run_log("private", tmp_path / "outer.jsonl", private_payloads=True):
            late_context = copy_context()
            with run_log("private", tmp_path / "inner.jsonl", private_payloads=True):
                pool.submit(
                    obs.get_logger("trace", run_id="private").error,
                    "PRIVATE_NESTED_ECHO",
                ).result(timeout=5)
            # Closing one registration must not remove the still-active outer one.
            pool.submit(
                obs.get_logger("trace", run_id="private").error,
                "PRIVATE_OUTER_ECHO",
            ).result(timeout=5)

            def ordinary_worker():
                with run_log("ordinary", tmp_path / "ordinary.jsonl"):
                    obs.get_logger("trace", run_id="ordinary").info("ordinary_concurrent")

            pool.submit(ordinary_worker).result(timeout=5)
        # The active-run registration is gone; an inherited private context still
        # suppresses a late callback without reopening its now-closed trace.
        before = (tmp_path / "outer.jsonl").read_bytes()
        late_context.run(obs.get_logger("trace").error, "PRIVATE_LATE_ECHO")
        assert (tmp_path / "outer.jsonl").read_bytes() == before
        pool.submit(
            obs.get_logger("trace", run_id="private").info,
            "ordinary_after_last_registration",
        ).result(timeout=5)

    console = capsys.readouterr().out
    assert "PRIVATE_" not in console
    assert "ordinary_concurrent" in console
    assert "ordinary_after_last_registration" in console
    assert "PRIVATE_OUTER_ECHO" in (tmp_path / "outer.jsonl").read_text()
    assert "PRIVATE_" not in (tmp_path / "ordinary.jsonl").read_text()


@pytest.mark.parametrize("outcome", ["completed_with_warnings", "exception", "cancel"])
def test_web_runner_closes_log_after_finalization(tmp_path, monkeypatch, outcome):
    from lumen_agent import harness_web
    from lumen_agent.tools import web_substrate

    monkeypatch.setattr(web_substrate, "CoreClient", FakeCoreClient)
    tools = web_substrate.LumenWebTools(runtime_config(tmp_path), "web", initial_web_doc={})

    def invoke(*_args, **_kwargs):
        obs.get_logger("lumen_agent.trace", run_id=tools.run_id).info("web_graph_entered")
        if outcome == "exception":
            raise RuntimeError("web graph failed")
        tools.finalize_web_run(outcome, "fixture finalized")

    monkeypatch.setattr(
        harness_web, "create_web_deepagent",
        lambda *_args, **_kwargs: (SimpleNamespace(invoke=invoke), tools),
    )
    result = harness_web.run_deepagent_web_turn(
        "web", tools.config, cancel_requested=lambda: outcome == "cancel",
    )
    assert result["status"] == ("applied" if outcome == "completed_with_warnings" else "failed")
    path = tools.trace_dir / "logs/run.jsonl"
    rows = entries(path)
    assert {r["run_id"] for r in rows} == {tools.run_id}
    if outcome != "cancel":
        assert "web_graph_entered" in [r["event"] for r in rows]
    assert json.loads((tools.trace_dir / "final.json").read_text())["outcome"] == result["outcome"]
    before = path.read_bytes()
    obs.get_logger("lumen_agent.web_substrate", run_id=tools.run_id).warning("after_web_return")
    assert path.read_bytes() == before
