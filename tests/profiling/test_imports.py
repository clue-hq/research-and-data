"""Belt-and-suspenders over ``make contracts``: the profiling package stays import-independent of
the sibling milestone packages it only coordinates with through the claim store (the Beat-0
independence contract). M8 codes against the ``core`` gate/execution protocols; the concrete M7
(``durable``) / M9 (``verification``) implementations are injected at the api root, never imported.
"""

from __future__ import annotations

import ast
import pathlib

_PKG = pathlib.Path(__file__).resolve().parents[2] / "src" / "clue_research" / "profiling"
_FORBIDDEN = ("clue_research.durable", "clue_research.verification")


def _imported_modules(path: pathlib.Path) -> set[str]:
    tree = ast.parse(path.read_text())
    mods: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            mods.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module is not None and node.level == 0:
            mods.add(node.module)
    return mods


def test_profiling_imports_no_sibling_milestone_package() -> None:
    offenders: dict[str, set[str]] = {}
    for py in sorted(_PKG.glob("*.py")):
        bad = {m for m in _imported_modules(py) if m.startswith(_FORBIDDEN)}
        if bad:
            offenders[py.name] = bad
    assert not offenders, f"profiling must not import durable/verification: {offenders}"
