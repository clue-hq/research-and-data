"""One design document = one session folder; each turn owns a subfolder.

Design session continuity (2026-09-18). When ``AgentRuntimeConfig.session_id`` is
set, a turn's substrate lands inside the PERSISTENT session folder
``<trace_dir>/sessions/<session_id>/``: harness-owned per-turn outputs go under
``turns/<run_id>/`` (``turn_dir``) while the agent-visible ``workspace/`` — the
thing the model reads and writes across turns — stays on the session root, and
round directories keep numbering across the whole session instead of restarting
at 1 on every turn.

With ``session_id = None`` (editor preview, CLI, fixtures) every path is
byte-identical to before: ``trace_dir == <configured trace_dir>/<run_id>`` and
``turn_dir == trace_dir``.
"""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import pytest
from agent_fixtures import FakeCoreClient, runtime_config
from lumen_agent.config import AgentRuntimeConfig
from lumen_agent.tools.substrate import LumenDesignTools
from lumen_agent.tools.web_substrate import LumenWebTools
from lumen_agent.workspace import scaffold_workspace, workspace_root

REPO_ROOT = Path(__file__).resolve().parents[3]


def _tools(config, prompt: str = "p") -> LumenDesignTools:
    """Mirror of ``test_deepagent_harness._tools_only`` (engine stubbed by caller)."""
    return LumenDesignTools(config, prompt, initial_scene=None)


