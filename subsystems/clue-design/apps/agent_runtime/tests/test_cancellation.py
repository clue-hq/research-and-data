"""A3 (defect R3-D) — a cancel surface for an in-flight design turn.

THE DEFECT THIS FILE PINS. During the W5 Apollo walk (`.context/w5-apollo-e2e-report.md` §R3.7) a
manual-reference run was visibly doomed within its first minute and had to be watched to
completion, because nothing in the system could ask it to stop. Every test below is a statement
about that run shape: it stops now, at a bounded boundary, and what it had already earned is
still there afterwards.

WHAT IS AND IS NOT PROVEN HERE. The graph is stubbed (as every harness suite stubs it), so no
model is built and no network call fires. What that stub CAN reproduce faithfully is the one
thing that matters: the callback seam fires before each model call, and it is the only place a
running graph can be refused. The durable half — the row the request is written to and read
back from across a worker restart — is proven in `apps/api/tests/test_agent_run_cancel.py`,
against real Postgres.

deepagents is stubbed exactly as `test_deepagent_harness.py` stubs it.
"""

from __future__ import annotations

import json
import types
from pathlib import Path

import pytest

from lumen_agent import harness as harness_mod
from lumen_agent.budget import BudgetExhausted
from lumen_agent.cancellation import (
    CANCELLED_EVENT,
    CANCELLED_STOP_REASON,
    CancellationCallbackHandler,
    CancellationProbe,
    TurnCancelled,
    attach_cancellation_callback,
)
from lumen_agent.harness import create_design_deepagent, run_deepagent_turn

from agent_fixtures import runtime_config
from test_deepagent_harness import _install_deepagents_stub


# --- helpers ----------------------------------------------------------------


def _install_callbackable_models(monkeypatch) -> None:
    """Make the stubbed role models accept callbacks.

    `_install_deepagents_stub` returns a bare `object()` from `init_model`, which has no writable
    `callbacks` field — and `attach_cancellation_callback` deliberately leaves such a sentinel
    untouched. That is correct production behaviour and useless for asserting attachment, so the
    suites that care about the callback seam swap in a model shaped like the real one.
    """
    monkeypatch.setattr(
        "lumen_agent.llm.init_model",
        lambda *a, **k: types.SimpleNamespace(callbacks=[]),
        raising=False,
    )


def _cancel_handlers(model) -> list:
    return [h for h in model.callbacks if isinstance(h, CancellationCallbackHandler)]


class _CallDrivenAgent:
    """Stands in for the compiled graph: an unbounded loop of model calls.

    THE DOOMED-RUN SHAPE, in six lines. It never finishes on its own — exactly like the W5 run —
    so anything that ends it ended it from outside. Each iteration fires the role model's
    callbacks the way langchain does before a call, and lands a round's worth of work into the
    scene so there is something real to either keep or lose.
    """

    #: A test-only guard so the "nothing stops it" case below can be OBSERVED rather than hung on.
    #: The production shape is genuinely unbounded; this ceiling exists only so a red case can be
    #: asserted in finite time, and every green case stops far below it.
    RUNAWAY_GUARD = 25

    def __init__(self, tools, model, *, authors: bool = True) -> None:
        self._tools = tools
        self._model = model
        self._authors = authors
        self.calls = 0

    def invoke(self, *args, **kwargs):
        while self.calls < self.RUNAWAY_GUARD:
            for handler in list(self._model.callbacks):
                handler.on_chat_model_start({}, [])
            self.calls += 1
            if self._authors:
                # A round's work lands as it goes — this is what must survive a cancel.
                self._tools.scene = {
                    **self._tools.scene,
                    "nodes": {"headline": {"id": "headline", "children": []}},
                }


