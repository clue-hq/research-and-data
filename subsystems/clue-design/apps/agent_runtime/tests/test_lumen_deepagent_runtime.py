from __future__ import annotations

import json
import os
import sys
import types
from collections import Counter
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
from lumen_deepagent.knowledge import (
    DIRECTIVES_PATH,
    IMAGES_DECIDE_PATH,
    IMAGES_ICONS_PATH,
    IMAGES_PLACEMENT_PATH,
    IMAGES_PROMPTS_PATH,
    KNOWLEDGE_DOCS_ROOT,
    PRIMARY_KNOWLEDGE_PATHS,
    assumes_keys,
    assumes_path,
    mandatory_task_paths,
    parse_frontmatter,
    read_knowledge,
    read_task_knowledge,
)
from lumen_deepagent.loop import (
    HeuristicAgentDirector,
    LumenQualityLoop,
    classify_diagnostics,
    classify_visual_critique,
    imagery_recipe_for_feedback,
    is_layout_cluster_dsl,
    is_surgical_dsl,
    layout_cluster_allowed_node_ids,
    recompose_recipe_for_feedback,
    repair_is_surgical,
)
from lumen_deepagent.prompts import (
    COORDINATOR_SYSTEM_PROMPT,
    DSL_AUTHOR_SYSTEM_PROMPT,
    DSL_REF_GRAMMAR_ESCALATION,
    IMAGERY_REPAIR_RECIPE,
    IMAGERY_RUBRIC,
    POSTER_RECOMPOSE_RECIPE,
    REPEAT_BLOCK_ESCALATION,
    VISUAL_REVIEWER_SYSTEM_PROMPT,
    build_subagents,
)
from lumen_deepagent.providers import (
    compact_preview_payload,
    extract_dsl,
    parse_director_decision,
    parse_visual_critique,
    preview_image_blocks,
)
from lumen_api.core import CoreError
from lumen_deepagent.schemas import (
    AgentActionMode,
    AgentDirectorDecision,
    CritiqueCategory,
    EditSurfaceRecommendation,
    RepairClass,
    VisualCritique,
    VisualIssue,
    VisualTarget,
)
from lumen_deepagent.tools import LumenDesignTools, validate_preview_bytes


