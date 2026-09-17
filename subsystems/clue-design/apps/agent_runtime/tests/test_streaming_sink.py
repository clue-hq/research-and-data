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
    def compile_dsl_into_scene(self, scene, source, dsl_session=None, protected_node_ids=None, brand_kit=None, mode=None):
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


# --- (e) rung B: op-bearing frames carry their ledger position --------------
#
# The frontend de-duplicates streamed op batches against the version it last
# reloaded from a `design.checkpoint` frame (which carries `operations` = the
# COUNT of ledger ops committed so far). For that subtraction to be arithmetic
# rather than guesswork, every op-bearing sink frame states where its batch ends
# in the SAME ledger: `operations_total` is the length of `operations_ledger`
# AFTER this batch was appended. A checkpoint frame with `operations == N` and an
# op frame with `operations_total == N` therefore describe the same point.


class _ThreeOpCore(FakeCoreClient):
    """A clean compile that applies three operations (the base fake applies two)."""

    def compile_dsl_into_scene(self, scene, source, dsl_session=None, protected_node_ids=None, brand_kit=None, mode=None):
        response = super().compile_dsl_into_scene(
            scene, source, dsl_session=dsl_session, protected_node_ids=protected_node_ids
        )
        response["applied_operations"] = 3
        response["dsl"]["compile_output"]["operations"] = [
            {"kind": "add_page"},
            {"kind": "insert_node"},
            {"kind": "set_text"},
        ]
        return response


def _seed_ledger(tools, count):
    """Stand in for `count` operations already committed earlier in the run,
    in the exact entry shape `_log_scene_operations` writes."""
    tools.operations_ledger.extend(
        {"iteration": 0, "source": "seed", "operation": {"kind": "seed", "n": index}}
        for index in range(count)
    )


def test_clean_compile_sink_push_carries_ledger_position(tmp_path, monkeypatch):
    monkeypatch.setattr("lumen_agent.tools.substrate.CoreClient", _ThreeOpCore)
    from lumen_agent.tools.substrate import LumenDesignTools

    tools = LumenDesignTools(runtime_config(tmp_path), "design a launch poster")
    _seed_ledger(tools, 8)
    pushes = _attach_sink(tools)

    tools.compile_dsl_block('page Test\n  text "Plan"')

    push = _pushes_for(pushes, "dsl_compiled")[0]
    # 8 unstreamed seeds ride this frame ahead of the compile's 3 (Plan 2 Task 5).
    assert len(push["operations"]) == 11
    # 8 already on the ledger + this batch's 3 = the batch ends at position 11.
    assert push["operations_total"] == 11
    assert push["operations_total"] == len(tools.operations_ledger)


def test_failed_compile_sink_push_has_no_ledger_position(tmp_path, monkeypatch):
    monkeypatch.setattr("lumen_agent.tools.substrate.CoreClient", _RaisingCore)
    from lumen_agent.tools.substrate import LumenDesignTools

    tools = LumenDesignTools(runtime_config(tmp_path), "design a poster")
    _seed_ledger(tools, 8)
    pushes = _attach_sink(tools)

    tools.compile_dsl_block("page Broken\n  text")

    push = _pushes_for(pushes, "dsl_compile_failed")[0]
    # A refused draft streams neither half of the pair: no ops, and no position
    # for ops that were never committed.
    assert set(push) == BASE_SINK_KEYS
    assert "operations_total" not in push


def test_rejected_duplicate_page_sink_push_has_no_ledger_position(tmp_path, monkeypatch):
    seeded = {
        "meta": {"id": "doc", "title": "t"},
        "pages": {"hero_page": {"id": "hero_page", "children": []}},
        "nodes": {},
        "slots": {},
        "assets": {},
    }
    tools = _build_tools(tmp_path, monkeypatch, initial_scene=seeded)
    _seed_ledger(tools, 8)
    pushes = _attach_sink(tools)

    tools.compile_dsl_block("page hero_page\n  text \"again\"")

    push = _pushes_for(pushes, "dsl_compile_rejected")[0]
    assert set(push) == BASE_SINK_KEYS
    assert "operations_total" not in push


def test_asset_placement_sink_push_carries_ledger_position(tmp_path, monkeypatch):
    tools = _build_tools(tmp_path, monkeypatch, prompt="place a hero image")
    _seed_ledger(tools, 4)
    pushes = _attach_sink(tools)

    tools.place_asset_in_node("hero", "asset_img_abc", fit="cover", focal_x=0.5, focal_y=0.42)

    push = _pushes_for(pushes, "asset_placed")[0]
    # 4 unstreamed seeds ride this frame ahead of the placement's 1 (Plan 2 Task 5).
    assert len(push["operations"]) == 5
    # 4 already on the ledger + this single placement op = position 5.
    assert push["operations_total"] == 5
    assert push["operations_total"] == len(tools.operations_ledger)


