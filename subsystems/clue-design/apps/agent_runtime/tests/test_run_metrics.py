"""Per-run summary metrics (fast-loop v1 §7) — accumulator, emission, viewer.

The motivating failure is documented in ``docs/deepagent-fast-loop-v1-spec.md``:
the 43-minute baseline run's numbers were all present in the trace and nobody
could read them without hand-totalling ~6000 log lines. These tests drive a
STUBBED run through the real tracer and the real harness runner and assert that
the aggregation now happens by itself — including on the failure path, which is
the path whose metrics matter most (the 20m42s baseline died on a quota 403).
"""

from __future__ import annotations

from langchain_core.language_models.fake_chat_models import GenericFakeChatModel

import json
import sys
import types
from pathlib import Path

from py_lumen_obs import LogMode, capture_events

from lumen_agent import trace as viewer
from lumen_agent.run_metrics import (
    METRICS_FILENAME,
    RUN_METRICS_EVENT,
    RunMetrics,
    count_round_dirs,
    emit_run_metrics,
    summarize_line,
)
from lumen_agent.trace_callbacks import TraceCallbackHandler, attach_trace_callback

from agent_fixtures import FakeCoreClient, prepare_acceptance_evidence, runtime_config
from test_deepagent_harness import _install_deepagents_stub, _tools_only


# --------------------------------------------------------------------------- #
# LLMResult builder (same shape the tracer tests use)
# --------------------------------------------------------------------------- #
def _llm_result(text="ok", input_tokens=1200, output_tokens=48, total=1248):
    from langchain_core.messages import AIMessage
    from langchain_core.outputs import ChatGeneration, LLMResult

    message = AIMessage(
        content=text,
        usage_metadata={
            "input_tokens": input_tokens,
            "output_tokens": output_tokens,
            "total_tokens": total,
        },
    )
    gen = ChatGeneration(message=message, generation_info={"finish_reason": "stop"})
    return LLMResult(generations=[[gen]])


class _FakeTools:
    """The duck-typed surface ``emit_run_metrics`` needs: run_id, trace_dir,
    metrics, record. Small on purpose — the emitter must not require the whole
    substrate, which is what lets it serve any harness."""

    def __init__(self, trace_dir: Path, run_id: str = "run_fake") -> None:
        self.run_id = run_id
        self.trace_dir = trace_dir
        self.trace_dir.mkdir(parents=True, exist_ok=True)
        self.metrics = RunMetrics(run_id)
        self.records: list[tuple] = []
        self.sink_pushes: list[dict] = []

    def record(self, actor, event, *, output_summary=None, payload=None, sink_extra=None, **_):
        self.records.append((actor, event, output_summary, payload))
        if sink_extra:
            self.sink_pushes.append(sink_extra)


# --------------------------------------------------------------------------- #
# 1. the accumulator itself
# --------------------------------------------------------------------------- #
def test_accumulator_totals_per_role_and_overall():
    metrics = RunMetrics("run_x")
    metrics.register_role("reviewer")  # never speaks — must still report zeros

    metrics.record_llm_completed(
        role="orchestrator", duration_ms=42_000, input_tokens=14_200, output_tokens=1_800
    )
    metrics.record_llm_completed(
        role="orchestrator", duration_ms=5_000, input_tokens=100, output_tokens=10
    )
    metrics.record_llm_completed(
        role="author", duration_ms=31_000, input_tokens=8_000, output_tokens=500
    )
    metrics.record_llm_failed(role="author", duration_ms=1_000)

    summary = metrics.snapshot(outcome="accepted", status="accepted", rounds_total=3)

    assert summary["llm_calls_total"] == 4
    assert summary["llm_calls_failed"] == 1
    # Two calls broke 30s: the 42s orchestrator call and the 31s author call.
    assert summary["llm_calls_over_30s"] == 2
    assert summary["input_tokens_total"] == 22_300
    assert summary["output_tokens_total"] == 2_310
    assert summary["rounds_total"] == 3
    assert summary["outcome"] == "accepted"

    orchestrator = summary["by_role"]["orchestrator"]
    assert orchestrator["calls"] == 2
    assert orchestrator["duration_ms_total"] == 47_000
    assert orchestrator["duration_ms_max"] == 42_000

    author = summary["by_role"]["author"]
    assert author["calls"] == 2 and author["failed"] == 1
    assert author["duration_ms_max"] == 31_000

    # A registered-but-silent role reports zeros rather than vanishing.
    assert summary["by_role"]["reviewer"] == {
        "calls": 0,
        "failed": 0,
        "duration_ms_total": 0,
        "duration_ms_max": 0,
        "input_tokens": 0,
        "output_tokens": 0,
    }