class FakeCoreClient:
    def __init__(self, repo_root: Path) -> None:
        self.repo_root = repo_root
        # Every operation list passed through apply_operations, in order, so tests
        # can assert on the exact placement/upsert ops the tools emit.
        self.applied_operations: list = []

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
        self.applied_operations.extend(operations)
        updated = dict(scene)
        updated["applied_by_core"] = True
        return {"scene": updated, "applied_operations": len(operations), "diagnostics": []}

    def ingest_asset(
        self,
        store_root,
        bytes_base64,
        asset_id,
        label,
        declared_mime_type=None,
        filename=None,
        kind=None,
        uploaded_by=None,
        license=None,
        provenance=None,
        source=None,
        tags=None,
        max_bytes=None,
        raise_on_error=True,
    ):
        self.last_ingest = {
            "asset_id": asset_id,
            "mime": declared_mime_type,
            "kind": kind,
            "source": source,
            "bytes_base64": bytes_base64,
        }
        return {
            "ok": True,
            "diagnostics": [],
            "asset": {
                "record": {
                    "id": asset_id,
                    "label": label,
                    "kind": kind or "raster_image",
                    "status": "ready",
                    "source": source or {"kind": "generated", "request_id": asset_id, "model": "model"},
                    "media": {"mime_type": declared_mime_type or "image/png"},
                    "provenance": provenance,
                    "license": license,
                    "tags": tags or ["generated"],
                }
            },
        }

    def generate_asset(self, store_root, provider, request, asset_id, label=None, raise_on_error=True):
        self.last_generate_asset = {"provider": provider, "request": request, "asset_id": asset_id}
        return {
            "ok": True,
            "diagnostics": [],
            "asset": {
                "record": {
                    "id": asset_id,
                    "label": label or asset_id,
                    "kind": "raster_image",
                    "status": "ready",
                    "source": {"kind": "generated", "request_id": request.get("request_id"), "model": provider},
                    "media": {"mime_type": "image/png"},
                    "provenance": {"created_by": provider, "source_label": f"generated:{provider}"},
                    "license": {"name": "stub_generated", "allow_export": True},
                    "tags": ["generated"],
                },
                "provider": {"id": provider, "metadata": {}},
            },
        }

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
        # The critic now always requests a PNG (judge on pixels); return valid PNG
        # magic bytes for png and SVG otherwise so the bundle validates.
        if export_format == "png":
            mime_type, raw = "image/png", b"\x89PNG\r\n\x1a\nfake"
        else:
            mime_type, raw = "image/svg+xml", b"<svg></svg>"
        return {
            "diagnostics": [],
            "export": {
                "artifacts": [
                    {
                        "format": export_format,
                        "mime_type": mime_type,
                        "page_id": "page_test",
                        "bytes": list(raw),
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
        self.compile_sources = []

    def compile_dsl_into_scene(self, scene, source: str, dsl_session=None):
        self.compile_calls += 1
        self.compile_sources.append(source)
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


class ScriptedDirector:
    def __init__(self, decisions: list[AgentDirectorDecision]) -> None:
        self.decisions = decisions
        self.calls = []

    def decide(self, *, full_context: dict):
        self.calls.append(full_context)
        index = min(len(self.calls) - 1, len(self.decisions) - 1)
        return self.decisions[index]


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


def test_subagents_declare_empty_tools_to_stay_under_strict_tool_cap():
    # Regression guard for the deepagent-loop blocker: a subagent with NO `tools`
    # key inherits the coordinator's full tool surface, and the visual reviewer's
    # `response_format` forces Anthropic's strict provider strategy — together they
    # exceed Anthropic's 20 STRICT-tool cap ("Too many strict tools (33)"), which
    # killed every deepagent run. Each subagent must therefore declare an explicit
    # (empty) tool list so deepagents does NOT inherit the coordinator's tools.
    # Skills still load via the filesystem middleware, independent of `tools`.
    subagents = build_subagents("anthropic:claude-opus-4-6")
    for agent in subagents:
        assert "tools" in agent, f"{agent['name']} must declare tools explicitly"
        assert agent["tools"] == [], f"{agent['name']} must not inherit coordinator tools"


def test_coordinator_prompt_wires_the_imagery_decide_generate_place_chain():
    # The coordinator must actively drive the imagery chain (decide -> generate ->
    # place -> scrim) rather than leave it to chance — otherwise the loop only ever
    # produces typographic designs even when a brief warrants a hero image.
    prompt = COORDINATOR_SYSTEM_PROMPT
    # Decide first, defaulting to no image.
    assert "DECIDE IMAGERY" in prompt
    assert "knowledge/images/decide" in prompt
    # Generate, then place, are explicit coordinator-owned tool steps — now routed
    # through the single `asset` dispatcher (Group B consolidation).
    assert 'asset(action="generate_image"' in prompt
    assert 'asset(action="place"' in prompt
    # The author is handed the exact asset id and the placement/scrim idiom.
    assert "asset_id" in prompt
    assert "knowledge/images/placement" in prompt
    # Ordering invariant: decide before generate before place.
    assert prompt.index("DECIDE IMAGERY") < prompt.index('asset(action="generate_image"')
    assert prompt.index('asset(action="generate_image"') < prompt.index('asset(action="place"')


def test_author_prompt_defers_image_generation_to_the_coordinator():
    # The author has no tools (see the strict-tool-cap fix) and must not be told to
    # call the image tool; it composes the frame around the coordinator's asset_id.
    prompt = DSL_AUTHOR_SYSTEM_PROMPT
    assert 'never call the image tool' in prompt
    assert 'asset(action="generate_image")' in prompt
    assert "coordinator" in prompt
    assert "scrim" in prompt


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
    # 17 tools after the Group A/B/C consolidation: the asset/inspect dispatchers
    # replace the 4 generate/place + 6 summarize/query singletons, and
    # persist_trace_event is dropped.
    assert tool_names == {
        "load_knowledge",
        "compile_dsl_block",
        "apply_operations",
        "apply_structured_edit",
        "asset",
        "validate_binding_set",
        "derive_instance_preview",
        "preflight_design",
        "export_preview",
        "export_preview_bundle",
        "get_latest_preview_for_critique",
        "submit_visual_critique",
        "recommend_edit_surface",
        "create_repair_request",
        "record_gap",
        "inspect",
        "finalize_run",
    }
    assert len(calls["kwargs"]["tools"]) == 17
    # The folded singletons must NOT be in the model's tool surface anymore.
    assert not (
        {
            "generate_image",
            "generate_qr",
            "place_asset_in_node",
            "place_asset_in_slot",
            "summarize_scene",
            "summarize_page",
            "summarize_slots",
            "summarize_node_tree",
            "query_geometry",
            "query_slot_bindings",
            "persist_trace_event",
        }
        & tool_names
    )
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


def test_grammar_and_text_refs_are_pinned_for_authoring():
    # Regression for the va()/divider hallucinations: a prompt whose words do NOT
    # overlap the grammar/text references (no "valign", "grammar", "node kind")
    # must still retrieve them. They are pinned regardless of ranker score, even at
    # the default limit, so the author always has the valid node kinds and the
    # "there is no valign" rule in context.
    repo_root = Path(__file__).resolve().parents[3]

    snippets = read_task_knowledge(
        repo_root,
        "Create a patient appointment card with a clear headline and a Book a Demo button",
        limit=8,
    )
    paths = {snippet.path for snippet in snippets}

    assert (
        "apps/agent_runtime/knowledge_docs/knowledge/lumen-dsl/grammar.md" in paths
    )
    assert "apps/agent_runtime/knowledge_docs/knowledge/lumen-dsl/text.md" in paths


def test_block_catalog_is_pinned_and_delivered_full():
    # P0.2: the vetted block catalog must be pinned for any authoring task AND
    # delivered in FULL (not windowed to a best_excerpt) — a truncated block
    # example teaches the author broken/partial syntax.
    repo_root = Path(__file__).resolve().parents[3]

    snippets = read_task_knowledge(
        repo_root,
        "Create a patient appointment card with a clear headline and a Book a Demo button",
    )
    by_path = {snippet.path: snippet for snippet in snippets}
    base = "apps/agent_runtime/knowledge_docs/knowledge/design/blocks/"

    for name in ("README.md", "patterns.md", "layout.md", "actions.md", "data-display.md"):
        rel = base + name
        assert rel in by_path, f"block doc {name} not pinned for authoring"
        on_disk = (repo_root / rel).read_text(encoding="utf-8")
        assert by_path[rel].excerpt == on_disk, (
            f"block doc {name} was windowed/truncated, not delivered in full"
        )


def test_images_decide_is_pinned_and_delivered_full():
    # Step 4 (A0.1): the imagery DECIDE guardrail must be pinned for any authoring
    # task AND delivered in FULL — the author always decides whether a surface needs
    # imagery (and which mechanism) before composing.
    repo_root = Path(__file__).resolve().parents[3]

    snippets = read_task_knowledge(
        repo_root,
        "Create a patient appointment card with a clear headline and a Book a Demo button",
    )
    by_path = {snippet.path: snippet for snippet in snippets}

    assert IMAGES_DECIDE_PATH in by_path, "images/decide not pinned for authoring"
    on_disk = (repo_root / IMAGES_DECIDE_PATH).read_text(encoding="utf-8")
    assert by_path[IMAGES_DECIDE_PATH].excerpt == on_disk, (
        "images/decide was windowed/truncated, not delivered in full"
    )


def test_directives_ref_grammar_is_pinned_for_seeded_turns(
    tmp_path: Path, monkeypatch
):
    # Agent-improvement backlog: a SEEDED turn edits an existing document, so
    # the modify/ref grammar (`#page:` form, directives-take-node-ids-only)
    # must always be loaded — run_8cbeae790f07 burned every iteration on the
    # `#page_a4`-vs-`#page:page_a4` trap with directives.md never in context.
    repo_root = Path(__file__).resolve().parents[3]

    # The loader honors explicit extra mandatory pins even when the prompt
    # shares no words with the doc.
    snippets = read_task_knowledge(
        repo_root,
        "Change the greeting copy to Hello",
        extra_mandatory_paths=[DIRECTIVES_PATH],
    )
    assert DIRECTIVES_PATH in {snippet.path for snippet in snippets}

    # And the tools wire the pin automatically for seeded scenes.
    monkeypatch.setattr("lumen_deepagent.tools.CoreClient", FakeCoreClient)
    config = AgentRuntimeConfig(
        repo_root=repo_root,
        model="anthropic:claude-opus-4-6",
        max_iterations=1,
        preview_format="svg",
        trace_dir=tmp_path / ".lumen-runs",
    )
    seeded_tools = LumenDesignTools(
        config,
        "Change the greeting copy to Hello",
        initial_scene={
            "meta": {"id": "doc_live", "title": "Saved doc"},
            "pages": {"page_a4": {"id": "page_a4", "children": []}},
            "nodes": {},
            "slots": {},
            "assets": {},
        },
    )
    json.loads(seeded_tools.load_knowledge("Change the greeting copy to Hello"))
    assert DIRECTIVES_PATH in {
        snippet["path"] for snippet in seeded_tools.loaded_knowledge
    }


def test_imagery_prompt_and_placement_docs_pin_by_relevance():
    # decide is always pinned (cheap guardrail); the prompt-craft + placement/scrim
    # docs pin only for image-bearing tasks, so a pure-typographic card is not bloated.
    generic = mandatory_task_paths("a patient appointment card with a headline and a button")
    assert IMAGES_DECIDE_PATH in generic
    assert IMAGES_PROMPTS_PATH not in generic
    assert IMAGES_PLACEMENT_PATH not in generic
    assert IMAGES_ICONS_PATH not in generic

    imagery = mandatory_task_paths("a social ad with a hero photo and headline overlay")
    assert IMAGES_DECIDE_PATH in imagery
    assert IMAGES_PROMPTS_PATH in imagery
    assert IMAGES_PLACEMENT_PATH in imagery

    # Step 8: an icon-bearing brief pins the icon-library reference.
    icon_task = mandatory_task_paths("a four-pillar deck slide with an icon row")
    assert IMAGES_ICONS_PATH in icon_task


def test_assumes_frontmatter_resolves_transitively():
    # Brilliant-style `assumes:` resolution: selecting images/placement (mandatory for
    # an imagery task) must transitively pull its declared prerequisites —
    # assets/asset-placement and images/decide — into the loaded context, even though
    # neither is a mandatory pin nor a required-category pick.
    repo_root = Path(__file__).resolve().parents[3]
    snippets = read_task_knowledge(
        repo_root,
        "a social ad with a hero photo and a headline overlay",
        limit=12,
    )
    by_path = {snippet.path: snippet for snippet in snippets}
    asset_placement = f"{KNOWLEDGE_DOCS_ROOT}/knowledge/assets/asset-placement.md"

    assert IMAGES_PLACEMENT_PATH in by_path
    assert IMAGES_DECIDE_PATH in by_path
    assert asset_placement in by_path, "images/placement's assumes: dep was not pulled in"
    # assets/asset-placement is neither mandatory nor a required-category pick, so the
    # only way it enters is the assumes resolver (which runs before the score fill).
    assert by_path[asset_placement].selected_reason == "assumes_dependency"


def test_knowledge_assumes_keys_resolve_to_real_primary_docs():
    # Lint guard (scoped Tier-4 idea): every `assumes:` key in every knowledge doc must
    # resolve to a real PRIMARY doc, so the cross-reference graph can't silently rot.
    repo_root = Path(__file__).resolve().parents[3]
    knowledge_root = repo_root / KNOWLEDGE_DOCS_ROOT / "knowledge"
    primary = set(PRIMARY_KNOWLEDGE_PATHS)
    edges = 0
    for md in sorted(knowledge_root.rglob("*.md")):
        for key in assumes_keys(md.read_text(encoding="utf-8")):
            edges += 1
            dep_path = assumes_path(key)
            assert (repo_root / dep_path).exists(), (
                f"{md.name}: assumes key '{key}' -> missing file {dep_path}"
            )
            assert dep_path in primary, (
                f"{md.name}: assumes key '{key}' -> {dep_path} is not a PRIMARY doc"
            )
    assert edges >= 4, "expected the Tier 0-1 assumes: edges to be present"


def test_parse_frontmatter_is_a_noop_without_a_block():
    # Docs without frontmatter (the common case) must be returned untouched, so the
    # loader's full-delivery `excerpt == on_disk` invariant holds for them.
    body = "# Heading\n\nNo frontmatter here."
    meta, rest = parse_frontmatter(body)
    assert meta == {}
    assert rest == body

    meta2, rest2 = parse_frontmatter("---\nassumes: images/decide\n---\n# Title\nx")
    assert meta2["assumes"] == "images/decide"
    assert rest2 == "# Title\nx"


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


def test_imagery_fixture_briefs_cover_decisions_and_match_sidecar():
    # Imagery-quality eval set: the 16 imagery briefs exist in fixture_prompts.json,
    # the sidecar covers each with a valid decision, and ~a third are NONE-correct
    # (the DECIDE guardrail — a good agent declines imagery on data/type surfaces).
    repo_root = Path(__file__).resolve().parents[3]
    base = repo_root / "apps/agent_runtime/evaluation"
    fixtures = json.loads((base / "fixture_prompts.json").read_text(encoding="utf-8"))
    by_id = {fixture["id"]: fixture for fixture in fixtures}
    sidecar = json.loads((base / "imagery_fixtures" / "briefs.json").read_text(encoding="utf-8"))

    assert len(sidecar) == 16
    for brief_id, meta in sidecar.items():
        assert brief_id in by_id, f"imagery brief {brief_id} missing from fixture_prompts.json"
        assert meta["expected_decision"] in {"photo", "icon", "none"}
        assert meta["role"] and meta["risks"]
        # The prompt must NOT pre-decide the imagery for the agent (we test the DECIDE).
        prompt = by_id[brief_id]["prompt"].lower()
        assert "generate_image" not in prompt and "use a scrim" not in prompt

    decisions = Counter(meta["expected_decision"] for meta in sidecar.values())
    assert decisions["photo"] == 6 and decisions["icon"] == 4 and decisions["none"] == 6
    # The same GTM/SF theme appears with three different correct answers.
    assert {"gtm_conf_poster_photo", "gtm_conf_social_none", "gtm_conf_deck_band"} <= set(sidecar)
    assert sidecar["gtm_conf_poster_photo"]["expected_decision"] == "photo"
    assert sidecar["gtm_conf_social_none"]["expected_decision"] == "none"


def _poster_scene(*, asset_model="google/gemini-3-pro-image", with_scrim=True, asset_status="ready"):
    nodes = {
        "img": {
            "kind": {"kind": "image", "asset_id": "hero"},
            "asset_placement": {"fit": "cover", "focal_point": {"x": 0.5, "y": 0.4}},
            "computed": {"layout_bounds": {"x": 0, "y": 0, "width": 1080, "height": 1920}},
        },
        "headline": {
            "kind": {"kind": "text"},
            "computed": {"layout_bounds": {"x": 80, "y": 1400, "width": 920, "height": 300}},
        },
    }
    if with_scrim:
        nodes["scrim"] = {
            "kind": {"kind": "rect"},
            "opacity_token": "opacity.scrim",
            "computed": {"layout_bounds": {"x": 0, "y": 1100, "width": 1080, "height": 820}},
        }
    return {
        "pages": {"p": {"size": {"width": 1080, "height": 1920}}},
        "assets": {
            "hero": {
                "status": asset_status,
                "kind": "raster_image",
                "source": {"kind": "generated", "model": asset_model},
                "raster": {"pixel_width": 1080, "pixel_height": 1920},
            }
        },
        "nodes": nodes,
    }


def test_imagery_checks_accept_a_clean_scrimmed_poster():
    from lumen_deepagent.imagery_checks import score_scene

    result = score_scene(_poster_scene(), expected_decision="photo")
    assert result["accept"] is True
    assert result["gate_failed"] is False
    d = result["dimensions"]
    assert d["placeholder_real"]["score"] == 3
    assert d["decision"]["score"] == 3
    assert d["legibility"]["score"] == 3
    assert d["hero_count"]["score"] == 3


def test_imagery_checks_gate_on_placeholder_text_over_image_and_gratuitous():
    from lumen_deepagent.imagery_checks import score_scene

    # A solid-color stub placeholder shipped as final → hard gate.
    stub = score_scene(_poster_scene(asset_model="stub-image-v0"), expected_decision="photo")
    assert stub["accept"] is False and stub["dimensions"]["placeholder_real"]["gate"] is True

    # Text over a busy image with no covering scrim → legibility gate.
    no_scrim = score_scene(_poster_scene(with_scrim=False), expected_decision="photo")
    assert no_scrim["accept"] is False and no_scrim["dimensions"]["legibility"]["gate"] is True

    # The DECIDE guardrail: a photo placed on a NONE-correct brief → decision gate.
    gratuitous = score_scene(_poster_scene(), expected_decision="none")
    assert gratuitous["accept"] is False and gratuitous["dimensions"]["decision"]["gate"] is True

    # NONE-correct brief with a clean typographic design (no image) → accepts.
    type_only = {"pages": {"p": {"size": {"width": 1080, "height": 1080}}},
                 "assets": {},
                 "nodes": {"h": {"kind": {"kind": "text"},
                                 "computed": {"layout_bounds": {"x": 80, "y": 80, "width": 920, "height": 400}}}}}
    clean = score_scene(type_only, expected_decision="none")
    assert clean["accept"] is True and clean["dimensions"]["decision"]["score"] == 3


class _FakeJudgeModel:
    """A stand-in for the structured-output LLM judge: .invoke returns a canned verdict
    and records that a vision call happened (so we can assert when the judge is skipped)."""

    def __init__(self, verdict):
        self.verdict = verdict
        self.calls = 0

    def invoke(self, messages):
        self.calls += 1
        return self.verdict


def _perfect_verdict():
    from lumen_deepagent.imagery_judge import ImageryJudgeVerdict

    return ImageryJudgeVerdict(
        relevance=3, placeholder_real=3, aspect_fit=3, placement=3, legibility=3,
        resolution_dpi=3, no_in_image_text=3, theme_coherence=3, reasoning="clean",
    )


def test_imagery_judge_ships_a_clean_scrimmed_poster_with_a_good_verdict():
    from lumen_deepagent.imagery_judge import judge_imagery

    model = _FakeJudgeModel(_perfect_verdict())
    result = judge_imagery(
        _poster_scene(),
        b"\x89PNG fake-bytes",
        {"id": "GTM-01", "expected_decision": "photo", "role": "full_bleed_hero", "risks": []},
        model=model,
    )
    assert model.calls == 1  # an image is present → the judge runs
    assert result["judge_ran"] is True
    assert result["accept"] is True and result["tier"] == "ship"
    assert result["per_axis"]["theme_coherence"]["final"] == 3
    assert result["weighted_mean"] >= 2.3


def test_imagery_judge_skips_the_vision_call_on_a_correct_typographic_none_design():
    from lumen_deepagent.imagery_judge import judge_imagery

    type_only = {
        "pages": {"p": {"size": {"width": 1080, "height": 1080}}},
        "assets": {},
        "nodes": {"h": {"kind": {"kind": "text"},
                        "computed": {"layout_bounds": {"x": 80, "y": 80, "width": 920, "height": 400}}}},
    }
    model = _FakeJudgeModel(_perfect_verdict())
    result = judge_imagery(type_only, None, {"id": "NO-01", "expected_decision": "none"}, model=model)
    # No image and none expected → deterministic accept, no paid vision call.
    assert model.calls == 0 and result["judge_ran"] is False
    assert result["accept"] is True and result["tier"] == "ship"
    assert result["per_axis"]["relevance"]["final"] == 3


def test_imagery_judge_det_gate_caps_a_perfect_verdict_to_redo():
    from lumen_deepagent.imagery_judge import judge_imagery

    # A perfect verdict cannot rescue a design whose text is unscrimmed over the image:
    # the DET legibility gate caps the axis at 1 and forces a redo.
    model = _FakeJudgeModel(_perfect_verdict())
    result = judge_imagery(
        _poster_scene(with_scrim=False),
        b"\x89PNG",
        {"id": "GTM-01", "expected_decision": "photo"},
        model=model,
    )
    assert result["gate_failed"] is True
    assert result["per_axis"]["legibility"]["final"] == 1
    assert result["accept"] is False and result["tier"] == "redo"


def test_imagery_judge_final_is_min_of_det_cap_and_judge():
    from lumen_deepagent.imagery_judge import ImageryJudgeVerdict, judge_imagery

    # DET passes every gate (score 3), but the judge dislikes the theme (1) and the
    # composition/placement (2) → final theme is the judge's 1 → redo.
    verdict = ImageryJudgeVerdict(
        relevance=3, placeholder_real=3, aspect_fit=3, placement=2, legibility=3,
        resolution_dpi=2, no_in_image_text=3, theme_coherence=1, reasoning="off-brand stock cliché",
    )
    result = judge_imagery(
        _poster_scene(),
        b"\x89PNG",
        {"id": "GTM-01", "expected_decision": "photo"},
        model=_FakeJudgeModel(verdict),
    )
    assert result["per_axis"]["theme_coherence"]["final"] == 1  # judge below DET cap
    assert result["per_axis"]["placement"]["final"] == 2        # min(2 judge, 3 det)
    assert result["accept"] is False and result["tier"] == "redo"


def _load_imagery_runner():
    import importlib.util

    path = Path(__file__).resolve().parents[1] / "evaluation" / "run_imagery_evals.py"
    spec = importlib.util.spec_from_file_location("run_imagery_evals", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _write_synthetic_run_dir(run_dir: Path, scene: dict) -> Path:
    run_dir.mkdir(parents=True, exist_ok=True)
    (run_dir / "final_scene.json").write_text(json.dumps(scene), encoding="utf-8")
    png = run_dir / "iterations" / "001" / "preview.png"
    png.parent.mkdir(parents=True, exist_ok=True)
    png.write_bytes(b"\x89PNG synthetic")
    (run_dir / "final.json").write_text(
        json.dumps({"run_id": "run_synthetic", "status": "accepted", "preview_paths": [str(png)]}),
        encoding="utf-8",
    )
    return run_dir


def test_imagery_runner_merge_briefs_joins_sidecar_and_prompt():
    runner = _load_imagery_runner()
    merged = runner.merge_briefs(runner.DEFAULT_BRIEFS, runner.DEFAULT_PROMPTS)
    assert len(merged) == 16
    by_id = {b["id"]: b for b in merged}
    gtm = by_id["gtm_conf_poster_photo"]
    assert gtm["expected_decision"] == "photo" and gtm["prompt"] and gtm["risks"]
    decisions = Counter(b["expected_decision"] for b in merged)
    assert decisions == Counter({"photo": 6, "none": 6, "icon": 4})


def test_imagery_runner_scores_and_captures_a_run_dir(tmp_path: Path):
    runner = _load_imagery_runner()
    run_dir = _write_synthetic_run_dir(tmp_path / "run", _poster_scene())
    brief = {"id": "GTM-01", "artifact": "event_poster_9x16", "prompt": "p",
             "expected_decision": "photo", "role": "full_bleed_hero", "risks": []}

    scores = runner.score_run_dir(run_dir, brief, model=_FakeJudgeModel(_perfect_verdict()))
    assert scores["tier"] == "ship" and scores["accept"] is True
    assert scores["run_id"] == "run_synthetic"

    capture = runner.write_capture(tmp_path / "out", brief, scores, tag="baseline-pre-step9", model="fake-model")
    for name in ("brief.json", "scores.json", "asset_provenance.json", "run_meta.json", "render.png"):
        assert (capture / name).exists(), name
    prov = json.loads((capture / "asset_provenance.json").read_text())
    assert prov["asset_id"] == "hero" and prov["source_kind"] == "generated"


def test_imagery_runner_summarize_aggregates_accept_and_tiers():
    runner = _load_imagery_runner()
    results = [
        {"brief": {"expected_decision": "photo"}, "scores": {"tier": "ship", "accept": True}},
        {"brief": {"expected_decision": "photo"}, "scores": {"tier": "redo", "accept": False}},
        {"brief": {"expected_decision": "none"}, "scores": {"tier": "ship", "accept": True}},
        {"brief": {"expected_decision": "icon"}, "scores": None},  # unscored — ignored
    ]
    summary = runner.summarize(results)
    assert summary["briefs_scored"] == 3
    assert summary["accept_rate"] == round(2 / 3, 3)
    assert summary["tiers"]["ship"] == 2 and summary["tiers"]["redo"] == 1
    assert summary["by_decision"]["photo"] == {"n": 2, "accept": 1}


def test_imagery_runner_diff_tags_reports_axis_and_tier_transition(tmp_path: Path):
    runner = _load_imagery_runner()
    brief_dir = tmp_path / "GTM-01"
    (brief_dir / "a").mkdir(parents=True)
    (brief_dir / "b").mkdir(parents=True)
    (brief_dir / "a" / "scores.json").write_text(
        json.dumps({"tier": "ship", "weighted_mean": 2.6, "per_axis": {"legibility": {"final": 3}}})
    )
    (brief_dir / "b" / "scores.json").write_text(
        json.dumps({"tier": "redo", "weighted_mean": 1.8, "per_axis": {"legibility": {"final": 1}}})
    )
    diff = runner.diff_tags(brief_dir, "a", "b")
    assert diff["tier"] == {"from": "ship", "to": "redo", "regressed_from_ship": True}
    assert diff["axis_delta"]["legibility"] == -2


def test_tools_seed_scene_is_used_instead_of_new_scene(tmp_path: Path, monkeypatch):
    # Phase 0a: an initial_scene seeds the working scene (deep-copied), replaces
    # the new_scene call, and the seeding is recorded in the run trace.
    monkeypatch.setattr("lumen_deepagent.tools.CoreClient", FakeCoreClient)
    seed = {
        "meta": {"id": "doc_live", "title": "Saved doc"},
        "pages": {"hero_poster": {"id": "hero_poster", "children": ["headline"]}},
        "nodes": {
            "headline": {
                "id": "headline",
                "kind": {"kind": "text", "content": "Old copy"},
                "children": [],
            }
        },
        "slots": {},
        "assets": {},
    }
    config = runtime_config(tmp_path)
    tools = LumenDesignTools(config, "Edit the headline", initial_scene=seed)

    assert tools.seeded_from_initial_scene is True
    assert tools.scene["meta"]["id"] == "doc_live"
    assert "headline" in tools.scene["nodes"]
    assert tools.scene_update_sources[0] == "initial_scene_seed"
    # Deep copy: caller-side mutation must not leak into the running scene.
    seed["nodes"]["headline"]["kind"]["content"] = "Mutated by caller"
    assert tools.scene["nodes"]["headline"]["kind"]["content"] == "Old copy"
    input_payload = json.loads(
        (config.trace_dir / tools.run_id / "input.json").read_text(encoding="utf-8")
    )
    assert input_payload["seeded_from_initial_scene"] is True


def test_tools_without_seed_records_unseeded_run(tmp_path: Path, monkeypatch):
    monkeypatch.setattr("lumen_deepagent.tools.CoreClient", FakeCoreClient)
    config = runtime_config(tmp_path)
    tools = LumenDesignTools(config, "Create a square ad")

    assert tools.seeded_from_initial_scene is False
    assert tools.scene_update_sources == []
    input_payload = json.loads(
        (config.trace_dir / tools.run_id / "input.json").read_text(encoding="utf-8")
    )
    assert input_payload["seeded_from_initial_scene"] is False


def test_finalize_run_persists_the_full_final_scene_for_offline_scoring(tmp_path: Path, monkeypatch):
    # The imagery eval runner reads final_scene.json (the FULL scene, not just the
    # summary) to deterministically score imagery without re-running the agent.
    monkeypatch.setattr("lumen_deepagent.tools.CoreClient", FakeCoreClient)
    config = runtime_config(tmp_path)
    tools = LumenDesignTools(config, "Create a square ad")
    tools.compile_dsl_block("page page_test")
    tools.finalize_run("accepted", "accepted", "Accepted.")

    final_scene_path = config.trace_dir / tools.run_id / "final_scene.json"
    assert final_scene_path.exists()
    scene = json.loads(final_scene_path.read_text(encoding="utf-8"))
    assert "nodes" in scene and "pages" in scene  # the full scene, round-trippable


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


def test_director_author_and_reviewer_receive_full_context(tmp_path: Path, monkeypatch):
    monkeypatch.setattr("lumen_deepagent.tools.CoreClient", FakeCoreClient)
    tools = LumenDesignTools(
        runtime_config(tmp_path),
        'Create a square ad\n\nEditor context JSON:\n{"conversation_context":{"messages":[{"role":"user","content":"previous ask"}]}}',
    )
    author = ScriptedAuthor(["page page_test"])
    reviewer = ScriptedReviewer(
        [VisualCritique(accepted=True, summary="Preview is acceptable.")]
    )
    director = ScriptedDirector(
        [
            AgentDirectorDecision(
                action_mode=AgentActionMode.new_artifact,
                rationale="Create a fresh artifact.",
                instructions_to_author="Create the full page.",
            )
        ]
    )

    result = LumenQualityLoop(tools, author, reviewer, director=director).run(
        "Create a square ad"
    )

    assert result["status"] == "accepted"
    director_context = director.calls[0]
    # Curated/windowed shape (P1): a compact situation report, never the raw
    # scene / trace events / base64 previews that previously self-nested.
    for key in (
        "scene_summary",
        "scene_subtree",
        "diagnostics",
        "attempt_history",
        "preview_summary",
    ):
        assert key in director_context, key
    for banned in ("current_scene", "trace_events", "iteration_files", "preview_activity"):
        assert banned not in director_context, banned
    assert director_context["conversation_context"]["messages"][0]["content"] == "previous ask"

    author_request = author.requests[0]
    assert author_request.director_decision is not None
    assert author_request.director_decision.action_mode == AgentActionMode.new_artifact
    # Author and director share the same curated context object.
    assert author_request.full_context["scene_summary"] == director_context["scene_summary"]
    assert author_request.full_context["loaded_knowledge"] == director_context["loaded_knowledge"]

    reviewer_context = reviewer.calls[0]["full_context"]
    assert "preview_activity" not in reviewer_context
    assert "scene_summary" in reviewer_context
    # The reviewer still gets the real preview artifacts via its own kwarg.
    assert reviewer.calls[0]["preview_payload"]["artifacts"]

    # The defining P1 invariant: nothing context-shaped is ever written to the
    # trace, so the trace can never be re-inflated into a later prompt.
    trace_text = (
        (tools.config.trace_dir / tools.run_id / "trace.jsonl").read_text(
            encoding="utf-8"
        )
    )
    assert '"full_context":' not in trace_text
    assert '"preview_activity":' not in trace_text


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


def test_classifier_prioritizes_blocking_text_error_over_brand_warning():
    diagnostics = [
        {
            "severity": "warning",
            "code": "LUMB0613",
            "message": "font asset brand is not marked embeddable for export",
        },
        {
            "severity": "error",
            "code": "LUMV0903",
            "message": "text node subhead exceeds available height",
            "target_node_id": "subhead",
        },
    ]

    classification = classify_diagnostics(
        diagnostics,
        {"node_id": "subhead"},
        scene=layout_cluster_scene(),
    )

    assert classification.repair_class == RepairClass.targeted_node
    assert classification.reason == "single_text_fit_target"


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


def test_slot_subject_lumv0800_routes_to_slot_fixture_not_cluster():
    # A slot-SUBJECT LUMV0800 ("required slot needs a fixture") must route to a
    # slot-fixture repair (which permits #slot: edits), NOT the layout-cluster gate
    # (which bans #slot: refs). The node-subject LUMV0800 (artboard bounds) stays
    # layout_cluster — see test_lumv0800_routes_to_layout_cluster.
    diagnostics = [
        {
            "severity": "error",
            "code": "LUMV0800",
            "message": "required slot campaign.headline needs a placeholder or validation fixture",
            "target_slot_id": "slot_campaign_headline",
            "target_slot_key": "campaign.headline",
        }
    ]

    classification = classify_diagnostics(
        diagnostics,
        {"slot_key": "campaign.headline"},
        scene=layout_cluster_scene(),
    )

    assert classification.repair_class == RepairClass.slot_fixture
    assert classification.allowed_edit_surface.value == "structured_ops"
    assert "set_slot_worst_case" in classification.permissions


def test_slot_subject_lumv0801_binding_routes_to_slot_fixture():
    diagnostics = [
        {
            "severity": "error",
            "code": "LUMV0801",
            "message": "slot offer.primary_message binds missing node body_copy",
            "target_slot_id": "slot_offer_primary_message",
            "target_slot_key": "offer.primary_message",
        }
    ]

    classification = classify_diagnostics(
        diagnostics,
        {"slot_key": "offer.primary_message"},
        scene=layout_cluster_scene(),
    )

    assert classification.repair_class == RepairClass.slot_fixture


def test_visual_balance_critique_routes_to_layout_cluster():
    critique = VisualCritique(
        accepted=False,
        summary="The composition has a large dead zone.",
        issues=[
            VisualIssue(
                severity="error",
                category=CritiqueCategory.visual_balance,
                target=VisualTarget(page_id="page_a4", node_id="headline"),
                message="Dead space makes the page feel unfinished.",
                suggested_repair="Rebuild the affected artboard layout.",
            )
        ],
        repair_instruction="Use a structural layout repair, not a tiny node patch.",
    )

    classification = classify_visual_critique(
        critique,
        {"page_id": "page_a4", "node_id": "headline"},
        layout_cluster_scene(),
    )

    assert classification.repair_class == RepairClass.layout_cluster
    assert classification.reason == "visual_critique_requires_structural_layout_repair"


def test_recompose_recipe_triggers_only_on_dead_band_categories():
    # P1.5#2a: a visual critique flagging visual_balance/spacing hands the
    # rebuild the verbatim poster idiom; anything else does not.
    for category in ("visual_balance", "spacing"):
        feedback = {
            "kind": "visual",
            "feedback": {"issues": [{"category": category, "message": "dead band"}]},
        }
        assert recompose_recipe_for_feedback(feedback) == POSTER_RECOMPOSE_RECIPE
    # Unrelated category, non-visual kind, and None all yield no recipe.
    assert (
        recompose_recipe_for_feedback(
            {"kind": "visual", "feedback": {"issues": [{"category": "typography"}]}}
        )
        is None
    )
    assert recompose_recipe_for_feedback({"kind": "preflight", "feedback": {}}) is None
    assert recompose_recipe_for_feedback(None) is None


def test_imagery_critique_routes_to_asset_tool_repair():
    # Step 9: a pure imagery-quality critique must be repaired as an ASSET (regenerate /
    # recrop / scrim / replace / remove) on the asset-tool surface — never as a layout
    # patch. (asset_use / contrast / clipping etc. keep their existing routing.)
    critique = VisualCritique(
        accepted=False,
        summary="The hero photo is a generic stock cliché and the headline is illegible.",
        issues=[
            VisualIssue(
                severity="error",
                category=CritiqueCategory.imagery,
                target=VisualTarget(page_id="page_hero", node_id="hero_img"),
                message="Gratuitous stock-feel photo; headline has no scrim.",
                suggested_repair="Regenerate a relevant hero and add a covering scrim.",
            )
        ],
        repair_instruction="Fix the image, not the layout.",
    )

    classification = classify_visual_critique(
        critique,
        {"page_id": "page_hero", "node_id": "hero_img"},
        {},
    )

    assert classification.repair_class == RepairClass.asset_tool
    assert classification.allowed_edit_surface == EditSurfaceRecommendation.asset_tool
    assert classification.reason == "imagery_quality_requires_asset_repair"
    assert "regenerate_asset" in classification.permissions


def test_imagery_critique_with_structural_failure_defers_to_layout_repair():
    # If a critique carries BOTH an imagery defect AND a structural layout failure, the
    # geometry repair wins this iteration (the imagery axis is revisited next).
    critique = VisualCritique(
        accepted=False,
        summary="Dead band above the footer, and the hero photo is off-crop.",
        issues=[
            VisualIssue(
                severity="error",
                category=CritiqueCategory.visual_balance,
                target=VisualTarget(page_id="page_a4", node_id="main"),
                message="Large empty band above the footer.",
                suggested_repair="Recompose with the poster idiom.",
            ),
            VisualIssue(
                severity="warning",
                category=CritiqueCategory.imagery,
                target=VisualTarget(page_id="page_a4", node_id="hero_img"),
                message="Hero crop cuts off the subject.",
                suggested_repair="Recrop via focal point.",
            ),
        ],
        repair_instruction="Fix the dead band first.",
    )

    classification = classify_visual_critique(
        critique,
        {"page_id": "page_a4", "node_id": "main"},
        layout_cluster_scene(),
    )

    assert classification.repair_class == RepairClass.layout_cluster


def test_imagery_recipe_triggers_only_on_imagery_categories():
    # Step 9 mirror of the recompose-recipe trigger: a visual critique flagging the
    # `imagery` category hands the rebuild the verbatim imagery-repair recipe.
    feedback = {
        "kind": "visual",
        "feedback": {"issues": [{"category": "imagery", "message": "cliché hero"}]},
    }
    assert imagery_recipe_for_feedback(feedback) == IMAGERY_REPAIR_RECIPE
    # A structural layout co-failure suppresses the imagery recipe (layout fixed first).
    mixed = {
        "kind": "visual",
        "feedback": {
            "issues": [
                {"category": "imagery", "message": "off-crop"},
                {"category": "visual_balance", "message": "dead band"},
            ]
        },
    }
    assert imagery_recipe_for_feedback(mixed) is None
    # Unrelated category, non-visual kind, and None all yield no recipe.
    assert (
        imagery_recipe_for_feedback(
            {"kind": "visual", "feedback": {"issues": [{"category": "typography"}]}}
        )
        is None
    )
    assert imagery_recipe_for_feedback({"kind": "preflight", "feedback": {}}) is None
    assert imagery_recipe_for_feedback(None) is None


def test_reviewer_prompt_carries_the_shared_imagery_rubric():
    # Step 9 / Phase-2 pairing: the in-loop reviewer applies the SAME imagery rubric the
    # offline judge uses, framed as a reject gate with category `imagery`.
    prompt = VISUAL_REVIEWER_SYSTEM_PROMPT
    assert "J. IMAGERY" in prompt
    assert "category" in prompt and "imagery" in prompt
    # The shared rubric constant is spliced in verbatim (single source of truth).
    assert IMAGERY_RUBRIC in prompt
    assert "LEGIBILITY-OVER-IMAGE" in prompt
    assert "RELEVANCE / DECIDE" in prompt


def test_heuristic_director_hands_poster_recipe_for_visual_balance():
    decision = HeuristicAgentDirector().decide(
        full_context={
            "latest_feedback": {
                "kind": "visual",
                "feedback": {
                    "issues": [
                        {"category": "visual_balance", "message": "two dead bands"}
                    ]
                },
            }
        }
    )
    assert decision.action_mode == AgentActionMode.replace_artboard_subtree
    assert POSTER_RECOMPOSE_RECIPE in decision.instructions_to_author


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


def test_mixed_top_level_overflow_uses_root_cluster_not_target_parent():
    scene = layout_cluster_scene()
    scene["nodes"]["footer"] = {
        "id": "footer",
        "kind": {"kind": "frame"},
        "children": [],
    }
    scene["nodes"]["artboard"]["children"] = ["card", "footer"]
    diagnostics = [
        {
            "severity": "error",
            "code": "LUMV0801",
            "message": "node card exceeds artboard bounds",
            "target_node_id": "card",
        },
        {
            "severity": "error",
            "code": "LUMV0801",
            "message": "node footer exceeds artboard bounds",
            "target_node_id": "footer",
        },
    ]

    classification = classify_diagnostics(
        diagnostics,
        {"page_id": "page_a4", "node_id": "headline", "parent_node_id": "card"},
        scene=scene,
    )

    assert classification.repair_class == RepairClass.layout_cluster
    assert classification.cluster is not None
    assert classification.cluster.root_frame_id == "artboard"
    assert classification.cluster.parent_node_id is None
    allowed = layout_cluster_allowed_node_ids(
        classification.cluster.model_dump(mode="json")
    )
    assert {"artboard", "card", "footer", "headline"}.issubset(allowed)


def test_slot_fit_nodes_join_bounds_layout_cluster():
    scene = layout_cluster_scene()
    scene["nodes"].update(
        {
            "header": {
                "id": "header",
                "kind": {"kind": "autolayout"},
                "children": ["headline"],
            },
            "logo_mark": {
                "id": "logo_mark",
                "kind": {"kind": "frame"},
                "children": ["logo_plus"],
            },
            "logo_plus": {
                "id": "logo_plus",
                "kind": {"kind": "text", "content": "+"},
                "children": [],
            },
            "body_section": {
                "id": "body_section",
                "kind": {"kind": "autolayout"},
                "children": ["instruction"],
            },
            "benefit_section": {
                "id": "benefit_section",
                "kind": {"kind": "autolayout"},
                "children": ["benefit_copy", "stats_row"],
            },
            "stats_row": {
                "id": "stats_row",
                "kind": {"kind": "autolayout"},
                "children": ["stat_one", "stat_two", "stat_three"],
            },
            "stat_one": {
                "id": "stat_one",
                "kind": {"kind": "autolayout"},
                "children": ["stat_val_one"],
            },
            "stat_two": {
                "id": "stat_two",
                "kind": {"kind": "autolayout"},
                "children": ["stat_lab_two"],
            },
            "stat_three": {
                "id": "stat_three",
                "kind": {"kind": "autolayout"},
                "children": ["stat_val_three", "stat_lab_three"],
            },
            "cta_section": {
                "id": "cta_section",
                "kind": {"kind": "autolayout"},
                "children": ["cta_label"],
            },
            "instruction": {
                "id": "instruction",
                "kind": {"kind": "text", "content": "Instruction"},
                "children": [],
            },
            "benefit_copy": {
                "id": "benefit_copy",
                "kind": {"kind": "text", "content": "Benefit"},
                "children": [],
            },
            "stat_val_one": {
                "id": "stat_val_one",
                "kind": {"kind": "text", "content": "40%"},
                "children": [],
            },
            "stat_lab_two": {
                "id": "stat_lab_two",
                "kind": {"kind": "text", "content": "Patient Satisfaction"},
                "children": [],
            },
            "stat_val_three": {
                "id": "stat_val_three",
                "kind": {"kind": "text", "content": "3 min"},
                "children": [],
            },
            "stat_lab_three": {
                "id": "stat_lab_three",
                "kind": {"kind": "text", "content": "Avg Check-in"},
                "children": [],
            },
            "cta_label": {
                "id": "cta_label",
                "kind": {"kind": "text", "content": "Book a Demo"},
                "children": [],
            },
        }
    )
    scene["nodes"]["card"]["children"] = [
        "logo_mark",
        "header",
        "body_section",
        "benefit_section",
        "cta_section",
    ]
    scene["slots"] = {
        "slot_campaign_headline": {
            "id": "slot_campaign_headline",
            "key": "campaign.headline",
            "bound_nodes": ["headline"],
        },
        "slot_offer_primary_message": {
            "id": "slot_offer_primary_message",
            "key": "offer.primary_message",
            "bound_nodes": ["instruction"],
        },
        "slot_offer_secondary_message": {
            "id": "slot_offer_secondary_message",
            "key": "offer.secondary_message",
            "bound_nodes": ["benefit_copy"],
        },
        "slot_cta_primary": {
            "id": "slot_cta_primary",
            "key": "cta.primary",
            "bound_nodes": ["cta_label"],
        },
    }
    diagnostics = [
        {
            "severity": "warning",
            "code": "LUMV0509",
            "message": "text slot cta.primary has no fit-validation fixtures",
            "target_slot_id": "slot_cta_primary",
        },
        {
            "severity": "error",
            "code": "LUMV0800",
            "message": "node artboard exceeds exportable bounds for page page_a4",
            "target_node_id": "artboard",
        },
        {
            "severity": "warning",
            "code": "LUMV0801",
            "message": "node logo_plus exceeds parent bounds on page page_a4",
            "target_node_id": "logo_plus",
        },
        {
            "severity": "error",
            "code": "LUMV0801",
            "message": "node cta_section exceeds parent bounds on page page_a4",
            "target_node_id": "cta_section",
        },
        {
            "severity": "error",
            "code": "LUMV0902",
            "message": "non-wrapping text node stat_lab_three overflows horizontally",
            "target_node_id": "stat_lab_three",
        },
        {
            "severity": "error",
            "code": "LUMV0902",
            "message": "non-wrapping text node stat_lab_two overflows horizontally",
            "target_node_id": "stat_lab_two",
        },
        {
            "severity": "error",
            "code": "LUMV0902",
            "message": "non-wrapping text node stat_val_one overflows horizontally",
            "target_node_id": "stat_val_one",
        },
        {
            "severity": "error",
            "code": "LUMV0810",
            "message": "slot campaign.headline fixture overflows text node headline",
            "target_slot_id": "slot_campaign_headline",
        },
        {
            "severity": "error",
            "code": "LUMV0810",
            "message": "slot offer.primary_message fixture overflows text node instruction",
            "target_slot_id": "slot_offer_primary_message",
        },
        {
            "severity": "error",
            "code": "LUMV0810",
            "message": "slot offer.secondary_message fixture overflows text node benefit_copy",
            "target_slot_key": "offer.secondary_message",
        },
    ]

    classification = classify_diagnostics(
        diagnostics,
        {
            "page_id": "page_a4",
            "node_id": "logo_plus",
            "parent_node_id": "logo_mark",
        },
        scene=scene,
    )

    assert classification.repair_class == RepairClass.layout_cluster
    assert classification.cluster is not None
    assert classification.cluster.root_frame_id == "artboard"
    assert classification.cluster.parent_node_id == "card"
    allowed = layout_cluster_allowed_node_ids(
        classification.cluster.model_dump(mode="json")
    )
    assert {
        "artboard",
        "card",
        "logo_mark",
        "logo_plus",
        "cta_section",
        "header",
        "body_section",
        "benefit_section",
        "stats_row",
        "stat_one",
        "stat_two",
        "stat_three",
        "headline",
        "instruction",
        "benefit_copy",
        "stat_lab_three",
        "stat_lab_two",
        "stat_val_one",
    }.issubset(allowed)
    assert "cta_label" not in allowed
    assert is_layout_cluster_dsl(
        "\n".join(
            [
                "#artboard s(fill,fill) g(24) pad(48)",
                "#card s(499,hug) g(16) pad(24)",
                "#headline s(fill,hug) wrap_text(true) max_lines(3)",
                "#instruction s(fill,hug) wrap_text(true) max_lines(8)",
                "#benefit_copy s(fill,hug) wrap_text(true) max_lines(6)",
            ]
        ),
        {
            "repair_class": "layout_cluster",
            "cluster": classification.cluster.model_dump(mode="json"),
        },
    )
    assert not is_layout_cluster_dsl(
        "#artboard s(595,842) g(24) pad(48)",
        {
            "repair_class": "layout_cluster",
            "cluster": classification.cluster.model_dump(mode="json"),
        },
    )

    scene["slots"] = [
        {
            "id": "slot_campaign_headline",
            "key": "campaign.headline",
            "bound_nodes": [{"id": "headline"}],
        },
        {
            "id": "slot_offer_primary_message",
            "key": "offer.primary_message",
            "bound_nodes": [{"id": "instruction"}],
        },
        {
            "id": "slot_offer_secondary_message",
            "key": "offer.secondary_message",
            "bound_nodes": [{"id": "benefit_copy"}],
        },
    ]
    summary_shape = classify_diagnostics(
        diagnostics,
        {
            "page_id": "page_a4",
            "node_id": "logo_plus",
            "parent_node_id": "logo_mark",
        },
        scene=scene,
    )
    assert summary_shape.cluster is not None
    assert {
        "headline",
        "instruction",
        "benefit_copy",
    }.issubset(
        layout_cluster_allowed_node_ids(summary_shape.cluster.model_dump(mode="json"))
    )


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
    assert is_layout_cluster_dsl("#artboard s(fill,fill) pad(48) g(24)", context)
    assert is_layout_cluster_dsl("delete(bg)\n#artboard fill($surface.page)", context)
    assert not is_layout_cluster_dsl("page page_a4 preset(a4,portrait)", context)
    assert not is_layout_cluster_dsl("#artboard s(595,842) pad(48) g(24)", context)
    assert not is_layout_cluster_dsl("#unrelated s(1,1)", context)
    assert not is_layout_cluster_dsl("#card al(v,x(s),g(12),pad(24))", context)
    assert not is_layout_cluster_dsl("#card wrap(true)", context)
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
    assert (
        "do not regenerate the whole scene"
        in author.requests[1].repair_context["prohibitions"]
    )
    assert author.requests[2].repair_context["kind"] == "layout_cluster_violation"
    repair_request_path = (
        config.trace_dir / tools.run_id / "iterations" / "001" / "repair_request.json"
    )
    repair_request = json.loads(repair_request_path.read_text(encoding="utf-8"))[
        "repair_request"
    ]
    assert repair_request["repair_class"] == "layout_cluster"
    assert repair_request["cluster"]["parent_node_id"] == "card"
    assert "modify_auto_layout" in repair_request["permissions"]
    assert "do not regenerate the whole scene" in repair_request["prohibitions"]
    events = [
        json.loads(line)["event"]
        for line in (config.trace_dir / tools.run_id / "trace.jsonl")
        .read_text(encoding="utf-8")
        .splitlines()
    ]
    assert "layout_cluster_repair_rejected" in events
    assert tools.core.compile_calls == 2
    assert tools.core.compile_sources == [
        "page page_a4 preset(a4,portrait)",
        "#card s(fill,hug)\n#headline s(fill,hug)",
    ]


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


def test_partial_layout_cluster_repair_applies_valid_refs_and_skips_strays(
    tmp_path: Path, monkeypatch
):
    # NON-ATOMIC cluster repair: a block that mixes a valid in-cluster modify with
    # an out-of-cluster ref must NOT be zero-applied. The in-cluster edit compiles
    # and the stray line is skipped, so the iteration makes progress instead of
    # being wasted (the old behavior rejected the whole block before compile).
    monkeypatch.setattr(
        "lumen_deepagent.tools.CoreClient", FakeLayoutClusterPreflightCoreClient
    )
    config = runtime_config(tmp_path, max_iterations=2)
    tools = LumenDesignTools(config, "Create an A4 appointment card")
    author = ScriptedAuthor(
        [
            "page page_a4 preset(a4,portrait)",      # iter0: initial design, compiles
            "#card s(fill,hug)\n#unrelated s(1,1)",  # iter1: keep #card, drop #unrelated
        ]
    )
    reviewer = ScriptedReviewer(
        [VisualCritique(accepted=True, summary="should not be reached")]
    )

    result = LumenQualityLoop(tools, author, reviewer).run(
        "Create an A4 appointment card"
    )

    # Preflight never clears (the fake always returns LUMV0801), so the run still
    # ends without acceptance — the point is HOW the mixed repair was handled.
    assert result["status"] == "failed"
    trace_lines = (
        (config.trace_dir / tools.run_id / "trace.jsonl")
        .read_text(encoding="utf-8")
        .splitlines()
    )
    events = [json.loads(line)["event"] for line in trace_lines]
    # The mixed block was applied PARTIALLY, not rejected wholesale.
    assert "layout_cluster_repair_partial" in events
    assert "layout_cluster_repair_rejected" not in events
    # Both the initial block and the kept subset of the repair reached the compiler.
    assert tools.core.compile_calls == 2
    # The stray #unrelated line was stripped; only the in-cluster #card edit compiled.
    assert tools.core.compile_sources[1] == "#card s(fill,hug)"
    # The dropped line is recorded for observability.
    partial = next(
        json.loads(line)
        for line in trace_lines
        if json.loads(line)["event"] == "layout_cluster_repair_partial"
    )
    dropped = partial["payload"]["dropped_lines"]
    assert any("#unrelated" in entry["line"] for entry in dropped)


class FakeSlotFixturePreflightCoreClient(FakeCoreClient):
    """Preflight always reports a slot-SUBJECT LUMV0800 (required slot needs a
    fixture), which must route to a slot_fixture repair so the #slot: fix is
    permitted rather than banned by the layout-cluster gate."""

    def __init__(self, repo_root: Path) -> None:
        super().__init__(repo_root)
        self.compile_calls = 0
        self.compile_sources = []

    def compile_dsl_into_scene(self, scene, source: str, dsl_session=None):
        self.compile_calls += 1
        self.compile_sources.append(source)
        return {
            "scene": layout_cluster_scene(),
            "applied_operations": 1,
            "dsl": {
                "compile_output": {
                    "operations": [{"kind": "set_slot_fixture"}],
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
                    "code": "LUMV0800",
                    "message": "required slot campaign.headline needs a placeholder or validation fixture",
                    "target_slot_id": "slot_campaign_headline",
                    "target_slot_key": "campaign.headline",
                }
            ],
            "preflight": {
                "has_errors": True,
                "brand_ref_operations": [],
                "token_operations": [],
                "layout_operations": [],
            },
        }


def test_slot_fixture_repair_permits_slot_modify_lines(tmp_path: Path, monkeypatch):
    # A slot-subject LUMV0800 routes to a slot_fixture repair; the #slot: fixture
    # edit (which the layout-cluster gate used to ban) is accepted and compiles.
    monkeypatch.setattr(
        "lumen_deepagent.tools.CoreClient", FakeSlotFixturePreflightCoreClient
    )
    config = runtime_config(tmp_path, max_iterations=2)
    tools = LumenDesignTools(config, "Create an A4 appointment card")
    author = ScriptedAuthor(
        [
            "page page_a4 preset(a4,portrait)",  # iter0: initial design, compiles
            '#slot:campaign.headline sample("Short") worst_case("A very long headline for fit")',
        ]
    )
    reviewer = ScriptedReviewer(
        [VisualCritique(accepted=True, summary="should not be reached")]
    )

    LumenQualityLoop(tools, author, reviewer).run("Create an A4 appointment card")

    # The slot-subject LUMV0800 routed to slot_fixture, not layout_cluster.
    assert author.requests[1].repair_context["repair_class"] == "slot_fixture"
    events = [
        json.loads(line)["event"]
        for line in (config.trace_dir / tools.run_id / "trace.jsonl")
        .read_text(encoding="utf-8")
        .splitlines()
    ]
    # The #slot: fixture edit was NOT rejected and DID reach the compiler.
    assert "slot_fixture_repair_rejected" not in events
    assert tools.core.compile_calls == 2
    assert "slot:campaign.headline" in tools.core.compile_sources[1]


def test_slot_fixture_repair_rejects_destructive_block(tmp_path: Path, monkeypatch):
    # The slot_fixture gate is modify-only: a destructive reply (delete + re-page)
    # is rejected before compile, so the scene is never stripped.
    monkeypatch.setattr(
        "lumen_deepagent.tools.CoreClient", FakeSlotFixturePreflightCoreClient
    )
    config = runtime_config(tmp_path, max_iterations=2)
    tools = LumenDesignTools(config, "Create an A4 appointment card")
    author = ScriptedAuthor(
        [
            "page page_a4 preset(a4,portrait)",
            "delete(headline)\npage page_a4 preset(a4,portrait)",  # destructive → rejected
        ]
    )
    reviewer = ScriptedReviewer(
        [VisualCritique(accepted=True, summary="should not be reached")]
    )

    LumenQualityLoop(tools, author, reviewer).run("Create an A4 appointment card")

    events = [
        json.loads(line)["event"]
        for line in (config.trace_dir / tools.run_id / "trace.jsonl")
        .read_text(encoding="utf-8")
        .splitlines()
    ]
    assert "slot_fixture_repair_rejected" in events
    assert tools.core.compile_calls == 1
    assert "headline" in tools.scene["nodes"]


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


def test_director_structural_rewrite_overrides_stale_surgical_gate(
    tmp_path: Path, monkeypatch
):
    # Regression for the repair-loop deadlock: prior feedback demanded a SURGICAL
    # (modify-only) repair, but the director then explicitly orders a full-page
    # rewrite. The rewrite must NOT be rejected by the stale surgical gate as
    # `dsl_repair_not_surgical`. Before the fix, the surgical gate ignored the
    # director's authority, rejected every authored rewrite before compile, and
    # spun the loop to max_iterations without ever attempting the structural fix.
    monkeypatch.setattr(
        "lumen_deepagent.tools.CoreClient", FakeAlwaysPreflightErrorCoreClient
    )
    config = runtime_config(tmp_path, max_iterations=2)
    tools = LumenDesignTools(config, "Create a square LinkedIn ad")
    author = ScriptedAuthor(
        [
            "page page_test",  # iter0: initial design; compiles, preflight errors → surgical feedback
            "delete(headline)\npage page_test\n  bg rect p(0,0) s(1080,1080)",  # iter1: full rewrite
        ]
    )
    reviewer = ScriptedReviewer(
        [VisualCritique(accepted=False, summary="never reached; preflight blocks")]
    )
    director = ScriptedDirector(
        [
            AgentDirectorDecision(
                action_mode=AgentActionMode.new_artifact,
                rationale="Author the initial artifact.",
            ),
            AgentDirectorDecision(
                action_mode=AgentActionMode.full_page_rewrite,
                rationale="Composition is structurally weak; rewrite the whole page.",
            ),
        ]
    )

    result = LumenQualityLoop(tools, author, reviewer, director=director).run(
        "Create a square LinkedIn ad"
    )

    events = [
        json.loads(line)["event"]
        for line in (config.trace_dir / tools.run_id / "trace.jsonl")
        .read_text(encoding="utf-8")
        .splitlines()
    ]
    # The director-authorised rewrite is NOT rejected by the stale surgical gate.
    assert "dsl_repair_not_surgical" not in events
    # Both the initial block AND the rewrite reached the compiler (no deadlock).
    assert tools.core.compile_calls == 2
    # The run still fails (preflight never clears) but the best draft is preserved
    # on the canvas rather than a wiped scene.
    assert result["status"] == "failed"
    assert "headline" in tools.scene["nodes"]


def test_curated_context_stays_bounded_across_iterations(tmp_path: Path, monkeypatch):
    # P1: the per-iteration context must NOT accumulate. Across several failing
    # repair iterations the director-observed context stays bounded — no scene
    # deepcopy, no append-only previews, and crucially no `full_context` written
    # to the trace and read back in. The old `full_activity_context` grew ~17x per
    # iteration via recursive self-nesting; this asserts that growth is gone.
    monkeypatch.setattr(
        "lumen_deepagent.tools.CoreClient", FakeAlwaysPreflightErrorCoreClient
    )
    config = runtime_config(tmp_path, max_iterations=5)
    tools = LumenDesignTools(config, "Create a square LinkedIn ad")
    author = ScriptedAuthor(["page page_test", "#headline s(400,80)"])
    reviewer = ScriptedReviewer(
        [VisualCritique(accepted=False, summary="never reached; preflight blocks")]
    )

    class RecordingDirector:
        def __init__(self) -> None:
            self.sizes: list[int] = []

        def decide(self, *, full_context):
            self.sizes.append(len(json.dumps(full_context)))
            return AgentDirectorDecision(
                action_mode=AgentActionMode.targeted_patch,
                rationale="Apply the smallest patch for the preflight error.",
            )

    director = RecordingDirector()
    LumenQualityLoop(tools, author, reviewer, director=director).run(
        "Create a square LinkedIn ad"
    )

    # The loop ran multiple repair iterations.
    assert len(director.sizes) >= 4
    # Bounded growth: the final iteration's context is no larger than ~2x the
    # first feedback-bearing iteration. (The old design was ~17x PER step.)
    assert director.sizes[-1] <= director.sizes[1] * 2
    # And it stays small in absolute terms regardless of iteration count.
    assert max(director.sizes) < 200_000
    # The trace never carries a context envelope, so it cannot be re-inflated.
    trace_text = (
        (config.trace_dir / tools.run_id / "trace.jsonl").read_text(encoding="utf-8")
    )
    assert '"full_context":' not in trace_text
    assert '"preview_activity":' not in trace_text


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

    # The draft is preflight-clean (valid) but the reviewer never accepted within
    # the budget: the run completes WITH WARNINGS rather than failing, and the best
    # draft stays on the canvas instead of being surfaced to the user as an error.
    assert result["status"] == "completed_with_warnings"
    assert result["stop_reason"] == "max_iterations_reached"
    assert tools.scene["nodes"], "best preflight-clean draft must remain on the canvas"


def test_identical_repeat_block_is_skipped_and_escalated(
    tmp_path: Path, monkeypatch
):
    # run_d6e08a28 pinned: the author answered the same critique with the
    # byte-identical 1-op patch on every iteration, burning the whole repair
    # budget with zero information gain. An identical block cannot change the
    # outcome, so the loop must skip the wasted compile/review, escalate the
    # standing feedback, and hand the NEXT attempt the strengthened instruction.
    monkeypatch.setattr("lumen_deepagent.tools.CoreClient", FakeCoreClient)
    config = runtime_config(tmp_path, max_iterations=4)
    tools = LumenDesignTools(config, "Create a square LinkedIn ad")
    rejected_critique = VisualCritique(
        accepted=False,
        summary="Composition sits low.",
        issues=[
            VisualIssue(
                category=CritiqueCategory.alignment,
                target=VisualTarget(page_id="page_test", node_id="headline"),
                message="Re-center the composition.",
                suggested_repair="Wrap and center the main group.",
            )
        ],
    )
    author = ScriptedAuthor(
        [
            "page page_test",
            "#headline x(c) y(c)",  # in-cluster repair; the critic still rejects
            "#headline x(c) y(c)",  # IDENTICAL re-emit — must be skipped
            "#headline pad(24)",  # the escalated, different attempt
        ]
    )
    reviewer = ScriptedReviewer(
        [
            rejected_critique,
            rejected_critique,
            VisualCritique(accepted=True, summary="Centered now."),
        ]
    )
    loop = LumenQualityLoop(tools, author, reviewer)

    result = loop.run("Create a square LinkedIn ad")

    assert result["status"] == "accepted"
    assert len(author.requests) == 4
    # The identical re-emit (iteration 3) consumed NO review call.
    assert len(reviewer.calls) == 3
    events = [
        json.loads(line).get("event")
        for line in (config.trace_dir / tools.run_id / "trace.jsonl")
        .read_text(encoding="utf-8")
        .splitlines()
        if line.strip()
    ]
    assert "repeat_block_escalated" in events
    # The final attempt's repair context carries the escalation up front.
    escalated_context = author.requests[3].repair_context
    assert escalated_context.get("escalation") == "repeat_block"
    assert (escalated_context.get("authoring_constraints") or [""])[0] == (
        REPEAT_BLOCK_ESCALATION
    )


class FakeSameHaltTwiceCoreClient(FakeCoreClient):
    """First two compiles halt with the SAME diagnostic code (a modify-grammar
    error, session-shaped exactly as the real path mangles it); the third
    succeeds via the base fake."""

    def __init__(self, repo_root: Path) -> None:
        super().__init__(repo_root)
        self.compile_calls = 0

    def compile_dsl_into_scene(self, scene, source: str, dsl_session=None):
        self.compile_calls += 1
        if self.compile_calls <= 2:
            return {
                "scene": scene,
                "applied_operations": 0,
                "dsl": {
                    "compile_output": {
                        "operations": [],
                        "diagnostics": [
                            {
                                "diagnostic": {
                                    "code": "LUMD0210",
                                    "message": "unsupported property syntax on modify line",
                                    "severity": "error",
                                },
                                "span": {"line": 1, "column": 1},
                            }
                        ],
                        "halted_at": {"code": "LUMD0210", "line": 1},
                    },
                    "operation_error": None,
                    "session_snapshot": None,
                },
            }
        return super().compile_dsl_into_scene(scene, source, dsl_session)


def test_repeated_same_code_halt_pins_ref_grammar_escalation(
    tmp_path: Path, monkeypatch
):
    # run_8cbeae790f07 pinned (the agent-improvement backlog's escalation
    # heuristic): three DIFFERENT blocks, one unlearned grammar form, zero
    # applied ops. On the second consecutive halt with the same code the loop
    # must pin the ref-grammar excerpt into the next author request.
    monkeypatch.setattr(
        "lumen_deepagent.tools.CoreClient", FakeSameHaltTwiceCoreClient
    )
    config = runtime_config(tmp_path, max_iterations=3)
    tools = LumenDesignTools(config, "Edit the headline")
    author = ScriptedAuthor(
        [
            '#headline text "A"',
            '#headline text "B"',
            '#headline text("C")',
        ]
    )
    reviewer = ScriptedReviewer([VisualCritique(accepted=True, summary="ok")])
    loop = LumenQualityLoop(tools, author, reviewer)

    result = loop.run("Edit the headline")

    assert result["status"] == "accepted"
    first, second = loop.previous_feedback[0], loop.previous_feedback[1]
    assert first.get("halt_code") == "LUMD0210"
    assert first.get("escalation") is None
    assert second.get("halt_code") == "LUMD0210"
    assert second.get("escalation") == "repeated_halt"
    constraints = second.get("authoring_constraints") or []
    assert DSL_REF_GRAMMAR_ESCALATION in constraints
    assert "ESCALATION" in constraints[0]
    events = [
        json.loads(line).get("event")
        for line in (config.trace_dir / tools.run_id / "trace.jsonl")
        .read_text(encoding="utf-8")
        .splitlines()
        if line.strip()
    ]
    assert "repeated_halt_escalated" in events
    # Iteration 3's author request received the pinned grammar.
    assert author.requests[2].repair_context.get("escalation") == "repeated_halt"


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

    Iteration 1 compiles a full scene (preflight-clean) but the reviewer rejects
    it; the repair (iteration 2) wipes the scene and halts. The run completes with
    warnings (a clean draft existed), and the loop must restore the best compiled
    scene so the editor renders it as a draft instead of an empty canvas (the
    `draft_scene` the API surfaces is `tools.scene`)."""
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

    assert result["status"] == "completed_with_warnings"
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
    assert summary["failure_attribution"] == {"renderer_export_preview": 1}
    assert summary["run_attributions"][0]["primary"] == "renderer_export_preview"
    assert summary["run_attributions"][0]["confidence"] == "high"
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
    assert summary["failure_attribution"] == {"agent_authoring": 1}
    assert summary["run_attributions"][0]["primary"] == "agent_authoring"
    assert "LUMV0800" in summary["run_attributions"][0]["diagnostic_codes"]
    assert summary["oversized_background_rects"] == 1
    assert summary["remaining_artboard_overflow"] == 1
    assert summary["remaining_parent_overflow"] == 1
    assert summary["final_lumv080x_count"] == 2
    assert summary["final_lumv090x_count"] == 1


def test_provider_helpers_extract_dsl_and_parse_structured_critique():
    assert extract_dsl("```lumen\npage page_a4\n```") == "page page_a4"
    assert extract_dsl("```lumen-dsl\npage page_a4\n```") == "page page_a4"
    decision = parse_director_decision(
        """
```json
{
  "action_mode": "replace_artboard_subtree",
  "rationale": "The page composition is structurally weak.",
  "target": {"page_id": "page_a4"},
  "allowed_scope": {"page_id": "page_a4", "mode": "replace_root_subtree"},
  "instructions_to_author": "Rebuild the page with a coherent hierarchy.",
  "uses_full_context": true
}
```
"""
    )
    assert decision.action_mode == AgentActionMode.replace_artboard_subtree
    assert decision.uses_full_context is True
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


def test_generate_image_uses_configured_model_and_upserts_generated_asset(
    tmp_path: Path, monkeypatch
):
    monkeypatch.setattr("lumen_deepagent.tools.CoreClient", FakeCoreClient)
    captured: dict = {}

    def fake_generate(**kwargs):
        captured.update(kwargs)
        return types.SimpleNamespace(
            image_bytes=b"\x89PNG fake-image-bytes",
            mime_type="image/png",
            model="test/image-model",
            provenance={"created_by": "agent", "source_label": "image generation", "notes": []},
            license={"name": "generated_commercial_use", "allow_export": True},
        )

    stub = types.SimpleNamespace(is_configured=lambda: True, generate=fake_generate)
    monkeypatch.setattr("lumen_deepagent.tools.image_provider", stub)

    tools = LumenDesignTools(runtime_config(tmp_path), "Create a clinic ad")
    result = json.loads(
        tools.generate_image("editorial photo of a calm clinic reception", brand_notes=["deep navy"])
    )

    assert result["image"]["status"] == "ok"
    assert result["image"]["mode"] == "model"
    assert result["image"]["model"] == "test/image-model"
    assert result["image"]["asset_id"].startswith("asset_img_")
    assert result["image"]["source"]["kind"] == "generated"
    assert result["image"]["source"]["model"] == "test/image-model"

    # The prompt + brand notes reached the model; bytes were ingested as Generated.
    assert captured["prompt"].startswith("editorial photo")
    assert captured["brand_notes"] == ["deep navy"]
    assert tools.core.last_ingest["source"]["model"] == "test/image-model"
    assert tools.core.last_ingest["kind"] == "raster_image"

    # Registered through the canonical upsert_asset op path.
    assert any(op.get("kind") == "upsert_asset" for op in tools.core.applied_operations)
    assert tools.scene_update_sources[-1] == "generate_image"


def test_generate_image_falls_back_to_placeholder_when_model_unconfigured(
    tmp_path: Path, monkeypatch
):
    monkeypatch.setattr("lumen_deepagent.tools.CoreClient", FakeCoreClient)

    def fail_generate(**kwargs):  # must not be called when unconfigured
        raise AssertionError("model should not be called when unconfigured")

    stub = types.SimpleNamespace(is_configured=lambda: False, generate=fail_generate)
    monkeypatch.setattr("lumen_deepagent.tools.image_provider", stub)

    tools = LumenDesignTools(runtime_config(tmp_path), "Create a poster")
    result = json.loads(tools.generate_image("a serene mountain lake at dawn"))

    assert result["image"]["status"] == "ok"
    assert result["image"]["mode"] == "placeholder"
    assert result["image"]["model"] == "stub-image-v0"
    assert any(diag["code"] == "LUMA0711" for diag in result["diagnostics"])
    assert tools.core.last_generate_asset["provider"] == "stub-image-v0"
    assert tools.scene_update_sources[-1] == "generate_image"


def test_generate_image_derives_aspect_from_target_node(tmp_path: Path, monkeypatch):
    monkeypatch.setattr("lumen_deepagent.tools.CoreClient", FakeCoreClient)
    stub = types.SimpleNamespace(is_configured=lambda: False, generate=lambda **k: None)
    monkeypatch.setattr("lumen_deepagent.tools.image_provider", stub)

    tools = LumenDesignTools(runtime_config(tmp_path), "Create a landscape hero")
    tools.scene["nodes"]["hero"] = {
        "id": "hero",
        "kind": {"kind": "image", "asset_id": "placeholder", "alt": None},
        "computed": {"layout_bounds": {"x": 0.0, "y": 0.0, "width": 1600.0, "height": 900.0}},
    }

    result = json.loads(tools.generate_image("a coastal city skyline", target_node_id="hero"))

    # 1600x900 -> nearest common aspect 16:9, long-edge 1536 -> 1536x864.
    assert result["image"]["aspect_ratio"] == "16:9"
    assert result["image"]["width"] == 1536
    assert result["image"]["height"] == 864
    assert tools.core.last_generate_asset["request"]["constraints"]["width"] == 1536
    assert tools.core.last_generate_asset["request"]["constraints"]["height"] == 864


def test_generate_image_caches_identical_model_requests(tmp_path: Path, monkeypatch):
    # Step 6: across loop iterations the same hero is requested repeatedly; the
    # cache re-uses the asset instead of re-paying the model.
    monkeypatch.setattr("lumen_deepagent.tools.CoreClient", FakeCoreClient)
    calls = {"n": 0}

    def fake_generate(**kwargs):
        calls["n"] += 1
        return types.SimpleNamespace(
            image_bytes=b"\x89PNG fake-image-bytes",
            mime_type="image/png",
            model="test/image-model",
            provenance={"created_by": "agent", "source_label": "image generation", "notes": []},
            license={"name": "generated_commercial_use", "allow_export": True},
        )

    stub = types.SimpleNamespace(
        is_configured=lambda: True,
        generate=fake_generate,
        configured_model_id=lambda: "test/image-model",
    )
    monkeypatch.setattr("lumen_deepagent.tools.image_provider", stub)

    tools = LumenDesignTools(runtime_config(tmp_path), "Create a clinic ad")

    first = json.loads(tools.generate_image("editorial photo of a calm clinic reception", brand_notes=["deep navy"]))
    assert first["image"]["status"] == "ok"
    assert first["image"]["mode"] == "model"
    assert calls["n"] == 1

    # Identical re-request (next iteration) → cache hit: model not called again.
    second = json.loads(tools.generate_image("editorial photo of a calm clinic reception", brand_notes=["deep navy"]))
    assert second["image"]["status"] == "ok"
    assert second["image"]["mode"] == "cached"
    assert calls["n"] == 1
    assert second["image"]["asset_id"] == first["image"]["asset_id"]


def test_place_asset_in_node_emits_reversible_placement_op(tmp_path: Path, monkeypatch):
    monkeypatch.setattr("lumen_deepagent.tools.CoreClient", FakeCoreClient)
    tools = LumenDesignTools(runtime_config(tmp_path), "Place a hero image")

    result = json.loads(
        tools.place_asset_in_node(
            "hero", "asset_img_abc", fit="cover", focal_x=0.5, focal_y=0.42, alt="clinic hero"
        )
    )

    assert result["placement"]["status"] == "ok"
    place_ops = [op for op in tools.core.applied_operations if op.get("kind") == "place_asset_in_node"]
    assert len(place_ops) == 1
    op = place_ops[0]
    assert op["node_id"] == "hero"
    assert op["asset_id"] == "asset_img_abc"
    assert op["placement"]["fit"] == "cover"
    assert op["placement"]["focal_point"] == {"x": 0.5, "y": 0.42}
    assert op["placement"]["alt_text"] == "clinic hero"
    assert tools.scene_update_sources[-1] == "place_asset_in_node"


def test_place_asset_in_slot_targets_the_slot(tmp_path: Path, monkeypatch):
    monkeypatch.setattr("lumen_deepagent.tools.CoreClient", FakeCoreClient)
    tools = LumenDesignTools(runtime_config(tmp_path), "Place into a slot")

    result = json.loads(tools.place_asset_in_slot("slot_campaign_hero_image", "asset_img_abc"))

    assert result["placement"]["status"] == "ok"
    op = [op for op in tools.core.applied_operations if op.get("kind") == "place_asset_in_slot"][-1]
    assert op["slot_id"] == "slot_campaign_hero_image"
    assert op["asset_id"] == "asset_img_abc"
    assert op["placement"]["fit"] == "cover"
    assert op["placement"]["focal_point"] == {"x": 0.5, "y": 0.5}


def test_asset_dispatcher_routes_actions_and_preserves_place_kinds(
    tmp_path: Path, monkeypatch
):
    # Group B: the single `asset` tool fans out to generate_image / generate_qr / place,
    # and `place` MUST preserve the two distinct core op kinds (node vs slot) — the
    # critic-flagged invariant.
    monkeypatch.setattr("lumen_deepagent.tools.CoreClient", FakeCoreClient)
    stub = types.SimpleNamespace(is_configured=lambda: False, generate=lambda **k: None)
    monkeypatch.setattr("lumen_deepagent.tools.image_provider", stub)
    tools = LumenDesignTools(runtime_config(tmp_path), "Create an ad with imagery")

    img = json.loads(tools.asset(action="generate_image", prompt="a serene mountain lake at dawn"))
    assert img["image"]["status"] == "ok"
    assert tools.scene_update_sources[-1] == "generate_image"

    qr = json.loads(
        tools.asset(action="generate_qr", data="https://lumen.example/x", print_media=True, target_width_mm=12.0)
    )
    assert qr["qr"]["status"] == "ok"
    assert tools.scene_update_sources[-1] == "generate_qr"

    node_place = json.loads(
        tools.asset(action="place", node_id="hero", asset_id="asset_img_abc", focal_y=0.4)
    )
    assert node_place["placement"]["status"] == "ok"
    assert tools.scene_update_sources[-1] == "place_asset_in_node"
    assert any(op.get("kind") == "place_asset_in_node" for op in tools.core.applied_operations)

    slot_place = json.loads(
        tools.asset(action="place", slot_id="slot_campaign_hero_image", asset_id="asset_img_abc")
    )
    assert slot_place["placement"]["status"] == "ok"
    assert tools.scene_update_sources[-1] == "place_asset_in_slot"
    assert any(op.get("kind") == "place_asset_in_slot" for op in tools.core.applied_operations)

    # Bad requests fail closed (no new scene mutation).
    sources_before = list(tools.scene_update_sources)
    assert json.loads(tools.asset(action="place", asset_id="asset_img_abc"))["error_code"] == "asset.bad_request"
    assert json.loads(tools.asset(action="generate_image"))["error_code"] == "asset.bad_request"
    assert json.loads(tools.asset(action="generate_qr"))["error_code"] == "asset.bad_request"
    assert json.loads(tools.asset(action="bogus"))["error_code"] == "asset.unknown_action"
    assert tools.scene_update_sources == sources_before


def test_inspect_dispatcher_routes_all_views(tmp_path: Path, monkeypatch):
    # Group A: the single `inspect` tool returns exactly what the former
    # summarize_*/query_* singletons returned, for every view.
    monkeypatch.setattr("lumen_deepagent.tools.CoreClient", FakeCoreClient)
    tools = LumenDesignTools(runtime_config(tmp_path), "Inspect a scene")
    tools.compile_dsl_block("page page_test")

    assert json.loads(tools.inspect(view="scene")) == json.loads(tools.summarize_scene())
    assert json.loads(tools.inspect(view="slots")) == json.loads(tools.summarize_slots())
    assert json.loads(tools.inspect(view="page", target="page_test")) == json.loads(
        tools.summarize_page("page_test")
    )
    assert json.loads(tools.inspect(view="node_tree", target="page_test")) == json.loads(
        tools.summarize_node_tree("page_test")
    )
    assert json.loads(tools.inspect(view="geometry", target="headline")) == json.loads(
        tools.query_geometry("headline")
    )
    assert json.loads(tools.inspect(view="slot_bindings", target="campaign.headline")) == json.loads(
        tools.query_slot_bindings("campaign.headline")
    )

    # Views needing a target fail closed; unknown view is reported.
    assert json.loads(tools.inspect(view="page"))["error_code"] == "inspect.bad_request"
    assert json.loads(tools.inspect(view="geometry"))["error_code"] == "inspect.bad_request"
    assert json.loads(tools.inspect(view="bogus"))["error_code"] == "inspect.unknown_view"


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
