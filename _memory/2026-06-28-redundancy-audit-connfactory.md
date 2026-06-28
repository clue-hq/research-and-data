# 2026-06-28 — Redundancy audit cleanup: ConnFactory/SessionFactory (#60)

Working the redundancy audit in `.context/redundancy-audit-report.md` (78 findings, 4 root
causes). Pulling the safe, high-leverage items one at a time.

## Done this session — audit #60 (commit `5e3ca85`)
Collapsed the single most-duplicated type in the tree:
`Callable[[], AbstractAsyncContextManager[AsyncConnection]]` was hand-declared 12–26× under two
names (`_ConnFactory` private; `SessionFactory` public) + raw inline expansions.

- Declared **once** as `db.ConnFactory` in `db/engine.py` (next to `connection`/`transaction`),
  exported from `db/__init__.py`. `db` is shared-base → freely importable, no contract risk.
- Replaced all 12 private `_ConnFactory` declarations + 10 inline expansions
  (compliance/verification/narrative.positioner) with `from clue_research.db import ConnFactory`,
  used directly (private alias deleted).
- Kept the worker-domain `SessionFactory` name as a **one-line re-export** of `db.ConnFactory` in
  `profiling/runtime.py`, `discovery_scoring/phases.py`, `review/surface.py` (public API → call
  sites untouched; `review.__init__`/`aspect_worker.__all__` re-exports intact).
- `profiling/aspect_worker.py` now imports `SessionFactory` from `profiling/runtime` instead of
  re-declaring it (killed the intra-package duplicate).
- Import cleanup (unused `Callable`/`AbstractAsyncContextManager`/`AsyncConnection`) done by
  `ruff check --fix`; 27 files, net **−69 lines**.

Type-identical: asserted `profiling.runtime.SessionFactory is db.ConnFactory` (same object), so
zero runtime change — annotations only (`from __future__ import annotations` everywhere).

## Verification
- `make check` green: ruff, mypy strict (263 files), import-linter **11/11 kept**.
- Default `pytest` (no DB): 1107 passed, 782 skipped.
- **Clean throwaway DB** (`alembic upgrade head`, deterministic order): **1889 passed / 0 failed /
  14 skipped**.
- Gotcha: running the DB suite against the *shared dev `clue` DB* with `pytest-randomly` shuffling
  surfaces ~7–10 spurious failures (`test_no_domain_tables_at_m0_head` downgrades the DB mid-suite;
  `test_field_registry` sees leftover committed rows). **Pre-existing & identical on baseline**
  (proven by git-stash compare). Always validate DB tests on a fresh DB, not the shared one.

## Follow-up — full collapse to one name (commit `eee1b4c`)
User chose **Option B**: drop the `SessionFactory` name entirely, not keep it as a re-export.
- Deleted the 3 `SessionFactory = ConnFactory` aliases + **deleted `profiling/runtime.py`** (it
  only housed the alias); its 10 importers now import `ConnFactory` from `clue_research.db`.
- Repointed the mixed-import sites (resonance/account ← aspect_worker; review_feedback_wiring /
  review.composition ← review), dropped `SessionFactory` from the `review`/`surface`/`aspect_worker`
  `__all__` + the `review` re-export, renamed every `session_factory: SessionFactory` → `: ConnFactory`
  (param name unchanged), updated the prose.
- **Zero `SessionFactory` left in src or tests.** mypy 262 files (one fewer — runtime.py gone),
  import-linter 11/11, ruff clean, clean-DB suite 1889 passed / 0 failed. Net −42 lines on top of #60.
- Why find-replace alone couldn't do it: it renames the symbol but not the **import module path**
  (`from profiling.runtime import SessionFactory` → must become `from clue_research.db import
  ConnFactory`), and the mixed-import lines (`import DispositionStore, SessionFactory`) need splitting.

## Status of the audit backlog
- **#8** `_conn_factory_default` ×9 → bare `transaction`: DONE (prior commit `45f42bc`).
- **#60** ConnFactory/SessionFactory: DONE — `5e3ca85` (consolidate to `db.ConnFactory` + re-export)
  then `eee1b4c` (full collapse, `SessionFactory` removed; one canonical name).
- **#18** `_to_cost` correctness fix → `core.parse_cost_cents`: DONE — see
  `2026-06-28-redundancy-audit-cost-coercion.md`.
- Not started: the `core`-primitives consolidation batch (#1–6, contract-delta; biggest dedup),
  #32 dead `config.ScoringRubric/SourceProfile`, etc.