def test_missing_token_counts_do_not_poison_the_sum():
    """Providers routinely return no usage block; a `None` must count as zero,
    never crash the run and never make the total `None`."""
    metrics = RunMetrics("run_x")
    metrics.record_llm_completed(
        role="author", duration_ms=None, input_tokens=None, output_tokens=None
    )
    summary = metrics.snapshot()
    assert summary["llm_calls_total"] == 1
    assert summary["input_tokens_total"] == 0
    assert summary["by_role"]["author"]["duration_ms_total"] == 0


def test_first_preview_is_recorded_once_and_is_null_when_never_rendered():
    metrics = RunMetrics("run_x")
    assert metrics.snapshot()["time_to_first_preview_ms"] is None

    metrics.mark_first_preview()
    first = metrics.snapshot()["time_to_first_preview_ms"]
    assert isinstance(first, int)
    metrics.mark_first_preview()  # idempotent — a later preview must not move it
    assert metrics.snapshot()["time_to_first_preview_ms"] == first


def test_count_round_dirs(tmp_path):
    rounds = tmp_path / "rounds"
    assert count_round_dirs(rounds) == 0  # never created
    rounds.mkdir()
    (rounds / "round_1").mkdir()
    (rounds / "round_2").mkdir()
    (rounds / "round_notanumber").mkdir()
    (rounds / "index.md").write_text("x")
    assert count_round_dirs(rounds) == 2


def test_count_round_dirs_above_a_base(tmp_path: Path) -> None:
    """Session continuity: a turn reports the rounds IT ran, not the session's
    whole history, so the count starts above the round base it inherited."""
    for n in (1, 2, 3):
        (tmp_path / f"round_{n}").mkdir()
    assert count_round_dirs(tmp_path) == 3
    assert count_round_dirs(tmp_path, above=2) == 1


def test_metrics_json_lands_in_the_turn_folder(tmp_path):
    """``metrics.json`` is a per-TURN artifact: it sits next to that turn's
    ``final.json``, which under a session lives in ``turn_dir``."""
    tools = _FakeTools(tmp_path / "session")
    tools.turn_dir = tmp_path / "session" / "turns" / "run_fake"
    tools.turn_dir.mkdir(parents=True)
    summary = emit_run_metrics(tools, outcome="accepted", status="accepted")
    assert summary is not None
    assert (tools.turn_dir / METRICS_FILENAME).is_file()
    assert not (tools.trace_dir / METRICS_FILENAME).exists()


# --------------------------------------------------------------------------- #
# 2. the tracer feeds the accumulator — same events, now aggregated
# --------------------------------------------------------------------------- #
def test_tracer_folds_calls_into_metrics_without_changing_events():
    metrics = RunMetrics("run_x")
    with capture_events(mode=LogMode.DEBUG) as cap:
        handler = TraceCallbackHandler(role="author", metrics=metrics)
        handler.on_chat_model_start({"kwargs": {"model": "openai:x"}}, [[]], run_id="c1")
        handler.on_llm_end(_llm_result(), run_id="c1")
        handler.on_chat_model_start({}, [[]], run_id="c2")
        handler.on_llm_error(RuntimeError("quota"), run_id="c2")

    # The pre-existing per-call events are untouched (purely additive).
    completed = cap.first("llm_call_completed")
    assert completed["input_tokens"] == 1200 and completed["role"] == "author"
    assert cap.first("llm_call_failed")["error"].startswith("RuntimeError")

    summary = metrics.snapshot()
    assert summary["llm_calls_total"] == 2
    assert summary["llm_calls_failed"] == 1
    assert summary["by_role"]["author"]["input_tokens"] == 1200


