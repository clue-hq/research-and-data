from __future__ import annotations

import json
import os
import sys
import types
from pathlib import Path

import pytest

sys.path.append(str(Path(__file__).resolve().parents[1]))
sys.path.append(str(Path(__file__).resolve().parents[2] / "api"))

try:
    from dotenv import load_dotenv
except ImportError:  # pragma: no cover - dotenv is a dev/test dependency.
    load_dotenv = None

if load_dotenv is not None:
    load_dotenv(Path(__file__).resolve().parents[3] / ".env", override=False)

from lumen_deepagent.config import AgentRuntimeConfig
from lumen_deepagent.eval_traces import summarize_trace_dir
from lumen_deepagent.knowledge import read_knowledge, read_task_knowledge
from lumen_deepagent.loop import LumenQualityLoop
from lumen_deepagent.prompts import build_subagents
from lumen_deepagent.providers import (
    compact_preview_payload,
    extract_dsl,
    parse_visual_critique,
    preview_image_blocks,
)
from lumen_deepagent.schemas import CritiqueCategory, VisualCritique, VisualIssue, VisualTarget
from lumen_deepagent.tools import LumenDesignTools, validate_preview_bytes


class FakeCoreClient:
    def __init__(self, repo_root: Path) -> None:
        self.repo_root = repo_root

    def new_scene(self, document_id: str, title: str):
        return {
            "meta": {"id": document_id, "title": title},
            "pages": {},
            "nodes": {},
            "slots": {},
            "assets": {},
        }

    def compile_dsl_into_scene(self, scene, source: str, dsl_session=None):
        updated = dict(scene)
        updated["pages"] = {
            "page_test": {
                "id": "page_test",
                "name": "Test",
                "size": {"width": 1080.0, "height": 1080.0, "unit": "px"},
                "children": ["headline"],
            }
        }
        updated["nodes"] = {
            "headline": {
                "id": "headline",
                "name": "Headline",
                "kind": {"kind": "text", "content": "Plan"},
                "children": [],
                "transform": {"x": 24.0, "y": 24.0, "rotation": 0.0, "skew_x": 0.0, "skew_y": 0.0, "flip_x": False, "flip_y": False},
                "size": {"width": {"kind": "fixed", "value": 400.0}, "height": {"kind": "hug"}},
                "computed": {"layout_bounds": {"x": 24.0, "y": 24.0, "width": 400.0, "height": 80.0}},
            }
        }
        updated["slots"] = {
            "slot_campaign_headline": {
                "key": "campaign.headline",
                "content_type": "text",
                "bound_nodes": ["headline"],
            }
        }
        return {
            "scene": updated,
            "applied_operations": 2,
            "dsl": {
                "compile_output": {
                    "operations": [{"kind": "add_page"}, {"kind": "insert_node"}],
                    "diagnostics": [],
                },
                "operation_error": None,
                "session_snapshot": {
                    "seen_node_ids": ["headline"],
                    "previous_structural_depth": 1,
                    "previous_can_have_children": False,
                    "parent_stack": [
                        {"indent": 0, "parent": {"kind": "page", "id": "page_test"}}
                    ],
                    "emitted_slots": {"campaign.headline": "slot_campaign_headline"},
                },
            },
        }

    def apply_operations(self, scene, operations):
        updated = dict(scene)
        updated["applied_by_core"] = True
        return {"scene": updated, "applied_operations": len(operations), "diagnostics": []}

    def platform_default_brand_kit(self):
        return {"id": "brand_kit_platform_default", "version": 1}

    def preflight_scene(self, scene, brand_kit):
        return {
            "scene": scene,
            "diagnostics": [],
            "preflight": {
                "has_errors": False,
                "brand_ref_operations": [],
                "token_operations": [],
                "layout_operations": [],
            },
        }

    def export_preview(self, scene, export_format="svg", page_ids=None):
        return {
            "diagnostics": [],
            "export": {
                "artifacts": [
                    {
                        "format": export_format,
                        "mime_type": "image/svg+xml",
                        "page_id": "page_test",
                        "bytes": list(b"<svg></svg>"),
                    }
                ]
            },
        }


class FakeInvalidPreviewCoreClient(FakeCoreClient):
    def export_preview(self, scene, export_format="svg", page_ids=None):
        return {
            "diagnostics": [],
            "export": {
                "artifacts": [
                    {
                        "format": export_format,
                        "mime_type": "image/svg+xml",
                        "page_id": "page_test",
                        "bytes": list(b"not svg"),
                    }
                ]
            },
        }


