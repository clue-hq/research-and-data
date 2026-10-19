"""Deepagent v0 harness (Phase A) — offline unit tests, no LLM calls.

Covers the IMPLEMENTATION-BRIEF §8 test list: workspace scaffolding, the `view`
tool's content structure, the D5 tool-surface contract, the D6 prompt contract,
the constitution state schema, and the runner's honest-failure guarantees.

Only `create_deep_agent` and `init_model` are stubbed, so no real model is built
and no network call fires. Filesystem and state classes stay real: replacing a
filesystem module would permanently change a lazily imported backend base class.
"""

from __future__ import annotations

from langchain_core.language_models.fake_chat_models import GenericFakeChatModel

import base64
import hashlib
import json
import threading
import types
from dataclasses import replace
from pathlib import Path

import pytest
from langchain.agents.structured_output import ToolStrategy

from lumen_agent import harness as harness_mod
from lumen_agent.models.schemas import VisualCritique
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
from lumen_agent.prompts import BATCHING_RULE, SHARED_SURFACE_CONTRACT
from lumen_agent.tools.substrate import LumenDesignTools

from agent_fixtures import FakeCoreClient, prepare_acceptance_evidence, runtime_config


# --- deepagents stub --------------------------------------------------------


def _install_deepagents_stub(monkeypatch, capture: dict):
    def fake_create_deep_agent(**kwargs):
        capture["kwargs"] = kwargs
        return types.SimpleNamespace(invoke=lambda *a, **k: {"messages": []}, kwargs=kwargs)

    monkeypatch.setattr("deepagents.create_deep_agent", fake_create_deep_agent)
    monkeypatch.setattr("lumen_agent.tools.substrate.CoreClient", FakeCoreClient)
    monkeypatch.setattr(
        "lumen_agent.harness.init_model",
        lambda *a, **k: GenericFakeChatModel(messages=iter(())),
        raising=False,
    )
    # init_model is imported lazily inside create_design_deepagent from providers,
    # so also patch it there.
    monkeypatch.setattr(
        "lumen_agent.llm.init_model",
        lambda *a, **k: GenericFakeChatModel(messages=iter(())),
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


def _give_page(tools):
    """Editor Quality Plan 2 (item C): generate_image refuses on a pageless scene
    BEFORE it calls the model, so an imagery test needs the page the real author
    would have compiled first. FakeCoreClient.compile_dsl_into_scene plants
    `page_test`; any source will do."""
    tools.compile_dsl_block("page page_test size(1080,1080,px)")
    assert tools.scene["pages"], "fixture must have planted a page"


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


def test_prompts_receive_virtual_workspace_path(tmp_path, monkeypatch):
    """W-isolation (D4): the harness hands the subagents/orchestrator the VIRTUAL
    workspace string `/run_<id>/workspace`, never a host-absolute path."""
    capture: dict = {}
    _install_deepagents_stub(monkeypatch, capture)

    _agent, tools = create_design_deepagent("Make a poster", runtime_config(tmp_path))
    kwargs = capture["kwargs"]

    virtual_ws = f"/{tools.run_id}/workspace"
    assert virtual_ws in kwargs["system_prompt"]
    # No host-absolute workspace path leaks into the prompt.
    assert str(tools.trace_dir) not in kwargs["system_prompt"]
    author = next(s for s in kwargs["subagents"] if s["name"] == "lumen-dsl-author")
    assert virtual_ws in author["system_prompt"]


def test_a_session_turn_prompts_the_persistent_session_workspace(tmp_path, monkeypatch):
    """Design session continuity (2026-09-18): on a continued thread the prompt
    must name `/sessions/<session_id>/workspace` — the folder that SURVIVES the
    turn — and never a per-turn `/run_<id>/` path that will not exist next turn."""
    capture: dict = {}
    _install_deepagents_stub(monkeypatch, capture)

    config = replace(runtime_config(tmp_path), session_id="dsess_prompt")
    _agent, tools = create_design_deepagent("Make a poster", config)
    kwargs = capture["kwargs"]
    author = next(s for s in kwargs["subagents"] if s["name"] == "lumen-dsl-author")

    assert tools.workspace_scope_id == "sessions/dsess_prompt"
    for system_prompt in (kwargs["system_prompt"], author["system_prompt"]):
        assert "/sessions/dsess_prompt/workspace" in system_prompt
        assert f"/{tools.run_id}/workspace" not in system_prompt


def test_run_artifacts_land_under_isolated_workspace(tmp_path, monkeypatch):
    """W-isolation (D9 acceptance #2): every produced artifact lands under
    `<workspace_root>/run_<id>/`, the skills + knowledge trees are materialized,
    and nothing is written outside the workspace root."""
    capture: dict = {}
    _install_deepagents_stub(monkeypatch, capture)  # invoke returns cleanly, no final.json

    config = runtime_config(tmp_path)
    payload, tools = run_deepagent_turn("Design a card", config)

    ws_root = config.workspace_root
    # The run root is <workspace_root>/run_<id>.
    assert tools.trace_dir.parent == ws_root
    assert tools.trace_dir.name == tools.run_id
    assert tools.run_id.startswith("run_")

    # Honest-failure artifacts all under the run root.
    for name in ("final.json", "trace.jsonl", "input.json"):
        assert (tools.trace_dir / name).exists()
    assert (tools.trace_dir / "workspace" / "brief.md").exists()

    # The materializer synced the read-only trees into the workspace.
    assert (ws_root / ".deepagent" / "skills").is_dir()
    assert (ws_root / "knowledge_docs").is_dir()
    assert (ws_root / ".deepagent" / ".sync-stamp").exists()

    # Nothing was written OUTSIDE the workspace root: the only top-level entries
    # are the run dir and the materialized trees (+ any asset-store default).
    allowed = {tools.run_id, ".deepagent", ".materialize.lock", "knowledge_docs", "asset-store"}
    assert {child.name for child in ws_root.iterdir()} <= allowed


# --- 2. view tool structure -------------------------------------------------


def _solid_png(size: int = 640) -> bytes:
    # A realistic >=512px preview: at or above the vision-provider minimum it
    # passes through view() unchanged, so exact-byte round-trip still holds.
    import io as _io

    from PIL import Image

    buffer = _io.BytesIO()
    Image.new("RGB", (size, size), (12, 34, 56)).save(buffer, format="PNG")
    return buffer.getvalue()


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
        "artifacts": [{"format": "png", "path": str(png_path), "width": 640, "height": 640}],
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


def _clue_storage_kit_asset(
    workspace_id: str, thumb_bytes: bytes, source_bytes: bytes
) -> dict:
    """A brand-kit asset record shaped exactly as D4 leaves one: both byte objects
    live in platform storage and their `media.location.opaque_ref` is a REAL
    `clue-storage` key, minted by the production helpers rather than typed out here."""
    from clue_design.storage import design_location, design_storage_key

    source_digest = hashlib.sha256(source_bytes).hexdigest()
    thumb_digest = hashlib.sha256(thumb_bytes).hexdigest()
    return {
        "id": "asset_kit_logo",
        "label": "Scribe wordmark",
        "kind": "logo",
        "status": "ready",
        "media": {
            "mime_type": "image/png",
            "digest": {"algorithm": "sha256", "value": source_digest},
            "location": design_location(design_storage_key(workspace_id, source_digest)),
            "thumbnail": {
                "location": design_location(
                    design_storage_key(workspace_id, thumb_digest)
                ),
                "mime_type": "image/png",
                "pixel_width": 640,
                "pixel_height": 640,
            },
        },
    }


def test_view_asset_delivers_pixels_for_a_clue_storage_backed_record(
    tmp_path, monkeypatch
):
    """P0.1 regression (fast-loop v1 spec §4): `view("asset:<id>")` must return real
    pixels for a DURABLY-stored brand-kit asset.

    The bug this pins: `_asset_preview_path` appended the record's `opaque_ref`
    verbatim onto `effective_asset_store_root`, which the API points at the
    per-WORKSPACE engine cache. A D4 ref (`ws_X/design/<digest>`) therefore resolved
    to `<cache>/ws_X/ws_X/design/<digest>` — a doubled workspace segment that never
    exists — so every kit asset answered `asset_missing_file` and the author designed
    blind (2026-08-24 Stuttgart forensics). Resolution is by DIGEST now, so the
    genuine ref shape lands on the bytes the API's read-through materialized.
    """
    from lumen_api.asset_custody import write_cache_blob

    workspace_id = "ws_p01regression"
    # The runtime's asset-store root IS the per-workspace engine cache — exactly what
    # `api_engine_cache_root(workspace_id)` builds and `run_agent_turn_preview` injects.
    cache_dir = tmp_path / "engine-cache" / workspace_id
    thumb_bytes = _solid_png()
    source_bytes = _solid_png(size=1024)
    record = _clue_storage_kit_asset(workspace_id, thumb_bytes, source_bytes)
    # The API's read-through (`ensure_materialized`) lands durable bytes here by
    # digest; `write_cache_blob` is the very function it uses, so the on-disk state
    # this test starts from is production's, not an invention.
    write_cache_blob(cache_dir, hashlib.sha256(thumb_bytes).hexdigest(), thumb_bytes)
    write_cache_blob(cache_dir, hashlib.sha256(source_bytes).hexdigest(), source_bytes)

    config = replace(
        runtime_config(tmp_path),
        asset_store_root=cache_dir,
        brand_kit_assets={record["id"]: {"record": record, "title": "Scribe wordmark"}},
    )
    monkeypatch.setattr("lumen_agent.tools.substrate.CoreClient", FakeCoreClient)
    tools = _tools_only(config)

    # RED CASE, spelled out: the path the old resolver built for this very record.
    doubled = cache_dir / record["media"]["thumbnail"]["location"]["opaque_ref"]
    assert not doubled.exists(), "the pre-fix concatenation must still be a dead path"

    view = harness_mod.make_view_tool(tools)
    msg = view.invoke(
        {
            "name": "view",
            "args": {"target": f"asset:{record['id']}"},
            "id": "c4",
            "type": "tool_call",
        }
    )
    content = msg.content
    assert isinstance(content, list), content
    image_blocks = [b for b in content if b["type"] == "image"]
    assert len(image_blocks) == 1, content
    assert base64.b64decode(image_blocks[0]["data"]) == thumb_bytes

    # And the placement/contact-sheet surfaces that share the resolver see it too.
    sheet, omitted = tools._brand_asset_contact_sheet()
    assert omitted == 0
    assert [entry["asset_id"] for entry in sheet] == [record["id"]]


def test_view_asset_still_resolves_a_legacy_engine_cache_record(tmp_path, monkeypatch):
    """The pre-D4 `sha256/<ab>/<digest>` ref shape must keep working — asset records
    are durable JSON on scenes and registry rows that nothing rewrites in place, so
    both shapes are live at once and the fix may not trade one for the other."""
    from lumen_api.asset_custody import write_cache_blob

    cache_dir = tmp_path / "engine-cache" / "ws_legacy"
    thumb_bytes = _solid_png(size=576)
    digest = hashlib.sha256(thumb_bytes).hexdigest()
    write_cache_blob(cache_dir, digest, thumb_bytes)
    record = {
        "id": "asset_legacy_logo",
        "label": "Legacy mark",
        "kind": "logo",
        "status": "ready",
        "media": {
            "mime_type": "image/png",
            "digest": {"algorithm": "sha256", "value": digest},
            "thumbnail": {
                "location": {
                    "provider": "local-store",
                    "opaque_ref": f"sha256/{digest[:2]}/{digest}",
                    "url": None,
                },
                "mime_type": "image/png",
                "pixel_width": 576,
                "pixel_height": 576,
            },
        },
    }

    config = replace(
        runtime_config(tmp_path),
        asset_store_root=cache_dir,
        brand_kit_assets={record["id"]: {"record": record}},
    )
    monkeypatch.setattr("lumen_agent.tools.substrate.CoreClient", FakeCoreClient)
    tools = _tools_only(config)

    view = harness_mod.make_view_tool(tools)
    msg = view.invoke(
        {
            "name": "view",
            "args": {"target": f"asset:{record['id']}"},
            "id": "c5",
            "type": "tool_call",
        }
    )
    image_blocks = [b for b in msg.content if b["type"] == "image"]
    assert len(image_blocks) == 1, msg.content
    assert base64.b64decode(image_blocks[0]["data"]) == thumb_bytes


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
        # Brief clarification (opening-move only): present on a default turn —
        # withheld under auto_defaults or after a prior clarification round (see
        # test_clarification.py for the two absence cases).
        "request_clarification",
        "finalize_run",
    }

    subagents = {sa["name"]: sa for sa in kwargs["subagents"]}
    author_tools = {_tool_name(t) for t in subagents["lumen-dsl-author"]["tools"]}
    assert author_tools == {
        "view",
        "inspect",
        "compile_dsl_block",
        "asset",
        # Another company's real logo, fetched from their own website. The
        # author places it; it never draws one.
        "fetch_logo",
        "validate_binding_set",
        "preflight_design",
    }

    reviewer_tools = {_tool_name(t) for t in subagents["lumen-visual-reviewer"]["tools"]}
    assert reviewer_tools == {"view", "inspect"}

    assert kwargs["name"] == "lumen-design-deepagent"

    # D11: the reviewer's structured output is wrapped in ToolStrategy (TOOL
    # strategy), not handed raw to the provider/native path. This is the fix for
    # P1r7 dying twice on `StructuredOutputValidationError ... Native structured
    # output expected valid JSON for VisualCritique` (grok-4.5 via OpenRouter).
    reviewer_format = subagents["lumen-visual-reviewer"].get("response_format")
    assert isinstance(reviewer_format, ToolStrategy)
    # The tool strategy carries the VisualCritique schema...
    assert reviewer_format.schema is VisualCritique
    # ...and keeps validation-retry on (default handle_errors=True), so a
    # malformed tool call gets re-asked rather than crashing the run.
    assert reviewer_format.handle_errors is True

    # The orchestrator and author remain format-free — only the reviewer
    # emits structured output.
    assert "response_format" not in kwargs
    assert "response_format" not in subagents["lumen-dsl-author"]


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