def test_attach_trace_callback_threads_metrics_and_registers_the_role():
    class _Model:
        def __init__(self):
            self.callbacks = None

    metrics = RunMetrics("run_x")
    attach_trace_callback(_Model(), role="reviewer", metrics=metrics)
    assert "reviewer" in metrics.snapshot()["by_role"]


def test_metrics_failure_never_breaks_the_trace():
    """Observability must never be the thing that fails a turn: a metrics object
    that explodes degrades to the existing warn-once 'no trace' path."""

    class _Exploding:
        def register_role(self, role):
            raise RuntimeError("boom")

    with capture_events(mode=LogMode.DEBUG) as cap:
        handler = TraceCallbackHandler(role="author", metrics=_Exploding())
        handler.on_chat_model_start({}, [[]], run_id="c1")
        handler.on_llm_end(_llm_result(), run_id="c1")

    # The bad accumulator was dropped at construction; tracing carried on.
    assert handler._metrics is None
    assert cap.first("llm_call_completed") is not None


# --------------------------------------------------------------------------- #
# 3. emission: one run_metrics event + metrics.json + the sink push
# --------------------------------------------------------------------------- #
def test_emit_writes_event_file_and_sink(tmp_path):
    tools = _FakeTools(tmp_path / "run_fake")
    tools.metrics.register_role("orchestrator")
    tools.metrics.record_llm_completed(
        role="orchestrator", duration_ms=1_000, input_tokens=500, output_tokens=20
    )
    tools.metrics.mark_compile_iteration()
    tools.metrics.mark_compile_iteration()
    tools.metrics.mark_first_preview()

    rounds = tmp_path / "run_fake" / "workspace" / "rounds"
    (rounds / "round_1").mkdir(parents=True)

    with capture_events(mode=LogMode.DEBUG) as cap:
        summary = emit_run_metrics(
            tools,
            outcome="accepted",
            status="accepted",
            stop_reason="review_passed",
            rounds_dir=rounds,
        )

    # (a) exactly ONE summary event, on the obs logger → logs/run.jsonl.
    events = cap.events(RUN_METRICS_EVENT)
    assert len(events) == 1
    event = events[0]
    assert event["llm_calls_total"] == 1
    assert event["compile_iterations_total"] == 2
    assert event["rounds_total"] == 1
    assert isinstance(event["time_to_first_preview_ms"], int)
    assert event["outcome"] == "accepted"

    # (b) the same numbers as a durable file next to final.json.
    on_disk = json.loads((tools.trace_dir / METRICS_FILENAME).read_text(encoding="utf-8"))
    assert on_disk == summary
    assert on_disk["input_tokens_total"] == 500

    # (c) the substrate record + its sink_extra, which is what reaches run_event.
    assert [name for _actor, name, _sum, _payload in tools.records] == [RUN_METRICS_EVENT]
    assert tools.sink_pushes == [{"metrics": summary}]