def test_failed_asset_placement_sink_push_has_no_ledger_position(tmp_path, monkeypatch):
    class _RefusingCore(FakeCoreClient):
        def apply_operations(self, scene, operations, scope=None):
            raise CoreError("op.asset_missing", "no such asset")

    monkeypatch.setattr("lumen_agent.tools.substrate.CoreClient", _RefusingCore)
    from lumen_agent.tools.substrate import LumenDesignTools

    tools = LumenDesignTools(runtime_config(tmp_path), "place a hero image")
    _seed_ledger(tools, 4)
    pushes = _attach_sink(tools)

    tools.place_asset_in_node("hero", "asset_img_abc", fit="cover", focal_x=0.5, focal_y=0.42)

    push = _pushes_for(pushes, "asset_placement_failed")[0]
    assert set(push) == BASE_SINK_KEYS
    assert "operations" not in push and "operations_total" not in push


# --- (d) Plan 2 Task 5: frames are contiguous with the ledger -------------------


def _upsert(asset_id):
    return {"kind": "upsert_asset", "asset": {"id": asset_id}}


def test_ops_ledgered_without_a_frame_ride_the_next_frame(tmp_path, monkeypatch):
    """The Apollo/Ramp shape: a compile auto-registers two kit assets (ledger 1–2, no frame)
    and then streams its own 3 ops ending at 5. The frame must BEGIN at 0 — the client's
    cursor — so it carries all five, the two registrations first."""
    monkeypatch.setattr("lumen_agent.tools.substrate.CoreClient", _ThreeOpCore)
    from lumen_agent.tools.substrate import LumenDesignTools

    tools = LumenDesignTools(runtime_config(tmp_path), "design a launch poster")
    pushes = _attach_sink(tools)
    tools._log_scene_operations("brand_asset", [_upsert("asset_a"), _upsert("asset_b")])

    tools.compile_dsl_block('page Test\n  text "Plan"')

    push = _pushes_for(pushes, "dsl_compiled")[0]
    assert push["operations_total"] == 5
    assert [op["kind"] for op in push["operations"]] == [
        "upsert_asset", "upsert_asset", "add_page", "insert_node", "set_text",
    ]
    assert push["operations_total"] - len(push["operations"]) == 0


def test_a_second_frame_carries_only_its_own_ops(tmp_path, monkeypatch):
    monkeypatch.setattr("lumen_agent.tools.substrate.CoreClient", _ThreeOpCore)
    from lumen_agent.tools.substrate import LumenDesignTools

    tools = LumenDesignTools(runtime_config(tmp_path), "design a launch poster")
    pushes = _attach_sink(tools)
    tools._log_scene_operations("brand_asset", [_upsert("asset_a")])
    tools.compile_dsl_block('page Test\n  text "Plan"')
    tools.compile_dsl_block('page Test2\n  text "Plan"')

    first, second = _pushes_for(pushes, "dsl_compiled")
    assert first["operations_total"] == 4 and len(first["operations"]) == 4
    assert second["operations_total"] == 7 and len(second["operations"]) == 3
    # Contiguous: the second frame begins exactly where the first ended.
    assert second["operations_total"] - len(second["operations"]) == first["operations_total"]


def test_a_checkpoint_advances_the_streamed_marker(tmp_path, monkeypatch):
    """Ops committed by a checkpoint are durable and the client reloads them (rung A), so a
    frame after the checkpoint must not re-carry them — it begins at the checkpoint's position."""
    monkeypatch.setattr("lumen_agent.tools.substrate.CoreClient", _ThreeOpCore)
    from lumen_agent.tools.substrate import LumenDesignTools

    tools = LumenDesignTools(runtime_config(tmp_path), "design a launch poster")
    tools.scene_checkpoint = lambda operations, meta: None
    pushes = _attach_sink(tools)
    tools._log_scene_operations("brand_asset", [_upsert("asset_a"), _upsert("asset_b")])
    tools.checkpoint_scene("round_1")

    tools.compile_dsl_block('page Test\n  text "Plan"')

    push = _pushes_for(pushes, "dsl_compiled")[0]
    assert push["operations_total"] == 5
    assert len(push["operations"]) == 3
    assert push["operations_total"] - len(push["operations"]) == 2