class FakeCompileErrorOnceCoreClient(FakeCoreClient):
    def __init__(self, repo_root: Path) -> None:
        super().__init__(repo_root)
        self.compile_count = 0

    def compile_dsl_into_scene(self, scene, source: str, dsl_session=None):
        self.compile_count += 1
        if self.compile_count == 1:
            return {
                "scene": scene,
                "applied_operations": 0,
                "dsl": {
                    "compile_output": {
                        "operations": [],
                        "diagnostics": [
                            {
                                "severity": "error",
                                "code": "LUMD_TEST",
                                "message": "simulated compile error",
                                "span": {"line": 1, "column": 1},
                            }
                        ],
                    },
                    "operation_error": None,
                    "session_snapshot": dsl_session,
                },
            }
        return super().compile_dsl_into_scene(scene, source, dsl_session=dsl_session)


class FakeHaltedCompileCoreClient(FakeCoreClient):
    def compile_dsl_into_scene(self, scene, source: str, dsl_session=None):
        return {
            "scene": scene,
            "applied_operations": 0,
            "dsl": {
                "compile_output": {
                    "operations": [],
                    "diagnostics": [
                        {
                            "severity": "error",
                            "code": "LUMD0205",
                            "message": "unsupported DSL syntax",
                            "span": {"line": 1, "column": 1},
                        }
                    ],
                    "halted_at": {"code": "LUMD0205", "line": 1},
                },
                "operation_error": None,
                "session_snapshot": dsl_session,
            },
        }


class FakePreflightErrorOnceCoreClient(FakeCoreClient):
    def __init__(self, repo_root: Path) -> None:
        super().__init__(repo_root)
        self.preflight_count = 0

    def preflight_scene(self, scene, brand_kit):
        self.preflight_count += 1
        if self.preflight_count == 1:
            return {
                "scene": scene,
                "diagnostics": [
                    {
                        "severity": "error",
                        "code": "preflight.test",
                        "message": "simulated preflight error",
                        "subject": {"kind": "node", "id": "headline"},
                        "hint": "Use hug height or reduce the headline font size.",
                    }
                ],
                "preflight": {
                    "has_errors": True,
                    "brand_ref_operations": [],
                    "token_operations": [],
                    "layout_operations": [],
                },
            }
        return super().preflight_scene(scene, brand_kit)


class FakePngCoreClient(FakeCoreClient):
    def export_preview(self, scene, export_format="svg", page_ids=None):
        if export_format == "png":
            return {
                "diagnostics": [],
                "export": {
                    "artifacts": [
                        {
                            "format": "png",
                            "mime_type": "image/png",
                            "page_id": "page_test",
                            "bytes": list(b"\x89PNG\r\n\x1a\nfake"),
                        }
                    ]
                },
            }
        return super().export_preview(scene, export_format, page_ids)


class FakeNonSquareCoreClient(FakeCoreClient):
    def compile_dsl_into_scene(self, scene, source: str, dsl_session=None):
        response = super().compile_dsl_into_scene(scene, source, dsl_session=dsl_session)
        response["scene"]["pages"]["page_test"]["size"]["width"] = 1200.0
        response["scene"]["pages"]["page_test"]["size"]["height"] = 628.0
        return response


class ScriptedAuthor:
    def __init__(self, blocks: list[str]) -> None:
        self.blocks = blocks
        self.requests = []

    def write_block(self, request):
        self.requests.append(request)
        index = min(len(self.requests) - 1, len(self.blocks) - 1)
        return self.blocks[index]


class ScriptedReviewer:
    def __init__(self, critiques: list[VisualCritique]) -> None:
        self.critiques = critiques
        self.calls = []

    def review(self, **kwargs):
        self.calls.append(kwargs)
        index = min(len(self.calls) - 1, len(self.critiques) - 1)
        return self.critiques[index]


class BrokenReviewer:
    def __init__(self, message: str = "malformed reviewer response") -> None:
        self.message = message
        self.calls = []

    def review(self, **kwargs):
        self.calls.append(kwargs)
        raise ValueError(self.message)


def runtime_config(tmp_path: Path, max_iterations: int = 3) -> AgentRuntimeConfig:
    return AgentRuntimeConfig(
        repo_root=tmp_path,
        model="anthropic:claude-opus-4-6",
        max_iterations=max_iterations,
        preview_format="svg",
        trace_dir=tmp_path / ".lumen-runs",
    )


def test_subagents_have_isolated_skills_and_structured_reviewer_output():
    subagents = build_subagents("anthropic:claude-opus-4-6")

    assert {agent["name"] for agent in subagents} == {
        "lumen-dsl-author",
        "lumen-visual-reviewer",
    }
    reviewer = next(
        agent for agent in subagents if agent["name"] == "lumen-visual-reviewer"
    )
    assert reviewer["response_format"] is VisualCritique
    assert reviewer["skills"] == ["apps/agent_runtime/skills/lumen-visual-review"]