# --- the scene substrate ----------------------------------------------------
def test_without_a_session_the_run_folder_is_unchanged(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr("lumen_agent.tools.substrate.CoreClient", FakeCoreClient)
    tools = _tools(replace(runtime_config(tmp_path), trace_dir=tmp_path))
    assert tools.trace_dir == tmp_path / tools.run_id
    assert tools.turn_dir == tools.trace_dir
    assert tools.workspace_scope_id == tools.run_id
    assert tools.round_base == 0


def test_a_session_owns_one_folder_and_each_turn_a_subfolder(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr("lumen_agent.tools.substrate.CoreClient", FakeCoreClient)
    config = replace(runtime_config(tmp_path), trace_dir=tmp_path, session_id="dsess_abc")
    first = _tools(config)
    second = _tools(config)
    assert first.trace_dir == second.trace_dir == tmp_path / "sessions" / "dsess_abc"
    assert first.turn_dir == first.trace_dir / "turns" / first.run_id
    assert second.turn_dir != first.turn_dir
    assert first.workspace_scope_id == "sessions/dsess_abc"
    assert workspace_root(first) == workspace_root(second)


def test_a_config_supplied_run_id_is_the_turns_own_id(tmp_path, monkeypatch) -> None:
    # A leg turn passes the PLATFORM's design run id, so a retried run lands back in the same
    # turn folder and stamps the same `lumen_run_id` on its human message — which is what lets
    # `checkpoint.invoke_turn_graph` recognise the retry and resume instead of re-prompting.
    monkeypatch.setattr("lumen_agent.tools.substrate.CoreClient", FakeCoreClient)
    config = replace(
        runtime_config(tmp_path), trace_dir=tmp_path, session_id="dsess_fixed", run_id="run_fixed"
    )
    tools = _tools(config)
    assert tools.run_id == "run_fixed"
    assert tools.turn_dir == tools.trace_dir / "turns" / "run_fixed"
    assert _tools(config).turn_dir == tools.turn_dir, "a retry reuses its own turn folder"
    # No supplied id → a fresh one per construction, exactly as before.
    minted = replace(config, run_id=None)
    assert _tools(minted).run_id != _tools(minted).run_id


def test_rounds_continue_numbering_across_turns(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr("lumen_agent.tools.substrate.CoreClient", FakeCoreClient)
    config = replace(runtime_config(tmp_path), trace_dir=tmp_path, session_id="dsess_r")
    first = _tools(config)
    scaffold_workspace(first, "p")
    (workspace_root(first) / "rounds" / "round_1").mkdir(parents=True)
    (workspace_root(first) / "rounds" / "round_2").mkdir()
    second = _tools(config)
    assert second.round_base == 2
    scaffold_workspace(second, "p2")
    index = (workspace_root(second) / "rounds" / "index.md").read_text()
    assert index.count("# Rounds") == 1 and f"## Turn {second.run_id}" in index
    assert (workspace_root(second) / "rounds" / "round_1").is_dir(), (
        "earlier rounds are never deleted"
    )


def test_a_second_turns_solo_round_follows_the_sessions_highest(tmp_path, monkeypatch) -> None:
    """The solo construction round is numbered off ``round_base``, so turn two's
    first round is ``round_3`` — not a second ``round_1`` overwriting turn one's."""
    monkeypatch.setattr("lumen_agent.tools.substrate.CoreClient", FakeCoreClient)
    config = replace(
        runtime_config(tmp_path),
        trace_dir=tmp_path,
        session_id="dsess_solo",
        scene_solo=True,
        scene_skill_bundle="candidate",
        fast_loop=True,
    )
    first = _tools(config)
    scaffold_workspace(first, "p")
    (workspace_root(first) / "rounds" / "round_1").mkdir(parents=True)
    (workspace_root(first) / "rounds" / "round_2").mkdir()

    second = _tools(config)
    second._validated_direction_digest = "digest"
    second._begin_solo_construction()
    assert (workspace_root(second) / "rounds" / "round_3").is_dir()
    assert second._fast_loop_round_number() == 3


def test_turn_outputs_land_in_the_turn_folder(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr("lumen_agent.tools.substrate.CoreClient", FakeCoreClient)
    config = replace(runtime_config(tmp_path), trace_dir=tmp_path, session_id="dsess_o")
    tools = _tools(config)
    assert (tools.turn_dir / "input.json").is_file()
    tools.record("coordinator", "x", output_summary="y")
    assert (tools.turn_dir / "trace.jsonl").is_file()
    assert not (tools.trace_dir / "trace.jsonl").exists()


def test_iterations_live_under_the_turn_folder(tmp_path, monkeypatch) -> None:
    """Per-iteration artifacts are this turn's, not the session's."""
    monkeypatch.setattr("lumen_agent.tools.substrate.CoreClient", FakeCoreClient)
    config = replace(runtime_config(tmp_path), trace_dir=tmp_path, session_id="dsess_i")
    tools = _tools(config)
    assert tools.iterations_dir == tools.turn_dir / "iterations"
    assert tools.iterations_dir.is_dir()


# --- the web substrate ------------------------------------------------------
def _web_tools(config) -> LumenWebTools:
    """Mirror of ``test_web_substrate._tools`` (the real deterministic core)."""
    from lumen_api.core import CoreClient

    core = CoreClient(repo_root=REPO_ROOT)
    seed = core.web_new_doc("doc_web_session", "Test site", None)["web_doc"]
    return LumenWebTools(config, "Build a page", initial_web_doc=seed)


@pytest.fixture()
def _web_config(tmp_path: Path) -> AgentRuntimeConfig:
    return replace(AgentRuntimeConfig.from_env(REPO_ROOT), trace_dir=tmp_path)


def test_web_without_a_session_the_run_folder_is_unchanged(_web_config, tmp_path) -> None:
    tools = _web_tools(_web_config)
    assert tools.trace_dir == tmp_path / tools.run_id
    assert tools.turn_dir == tools.trace_dir
    assert tools.workspace_scope_id == tools.run_id
    # The component projection is session-wide, so it stays on the session root —
    # which for a run without a session IS the run folder.
    assert tools.custom_component_projection_root == tools.trace_dir / "custom_components"


def test_web_session_turns_get_their_own_subfolder(_web_config, tmp_path) -> None:
    config = replace(_web_config, session_id="dsess_web")
    first = _web_tools(config)
    second = _web_tools(config)
    assert first.trace_dir == second.trace_dir == tmp_path / "sessions" / "dsess_web"
    assert first.turn_dir == first.trace_dir / "turns" / first.run_id
    assert second.turn_dir != first.turn_dir
    assert first.workspace_scope_id == "sessions/dsess_web"
    # Custom components are derived once per session root, shared by its turns.
    assert first.custom_component_projection_root == first.trace_dir / "custom_components"
    first.record("coordinator", "x", output_summary="y")
    assert (first.turn_dir / "trace.jsonl").is_file()
    assert not (first.trace_dir / "trace.jsonl").exists()


def test_web_a_config_supplied_run_id_is_the_turns_own_id(_web_config, tmp_path) -> None:
    # Same contract on the web substrate — see the scene case above.
    config = replace(_web_config, session_id="dsess_web_fixed", run_id="run_fixed")
    tools = _web_tools(config)
    assert tools.run_id == "run_fixed"
    assert tools.turn_dir == tools.trace_dir / "turns" / "run_fixed"
    assert _web_tools(config).turn_dir == tools.turn_dir, "a retry reuses its own turn folder"
    minted = replace(config, run_id=None)
    assert _web_tools(minted).run_id != _web_tools(minted).run_id
