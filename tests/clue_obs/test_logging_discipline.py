"""Doc R §4 "enforced, not trusted": direct ``logging.getLogger`` is banned outside
``clue_obs`` (the structlog bridge) — everything acquires loggers via ``clue_obs.get_logger``.

``print`` is enforced separately by ruff T20 (with sanctioned per-file ignores).
"""

from __future__ import annotations

import re
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]

_ALLOWED = (
    REPO / "libs" / "clue-obs" / "clue_obs",
    # The merged design-subsystem tree keeps its own toolchain (incl. py_lumen_obs) until
    # Part-I Step-2 hygiene folds it into the clue libs — the master plan's sanctioned
    # structure-guard carve-out (docs/specs/design-integration-master-plan.md, Step 2),
    # pulled forward at Part-II D0 because the guard predates the merge.
    REPO / "subsystems" / "clue-design",
)

_PATTERN = re.compile(r"\blogging\.getLogger\s*\(")


def _is_allowed(path: Path) -> bool:
    return any(path.is_relative_to(base) for base in _ALLOWED)


def test_no_direct_logging_getlogger_outside_clue_obs() -> None:
    offenders: list[str] = []
    for root in (REPO / "subsystems", REPO / "platform", REPO / "libs", REPO / "scripts"):
        if not root.exists():
            continue
        for path in root.rglob("*.py"):
            if _is_allowed(path):
                continue
            if _PATTERN.search(path.read_text(encoding="utf-8")):
                offenders.append(str(path.relative_to(REPO)))
    assert not offenders, (
        f"direct logging.getLogger outside clue_obs — use clue_obs.get_logger: {sorted(offenders)}"
    )
