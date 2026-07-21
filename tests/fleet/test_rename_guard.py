"""Interim §1a rename guard (stage 1) — legacy campaign_run tokens are pinned to the marked
stage-1 exceptions, structurally, until stage 2's full guard lands.

The fleet lane is already ``project_run_id``-native (see ``docs/specs/PB-B1-fleet-worker.md``
§"§1a vocabulary"), with a *small, deliberate* set of legacy ``campaign_run`` / ``CampaignRun*``
tokens that must stay until the whole-repo stage-2 rename
(``docs/specs/PB-rename-campaign-run-to-project-run.md``): the seam parameter names
conformance-tested against the untouchable ``durable.CampaignRun`` (marked with
``# §1a rename: flips at stage 2``), and the durable/core types the fleet surfaces import
(``CampaignRunId``/``CampaignPhase``/``CampaignRunRow``/``CampaignRunStatus``/``CampaignRun``/
``DbCampaignRunStore``).

This is the interim, weaker cousin of stage 2's empty-allowlist guard: it makes "these are the
ONLY legacy tokens on the lane" a build invariant, so a revived ``CampaignRunWorker`` or a new,
unmarked ``campaign_run_*`` usage fails the build *now*, and the snake-tier allowlist is forced to
shrink toward empty as stage 2 lands (a file that drops below its snapshot fails until the
allowlist entry is pruned). It is intentionally scoped to the two fleet roots only.

Two tiers, over ``platform/fleet/**/*.py`` + ``tests/fleet/**/*.py`` (this guard file excluded):

1. **CamelCase** — every ``CampaignRun\\w*`` / ``CampaignPhase`` match must be one of the exact
   allowed imported names below (built from what the fleet surfaces import today). Anything else
   (a new ``CampaignRunFoo``, a revived worker class) fails.
2. **snake** — every file's ``campaign_run\\w*`` occurrence count must equal its snapshot from the
   current tree. Over the count = new unmarked usage; under = stale allowlist (shrink it); a file
   carrying the token but absent from the allowlist = fail. (Note ``\\b`` does not match inside
   ``new_campaign_run_id`` — that helper is preceded by ``_`` — so those calls are not counted;
   the snapshot reflects only standalone ``campaign_run*`` tokens.)
"""

from __future__ import annotations

import re
from pathlib import Path

_PLAYBOOK = "docs/specs/PB-rename-campaign-run-to-project-run.md"
_REPO_ROOT = Path(__file__).resolve().parents[2]
_ROOTS = ("platform/fleet", "tests/fleet")
_GUARD_FILE = Path(__file__).resolve()

# --- CamelCase tier ----------------------------------------------------------------------------

# Lookaround-free but boundary-anchored (compounds like a revived ``CampaignRunWorker`` are caught
# by the greedy ``\w*``); ``DbCampaignRunStore`` intentionally does NOT match (no word boundary
# before ``Campaign``), so it never trips this tier even though it is an allowed import.
_CAMEL_RE = re.compile(r"\bCampaignRun\w*|\bCampaignPhase\b")

# The exact set of allowed imported durable/core names the fleet surfaces use today.
_ALLOWED_CAMEL = frozenset(
    {
        "CampaignRunId",  # core run-id type
        "CampaignPhase",  # core phase enum
        "CampaignRun",  # durable state machine (the RunDriver conformance target)
        "CampaignRunRow",  # durable run row
        "CampaignRunStatus",  # durable status enum
        "DbCampaignRunStore",  # durable store (exit-gate harness); listed for intent
    }
)

# --- snake tier --------------------------------------------------------------------------------

_SNAKE_RE = re.compile(r"\bcampaign_run\w*")