def _drive(monkeypatch, tmp_path, *, probe=None, cancel_after=None, authors=True):
    """Run one stubbed turn, returning (payload, tools, agent).

    `cancel_after=N` is the readable form of "a human hits cancel once N model calls have been
    made", stated against the agent's own counter rather than against a count of probe reads —
    the runner probes once BEFORE it invokes at all, and a test that quietly absorbed that
    off-by-one would be pinning an accident.
    """
    capture: dict = {}
    _install_deepagents_stub(monkeypatch, capture)
    _install_callbackable_models(monkeypatch)

    holder: dict = {}
    real = harness_mod.create_design_deepagent

    def fake_create(prompt, **kwargs):
        _agent, tools = real(prompt, **kwargs)
        model = capture["kwargs"]["model"]
        agent = _CallDrivenAgent(tools, model, authors=authors)
        holder["agent"] = agent
        return agent, tools

    if probe is None:
        def probe() -> bool:
            agent = holder.get("agent")
            return agent is not None and agent.calls >= cancel_after

    monkeypatch.setattr(harness_mod, "create_design_deepagent", fake_create)
    payload, tools = run_deepagent_turn(
        "Design something", runtime_config(tmp_path), cancel_requested=probe
    )
    return payload, tools, holder.get("agent")


# ===========================================================================
# 1. NO PROBE — byte-identical
# ===========================================================================


def test_a_turn_with_no_probe_attaches_no_cancellation_handler(monkeypatch, tmp_path) -> None:
    """The CLI / fixture / offline / synchronous-preview contract: nothing changed.

    Cancellation is a fleet-path capability because only a fleet-path turn has a run row a second
    caller can name. Every other caller must keep the callback list it always had — that is what
    makes this feature unable to regress the paths it does not serve.
    """
    capture: dict = {}
    _install_deepagents_stub(monkeypatch, capture)
    _install_callbackable_models(monkeypatch)

    create_design_deepagent("Design something", runtime_config(tmp_path))

    assert _cancel_handlers(capture["kwargs"]["model"]) == []


def test_a_turn_with_no_probe_calls_instrument_with_the_pre_a3_argument_list(
    monkeypatch, tmp_path
) -> None:
    """`_instrument` is a shipped monkeypatch seam, and A3 must not move it for callers it does
    not serve.

    Two suites spy on it with a five-parameter signature. A sixth positional argument broke both
    the first time this was written — a suite failing over a parameter its subject never uses is
    a false alarm about a real seam, so the probe is keyword-only AND omitted when absent. This
    pins that: no probe, no extra argument, of any kind.
    """
    capture: dict = {}
    _install_deepagents_stub(monkeypatch, capture)
    _install_callbackable_models(monkeypatch)

    seen: list = []
    real = harness_mod._instrument

    def five_parameter_spy(cfg, tools, model_id, role, budget=None):
        seen.append(role)
        return real(cfg, tools, model_id, role, budget)

    monkeypatch.setattr(harness_mod, "_instrument", five_parameter_spy)
    create_design_deepagent("Design something", runtime_config(tmp_path))

    assert seen == ["orchestrator", "author", "reviewer"]


def test_a_probe_attaches_the_handler_to_every_role(monkeypatch, tmp_path) -> None:
    """All three minds, not just the orchestrator.

    A cancel that only the orchestrator honoured would be no cancel at all: the expensive part of
    a doomed run is the AUTHOR's delegated round, and the orchestrator is blocked inside `task`
    while that runs. The budget is shared across the roles for the same reason (§5.6, "the
    orchestrator cannot buy itself more calls by delegating") — so is this.
    """
    capture: dict = {}
    _install_deepagents_stub(monkeypatch, capture)
    _install_callbackable_models(monkeypatch)

    create_design_deepagent(
        "Design something", runtime_config(tmp_path), cancel_requested=lambda: False
    )

    orchestrator = capture["kwargs"]["model"]
    subagent_models = [sa["model"] for sa in capture["kwargs"]["subagents"]]
    assert len(_cancel_handlers(orchestrator)) == 1
    for model in subagent_models:
        assert len(_cancel_handlers(model)) == 1