def test_author_prompt_teaches_detach_to_freehand_for_layering_above_pins():
    # D12: the author must discover `detach_to_freehand(<id>)` as the way to
    # paint managed content above a pinned human node (the P1r6 class).
    author = build_author_prompt("/tmp/ws")
    assert "detach_to_freehand(<its_id>)" in author
    assert "paint ABOVE a pinned human node" in author


def test_author_prompt_teaches_physical_page_units_first_class():
    # genad2 (agent-authored pages): the scene is born with ZERO pages, so the
    # author owns page setup — the always-on prompt must teach the physical/print
    # idiom (mm / in, print presets) as first-class alongside the digital px one,
    # and must warn that an explicit size(...)/preset(...) is ALWAYS required
    # because a bare `page <id>` silently defaults to A4 portrait (dsl.rs
    # lower_page's fallback_preset).
    author = build_author_prompt("/tmp/ws-pages")
    # The OWNERSHIP clause — the one sentence that tells the author the platform
    # mints nothing (genad2 ruling 1). It carries its own bullet rather than
    # riding the units bullet, so it cannot be lost to an edit about units.
    assert "- YOU author every page." in author
    assert "A scene can arrive with no pages at all" in author
    # Digital idiom (unchanged) beside the physical/print one.
    assert "size(width,height,px)" in author
    assert "size(210,297,mm)" in author
    assert "size(8.5,11,in)" in author
    # The print-preset list must read OPEN — three of the engine's five presets
    # are named, so a closed-sounding list would teach the agent that the other
    # two do not exist.
    assert "for example, `preset(a4,portrait)`" in author
    assert "preset(us_letter,portrait)" in author
    # A bare page line is never acceptable.
    assert "ALWAYS give an explicit `size(...)` or `preset(...)`" in author
    assert "defaults to A4 portrait" in author
    # No dimensions named in the ask → choose canonical ones and say so.
    assert "STATE them in your report" in author


