"""Deepagent v0 harness (Phase A) — offline unit tests, no LLM calls.

Covers the IMPLEMENTATION-BRIEF §8 test list: workspace scaffolding, the `view`
tool's content structure, the D5 tool-surface contract, the D6 prompt contract,
the constitution state schema, and the runner's honest-failure guarantees.

deepagents is stubbed (as the existing factory test stubs it) so `create_deep_agent`
never builds a real model and no network call fires. `init_model` is monkeypatched
to a sentinel for the same reason.
"""

from __future__ import annotations

import base64
import json
import sys
import types
from pathlib import Path

import pytest

from lumen_agent import harness as harness_mod
from lumen_agent.harness import (
    CONSTITUTION_FIELDS,
    LumenTurnState,
    create_design_deepagent,
    run_deepagent_turn,
)
from lumen_agent.prompts import (
    build_author_prompt,
    build_orchestrator_prompt,
    build_reviewer_prompt,
)
from lumen_agent.prompts import SHARED_SURFACE_CONTRACT
from lumen_agent.tools.substrate import LumenDesignTools

from agent_fixtures import FakeCoreClient, runtime_config


# --- deepagents stub --------------------------------------------------------


class _FakeFilesystemBackend:
    def __init__(self, root_dir: str) -> None:
        self.root_dir = root_dir


class _FakeFilesystemPermission:
    def __init__(self, operations, paths, mode="allow") -> None:
        self.operations = operations
        self.paths = paths
        self.mode = mode


class _FakeDeepAgentState(dict):
    """Stand-in for deepagents.DeepAgentState — a dict subclass, like the real
    one (which is a TypedDict over dict)."""


def _install_deepagents_stub(monkeypatch, capture: dict):
    def fake_create_deep_agent(**kwargs):
        capture["kwargs"] = kwargs
        return types.SimpleNamespace(invoke=lambda *a, **k: {"messages": []}, kwargs=kwargs)

    module = types.ModuleType("deepagents")
    module.create_deep_agent = fake_create_deep_agent
    module.FilesystemPermission = _FakeFilesystemPermission
    module.DeepAgentState = _FakeDeepAgentState
    backends_module = types.ModuleType("deepagents.backends")
    filesystem_module = types.ModuleType("deepagents.backends.filesystem")
    filesystem_module.FilesystemBackend = _FakeFilesystemBackend
    monkeypatch.setitem(sys.modules, "deepagents", module)
    monkeypatch.setitem(sys.modules, "deepagents.backends", backends_module)
    monkeypatch.setitem(sys.modules, "deepagents.backends.filesystem", filesystem_module)
    monkeypatch.setattr("lumen_agent.tools.substrate.CoreClient", FakeCoreClient)
    monkeypatch.setattr(
        "lumen_agent.harness.init_model",
        lambda *a, **k: object(),
        raising=False,
    )
    # init_model is imported lazily inside create_design_deepagent from providers,
    # so also patch it there.
    monkeypatch.setattr(
        "lumen_agent.llm.init_model",
        lambda *a, **k: object(),
        raising=False,
    )


def _tool_name(entry) -> str:
    """Names for both BaseTool objects (`.name`) and bound substrate methods
    (`.__name__`)."""
    return getattr(entry, "name", None) or getattr(entry, "__name__")


# --- fixtures ---------------------------------------------------------------


def seeded_scene() -> dict:
    return {
        "meta": {"id": "doc_live", "title": "Saved doc"},
        "pages": {
            "hero_page": {"id": "hero_page", "children": ["headline"]},
        },
        "nodes": {
            "headline": {
                "id": "headline",
                "kind": {"kind": "text", "content": "Hi"},
                "children": [],
            }
        },
        "slots": {},
        "assets": {},
    }


def _tools_only(config, prompt="Make a poster", initial_scene=None):
    return LumenDesignTools(config, prompt, initial_scene=initial_scene)


# --- 1. workspace scaffolding -----------------------------------------------


def test_workspace_scaffolding(tmp_path, monkeypatch):
    capture: dict = {}
    _install_deepagents_stub(monkeypatch, capture)
    prompt = "Make the headline bigger and add a footer"

    agent, tools = create_design_deepagent(prompt, runtime_config(tmp_path))

    workspace = tools.trace_dir / "workspace"
    brief = (workspace / "brief.md").read_text(encoding="utf-8")
    assert prompt in brief
    assert tools.run_id in brief

    brand_card = (workspace / "brand_card.json").read_text(encoding="utf-8")
    # No kit attached in the fixture -> brand_card is null, dumped as JSON.
    assert json.loads(brand_card) == tools.brand_card

    state = json.loads((workspace / "state.json").read_text(encoding="utf-8"))
    assert set(state.keys()) == set(CONSTITUTION_FIELDS)
    assert state["turn_request"] == prompt

    index = (workspace / "rounds" / "index.md").read_text(encoding="utf-8")
    assert tools.run_id in index
    assert (workspace / "rounds").is_dir()
    assert (workspace / "previews").is_dir()