# ===========================================================================
# 2. THE SEAM
# ===========================================================================


def test_the_cancellation_callback_raises_rather_than_being_swallowed() -> None:
    """`raise_error` is the whole mechanism.

    Without langchain-core's documented opt-in, `handle_event` logs our exception and carries on —
    and a cancel becomes a wish. Pinned as an attribute assertion as well as a behavioural one
    because the attribute is what the framework actually reads.
    """
    handler = CancellationCallbackHandler(lambda: True, "orchestrator")
    assert handler.raise_error is True
    with pytest.raises(TurnCancelled):
        handler.on_chat_model_start({}, [])
    with pytest.raises(TurnCancelled):
        handler.on_llm_start({}, [])


def test_an_uncancelled_run_is_never_refused() -> None:
    handler = CancellationCallbackHandler(lambda: False, "author")
    assert handler.on_chat_model_start({}, []) is None


def test_unknown_hooks_are_inert() -> None:
    """langchain probes a wide, version-dependent hook surface; a missing one must be a no-op."""
    handler = CancellationCallbackHandler(lambda: False, "author")
    assert handler.on_some_future_hook_we_do_not_implement() is None
    with pytest.raises(AttributeError):
        handler.not_a_hook


# ===========================================================================
# 3. THE PROBE
# ===========================================================================


def test_the_probe_is_sticky() -> None:
    """Once cancelled, always cancelled — a run must not be able to resume itself.

    The source is consulted exactly once after it answers True; everything after that is answered
    from memory, which is both cheaper and impossible to un-say.
    """
    answers = iter([True, False, False])
    reads = {"n": 0}

    def source() -> bool:
        reads["n"] += 1
        return next(answers)

    probe = CancellationProbe(source, min_interval_s=0.0)
    assert probe() is True
    assert probe() is True
    assert reads["n"] == 1


def test_the_probe_throttles_only_the_negative_answer() -> None:
    """A burst of cheap calls must not become a burst of queries — but never at a cancel's cost."""
    now = {"t": 100.0}
    reads = {"n": 0}
    cancelled = {"yes": False}

    def source() -> bool:
        reads["n"] += 1
        return cancelled["yes"]

    probe = CancellationProbe(source, min_interval_s=5.0, clock=lambda: now["t"])
    assert probe() is False
    assert probe() is False  # inside the window: answered without a read
    assert reads["n"] == 1

    now["t"] += 5.0
    cancelled["yes"] = True
    assert probe() is True
    assert reads["n"] == 2


def test_the_probe_fails_open_on_a_read_fault() -> None:
    """A database blip must never become a run's cause of death.

    Stopping a run nobody asked about is a strictly worse failure than missing a cancel for one
    more model call, and the next call re-reads — so the error is swallowed and read as "no".
    """
    def source() -> bool:
        raise RuntimeError("connection reset")

    probe = CancellationProbe(source, min_interval_s=0.0)
    assert probe() is False
    assert probe() is False


# ===========================================================================
# 4. THE STOP, END TO END THROUGH THE RUNNER
# ===========================================================================


def test_the_defect_itself_a_run_with_no_cancel_path_cannot_be_stopped(
    monkeypatch, tmp_path
) -> None:
    """THE RED CASE, EXECUTED. This is the W5 run, and it is unstoppable.

    With no probe — which is the ONLY shape the pre-A3 code could produce, since neither the
    parameter nor the callback existed — the same agent runs until its own test-only guard,
    spending every call. Nothing in the process can interrupt it. Kept green on purpose: it is
    the control the test below is measured against, and it fails the moment someone tries to
    "fix" cancellation somewhere other than the boundary the probe reaches.
    """
    payload, tools, agent = _drive(monkeypatch, tmp_path, probe=None, cancel_after=10**9)

    assert agent.calls == _CallDrivenAgent.RUNAWAY_GUARD
    assert payload["stop_reason"] != CANCELLED_STOP_REASON


