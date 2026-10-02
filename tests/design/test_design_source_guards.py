"""Part II D8 (ruling R-D8-5) — two source-level guards, promoted from human greps to tests.

Both are **textual** guards in the style of the design API's ``test_write_path_governance.py``: they
read the repository's own source and refuse a class of regression that no runtime test can see. Both
are deliberately offline (no DB gate), because a source-level regression must fail in the ordinary
``make check``, not only where a Postgres happens to be configured.

1. :func:`test_design_run_event_stays_retired` — D7 dropped the ``design_run_event`` table and D7's
   close-out verified the retirement **by hand**, with a grep whose result was written into a memory
   note. A verification that lives in a memory note is a verification that decays; this is the same
   grep, with its allowlist enumerated, so the next reference to the retired substrate fails a test
   instead of surviving unnoticed.
2. :func:`test_production_design_code_has_no_sqlite_beyond_the_ratified_exemption` — D2.5B deleted
   the SQLite substrate from the design API but deliberately kept ``sqlite3`` as the API's
   *constraint-violation exception family*, so the shipped 409 DTOs did not have to be rewritten in
   the same slice. This pins that exemption to the exact three modules that hold it, so a fourth
   cannot appear and so the retained sites cannot quietly grow a real SQLite connection.
"""

from __future__ import annotations

import re
import tokenize
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[2]

#: Where design code lives, in every tree it lives in. ``alembic`` is included because the retired
#: table's DDL history is there and must stay reachable to the guard rather than exempt from it.
_SCAN_ROOTS = (
    "subsystems/clue-design/apps",
    "subsystems/design/clue_design",
    "platform",
    "libs",
    "tests",
    "alembic",
)

#: Never scanned: prose about the retirement is the *point* of these directories, and vendored or
#: generated trees are not ours to govern.
_SKIP_PARTS = frozenset(
    {"_memory", "docs", ".context", "node_modules", "__pycache__", ".venv", "target", "dist"}
)


def _python_sources() -> list[Path]:
    found: list[Path] = []
    for root in _SCAN_ROOTS:
        base = _REPO_ROOT / root
        if not base.exists():
            continue
        for path in base.rglob("*.py"):
            if _SKIP_PARTS & set(path.relative_to(_REPO_ROOT).parts):
                continue
            found.append(path)
    return sorted(found)


def _rel(path: Path) -> str:
    return str(path.relative_to(_REPO_ROOT))


# --- guard 1: the retired ``design_run_event`` substrate ------------------------------------------

#: The retired TABLE's exact name, matched as a whole word. The boundary is what makes the guard
#: usable rather than merely loud: the live emitter ``emit_design_run_event``, the D8 retention
#: knobs ``design_run_event_{prune_interval,retention}_s`` and the migrations' index/constraint
#: names ``design_run_event_run`` / ``design_run_event_seq_unique`` are all *different identifiers*
#: that happen to share a prefix or suffix, and none of them is a reference to the dropped table.
_RETIRED_TABLE = re.compile(r"(?<![A-Za-z0-9_])design_run_event(?![A-Za-z0-9_])")

#: Every file allowed to still name the retired table as a bare word, and why.
_DESIGN_RUN_EVENT_ALLOWLIST: dict[str, str] = {
    # The DDL history. Frozen by definition: a migration is a record of what happened.
    "alembic/versions/e79f192828b1_design_runs_events_ingestion_part2_d1f.py": (
        "D1f created the table (labelled TEMPORARY — 'dies at D7' in its own COMMENT)"
    ),
    "alembic/versions/eb9c5b963f40_d7_drop_design_run_event.py": (
        "the D7 drop migration; its downgrade() must be able to recreate the table"
    ),
    # Historical docstrings — each explains what the platform outbox REPLACED, which is the one
    # thing a reader of the successor code most needs to know.
    "libs/clue-core/clue_core/run_event.py": (
        "explains that the free event vocabulary moved into the payload when the table died"
    ),
    "subsystems/design/clue_design/runs.py": "records that D7 retired the run's event log",
    "subsystems/design/clue_design/sequences.py": (
        "records that the third seq allocator died with the table"
    ),
    "subsystems/clue-design/apps/api/lumen_api/run_stream.py": (
        "the successor module: names what it replaced and pins the byte-for-byte editor contract"
    ),
    "subsystems/clue-design/apps/api/lumen_api/design_store.py": (
        "the snapshot facade's docstring names the row shape it preserves"
    ),
    "subsystems/clue-design/apps/api/lumen_api/toolbelt/wiring.py": (
        "explains why the D6 no-op transport became a real writer at D7"
    ),
    "subsystems/clue-design/apps/api/tests/test_write_path_governance.py": (
        "explains the D7 rename of the governed run-lifecycle write"
    ),
    "tests/design/test_dal_foundation_db.py": "asserts the table is GONE (to_regclass IS NULL)",
    "tests/design/test_runs_dal_db.py": (
        "contrasts the retired per-run seq allocator with the outbox"
    ),
    "tests/design/test_design_source_guards.py": "this guard",
}


