from __future__ import annotations

import re
from pathlib import Path
from typing import Iterable, List

from .schemas import KnowledgeSnippet


# The deepagent's knowledge system lives entirely under `knowledge_docs/` — a
# self-contained tree (AGENT.md + per-skill SKILL.md + topic reference files)
# authored for the agent. The repo's top-level `docs/` is developer/human-facing
# and is intentionally NOT loaded here.
KNOWLEDGE_DOCS_ROOT = "apps/agent_runtime/knowledge_docs"

PRIMARY_KNOWLEDGE_PATHS = [
    f"{KNOWLEDGE_DOCS_ROOT}/AGENT.md",
    f"{KNOWLEDGE_DOCS_ROOT}/knowledge/lumen-dsl/grammar.md",
    f"{KNOWLEDGE_DOCS_ROOT}/knowledge/lumen-dsl/colors.md",
    f"{KNOWLEDGE_DOCS_ROOT}/knowledge/lumen-dsl/layout.md",
    f"{KNOWLEDGE_DOCS_ROOT}/knowledge/lumen-dsl/text.md",
    f"{KNOWLEDGE_DOCS_ROOT}/knowledge/lumen-dsl/directives.md",
    f"{KNOWLEDGE_DOCS_ROOT}/knowledge/lumen-dsl/diagnostics.md",
    f"{KNOWLEDGE_DOCS_ROOT}/knowledge/design/foundations.md",
    f"{KNOWLEDGE_DOCS_ROOT}/knowledge/images/decide.md",
    f"{KNOWLEDGE_DOCS_ROOT}/knowledge/images/prompts.md",
    f"{KNOWLEDGE_DOCS_ROOT}/knowledge/images/placement.md",
    f"{KNOWLEDGE_DOCS_ROOT}/knowledge/design/artboard-frame-authoring.md",
    f"{KNOWLEDGE_DOCS_ROOT}/knowledge/design/layout-recipes.md",
    f"{KNOWLEDGE_DOCS_ROOT}/knowledge/design/typography-and-composition.md",
    f"{KNOWLEDGE_DOCS_ROOT}/knowledge/design/blocks/README.md",
    f"{KNOWLEDGE_DOCS_ROOT}/knowledge/design/blocks/patterns.md",
    f"{KNOWLEDGE_DOCS_ROOT}/knowledge/design/blocks/layout.md",
    f"{KNOWLEDGE_DOCS_ROOT}/knowledge/design/blocks/actions.md",
    f"{KNOWLEDGE_DOCS_ROOT}/knowledge/design/blocks/data-display.md",
    f"{KNOWLEDGE_DOCS_ROOT}/knowledge/design-systems/token-taxonomy.md",
    f"{KNOWLEDGE_DOCS_ROOT}/knowledge/design-systems/brand-kits.md",
    f"{KNOWLEDGE_DOCS_ROOT}/knowledge/design-systems/brand-validation.md",
    f"{KNOWLEDGE_DOCS_ROOT}/knowledge/design-systems/modes.md",
    f"{KNOWLEDGE_DOCS_ROOT}/knowledge/design-systems/logo-and-assets.md",
    f"{KNOWLEDGE_DOCS_ROOT}/knowledge/design-systems/brand-fit-critique.md",
    f"{KNOWLEDGE_DOCS_ROOT}/knowledge/assets/asset-placement.md",
    f"{KNOWLEDGE_DOCS_ROOT}/knowledge/export/preview-quality.md",
    f"{KNOWLEDGE_DOCS_ROOT}/knowledge/loop/authoring-and-repair.md",
    f"{KNOWLEDGE_DOCS_ROOT}/knowledge/loop/layout-cluster-repair.md",
]

# Product specs are optional background context. The forbidden `docs/` tree is
# never listed here.
SECONDARY_KNOWLEDGE_PATHS = [
    "reference_docs/ABM-Design-Engine-Temporary-Spec.md",
    "reference_docs/Brilliant-Reverse-Engineering-Report.md",
    "reference_docs/Brilliant-vs-Lumen-Product-Gap-Analysis.md",
]

DEFAULT_KNOWLEDGE_PATHS = PRIMARY_KNOWLEDGE_PATHS + SECONDARY_KNOWLEDGE_PATHS
REQUIRED_TASK_CATEGORIES = ["lumen-dsl", "design", "design-systems", "loop"]
ARTBOARD_AUTHORING_PATH = (
    f"{KNOWLEDGE_DOCS_ROOT}/knowledge/design/artboard-frame-authoring.md"
)
LAYOUT_CLUSTER_REPAIR_PATH = (
    f"{KNOWLEDGE_DOCS_ROOT}/knowledge/loop/layout-cluster-repair.md"
)
# The DSL grammar (valid node kinds + property catalogue) and the text reference
# (horizontal-only align — there is NO valign/text_align — plus wrap/max_lines).
GRAMMAR_PATH = f"{KNOWLEDGE_DOCS_ROOT}/knowledge/lumen-dsl/grammar.md"
TEXT_PATH = f"{KNOWLEDGE_DOCS_ROOT}/knowledge/lumen-dsl/text.md"
# The art-direction taste rubric the visual critic scores against (one-dominant /
# squint test, hero-size-per-surface, jump rule, whitespace-as-margin, 60-30-10,
# WCAG contrast, single alignment spine, eyebrow/anti-cliche). Pinned + delivered
# in full so the priors arrive intact, not windowed to a half-rule.
FOUNDATIONS_PATH = f"{KNOWLEDGE_DOCS_ROOT}/knowledge/design/foundations.md"