def test_a_cancelled_run_stops_at_the_next_call_boundary_and_keeps_its_work(
    monkeypatch, tmp_path
) -> None:
    """THE W5 DEFECT, CLOSED. The doomed run ends, and it ends honestly.

    `_CallDrivenAgent` never terminates on its own — it is the run that had to be waited out. The
    human cancels once three calls have been made; the fourth is refused at its boundary, so the
    run made exactly the calls it was allowed to make and not one more. What it had authored by
    then is still in the scene, which is the P0.4 guarantee this path must not undo.
    """
    payload, tools, agent = _drive(monkeypatch, tmp_path, cancel_after=3)

    assert agent.calls == 3  # the 4th call was refused BEFORE it was paid for
    assert payload["status"] == "completed_with_warnings"
    assert payload["stop_reason"] == CANCELLED_STOP_REASON
    # Not `accepted`, and not `failed` — nothing accepted this, and nothing failed.
    assert payload["status"] != "accepted"
    # The work stands.
    assert tools.scene["nodes"]["headline"]["id"] == "headline"
    # And the incompleteness is in the ledger the editor reads, not only in a log line.
    assert tools.gaps
    assert tools.gaps[-1]["area"] == "agent_protocol"
    assert "cancel" in tools.gaps[-1]["summary"].lower()


def test_a_cancelled_run_that_authored_nothing_is_failed_not_fabricated(
    monkeypatch, tmp_path
) -> None:
    """NEVER FABRICATE. A cancel is not a licence to call an empty run a partial success."""
    payload, tools, agent = _drive(
        monkeypatch, tmp_path, probe=lambda: True, authors=False
    )

    assert payload["status"] == "failed"
    assert payload["stop_reason"] == CANCELLED_STOP_REASON
    assert "no draft to keep" in payload["summary"]


def test_a_run_cancelled_before_its_first_call_never_enters_the_graph(
    monkeypatch, tmp_path
) -> None:
    """The boundary BEFORE the first call.

    A run cancelled while it sat queued — or between a lease takeover and its redrive — must not
    pay for one call to discover that. The callback seam can only refuse a call already being
    made, so the runner checks once more before it invokes at all.
    """
    payload, tools, agent = _drive(monkeypatch, tmp_path, probe=lambda: True)

    assert agent.calls == 0
    assert payload["stop_reason"] == CANCELLED_STOP_REASON


def test_a_cancel_arriving_after_finalize_does_not_rewrite_the_result(
    monkeypatch, tmp_path
) -> None:
    """Too late is an honest answer.

    A turn the orchestrator already finalized is finished. Rewriting its real result as a
    cancellation would be exactly the fabrication the whole result envelope exists to prevent —
    so `final.json` outranks both interrupt paths, cancellation included.
    """
    capture: dict = {}
    _install_deepagents_stub(monkeypatch, capture)
    _install_callbackable_models(monkeypatch)

    holder: dict = {"finalized": False}
    real = harness_mod.create_design_deepagent

    class _FinalizesThenIsCancelled:
        def __init__(self, tools, model) -> None:
            self._tools = tools
            self._model = model

        def invoke(self, *args, **kwargs):
            self._tools.finalize_run("accepted", "accepted", "The design is done.")
            holder["finalized"] = True
            for handler in list(self._model.callbacks):
                handler.on_chat_model_start({}, [])

    def fake_create(prompt, **kwargs):
        _agent, tools = real(prompt, **kwargs)
        holder["tools"] = tools
        return _FinalizesThenIsCancelled(tools, capture["kwargs"]["model"]), tools

    monkeypatch.setattr(harness_mod, "create_design_deepagent", fake_create)
    payload, _tools = run_deepagent_turn(
        "Design something",
        runtime_config(tmp_path),
        # The cancel lands strictly AFTER the orchestrator finalized — which is the whole point.
        cancel_requested=lambda: holder["finalized"],
    )

    assert payload["status"] == "accepted"
    assert payload["stop_reason"] == "accepted"


