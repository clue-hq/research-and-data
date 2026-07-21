# 2026-07-21 — R3 (api → platform/api) + Phase B worktree briefs

Branch `platform/workspace-restructure`. Phase A closed earlier today (see
`2026-07-21-budget-tracker-dry.md` and the deferral close-out commits). This session executed
**Doc R R3** and ratified the **Phase B parallelization plan** with the founder.

## Founder rulings this session
1. **Proceed with R3 now** (before any Phase B code), because both B1 and B2 would otherwise
   commit wiring into a directory about to move.
2. **Three parallel worktrees for Phase B** — B1 fleet worker (step 0), B2 storage (step 1),
   B3 memory slice 1 (Doc M). **They integrate back onto `platform/workspace-restructure`
   itself**, not a separate integration branch. B4 (step 2, toolbelt/projections/SSE) opens
   after B1 integrates.
3. **Commit a scope/treaty reference doc** the worktrees read to avoid accidental overlap →
   `docs/specs/PB-phase-b-platform-infra-core.md` (the authoritative brief: current state,
   per-lane owned surfaces, the four append-only shared surfaces, integration order B2→B3→B1,
   standing gates incl. the scripts/01–06 Recipe-#1 regression).
4. Millicredit groundwork in B2 is **additive-only** (no `durable/budget.py` / `budget_event` /
   ledger-schema changes — B1 builds against those); if ledger changes are needed they land
   serially after B1.
5. No worktree commits `clue_api` wiring — wiring commits are written at integration on the
   integration branch by the integrator.

## R3 — what was done (move-only + config)
- `git mv subsystems/research/clue_research/api` → **`platform/api/clue_api`**; new
  `platform/api/pyproject.toml` (`clue-api`: deps clue-research/core/config/db/obs + fastapi —
  fastapi moved OUT of clue-research's deps, api was its only user); `py.typed` added.
- Global rewrite `clue_research.api` → `clue_api` (53 files: api internals, tests, scripts
  01–06, two docstring-only subsystem references in `durable/budget.py` + `narrative/fields.py`).
- Root `pyproject.toml`: first-party/mypy files/`mypy_path` (+`platform/api` — omitting it broke
  mypy with "source file found twice")/root_packages += clue_api; import-linter contracts renamed
  and Rule 5 **simplified**: sources are now every other workspace package (api is top-level, no
  more clue_research subpackage enumeration); Rule 2b forbids libs→clue_api; Rule S2 forbids
  agents→clue_api.
- Guards updated: `tests/test_structure_guards.py` `_MOVED` += "api" (old dotted path is dead
  vocabulary); `tests/test_package_layout.py` `_SPECIAL_HOMES["api"]` → platform/api/clue_api.
- `docs/specs/README.md`: added the harness-era phase table (PA closed, PB open).

## Verification (all green at the R3 commit)
- `make check`: ruff clean · mypy 281 files · import-linter **16 kept, 0 broken** · offline
  suite 1158 passed / 794 skipped.
- Full DB suite on `clue`: **1938 passed, 14 skipped** (matches pre-move baseline).
- `make db-smoke` on throwaway `clue_r3_smoke` (created, smoked up→down→up, dropped): green.

## Follow-ups / notes for the B-worktrees
- Branch names: `platform/b1-fleet-worker`, `platform/b2-storage`, `platform/b3-memory`, cut
  from the R3 commit. Read `docs/specs/PB-phase-b-platform-infra-core.md` FIRST — it is the
  scope treaty; §3 lists the only four files/surfaces two lanes may both touch (append-only).
- Each lane writes its own `docs/specs/PB-B<n>-….md` spec before implementation (M0–M13
  workflow) and keeps a `_memory/` session note.
- Postgres is local (Homebrew, localhost:5432, user `clue`/`clue`); per-branch throwaway DBs
  for db-smoke (`CREATE DATABASE clue_<slice>_smoke OWNER clue`), persistent `clue` for the
  suite (rerun-idempotent since commit `71840fe`; see
  `2026-07-21-db-test-rerun-idempotency.md`).
- The old `api` README's relative doc links resolve correctly again at the new depth (they had
  been one level off since R1 moved the tree under subsystems/).
