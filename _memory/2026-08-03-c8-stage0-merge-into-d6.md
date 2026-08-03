# 2026-08-03 — Merge Stage 0 C8 corrections into D6 discovery branch

## Request and lineage

- User requested the latest Stage 0 corrections from `origin/platform/c8-context-card` be pulled
  into `platform/c8-exa-sumble-discovery` after D6 closure.
- Fetched remote tip: `b2c15ff` (`fix(stage0): close dynamic client kb governance gaps`).
- Incoming commits: `d847aef`, `3df62cf`, and `b2c15ff`.
- Existing D6 commits retained: `bddca66` implementation and `591b2a1` acceptance record.

## Merge resolution

- One content conflict occurred in `platform/api/clue_api/toolbelt_wiring.py` at imports only.
- Resolution preserved both `DbSealedDiscoveryAccountManifestReader` from the D5 scoring guard and
  `DynamicClientKbMaterializer` from the Stage 0 correction branch. No behavioral block from either
  side was discarded.
- The two branches carried independent Alembic heads: D5 `3f41f54d6238` and Stage 0
  `b0fa1743c982`. Added merge revision `44ca5271670f`; current graph has exactly one head.
- Pre-existing modified/untracked workspace files were not staged or changed by the merge.

## Verification

- Fresh dedicated DB: `clue_c8_d6_merge_20260803`.
- `make db-smoke` completed head -> base -> head across both migration branches and the join.
- Combined Stage 0 dynamic-field, verdict-attribution, DSAR, shared toolbelt/recipe, D5 barrier,
  scoring-bypass, and D6 acquisition suites: 144 passed.
- Ruff format/check passed on all 56 integrated Python files.
- mypy passed 477 source files.
- import-linter kept all 24 contracts.
- No provider or model calls were made and no spend occurred.