def test_the_cancel_is_announced_on_the_run_event_stream(monkeypatch, tmp_path) -> None:
    """SSE consumers learn the moment the cancel is honoured, not only when the run ends.

    `LumenDesignTools.record` is BOTH the file trace and the live event push, so the runner's one
    record call is the stream event. `sink_extra` is the only channel that rides the push, which
    is why the stop reason is asserted there.
    """
    events: list = []
    capture: dict = {}
    _install_deepagents_stub(monkeypatch, capture)
    _install_callbackable_models(monkeypatch)

    real = harness_mod.create_design_deepagent

    def fake_create(prompt, **kwargs):
        _agent, tools = real(prompt, **kwargs)
        return _CallDrivenAgent(tools, capture["kwargs"]["model"]), tools

    monkeypatch.setattr(harness_mod, "create_design_deepagent", fake_create)
    run_deepagent_turn(
        "Design something",
        runtime_config(tmp_path),
        event_sink=lambda event, data: events.append((event, data)),
        cancel_requested=lambda: True,
    )

    cancelled = [data for event, data in events if event == CANCELLED_EVENT]
    assert cancelled, f"no {CANCELLED_EVENT} event on the stream; saw {[e for e, _ in events]}"
    assert cancelled[0]["stop_reason"] == CANCELLED_STOP_REASON


# ===========================================================================
# 5. WEBSITE MODE — the same route must be able to stop either kind of run
# ===========================================================================


def test_a_web_turn_with_no_probe_calls_instrument_with_the_pre_a3_argument_list(
    monkeypatch, tmp_path
) -> None:
    """The web harness's `_instrument` seam is spied on with a FOUR-parameter signature
    (`test_web_review_cap.py`), so the same omit-when-absent rule applies here."""
    import deepagents

    import lumen_agent.llm as llm
    from lumen_agent import harness_web
    from lumen_agent.config import AgentRuntimeConfig
    from lumen_api.core import CoreClient

    repo_root = Path(__file__).resolve().parents[3]
    captured: dict = {}
    monkeypatch.setattr(deepagents, "create_deep_agent", lambda **kwargs: captured.update(kwargs))
    monkeypatch.setattr(harness_web, "materialize_agent_workspace", lambda _config: None)
    monkeypatch.setattr(
        harness_web, "_instrument", lambda _config, _tools, _model, role: f"{role}-model"
    )
    monkeypatch.setattr(llm, "assert_all_role_models_support_image_input", lambda _config: None)

    from dataclasses import replace as _replace

    config = _replace(
        AgentRuntimeConfig.from_env(repo_root), trace_dir=tmp_path / "workspace"
    )
    web_doc = CoreClient(repo_root=repo_root).web_new_doc("doc_a3", "A3", None)["web_doc"]

    harness_web.create_web_deepagent("Build a page.", config, web_doc)

    assert captured["model"] == "orchestrator-model"


