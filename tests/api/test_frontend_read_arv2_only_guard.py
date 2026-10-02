"""The standing rule for the read surface: no legacy research lane on the ARV2 path.

Founder ruling 2026-09-09 — *ARV2's own rows are the only truth; nothing about the old research
lane matters, and no work may be spent preserving it.* D4-b made that structural: the FI-2 readers,
their wire models and the ``?contract=`` selector are gone, and with them every read of the old
lane's tables and governance that the accounts screens used to depend on.

This is a grep rather than a fixture on purpose. The failure mode it guards is a *plausible*
one — someone reaches for ``read_governed_committee`` or ``ContactEligibilityResolver`` because
they resolve a committee, or scopes a status read to ``entity_research_job`` because that table
still exists and still has rows. Both compile, both pass their own unit tests, and both serve an
empty or stale answer on ARV2 data, which is exactly the class of bug no assertion over a seeded
fixture catches.

Comment and docstring lines are allowed: naming what was deleted, and why, is how the next reader
learns the rule instead of rediscovering it.
"""

from __future__ import annotations

import re
from pathlib import Path

_SCANNED = (
    Path(__file__).resolve().parents[2] / "platform" / "api" / "clue_api" / "arv2",
    Path(__file__).resolve().parents[2] / "platform" / "api" / "clue_api" / "frontend_read",
)

#: The old research lane's read surfaces. A hit in scanned code is the defect this file exists for.
_FORBIDDEN: tuple[tuple[str, str], ...] = (
    (r"entity_research_", "the M8D lane's run/job/coverage tables"),
    (r"\baccount_run\b", "the M8A/C orchestrator's per-account run row"),
    (r"research_view", "the C7 research-view read and its governance module"),
    (r"read_governed_committee", "the FI-2 governed committee reader"),
    (r"ContactEligibilityResolver", "the old lane's committee resolver"),
    (r"(?<![\w.])display_allowed\b", "C7's display predicate (ARV2 uses arv2_display_allowed)"),
)

#: The one exception, and why it is not a legacy read: ``provider_call_ledger`` carries the ARV2
#: job id in a column named ``entity_research_job_id`` (``provider_ledger.py``, and the spend sum
#: in ``account_research_store.py``). It is ARV2's own row under an inherited column name, so the
#: *name* matches the pattern while the read does not.
_ALLOWED_SUBSTRINGS = ("entity_research_job_id",)

#: **No file is allowed.** ``answer_key_loader.py`` was the last exception — it seeded the M8D
#: lane's terminal run/job/coverage rows as a database fixture. D4-b task 6 deleted those writes:
#: the answer key now writes one ``arv2_research_run`` and one ``arv2_research_job``, like every
#: other ARV2 run, so the rule holds with no allowlist at all.
_ALLOWED_FILES: tuple[str, ...] = ()


def _is_prose(line: str) -> bool:
    """A comment line, or a line inside prose — the guard is about code, not about naming it."""
    stripped = line.strip()
    return stripped.startswith("#") or stripped.startswith('"""') or stripped.startswith("``")


def _offences() -> list[str]:
    found: list[str] = []
    for root in _SCANNED:
        for path in sorted(root.rglob("*.py")):
            if path.name in _ALLOWED_FILES:
                continue
            in_docstring = False
            for number, line in enumerate(path.read_text().splitlines(), start=1):
                # A crude but sufficient docstring tracker: every module here opens its docstring
                # on line 1 and closes it before any import, and no scanned file nests one.
                if line.count('"""') == 1:
                    in_docstring = not in_docstring
                    continue
                if in_docstring or _is_prose(line):
                    continue
                for pattern, what in _FORBIDDEN:
                    if not re.search(pattern, line):
                        continue
                    if any(allowed in line for allowed in _ALLOWED_SUBSTRINGS):
                        continue
                    found.append(f"{path}:{number}: {what} — {line.strip()}")
    return found


def test_no_legacy_research_lane_read_survives_on_the_arv2_path() -> None:
    offences = _offences()
    assert not offences, "legacy research-lane reads on the ARV2 path:\n" + "\n".join(offences)


def test_the_guard_would_actually_fire() -> None:
    """Without this, a broken scanner (a bad path, a swallowed exception) passes vacuously."""
    assert _SCANNED[0].is_dir() and _SCANNED[1].is_dir()
    assert sum(1 for root in _SCANNED for _ in root.rglob("*.py")) > 10
    assert re.search(_FORBIDDEN[3][0], "await read_governed_committee(conn)")
    assert re.search(_FORBIDDEN[5][0], "if display_allowed(claim, policy):")
    # …and that the ARV2 predicate is not caught by the C7 one's pattern.
    assert not re.search(_FORBIDDEN[5][0], "if arv2_display_allowed(claim, policy):")


def test_the_contract_selector_no_longer_exists() -> None:
    """One contract: ``?contract=`` selects nothing, so nothing may still resolve it."""
    import clue_api.frontend_read.app as app

    assert not hasattr(app, "contract_mode")
    assert not hasattr(app, "ContractDep")
    assert not hasattr(app, "ContractMode")
