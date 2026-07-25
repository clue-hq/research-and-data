# M8A.0 — durable seams (scheduler `run_one` callback + `account_run.sub_phase`) — implementation

**Date:** 2026-06-23 · **Branch:** `m8a/durable-seams` (off `origin/main` @ 54b8c50) · **Spec:**
`docs/specs/M8A-project-run-deep-orchestration.md` §M8A.0 · **Plan:**
[[2026-06-23-m8a-implementation-plan]] · **Design:** [[2026-06-22-m8a-orchestration-design]].

First M8A issue: the additive, **`durable`-owned** substrate the deep-orchestration (M8A.1+) depends
on. Lands solo, first. No behavior change to the existing account axis.

## What shipped
- **`durable/enums.py`** — `AccountRunSubPhase(StrEnum){account_profiled, committee_discovered,
  contacts_complete}`. Durable-internal (NOT in `core.enums`), mirroring `AccountRunStatus`. Decision:
  kept it durable-internal rather than promoting to `core` — M8A.1's orchestrator lives in `api/deep`
  (import-exempt) so it can import `durable.enums` directly; no `core` contract-delta needed.
- **Migration `ee97c497d31f_account_run_sub_phase_m8a_0.py`** — `down_revision = 089dc65b5814`
  (the origin/main head). Creates PG enum `account_run_sub_phase` + adds **additive nullable**
  `account_run.sub_phase` column (no DEFAULT; NULL = not started). `account_run.status` untouched.
  Reversible `downgrade()`. Hash id (adopted convention). **Parallel to `c74c23defd01`** (the in-flight
  #1 / M9.1 Option-C gate migration, also off `089dc65b5814`, NOT on origin/main) — when #1 and this
  both land, `alembic merge` joins the two heads (the adopted parallel-branch discipline).
- **`account_run.py`** — `sub_phase` on `AccountRunRow` (+ `_SELECT_COLUMNS`, `_row_to_account_run`);
  conn-taking `set_account_sub_phase(conn, id, sub_phase)` (mirrors `set_status`; stamps `updated_at`),
  so M8A.4 can advance the marker inside the spend transaction.
- **`graph.py`** — `set_account_sub_phase` + `get_account_sub_phase` on the `AccountRunStore` protocol
  + `DbAccountRunStore` (own-transaction convenience; `set_*` delegates to the module fn name-shadow
  style like `fail`→`set_status`; `get_*` delegates to `get_account_run(...).sub_phase`).
- **`scheduler.py`** — additive **generic** `run_one` callback on `run_accounts` (`@overload`: omitted
  → `list[AccountRunResult]` unchanged; supplied `RunOne[_RunResultT]` → `list[_RunResultT]`, so M8A.1's
  richer `AccountDeepResult` widens correctly). The callback runs inside the **existing** `Semaphore`
  + per-entity single-flight slot via a nested `_go()` closure; `_invoke` is byte-for-byte unchanged.
  `RunOne` alias defined AFTER `AccountSpec` (avoids a runtime forward-ref `NameError`).
- **`durable/__init__.py`** — exports `AccountRunSubPhase`, `set_account_sub_phase`, `RunOne`.
- **Tests** — `test_account_scheduler.py`: callback runs capped + in input order + bypasses the graph;
  single-flighted by the entity lock; returns a non-`AccountRunResult` (generic widening); default path
  unchanged. `test_account_run_db.py`: enum parity, repo round-trip (born-NULL → monotonic advance,
  status untouched), store-seam round-trip. `conftest.py`: `FakeAccountRunStore` grew the two methods +
  a static + runtime conformance guard (`_FAKE_ACCOUNT_RUN_STORE_IS_A_STORE`, mirroring the budget fake).

## Verification (all green)
- `ruff` (lint+format), `mypy` (195 src files), `import-linter` (11/0 — `durable` independence intact).
- **db-smoke** up→down(base)→up on a clean throwaway `clue_m8a_smoke`; `alembic heads` == 1
  (`ee97c497d31f`).
- `tests/durable/` = **179 passed** on a pristine DB; the M8A.0 tests = **18 passed** (no skips).

## Gotcha recorded (not a code defect)
Running `pytest tests/durable/` **before** the full suite against the *same* throwaway DB pollutes it:
the M7 `test_graph_end_to_end…postgres_checkpointer` test creates LangGraph `checkpoints*` tables via
`AsyncPostgresSaver.setup()` — these are **not** alembic-managed, so `tests/db/test_db_migrations.py::
test_no_domain_tables_at_m0_head` (downgrades to 0001, asserts `tables == ["alembic_version"]`) trips
over them, and a leftover committed `account.strategic_moves` `field_definition` row causes
`FieldRedefinitionError`. On a pristine DB `tests/db/` runs before `tests/durable/` (alphabetical), so
the invariant sees a clean schema. **Run the full suite on a fresh DB, or run `tests/durable/` last.**

## Adversarial review (4 confirmed findings, all addressed)
1. (major) migration was untracked → **`git add`ed in the commit** (it is the defining deliverable).
2. (minor) DB-gated AC tests skip without a DB → executed green against `clue_m8a_smoke`.
3. (minor) no conformance guard binding `FakeAccountRunStore` to the extended protocol → **added**
   (`_FAKE_ACCOUNT_RUN_STORE_IS_A_STORE` + a runtime `isinstance` assert in conftest).
4. (nit) generic-return test proves runtime, not static widening → left as-is (the `@overload` is
   mypy-verified on `src/`; tests are out of mypy scope so an `assert_type` there wouldn't be checked).

## Follow-ups (for M8A.1+)
- M8A.1 `AccountDeepOrchestrator` consumes: the scheduler `run_one` seam, `set_/get_account_sub_phase`,
  and `RunOne`. It injects `set_sub_phase`/`get_sub_phase` (bind `DbAccountRunStore`'s methods).
- M8A.4 (exactly-once) uses the **conn-taking** `account_run.set_account_sub_phase` to advance the
  marker inside the spend transaction (the store's own-transaction method is for the simple path).
- At integration, `alembic merge` `ee97c497d31f` + `c74c23defd01` back to one head.
