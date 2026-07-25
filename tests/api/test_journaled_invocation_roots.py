"""Production composition roots cannot bypass the C5.1 journaled invoker."""

from __future__ import annotations

from pathlib import Path


def test_bare_invoke_tool_is_confined_to_toolbelt_internal_runner() -> None:
    root = Path(__file__).resolve().parents[2]
    production_roots = (
        root / "platform" / "api",
        root / "platform" / "execution",
        root / "subsystems",
    )
    offenders: list[str] = []
    for production_root in production_roots:
        for path in production_root.rglob("*.py"):
            body = path.read_text()
            if "invoke_tool(" in body:
                offenders.append(str(path.relative_to(root)))
    assert offenders == []
