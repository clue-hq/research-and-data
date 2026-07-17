"""Phase A3.1 rename guard — the old tenancy-id vocabulary must stay gone.

The founder-ruled rename collapsed both ``tenant_id`` and ``client_id`` (two names for the same
concept — the tenancy root) into ``workspace_id`` (spec
``docs/specs/PA-phase-a-restructure-and-spine.md`` §A3.1; migration ``b61cd4887129``). This guard
greps the live code tree and fails on any reappearance of either token, so a stray revert, a
copy-paste from an old branch, or a generated snippet can't quietly reintroduce the split
vocabulary.

Scope: ``src/``, ``libs/``, ``scripts/``, and ``tests/`` (this file excepted — it must name the
tokens to hunt them). Deliberately out of scope: ``alembic/versions/`` (history is never
rewritten), ``docs/``, and ``_memory/`` (records of the pre-rename era).

Retained on purpose (and invisible to this guard because neither *token* appears): the
``reuse_scope`` enum value ``'tenant_private'`` and its helpers (they name claim-pooling
semantics, not the id), the ``claimstore/tenancy.py`` filename ("tenancy" is the concept), and
``client_knowledge_ids`` / the Stage-0 "client" domain vocabulary (the client's knowledge base is
a different concept from the tenancy root).
"""

from __future__ import annotations

import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
GUARD_FILE = Path(__file__).resolve()

# The forbidden tokens: tenant_id / client_id as a standalone identifier-ish token. The lookarounds
# (rather than \b) deliberately catch prefixed/suffixed forms like ``_client_id`` / ``x_client_id``
# / ``:client_id`` / ``"tenant_id"`` while ignoring longer identifiers that merely embed the
# letters (``client_ids``, ``client_identity``).
_FORBIDDEN = re.compile(r"(?<![A-Za-z0-9])(tenant_id|client_id)(?![A-Za-z0-9])")

# Genuinely-must-stay exceptions, as (relative path, token) pairs. Keep this EMPTY — the rename is
# total; grow it only with a founder-level ruling.
_ALLOWLIST: frozenset[tuple[str, str]] = frozenset()

_SCAN_DIRS = ("src", "libs", "scripts", "tests")
_SKIP_DIR_NAMES = {"__pycache__", ".pytest_cache", ".mypy_cache", ".ruff_cache", "node_modules"}
_SKIP_SUFFIXES = {".pyc", ".so", ".whl", ".png", ".jpg", ".gif", ".ico", ".lock"}


def _scan_files() -> list[Path]:
    files: list[Path] = []
    for top in _SCAN_DIRS:
        for path in sorted((REPO_ROOT / top).rglob("*")):
            if not path.is_file() or path.suffix in _SKIP_SUFFIXES:
                continue
            if any(part in _SKIP_DIR_NAMES or part.endswith(".egg-info") for part in path.parts):
                continue
            files.append(path)
    return files


def _violations() -> list[str]:
    found: list[str] = []
    for path in _scan_files():
        if path == GUARD_FILE:
            continue  # this guard must spell the tokens out to hunt them
        try:
            text = path.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue  # binary or unreadable — nothing identifier-shaped to guard
        rel = str(path.relative_to(REPO_ROOT))
        for lineno, line in enumerate(text.splitlines(), start=1):
            for match in _FORBIDDEN.finditer(line):
                if (rel, match.group(1)) in _ALLOWLIST:
                    continue
                found.append(f"{rel}:{lineno}: {match.group(1)!r} in: {line.strip()[:100]}")
    return found


def test_no_tenant_id_or_client_id_tokens_remain() -> None:
    violations = _violations()
    assert not violations, (
        "Phase A3.1 renamed both tenant_id and client_id to workspace_id — the old tokens must "
        "not reappear in src/, libs/, scripts/, or tests/ (use workspace_id; see "
        "docs/specs/PA-phase-a-restructure-and-spine.md §A3.1):\n" + "\n".join(violations)
    )


def test_guard_scans_a_meaningful_tree() -> None:
    """The guard is only as good as its file walk — fail loud if the scan comes back implausibly
    small (a moved directory or an over-eager skip rule would otherwise hollow the guard out)."""
    files = _scan_files()
    assert len(files) > 200, f"rename-guard scan found only {len(files)} files — scope broken?"
    tops = {f.relative_to(REPO_ROOT).parts[0] for f in files}
    assert tops == set(_SCAN_DIRS), f"rename-guard missing a scan root: {sorted(tops)}"
