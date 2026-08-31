# 2026-08-07 — Part II slice D0 executed (preflight & contract freeze)

## What landed (branch `platform/design-integration`)
- **Contract doc:** `docs/specs/PD-part2-design-substrate.md` — Part II's frozen implementation
  contract: the D0–D8 slice map + gates, D0 rulings R1–R3, tenancy laws, SQLite→Postgres
  type/idiom rules, the full 22-table → `design_*` map (26 mapped rows; `asset_metadata`
  dropped per O3 draft), open decisions O1–O6 with recommendations, D1/D2 acceptance criteria.
  **O1–O6 are NOT yet ratified — they gate D1; ratify at the D1 discussion before any migration
  is written.**
- **Package skeleton:** `subsystems/design/clue_design` (dist `clue-design`) — empty-but-
  contracted scaffold per the memory/content template (`pyproject.toml`, `__init__.py`,
  `README.md`, `py.typed`). Registered at every root gate in one commit: uv workspace (via the
  `subsystems/*` glob; `uv sync` added it to `uv.lock`), mypy files+path, ruff
  known-first-party, import-linter `root_packages`, the independence contract, the S3-SDK
  containment list, all six plane-purity forbidden lists, the api-layer source list, and a new
  **Rule S4** contract: "design substrate imports only core + db + config + obs + storage"
  (never gateway/locks/spine/toolbelt/agents/execution/fleet/projections). 25 contracts kept.
- **Alembic ruling enshrined:** ONE head `c6d84aa84b79`; first design migration
  `down_revision = "c6d84aa84b79"`. (See `2026-08-07-alembic-single-head-c6d84aa84b79.md`.)
- **Logging-guard carve-out:** `tests/clue_obs/test_logging_discipline.py` now excludes
  `subsystems/clue-design/` — the guard predates the monorepo merge and failed on 9 merged
  design files since 2026-08-07; the master plan Step-2 sanctions exactly this structure-guard
  carve-out (same class as the merge-day ruff exclusion). Removed when Step-2 folds
  `py_lumen_obs` into `clue_obs`.

## Verification
- `uv run alembic heads` → `c6d84aa84b79` (single).
- `uv run mypy` → clean (569 files, now incl. `clue_design`).
- `uv run lint-imports` → 25 kept, 0 broken.
- `uv run ruff check .` → clean; `ruff format --check subsystems/design/` → clean.
- `uv run pytest` → 2174 passed / 1448 skipped after the logging carve-out (the only failure
  before it was that guard, offenders all in `subsystems/clue-design/`).

## Pre-existing red discovered (NOT caused by D0 — owner ruling pending)
**`make lint` fails at `ruff format --check` on 23 M8D-era files at clean `origin/main`**
(verified by stashing all D0 changes and re-running). Files: `alembic/versions/c6d84aa84b79_…`,
`libs/clue-core/clue_core/field.py`, 11 `platform/api/clue_api/*` modules, 2 research modules,
8 test modules. Cause: format drift on the M8D lane (likely a ruff-version mismatch when those
commits landed). Fix is mechanical (`uv run ruff format` on those files, one chore commit) but
touches other lanes' files — **left for the user to rule on.** Until fixed, `make check` is red
at the first target on any branch off main.

## Next: D1 (tenancy + Postgres schema)
Blocked on: user ratification of O1–O6 (see the contract doc §6) + the format-drift ruling.
Then: six reversible `design_*` migrations off `c6d84aa84b79`, enums + parity tests,
immutability triggers, tenancy-isolation test, `make db-smoke` on a clean per-branch DB.