def test_summary_lands_in_the_real_run_jsonl_and_renders(tmp_path):
    """The whole chain against the REAL obs file sink, not the capture fixture:
    the summary must survive into `logs/run.jsonl` (which is what a human greps
    and what `python -m lumen_agent.trace` reads) with its `run_id` intact —
    `run_id` is also a bound contextvar, so an explicit field of that name has to
    win rather than collide."""
    from py_lumen_obs import configure

    tools = _FakeTools(tmp_path / "run_fake")
    tools.metrics.record_llm_completed(
        role="orchestrator", duration_ms=42_000, input_tokens=14_200, output_tokens=1_800
    )
    run_log = tools.trace_dir / "logs" / "run.jsonl"
    configure(run_log_path=run_log, mode=None)
    try:
        emit_run_metrics(tools, outcome="accepted", status="accepted")
    finally:
        configure(run_log_path=None, mode=None)

    events = [json.loads(line) for line in run_log.read_text(encoding="utf-8").splitlines() if line]
    summaries = [e for e in events if e.get("event") == RUN_METRICS_EVENT]
    assert len(summaries) == 1
    assert summaries[0]["run_id"] == "run_fake"
    assert summaries[0]["llm_calls_total"] == 1

    report = viewer.render_report(events)
    assert "RUN METRICS ▸ accepted" in report
    assert "orchestrator    1 calls · 42.0s total" in report


def test_emit_is_a_no_op_without_an_accumulator(tmp_path):
    """A substrate that carries no `metrics` (the web tools today) must be
    completely unaffected — no file, no event, no crash."""

    class _NoMetrics:
        trace_dir = tmp_path

    assert emit_run_metrics(_NoMetrics(), outcome="accepted") is None
    assert not (tmp_path / METRICS_FILENAME).exists()


def test_emit_survives_an_unwritable_run_directory(tmp_path):
    tools = _FakeTools(tmp_path / "run_fake")
    tools.trace_dir = tmp_path / "gone" / "deeper"  # never created
    summary = emit_run_metrics(tools, outcome="failed", status="failed")
    # The file write failed; the event and the record still happened.
    assert summary is not None
    assert [name for _a, name, _s, _p in tools.records] == [RUN_METRICS_EVENT]


# --------------------------------------------------------------------------- #
# 4. the real substrate marks compiles and previews
# --------------------------------------------------------------------------- #
def test_substrate_marks_compiles_and_first_valid_preview(tmp_path, monkeypatch):
    monkeypatch.setattr("lumen_agent.tools.substrate.CoreClient", FakeCoreClient)
    tools = _tools_only(runtime_config(tmp_path))

    assert tools.metrics.snapshot()["compile_iterations_total"] == 0
    tools.compile_dsl_block("page ad size(1080,1080,px)")
    assert tools.metrics.snapshot()["compile_iterations_total"] == 1

    # A preview that FAILS validation must not start the first-preview clock —
    # the agent could not see anything.
    assert tools.metrics.snapshot()["time_to_first_preview_ms"] is None
    tools._write_and_validate_preview_artifacts(
        [{"bytes": list(b"not a png"), "format": "png", "mime_type": "image/png"}],
        "png",
        tools._iteration_dir(),
    )
    assert tools.metrics.snapshot()["time_to_first_preview_ms"] is None

    # A valid SVG does.
    svg = b'<svg xmlns="http://www.w3.org/2000/svg" width="10" height="10"></svg>'
    artifacts = tools._write_and_validate_preview_artifacts(
        [{"bytes": list(svg), "format": "svg", "mime_type": "image/svg+xml"}],
        "svg",
        tools._iteration_dir(),
    )
    assert artifacts[0].valid is True
    assert isinstance(tools.metrics.snapshot()["time_to_first_preview_ms"], int)


def test_autofix_counters_split_the_payoff_from_the_waste(tmp_path):
    """§5.4's counter, the one W0 left as a named residual.

    `autofix_count` is the payoff — repairs that landed with NO model call, the
    number the §1 call-count gate is trying to move. `autofix_rolled_back` is
    the honesty check: a class that keeps getting rejected is spending two
    engine calls to hand the author the diagnostic it started with, and should
    be narrowed rather than left running. Summing them would hide exactly that.
    """
    metrics = RunMetrics("run_autofix")

    zero = metrics.snapshot()
    assert (zero["autofix_count"], zero["autofix_rolled_back"]) == (0, 0)
    assert zero["autofix_by_class"] == {}

    metrics.record_autofix("text_box_hug", accepted=True)
    metrics.record_autofix("slot_fixture", accepted=True)
    metrics.record_autofix("text_box_hug", accepted=True)
    metrics.record_autofix("text_box_hug", accepted=False)

    summary = metrics.snapshot()
    assert summary["autofix_count"] == 3
    assert summary["autofix_rolled_back"] == 1
    # per-class, so a class can be judged on its own record
    assert summary["autofix_by_class"] == {"slot_fixture": 1, "text_box_hug": 2}
    assert "3 autofix" in summarize_line(summary)


