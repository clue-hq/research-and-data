"""Exercise discovery and virtual-workspace delivery, not artistic quality.

The behavioral cases and visual acceptance procedure live in
``evals/reference_image_direction.json``. Passing these tests proves only that
the real runtime can discover and read the authored skill and its references.
"""

from __future__ import annotations

import re
from pathlib import Path
from types import SimpleNamespace

from lumen_agent.harness import _materialized_skill_index
from lumen_agent.knowledge import parse_frontmatter
from lumen_agent.materialize import materialize_agent_workspace

KNOWLEDGE = Path(__file__).resolve().parents[1] / "knowledge_docs"
SKILL = "reference-image-direction"


def test_direction_skill_is_discoverable_and_its_references_are_readable(tmp_path):
    config = SimpleNamespace(workspace_root=tmp_path / "run")
    workspace = materialize_agent_workspace(config)
    index = dict(_materialized_skill_index(config))
    assert SKILL in index, "The scene agent cannot discover the direction skill"

    source = KNOWLEDGE / "skills" / SKILL / "SKILL.md"
    authored = source.read_text(encoding="utf-8")
    metadata, _ = parse_frontmatter(authored)
    assert metadata["name"] == SKILL
    assert index[SKILL] == metadata["description"]

    for prefix in (".deepagent/skills", "knowledge_docs/skills"):
        assert (workspace / prefix / SKILL / "SKILL.md").read_text(
            encoding="utf-8"
        ) == authored

    references = re.findall(r"\]\((/knowledge_docs/[^)]+)\)", authored)
    assert references, "The agent has no link to the supporting reference"
    for virtual_path in references:
        served = workspace / virtual_path.lstrip("/")
        original = KNOWLEDGE / virtual_path.removeprefix("/knowledge_docs/")
        assert served.is_file(), f"Unreadable virtual reference: {virtual_path}"
        assert served.read_bytes() == original.read_bytes()


def test_direction_skill_is_available_in_a_fresh_run_without_runtime_patch(tmp_path):
    """Two independent run roots receive the same skill and reference bytes."""
    first = materialize_agent_workspace(
        SimpleNamespace(workspace_root=tmp_path / "first")
    )
    second = materialize_agent_workspace(
        SimpleNamespace(workspace_root=tmp_path / "second")
    )
    relative = Path(".deepagent/skills") / SKILL / "SKILL.md"
    assert (first / relative).is_file()
    assert (first / relative).read_bytes() == (second / relative).read_bytes()