def test_deepagents_factory_wires_full_phase_a_tool_surface(tmp_path: Path, monkeypatch):
    calls = {}

    def fake_create_deep_agent(**kwargs):
        calls["kwargs"] = kwargs
        return {"agent": "fake", "kwargs": kwargs}

    class FakeFilesystemBackend:
        def __init__(self, root_dir: str) -> None:
            self.root_dir = root_dir

    deepagents_module = types.ModuleType("deepagents")
    deepagents_module.create_deep_agent = fake_create_deep_agent
    backends_module = types.ModuleType("deepagents.backends")
    filesystem_module = types.ModuleType("deepagents.backends.filesystem")
    filesystem_module.FilesystemBackend = FakeFilesystemBackend
    monkeypatch.setitem(sys.modules, "deepagents", deepagents_module)
    monkeypatch.setitem(sys.modules, "deepagents.backends", backends_module)
    monkeypatch.setitem(sys.modules, "deepagents.backends.filesystem", filesystem_module)
    monkeypatch.setattr("lumen_deepagent.tools.CoreClient", FakeCoreClient)

    from lumen_deepagent.factory import create_lumen_design_agent

    agent, tools = create_lumen_design_agent("Create a square ad", runtime_config(tmp_path))

    assert agent["agent"] == "fake"
    assert tools.run_id
    tool_names = {tool.__name__ for tool in calls["kwargs"]["tools"]}
    assert {
        "load_knowledge",
        "compile_dsl_block",
        "apply_operations",
        "preflight_design",
        "export_preview",
        "export_preview_bundle",
        "get_latest_preview_for_critique",
        "submit_visual_critique",
        "recommend_edit_surface",
        "create_repair_request",
        "record_gap",
        "summarize_scene",
        "summarize_page",
        "summarize_slots",
        "summarize_node_tree",
        "query_geometry",
        "query_slot_bindings",
        "persist_trace_event",
        "finalize_run",
    }.issubset(tool_names)
    assert {agent["name"] for agent in calls["kwargs"]["subagents"]} == {
        "lumen-dsl-author",
        "lumen-visual-reviewer",
    }
    assert calls["kwargs"]["name"] == "lumen-design-coordinator"


def test_knowledge_retrieval_returns_provenance(tmp_path: Path):
    docs = tmp_path / "docs"
    docs.mkdir()
    (docs / "dsl-compiler.md").write_text(
        "# DSL Compiler\nCascade halt and visual repair.", encoding="utf-8"
    )

    snippets = read_knowledge(
        tmp_path,
        "How should cascade halt repair work?",
        paths=["docs/dsl-compiler.md"],
    )

    assert len(snippets) == 1
    assert snippets[0].path == "docs/dsl-compiler.md"
    assert "Cascade halt" in snippets[0].excerpt
    assert snippets[0].category == "product-doc"


def test_task_knowledge_prioritizes_lumen_docs(tmp_path: Path):
    paths = [
        "apps/agent_runtime/knowledge/lumen-dsl/authoring.md",
        "apps/agent_runtime/knowledge/design/layout-recipes.md",
        "apps/agent_runtime/knowledge/agent-loop/authoring-and-repair.md",
        "reference_docs/Brilliant-Reverse-Engineering-Report.md",
    ]
    for rel_path in paths:
        path = tmp_path / rel_path
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            f"# {rel_path}\nCreate a square ad with cascade repair and preview critique.",
            encoding="utf-8",
        )

    snippets = read_task_knowledge(tmp_path, "Create a square ad")

    categories = {snippet.category for snippet in snippets[:3]}
    assert {"lumen-dsl", "design", "agent-loop"}.issubset(categories)
    assert all("apps/agent_runtime/knowledge" in snippet.path for snippet in snippets[:3])


def test_quality_loop_passes_knowledge_excerpts_to_author(tmp_path: Path, monkeypatch):
    monkeypatch.setattr("lumen_deepagent.tools.CoreClient", FakeCoreClient)
    paths = [
        "apps/agent_runtime/knowledge/lumen-dsl/authoring.md",
        "apps/agent_runtime/knowledge/design/layout-recipes.md",
        "apps/agent_runtime/knowledge/agent-loop/authoring-and-repair.md",
    ]
    for rel_path in paths:
        path = tmp_path / rel_path
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            "# Required Knowledge\nUse line-oriented Lumen DSL: page page_a4.",
            encoding="utf-8",
        )
    tools = LumenDesignTools(runtime_config(tmp_path), "Create a square ad")
    author = ScriptedAuthor(["page page_test"])
    reviewer = ScriptedReviewer(
        [VisualCritique(accepted=True, summary="Preview is acceptable.")]
    )

    result = LumenQualityLoop(tools, author, reviewer).run("Create a square ad")

    assert result["status"] == "accepted"
    assert author.requests[0].knowledge_paths
    assert author.requests[0].knowledge_snippets
    assert "line-oriented Lumen DSL" in author.requests[0].knowledge_snippets[0].excerpt


