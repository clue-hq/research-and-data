from __future__ import annotations

import re
from pathlib import Path
from typing import Iterable, List

from .schemas import KnowledgeSnippet


DEFAULT_KNOWLEDGE_PATHS = [
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
        score = sum(text.lower().count(term) for term in terms)
        if score == 0 and snippets:
            continue
        excerpt = best_excerpt(text, terms)
        snippets.append(
            KnowledgeSnippet(
                path=rel_path,
                title=title_for(text, rel_path),
                score=score,
                excerpt=excerpt,
            )
        )

    return sorted(snippets, key=lambda item: (-item.score, item.path))[:limit]


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