def test_all_prompts_have_resource_map_and_workspace_path():
    ws = "/tmp/unique-workspace-xyz"
    for prompt in (
        build_orchestrator_prompt(ws),
        build_author_prompt(ws),
        build_reviewer_prompt(ws),
    ):
        assert "RESOURCES YOU HAVE" in prompt
        assert ws in prompt


def test_orchestrator_teaches_unchanged_scene_reuse():
    """L4b (deepagent-latency): when render_preview reports the scene is
    byte-identical to the last render, the orchestrator acts on the existing
    critique instead of re-delegating a full review — the ONLY exception being a
    reviewer re-run to fill a required field (e.g. reference_fidelity after a
    REFUSED finalize). Pinned so the additive teaching cannot silently drop."""
    orch = build_orchestrator_prompt("/tmp/ws-unchanged")
    assert "UNCHANGED-SCENE GUARD" in orch
    assert "do NOT re-delegate a full" in orch
    assert "REFUSED finalize_run demands" in orch
    # It must NOT contradict the batching rule (task stays never-batch).
    assert "never one at a time" in orch


def test_all_prompts_carry_batching_rule_and_never_batch_list():
    """L2 (deepagent-latency): every role learns to batch independent read-only
    lookups AND the never-batch exclusion list, so writes / render / preflight /
    task stay one-at-a-time. Pinned across all three roles."""
    ws = "/tmp/ws-batch"
    prompts = {
        "orchestrator": build_orchestrator_prompt(ws),
        "author": build_author_prompt(ws),
        "reviewer": build_reviewer_prompt(ws),
    }
    for role, prompt in prompts.items():
        # The shared rule body is present verbatim, exactly once per role.
        assert prompt.count(BATCHING_RULE) == 1, role
        # The crisp rule teaches batching independent read-only lookups.
        assert "BATCH READ-ONLY LOOKUPS" in prompt, role
        assert "in ONE response" in prompt, role
        assert "never one at a time" in prompt, role
        # The never-batch exclusion list — every tool that must stay alone.
        for excluded in (
            "task",
            "compile_dsl_block",
            "render_preview",
            "preflight_design",
            "asset",
            "any write",
        ):
            assert excluded in prompt, f"{role} missing never-batch {excluded!r}"


def test_orchestrator_verify_step_keeps_preflight_and_render_sequential():
    """L2: at the orchestrator verify step ONLY the reads batch — preflight_design
    and render_preview must be taught as explicitly NOT batchable."""
    orch = build_orchestrator_prompt("/tmp/ws-verify")
    assert "preflight_design and render_preview are NOT batchable" in orch