def test_runtime_tools_update_scene_export_preview_and_write_trace(
    tmp_path: Path, monkeypatch
):
    monkeypatch.setattr("lumen_deepagent.tools.CoreClient", FakeCoreClient)
    config = runtime_config(tmp_path)
    tools = LumenDesignTools(config, "Create a square ad")

    compile_result = json.loads(tools.compile_dsl_block("page page_test"))
    operations_result = json.loads(tools.apply_operations('[{"kind":"noop"}]'))
    preflight_result = json.loads(tools.preflight_design())
    preview_result = json.loads(tools.export_preview())
    critic_payload = json.loads(tools.get_latest_preview_for_critique())
    summary = json.loads(tools.summarize_scene())
    page_summary = json.loads(tools.summarize_page("page_test"))
    slot_summary = json.loads(tools.query_slot_bindings("campaign.headline"))
    geometry = json.loads(tools.query_geometry("headline"))

    assert compile_result["compile"]["applied_operations"] == 2
    assert compile_result["dsl_session"]["previous_structural_depth"] == 1
    assert operations_result["operations"]["applied_operations"] == 1
    assert tools.scene_update_sources == ["compile_dsl_block", "apply_operations", "preflight_design"]
    assert tools.dsl_session is None
    assert preflight_result["preflight"]["has_errors"] is False
    assert preview_result["export"]["artifacts"][0]["byte_len"] > 0
    assert preview_result["export"]["artifacts"][0]["valid"] is True
    assert preview_result["export"]["artifacts"][0]["aspect_ratio"] == 1.0
    assert Path(preview_result["export"]["artifacts"][0]["path"]).exists()
    assert critic_payload["artifacts"][0]["svg_text"].startswith("<svg")
    assert summary["node_count"] == 1
    assert page_summary["page"]["aspect_ratio"] == 1.0
    assert slot_summary["slots"][0]["bound_nodes"][0]["id"] == "headline"
    assert geometry["computed"]["layout_bounds"]["width"] == 400.0

    trace_path = config.trace_dir / tools.run_id / "trace.jsonl"
    events = [
        json.loads(line)["event"]
        for line in trace_path.read_text(encoding="utf-8").splitlines()
    ]
    assert events == [
        "run_started",
        "dsl_compiled",
        "operations_applied",
        "preflight_completed",
        "preview_exported",
        "critic_preview_loaded",
    ]
    assert (config.trace_dir / tools.run_id / "input.json").exists()
    assert (config.trace_dir / tools.run_id / "iterations" / "001" / "dsl.lumen").exists()
    assert (config.trace_dir / tools.run_id / "iterations" / "001" / "export.json").exists()


def test_compile_halt_location_is_preserved_as_repair_context(
    tmp_path: Path, monkeypatch
):
    monkeypatch.setattr("lumen_deepagent.tools.CoreClient", FakeHaltedCompileCoreClient)
    tools = LumenDesignTools(runtime_config(tmp_path), "Create a square ad")

    compile_result = json.loads(tools.compile_dsl_block("bad dsl"))

    assert compile_result["compile"]["status"] == "error"
    assert compile_result["compile"]["halted_at"] == {
        "code": "LUMD0205",
        "line": 1,
    }
    assert compile_result["compile"]["diagnostics"][0]["line"] == 1


def test_preview_validation_rejects_unusable_artifacts():
    assert validate_preview_bytes(b"", "svg", "svg") == ["artifact bytes are empty"]
    assert validate_preview_bytes(b"not svg", "svg", "svg") == [
        "SVG preview does not contain an <svg root near the start"
    ]
    assert validate_preview_bytes(b"not png", "png", "png") == [
        "PNG preview has an invalid PNG signature"
    ]
    assert validate_preview_bytes(b"<svg></svg>", "svg", "png") == [
        "artifact format svg does not match requested png"
    ]