# Per-file occurrence-count snapshot of the CURRENT tree (relative posix paths). Shrinks to empty
# as stage 2 flips each marked exception; a file dropping below its count fails until pruned here.
_SNAKE_ALLOWLIST: dict[str, int] = {
    "platform/fleet/clue_fleet/worker.py": 3,
    "platform/fleet/clue_fleet/lease.py": 1,
    "platform/fleet/clue_fleet/scheduler.py": 7,
    "tests/fleet/conftest.py": 2,
    "tests/fleet/exit_gate_harness.py": 3,
    "tests/fleet/test_worker_loop.py": 4,
    "tests/fleet/test_scheduler.py": 12,
    "tests/fleet/test_exit_gate.py": 4,
    "tests/fleet/test_fleet_db.py": 5,
}


def _scanned_files() -> list[Path]:
    files: list[Path] = []
    for root in _ROOTS:
        files.extend(p for p in (_REPO_ROOT / root).rglob("*.py") if p.resolve() != _GUARD_FILE)
    return files


def test_scan_scope_sanity() -> None:
    """A mis-pathed scan must not pass vacuously (the zsh no-word-split trap that once hid this
    rename's own measurement): both roots produce files, and more than ten in total."""
    files = _scanned_files()
    for root in _ROOTS:
        root_abs = str((_REPO_ROOT / root).resolve())
        assert any(str(p.resolve()).startswith(root_abs) for p in files), f"{root} not scanned"
    assert len(files) > 10, f"expected >10 fleet-lane files, scanned {len(files)}"


def test_camelcase_tokens_are_only_allowed_imported_names() -> None:
    offenders: dict[str, set[str]] = {}
    for path in _scanned_files():
        bad = {
            m
            for m in _CAMEL_RE.findall(path.read_text(encoding="utf-8"))
            if m not in _ALLOWED_CAMEL
        }
        if bad:
            offenders[path.relative_to(_REPO_ROOT).as_posix()] = bad
    assert not offenders, (
        f"disallowed CampaignRun*/CampaignPhase token(s) on the fleet lane: {offenders}. Stage 1 "
        f"pins these to the allowed imported names {set(_ALLOWED_CAMEL)}; do not revive a "
        f"campaign_run-named symbol — the whole-repo rename is {_PLAYBOOK}."
    )


def test_snake_tokens_match_the_stage1_snapshot() -> None:
    errors: list[str] = []
    seen: set[str] = set()
    for path in _scanned_files():
        rel = path.relative_to(_REPO_ROOT).as_posix()
        count = len(_SNAKE_RE.findall(path.read_text(encoding="utf-8")))
        if count == 0:
            continue
        seen.add(rel)
        expected = _SNAKE_ALLOWLIST.get(rel)
        if expected is None:
            errors.append(f"{rel}: {count} campaign_run token(s), not in the stage-1 allowlist")
        elif count > expected:
            errors.append(
                f"{rel}: {count} campaign_run tokens > snapshot {expected} (new unmarked usage)"
            )
        elif count < expected:
            errors.append(
                f"{rel}: {count} campaign_run tokens < snapshot {expected} "
                "(stage 2 progressed — shrink this allowlist entry)"
            )
    for rel in _SNAKE_ALLOWLIST:
        if rel not in seen:
            errors.append(f"{rel}: allowlisted but no campaign_run token found (stale — remove it)")
    assert not errors, f"stage-1 §1a snake-token drift (see {_PLAYBOOK} §4.4):\n  " + "\n  ".join(
        errors
    )


def test_guard_catches_a_violation() -> None:
    """Self-check (no planted violation committed to the tree): the guard's own tiers flag a
    revived ``CampaignRunWorker`` and any surplus ``campaign_run`` token on a synthetic string."""
    synthetic = "class CampaignRunWorker: ...\nx = campaign_run_id\n"
    bad_camel = {m for m in _CAMEL_RE.findall(synthetic) if m not in _ALLOWED_CAMEL}
    assert bad_camel == {"CampaignRunWorker"}
    # A file snapshotted at 0 (or absent) carrying a token is a snake-tier failure.
    assert len(_SNAKE_RE.findall(synthetic)) == 1
    # And ``new_campaign_run_id`` is deliberately NOT counted (no boundary before ``campaign``).
    assert _SNAKE_RE.findall("new_campaign_run_id()") == []
