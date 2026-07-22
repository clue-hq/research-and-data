"""§1a stage-2 rename guard — the ``campaign_run`` vocabulary is dead; allowlist EMPTY.

The A3.1-style lock on the 2026-07-22 stage-2 rename (`docs/specs/PB-rename-campaign-run-to-
project-run.md` §5): no ``campaign_run`` / ``CampaignRun`` / ``CampaignPhase`` (or screaming
``CAMPAIGN_RUN``) token may reappear anywhere in the five code roots. Complements
``tests/test_workspace_rename_guard.py`` (A3.1) and ``tests/test_structure_guards.py``.

Deliberately guarded / not guarded:

* **Bare ``campaign`` is NOT guarded** — it remains a valid concept (a channel program within a
  project: "per-campaign hard cap", ``set_campaign_cap``, campaign artifacts). Only the *run*
  vocabulary flipped.
* **``campaign_phase`` (lowercase) is NOT guarded** — the ``IdempotencyScope.PROJECT_PHASE``
  *value string* is frozen durable ledger data (``"campaign_phase"`` is baked into every M7.4
  ledger key at rest; playbook §4.5) and legitimately appears where that value is asserted.
  The class name ``CampaignPhase`` IS guarded (it renamed to ``ProjectPhase``).
* ``alembic/versions/`` is outside the scan roots — history is immutable and keeps old names.
"""

from __future__ import annotations

import re
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]

_PATTERN = re.compile(r"campaign_run|CampaignRun|CampaignPhase|CAMPAIGN_RUN")

_SCAN_ROOTS = ("libs", "subsystems", "platform", "tests", "scripts")

# Empty by design (playbook §5): any hit is a regression, not an exception to record.
_ALLOWLIST: frozenset[str] = frozenset()


def test_no_campaign_run_vocabulary_survives() -> None:
    offenders: list[str] = []
    scanned = 0
    for root in _SCAN_ROOTS:
        base = REPO / root
        assert base.is_dir(), f"scan root missing: {root}/ (guard would pass vacuously)"
        for path in base.rglob("*.py"):
            if path == Path(__file__):
                continue
            scanned += 1
            if _PATTERN.search(path.read_text(encoding="utf-8")):
                rel = str(path.relative_to(REPO))
                if rel not in _ALLOWLIST:
                    offenders.append(rel)
    # Scan-scope sanity: a mis-pathed guard must not pass by scanning nothing (the zsh
    # no-word-split trap that hid this rename's own scope measurement is the live example).
    assert scanned > 400, f"guard scanned only {scanned} files — scan scope is broken"
    assert not offenders, (
        f"campaign_run vocabulary reappeared (§1a stage-2 rename, allowlist empty): "
        f"{sorted(offenders)}"
    )
