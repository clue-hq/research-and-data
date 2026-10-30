"""Every platform package lumen_agent imports is a declared dependency (review M-6, 2026-10-30).

A fleet worker imports lumen_agent from an installed environment, so an import edge that is not
declared works only by accident of what else is installed. The pyproject's own comment says it
lists real import edges; this keeps it true for the platform packages.
"""

from __future__ import annotations

import re
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_every_imported_clue_package_is_declared() -> None:
    imported: set[str] = set()
    for path in (ROOT / "lumen_agent").rglob("*.py"):
        for match in re.finditer(
            r"^\s*(?:from|import)\s+(clue_[a-z_]+)", path.read_text(encoding="utf-8"), re.M
        ):
            imported.add(match.group(1).replace("_", "-"))
    declared = {
        re.split(r"[<>=\[ ;]", item, maxsplit=1)[0]
        for item in tomllib.loads((ROOT / "pyproject.toml").read_text())["project"]["dependencies"]
    }
    assert imported - declared == set()
