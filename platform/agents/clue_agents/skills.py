"""Minimal flat skill discovery for C4. Loading is metadata-only; it does not create an agent."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True, slots=True)
class SkillDescriptor:
    name: str
    version: str
    summary: str
    tool_allowlist: tuple[str, ...]
    path: Path


def load_skill(path: Path) -> SkillDescriptor:
    """Load C4's deliberately small ``key: value`` front matter from one SKILL.md."""
    content = path.read_text(encoding="utf-8")
    if not content.startswith("---\n"):
        raise ValueError(f"{path} has no skill front matter")
    _, header, _body = content.split("---\n", 2)
    values: dict[str, str] = {}
    for line in header.splitlines():
        key, separator, value = line.partition(":")
        if separator:
            values[key.strip()] = value.strip().strip("\"'")
    required = {"name", "version", "summary", "tools"}
    if missing := required - values.keys():
        raise ValueError(f"{path} is missing skill metadata: {sorted(missing)}")
    tools = tuple(item.strip() for item in values["tools"].split(",") if item.strip())
    return SkillDescriptor(
        name=values["name"],
        version=values["version"],
        summary=values["summary"],
        tool_allowlist=tools,
        path=path,
    )


def discover_skills(parent: Path) -> tuple[SkillDescriptor, ...]:
    """Discover one flat directory level; nested skill graphs are intentionally a C6 concern."""
    return tuple(
        load_skill(path)
        for path in sorted(parent.glob("*/SKILL.md"))
        if path.parent.parent == parent
    )


__all__ = ["SkillDescriptor", "discover_skills", "load_skill"]