# --- 2. view tool structure -------------------------------------------------


def _solid_png() -> bytes:
    # 1x1 PNG (valid magic header is enough for base64 round-trip assertions).
    return base64.b64decode(
        "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+M9QDwADhgGAWjR9awAAAABJRU5ErkJggg=="
    )


def test_view_preview_emits_text_and_image_blocks(tmp_path, monkeypatch):
    config = runtime_config(tmp_path)
    monkeypatch.setattr("lumen_agent.tools.substrate.CoreClient", FakeCoreClient)
    tools = _tools_only(config)

    png_bytes = _solid_png()
    png_path = tools.trace_dir / "preview.png"
    png_path.write_bytes(png_bytes)
    # Point the substrate's latest export at the on-disk PNG.
    tools.latest_export_summary = {
        "status": "ok",
        "artifacts": [{"format": "png", "path": str(png_path), "width": 4, "height": 4}],
    }

    view = harness_mod.make_view_tool(tools)
    msg = view.invoke({"name": "view", "args": {"target": "preview"}, "id": "c1", "type": "tool_call"})
    content = msg.content
    assert isinstance(content, list)
    text_blocks = [b for b in content if b["type"] == "text"]
    image_blocks = [b for b in content if b["type"] == "image"]
    assert len(text_blocks) == 1
    assert len(image_blocks) == 1
    img = image_blocks[0]
    assert img["source_type"] == "base64"
    assert img["mime_type"] == "image/png"
    assert base64.b64decode(img["data"]) == png_bytes


def test_view_preview_no_render_returns_text_only(tmp_path, monkeypatch):
    config = runtime_config(tmp_path)
    monkeypatch.setattr("lumen_agent.tools.substrate.CoreClient", FakeCoreClient)
    tools = _tools_only(config)

    view = harness_mod.make_view_tool(tools)
    msg = view.invoke({"name": "view", "args": {"target": "preview"}, "id": "c2", "type": "tool_call"})
    content = msg.content
    assert isinstance(content, list)
    assert all(b["type"] == "text" for b in content)
    assert "no preview" in content[0]["text"].lower()


def test_view_bogus_asset_lists_available_ids(tmp_path, monkeypatch):
    config = runtime_config(tmp_path)
    monkeypatch.setattr("lumen_agent.tools.substrate.CoreClient", FakeCoreClient)
    tools = _tools_only(config)

    view = harness_mod.make_view_tool(tools)
    msg = view.invoke({"name": "view", "args": {"target": "asset:bogus"}, "id": "c3", "type": "tool_call"})
    content = msg.content
    assert isinstance(content, list)
    assert all(b["type"] == "text" for b in content)
    assert "bogus" in content[0]["text"]
    assert "available asset ids" in content[0]["text"].lower()


# --- 3. tool surfaces pinned (D5) -------------------------------------------


def test_tool_surfaces_are_exactly_the_ledger(tmp_path, monkeypatch):
    capture: dict = {}
    _install_deepagents_stub(monkeypatch, capture)

    create_design_deepagent("Design something", runtime_config(tmp_path))
    kwargs = capture["kwargs"]

    orchestrator_tools = {_tool_name(t) for t in kwargs["tools"]}
    assert orchestrator_tools == {
        "view",
        "render_preview",
        "inspect",
        "preflight_design",
        "record_gap",
        "finalize_run",
    }

    subagents = {sa["name"]: sa for sa in kwargs["subagents"]}
    author_tools = {_tool_name(t) for t in subagents["lumen-dsl-author"]["tools"]}
    assert author_tools == {
        "view",
        "inspect",
        "compile_dsl_block",
        "asset",
        "validate_binding_set",
        "preflight_design",
    }

    reviewer_tools = {_tool_name(t) for t in subagents["lumen-visual-reviewer"]["tools"]}
    assert reviewer_tools == {"view", "inspect"}

    assert kwargs["name"] == "lumen-design-deepagent"
    assert subagents["lumen-visual-reviewer"].get("response_format") is not None


# --- 4. prompt contract (D6) ------------------------------------------------


def test_shared_surface_contract_appears_once_in_orchestrator_and_author():
    ws = "/tmp/ws-abc"
    orch = build_orchestrator_prompt(ws)
    author = build_author_prompt(ws)
    reviewer = build_reviewer_prompt(ws)

    marker = "THE SHARED-SURFACE CONTRACT"
    assert orch.count(marker) == 1
    assert author.count(marker) == 1
    # The reviewer cannot edit, so it does NOT carry the contract.
    assert reviewer.count(marker) == 0
    # Full contract body present verbatim.
    assert SHARED_SURFACE_CONTRACT in orch
    assert SHARED_SURFACE_CONTRACT in author


