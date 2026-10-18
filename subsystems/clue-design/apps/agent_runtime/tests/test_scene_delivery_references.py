"""Every reference the scene agent is given must lead somewhere it can actually go.

Harness alignment I8 (founder ruling 2026-10-17): a pointer to a file the scene view never
delivers, or to a tool the scene agent does not have, costs a failed call and leaves a rule the
agent cannot follow. This contract check (not a design judgement) materialises the real scene
delivery, builds the real first system prompt and checks every file path, bare guide name and
tool call they mention.
"""

from __future__ import annotations

import re
from dataclasses import replace

from agent_fixtures import FakeCoreClient, runtime_config
from langchain_core.messages import AIMessage
from lumen_agent import harness
from lumen_agent.materialize import materialize_agent_workspace
from lumen_agent.workspace import initial_turn_state
from test_scene_catalog_runtime import ScriptedModel

# Pointers the I10 topic (T8) removes together with the rest of its text.md / layout.md changes.
# T8 empties this set; it must never grow.
KNOWN_UNTIL_T8 = {
    "knowledge/design/foundations",
    "knowledge/design/typography-and-composition",
    "knowledge/images/placement",
}

# Files the agent writes or receives per turn, named in the guides without being delivered guides.
WORKSPACE_FILES = {
    "brief.md", "references.md", "ad-assets.md", "direction.md", "index.md", "SKILL.md",
    "AGENTS.md", "catalog.md",
}

# Tools other agents have; the scene agent must never be told to call them.
FOREIGN_TOOLS = ("task", "write_todos", "generate_brand_kit", "task_background", "task_result",
                 "task_status")


def _delivery(tmp_path, monkeypatch):
    monkeypatch.setattr("lumen_agent.tools.substrate.CoreClient", FakeCoreClient)
    built = []

    def build(model_id, **kwargs):
        model = ScriptedModel(responses=[AIMessage(content="done")])
        model.seen = []
        built.append(model)
        return model

    monkeypatch.setattr("lumen_agent.llm.init_model", build)
    monkeypatch.setattr("lumen_agent.llm.assert_model_supports_image_input", lambda *a, **k: None)
    config = replace(runtime_config(tmp_path), scene_solo=True, scene_skill_bundle="candidate",
                     fast_loop=True)
    graph, tools = harness.create_design_deepagent("Make an ad", config)
    graph.invoke(initial_turn_state(tools, "Make an ad") | {"messages": [("human", "Make an ad")]},
                 {"configurable": {"thread_id": "references"}})
    workspace = materialize_agent_workspace(tools.config, knowledge_view="scene")
    files = [*(workspace / "knowledge_docs").rglob("*.md"),
             *(workspace / ".deepagent/skills").rglob("*.md"), workspace / ".deepagent/AGENTS.md"]
    texts = {path.relative_to(workspace).as_posix(): path.read_text() for path in files}
    texts["<system prompt>"] = built[0].seen[0][0].text
    tool_names = set(built[0].bound_names)
    return workspace, texts, tool_names


def test_every_file_and_tool_the_scene_agent_is_pointed_at_exists(tmp_path, monkeypatch):
    workspace, texts, tool_names = _delivery(tmp_path, monkeypatch)
    knowledge = workspace / "knowledge_docs"
    skills = workspace / ".deepagent/skills"
    delivered_names = {path.rsplit("/", 1)[-1] for path in texts if path.endswith(".md")}
    broken: dict[str, set[str]] = {}
    for source, text in texts.items():
        for match in re.finditer(
            r"(?<![\w/.-])(?:/knowledge_docs/)?(knowledge/[a-z0-9_/-]+?)(?:\.md)?(?=[^a-z0-9_/-]|$)", text
        ):
            rel = match.group(1).rstrip("/")
            if rel.count("/") < 2:  # a folder such as knowledge/lumen-dsl/*
                continue
            if not ((knowledge / f"{rel}.md").exists() or (knowledge / rel).exists()):
                broken.setdefault(rel, set()).add(source)
        for name in re.findall(r"(?<![\w-])skills/([a-z0-9-]+)", text):
            if not (skills / name / "SKILL.md").exists():
                broken.setdefault(f"skills/{name}", set()).add(source)
        for name in re.findall(r"`([A-Za-z0-9_.-]+\.md)`", text):
            if name not in delivered_names and name not in WORKSPACE_FILES:
                broken.setdefault(name, set()).add(source)
        for tool in FOREIGN_TOOLS:
            assert tool not in tool_names
            if re.search(rf"(?<![\w.]){tool}\(|`{tool}`|: {tool}, ", text):
                broken.setdefault(f"tool {tool}", set()).add(source)
    unexpected = {ref: sources for ref, sources in broken.items() if ref not in KNOWN_UNTIL_T8}
    assert not unexpected, unexpected