# Imagery knowledge. `decide` is the cheap guardrail (generate only what you can't
# build) and is pinned for EVERY task so the author always considers whether imagery
# is warranted. `prompts` (5-component prompt craft) and `placement` (cover/focal +
# the text-over-image scrim rule) are pinned only when the task is image-bearing, so
# they don't bloat the context for a pure-typographic card. All three are delivered
# in full when present — a windowed prompt template or half a scrim example misleads.
IMAGES_DECIDE_PATH = f"{KNOWLEDGE_DOCS_ROOT}/knowledge/images/decide.md"
IMAGES_PROMPTS_PATH = f"{KNOWLEDGE_DOCS_ROOT}/knowledge/images/prompts.md"
IMAGES_PLACEMENT_PATH = f"{KNOWLEDGE_DOCS_ROOT}/knowledge/images/placement.md"

# The vetted block catalog: pre-proportioned, compile+preflight-validated blocks
# the author ASSEMBLES (README index + full-artifact patterns + component blocks).
# Pinned for every design task so the author composes vetted blocks instead of
# inventing proportions (the cause of the LUMV0810/0903/0904 overcrowding failures).
BLOCKS_DIR = f"{KNOWLEDGE_DOCS_ROOT}/knowledge/design/blocks"
BLOCK_CATALOG_PATHS = [
    f"{BLOCKS_DIR}/README.md",
    f"{BLOCKS_DIR}/patterns.md",
    f"{BLOCKS_DIR}/layout.md",
    f"{BLOCKS_DIR}/actions.md",
    f"{BLOCKS_DIR}/data-display.md",
]

# Docs delivered to the author IN FULL (not windowed to a best_excerpt). The block
# examples and the grammar/text references must arrive intact — a 1600-char window
# slices a full page+artboard+block example in half and teaches broken syntax.
FULL_DELIVERY_PATHS = {
    GRAMMAR_PATH,
    TEXT_PATH,
    FOUNDATIONS_PATH,
    IMAGES_DECIDE_PATH,
    IMAGES_PROMPTS_PATH,
    IMAGES_PLACEMENT_PATH,
    *BLOCK_CATALOG_PATHS,
}
# Query terms that mark an image-bearing task; when present, the imagery prompt-craft
# and placement docs are force-pinned alongside the always-pinned decide guardrail.
IMAGERY_TERMS = {
    "image",
    "images",
    "imagery",
    "photo",
    "photograph",
    "photography",
    "picture",
    "portrait",
    "hero",
    "background",
    "illustration",
    "illustrations",
    "texture",
    "banner",
    "visual",
    "product shot",
}
LAYOUT_CLUSTER_TERMS = {
    "artboard",
    "background",
    "bounds",
    "canvas",
    "clip",
    "containment",
    "layout_cluster",
    "overflow",
    "parent",
}


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
        excerpt = text if rel_path in FULL_DELIVERY_PATHS else best_excerpt(text, terms)
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
    # The candidate pool must cover every pinned/mandatory path — the mandatory
    # force-select below reads from it — so keep it wide enough to include all
    # default paths even though only `limit` are ultimately selected.
    candidates = read_knowledge(repo_root, query, limit=max(limit * 4, 64), paths=paths)
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

    for rel_path in mandatory_task_paths(query):
        match = next(
            (snippet for snippet in candidates if snippet.path == rel_path),
            None,
        )
        if match is None or match.path in seen_paths:
            continue
        selected.append(
            match.model_copy(update={"selected_reason": "mandatory_task_context"})
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


def mandatory_task_paths(query: str) -> list[str]:
    # Pin the grammar + text references for EVERY task. The category-based
    # selection only guarantees a single highest-scored lumen-dsl doc, and for
    # prompts whose words don't overlap the grammar (e.g. "patient appointment
    # card") the ranker drops grammar/text below the limit. Without them the author
    # hallucinates unsupported syntax — `va(center)` (LUMD0212), a `divider` node
    # kind (LUMD0206) — and wastes the first iteration. Both are PRIMARY paths, so
    # they are always among the candidates this force-selects from.
    paths = [
        GRAMMAR_PATH,
        TEXT_PATH,
        FOUNDATIONS_PATH,
        # The imagery guardrail is cheap and always relevant: the author must decide
        # whether a surface needs an image (and route icon/shape/none correctly)
        # before composing — so it is pinned for every task.
        IMAGES_DECIDE_PATH,
        ARTBOARD_AUTHORING_PATH,
        *BLOCK_CATALOG_PATHS,
    ]
    terms = set(re.split(r"[^a-z0-9_.$-]+", query.lower()))
    if terms & LAYOUT_CLUSTER_TERMS:
        paths.append(LAYOUT_CLUSTER_REPAIR_PATH)
    # Pin the prompt-craft + placement/scrim docs only for image-bearing tasks.
    if terms & IMAGERY_TERMS:
        paths.append(IMAGES_PROMPTS_PATH)
        paths.append(IMAGES_PLACEMENT_PATH)
    return paths


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
    if rel_path.endswith("knowledge_docs/AGENT.md"):
        return "agent"
    docs_marker = "apps/agent_runtime/knowledge_docs/knowledge/"
    if docs_marker in rel_path:
        return rel_path.split(docs_marker, 1)[1].split("/", 1)[0]
    # Legacy layout (still recognized so explicit-path callers keep working).
    if "apps/agent_runtime/knowledge/" in rel_path:
        return rel_path.split("apps/agent_runtime/knowledge/", 1)[1].split("/", 1)[0]
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