def test_a_cancelled_web_turn_is_failed_with_nothing_applied(monkeypatch, tmp_path) -> None:
    """Website mode's honest cancelled outcome, and why it differs from the scene path's.

    A web turn authors the page and persists ONCE, at the end — there is no P0.4 mid-run
    checkpoint, so a stopped web turn has no partial work to keep. `failed` with an empty
    operations ledger is therefore the whole truth, and a `completed_with_warnings` here would be
    the fabrication the result envelope exists to prevent. The path itself is the harness's
    pre-existing honest-failure finalize; A3 only made its reason truthful.
    """
    import deepagents

    import lumen_agent.llm as llm
    from lumen_agent import harness_web
    from lumen_agent.config import AgentRuntimeConfig
    from lumen_api.core import CoreClient

    repo_root = Path(__file__).resolve().parents[3]

    monkeypatch.setattr(
        deepagents,
        "create_deep_agent",
        lambda **kwargs: types.SimpleNamespace(invoke=lambda *a, **k: {"messages": []}),
    )
    monkeypatch.setattr(harness_web, "materialize_agent_workspace", lambda _config: None)
    monkeypatch.setattr(llm, "assert_all_role_models_support_image_input", lambda _config: None)

    from dataclasses import replace as _replace

    config = _replace(
        AgentRuntimeConfig.from_env(repo_root), trace_dir=tmp_path / "workspace"
    )
    web_doc = CoreClient(repo_root=repo_root).web_new_doc("doc_a3b", "A3", None)["web_doc"]

    events: list = []
    result = harness_web.run_deepagent_web_turn(
        prompt="Build a page.",
        config=config,
        initial_web_doc=web_doc,
        event_sink=lambda event, data: events.append((event, data)),
        cancel_requested=lambda: True,
    )

    assert result["status"] == "failed"
    assert result["operations"] == []
    assert "cancelled by request" in result["summary"]
    assert [e for e, _ in events if e == CANCELLED_EVENT]


# ===========================================================================
# 6. THE SHARED FINALIZE — reused, not reimplemented
# ===========================================================================


def test_both_interrupts_land_through_the_one_graceful_finalize(monkeypatch, tmp_path) -> None:
    """The budget's honest stop and the cancel's are the SAME code, differing only in words.

    A3's constraint, pinned mechanically: `_finalize_interrupted_run` is the single body, and both
    named entry points delegate to it. If someone ever copies the body to "customise" one of them,
    this fails — which is the point, because a look-alike finalize is how the two paths' honesty
    guarantees quietly drift apart.
    """
    seen: list = []
    real = harness_mod._finalize_interrupted_run

    def spy(tools, **kwargs):
        seen.append(kwargs["stop_reason"])
        return real(tools, **kwargs)

    monkeypatch.setattr(harness_mod, "_finalize_interrupted_run", spy)

    tools = types.SimpleNamespace(
        scene={"nodes": {}},
        gaps=[],
        record_gap=lambda *a, **k: None,
        finalize_run=lambda status, stop_reason, summary: json.dumps(
            {"status": status, "stop_reason": stop_reason, "summary": summary}
        ),
    )
    harness_mod._finalize_on_cancelled(tools, TurnCancelled())
    harness_mod._finalize_on_budget_exhausted(
        tools, BudgetExhausted("wall_clock", 1800.0, 1801.0)
    )

    assert seen == [CANCELLED_STOP_REASON, "budget_exhausted_wall_clock"]


def test_the_budget_path_s_words_are_unchanged() -> None:
    """A3 refactored the budget finalize's BODY out; its OUTPUT must be untouched.

    The `budget_exhausted_<axis>` stop reason is pinned by the fast-loop suite and read by
    operators; the summary's opening clause is what a founder sees in the editor. Both are
    asserted here so the extraction that shares the body cannot silently reword the older caller.
    """
    written: dict = {}
    tools = types.SimpleNamespace(
        scene={"nodes": {"headline": {}}},
        gaps=[],
        record_gap=lambda *a, **k: None,
        finalize_run=lambda status, stop_reason, summary: json.dumps(
            written.update(status=status, stop_reason=stop_reason, summary=summary) or written
        ),
    )
    harness_mod._finalize_on_budget_exhausted(
        tools, BudgetExhausted("wall_clock", 1800.0, 1801.5)
    )

    assert written["status"] == "completed_with_warnings"
    assert written["stop_reason"] == "budget_exhausted_wall_clock"
    assert written["summary"].startswith(
        "Stopped at the wall_clock budget (1800 allowed, 1801.5 observed) "
        "before the design was accepted. "
    )
    assert written["summary"].endswith(
        "A draft stands and every accepted round was already saved to the "
        "document; what remains is recorded as a gap."
    )