def test_invalid_preview_is_not_exposed_to_critic_payload(tmp_path: Path, monkeypatch):
    monkeypatch.setattr("lumen_deepagent.tools.CoreClient", FakeInvalidPreviewCoreClient)
    tools = LumenDesignTools(runtime_config(tmp_path), "Create a square ad")
    tools.compile_dsl_block("page page_test")

    preview_result = json.loads(tools.export_preview())
    critic_payload = json.loads(tools.get_latest_preview_for_critique())

    assert preview_result["export"]["status"] == "error"
    assert preview_result["export"]["artifacts"][0]["valid"] is False
    assert critic_payload["status"] == "error"
    assert "invalid" in critic_payload["message"]


def test_critic_preview_payload_requires_export_first(tmp_path: Path, monkeypatch):
    monkeypatch.setattr("lumen_deepagent.tools.CoreClient", FakeCoreClient)
    tools = LumenDesignTools(runtime_config(tmp_path), "Create a square ad")

    payload = json.loads(tools.get_latest_preview_for_critique())

    assert payload["status"] == "error"
    assert "no preview" in payload["message"]


def test_preview_bundle_stores_canonical_svg_and_png_critic_preview(
    tmp_path: Path, monkeypatch
):
    monkeypatch.setattr("lumen_deepagent.tools.CoreClient", FakePngCoreClient)
    config = runtime_config(tmp_path)
    config = AgentRuntimeConfig(
        repo_root=config.repo_root,
        model=config.model,
        max_iterations=config.max_iterations,
        preview_format="png",
        trace_dir=config.trace_dir,
    )
    tools = LumenDesignTools(config, "Create a square ad")
    tools.compile_dsl_block("page page_test")

    bundle = json.loads(tools.export_preview_bundle())
    critic_payload = json.loads(tools.get_latest_preview_for_critique())

    assert bundle["canonical"]["artifacts"][0]["format"] == "svg"
    assert bundle["critic"]["artifacts"][0]["format"] == "png"
    assert bundle["critic"]["artifacts"][0]["valid"] is True
    assert [artifact["format"] for artifact in critic_payload["artifacts"]] == [
        "svg",
        "png",
    ]
    assert critic_payload["artifacts"][0]["svg_text"].startswith("<svg")
    assert critic_payload["artifacts"][1]["encoding"] == "base64"
    assert (config.trace_dir / tools.run_id / "iterations" / "001" / "preview_bundle.json").exists()


def test_debug_preview_bundle_writes_artifacts_without_exposing_critic_payload(
    tmp_path: Path, monkeypatch
):
    monkeypatch.setattr("lumen_deepagent.tools.CoreClient", FakeCoreClient)
    config = runtime_config(tmp_path)
    tools = LumenDesignTools(config, "Create a square ad")
    tools.compile_dsl_block("page page_test")

    bundle = json.loads(
        tools.export_preview_bundle(
            debug_only=True,
            debug_reason="preflight_failed",
        )
    )
    critic_payload = json.loads(tools.get_latest_preview_for_critique())

    assert bundle["debug_only"] is True
    assert bundle["reviewer"]["status"] == "error"
    assert Path(bundle["reviewer"]["artifacts"][0]["path"]).exists()
    assert critic_payload["status"] == "error"
    assert "no preview" in critic_payload["message"]


def test_runtime_persists_critique_repair_and_gap_records(tmp_path: Path, monkeypatch):
    monkeypatch.setattr("lumen_deepagent.tools.CoreClient", FakeCoreClient)
    config = runtime_config(tmp_path)
    tools = LumenDesignTools(config, "Create a square ad")
    tools.compile_dsl_block("page page_test")

    critique_result = json.loads(
        tools.submit_visual_critique(
            json.dumps(
                {
                    "accepted": False,
                    "summary": "Headline is clipped.",
                    "issues": [
                        {
                            "severity": "error",
                            "category": "clipping",
                            "target": {"page_id": "page_test", "node_id": "headline"},
                            "message": "Headline clips on the right edge.",
                            "suggested_repair": "Reduce font size and wrap.",
                        }
                    ],
                    "repair_instruction": "Repair only the headline.",
                    "confidence": 0.9,
                }
            )
        )
    )
    repair = json.loads(
        tools.create_repair_request(
            exact_feedback="Headline clips on the right edge.",
            target_json='{"page_id":"page_test","node_id":"headline"}',
            allowed_edit_surface="structured_ops",
            forbidden_changes_json='["do not remove CTA"]',
        )
    )
    gap = json.loads(
        tools.record_gap(
            "layout",
            "Need explicit custom page dimensions",
            "Square ad cannot be represented by current preset DSL.",
            "Phase B",
        )
    )
    final = json.loads(tools.finalize_run("failed", "unsupported_capability", "Recorded gap."))

    assert critique_result["critique"]["accepted"] is False
    assert repair["repair_request"]["exact_feedback"] == "Headline clips on the right edge."
    assert repair["repair_request"]["allowed_edit_surface"] == "structured_ops"
    assert gap["gap"]["area"] == "layout"
    assert final["gaps"][0]["summary"] == "Need explicit custom page dimensions"
    assert (config.trace_dir / tools.run_id / "iterations" / "001" / "critique.json").exists()
    assert (config.trace_dir / tools.run_id / "iterations" / "001" / "repair_request.json").exists()
    assert (config.trace_dir / tools.run_id / "gaps.json").exists()
    assert (config.trace_dir / tools.run_id / "final.json").exists()


