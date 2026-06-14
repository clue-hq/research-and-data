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
from lumen_deepagent.loop import (
    LumenQualityLoop,
    classify_diagnostics,
    is_layout_cluster_dsl,
    is_surgical_dsl,
    repair_is_surgical,
)
from lumen_deepagent.prompts import build_subagents
from lumen_deepagent.providers import (
    compact_preview_payload,
    extract_dsl,
    parse_visual_critique,
    preview_image_blocks,
)
from lumen_api.core import CoreError
from lumen_deepagent.schemas import (
    CritiqueCategory,
    RepairClass,
    VisualCritique,
    VisualIssue,
    VisualTarget,
)
from lumen_deepagent.tools import LumenDesignTools, validate_preview_bytes


class FakeCoreClient:
    def __init__(self, repo_root: Path) -> None:
        self.repo_root = repo_root

    def new_scene(self, document_id: str, title: str):
        return {
            "meta": {"id": document_id, "title": title, "medium": "ad"},
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

    def apply_operations(self, scene, operations, scope=None):
        updated = dict(scene)
        updated["applied_by_core"] = True
        return {"scene": updated, "applied_operations": len(operations), "diagnostics": []}

    def generate_qr(
        self,
        store_root,
        data,
        asset_id,
        label=None,
        ec_level=None,
        print_media=False,
        target_width_mm=None,
        raise_on_error=True,
    ):
        effective_level = ec_level or ("h" if print_media else "m")
        diagnostics = []
        if target_width_mm is not None and target_width_mm < 20.0:
            diagnostics.append(
                {
                    "severity": "warning",
                    "phase": "validation",
                    "code": "LUMA0700",
                    "message": "QR below reliable print width",
                }
            )
        digest = "f" * 64
        return {
            "ok": True,
            "diagnostics": diagnostics,
            "asset": {
                "record": {
                    "id": asset_id,
                    "label": label or f"QR code ({data})",
                    "kind": "vector",
                    "status": "ready",
                    "source": {
                        "kind": "generated",
                        "request_id": asset_id,
                        "model": "qr-v1",
                    },
                    "media": {
                        "mime_type": "image/svg+xml",
                        "digest": {"algorithm": "sha256", "value": digest},
                        "location": {
                            "provider": "local-store",
                            "opaque_ref": f"sha256/ff/{digest}",
                            "url": None,
                        },
                    },
                    "provenance": {
                        "created_by": "qr-v1",
                        "source_label": "generated:qr",
                    },
                    "license": {"name": "generated_qr", "allow_export": True},
                    "tags": ["qr", "generated"],
                },
                "deduplicated": False,
                "qr": {
                    "ec_level": effective_level,
                    "module_count": 29,
                    "quiet_zone_modules": 4,
                },
            },
        }

    def apply_structured_edit(self, scene, edit, scope=None):
        if scope and scope.get("mode") == "strict":
            allowed_ids = {target.get("id") for target in scope.get("allowed", [])}
            target_id = (edit.get("target") or {}).get("id")
            if target_id not in allowed_ids:
                raise CoreError(
                    "edit.scope_violation",
                    "1 operation(s) touch targets outside the declared scope",
                    diagnostics=[
                        {
                            "severity": "error",
                            "phase": "operation",
                            "code": "edit.scope_violation",
                            "message": "out of declared scope",
                        }
                    ],
                )
        updated = json.loads(json.dumps(scene))
        updated["structured_edit_applied_by_core"] = True
        return {
            "scene": updated,
            "applied_operations": 1,
            "diagnostics": [],
            "operations": [{"kind": "update_node", "node_id": "headline"}],
            "edit": {
                "kind": edit.get("kind"),
                "touched_targets": [edit.get("target")],
                "intent": "modify_node",
                "checkpoint_label": None,
            },
        }

    def platform_default_brand_kit(self):
        return {
            "id": "brand_kit_platform_default",
            "version": 1,
            "name": "Platform Default",
            "modes": {
                "defaults": {
                    "theme": "light",
                    "density": "comfortable",
                    "accessibility": "standard",
                    "medium": "print",
                }
            },
        }

    def preflight_scene(self, scene, brand_kit):
        updated = json.loads(json.dumps(scene))
        updated.setdefault("meta", {})["brand_kit"] = {
            "id": brand_kit["id"],
            "version": brand_kit["version"],
        }
        return {
            "scene": updated,
            "diagnostics": [],
            "preflight": {
                "has_errors": False,
                "brand_ref_operations": [],
                "token_operations": [],
                "layout_operations": [],
            },
        }

    def export_preview(
        self, scene, export_format="svg", page_ids=None, asset_store_root=None
    ):
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
    def export_preview(
        self, scene, export_format="svg", page_ids=None, asset_store_root=None
    ):
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


class FakeAlwaysPreflightErrorCoreClient(FakeCoreClient):
    """Compiles a full scene; preflight ALWAYS reports a blocking error on node
    `headline`. Counts compile calls so a test can prove that a rejected
    non-surgical repair never reaches the compiler."""

    def __init__(self, repo_root: Path) -> None:
        super().__init__(repo_root)
        self.compile_calls = 0

    def compile_dsl_into_scene(self, scene, source: str, dsl_session=None):
        self.compile_calls += 1
        return super().compile_dsl_into_scene(scene, source, dsl_session=dsl_session)

    def preflight_scene(self, scene, brand_kit):
        return {
            "scene": scene,
            "diagnostics": [
                {
                    "severity": "error",
                    "code": "LUMV0903",
                    "message": "text node headline exceeds available height",
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


class FakeLayoutClusterPreflightCoreClient(FakeCoreClient):
    def __init__(self, repo_root: Path) -> None:
        super().__init__(repo_root)
        self.compile_calls = 0

    def compile_dsl_into_scene(self, scene, source: str, dsl_session=None):
        self.compile_calls += 1
        return {
            "scene": layout_cluster_scene(),
            "applied_operations": 2,
            "dsl": {
                "compile_output": {
                    "operations": [{"kind": "add_page"}, {"kind": "insert_node"}],
                    "diagnostics": [],
                },
                "operation_error": None,
                "session_snapshot": dsl_session,
            },
        }

    def preflight_scene(self, scene, brand_kit):
        return {
            "scene": scene,
            "diagnostics": [
                {
                    "severity": "error",
                    "code": "LUMV0801",
                    "message": "node headline exceeds parent card bounds",
                    "target_node_id": "headline",
                    "hint": "Resize the card/header layout cluster.",
                }
            ],
            "preflight": {
                "has_errors": True,
                "brand_ref_operations": [],
                "token_operations": [],
                "layout_operations": [],
            },
        }


class FakeSurgicalCarryForwardCoreClient(FakeCoreClient):
    """iter1 compiles; preflight errors once on node `headline` (→ surgical);
    iter2's modify-only block fails to COMPILE with a node-less diagnostic. Surgical
    mode must carry forward so a later destructive block is still rejected."""

    def __init__(self, repo_root: Path) -> None:
        super().__init__(repo_root)
        self.compile_calls = 0
        self.preflight_calls = 0

    def compile_dsl_into_scene(self, scene, source: str, dsl_session=None):
        self.compile_calls += 1
        if self.compile_calls == 2:
            return {
                "scene": scene,
                "applied_operations": 0,
                "dsl": {
                    "compile_output": {
                        "operations": [],
                        "diagnostics": [
                            {
                                "severity": "error",
                                "code": "LUMD0230",
                                "message": "rd(...) expects 1 argument(s), got 4",
                            }
                        ],
                        "halted_at": {"code": "LUMD0230", "line": 1},
                    },
                    "operation_error": None,
                    "session_snapshot": None,
                },
            }
        return super().compile_dsl_into_scene(scene, source, dsl_session=dsl_session)

    def preflight_scene(self, scene, brand_kit):
        self.preflight_calls += 1
        if self.preflight_calls == 1:
            return {
                "scene": scene,
                "diagnostics": [
                    {
                        "severity": "error",
                        "code": "LUMV0903",
                        "message": "text node headline exceeds available height",
                        "subject": {"kind": "node", "id": "headline"},
                        "hint": "Use hug height or reduce the font size.",
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
    def export_preview(
        self, scene, export_format="svg", page_ids=None, asset_store_root=None
    ):
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


def layout_cluster_scene() -> dict:
    return {
        "meta": {"id": "doc_test", "title": "Layout cluster"},
        "pages": {
            "page_a4": {
                "id": "page_a4",
                "children": ["artboard"],
                "size": {"width": 595.276, "height": 841.89, "unit": "pt"},
            }
        },
        "nodes": {
            "artboard": {
                "id": "artboard",
                "kind": {"kind": "frame"},
                "children": ["card"],
                "transform": {"x": 0, "y": 0},
            },
            "card": {
                "id": "card",
                "kind": {"kind": "frame"},
                "children": ["headline", "divider", "body"],
                "transform": {"x": 48, "y": 96},
            },
            "headline": {
                "id": "headline",
                "kind": {"kind": "text", "content": "Headline"},
                "children": [],
            },
            "divider": {
                "id": "divider",
                "kind": {"kind": "line"},
                "children": [],
            },
            "body": {
                "id": "body",
                "kind": {"kind": "text", "content": "Body"},
                "children": [],
            },
        },
        "slots": {},
        "assets": {},
    }


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
    assert reviewer["skills"] == [
        "apps/agent_runtime/knowledge_docs/skills/visual-review"
    ]
    author = next(
        agent for agent in subagents if agent["name"] == "lumen-dsl-author"
    )
    # The author's procedures are separated by concern under knowledge_docs/skills.
    assert "apps/agent_runtime/knowledge_docs/skills/create-design" in author["skills"]
    assert "apps/agent_runtime/knowledge_docs/skills/repair-design" in author["skills"]
    # The deepagent must not depend on the developer-facing docs/ tree.
    assert all("/skills/" in skill for skill in author["skills"])


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
        "apply_structured_edit",
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
        "apps/agent_runtime/knowledge_docs/knowledge/lumen-dsl/grammar.md",
        "apps/agent_runtime/knowledge_docs/knowledge/design/layout-recipes.md",
        "apps/agent_runtime/knowledge_docs/knowledge/design-systems/brand-validation.md",
        "apps/agent_runtime/knowledge_docs/knowledge/loop/authoring-and-repair.md",
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

    assert {"lumen-dsl", "design", "design-systems", "loop"}.issubset(
        {snippet.category for snippet in snippets[:4]}
    )
    assert all(
        "apps/agent_runtime/knowledge_docs/knowledge" in snippet.path
        for snippet in snippets[:4]
    )
    assert any(
        snippet.path
        == "apps/agent_runtime/knowledge_docs/knowledge/design-systems/brand-validation.md"
        for snippet in snippets[:4]
    )


def test_artboard_frame_knowledge_encodes_canonical_pt_contract():
    repo_root = Path(__file__).resolve().parents[3]
    docs = {
        "create": repo_root
        / "apps/agent_runtime/knowledge_docs/skills/create-design/SKILL.md",
        "recipes": repo_root
        / "apps/agent_runtime/knowledge_docs/knowledge/design/layout-recipes.md",
        "artboard": repo_root
        / "apps/agent_runtime/knowledge_docs/knowledge/design/artboard-frame-authoring.md",
        "cluster": repo_root
        / "apps/agent_runtime/knowledge_docs/knowledge/loop/layout-cluster-repair.md",
    }
    text = "\n".join(path.read_text(encoding="utf-8") for path in docs.values())

    assert "canonical layout points" in text
    assert "A4 is about `595 x 842 pt`" in text
    assert "artboard-local" in text
    assert "background fill" in text
    assert "layout_cluster" in text
    assert "page linkedin_square size(1080,1080,px)\n  bg fr" not in text
    assert "full-page background frame" not in docs["recipes"].read_text(
        encoding="utf-8"
    )


def test_task_knowledge_surfaces_artboard_and_layout_cluster_docs():
    repo_root = Path(__file__).resolve().parents[3]

    snippets = read_task_knowledge(
        repo_root,
        "Create an A4 appointment card with parent overflow and oversized background layout cluster repair",
        limit=12,
    )
    paths = {snippet.path for snippet in snippets}
    excerpts = "\n".join(snippet.excerpt for snippet in snippets)

    assert (
        "apps/agent_runtime/knowledge_docs/knowledge/design/artboard-frame-authoring.md"
        in paths
    )
    assert (
        "apps/agent_runtime/knowledge_docs/knowledge/loop/layout-cluster-repair.md"
        in paths
    )
    assert "canonical layout points" in excerpts
    assert "parent containment" in excerpts


def test_artboard_fixture_prompts_cover_required_surfaces():
    repo_root = Path(__file__).resolve().parents[3]
    fixture_path = repo_root / "apps/agent_runtime/evaluation/fixture_prompts.json"
    fixtures = json.loads(fixture_path.read_text(encoding="utf-8"))
    by_id = {fixture["id"]: fixture for fixture in fixtures}

    required_ids = {
        "a4_appointment_card_artboard_frame",
        "letter_healthcare_one_pager",
        "square_linkedin_neurosurgery",
        "wide_linkedin_healthcare",
        "parent_overflow_cluster_repair",
    }

    assert required_ids.issubset(by_id)
    assert "595x842pt" in by_id["a4_appointment_card_artboard_frame"]["prompt"]
    assert "612x792pt" in by_id["letter_healthcare_one_pager"]["prompt"]
    assert "1080x1080pt" in by_id["square_linkedin_neurosurgery"]["prompt"]
    assert "1200x628pt" in by_id["wide_linkedin_healthcare"]["prompt"]
    assert "layout_cluster" in by_id["parent_overflow_cluster_repair"]["prompt"]
    assert all(
        "loose oversized bg rectangle" in by_id[fixture_id]["prompt"]
        for fixture_id in {
            "a4_appointment_card_artboard_frame",
            "letter_healthcare_one_pager",
            "parent_overflow_cluster_repair",
        }
    )


def test_quality_loop_passes_knowledge_excerpts_to_author(tmp_path: Path, monkeypatch):
    monkeypatch.setattr("lumen_deepagent.tools.CoreClient", FakeCoreClient)
    paths = [
        "apps/agent_runtime/knowledge_docs/knowledge/lumen-dsl/grammar.md",
        "apps/agent_runtime/knowledge_docs/knowledge/design/layout-recipes.md",
        "apps/agent_runtime/knowledge_docs/knowledge/design-systems/token-taxonomy.md",
        "apps/agent_runtime/knowledge_docs/knowledge/loop/authoring-and-repair.md",
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


def test_structured_edit_tool_applies_core_generated_operations(
    tmp_path: Path, monkeypatch
):
    monkeypatch.setattr("lumen_deepagent.tools.CoreClient", FakeCoreClient)
    tools = LumenDesignTools(runtime_config(tmp_path), "Move the headline down")
    tools.compile_dsl_block('page page_test\n  headline text "Plan" p(24,24) s(400,hug)')

    result = json.loads(
        tools.apply_structured_edit(
            json.dumps(
                {
                    "kind": "modify",
                    "target": {"kind": "node", "id": "headline"},
                    "patch": {
                        "kind": "node",
                        "value": {
                            "text": {
                                "content": {
                                    "kind": "set",
                                    "value": "Better repaired headline",
                                }
                            }
                        },
                    },
                }
            )
        )
    )

    assert result["structured_edit"]["status"] == "ok"
    assert result["structured_edit"]["applied_operations"] == 1
    assert result["operations"] == [{"kind": "update_node", "node_id": "headline"}]
    assert tools.scene["structured_edit_applied_by_core"] is True
    assert tools.scene_update_sources[-1] == "apply_structured_edit"


def test_structured_edit_strict_scope_rejection_records_verdict(
    tmp_path: Path, monkeypatch
):
    monkeypatch.setattr("lumen_deepagent.tools.CoreClient", FakeCoreClient)
    tools = LumenDesignTools(runtime_config(tmp_path), "Repair the headline")
    tools.compile_dsl_block('page page_test\n  headline text "Plan" p(24,24) s(400,hug)')

    result = json.loads(
        tools.apply_structured_edit(
            json.dumps(
                {
                    "kind": "modify",
                    "target": {"kind": "node", "id": "body"},
                    "patch": {"kind": "node", "value": {}},
                    "scope": {
                        "mode": "strict",
                        "allowed": [{"kind": "node", "id": "headline"}],
                    },
                }
            )
        )
    )

    assert result["structured_edit"]["status"] == "error"
    assert (
        result["structured_edit"]["operation_error"]["code"] == "edit.scope_violation"
    )
    assert result["scope_verdict"] == "rejected"
    assert result["scope"]["allowed"] == [{"kind": "node", "id": "headline"}]
    assert "structured_edit_applied_by_core" not in tools.scene


def test_structured_edit_in_scope_repair_records_scope_verdict(
    tmp_path: Path, monkeypatch
):
    monkeypatch.setattr("lumen_deepagent.tools.CoreClient", FakeCoreClient)
    tools = LumenDesignTools(runtime_config(tmp_path), "Repair the headline")
    tools.compile_dsl_block('page page_test\n  headline text "Plan" p(24,24) s(400,hug)')

    result = json.loads(
        tools.apply_structured_edit(
            json.dumps(
                {
                    "kind": "modify",
                    "target": {"kind": "node", "id": "headline"},
                    "patch": {
                        "kind": "node",
                        "value": {
                            "text": {"content": {"kind": "set", "value": "Repaired"}}
                        },
                    },
                    "scope": {
                        "mode": "strict",
                        "allowed": [{"kind": "node", "id": "headline"}],
                    },
                }
            )
        )
    )

    assert result["structured_edit"]["status"] == "ok"
    assert result["scope_verdict"] == "in_scope"
    assert tools.scene["structured_edit_applied_by_core"] is True


def test_preflight_and_final_trace_record_effective_brand_context(
    tmp_path: Path, monkeypatch
):
    monkeypatch.setattr("lumen_deepagent.tools.CoreClient", FakeCoreClient)
    config = runtime_config(tmp_path)
    tools = LumenDesignTools(config, "Create a square ad")
    tools.compile_dsl_block("page page_test")

    preflight_result = json.loads(tools.preflight_design())
    final = json.loads(tools.finalize_run("accepted", "accepted", "Accepted."))

    assert preflight_result["preflight"]["brand_source"] == "platform_default"
    assert preflight_result["preflight"]["brand_kit_id"] == "brand_kit_platform_default"
    assert preflight_result["preflight"]["brand_kit_version"] == "1"
    assert preflight_result["preflight"]["brand_mode"] == {
        "theme": "light",
        "density": "comfortable",
        "accessibility": "standard",
        "medium": "digital",
    }
    assert preflight_result["effective_brand"] == final["effective_brand"]
    assert final["final_scene_summary"]["effective_brand"] == final["effective_brand"]

    preflight_payload = json.loads(
        (config.trace_dir / tools.run_id / "iterations" / "001" / "preflight.json")
        .read_text(encoding="utf-8")
    )
    assert preflight_payload["effective_brand"]["mode"]["medium"] == "digital"

    trace_events = [
        json.loads(line)
        for line in (config.trace_dir / tools.run_id / "trace.jsonl")
        .read_text(encoding="utf-8")
        .splitlines()
    ]
    preflight_event = next(event for event in trace_events if event["event"] == "preflight_completed")
    finalized_event = next(event for event in trace_events if event["event"] == "run_finalized")
    assert preflight_event["payload"]["effective_brand"]["brand_kit_id"] == "brand_kit_platform_default"
    assert finalized_event["payload"]["effective_brand"]["mode"]["medium"] == "digital"


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
    # A preflight error on a named node drives a SURGICAL repair: the author must
    # answer with a modify-only `#<node> ...` line, not a re-author.
    author = ScriptedAuthor(["page page_test", "#headline s(400,80)"])
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


def test_is_surgical_dsl_classifies_modify_only_blocks():
    # Modify-only blocks (edit existing nodes in place) are surgical.
    assert is_surgical_dsl("#headline s(400,80)")
    assert is_surgical_dsl("#card s(400,560)\n#title font_size(20)")
    assert is_surgical_dsl("// checkpoint\n#node o(0.5)")
    # Anything that can delete / re-declare / re-page the scene is NOT surgical.
    assert not is_surgical_dsl("page page_a4 preset(a4,portrait)")
    assert not is_surgical_dsl("delete(card)\n#card s(1,1)")
    assert not is_surgical_dsl("parent(card, page:page_a4)")
    assert not is_surgical_dsl("hero fr p(0,0) s(10,10)")  # element declaration
    assert not is_surgical_dsl("# just a comment")  # comment, not a modify ref
    assert not is_surgical_dsl("")  # no modify line at all
    assert repair_is_surgical("structured_ops", {"node_id": "headline"})
    assert not repair_is_surgical("dsl", {"node_id": "headline"})
    assert not repair_is_surgical("structured_ops", {"page_id": "page_a4"})


def test_targeted_overflow_repair_routes_to_structured_ops_despite_font_asset_warning(
    tmp_path: Path, monkeypatch
):
    # The preflight bundle for a text overflow also carries an unrelated
    # "font asset" warning. The bare word "asset" must NOT route a node-targeted
    # text-fit repair to the asset tool — it routes to structured_ops.
    monkeypatch.setattr("lumen_deepagent.tools.CoreClient", FakeCoreClient)
    tools = LumenDesignTools(runtime_config(tmp_path), "Design an appointment card")
    intent = (
        "repair targeted preflight diagnostics: LUMV0903 on instruction: text node "
        "instruction exceeds available height Use hug height. | LUMB0613 on document: "
        "font asset brand is not marked embeddable for export"
    )
    overflow = json.loads(
        tools.recommend_edit_surface(intent, json.dumps({"node_id": "instruction"}))
    )
    assert overflow["recommendation"] == "structured_ops"
    # A genuine asset-generation intent still routes to the asset tool.
    gen = json.loads(tools.recommend_edit_surface("generate image for the hero panel", "{}"))
    assert gen["recommendation"] == "asset_tool"
    # A no-target compose intent routes to DSL authoring.
    compose = json.loads(tools.recommend_edit_surface("design a square ad layout", "{}"))
    assert compose["recommendation"] == "dsl"


def test_lumv0800_routes_to_layout_cluster():
    scene = layout_cluster_scene()
    diagnostics = [
        {
            "severity": "error",
            "code": "LUMV0800",
            "message": "node artboard exceeds page bounds",
            "target_page_id": "page_a4",
            "target_node_id": "artboard",
        }
    ]

    classification = classify_diagnostics(
        diagnostics,
        {"page_id": "page_a4", "node_id": "artboard"},
        scene=scene,
    )

    assert classification.repair_class == RepairClass.layout_cluster
    assert classification.allowed_edit_surface.value == "structured_ops"
    assert classification.cluster is not None
    assert classification.cluster.page_id == "page_a4"
    assert classification.cluster.root_frame_id == "artboard"
    assert "LUMV0800" in classification.cluster.diagnostic_codes
    assert "convert_diagnosed_background" in classification.permissions


def test_lumv0801_routes_to_layout_cluster_with_parent_and_descendants():
    scene = layout_cluster_scene()
    diagnostics = [
        {
            "severity": "error",
            "code": "LUMV0801",
            "message": "node headline exceeds parent card bounds",
            "target_node_id": "headline",
        }
    ]

    classification = classify_diagnostics(
        diagnostics,
        {"node_id": "headline"},
        scene=scene,
    )

    assert classification.repair_class == RepairClass.layout_cluster
    assert classification.cluster is not None
    assert classification.cluster.page_id == "page_a4"
    assert classification.cluster.parent_node_id == "card"
    assert set(classification.cluster.descendant_node_ids) == {
        "headline",
        "divider",
        "body",
    }


def test_single_text_fit_stays_targeted_but_siblings_escalate_to_layout_cluster():
    scene = layout_cluster_scene()
    single = classify_diagnostics(
        [
            {
                "severity": "error",
                "code": "LUMV0903",
                "message": "headline exceeds available height",
                "target_node_id": "headline",
            }
        ],
        {"node_id": "headline"},
        scene=scene,
    )
    assert single.repair_class == RepairClass.targeted_node

    siblings = classify_diagnostics(
        [
            {
                "severity": "error",
                "code": "LUMV0903",
                "message": "headline exceeds available height",
                "target_node_id": "headline",
            },
            {
                "severity": "error",
                "code": "LUMV0903",
                "message": "body exceeds available height",
                "target_node_id": "body",
            },
        ],
        {"node_id": "headline"},
        scene=scene,
    )
    assert siblings.repair_class == RepairClass.layout_cluster
    assert siblings.cluster is not None
    assert siblings.cluster.parent_node_id == "card"


def test_brand_and_legacy_geometry_repair_classes():
    scene = layout_cluster_scene()
    brand = classify_diagnostics(
        [
            {
                "severity": "error",
                "code": "LUMB0804",
                "message": "raw color where token belongs",
                "target_node_id": "card",
            }
        ],
        {"node_id": "card"},
        scene=scene,
    )
    legacy = classify_diagnostics(
        [
            {
                "severity": "warning",
                "code": "LUMV0805",
                "message": "legacy non-pt page advice",
                "target_page_id": "page_a4",
            }
        ],
        {"page_id": "page_a4"},
        scene=scene,
    )

    assert brand.repair_class == RepairClass.brand_token
    assert legacy.repair_class == RepairClass.unsupported_gap
    assert legacy.allowed_edit_surface.value == "external_planner"


def test_layout_cluster_dsl_guard_scopes_modifies_and_background_delete():
    context = {
        "repair_class": "layout_cluster",
        "cluster": {
            "page_id": "page_a4",
            "root_frame_id": "artboard",
            "parent_node_id": "card",
            "descendant_node_ids": ["headline", "divider", "body"],
            "background_node_id": "bg",
        },
        "permissions": ["convert_diagnosed_background"],
    }

    assert is_layout_cluster_dsl(
        "#page:page_a4 background($surface.page)\n#card s(fill,hug)\n#headline s(fill,hug)",
        context,
    )
    assert is_layout_cluster_dsl("delete(bg)\n#artboard fill($surface.page)", context)
    assert not is_layout_cluster_dsl("page page_a4 preset(a4,portrait)", context)
    assert not is_layout_cluster_dsl("#unrelated s(1,1)", context)
    assert not is_layout_cluster_dsl("delete(headline)", context)
    assert not is_layout_cluster_dsl("#slot:campaign.headline required(false)", context)


def test_background_conversion_delete_requires_diagnosed_background_permission():
    context = {
        "repair_class": "layout_cluster",
        "cluster": {
            "page_id": "page_a4",
            "root_frame_id": "artboard",
            "parent_node_id": "card",
            "descendant_node_ids": ["headline"],
            "background_node_id": "bg",
        },
        "permissions": [],
    }

    assert not is_layout_cluster_dsl("delete(bg)", context)
    assert not is_layout_cluster_dsl("delete(backdrop)", context)
    context["permissions"] = ["convert_diagnosed_background"]
    assert is_layout_cluster_dsl("delete(bg)", context)


def test_layout_cluster_repair_request_carries_cluster_permissions_and_guard(
    tmp_path: Path, monkeypatch
):
    monkeypatch.setattr(
        "lumen_deepagent.tools.CoreClient", FakeLayoutClusterPreflightCoreClient
    )
    config = runtime_config(tmp_path, max_iterations=3)
    tools = LumenDesignTools(config, "Create an A4 appointment card")
    author = ScriptedAuthor(
        [
            "page page_a4 preset(a4,portrait)",
            "page page_a4 preset(a4,portrait)",  # rejected: not cluster-scoped DSL
            "#card s(fill,hug)\n#headline s(fill,hug)",
        ]
    )
    reviewer = ScriptedReviewer(
        [VisualCritique(accepted=True, summary="should not be reached")]
    )

    result = LumenQualityLoop(tools, author, reviewer).run(
        "Create an A4 appointment card"
    )

    assert result["status"] == "failed"
    assert author.requests[1].repair_context["repair_class"] == "layout_cluster"
    assert author.requests[1].repair_context["cluster"]["parent_node_id"] == "card"
    assert "modify_auto_layout" in author.requests[1].repair_context["permissions"]
    assert author.requests[2].repair_context["kind"] == "layout_cluster_violation"
    events = [
        json.loads(line)["event"]
        for line in (config.trace_dir / tools.run_id / "trace.jsonl")
        .read_text(encoding="utf-8")
        .splitlines()
    ]
    assert "layout_cluster_repair_rejected" in events
    assert tools.core.compile_calls == 2


def test_rejected_layout_cluster_repair_does_not_touch_scene(tmp_path: Path, monkeypatch):
    monkeypatch.setattr(
        "lumen_deepagent.tools.CoreClient", FakeLayoutClusterPreflightCoreClient
    )
    config = runtime_config(tmp_path, max_iterations=2)
    tools = LumenDesignTools(config, "Create an A4 appointment card")
    author = ScriptedAuthor(
        [
            "page page_a4 preset(a4,portrait)",
            "page page_a4 preset(a4,portrait)",
        ]
    )
    reviewer = ScriptedReviewer(
        [VisualCritique(accepted=True, summary="should not be reached")]
    )

    result = LumenQualityLoop(tools, author, reviewer).run(
        "Create an A4 appointment card"
    )

    assert result["status"] == "failed"
    assert tools.core.compile_calls == 1
    assert "card" in tools.scene["nodes"]
    assert "headline" in tools.scene["nodes"]
    assert author.requests[1].repair_context["repair_class"] == "layout_cluster"


def test_surgical_repair_rejects_destructive_block_without_touching_scene(
    tmp_path: Path, monkeypatch
):
    # A preflight error on a named node drives a surgical repair. If the author
    # answers with a destructive re-author (delete + re-page), the loop must
    # REJECT it before compile so the existing design is never stripped.
    monkeypatch.setattr(
        "lumen_deepagent.tools.CoreClient", FakeAlwaysPreflightErrorCoreClient
    )
    config = runtime_config(tmp_path, max_iterations=3)
    tools = LumenDesignTools(config, "Create a square LinkedIn ad")
    destructive = "delete(headline)\npage page_test\n  bg rect p(0,0) s(1080,1080)"
    author = ScriptedAuthor(["page page_test", destructive])
    reviewer = ScriptedReviewer(
        [VisualCritique(accepted=True, summary="should not be reached")]
    )

    result = LumenQualityLoop(tools, author, reviewer).run("Create a square LinkedIn ad")

    assert result["status"] == "failed"
    assert result["stop_reason"] == "max_iterations_reached"
    # Only the FIRST (initial) block ever reached the compiler; every destructive
    # repair was rejected before compile.
    assert tools.core.compile_calls == 1
    # The scene still holds the original design — it was never wiped.
    assert "headline" in tools.scene["nodes"]
    # The reviewer was never reached (preflight never passed).
    assert reviewer.calls == []
    events = [
        json.loads(line)["event"]
        for line in (config.trace_dir / tools.run_id / "trace.jsonl")
        .read_text(encoding="utf-8")
        .splitlines()
    ]
    assert "dsl_repair_not_surgical" in events


def test_surgical_mode_carries_forward_through_compile_error(tmp_path: Path, monkeypatch):
    # A surgical repair (preflight overflow on `headline`) whose modify-only block
    # then fails to COMPILE with a node-less diagnostic must STAY surgical: the
    # next destructive block is still rejected, even though the compile diagnostic
    # carried no node target.
    monkeypatch.setattr(
        "lumen_deepagent.tools.CoreClient", FakeSurgicalCarryForwardCoreClient
    )
    config = runtime_config(tmp_path, max_iterations=4)
    tools = LumenDesignTools(config, "Create a square LinkedIn ad")
    author = ScriptedAuthor(
        [
            "page page_test",  # iter1: full design, compiles
            "#headline s(400,80)",  # iter2: modify-only, but fails COMPILE
            "delete(headline)\npage page_test",  # iter3+: destructive — must be rejected
        ]
    )
    reviewer = ScriptedReviewer(
        [VisualCritique(accepted=True, summary="should not be reached")]
    )

    result = LumenQualityLoop(tools, author, reviewer).run("Create a square LinkedIn ad")

    assert result["status"] == "failed"
    # Only iter1 (initial) and iter2 (modify-only) reached the compiler; every
    # destructive repair after the compile error was rejected before compile.
    assert tools.core.compile_calls == 2
    assert "headline" in tools.scene["nodes"]
    events = [
        json.loads(line)["event"]
        for line in (config.trace_dir / tools.run_id / "trace.jsonl")
        .read_text(encoding="utf-8")
        .splitlines()
    ]
    assert "dsl_repair_not_surgical" in events


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


class FakeDestructiveRepairCoreClient(FakeCoreClient):
    """First compile builds a full scene; the repair compile strips every node
    and halts. This mirrors a real destructive repair that emits `delete(...)`
    for each node (which core applies) and then halts on a bad re-creation line —
    leaving `tools.scene` wiped before the compiler rejects the block."""

    def __init__(self, repo_root: Path) -> None:
        super().__init__(repo_root)
        self.compile_calls = 0

    def compile_dsl_into_scene(self, scene, source: str, dsl_session=None):
        self.compile_calls += 1
        if self.compile_calls == 1:
            return super().compile_dsl_into_scene(scene, source, dsl_session=dsl_session)
        wiped = dict(scene)
        wiped["pages"] = {}
        wiped["nodes"] = {}
        wiped["slots"] = {}
        return {
            "scene": wiped,
            "applied_operations": 0,
            "dsl": {
                "compile_output": {
                    "operations": [],
                    "diagnostics": [
                        {
                            "severity": "error",
                            "code": "LUMD0207",
                            "message": "parent(page_test) is not a valid statement",
                        }
                    ],
                    "halted_at": {"code": "LUMD0207", "line": 8},
                },
                "operation_error": None,
                "session_snapshot": None,
            },
        }


def test_failed_run_restores_best_compiled_scene_for_canvas_draft(
    tmp_path: Path, monkeypatch
):
    """A destructive final repair must not strip the design from the canvas.

    Iteration 1 compiles a full scene but the reviewer rejects it; the repair
    (iteration 2) wipes the scene and halts. The run fails, but the loop must
    restore the best compiled scene so the editor renders it as a draft instead
    of an empty canvas (the `draft_scene` the API surfaces is `tools.scene`)."""
    monkeypatch.setattr(
        "lumen_deepagent.tools.CoreClient", FakeDestructiveRepairCoreClient
    )
    config = runtime_config(tmp_path, max_iterations=2)
    tools = LumenDesignTools(config, "Create a square LinkedIn ad")
    author = ScriptedAuthor(["page page_test", "delete(headline)"])
    reviewer = ScriptedReviewer(
        [
            VisualCritique(
                accepted=False,
                summary="Hierarchy is unclear.",
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
    # The live scene the API hands to the editor as draft_scene must still carry
    # the best compiled design, not the wiped scene from the destructive repair.
    assert tools.scene["nodes"], "best compiled scene was not restored after failure"
    assert "headline" in tools.scene["nodes"]
    assert "page_test" in tools.scene["pages"]


def test_brand_fit_critique_blocks_acceptance_and_drives_repair(
    tmp_path: Path, monkeypatch
):
    monkeypatch.setattr("lumen_deepagent.tools.CoreClient", FakeCoreClient)
    config = runtime_config(tmp_path, max_iterations=2)
    tools = LumenDesignTools(config, "Create a brand-aligned LinkedIn ad")
    author = ScriptedAuthor(["page page_test", "headline text \"Branded repair\""])
    reviewer = ScriptedReviewer(
        [
            VisualCritique(
                accepted=False,
                summary="The design is visually tidy but off-brand.",
                issues=[
                    VisualIssue(
                        category=CritiqueCategory.brand_fit,
                        target=VisualTarget(page_id="page_test", node_id="headline"),
                        message="The headline ignores the effective Brand Kit typography and color roles.",
                        suggested_repair="Use the Brand Kit headline style and semantic surface/text tokens.",
                    )
                ],
                repair_instruction=(
                    "Repair only headline so it uses Brand Kit semantic type and color roles."
                ),
            ),
            VisualCritique(accepted=True, summary="Brand fit is acceptable."),
        ]
    )

    result = LumenQualityLoop(tools, author, reviewer).run(
        "Create a brand-aligned LinkedIn ad"
    )

    assert result["status"] == "accepted"
    assert len(author.requests) == 2
    assert len(reviewer.calls) == 2
    assert (
        reviewer.calls[0]["scene_summary"]["effective_brand"]["brand_kit_id"]
        == "brand_kit_platform_default"
    )
    repair_context = author.requests[1].repair_context
    assert repair_context["kind"] == "visual"
    assert repair_context["feedback"]["issues"][0]["category"] == "brand_fit"
    assert "Brand Kit headline style" in json.dumps(repair_context)


def test_trace_evaluator_summarizes_final_run_outputs(tmp_path: Path):
    run_dir = tmp_path / ".lumen-runs" / "run_test"
    run_dir.mkdir(parents=True)
    (run_dir / "final.json").write_text(
        json.dumps(
            {
                "status": "failed",
                "run_id": "run_test",
                "stop_reason": "preview_invalid",
                "effective_brand": {
                    "source": "platform_default",
                    "brand_kit_id": "brand_kit_platform_default",
                    "brand_kit_version": "1",
                    "mode": {
                        "theme": "light",
                        "density": "comfortable",
                        "accessibility": "standard",
                        "medium": "digital",
                    },
                },
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
    assert summary["brand_kits"] == {"brand_kit_platform_default@1": 1}
    assert summary["brand_modes"] == {
        "accessibility=standard,density=comfortable,medium=digital,theme=light": 1
    }
    assert summary["brand_contexts"][0]["brand_kit_id"] == "brand_kit_platform_default"
    assert summary["unresolved_issue_categories"]["clipping"] == 1
    assert summary["unresolved_issue_categories"]["gap:rendering_export_preview"] == 1
    assert summary["preview_paths"] == ["/tmp/preview.svg"]
    assert summary["layout_cluster_repairs"] == 0
    assert summary["remaining_parent_overflow"] == 0


def test_trace_evaluator_counts_layout_cluster_and_geometry_failures(tmp_path: Path):
    run_dir = tmp_path / ".lumen-runs" / "run_cluster"
    iteration_dir = run_dir / "iterations" / "001"
    iteration_dir.mkdir(parents=True)
    (run_dir / "final.json").write_text(
        json.dumps(
            {
                "status": "failed",
                "run_id": "run_cluster",
                "stop_reason": "max_iterations_reached",
                "critique": {},
                "gaps": [],
            }
        ),
        encoding="utf-8",
    )
    (iteration_dir / "repair_request.json").write_text(
        json.dumps(
            {
                "repair_request": {
                    "repair_class": "layout_cluster",
                    "cluster": {"page_id": "page_a4", "parent_node_id": "card"},
                }
            }
        ),
        encoding="utf-8",
    )
    (iteration_dir / "preflight.json").write_text(
        json.dumps(
            {
                "preflight": {
                    "diagnostics": [
                        {
                            "severity": "error",
                            "code": "LUMV0800",
                            "message": "background bg exceeds artboard bounds",
                            "target_node_id": "bg",
                        },
                        {
                            "severity": "error",
                            "code": "LUMV0801",
                            "message": "headline exceeds parent card bounds",
                            "target_node_id": "headline",
                        },
                        {
                            "severity": "error",
                            "code": "LUMV0903",
                            "message": "body exceeds available height",
                            "target_node_id": "body",
                        },
                    ]
                }
            }
        ),
        encoding="utf-8",
    )
    (run_dir / "trace.jsonl").write_text(
        "\n".join(
            [
                json.dumps(
                    {
                        "event": "layout_cluster_repair_rejected",
                        "payload": {"rejected_source": "page page_a4"},
                    }
                ),
                json.dumps(
                    {
                        "event": "dsl_repair_not_surgical",
                        "payload": {"rejected_source": "delete(headline)"},
                    }
                ),
            ]
        ),
        encoding="utf-8",
    )

    summary = summarize_trace_dir(tmp_path / ".lumen-runs")

    assert summary["layout_cluster_repairs"] == 1
    assert summary["layout_cluster_rejections"] == 1
    assert summary["destructive_repair_rejections"] == 1
    assert summary["whole_scene_regeneration_attempts"] == 2
    assert summary["oversized_background_rects"] == 1
    assert summary["remaining_artboard_overflow"] == 1
    assert summary["remaining_parent_overflow"] == 1
    assert summary["final_lumv080x_count"] == 2
    assert summary["final_lumv090x_count"] == 1


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


def test_generate_qr_tool_registers_asset_and_traces_provenance(
    tmp_path: Path, monkeypatch
):
    monkeypatch.setattr("lumen_deepagent.tools.CoreClient", FakeCoreClient)
    tools = LumenDesignTools(runtime_config(tmp_path), "Create a mailer")

    result = json.loads(
        tools.generate_qr(
            "https://lumen.example/a/acme-health",
            print_media=True,
            target_width_mm=14.0,
        )
    )

    assert result["qr"]["status"] == "ok"
    assert result["qr"]["source"]["model"] == "qr-v1"
    assert result["qr"]["provenance"]["source_label"] == "generated:qr"
    assert result["qr"]["ec_level"] == "h"
    assert result["qr"]["quiet_zone_modules"] == 4
    assert result["qr"]["license"] == "generated_qr"
    assert any(diag["code"] == "LUMA0700" for diag in result["diagnostics"])

    # The asset registered through the canonical operation path.
    assert tools.scene["applied_by_core"] is True
    assert tools.scene_update_sources[-1] == "generate_qr"

    # The trace records provenance for the generated asset.
    trace_lines = (
        (tools.trace_dir / "trace.jsonl").read_text().strip().splitlines()
    )
    events = [json.loads(line) for line in trace_lines]
    qr_events = [event for event in events if event["event"] == "qr_generated"]
    assert len(qr_events) == 1
    payload = qr_events[0]["payload"]
    assert payload["qr"]["provenance"]["source_label"] == "generated:qr"
    assert payload["qr"]["asset_id"].startswith("asset_qr_")


def test_critic_preview_export_passes_asset_store_root(tmp_path: Path, monkeypatch):
    captured: dict = {}

    class RecordingCoreClient(FakeCoreClient):
        def export_preview(
            self, scene, export_format="svg", page_ids=None, asset_store_root=None
        ):
            captured["asset_store_root"] = asset_store_root
            return super().export_preview(
                scene, export_format, page_ids, asset_store_root=asset_store_root
            )

    monkeypatch.setattr("lumen_deepagent.tools.CoreClient", RecordingCoreClient)
    tools = LumenDesignTools(runtime_config(tmp_path), "Create a square ad")
    tools.compile_dsl_block('page page_test\n  headline text "Plan" p(24,24) s(400,hug)')
    tools.export_preview()

    # The critic preview resolves real bytes: the agent's store root is
    # wired into every preview export rather than rendering placeholders.
    expected = str(tools.config.effective_asset_store_root)
    assert captured["asset_store_root"] == expected
    assert expected.endswith("asset-store")


# ---------------------------------------------------------------------------
# Phase G agent surfaces (slice G9)
# ---------------------------------------------------------------------------

PHASE_G_REPO_ROOT = Path(__file__).resolve().parents[3]
PHASE_G_MAILER_FIXTURE = (
    PHASE_G_REPO_ROOT
    / "crates/lumen-core/fixtures/conformance/phase_g_mailer_revision.json"
)
PHASE_G_NOMINAL_BINDING = (
    PHASE_G_REPO_ROOT / "crates/lumen-core/fixtures/binding/nominal.json"
)


@pytest.mark.skipif(
    not os.environ.get("LUMEN_CORE_HELPER"),
    reason="requires the real core helper binary",
)
def test_phase_g_agent_tools_validate_and_preview_instances(tmp_path: Path):
    tools = LumenDesignTools(runtime_config(tmp_path), "Personalize the mailer")
    tools.scene = json.loads(PHASE_G_MAILER_FIXTURE.read_text())
    binding = json.loads(PHASE_G_NOMINAL_BINDING.read_text())
    # Bind the logo to the asset record the template already carries so the
    # preview derivation resolves it from the scene.
    binding["values"]["account.logo"]["asset_id"] = "asset_placeholder_logo"

    # validate_binding_set: the critic can check a recipient's data.
    valid = json.loads(tools.validate_binding_set(json.dumps(binding)))
    assert valid["binding_validation"]["status"] == "valid", valid

    broken = json.loads(PHASE_G_NOMINAL_BINDING.read_text())
    broken["values"].pop("contact.full_name")
    invalid = json.loads(tools.validate_binding_set(json.dumps(broken)))
    assert invalid["binding_validation"]["status"] == "invalid"
    assert any(
        diag["code"] == "LUMG0012" for diag in invalid["diagnostics"]
    ), invalid

    # derive_instance_preview: a personalized instance the critic can see.
    preview = json.loads(
        tools.derive_instance_preview(json.dumps(binding), export_format="svg")
    )
    assert preview["instance_preview"]["status"] == "ok", preview
    assert preview["instance_preview"]["has_errors"] is False
    assert preview["instance_preview"]["fit_status"] == "fits"
    paths = preview["instance_preview"]["preview_paths"]
    assert paths, "preview artifact must be written for critique"
    svg = Path(paths[0]).read_text()
    assert "Dr. Priya Sharma" in svg, "the preview carries the bound content"
    assert paths[0] in tools.preview_paths

    # The working scene was never mutated: instances are derived artifacts.
    assert (
        tools.scene["nodes"]["node_qr"]["kind"]["asset_id"]
        == "asset_placeholder_qr"
    )

    # Trace records both tool runs.
    events = [
        json.loads(line)
        for line in (tools.trace_dir / "trace.jsonl").read_text().splitlines()
    ]
    assert any(event["event"] == "binding_set_validated" for event in events)
    assert any(event["event"] == "instance_preview_derived" for event in events)
