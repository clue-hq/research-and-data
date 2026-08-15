"""Doc R §4 "enforced, not trusted": direct ``logging.getLogger`` is banned outside
``clue_obs`` (the structlog bridge) — everything acquires loggers via ``clue_obs.get_logger``.

``print`` is enforced separately by ruff T20 (with sanctioned per-file ignores).
"""

from __future__ import annotations

import re
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]

_ALLOWED = (REPO / "libs" / "clue-obs" / "clue_obs",)
# The merged design subsystem retains its own observability/tooling contracts until the explicit
# Step-2 integration. Root policy tests must not silently govern its preserved implementation.
_EXCLUDED = (REPO / "subsystems" / "clue-design",)

_PATTERN = re.compile(r"\blogging\.getLogger\s*\(")


def _is_allowed(path: Path) -> bool:
    return any(path.is_relative_to(base) for base in (*_ALLOWED, *_EXCLUDED))


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
