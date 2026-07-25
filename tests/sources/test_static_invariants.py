"""M4.2 static invariants — enforced WITHOUT a database (no ``require_db`` gate).

These two checks (spec AC §95/§96) are pure: a filesystem scan of ``src/`` and an in-memory scan of
``SEED_MANIFESTS``. They are the invariants with the most value precisely when the DB suite cannot
run, so they live in their own module free of the ``require_db`` mark — they execute on every run.
"""

from __future__ import annotations

from pathlib import Path

from clue_config import redact
from clue_research.sources import SEED_MANIFESTS

_SRC_ROOT = Path(__file__).resolve().parents[2] / "src" / "clue_research"


def test_nothing_outside_sources_or_obs_branches_on_provider() -> None:
    """The 'nothing downstream knows the provider' invariant, made checkable: no module reads
    ``.provider`` except the registry that *owns* the column (sources/, which persists/returns it)
    and observability/billing (obs/). A downstream consumer branching on it would fail here."""
    owner = _SRC_ROOT / "sources"  # the column's owner: defines, persists, and serves it
    offenders: list[str] = []
    for path in _SRC_ROOT.rglob("*.py"):
        if owner in path.parents or "obs" in path.parts:
            continue
        for lineno, line in enumerate(path.read_text().splitlines(), start=1):
            if ".provider" in line:
                offenders.append(f"{path.relative_to(_SRC_ROOT)}:{lineno}: {line.strip()}")
    assert not offenders, "callers must not branch on manifest.provider:\n" + "\n".join(offenders)


def test_seed_auth_refs_are_references_not_secrets() -> None:
    """Every seed ``auth_ref`` is a *reference* (a ``CLUE_*`` env-var name), never a secret value
    (positively shape-checked, plus the redaction heuristic as a backstop)."""
    for entry in SEED_MANIFESTS:
        if entry.auth_ref is not None:
            assert entry.auth_ref.startswith("CLUE_"), entry.source_key
            assert redact(entry.auth_ref) != "***REDACTED***", entry.source_key