def test_malformed_critique_fails_closed(tmp_path: Path, monkeypatch):
    monkeypatch.setattr("lumen_deepagent.tools.CoreClient", FakeCoreClient)
    config = runtime_config(tmp_path)
    tools = LumenDesignTools(config, "Create a square ad")

    result = json.loads(tools.submit_visual_critique('{"accepted": "not-a-bool"}'))

    assert result["status"] == "error"
    assert result["stop_reason"] == "critic_failed"


def test_quality_loop_repairs_after_visual_rejection(tmp_path: Path, monkeypatch):
    monkeypatch.setattr("lumen_deepagent.tools.CoreClient", FakeCoreClient)
    config = runtime_config(tmp_path, max_iterations=3)
    tools = LumenDesignTools(config, "Create a square LinkedIn ad")
    author = ScriptedAuthor(["page page_test", "#headline font(Inter,42,700,left)"])
    reviewer = ScriptedReviewer(
        [
            VisualCritique(
                accepted=False,
                summary="Headline is clipped.",
                issues=[
                    VisualIssue(
                        severity="error",
                        category=CritiqueCategory.clipping,
                        target=VisualTarget(page_id="page_test", node_id="headline"),
                        message="Headline clips on the right edge.",
                        suggested_repair="Reduce the headline size and wrap.",
                    )
                ],
                repair_instruction="Repair only the headline.",
                confidence=0.9,
            ),
            VisualCritique(
                accepted=True,
                summary="The repaired preview satisfies the request.",
                confidence=0.85,
            ),
        ]
    )

    result = LumenQualityLoop(tools, author, reviewer).run("Create a square LinkedIn ad")

    assert result["status"] == "accepted"
    assert result["stop_reason"] == "accepted"
    assert len(author.requests) == 2
    assert author.requests[0].preview_target.requested_aspect_ratio == 1.0
    assert len(reviewer.calls) == 2
    repair_payload = json.loads(
        (config.trace_dir / tools.run_id / "iterations" / "001" / "repair_request.json")
        .read_text(encoding="utf-8")
    )
    assert repair_payload["repair_request"]["allowed_edit_surface"] == "structured_ops"
    events = [
        json.loads(line)["event"]
        for line in (config.trace_dir / tools.run_id / "trace.jsonl")
        .read_text(encoding="utf-8")
        .splitlines()
    ]
    assert "repair_requested" in events
    assert events[-1] == "run_finalized"


def test_quality_loop_persists_reviewer_failures_as_critic_failed(
    tmp_path: Path, monkeypatch
):
    monkeypatch.setattr("lumen_deepagent.tools.CoreClient", FakeCoreClient)
    config = runtime_config(tmp_path, max_iterations=3)
    tools = LumenDesignTools(config, "Create a square LinkedIn ad")
    author = ScriptedAuthor(["page page_test"])
    reviewer = BrokenReviewer("reviewer returned malformed content")

    result = LumenQualityLoop(tools, author, reviewer).run("Create a square LinkedIn ad")

    assert result["status"] == "failed"
    assert result["stop_reason"] == "critic_failed"
    critique_path = config.trace_dir / tools.run_id / "iterations" / "001" / "critique.json"
    assert critique_path.exists()
    critique_payload = json.loads(critique_path.read_text(encoding="utf-8"))
    assert critique_payload["status"] == "error"
    assert critique_payload["stop_reason"] == "critic_failed"
    assert "reviewer returned malformed content" in critique_payload["message"]
    assert (config.trace_dir / tools.run_id / "final.json").exists()


def test_quality_loop_repairs_after_compile_failure(tmp_path: Path, monkeypatch):
    monkeypatch.setattr("lumen_deepagent.tools.CoreClient", FakeCompileErrorOnceCoreClient)
    config = runtime_config(tmp_path, max_iterations=3)
    tools = LumenDesignTools(config, "Create a square LinkedIn ad")
    author = ScriptedAuthor(["bad dsl", "page page_test"])
    reviewer = ScriptedReviewer(
        [VisualCritique(accepted=True, summary="Preview is now acceptable.")]
    )

    result = LumenQualityLoop(tools, author, reviewer).run("Create a square LinkedIn ad")

    assert result["status"] == "accepted"
    assert len(author.requests) == 2
    assert author.requests[1].repair_context["kind"] == "compile"
    events = [
        json.loads(line)["event"]
        for line in (config.trace_dir / tools.run_id / "trace.jsonl")
        .read_text(encoding="utf-8")
        .splitlines()
    ]
    assert "repair_requested" in events


