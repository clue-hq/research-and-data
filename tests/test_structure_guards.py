"""Phase A structure guards (Doc R R1/R2, executed 2026-07-17).

The shim-less promotion (approved deviation) is locked by grep, not convention: no import of a
moved package's old ``clue_research.<pkg>`` path may reappear anywhere. Complements
``tests/test_workspace_rename_guard.py`` (the vocabulary guard) and the import-linter contracts
(the dependency-direction guards).
"""

from __future__ import annotations

import re
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]

# Packages promoted out of clue_research in Phase A (old dotted path is dead vocabulary).
# "api" joined at R3 (2026-07-21): clue_research/api -> platform/api (clue_api).
_MOVED = ("core", "db", "config", "gateway", "locks", "obs", "api")
_PATTERN = re.compile(r"\bclue_research\.(?:" + "|".join(_MOVED) + r")\b")

_SCAN_ROOTS = ("subsystems", "platform", "libs", "scripts", "tests")


def test_no_old_lib_import_paths_survive() -> None:
    offenders: list[str] = []
    for root in _SCAN_ROOTS:
        base = REPO / root
        if not base.exists():
            continue
        for path in base.rglob("*.py"):
            if path == Path(__file__):
                continue
            if _PATTERN.search(path.read_text(encoding="utf-8")):
                offenders.append(str(path.relative_to(REPO)))
    assert not offenders, (
        f"old clue_research.<lib> paths survive (libs moved at Doc R R1): {sorted(offenders)}"
    )
