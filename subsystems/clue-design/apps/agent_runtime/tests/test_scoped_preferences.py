"""Scoped advisory context reaches the real graph without entering durable input state."""

import asyncio
import contextlib
import json

import pytest
from langchain_core.messages import AIMessage
from langgraph.checkpoint.memory import InMemorySaver
from lumen_agent import harness
from test_scene_solo_runtime import offline_models, solo_config

from clue_core import (
    MemoryBundle,
    MemoryBundleEntry,
    MemoryLabel,
    MemoryProvenanceClass,
    MemoryScopeType,
    MemorySelectionStale,
    MemorySelectionUnavailable,
    MemoryType,
)

PREFERENCE = "PREFERENCE_SENTINEL_67: use the approved restrained contrast."
TRIGGER = "TRIGGER_SENTINEL_29: only for this campaign."


def selected_bundle():
    return MemoryBundle(
        workspace_id="ws_preferences",
        recipe="scene-preferences-v1",
        journal_id="125ab955-8bc0-46e6-9bcd-16a99904c9c5",
        entries=(
            MemoryBundleEntry(
                memory_id="mem_selected",
                body=PREFERENCE,
                label=MemoryLabel(
                    scope_type=MemoryScopeType.PROJECT,
                    scope_id="prj_campaign",
                    type=MemoryType.PREFERENCE,
                    trigger=TRIGGER,
                    provenance_class=MemoryProvenanceClass.USER_STATED,
                    trust_grade=4,
                    cycles_since_confirmed=0,
                    confirmation_count=1,
                ),
            ),
        ),
    )


def test_real_graph_receives_labeled_preferences_without_checkpoint_or_workspace_copy(
    tmp_path,
    monkeypatch,
):
    built, _ = offline_models(monkeypatch)
    checkpoint = InMemorySaver()
    graph, tools = harness.create_design_deepagent(
        "Make a new ad",
        solo_config(tmp_path),
        checkpointer=checkpoint,
        scoped_preferences=selected_bundle,
    )
    invoke_config = {"configurable": {"thread_id": "preference-test"}}
    result = graph.invoke(
        {"messages": [{"role": "user", "content": "Make a new ad"}]},
        invoke_config,
    )
    seen = built[0][2].seen
    system = "\n".join(str(m.content) for m in seen[0] if m.type == "system")
    assert PREFERENCE in system and TRIGGER in system
    assert "prj_campaign" in system and "user_stated" in system
    assert "advisory" in system and "current user" in system
    assert PREFERENCE not in repr(result)
    assert PREFERENCE not in repr(list(checkpoint.list(invoke_config)))
    for path in tmp_path.rglob("*"):
        if path.is_file():
            contents = path.read_bytes()
            assert PREFERENCE.encode() not in contents, str(path)
            assert TRIGGER.encode() not in contents, str(path)
    events = [
        json.loads(line) for line in (tools.trace_dir / "trace.jsonl").read_text().splitlines()
    ]
    usage = [e for e in events if e["event"] == "scoped_preferences_resolved"]
    assert usage[-1]["payload"]["memory_ids"] == ["mem_selected"]
    assert usage[-1]["payload"]["bundle_hash"] == selected_bundle().bundle_hash()


def test_stale_selection_refuses_before_model_receives_any_preferences(tmp_path, monkeypatch):
    built, _ = offline_models(monkeypatch)
    graph, _ = harness.create_design_deepagent(
        "Make an ad",
        solo_config(tmp_path),
        scoped_preferences=lambda: MemorySelectionStale(reason="bundle_changed"),
    )
    with pytest.raises(RuntimeError, match="scoped_preferences.*bundle_changed"):
        graph.invoke({"messages": [{"role": "user", "content": "Make an ad"}]})
    assert built[0][2].seen == []


def test_graph_rechecks_selection_on_a_later_model_call(tmp_path, monkeypatch):
    built, _ = offline_models(
        monkeypatch, [AIMessage(content="First."), AIMessage(content="Second.")]
    )
    current = selected_bundle()
    graph, _ = harness.create_design_deepagent(
        "Make an ad",
        solo_config(tmp_path),
        scoped_preferences=lambda: current,
    )
    graph.invoke({"messages": [{"role": "user", "content": "First ad"}]})
    current = MemorySelectionStale(reason="bundle_changed")
    with pytest.raises(RuntimeError, match="scoped_preferences.*bundle_changed"):
        graph.invoke({"messages": [{"role": "user", "content": "Second ad"}]})
    assert len(built[0][2].seen) == 1