# --------------------------------------------------------------------------- #
# 5. the FAILURE path emits too — the run whose metrics matter most
# --------------------------------------------------------------------------- #
def test_failed_run_still_emits_metrics_json(tmp_path, monkeypatch):
    """The 20m42s baseline died on a quota 403 at finalize and its numbers were
    the most valuable in the whole forensics. A summary that only fired on the
    happy path would have missed it."""
    capture: dict = {}

    def fake_create_deep_agent(**kwargs):
        capture["kwargs"] = kwargs

        def _explode(*a, **k):
            raise RuntimeError("model exploded mid-turn")

        return types.SimpleNamespace(invoke=_explode, kwargs=kwargs)

    _install_deepagents_stub(monkeypatch, capture)
    module = sys.modules["deepagents"]
    monkeypatch.setattr(module, "create_deep_agent", fake_create_deep_agent)
    monkeypatch.setattr("lumen_agent.tools.substrate.CoreClient", FakeCoreClient)
    monkeypatch.setattr("lumen_agent.llm.init_model", lambda *a, **k: GenericFakeChatModel(messages=iter(())))

    from lumen_agent.harness import run_deepagent_turn

    payload, tools = run_deepagent_turn("Design a card", runtime_config(tmp_path))

    assert payload["status"] == "failed"
    metrics_path = tools.trace_dir / METRICS_FILENAME
    assert metrics_path.exists(), "a failed run must still leave metrics.json"
    summary = json.loads(metrics_path.read_text(encoding="utf-8"))
    assert summary["run_id"] == tools.run_id
    assert summary["outcome"] == "failed"
    assert summary["status"] == "failed"
    assert summary["stop_reason"] == "orchestrator_did_not_finalize"
    assert isinstance(summary["wall_time_ms"], int)
    assert summary["time_to_first_preview_ms"] is None
    # The three role handlers registered themselves even though none was called.
    assert set(summary["by_role"]) == {"orchestrator", "author", "reviewer"}
    assert summary["llm_calls_total"] == 0

    # The same summary rode the run's own trace.jsonl (and so the event sink).
    trace = (tools.trace_dir / "trace.jsonl").read_text(encoding="utf-8")
    assert RUN_METRICS_EVENT in trace


def test_successful_run_emits_metrics_after_its_finalize(tmp_path, monkeypatch):
    """The happy path: the orchestrator writes final.json, and the summary is
    emitted from the runner's `finally` carrying that run's real outcome."""
    capture: dict = {}
    _install_deepagents_stub(monkeypatch, capture)
    monkeypatch.setattr("lumen_agent.tools.substrate.CoreClient", FakeCoreClient)
    monkeypatch.setattr("lumen_agent.llm.init_model", lambda *a, **k: GenericFakeChatModel(messages=iter(())))

    holder: dict = {}
    real_init = __import__(
        "lumen_agent.tools.substrate", fromlist=["LumenDesignTools"]
    ).LumenDesignTools.__init__

    def spy_init(self, *args, **kwargs):
        real_init(self, *args, **kwargs)
        holder["tools"] = self

    monkeypatch.setattr(
        "lumen_agent.tools.substrate.LumenDesignTools.__init__", spy_init, raising=True
    )

    from lumen_agent.harness import run_deepagent_turn

    module = sys.modules["deepagents"]

    def fake_create_deep_agent(**kwargs):
        capture["kwargs"] = kwargs

        def _finalize(*a, **k):
            prepare_acceptance_evidence(holder["tools"])
            result = holder["tools"].finalize_run("accepted", "review_passed", "looks good")
            assert json.loads(result)["status"] == "accepted"
            return {"messages": []}

        return types.SimpleNamespace(invoke=_finalize, kwargs=kwargs)

    monkeypatch.setattr(module, "create_deep_agent", fake_create_deep_agent)

    payload, tools = run_deepagent_turn("Design a card", runtime_config(tmp_path))

    assert payload["status"] == "accepted"
    summary = json.loads((tools.trace_dir / METRICS_FILENAME).read_text(encoding="utf-8"))
    assert summary["outcome"] == "accepted"
    assert summary["stop_reason"] == "review_passed"
    # The scaffold created rounds/ but no round_N dir — an honest zero.
    assert summary["rounds_total"] == 0