def test_duplicate_page_repair_block_is_rejected_before_core_compile(
    tmp_path: Path, monkeypatch
):
    monkeypatch.setattr("lumen_deepagent.tools.CoreClient", FakeCoreClient)
    tools = LumenDesignTools(runtime_config(tmp_path), "Create a square LinkedIn ad")

    first = json.loads(tools.compile_dsl_block("page page_test"))
    assert first["compile"]["status"] == "ok"

    second = json.loads(
        tools.compile_dsl_block(
            "page page_test size(1080,1080,px)\n  bg rect p(0,0) s(1080,1080)"
        )
    )

    assert second["compile"]["status"] == "error"
    assert second["compile"]["diagnostics"][0]["code"] == "LUMA0200"
    assert second["compile"]["diagnostics"][0]["target_page_id"] == "page_test"
    assert second["compile"]["halted_at"]["code"] == "LUMA0200"
    events = [
        json.loads(line)["event"]
        for line in (tools.trace_dir / "trace.jsonl")
        .read_text(encoding="utf-8")
        .splitlines()
    ]
    assert "dsl_compile_rejected" in events


def test_quality_loop_repairs_after_preflight_failure(tmp_path: Path, monkeypatch):
    monkeypatch.setattr("lumen_deepagent.tools.CoreClient", FakePreflightErrorOnceCoreClient)
    config = runtime_config(tmp_path, max_iterations=3)
    tools = LumenDesignTools(config, "Create a square LinkedIn ad")
    author = ScriptedAuthor(["page page_test", "# repair"])
    reviewer = ScriptedReviewer(
        [VisualCritique(accepted=True, summary="Preview is now acceptable.")]
    )

    result = LumenQualityLoop(tools, author, reviewer).run("Create a square LinkedIn ad")

    assert result["status"] == "accepted"
    assert len(author.requests) == 2
    assert author.requests[1].repair_context["kind"] == "preflight"
    debug_bundle_path = config.trace_dir / tools.run_id / "iterations" / "001" / "preview_bundle.json"
    assert debug_bundle_path.exists()
    debug_bundle = json.loads(debug_bundle_path.read_text(encoding="utf-8"))
    assert debug_bundle["debug_only"] is True
    assert debug_bundle["reviewer"]["status"] == "error"
    assert "preflight_failed" in debug_bundle["reviewer"]["validation_errors"]
    assert Path(debug_bundle["reviewer"]["artifacts"][0]["path"]).exists()
    repair_payload = json.loads(
        (config.trace_dir / tools.run_id / "iterations" / "001" / "repair_request.json")
        .read_text(encoding="utf-8")
    )
    assert repair_payload["repair_request"]["allowed_edit_surface"] == "structured_ops"
    assert repair_payload["repair_request"]["target"]["node_id"] == "headline"
    assert "do not recreate existing pages" in repair_payload["repair_request"]["forbidden_changes"]
    assert len(reviewer.calls) == 1
    events = [
        json.loads(line)["event"]
        for line in (config.trace_dir / tools.run_id / "trace.jsonl")
        .read_text(encoding="utf-8")
        .splitlines()
    ]
    assert "debug_preview_exported" in events


def test_quality_loop_stops_before_reviewer_on_invalid_preview(tmp_path: Path, monkeypatch):
    monkeypatch.setattr("lumen_deepagent.tools.CoreClient", FakeInvalidPreviewCoreClient)
    config = runtime_config(tmp_path, max_iterations=3)
    tools = LumenDesignTools(config, "Create a square LinkedIn ad")
    author = ScriptedAuthor(["page page_test"])
    reviewer = ScriptedReviewer(
        [VisualCritique(accepted=True, summary="Should not be called.")]
    )

    result = LumenQualityLoop(tools, author, reviewer).run("Create a square LinkedIn ad")

    assert result["status"] == "failed"
    assert result["stop_reason"] == "preview_invalid"
    assert reviewer.calls == []


