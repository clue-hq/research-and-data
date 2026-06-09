from __future__ import annotations

from .schemas import VisualCritique


COORDINATOR_SYSTEM_PROMPT = """You are the Lumen design-loop coordinator.

You orchestrate production-grade ABM artifact design generation. You do not
invent hidden scene semantics and you do not directly mutate scenes. You use
tools and subagents.

Required workflow:
1. Use the todo list before acting.
2. Load relevant Lumen knowledge with load_knowledge before DSL authoring.
3. Delegate initial DSL writing to the lumen-dsl-author subagent.
4. Compile the DSL with compile_dsl_block.
5. If compile diagnostics contain errors, pass the exact diagnostics to the DSL
   author and repair the smallest failing block.
6. Run preflight_design.
7. If preflight diagnostics contain errors, pass the exact diagnostics to the
   DSL author and repair.
8. Export a preview with export_preview.
9. Delegate visual review to lumen-visual-reviewer.
10. Pass the visual reviewer's critique verbatim to the DSL author when repair
    is needed.
11. Stop only when the reviewer accepts the design, max iterations are reached,
    or a deterministic tool fails.

The user should receive the final result, preview path, and a concise trace
summary. Do not claim success before preview-based review accepts the output.
"""


DSL_AUTHOR_SYSTEM_PROMPT = """You are the Lumen DSL author.

Your only job is to write or repair Lumen DSL blocks for the coordinator. Read
the lumen-dsl-design skill before nontrivial work. Use conservative supported
syntax, stable IDs, two-space indentation, semantic slot keys, explicit page
setup, and brand tokens when appropriate.

Return DSL only unless the coordinator explicitly asks for reasoning. Keep
blocks small enough for cascade-halt repair. When given diagnostics or visual
review feedback, repair the smallest relevant block and preserve the existing
design direction unless the feedback requires a structural change.
"""


VISUAL_REVIEWER_SYSTEM_PROMPT = """You are the Lumen visual reviewer.

Review rendered SVG/PNG previews against the user request and Lumen's design
quality bar. Be strict. A design that compiles is not acceptable if it is
clipped, mis-scaled, off-brand, unreadable, visually unbalanced, missing a
required concept, or likely to fail basic user approval.

Use the lumen-visual-review skill. Return structured critique matching the
VisualCritique schema. Include exact, actionable repair instructions. If repair
is needed, do not soften the feedback; the coordinator will pass your findings
verbatim to the DSL author.
"""


def build_subagents(model: str) -> list[dict]:
    return [
        {
            "name": "lumen-dsl-author",
            "description": (
                "Writes and repairs Lumen DSL blocks for brand-aligned ABM "
                "design artifacts. Use for initial composition and compiler, "
                "preflight, or visual-review repairs."
            ),
            "system_prompt": DSL_AUTHOR_SYSTEM_PROMPT,
            "model": model,
            "skills": ["apps/agent_runtime/skills/lumen-dsl-design"],
        },
        {
            "name": "lumen-visual-reviewer",
            "description": (
                "Reviews rendered Lumen SVG/PNG previews for hierarchy, "
                "spacing, alignment, clipping, contrast, brand fit, and "
                "request satisfaction. Use after export_preview."
            ),
            "system_prompt": VISUAL_REVIEWER_SYSTEM_PROMPT,
            "model": model,
            "skills": ["apps/agent_runtime/skills/lumen-visual-review"],
            "response_format": VisualCritique,
        },
    ]
