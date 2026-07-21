# 2026-07-21 — DB-gated test suite made rerun-idempotent on a persistent schema

## Problem
`CLUE_DATABASE_URL=... uv run pytest -q` passed on a fresh schema but a SECOND consecutive run
failed 6 tests (plus one stats-dependent flake). Two pollution species:

1. **LangGraph checkpointer tables** (`checkpoints`, `checkpoint_blobs`, `checkpoint_writes`,
   `checkpoint_migrations`) created at runtime by `AsyncPostgresSaver.setup()` (via
   `durable.graph.postgres_checkpointer`) in
   `tests/durable/test_account_run_db.py::test_graph_end_to_end_on_db_store_and_postgres_checkpointer`
   — the only test using the real saver. It deleted its *rows* but left the *tables*, breaking
   `tests/db/test_db_migrations.py::test_no_domain_tables_at_m0_head` on rerun (tables are outside
   alembic, so `downgrade 0001` leaves them standing).
2. **Committed production seeds.** `tests/stage0/test_handler.py`, `tests/stage0/conftest.py`, and
   `tests/stage0/test_icp_handler.py` COMMIT (via `db.transaction()`) `load_core_pack`,
   `seed_source_manifests`, `load_starter_packs`, `load_client_knowledge_pack`,
   `load_icp_feedback_pack`. These loads are idempotent against *themselves*, but on run 2 the
   earlier-alphabetical suites (adapters/api/claimstore) now see committed rows their
   rollback-transaction tests re-register with *different* definitions:
   - `firecrawl_site` v1 seed (provider="firecrawl") vs the adapters pipeline test's variant →
     `SourceManifestRedefinitionError`.
   - `exa_deep` v1 seed (BOTH scope, cost 10) vs the AC-6 gate test's tier-4/cost-0 variant → same.
   - `healthcare.npi` (icp starter pack, full def) vs the field-registry tests' minimal def →
     `FieldRedefinitionError`.
   - `account.resonance.research_prestige` (frontier_ai starter pack) broke the exact-set
     assertion in `test_governed_field_classes_are_deep`.
   - `test_live_claims_partial_index_is_used`: with committed claim rows, the planner picks the
     non-partial `claim_field_key` index even with `enable_seqscan=off` (verified by hand on the
     dirty schema) — stats-dependent flake.

## Fixes (all test-side; no production code touched; no skips needed)
- `tests/durable/test_account_run_db.py` — the mess-owner cleans up: the finally block now
  `DROP TABLE IF EXISTS ... CASCADE`s all four checkpointer tables (setup() recreates them).
- `tests/db/test_db_migrations.py` — belt-and-suspenders: `test_no_domain_tables_at_m0_head`
  drops exactly those four runtime tables (documented `_RUNTIME_CHECKPOINTER_TABLES`) before
  asserting; any OTHER stray table still fails. Covers interrupted/partial runs.
- `tests/adapters/test_pipeline.py` — `_register` grew a `version` param; the firecrawl test
  registers its variant at `version=2` (a versioned update inside the rolled-back txn — legal per
  the registry's own rules), so it never collides with the committed v1 seed.
- `tests/api/deep/test_gate_routing_ac6.py` — same `version=2` approach for `exa_deep`.
- `tests/claimstore/test_field_registry.py` —
  - pack tests use a test-only namespace (`maritime.imo_number`) instead of `healthcare.npi`;
  - `test_governed_field_classes_are_deep` asserts seed membership + the deep/field-class
    invariant over EVERY returned governed row (state-tolerant, arguably stronger).
- `tests/claimstore/test_claim_table.py::test_live_claims_partial_index_is_used` — inside the
  rolled-back txn, `DROP INDEX claim_field_key` (DDL is transactional) before the EXPLAIN, so the
  planner can only pick an index whose partial predicate it PROVES matches — deterministic,
  keeps the exact original guarantee.
- `Makefile` — new `db-fresh` target: drop+recreate the `public` schema via a `uv run python -c`
  snippet over `clue_db` (`define DB_FRESH_PY ... endef`, `python -c "$$DB_FRESH_PY"`), no psql
  dependency, honours `CLUE_DATABASE_URL`. `db-smoke` untouched.

## Verification (closing entry — all gates green)
- `uv run ruff check --fix . && uv run ruff format .` — "All checks passed! / 569 files left
  unchanged".
- `make check` (no DB env) — exit 0, `1151 passed, 791 skipped`.
- `make db-fresh` (one fresh reset) then three consecutive full
  `CLUE_DATABASE_URL=... uv run pytest -q` runs on the SAME persistent schema —
  RUN1 exit=0, RUN2 exit=0, RUN3 exit=0. (Note: repo addopts already include `-q`, so a CLI `-q`
  makes it `-q -q` and suppresses the pass-count summary line; exit codes are the gate.)
- `make db-fresh && make db-smoke` — exit 0 (up → base → up, single head).
- Also verified directly: after `tests/durable/test_account_run_db.py` runs, zero `checkpoint%`
  tables remain; and the six previously-failing tests pass when run against a deliberately dirty
  (post-second-run) schema.
- NOT committed (per task instruction); working tree carries the 7 modified files + this note.

## Notes / follow-ups
- The committed-seed pollution is inherent (stage0 handler tests exercise real committed writes);
  the ruling here is: victim tests must be state-tolerant, seeds stay committed.
- If a future test registers another *seed* source key with a divergent definition inside a
  rollback txn, use the same `version=2` pattern.