def test_quality_loop_rejects_square_request_with_non_square_preview(
    tmp_path: Path, monkeypatch
):
    monkeypatch.setattr("lumen_deepagent.tools.CoreClient", FakeNonSquareCoreClient)
    config = runtime_config(tmp_path, max_iterations=3)
    tools = LumenDesignTools(config, "Create a 1:1 LinkedIn ad")
    author = ScriptedAuthor(["page page_test"])
    reviewer = ScriptedReviewer(
        [VisualCritique(accepted=True, summary="Should not be called.")]
    )

    result = LumenQualityLoop(tools, author, reviewer).run("Create a 1:1 LinkedIn ad")

    assert result["status"] == "failed"
    assert result["stop_reason"] == "preview_invalid"
    assert reviewer.calls == []
    assert result["gaps"][0]["area"] == "rendering_export_preview"


def test_quality_loop_records_max_iteration_stop(tmp_path: Path, monkeypatch):
    monkeypatch.setattr("lumen_deepagent.tools.CoreClient", FakeCoreClient)
    config = runtime_config(tmp_path, max_iterations=1)
    tools = LumenDesignTools(config, "Create a square LinkedIn ad")
    author = ScriptedAuthor(["page page_test"])
    reviewer = ScriptedReviewer(
        [
            VisualCritique(
                accepted=False,
                summary="Still too weak.",
                issues=[
                    VisualIssue(
                        category=CritiqueCategory.hierarchy,
                        message="The hierarchy is unclear.",
                        suggested_repair="Make the headline dominant.",
                    )
                ],
            )
        ]
    )

    result = LumenQualityLoop(tools, author, reviewer).run("Create a square LinkedIn ad")

    assert result["status"] == "failed"
    assert result["stop_reason"] == "max_iterations_reached"


def test_trace_evaluator_summarizes_final_run_outputs(tmp_path: Path):
    run_dir = tmp_path / ".lumen-runs" / "run_test"
    run_dir.mkdir(parents=True)
    (run_dir / "final.json").write_text(
        json.dumps(
            {
                "status": "failed",
                "stop_reason": "preview_invalid",
                "preview_paths": ["/tmp/preview.svg"],
                "critique": {
                    "issues": [
                        {"category": "clipping"},
                        {"category": "hierarchy"},
                    ]
                },
                "gaps": [{"area": "rendering_export_preview"}],
            }
        ),
        encoding="utf-8",
    )

    summary = summarize_trace_dir(tmp_path / ".lumen-runs")

    assert summary["run_count"] == 1
    assert summary["accepted"] == 0
    assert summary["failed"] == 1
    assert summary["stop_reasons"] == {"preview_invalid": 1}
    assert summary["unresolved_issue_categories"]["clipping"] == 1
    assert summary["unresolved_issue_categories"]["gap:rendering_export_preview"] == 1
    assert summary["preview_paths"] == ["/tmp/preview.svg"]


def test_provider_helpers_extract_dsl_and_parse_structured_critique():
    assert extract_dsl("```lumen\npage page_a4\n```") == "page page_a4"
    assert extract_dsl("```lumen-dsl\npage page_a4\n```") == "page page_a4"
    critique = parse_visual_critique(
        """
```json
{
  "accepted": true,
  "summary": "Looks balanced.",
  "issues": [],
  "confidence": 0.8
}
```
"""
    )
    assert critique.accepted is True
    assert critique.confidence == 0.8


def test_provider_preview_payload_omits_base64_from_text_and_emits_image_block():
    payload = {
        "status": "ok",
        "artifacts": [
            {
                "format": "png",
                "mime_type": "image/png",
                "base64": "abcd",
                "path": "/tmp/preview.png",
                "width": 1080,
                "height": 1080,
            }
        ],
    }

    compact = compact_preview_payload(payload)
    image_blocks = preview_image_blocks(payload)

    assert "base64" not in compact["artifacts"][0]
    assert compact["artifacts"][0]["base64_omitted_from_text_prompt"] is True
    assert image_blocks == [
        {
            "type": "image",
            "source_type": "base64",
            "mime_type": "image/png",
            "data": "abcd",
        }
    ]


@pytest.mark.skipif(
    os.environ.get("LUMEN_AGENT_RUN_LIVE") != "1"
    or not os.environ.get("ANTHROPIC_API_KEY"),
    reason="live provider smoke requires LUMEN_AGENT_RUN_LIVE=1 and ANTHROPIC_API_KEY",
)
def test_live_provider_quality_loop_smoke(tmp_path: Path):
    from lumen_deepagent.providers import create_provider_quality_loop

    config = AgentRuntimeConfig.from_env(Path(__file__).resolve().parents[3])
    loop, _tools = create_provider_quality_loop(
        "Create a tiny one-card Lumen DSL preview with one headline.",
        config,
    )
    result = loop.run("Create a tiny one-card Lumen DSL preview with one headline.")
    assert result["status"] in {"accepted", "failed"}
    assert result["stop_reason"]
