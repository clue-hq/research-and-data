"""Live-design-streaming S0 (D1): the event_sink push now carries an OPT-IN
`sink_extra` channel so a SUCCESSFUL authoring mutation streams its applied
`operations` list to the client, while non-mutating events (and refused drafts)
keep the lean five summary fields.

These exercise the live substrate (`lumen_agent.tools.substrate`) against the
offline FakeCoreClient — the same monkeypatch idiom the harness tests use. The
trace.jsonl shape is deliberately NOT asserted here: `sink_extra` rides the sink
push only, never the trace (which already carries the full payload).
"""
from __future__ import annotations

import json

import pytest

from lumen_api.core import CoreError

from agent_fixtures import FakeCoreClient, runtime_config

BASE_SINK_KEYS = {
    "actor",
    "iteration",
    "input_summary",
    "output_summary",
    "diagnostic_count",
}


def _build_tools(tmp_path, monkeypatch, prompt="design a launch poster", initial_scene=None):
    monkeypatch.setattr("lumen_agent.tools.substrate.CoreClient", FakeCoreClient)
    from lumen_agent.tools.substrate import LumenDesignTools

    return LumenDesignTools(runtime_config(tmp_path), prompt, initial_scene=initial_scene)


def _attach_sink(tools):
    pushes: list[tuple[str, dict]] = []
    tools.event_sink = lambda event, data: pushes.append((event, data))
    return pushes


def _pushes_for(pushes, event):
    return [data for name, data in pushes if name == event]


# --- (a) clean compile streams its applied ops ------------------------------


def test_clean_compile_sink_push_carries_operations(tmp_path, monkeypatch):
    tools = _build_tools(tmp_path, monkeypatch)
    pushes = _attach_sink(tools)

    tools.compile_dsl_block('page Test\n  text "Plan"')

    compiled = _pushes_for(pushes, "dsl_compiled")
    assert len(compiled) == 1, "a clean compile records exactly one dsl_compiled"
    push = compiled[0]
    # Base five fields preserved verbatim.
    assert BASE_SINK_KEYS <= set(push)
    ops = push.get("operations")
    assert isinstance(ops, list) and ops, "clean compile streams a non-empty ops list"
    # The applied ops carry element-level sequencing (add_page then insert_node);
    # the same list logged to the proposal ledger, so Accept parity holds.
    kinds = [op.get("kind") for op in ops]
    assert kinds == ["add_page", "insert_node"]


# --- (b) a refused draft streams nothing to the canvas ----------------------


class _RaisingCore(FakeCoreClient):
    def compile_dsl_into_scene(self, scene, source, dsl_session=None, protected_node_ids=None):
        raise CoreError("dsl.parse_error", "unbalanced block")


def test_failed_compile_sink_push_has_no_operations(tmp_path, monkeypatch):
    monkeypatch.setattr("lumen_agent.tools.substrate.CoreClient", _RaisingCore)
    from lumen_agent.tools.substrate import LumenDesignTools

    tools = LumenDesignTools(runtime_config(tmp_path), "design a poster")
    pushes = _attach_sink(tools)

    tools.compile_dsl_block("page Broken\n  text")

    failed = _pushes_for(pushes, "dsl_compile_failed")
    assert len(failed) == 1, "a failed compile records dsl_compile_failed"
    push = failed[0]
    assert set(push) == BASE_SINK_KEYS, "a refused draft never streams operations"
    assert "operations" not in push


def test_rejected_duplicate_page_sink_push_has_no_operations(tmp_path, monkeypatch):
    # A repair block that re-declares an existing page is rejected (LUMA0200)
    # before ever reaching core — it must stream nothing to the canvas.
    seeded = {
        "meta": {"id": "doc", "title": "t"},
        "pages": {"hero_page": {"id": "hero_page", "children": []}},
        "nodes": {},
        "slots": {},
        "assets": {},
    }
    tools = _build_tools(tmp_path, monkeypatch, initial_scene=seeded)
    pushes = _attach_sink(tools)

    tools.compile_dsl_block("page hero_page\n  text \"again\"")

    rejected = _pushes_for(pushes, "dsl_compile_rejected")
    assert len(rejected) == 1
    push = rejected[0]
    assert set(push) == BASE_SINK_KEYS
    assert "operations" not in push


# --- (c) asset placement streams its applied op -----------------------------


def test_asset_placement_sink_push_carries_operations(tmp_path, monkeypatch):
    tools = _build_tools(tmp_path, monkeypatch, prompt="place a hero image")
    pushes = _attach_sink(tools)

    tools.place_asset_in_node("hero", "asset_img_abc", fit="cover", focal_x=0.5, focal_y=0.42)

    placed = _pushes_for(pushes, "asset_placed")
    assert len(placed) == 1
    push = placed[0]
    assert BASE_SINK_KEYS <= set(push)
    ops = push.get("operations")
    assert isinstance(ops, list) and len(ops) == 1
    op = ops[0]
    assert op["kind"] == "place_asset_in_node"
    assert op["node_id"] == "hero"
    assert op["asset_id"] == "asset_img_abc"
    assert op["placement"]["fit"] == "cover"


# --- (d) non-mutating events keep the lean five fields ----------------------


def test_non_mutating_event_sink_push_is_unchanged(tmp_path, monkeypatch):
    tools = _build_tools(tmp_path, monkeypatch)
    pushes = _attach_sink(tools)

    # A plain record with no sink_extra — the shape every checklist/usage event
    # rides on. It must stay exactly the five summary fields.
    tools.record("coordinator", "view_called", input_summary="preview", output_summary="ok")

    viewed = _pushes_for(pushes, "view_called")
    assert len(viewed) == 1
    assert set(viewed[0]) == BASE_SINK_KEYS
    assert "operations" not in viewed[0]
