from __future__ import annotations

import re
from pathlib import Path
from typing import Iterable, List

from .schemas import KnowledgeSnippet


PRIMARY_KNOWLEDGE_PATHS = [
    "apps/agent_runtime/knowledge/lumen-dsl/authoring.md",
    "apps/agent_runtime/knowledge/design/layout-recipes.md",
    "apps/agent_runtime/knowledge/design/typography-and-composition.md",
    "apps/agent_runtime/knowledge/design-systems/brand-tokens.md",
    "apps/agent_runtime/knowledge/design-systems/token-taxonomy.md",
    "apps/agent_runtime/knowledge/design-systems/brand-generation.md",
    "apps/agent_runtime/knowledge/design-systems/brand-validation.md",
    "apps/agent_runtime/knowledge/design-systems/modes.md",
    "apps/agent_runtime/knowledge/design-systems/logo-and-assets.md",
    "apps/agent_runtime/knowledge/design-systems/brand-fit-critique.md",
    "apps/agent_runtime/knowledge/assets/asset-placement.md",
    "apps/agent_runtime/knowledge/export/preview-quality.md",
    "apps/agent_runtime/knowledge/agent-loop/authoring-and-repair.md",
    "apps/agent_runtime/knowledge/future/scaffolds.md",
]

SECONDARY_KNOWLEDGE_PATHS = [
    "reference_docs/ABM-Design-Engine-Temporary-Spec.md",
    "reference_docs/Brilliant-Reverse-Engineering-Report.md",
    "reference_docs/Brilliant-vs-Lumen-Product-Gap-Analysis.md",
    "docs/dsl-compiler.md",
    "docs/agents-design-loop.md",
    "docs/preflight-pipeline.md",
    "docs/slots-layout.md",
    "docs/assets-pipeline.md",
    "docs/phase4-integration.md",
]

DEFAULT_KNOWLEDGE_PATHS = PRIMARY_KNOWLEDGE_PATHS + SECONDARY_KNOWLEDGE_PATHS
REQUIRED_TASK_CATEGORIES = ["lumen-dsl", "design", "design-systems", "agent-loop"]


def read_knowledge(
    repo_root: Path,
    query: str,
    limit: int = 5,
    paths: Iterable[str] = DEFAULT_KNOWLEDGE_PATHS,
) -> List[KnowledgeSnippet]:
    terms = [term for term in re.split(r"[^a-z0-9_.$-]+", query.lower()) if term]
    snippets: list[KnowledgeSnippet] = []

    for rel_path in paths:
        path = repo_root / rel_path
        if not path.exists():
            continue
        text = path.read_text(encoding="utf-8")
        category = category_for(rel_path)
        score = score_text(text, terms, rel_path)
        if score == 0 and snippets and rel_path not in PRIMARY_KNOWLEDGE_PATHS:
            continue
        excerpt = best_excerpt(text, terms)
        snippets.append(
            KnowledgeSnippet(
                path=rel_path,
                title=title_for(text, rel_path),
                score=score,
                excerpt=excerpt,
                category=category,
                selected_reason="keyword_match" if score else "fallback_context",
            )
        )

    return sorted(snippets, key=lambda item: (-item.score, item.path))[:limit]


def read_task_knowledge(
    repo_root: Path,
    query: str,
    limit: int = 8,
    paths: Iterable[str] = DEFAULT_KNOWLEDGE_PATHS,
) -> List[KnowledgeSnippet]:
    """Return task knowledge with mandatory Lumen docs before reference docs."""
    candidates = read_knowledge(repo_root, query, limit=max(limit * 3, 20), paths=paths)
    selected: list[KnowledgeSnippet] = []
    seen_paths: set[str] = set()

    for category in REQUIRED_TASK_CATEGORIES:
        match = next(
            (snippet for snippet in candidates if snippet.category == category),
            None,
        )
        if match is None:
            continue
        selected.append(
            match.model_copy(
                update={"selected_reason": f"required_{category}_context"}
            )
        )
        seen_paths.add(match.path)

    for snippet in candidates:
        if snippet.path in seen_paths:
            continue
        selected.append(snippet)
        seen_paths.add(snippet.path)
        if len(selected) >= limit:
            break

    return selected


def score_text(text: str, terms: list[str], rel_path: str) -> int:
    lower = text.lower()
    score = sum(lower.count(term) for term in terms)
    path_bonus = sum(rel_path.lower().count(term) for term in terms)
    heading_bonus = sum(
        2
        for line in lower.splitlines()
        if line.startswith("#") and any(term in line for term in terms)
    )
    primary_bonus = 3 if rel_path in PRIMARY_KNOWLEDGE_PATHS else 0
    return score + path_bonus + heading_bonus + primary_bonus


def category_for(rel_path: str) -> str:
    if "apps/agent_runtime/knowledge/" in rel_path:
        after_root = rel_path.split("apps/agent_runtime/knowledge/", 1)[1]
        return after_root.split("/", 1)[0]
    if rel_path.startswith("docs/"):
        return "product-doc"
    return "reference"


def title_for(text: str, fallback: str) -> str:
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith("#"):
            return stripped.lstrip("#").strip()
    return fallback


def best_excerpt(text: str, terms: list[str], max_chars: int = 1600) -> str:
    lower = text.lower()
    first_match = min(
        (lower.find(term) for term in terms if lower.find(term) >= 0),
        default=0,
    )
    start = max(0, first_match - max_chars // 3)
    end = min(len(text), start + max_chars)
    excerpt = text[start:end].strip()
    if start > 0:
        excerpt = "..." + excerpt
    if end < len(text):
        excerpt = excerpt + "..."
    return excerpt
