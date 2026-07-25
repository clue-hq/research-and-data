# 2026-07-24 — Phase C5.2 immutable recipes and compatibility

## Scope and branch

- Implemented on `platform/c5-recipe-execution` after C5.1 commit `a9278a4`.
- Binding authority:
  `docs/specs/PC-C5-run-graph-recipes-executor.md` and
  `docs/superpowers/plans/2026-07-24-phase-c5-run-graph-recipes-executor.md` §4.
- No Alembic revision and no executor/fleet behavior were added. C5.2 uses the dormant recipe
  tables created by C5.1.

## Implemented

- `clue_execution.recipes` now owns idempotent proposal, promotion, retirement, and supersession
  over append-only revision events. Same-version/same-digest proposal replays; same-version changed
  content raises `RecipeVersionConflict` and requires a version bump. Promotion recomputes the
  stored definition digest, validates the whole graph, resolves all pins, and appends `promoted`
  only when both reports are clean.
- `clue_execution.graph` is a closed Pydantic AST:
  `literal` (short scalar only), `parameter`, and `node_reference` with identifier-only path
  segments. It supports tool/gate/barrier/activity nodes and one bounded map-template level; no
  Jinja, eval, callable path, arbitrary JSONPath, nested unbounded maps, or raw body literals.
- Graph promotion validation returns every issue together: duplicate/missing/cyclic nodes,
  envelope violations, closed gate authorities/condition kinds, exact allowlists, exact tool and
  descriptor-required pins, input/output schema digest drift, required/unknown bindings, typed
  reference paths, conservative JSON-schema compatibility, and bounded expansion totals.
- `clue_execution.compatibility` provides an open `PinResolverRegistry`, exact loader, deterministic
  pin/report digests, all-error incompatibility reports, optional-resource pins, and
  `recheck_node()` for the retirement-between-load-and-dispatch window. It never selects a version
  lexically.
- `clue_api.recipe_wiring` registers production adapters for exact tools, field/source registries,
  ICP versions, per-slot source-profile snapshots, workspace readiness revisions, Stage-0 policy,
  skill metadata/body digest, prompt/model catalogs, product-context manifests, artifact inputs,
  the live memory switch, and memory-bundle journals. Field/source retirement and artifact/memory
  safety states fail closed. Archived/draft ICP lifecycle status is metadata, not erasure of an
  otherwise retained exact version.
- Checked-in JSON assets:
  `platform/execution/recipes/recipe0-stage0-v1.json` and
  `platform/execution/recipes/recipe1-classic-v1.json`. Hatch wheel packaging includes both.
  `seed_system_recipes()` is the idempotent API-root boot function and verifies that the persisted
  digest equals the checked-in definition.

## Standing-seed boundary

- The two C5.2 v1 assets are deliberately promoted `migration_state=placeholder` revisions limited
  to barrier nodes. This reconciles the C5.2 requirement for stable promoted system identities with
  the binding plan that C5.4 authors/migrates formal Recipe #0 and C5.6 authors/canaries Recipe #1.
- A placeholder is not an executable recipe and C5.2 creates no runnable task. C5.3 must preserve
  that rejection. C5.4/C5.6 append newer executable revisions; they must not rewrite v1.

## Verification

- C5.2 focused DB suite: `28 passed`.
- Full DB-backed repository suite:
  `2380 passed, 20 skipped`.
- Scoped tracked-root Ruff format/lint: green (`773 files`); mypy:
  `384 source files`, no issues; import-linter: `24 kept, 0 broken`.
- `alembic heads`: one head, `128c83d5e151`; `git diff --check`: green.
- Built the execution wheel and inspected it: both JSON assets are present under
  `clue_execution/recipes/`.
- Raw `make check` reaches Ruff and fails only on 16 pre-existing `T201` findings in the untracked,
  user-owned `.claude/` and `.codex/` helper copies. Those directories were not edited or staged.
  The equivalent tracked-root lint/type/contracts/test gates are green.

## C5.3 handoff

- Add no new recipe mutation semantics in C5.3; consume the frozen C5.2 contracts.
- The execution loader must refuse placeholder revisions, resolve all execution/node pins, persist
  the deterministic resolved-pin set, and create no runnable task on any incompatibility.
- Re-run `CompatibilityLoader.recheck_node()` immediately before dispatch.
- Generalize the fleet shell behind `WorkHandler`, then add the graph handler/cursor scheduling and
  stable operation-id crash recovery per the plan. Do not cut over Recipe #0/#1 yet.