def test_author_prompt_drops_pipeline_output_and_halt_cap_language():
    author = build_author_prompt("/tmp/ws")
    assert "Return DSL only" not in author
    assert "Return Lumen DSL only" not in author
    # No numeric halt-cap language (the user removed the "3 halts -> stop" clause).
    assert "halts you 3" not in author
    assert "three times" not in author


def test_all_prompts_have_resource_map_and_workspace_path():
    ws = "/tmp/unique-workspace-xyz"
    for prompt in (
        build_orchestrator_prompt(ws),
        build_author_prompt(ws),
        build_reviewer_prompt(ws),
    ):
        assert "RESOURCES YOU HAVE" in prompt
        assert ws in prompt


# --- 5. state schema --------------------------------------------------------


def test_state_schema_declares_exactly_six_constitution_fields():
    # A TypedDict subclass merges parent annotations into __annotations__; the
    # constitution is exactly the six fields LumenTurnState adds over its base.
    from lumen_agent.models import state as state_mod
    base_fields = set(getattr(state_mod._DeepAgentStateBase, "__annotations__", {}).keys())
    added_fields = set(LumenTurnState.__annotations__.keys()) - base_fields
    assert added_fields == set(CONSTITUTION_FIELDS)
    assert len(CONSTITUTION_FIELDS) == 6


def test_initial_state_carries_seeded_chips_and_kit_ref(tmp_path, monkeypatch):
    capture: dict = {}
    _install_deepagents_stub(monkeypatch, capture)

    from dataclasses import replace as dc_replace

    base = runtime_config(tmp_path)
    config = dc_replace(base, turn_target_node_ids=["headline"])

    tools = _tools_only(config, prompt="Recolor the headline", initial_scene=seeded_scene())
    state = harness_mod.initial_turn_state(tools, "Recolor the headline")

    assert state["seeded"] is True
    assert state["chip_target_node_ids"] == ["headline"]
    assert state["artboard_id"] == "hero_page"
    assert state["turn_request"] == "Recolor the headline"
    assert state["current_round"] == 0
    assert isinstance(state["brand_kit_ref"], dict)


# --- 6. runner honesty ------------------------------------------------------


def test_runner_honest_failure_on_invoke_exception(tmp_path, monkeypatch):
    capture: dict = {}

    def fake_create_deep_agent(**kwargs):
        capture["kwargs"] = kwargs

        def _boom(*a, **k):
            raise RuntimeError("model exploded mid-turn")

        return types.SimpleNamespace(invoke=_boom, kwargs=kwargs)

    module = types.ModuleType("deepagents")
    module.create_deep_agent = fake_create_deep_agent
    module.FilesystemPermission = _FakeFilesystemPermission
    module.DeepAgentState = _FakeDeepAgentState
    backends_module = types.ModuleType("deepagents.backends")
    filesystem_module = types.ModuleType("deepagents.backends.filesystem")
    filesystem_module.FilesystemBackend = _FakeFilesystemBackend
    monkeypatch.setitem(sys.modules, "deepagents", module)
    monkeypatch.setitem(sys.modules, "deepagents.backends", backends_module)
    monkeypatch.setitem(sys.modules, "deepagents.backends.filesystem", filesystem_module)
    monkeypatch.setattr("lumen_agent.tools.substrate.CoreClient", FakeCoreClient)
    monkeypatch.setattr("lumen_agent.llm.init_model", lambda *a, **k: object())

    payload, tools = run_deepagent_turn("Design a card", runtime_config(tmp_path))

    assert payload["status"] == "failed"
    assert payload["stop_reason"] == "orchestrator_did_not_finalize"
    final_path = tools.trace_dir / "final.json"
    assert final_path.exists()
    # Exception text recorded verbatim in the trace.
    trace = (tools.trace_dir / "trace.jsonl").read_text(encoding="utf-8")
    assert "model exploded mid-turn" in trace
    assert "RuntimeError" in trace


def test_runner_honest_failure_when_agent_never_finalizes(tmp_path, monkeypatch):
    capture: dict = {}
    _install_deepagents_stub(monkeypatch, capture)  # invoke returns cleanly, no final.json

    payload, tools = run_deepagent_turn("Design a card", runtime_config(tmp_path))

    assert payload["status"] == "failed"
    assert payload["stop_reason"] == "orchestrator_did_not_finalize"
    assert (tools.trace_dir / "final.json").exists()
    assert payload["summary"] == "agent ended without finalize"