def _design_run_event_hits(path: Path) -> list[tuple[int, str]]:
    """Lines naming the retired table as a whole word."""
    return [
        (number, line.strip())
        for number, line in enumerate(path.read_text().splitlines(), start=1)
        if _RETIRED_TABLE.search(line)
    ]


def test_design_run_event_stays_retired() -> None:
    """No file outside the enumerated allowlist may mention the dropped table."""
    offences = {
        _rel(path): hits
        for path in _python_sources()
        if (hits := _design_run_event_hits(path)) and _rel(path) not in _DESIGN_RUN_EVENT_ALLOWLIST
    }
    assert not offences, (
        "``design_run_event`` was dropped at D7; these files reference it and are not on the "
        "allowlist (add a live reference only with a ruling, and a historical one with a reason):\n"
        + "\n".join(
            f"  {name}\n    " + "\n    ".join(f"{n}: {line}" for n, line in hits)
            for name, hits in offences.items()
        )
    )


def test_the_retirement_allowlist_has_no_dead_entries() -> None:
    """An allowlist that outlives its reasons stops being a guard and becomes decoration."""
    stale = [
        name
        for name in _DESIGN_RUN_EVENT_ALLOWLIST
        if not (_REPO_ROOT / name).exists() or not _design_run_event_hits(_REPO_ROOT / name)
    ]
    assert not stale, f"allowlisted files that no longer mention design_run_event: {stale}"


def test_no_design_source_uses_design_run_event_as_a_python_identifier() -> None:
    """The allowlist governs *mentions*; this governs *use*.

    Every surviving mention must be prose — a comment, a docstring, or a SQL string in a frozen
    migration. A bare ``NAME`` token would mean live Python bound to the retired substrate, which no
    amount of allowlisting should permit.
    """
    offences: dict[str, list[str]] = {}
    for path in _python_sources():
        if not _design_run_event_hits(path):
            continue
        with path.open("rb") as handle:
            for token in tokenize.tokenize(handle.readline):
                if token.type != tokenize.NAME:
                    continue
                if token.string == "design_run_event":
                    offences.setdefault(_rel(path), []).append(
                        f"{token.start[0]}: {token.line.strip()}"
                    )
    assert not offences, f"live Python identifiers named after the retired table: {offences}"


# --- guard 2: the design API's SQLite exemption ---------------------------------------------------

#: Production design code. Tests are excluded deliberately — two design API tests import ``sqlite3``
#: to assert the exception-family behaviour below, which is the exemption working, not breaking it.
_PRODUCTION_DESIGN_ROOTS = (
    "subsystems/clue-design/apps/api/lumen_api",
    "subsystems/clue-design/apps/api/lumen_ingestion",
    "subsystems/design/clue_design",
)

#: The exemption, enumerated exactly as it exists today (D2.5B kept the *exception family*, not the
#: database). The actual cut — replacing ``sqlite3.IntegrityError`` with a design-owned error type —
#: is Step-2 hygiene work, recorded in ``_memory/2026-08-08-part2-d25b-sqlite-deletion.md``; D8
#: ratifies the exemption as-is and pins its blast radius so it cannot grow while it waits.
_SQLITE_EXEMPT: dict[str, str] = {
    "subsystems/clue-design/apps/api/lumen_api/main.py": (
        "@app.exception_handler(sqlite3.Error) — the app-level 409/500 mapping the shipped DTOs "
        "are written against"
    ),
    "subsystems/clue-design/apps/api/lumen_api/design_store.py": (
        "raises sqlite3.IntegrityError when the Postgres DAL reports a constraint violation, so "
        "the handler above and every route's 409 shape are unchanged by the substrate swap"
    ),
    "subsystems/clue-design/apps/api/lumen_api/custom_component_compiler.py": (
        "except (..., sqlite3.Error) around the compile persist — the same exception family"
    ),
}


def _production_design_sources() -> list[Path]:
    found: list[Path] = []
    for root in _PRODUCTION_DESIGN_ROOTS:
        base = _REPO_ROOT / root
        if not base.exists():
            continue
        found.extend(
            path
            for path in base.rglob("*.py")
            if "__pycache__" not in path.parts and "tests" not in path.parts
        )
    return sorted(found)


def test_production_design_code_has_no_sqlite_beyond_the_ratified_exemption() -> None:
    """``import sqlite3`` only in the three exempt modules; ``sqlite3.connect(`` nowhere at all."""
    importers: list[str] = []
    connectors: list[str] = []
    for path in _production_design_sources():
        text = path.read_text()
        if "sqlite3.connect(" in text:
            connectors.append(_rel(path))
        for line in text.splitlines():
            if line.strip().startswith(("import sqlite3", "from sqlite3 import")):
                importers.append(_rel(path))
                break

    assert not connectors, (
        "production design code opened a SQLite database; the design substrate is Postgres only "
        f"(D2.5B deleted SQLite): {connectors}"
    )
    assert sorted(importers) == sorted(_SQLITE_EXEMPT), (
        "the D8-ratified sqlite3 exemption is exactly the three modules that keep sqlite3 as the "
        "API's constraint-violation EXCEPTION family. Changed set:\n"
        f"  found:    {sorted(importers)}\n"
        f"  exempted: {sorted(_SQLITE_EXEMPT)}"
    )
