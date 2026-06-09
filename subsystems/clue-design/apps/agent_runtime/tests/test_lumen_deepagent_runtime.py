from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.append(str(Path(__file__).resolve().parents[1]))
sys.path.append(str(Path(__file__).resolve().parents[2] / "api"))

from lumen_deepagent.config import AgentRuntimeConfig
from lumen_deepagent.knowledge import read_knowledge
from lumen_deepagent.prompts import build_subagents
from lumen_deepagent.schemas import VisualCritique
from lumen_deepagent.tools import LumenDesignTools


class FakeCoreClient:
    def __init__(self, repo_root: Path) -> None:
        self.repo_root = repo_root

    def new_scene(self, document_id: str, title: str):
        return {
            "meta": {"id": document_id, "title": title},
            "pages": {},
            "nodes": {},
            "slots": {},
        }

    def compile_dsl_into_scene(self, scene, source: str):
        updated = dict(scene)
        updated["pages"] = {"page_test": {"name": "Test", "children": ["headline"]}}
        updated["nodes"] = {
            "headline": {"kind": {"kind": "text", "content": "Plan"}}
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
            },
        }

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


def test_runtime_tools_update_scene_export_preview_and_write_trace(
    tmp_path: Path, monkeypatch
):
    monkeypatch.setattr("lumen_deepagent.tools.CoreClient", FakeCoreClient)
    config = AgentRuntimeConfig(
        repo_root=tmp_path,
        model="anthropic:claude-opus-4-6",
        max_iterations=3,
        preview_format="svg",
        trace_dir=tmp_path / ".lumen-runs",
    )
    tools = LumenDesignTools(config, "Create a square ad")

    compile_result = json.loads(tools.compile_dsl_block("page page_test"))
    preflight_result = json.loads(tools.preflight_design())
    preview_result = json.loads(tools.export_preview())
    summary = json.loads(tools.summarize_scene())

    assert compile_result["applied_operations"] == 2
    assert preflight_result["preflight"]["has_errors"] is False
    assert preview_result["artifacts"][0]["byte_len"] > 0
    assert Path(preview_result["artifacts"][0]["path"]).exists()
    assert summary["node_count"] == 1

    trace_path = config.trace_dir / tools.run_id / "trace.jsonl"
    events = [
        json.loads(line)["event"]
        for line in trace_path.read_text(encoding="utf-8").splitlines()
    ]
    assert events == [
        "run_started",
        "dsl_compiled",
        "preflight_completed",
        "preview_exported",
    ]