# --------------------------------------------------------------------------- #
# 6. the CLI viewer renders the summary
# --------------------------------------------------------------------------- #
_SUMMARY_EVENT_FIXTURE = {
    "event": RUN_METRICS_EVENT,
    "run_id": "run_abc",
    "outcome": "accepted",
    "status": "accepted",
    "stop_reason": "review_passed",
    "wall_time_ms": 2_598_000,
    "llm_calls_total": 178,
    "llm_calls_failed": 0,
    "llm_calls_over_30s": 6,
    "input_tokens_total": 13_500_000,
    "output_tokens_total": 92_000,
    "time_to_first_preview_ms": 924_000,
    "rounds_total": 3,
    "compile_iterations_total": 34,
    "by_role": {
        "author": {
            "calls": 90,
            "failed": 0,
            "duration_ms_total": 1_200_000,
            "duration_ms_max": 104_000,
            "input_tokens": 9_000_000,
            "output_tokens": 60_000,
        }
    },
    "timestamp": "2026-08-24T01:04:30.000000Z",
}


def test_viewer_renders_the_run_summary():
    report = viewer.render_report([_SUMMARY_EVENT_FIXTURE])
    assert "RUN METRICS ▸ accepted (review_passed)" in report
    assert "wall            43.3m" in report
    assert "llm calls       178 (0 failed, 6 over 30s)" in report
    assert "tokens          in 13500.0k / out 92.0k" in report
    assert "first preview   15.4m" in report
    assert "rounds          3" in report
    assert "compiles        34" in report
    assert "author          90 calls · 20.0m total · 1.7m slowest" in report


def test_viewer_renders_the_autofix_split_with_its_classes():
    """A reader comparing a fast-loop run against the 178-call baseline needs to
    see how much of the mechanical work the code loop absorbed, and which class
    absorbed it — one under-performing class is the actionable finding."""
    event = dict(
        _SUMMARY_EVENT_FIXTURE,
        autofix_count=4,
        autofix_rolled_back=1,
        autofix_by_class={"slot_fixture": 1, "text_box_hug": 3},
    )
    report = viewer.render_report([event])
    assert "autofix         4 applied (1 rolled back) — slot_fixture×1, text_box_hug×3" in report


def test_viewer_reports_zero_autofix_on_a_pre_fast_loop_run():
    """The fixture below predates §5.4 and carries no autofix keys at all — a
    replayed old run must render, not raise."""
    assert "autofix         0 applied (0 rolled back)" in viewer.render_report(
        [_SUMMARY_EVENT_FIXTURE]
    )


def test_viewer_summary_survives_every_filter():
    """The summary belongs to the whole run, so a narrowed view still shows it —
    the point of the counters is that they are never the thing you have to go
    looking for."""
    for kwargs in ({"role": "author"}, {"tools_only": True}, {"messages_only": True}):
        report = viewer.render_report([_SUMMARY_EVENT_FIXTURE], **kwargs)
        assert "RUN METRICS" in report, kwargs


def test_viewer_reports_a_run_that_never_previewed():
    event = dict(_SUMMARY_EVENT_FIXTURE, time_to_first_preview_ms=None)
    assert "first preview   never rendered" in viewer.render_report([event])
