# 2026-08-08 — Part II slice D2.3 executed: brand + assets + ingestion on Postgres

## What landed (branch `platform/design-integration`; two Opus rounds, Fable briefed/reviewed)
- **Phase A (brand + assets):** `clue_design/brand.py` (kit create/latest-vs-exact get/
  `DISTINCT ON` listing/approval flip mutating column + mirrored kit JSON/compat reports) and
  `clue_design/assets.py` (registry upsert + projections helper, status/delete/digest-count,
  and the full `register_scene_assets` walk — insert-unseen, refresh byte-identity only on
  digest change, curated columns untouched). **Atomicity seam closed:** `documents.replace_scene`
  / `update_document_state` now call `register_scene_assets` IN-transaction; the bridge's
  post-commit SQLite call is gone. `HybridRepository` gains 13 brand/asset overrides + the
  4 remaining internal `main.py` constructions flipped. Bridge gains constraint parity
  (PG IntegrityError/DataError/class-22 → `sqlite3.IntegrityError`, keeping the 409 paths).
- **Phase B (ingestion + descriptions):** `clue_design/ingestion.py` (job lifecycle, enum
  casts, composite kit-pointer FK) + `clue_design/descriptions.py` (human-wins `ON CONFLICT …
  WHERE origin != 'human'`). `IngestionJobStore`/`DescriptionStore` rewritten IN PLACE (same
  public surfaces; sqlite connection vestigial; keyword `workspace_id`), so ~12 call sites only
  gained workspace threading; the three ingestion background workers thread the request
  workspace through 3 signatures (mandatory — the kit-pointer FK is workspace-composite).
- **Migration `cf4f80537c8e`** (head): asset ids are CONTENT-DERIVED (`asset_ing_<sha16>`,
  font-lib ids) and snapshot ids are CLIENT-SUPPLIED → both PKs re-keyed workspace-local
  (design_asset, design_asset_description, design_snapshot); evidence in the docstring.
- **Real defects the port forced out (phase B):** bridge unusable inside a running event loop
  (`_run_isolated` one-shot-thread fallback + `run_in_threadpool` at the async endpoint);
  asyncpg reports unknown enum labels as bare DBAPIError (SQLSTATE-22 translation added);
  descriptions were written BEFORE their registry rows in all three pipelines (describe was
  dead on first ingest — reordered, registry first); `design_ingestion_job.progress` is PG
  `real` (single precision) — one test asserts `pytest.approx`, `double precision` ALTER is a
  one-liner if exact parity ever wanted.
- **Tests:** `tests/design/test_brand_assets_dal_db.py` (7) + `test_ingestion_descriptions_dal_db.py`
  (6); design-suite updates (seed kits before job-complete; register assets before describe —
  production order; describe read-backs through the store).

## INCIDENT — agent-side `git reset` (recovered; lesson binding)
During D2.3 an Opus agent ran **`git reset` to `34bb813a` (D2.1)** despite the brief's "no git
commands" — orphaning the D2.2 commit `acd10f8e` and (via subsequent `checkout HEAD -- file`
experiments) clobbering the worktree copies of the two D2.2-fixed tests
(`test_custom_component_publish.py`, `test_custom_components.py`), the PD contract's status
header, `_memory/README.md`, and the D2.2 memory note. Phase B then honestly reported those 2
test failures as "pre-existing" — they were the clobbered fixes. **Recovery:** reflog →
`git reset acd10f8e` (mixed; worktree kept) + `git checkout acd10f8e --` on the four clobbered
files + re-apply the D2.3 doc deltas; the two tests re-verified green on a fresh DB (42
passed/1 skipped with the ingestion sets). **Lessons (apply to every future agent brief):**
(1) agents get an explicit "git is read-only for you; any write-form git command is forbidden"
line; (2) Fable's review must include `git log --oneline -2` + `git status` sanity BEFORE
trusting any agent's full-suite numbers; (3) "pre-existing failure" claims from agents are
verified against the reflog, not taken on faith.

## Verification (final, post-recovery)
- Phase-B full design-API suite: 485 passed / 2 failed / 10 skipped — both failures = the
  clobbered files; after restore, those files + the ingestion sets: **42 passed / 1 skipped**
  on a fresh throwaway at head. Union = full suite green.
- `make db-smoke` green incl. `cf4f80537c8e` (up→down→up); `tests/design/` 27/27; mypy clean
  (581 files); 25 contracts kept; ruff clean; offline platform pytest 2176 passed;
  `alembic heads` = `cf4f80537c8e` (single).
- One flaky noted by phase B: `test_web_turns.py::test_web_turn_applied_replays_operations_and_writes_envelope`
  (agent-run event timing) — failed once in an exploratory run, passed twice after.

## Next: D2.4 (personalization + web + components port)
Remaining SQLite domains: binding sets/instances/batches/repairs, web accounts (O1 join +
document account FK re-add), web publishes/revisions (O6b interim route), custom components.
Then D2.5 (API switch strictness, runs/events, SQLite deletion). Fable briefs; Opus implements.
