"""C7.1 evidence-access dependency boundary.

Evidence action descriptors are safe data. Only the future API-root evidence-access service may
turn an authorized artifact action into a short-lived storage preview; routes/tools and core
contracts may not presign directly.
"""

from __future__ import annotations

from pathlib import Path

_ROOT = Path(__file__).resolve().parents[2]
_API_ROOT = _ROOT / "platform/api/clue_api"
_AUTHORIZED_SERVICE = _API_ROOT / "evidence_access.py"


def test_only_authorized_evidence_service_may_call_storage_presign() -> None:
    offenders: list[str] = []
    for path in sorted(_API_ROOT.rglob("*.py")):
        if path == _AUTHORIZED_SERVICE:
            continue
        source = path.read_text(encoding="utf-8")
        if ".presign(" in source:
            offenders.append(str(path.relative_to(_ROOT)))
    assert offenders == []


def test_core_evidence_contract_does_not_depend_on_storage() -> None:
    source = (_ROOT / "libs/clue-core/clue_core/research_view.py").read_text(encoding="utf-8")
    assert "clue_storage" not in source
    assert ".presign(" not in source


def test_c7_has_no_unsafe_body_cache() -> None:
    """C7.8 forbids solving read latency by caching research/evidence bodies."""

    roots = (
        _ROOT / "platform/api/clue_api",
        _ROOT / "platform/projections/clue_projections",
        _ROOT / "subsystems/research/clue_research/narrative",
    )
    sources = "\n".join(
        path.read_text(encoding="utf-8")
        for root in roots
        for path in root.glob("*.py")
        if path.name != "__pycache__"
    ).lower()
    assert "research_view_projection_cache" not in sources
    assert "research_view_body_cache" not in sources
    assert "evidence_body_cache" not in sources