def test_record_is_thread_safe_under_concurrent_batched_reads(tmp_path, monkeypatch):
    """L2 thread-safety: batched read-only tool calls run on langgraph's ToolNode
    thread pool, so `record` is now invoked from concurrent threads. The lock must
    keep trace.jsonl a valid, complete JSONL file (no interleaved/torn lines) and
    the event_sink must receive every event exactly once."""
    # Seed a scene so construction never touches the real core helper.
    tools = _tools_only(runtime_config(tmp_path), initial_scene=seeded_scene())
    n = 200
    sink_events: list = []
    sink_lock = threading.Lock()

    def sink(event, payload):
        # Append under the record lock in production; here we guard our own list
        # so the test's assertion on the sink is itself race-free.
        with sink_lock:
            sink_events.append((event, payload))

    tools.event_sink = sink

    trace_path = tools.trace_dir / "trace.jsonl"
    # Construction may already have recorded events (e.g. run_started); count them
    # so the assertion targets only the N events this test drives concurrently.
    baseline = len(
        [ln for ln in trace_path.read_text(encoding="utf-8").splitlines() if ln.strip()]
    ) if trace_path.exists() else 0

    barrier = threading.Barrier(n)

    def worker(i: int) -> None:
        barrier.wait()  # maximize contention: all threads hit record together
        tools.record(actor="tester", event=f"evt_{i}", input_summary=str(i))

    threads = [threading.Thread(target=worker, args=(i,)) for i in range(n)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    raw = trace_path.read_text(encoding="utf-8")
    lines = [ln for ln in raw.splitlines() if ln.strip()]
    assert len(lines) == baseline + n
    parsed = [json.loads(ln) for ln in lines]  # every line is intact JSON
    events = {p["event"] for p in parsed}
    assert {f"evt_{i}" for i in range(n)}.issubset(events)
    # The best-effort sink saw every event exactly once, no drops from a torn push.
    assert {e for e, _ in sink_events} == {f"evt_{i}" for i in range(n)}


# --- 5. state schema --------------------------------------------------------


def test_state_schema_declares_exactly_seven_constitution_fields():
    # A TypedDict subclass merges parent annotations into __annotations__; the
    # constitution is exactly the fields LumenTurnState adds over its base. RC
    # added `reference_asset_ids` (the always-present-but-possibly-empty ids).
    from lumen_agent.models import state as state_mod
    base_fields = set(getattr(state_mod._DeepAgentStateBase, "__annotations__", {}).keys())
    added_fields = set(LumenTurnState.__annotations__.keys()) - base_fields
    assert added_fields == set(CONSTITUTION_FIELDS)
    assert len(CONSTITUTION_FIELDS) == 7
    assert "reference_asset_ids" in CONSTITUTION_FIELDS


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
    # RC: no references on this turn → empty list (always present, like chips).
    assert state["reference_asset_ids"] == []


# --- 6. runner honesty ------------------------------------------------------


def test_runner_honest_failure_on_invoke_exception(tmp_path, monkeypatch):
    capture: dict = {}

    def fake_create_deep_agent(**kwargs):
        capture["kwargs"] = kwargs

        def _boom(*a, **k):
            raise RuntimeError("model exploded mid-turn")

        return types.SimpleNamespace(invoke=_boom, kwargs=kwargs)

    monkeypatch.setattr("deepagents.create_deep_agent", fake_create_deep_agent)
    monkeypatch.setattr("lumen_agent.tools.substrate.CoreClient", FakeCoreClient)
    monkeypatch.setattr("lumen_agent.llm.init_model", lambda *a, **k: GenericFakeChatModel(messages=iter(())))

    payload, tools = run_deepagent_turn("Design a card", runtime_config(tmp_path))

    assert payload["status"] == "failed"
    assert payload["stop_reason"] == "orchestrator_did_not_finalize"
    final_path = tools.trace_dir / "final.json"
    assert final_path.exists()
    # Exception text recorded verbatim in the trace.
    trace = (tools.trace_dir / "trace.jsonl").read_text(encoding="utf-8")
    assert "model exploded mid-turn" in trace
    assert "RuntimeError" in trace


def test_runner_honest_failure_on_api_timeout_error(tmp_path, monkeypatch):
    """L3/D3: an exhausted-retry straggler surfaces as openai.APITimeoutError out of
    agent.invoke (nothing in langchain/deepagents catches it). The runner's broad
    catch must route it into the EXISTING honest failed-finalize path — a failed
    final.json + a trace event recording the exception CLASS + message — never a
    silent thread crash and never a fabricated success. This pins the specific
    timeout-exception path the watchdog introduces."""
    import httpx
    import openai

    capture: dict = {}

    def fake_create_deep_agent(**kwargs):
        capture["kwargs"] = kwargs

        def _timeout(*a, **k):
            # Exactly what the OpenAI SDK propagates after max_retries is exhausted.
            raise openai.APITimeoutError(request=httpx.Request("POST", "https://openrouter.ai/api/v1/chat/completions"))

        return types.SimpleNamespace(invoke=_timeout, kwargs=kwargs)

    monkeypatch.setattr("deepagents.create_deep_agent", fake_create_deep_agent)
    monkeypatch.setattr("lumen_agent.tools.substrate.CoreClient", FakeCoreClient)
    monkeypatch.setattr("lumen_agent.llm.init_model", lambda *a, **k: GenericFakeChatModel(messages=iter(())))

    # Must NOT raise: the runner returns an honest failed payload instead.
    payload, tools = run_deepagent_turn("Design a card", runtime_config(tmp_path))

    assert payload["status"] == "failed"
    assert payload["stop_reason"] == "orchestrator_did_not_finalize"
    final_path = tools.trace_dir / "final.json"
    assert final_path.exists()
    # The exception CLASS name + message are recorded verbatim in the trace.
    trace = (tools.trace_dir / "trace.jsonl").read_text(encoding="utf-8")
    assert "APITimeoutError" in trace
    assert "deepagent_turn_exception" in trace
    # The class + message also ride into the finalize detail (summary), so the
    # API worker sees a structured failure, not an opaque crash.
    assert "APITimeoutError" in payload["summary"]


def test_runner_honest_failure_when_agent_never_finalizes(tmp_path, monkeypatch):
    capture: dict = {}
    _install_deepagents_stub(monkeypatch, capture)  # invoke returns cleanly, no final.json

    payload, tools = run_deepagent_turn("Design a card", runtime_config(tmp_path))

    assert payload["status"] == "failed"
    assert payload["stop_reason"] == "orchestrator_did_not_finalize"
    assert (tools.trace_dir / "final.json").exists()
    assert payload["summary"] == "agent ended without finalize"


# --- 7. RC: reference-conditioned design ------------------------------------

import hashlib
from dataclasses import replace as _dc_replace

from lumen_agent.models.schemas import ReferenceFidelity, VisualIssue
from lumen_agent.prompts import (
    build_orchestrator_prompt as _orch,
    build_author_prompt as _auth,
    build_reviewer_prompt as _rev,
)


def _store_reference_png(config, png: bytes) -> str:
    """Write `png` into the shared content-addressed store and return its digest,
    exactly where view() resolves reference bytes (sha256/<2>/<digest>)."""
    digest = hashlib.sha256(png).hexdigest()
    folder = Path(config.effective_asset_store_root) / "sha256" / digest[:2]
    folder.mkdir(parents=True, exist_ok=True)
    (folder / digest).write_bytes(png)
    return digest


def _reference_config(tmp_path, specs):
    """Build a config whose reference_assets manifest mirrors the API's by-value
    shape. `specs` = list of dicts: {asset_id, png, order, title?, description?,
    colors?, label?, store?(bool, default True)}."""
    base = runtime_config(tmp_path)
    manifest = {}
    for spec in specs:
        png = spec["png"]
        digest = _store_reference_png(base, png) if spec.get("store", True) else "0" * 64
        manifest[spec["asset_id"]] = {
            "record": {"id": spec["asset_id"], "label": spec.get("label", spec["asset_id"])},
            "preview_digest": digest,
            "mime_type": "image/png",
            "width": 640,
            "height": 640,
            "dominant_colors": spec.get("colors", ["#112233", "#445566"]),
            "title": spec.get("title"),
            "description": spec.get("description"),
            "order": spec["order"],
        }
    return _dc_replace(base, reference_assets=manifest)


def _view(tools, target):
    view = harness_mod.make_view_tool(tools)
    return view.invoke({"name": "view", "args": {"target": target}, "id": "r", "type": "tool_call"}).content


# 7f. finalize_run reference-fidelity guard (adversarial-gate F1) -------------


def _finalize(tools, status="accepted", critique="{}"):
    return tools.finalize_run(
        status=status,
        stop_reason="test",
        summary="s",
        critique_json=critique,
    )


def test_finalize_refuses_accepted_reference_turn_without_fidelity(tmp_path, monkeypatch):
    """RC F1 (the deterministic anti-rubber-stamp): a reference turn can NEVER
    finalize as accepted when the critique omits reference_fidelity — the
    omission IS the moda failure (a review that never checked fidelity)."""
    monkeypatch.setattr("lumen_agent.tools.substrate.CoreClient", FakeCoreClient)
    tools = _tools_only(
        _reference_config(tmp_path, [{"asset_id": "asset_r1", "png": _solid_png(), "order": 0}])
    )
    critique = prepare_acceptance_evidence(tools)
    result = _finalize(tools, critique=json.dumps(critique))
    assert result.startswith("REFUSED")
    assert "reference_fidelity" in result
    assert not (tools.trace_dir / "final.json").exists()


def test_finalize_refuses_accepted_reference_turn_with_low_fidelity(tmp_path, monkeypatch):
    monkeypatch.setattr("lumen_agent.tools.substrate.CoreClient", FakeCoreClient)
    tools = _tools_only(
        _reference_config(tmp_path, [{"asset_id": "asset_r1", "png": _solid_png(), "order": 0}])
    )
    critique = prepare_acceptance_evidence(tools, {
        "accepted": True, "summary": "Only the palette carried over.", "issues": [],
        "reference_fidelity": {
            "score": 1, "reasons": "ignored", "regressed_to_house_style": True,
        },
    })
    result = _finalize(tools, critique=json.dumps(critique))
    assert result.startswith("REFUSED")
    assert "reference_fidelity" in result
    assert not (tools.trace_dir / "final.json").exists()


def test_finalize_accepts_reference_turn_with_explicit_fidelity(tmp_path, monkeypatch):
    monkeypatch.setattr("lumen_agent.tools.substrate.CoreClient", FakeCoreClient)
    tools = _tools_only(
        _reference_config(tmp_path, [{"asset_id": "asset_r1", "png": _solid_png(), "order": 0}])
    )
    critique = prepare_acceptance_evidence(tools, {
        "accepted": True, "summary": "The current render adopts the reference qualities.",
        "issues": [], "reference_fidelity": {
            "score": 3, "reasons": "adopts the qualities", "regressed_to_house_style": False,
        },
    })
    result = _finalize(tools, critique=json.dumps(critique))
    assert not result.startswith("REFUSED")
    assert json.loads(result)["status"] == "accepted"
    assert (tools.trace_dir / "final.json").exists()


def test_finalize_without_references_never_requires_fidelity(tmp_path, monkeypatch):
    """A fully reviewed plain turn requires no reference-fidelity judgment."""
    monkeypatch.setattr("lumen_agent.tools.substrate.CoreClient", FakeCoreClient)
    tools = _tools_only(runtime_config(tmp_path))
    critique = prepare_acceptance_evidence(tools)
    result = _finalize(tools, critique=json.dumps(critique))
    assert not result.startswith("REFUSED")
    assert json.loads(result)["status"] == "accepted"
    assert json.loads(result)["critique"] == critique
    assert (tools.trace_dir / "final.json").exists()


# 7f-bis. W1.5 — the gate reads a judgment the author wrote as prose ----------
#
# RED (Cursor pilot): the author judged fidelity 2/3 into `acceptance_notes`
# prose while the typed field stayed null, so this gate refused a finalize the
# author had actually earned. The gate now normalizes before it reads.

_PROSE_ONLY_CRITIQUE = json.dumps(
    {
        "accepted": True,
        "summary": "Dark flat field, centered lockup, one large light headline.",
        "acceptance_notes": [
            "safe-margins: 2 — pad(96) all sides",
            "reference_fidelity: 2 — dark flat field, centered lockup, generous air; "
            "held back by the plate and the Inter fallback",
        ],
    }
)


def test_finalize_accepts_when_the_fidelity_judgment_was_written_as_prose(tmp_path, monkeypatch):
    """W1.5 GREEN: the prose score is promoted, so the gate can read it."""
    monkeypatch.setattr("lumen_agent.tools.substrate.CoreClient", FakeCoreClient)
    tools = _tools_only(
        _reference_config(tmp_path, [{"asset_id": "asset_r1", "png": _solid_png(), "order": 0}])
    )
    prepare_acceptance_evidence(tools, json.loads(_PROSE_ONLY_CRITIQUE))
    result = _finalize(tools, critique=_PROSE_ONLY_CRITIQUE)
    assert not result.startswith("REFUSED")

    final = json.loads((tools.trace_dir / "final.json").read_text())
    fidelity = final["critique"]["reference_fidelity"]
    assert fidelity["score"] == 2
    assert "dark flat field" in fidelity["reasons"]


def test_finalize_still_refuses_when_the_prose_score_is_low(tmp_path, monkeypatch):
    """Promotion is not laundering: a prose 1 is still a refusal."""
    monkeypatch.setattr("lumen_agent.tools.substrate.CoreClient", FakeCoreClient)
    tools = _tools_only(
        _reference_config(tmp_path, [{"asset_id": "asset_r1", "png": _solid_png(), "order": 0}])
    )
    critique = prepare_acceptance_evidence(tools, {
        "accepted": True, "summary": "Palette alone matches.", "issues": [],
        "acceptance_notes": ["reference_fidelity: 1 — palette only"],
    })
    result = _finalize(tools, critique=json.dumps(critique))
    assert result.startswith("REFUSED")
    assert "reference_fidelity" in result
    assert not (tools.trace_dir / "final.json").exists()


def test_a_non_accepted_reference_finalize_still_records_the_typed_field(tmp_path, monkeypatch):
    """Unbound feedback retains typed metrics without becoming a current review."""
    monkeypatch.setattr("lumen_agent.tools.substrate.CoreClient", FakeCoreClient)
    tools = _tools_only(
        _reference_config(tmp_path, [{"asset_id": "asset_r1", "png": _solid_png(), "order": 0}])
    )
    result = _finalize(tools, status="blocked", critique='{"accepted": false, "summary": "s"}')
    assert not result.startswith("REFUSED")

    final = json.loads((tools.trace_dir / "final.json").read_text())
    assert final["critique"] == {}
    assert final["historical_critique"]["status"] == "unbound"
    assert final["historical_critique"]["critique"]["reference_fidelity"]["score"] == 0
    assert final["draft_verification"]["review"]["status"] == "missing"
    assert final["acceptance_receipt"] is None


def test_finalize_non_accepted_reference_turn_needs_no_fidelity(tmp_path, monkeypatch):
    """Honest non-acceptance stays available without a fidelity judgment."""
    monkeypatch.setattr("lumen_agent.tools.substrate.CoreClient", FakeCoreClient)
    tools = _tools_only(
        _reference_config(tmp_path, [{"asset_id": "asset_r1", "png": _solid_png(), "order": 0}])
    )
    result = _finalize(tools, status="failed", critique="{}")
    assert not result.startswith("REFUSED")
    assert (tools.trace_dir / "final.json").exists()


# 7a. view("reference:<n>") ---------------------------------------------------


def test_view_reference_by_1based_index(tmp_path, monkeypatch):
    monkeypatch.setattr("lumen_agent.tools.substrate.CoreClient", FakeCoreClient)
    first, second = _solid_png(544), _solid_png(576)
    config = _reference_config(
        tmp_path,
        [
            {"asset_id": "ref_b", "png": second, "order": 1},  # deliberately out of dict order
            {"asset_id": "ref_a", "png": first, "order": 0},
        ],
    )
    tools = _tools_only(config)

    content = _view(tools, "reference:1")
    images = [b for b in content if b["type"] == "image"]
    texts = [b for b in content if b["type"] == "text"]
    assert len(images) == 1 and len(texts) == 1
    # order=0 is reference:1 → the FIRST attachment, regardless of dict insertion.
    assert base64.b64decode(images[0]["data"]) == first
    assert "reference 1" in texts[0]["text"]

    # reference:2 is the order=1 attachment.
    assert base64.b64decode([b for b in _view(tools, "reference:2") if b["type"] == "image"][0]["data"]) == second


def test_view_reference_by_asset_id(tmp_path, monkeypatch):
    monkeypatch.setattr("lumen_agent.tools.substrate.CoreClient", FakeCoreClient)
    png = _solid_png(528)
    config = _reference_config(tmp_path, [{"asset_id": "ref_x", "png": png, "order": 0}])
    tools = _tools_only(config)

    content = _view(tools, "reference:ref_x")
    images = [b for b in content if b["type"] == "image"]
    assert len(images) == 1
    assert base64.b64decode(images[0]["data"]) == png


def test_view_reference_unknown_lists_available(tmp_path, monkeypatch):
    monkeypatch.setattr("lumen_agent.tools.substrate.CoreClient", FakeCoreClient)
    config = _reference_config(tmp_path, [{"asset_id": "ref_a", "png": _solid_png(), "order": 0}])
    tools = _tools_only(config)

    content = _view(tools, "reference:9")
    assert all(b["type"] == "text" for b in content)
    assert "unknown reference" in content[0]["text"].lower()
    assert "reference:1" in content[0]["text"]


def test_view_reference_missing_bytes_is_honest(tmp_path, monkeypatch):
    monkeypatch.setattr("lumen_agent.tools.substrate.CoreClient", FakeCoreClient)
    # store=False → the digest points at a file that was never written.
    config = _reference_config(
        tmp_path, [{"asset_id": "ref_a", "png": _solid_png(), "order": 0, "store": False}]
    )
    tools = _tools_only(config)

    content = _view(tools, "reference:1")
    assert all(b["type"] == "text" for b in content)
    assert "missing" in content[0]["text"].lower()


def test_view_reference_none_attached_is_unknown(tmp_path, monkeypatch):
    monkeypatch.setattr("lumen_agent.tools.substrate.CoreClient", FakeCoreClient)
    tools = _tools_only(runtime_config(tmp_path))  # no reference_assets

    content = _view(tools, "reference:1")
    assert all(b["type"] == "text" for b in content)
    assert "unknown reference" in content[0]["text"].lower()


def test_view_invalid_target_advertises_reference_form_only_when_references(tmp_path, monkeypatch):
    monkeypatch.setattr("lumen_agent.tools.substrate.CoreClient", FakeCoreClient)

    # No references → the error string is byte-identical to pre-RC (no reference form).
    plain = _tools_only(runtime_config(tmp_path))
    plain_err = _view(plain, "bogus")[0]["text"]
    assert "reference:<n>" not in plain_err
    assert 'Use "preview" or "asset:<asset_id>"' in plain_err

    # References attached → the error string offers the reference form.
    ref_cfg = _reference_config(tmp_path, [{"asset_id": "ref_a", "png": _solid_png(), "order": 0}])
    withref_err = _view(_tools_only(ref_cfg), "bogus")[0]["text"]
    assert "reference:<n>" in withref_err


# 7g. RC2 reference-conditioned generation (D-RC2.4) --------------------------


def _install_image_model(monkeypatch, captured, provenance):
    """Install a configured T2I stub on the deepagent substrate module that
    captures generate()'s kwargs and returns a ready image; `provenance` is the
    exact dict the substrate stamps in place, so the test can read the notes back."""
    def fake_generate(**kwargs):
        captured.update(kwargs)
        return types.SimpleNamespace(
            image_bytes=b"\x89PNG-generated-bytes",
            mime_type="image/png",
            model="test/image-model",
            provenance=provenance,
            license={"name": "generated_commercial_use", "allow_export": True},
        )

    stub = types.SimpleNamespace(
        is_configured=lambda: True,
        configured_model_id=lambda: "test/image-model",
        generate=fake_generate,
    )
    monkeypatch.setattr("lumen_agent.tools.substrate.image_provider", stub)


def test_generate_image_conditions_on_references(tmp_path, monkeypatch):
    """D-RC2.4: with references attached, generate_image feeds their order-sorted
    preview bytes on the provider's reference_images channel, keys the cache on
    their pixel digests, and stamps honest reference-conditioned provenance."""
    monkeypatch.setattr("lumen_agent.tools.substrate.CoreClient", FakeCoreClient)
    from lumen_agent.tools import substrate as sub

    png_a, png_b = _solid_png(544), _solid_png(576)
    dig_a, dig_b = hashlib.sha256(png_a).hexdigest(), hashlib.sha256(png_b).hexdigest()
    config = _reference_config(
        tmp_path,
        [
            {"asset_id": "ref_b", "png": png_b, "order": 1},  # dict order != attach order
            {"asset_id": "ref_a", "png": png_a, "order": 0},
        ],
    )
    captured: dict = {}
    prov = {"created_by": "agent", "source_label": "image generation", "notes": []}
    _install_image_model(monkeypatch, captured, prov)

    tools = _tools_only(config, prompt="hero")
    _give_page(tools)
    result = json.loads(tools.generate_image("a calm clinic reception"))
    assert result["image"]["status"] == "ok"
    assert result["image"]["mode"] == "model"

    # Order-sorted by attachment order (order 0 first), regardless of dict order.
    assert captured["reference_images"] == [(png_a, "image/png"), (png_b, "image/png")]
    # Honest provenance names the conditioning digests.
    note = prov["notes"][-1]
    assert "reference-conditioned on 2 attachment(s)" in note
    assert dig_a in note and dig_b in note
    # The cache was keyed on the reference PIXEL digests.
    key = sub.image_cache.generation_key(
        prompt="a calm clinic reception",
        model="test/image-model",
        brand_notes=[],
        reference_digests=[dig_a, dig_b],
    )
    assert sub.image_cache.lookup(str(config.effective_asset_store_root), key) is not None


def test_generate_image_condition_on_references_false_skips(tmp_path, monkeypatch):
    """D-RC2.1 opt-out: condition_on_references=false suppresses conditioning even
    with references attached — no reference_images, no reference-conditioned note."""
    monkeypatch.setattr("lumen_agent.tools.substrate.CoreClient", FakeCoreClient)
    config = _reference_config(
        tmp_path, [{"asset_id": "ref_a", "png": _solid_png(544), "order": 0}]
    )
    captured: dict = {}
    prov = {"created_by": "agent", "source_label": "image generation", "notes": []}
    _install_image_model(monkeypatch, captured, prov)

    tools = _tools_only(config, prompt="hero")
    _give_page(tools)
    result = json.loads(
        tools.generate_image("a calm clinic reception", condition_on_references=False)
    )
    assert result["image"]["status"] == "ok"
    assert captured["reference_images"] is None
    assert not any("reference-conditioned" in n for n in prov["notes"])


def test_generate_image_without_references_byte_identical_call(tmp_path, monkeypatch):
    """No references → the provider call is byte-identical to pre-RC2: every kwarg
    pinned, reference_images None (no new behavior on the plain path)."""
    monkeypatch.setattr("lumen_agent.tools.substrate.CoreClient", FakeCoreClient)
    captured: dict = {}
    prov = {"created_by": "agent", "source_label": "image generation", "notes": []}
    _install_image_model(monkeypatch, captured, prov)

    tools = _tools_only(runtime_config(tmp_path), prompt="hero")
    _give_page(tools)
    tools.generate_image("a serene mountain lake at dawn", brand_notes=["deep navy"])
    assert captured.pop("request_id").startswith("asset_img_")
    assert captured == {
        "prompt": "a serene mountain lake at dawn",
        "width": None,
        "height": None,
        "brand_notes": ["deep navy"],
        "aspect_ratio": None,
        "transparent_background": None,
        "reference_images": None,
    }
    assert not any("reference-conditioned" in n for n in prov["notes"])


def test_generate_image_missing_reference_blob_skipped_not_fatal(tmp_path, monkeypatch):
    """D-RC2.4: a reference whose store blob is gone mid-run is SKIPPED with a
    recorded warning (never a hard fail) — the remaining reference still
    conditions, generation still succeeds, and the key drops the missing digest."""
    monkeypatch.setattr("lumen_agent.tools.substrate.CoreClient", FakeCoreClient)
    from lumen_agent.tools import substrate as sub

    present_png = _solid_png(544)
    present_dig = hashlib.sha256(present_png).hexdigest()
    config = _reference_config(
        tmp_path,
        [
            {"asset_id": "ref_ok", "png": present_png, "order": 0},
            {"asset_id": "ref_gone", "png": _solid_png(576), "order": 1, "store": False},
        ],
    )
    captured: dict = {}
    prov = {"created_by": "agent", "source_label": "image generation", "notes": []}
    _install_image_model(monkeypatch, captured, prov)

    tools = _tools_only(config, prompt="hero")
    _give_page(tools)
    result = json.loads(tools.generate_image("a calm clinic reception"))
    assert result["image"]["status"] == "ok"  # never dead-ends on a missing blob

    # Only the present reference conditions; the missing one is dropped everywhere.
    assert captured["reference_images"] == [(present_png, "image/png")]
    assert "reference-conditioned on 1 attachment(s)" in prov["notes"][-1]
    assert present_dig in prov["notes"][-1]
    key = sub.image_cache.generation_key(
        prompt="a calm clinic reception",
        model="test/image-model",
        brand_notes=[],
        reference_digests=[present_dig],
    )
    assert sub.image_cache.lookup(str(config.effective_asset_store_root), key) is not None

    # The skip was recorded (honest trace, not a silent drop).
    trace = (tools.trace_dir / "trace.jsonl").read_text(encoding="utf-8")
    assert "reference_preview_missing" in trace
    assert "ref_gone" in trace


# 7h. W1.7 generation robustness (brand-ad-assets v1) -------------------------


def _install_failing_image_model(monkeypatch, error):
    """A configured T2I model whose generate() always raises — the shape of a
    real provider failure (no_image after its retry, a 404, a read timeout)."""
    def fake_generate(**kwargs):
        raise error

    monkeypatch.setattr(
        "lumen_agent.tools.substrate.image_provider",
        types.SimpleNamespace(
            is_configured=lambda: True,
            configured_model_id=lambda: "test/image-model",
            generate=fake_generate,
        ),
    )


def test_w17c_generation_failure_does_not_fail_the_turn(tmp_path, monkeypatch):
    """W1.7(c) + founder ruling D5 (no new blocking gates): a failed generation
    must NEVER block the design turn. It degrades to the deterministic
    placeholder so the design still composes, and hands the agent a TYPED,
    non-blocking outcome it can react to — the documented reaction being to drop
    the image ground and proceed with a flat brand-token ground.

    This pins the behavior the Apollo pilot observed for `image_edit_failed` on
    the GENERATE path too, so it cannot silently regress into a hard failure."""
    monkeypatch.setattr("lumen_agent.tools.substrate.CoreClient", FakeCoreClient)

    class _ProviderError(Exception):
        code = "image_model.no_image"

    _install_failing_image_model(
        monkeypatch, _ProviderError("OpenRouter response contained no image")
    )

    tools = _tools_only(runtime_config(tmp_path), prompt="hero")
    _give_page(tools)
    result = json.loads(tools.generate_image("an abstract holographic yellow wash"))

    # NOT blocked: the tool returns a usable asset, not an error status.
    image = result["image"]
    assert image["status"] == "ok"
    assert image["asset_id"]
    # ...but it is honest that the imagery is a placeholder, not the real thing.
    assert image["mode"] == "placeholder"

    # The typed, machine-readable outcome the agent reacts to.
    fallback = image["fallback"]
    assert fallback["reason"] == "model_failed"
    assert fallback["error_code"] == "image_model.no_image"
    assert fallback["conditioning_lost"] is False
    # ...and the reaction is spelled out, including the flat-token-ground option.
    assert "flat brand-token ground" in image["hint"]

    # A warning diagnostic still rides along (unchanged behavior).
    assert any(diag.get("code") == "LUMA0710" for diag in result["diagnostics"])


def test_w17c_unconfigured_model_is_a_distinct_typed_fallback(tmp_path, monkeypatch):
    """W1.7(c): 'the model broke' and 'no model is configured' are different
    problems with different fixes, so they are different typed reasons — an agent
    should not retry a prompt against a model that does not exist."""
    monkeypatch.setattr("lumen_agent.tools.substrate.CoreClient", FakeCoreClient)
    monkeypatch.setattr(
        "lumen_agent.tools.substrate.image_provider",
        types.SimpleNamespace(is_configured=lambda: False, configured_model_id=lambda: ""),
    )

    tools = _tools_only(runtime_config(tmp_path), prompt="hero")
    _give_page(tools)
    image = json.loads(tools.generate_image("an abstract wash"))["image"]

    assert image["status"] == "ok"  # still never blocks
    assert image["mode"] == "placeholder"
    assert image["fallback"]["reason"] == "not_configured"
    assert image["fallback"]["error_code"] == "image_model.not_configured"


def test_w17c_reference_conditioned_failure_reports_conditioning_lost(
    tmp_path, monkeypatch
):
    """W1.7(c): a placeholder is inherently UNCONDITIONED. When the failed
    generation was reference-conditioned, the typed outcome says the brand
    conditioning was lost — otherwise the agent would place a generic placeholder
    believing it still carries the reference's palette and mood."""
    monkeypatch.setattr("lumen_agent.tools.substrate.CoreClient", FakeCoreClient)
    config = _reference_config(
        tmp_path, [{"asset_id": "ref_a", "png": _solid_png(544), "order": 0}]
    )
    _install_failing_image_model(monkeypatch, RuntimeError("upstream exploded"))

    tools = _tools_only(config, prompt="hero")
    _give_page(tools)
    image = json.loads(tools.generate_image("a calm clinic reception"))["image"]

    assert image["status"] == "ok"
    assert image["fallback"]["conditioning_lost"] is True


def test_w17b_turn_sees_real_output_dimensions_not_its_own_request(
    tmp_path, monkeypatch
):
    """W1.7(b): the Apollo POC asked 16:9 and got 1024x1024, while the reference
    manifest kept reporting the REQUEST back. The tool payload must carry the
    model's real geometry and flag the mismatch, so an agent choosing a ground
    treatment is never misled about what it just placed."""
    monkeypatch.setattr("lumen_agent.tools.substrate.CoreClient", FakeCoreClient)

    def fake_generate(**kwargs):
        return types.SimpleNamespace(
            image_bytes=b"\x89PNG-generated-bytes",
            mime_type="image/png",
            model="test/image-model",
            provenance={"created_by": "agent", "notes": []},
            license={"name": "generated_commercial_use", "allow_export": True},
            width=1024,          # what the model actually returned...
            height=1024,
            aspect_ratio_honored=False,  # ...which is not the 16:9 that was asked
        )

    monkeypatch.setattr(
        "lumen_agent.tools.substrate.image_provider",
        types.SimpleNamespace(
            is_configured=lambda: True,
            configured_model_id=lambda: "test/image-model",
            generate=fake_generate,
        ),
    )

    tools = _tools_only(runtime_config(tmp_path), prompt="hero")
    _give_page(tools)
    image = json.loads(
        tools.generate_image("a holographic wash", aspect_ratio="16:9")
    )["image"]

    assert image["status"] == "ok"
    assert image["aspect_ratio"] == "16:9"  # the request is still reported...
    assert (image["actual_width"], image["actual_height"]) == (1024, 1024)  # ...and the truth
    assert image["aspect_ratio_honored"] is False
    assert "1024x1024" in image["note"] and "16:9" in image["note"]


# 7b. scaffold ----------------------------------------------------------------


def test_scaffold_writes_references_md_and_state_ids(tmp_path, monkeypatch):
    from lumen_agent.workspace import scaffold_workspace

    monkeypatch.setattr("lumen_agent.tools.substrate.CoreClient", FakeCoreClient)
    config = _reference_config(
        tmp_path,
        [
            {"asset_id": "ref_a", "png": _solid_png(), "order": 0, "label": "logo-hero.png",
             "colors": ["#0b1220", "#2a6f97"], "title": "advisory caption"},
            {"asset_id": "ref_b", "png": _solid_png(), "order": 1, "label": "poster.jpg"},
        ],
    )
    tools = _tools_only(config)
    workspace = scaffold_workspace(tools, "Make a poster like these")

    refs_md = (workspace / "references.md").read_text(encoding="utf-8")
    # Header duties: view("reference:<n>") shows pixels; the DIRECTOR writes the brief.
    assert 'view("reference:<n>")' in refs_md
    assert "reference-brief.md" in refs_md
    assert "BEFORE round 1" in refs_md
    # One row per reference IN ORDER, with metadata + advisory clearly marked.
    assert "| 1 | ref_a |" in refs_md
    assert "| 2 | ref_b |" in refs_md
    assert "logo-hero.png" in refs_md and "poster.jpg" in refs_md
    assert "#0b1220" in refs_md
    assert "advisory caption" in refs_md
    assert "advisory" in refs_md.lower()

    # reference-brief.md is the DIRECTOR's job — the scaffold must NOT pre-write it.
    assert not (workspace / "reference-brief.md").exists()

    state = json.loads((workspace / "state.json").read_text(encoding="utf-8"))
    assert state["reference_asset_ids"] == ["ref_a", "ref_b"]


def test_scaffold_without_references_is_byte_identical_noop(tmp_path, monkeypatch):
    """The no-op guarantee: no references → references.md and reference-brief.md
    never appear, and no scaffold file mentions references."""
    from lumen_agent.workspace import scaffold_workspace

    monkeypatch.setattr("lumen_agent.tools.substrate.CoreClient", FakeCoreClient)
    tools = _tools_only(runtime_config(tmp_path))
    workspace = scaffold_workspace(tools, "Make a plain poster")

    assert not (workspace / "references.md").exists()
    assert not (workspace / "reference-brief.md").exists()
    # No reference language leaks into the human-facing scaffold files.
    assert "reference" not in (workspace / "brief.md").read_text(encoding="utf-8").lower()
    assert "reference" not in (workspace / "rounds" / "index.md").read_text(encoding="utf-8").lower()
    # state.json carries the field but empty (the always-present-but-empty shape).
    state = json.loads((workspace / "state.json").read_text(encoding="utf-8"))
    assert state["reference_asset_ids"] == []


# 7c. VisualCritique schema round-trip ---------------------------------------


def test_visual_critique_roundtrip_without_reference_fidelity_is_backward_compatible():
    # A pre-RC critique.json has no reference_fidelity key at all — it must still
    # validate, defaulting the field to None, and re-serialize with it None.
    legacy_json = json.dumps(
        {"accepted": True, "summary": "looks good", "issues": [], "confidence": 0.9}
    )
    critique = VisualCritique.model_validate_json(legacy_json)
    assert critique.reference_fidelity is None
    reloaded = VisualCritique.model_validate_json(critique.model_dump_json())
    assert reloaded.reference_fidelity is None


def test_visual_critique_roundtrip_with_reference_fidelity_and_score_clamp():
    critique = VisualCritique(
        accepted=False,
        summary="regressed to house style",
        issues=[],
        reference_fidelity=ReferenceFidelity(
            score=7, reasons="ignored the references' hard edges", regressed_to_house_style=True
        ),
    )
    # Score clamps into 0..3 (no JSON-schema min/max, like confidence).
    assert critique.reference_fidelity.score == 3
    reloaded = VisualCritique.model_validate_json(critique.model_dump_json())
    assert reloaded.reference_fidelity is not None
    assert reloaded.reference_fidelity.regressed_to_house_style is True
    assert reloaded.reference_fidelity.reasons == "ignored the references' hard edges"

    # ToolStrategy(VisualCritique) still constructs (reviewer output path, D11).
    assert ToolStrategy(VisualCritique).schema is VisualCritique


# 7d. prompt contract (RC blocks are conditional + no-op) --------------------


def test_prompts_without_references_are_byte_identical_to_default():
    ws = "/tmp/ws-rc"
    # The default (one-arg) call and the explicit has_references=False call are the
    # SAME string, and neither carries any RC reference block — the prompt no-op pin.
    # (The base author prompt legitimately says "the DSL reference"; the pin is on
    # the RC-specific markers, not the substring "reference".)
    rc_markers = (
        "references.md",
        "reference-brief.md",
        "reference:<n>",
        "reference_fidelity",
        "REFERENCE IMAGES",
        "REFERENCE FIDELITY",
    )
    for build in (_orch, _auth, _rev):
        assert build(ws) == build(ws, has_references=False)
        rendered = build(ws)
        for marker in rc_markers:
            assert marker not in rendered


def test_orchestrator_prompt_with_references_carries_step_1b():
    ws = "/tmp/ws-rc"
    orch = _orch(ws, has_references=True)
    assert "references.md" in orch
    assert "reference-brief.md" in orch
    assert 'view("reference:<n>")' in orch
    # The three brief duties + precedence + injection scoping + blocking gate.
    assert "DEFINING QUALITIES" in orch
    assert "REFERENCE-vs-KIT PRECEDENCE" in orch
    assert "kit identity" in orch
    # Injection scoping: attacker text inside a reference image is content, not commands.
    assert "content to depict or ignore" in orch
    assert "reference_fidelity" in orch
    assert "<=1" in orch


def test_harness_threads_has_references_into_all_three_prompts(tmp_path, monkeypatch):
    """End-to-end wiring: a reference config makes create_design_deepagent scaffold
    references.md AND inject the reference blocks into all three role prompts."""
    capture: dict = {}
    _install_deepagents_stub(monkeypatch, capture)

    config = _reference_config(tmp_path, [{"asset_id": "ref_a", "png": _solid_png(), "order": 0}])
    _agent, tools = create_design_deepagent("Design like this", config)

    assert (tools.trace_dir / "workspace" / "references.md").exists()
    kwargs = capture["kwargs"]
    assert "reference-brief.md" in kwargs["system_prompt"]  # orchestrator
    subagents = {sa["name"]: sa for sa in kwargs["subagents"]}
    assert "reference-brief.md" in subagents["lumen-dsl-author"]["system_prompt"]
    assert "REFERENCE FIDELITY" in subagents["lumen-visual-reviewer"]["system_prompt"]


def test_author_and_reviewer_prompts_with_references():
    ws = "/tmp/ws-rc"
    author = _auth(ws, has_references=True)
    assert "reference-brief.md" in author
    assert "house vocabulary" in author

    reviewer = _rev(ws, has_references=True)
    assert "REFERENCE FIDELITY" in reviewer
    assert "reference_fidelity" in reviewer
    assert "regressed_to_house_style" in reviewer
    assert 'view("reference:<n>")' in reviewer