@pytest.mark.parametrize("reason", ["memory_disabled", "selected_memory_unavailable"])
def test_revoked_selection_refuses_before_model(tmp_path, monkeypatch, reason):
    built, _ = offline_models(monkeypatch)
    graph, _ = harness.create_design_deepagent(
        "Make an ad",
        solo_config(tmp_path),
        scoped_preferences=lambda: MemorySelectionUnavailable(reason=reason),
    )
    with pytest.raises(RuntimeError, match=f"scoped_preferences.{reason}"):
        graph.invoke({"messages": [{"role": "user", "content": "Make an ad"}]})
    assert built[0][2].seen == []


@pytest.mark.parametrize("cancellable", [False, True])
def test_async_graph_delivers_advice_without_mutating_state(tmp_path, monkeypatch, cancellable):
    from test_scene_catalog_runtime import ScriptedModel

    # The shared sync fixture overrides _generate without positional arguments;
    # supply its async adapter, preserving the actual async graph/middleware path.
    async def generate(self, messages, stop=None, run_manager=None, **kwargs):
        return self._generate(messages, stop=stop, run_manager=run_manager, **kwargs)

    monkeypatch.setattr(ScriptedModel, "_agenerate", generate)
    built, _ = offline_models(monkeypatch)
    graph, _ = harness.create_design_deepagent(
        "Make an ad",
        solo_config(tmp_path),
        scoped_preferences=selected_bundle,
        cancel_requested=(lambda: False) if cancellable else None,
    )
    result = asyncio.run(graph.ainvoke({"messages": [{"role": "user", "content": "Make an ad"}]}))
    assert PREFERENCE in repr(built[0][2].seen)
    assert PREFERENCE not in repr(result)


def test_separate_graphs_do_not_share_advice(tmp_path, monkeypatch):
    built, _ = offline_models(monkeypatch)
    first, _ = harness.create_design_deepagent(
        "First ad",
        solo_config(tmp_path / "first"),
        scoped_preferences=selected_bundle,
    )
    second, _ = harness.create_design_deepagent("Second ad", solo_config(tmp_path / "second"))
    first.invoke({"messages": [{"role": "user", "content": "First ad"}]})
    second.invoke({"messages": [{"role": "user", "content": "Second ad"}]})
    assert PREFERENCE in repr(built[0][2].seen)
    assert PREFERENCE not in repr(built[1][2].seen)


def test_empty_selected_bundle_adds_no_advisory_block(tmp_path, monkeypatch):
    built, _ = offline_models(monkeypatch)
    graph, _ = harness.create_design_deepagent(
        "Make an ad",
        solo_config(tmp_path),
        scoped_preferences=lambda: selected_bundle().model_copy(update={"entries": ()}),
    )
    graph.invoke({"messages": [{"role": "user", "content": "Make an ad"}]})
    assert "<scoped_preference_data>" not in repr(built[0][2].seen)


def test_debug_model_tracing_does_not_copy_resolved_preference_data(tmp_path, monkeypatch):
    from py_lumen_obs import LogMode, capture_events

    monkeypatch.setenv("LUMEN_LOG_MODE", "debug")
    built, _ = offline_models(monkeypatch)
    graph, _ = harness.create_design_deepagent(
        "Make an ad",
        solo_config(tmp_path),
        scoped_preferences=selected_bundle,
    )
    with capture_events(mode=LogMode.DEBUG) as events:
        graph.invoke({"messages": [{"role": "user", "content": "Make an ad"}]})
    started = events.first("llm_call_started")
    assert started is not None and started["messages"]
    assert PREFERENCE in repr(built[0][2].seen)
    assert PREFERENCE not in repr(started)
    assert TRIGGER not in repr(started)
    assert "Make an ad" in repr(started)


def test_durable_workspace_binding_precedes_preference_resolution(tmp_path, monkeypatch):
    built, _ = offline_models(monkeypatch)
    active = []

    @contextlib.contextmanager
    def guard(inner_id, trace_dir):
        assert trace_dir.name == inner_id
        active.append(inner_id)
        try:
            yield
        finally:
            active.clear()

    def resolve():
        assert active, "a private model call needs a durable owned workspace first"
        return selected_bundle()

    harness.run_deepagent_turn(
        "Make an ad",
        solo_config(tmp_path),
        scoped_preferences=resolve,
        runtime_workspace_guard=guard,
    )
    assert built[0][2].seen and active == []


def test_failed_workspace_binding_stops_before_model_or_private_resolution(tmp_path, monkeypatch):
    built, _ = offline_models(monkeypatch)

    @contextlib.contextmanager
    def guard(inner_id, trace_dir):
        raise RuntimeError("binding write unavailable")
        yield  # pragma: no cover -- contextmanager shape, never entered

    def forbidden():
        pytest.fail("private preferences must not be resolved")

    with pytest.raises(RuntimeError, match="binding write unavailable"):
        harness.run_deepagent_turn(
            "Make an ad",
            solo_config(tmp_path),
            scoped_preferences=forbidden,
            runtime_workspace_guard=guard,
        )
    assert built[0][2].seen == []
