"""Recipe gates for quality research behaviour, read from the job's pinned input refs.

Recipe 26 is phase-1 waste removal (docs/superpowers/plans/2026-10-07-research-cost-phase1.md).
Recipe 27 aligns every people-finding instruction on early discovery (run 3 vs run 4 post-mortem,
docs/reports/2026-10-10-dialpad-run3-vs-run4-postmortem.md). A job pinned to an earlier recipe keeps
exactly its old behaviour.
"""

from typing import Any, Final

RECIPE_26: Final = 26
RECIPE_27: Final = 27


def recipe_of(scope: Any) -> int:
    return int((getattr(scope, "input_refs", None) or {}).get("quality_recipe_version") or 0)


def at_least(scope: Any, version: int) -> bool:
    return recipe_of(scope) >= version
