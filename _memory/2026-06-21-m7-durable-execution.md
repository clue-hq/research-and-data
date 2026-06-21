# 2026-06-21 — M7 Durable Execution (branch `m7/verification-layer`… renamed plan)

> Branch actually created: `m7/verification-layer` off `beat0/contract-freeze-v1`. (Name is a
> slight misnomer — M7 is *durable execution*, not verification. Left as-is unless user asks to
> rename; do not rename without instruction.)

## Goal
Implement M7 (durable execution substrate) issue-by-issue, pausing after each for user review.
Linear issues (project Research Subsystem, milestone "M7 — Durable Execution"):
- ENG-131 M7.1 per-account orchestrator-worker graph (LangGraph + AsyncPostgresSaver)
- ENG-135 M7.2 bounded recursion knob (SpawnGuard + RecursionPolicy)
- ENG-141 M7.3 campaign-run state machine
- ENG-147 M7.4 idempotency ledger + idempotent() ctx manager
- ENG-153 M7.5 budget caps & cost-governance engine
Build order = numeric (matches spec + Linear). Each issue: implement → self-review → fix → PAUSE.

## Frozen surface (DO NOT TOUCH without user re-freeze discussion)
core/*, obs/spans.py, the `[tool.importlinter]` contracts in pyproject.toml. M7 implements the
core.execution / core.idempotency seams; impls live in `durable/`, wired at api root (integration-time).

## The one guarded-surface touch flagged to user: langgraph dep
M7.1 needs `langgraph` + `langgraph-checkpoint-postgres` in pyproject `[project.dependencies]`.
This is a *dependency addition* (additive, M7-only), NOT a contract re-freeze — matches the
"runtime stack lands per-milestone" precedent (M0.3 sqlalchemy, M0.4 openai, M2.4 redis, M4.3 pypdf).
Does not touch the importlinter contracts. Flagged to user at M7.1 pause.

## Verified codebase conventions (the map)
- **Migrations:** raw SQL via `op.execute()`; tables defined ONLY in migrations (no ORM,
  target_metadata=None). New = `uv run alembic revision -m "<slug>"` → hash id, down_revision chains
  off head. Current head = `eab62cbb1366`. Within M7 branch: chain linearly → single head (no merge).
  Enums = module tuples mirroring core.enums + `CREATE TYPE … AS ENUM(…)` + parity test. Named
  constraints/indexes/triggers. `timestamptz NOT NULL DEFAULT now()`. JSONB serialized via
  core.serialize_value_json. Append-only guarded by plpgsql BEFORE-UPDATE trigger.
- **Repos:** per-package data module (e.g. claimstore/claims.py, icp/spec.py) — `_SQL = text(...)`,
  `async def insert_*(conn, …)`, `_row_to_*`. Sessions via db.connection()/db.transaction() →
  AsyncConnection, raw `conn.execute(text(...), params)`.
- **Config (policy-as-data):** config/schema.py holds BudgetCaps (RESERVED for M7 — build on it),
  add RecursionPolicy here. Layered overlays defaults→client→ICP via config/loader.get_config;
  add policy → schema.py + ConfigOverlay + Config + loader._merge + __init__ exports.
- **Obs:** import traced_step, apply_attributes, phase_span, CAMPAIGN_PHASES, ATTR_CAMPAIGN_RUN_ID,
  ATTR_ENTITY_ID, ATTR_COST_CENTS, record_phase_progress from clue_research.obs. M7 owns its own span
  names in `durable/spans.py` (do NOT edit obs/spans.py). phase_span(phase) for campaign spans.
- **Locks (M2.4):** `from clue_research.locks import entity_lock, get_redis`. `async with
  entity_lock(redis, EntityType.ACCOUNT, entity_id, ttl_ms=…)` auto-renews (use ctx-mgr form,
  NOT manual acquire — multi_lock early-expiry caveat). Concurrency: asyncio.Semaphore + entity_lock.
- **Claimstore:** WRITE insert_claim(conn, claim)->ClaimId, supersede_claim. Build via
  core.factories.account_claim/contact_claim/discovery_claim (run_id, research_mode). Stamp reuse via
  identity.reuse.stamp_reuse(claim, tenant_id=…) BEFORE insert (M2.5). READ current_value(conn,
  entity_id, field_key, *, scope: TenantScope) [scope REQUIRED], current_values batch, claims_for.
  Field registry: get_field(conn, key)->FieldDef (tier_plan, freshness_ttl, pass_kind, gate),
  list_fields(conn, pass_kind=PassKind.DEEP). run_id (=account_run.id) minted via new_run_id().
- **Tests:** NO pytest-asyncio. `run_async(coro)`=asyncio.run. `rollback_conn()` ctx-mgr yields
  AsyncConnection in a rolled-back txn (seeds core pack). require_db/require_claimstore_db/migrated_db
  fixtures; skip-if-no-DB. Pure-logic tests = factories + parametrize, no DB. tests/durable/ + conftest.
- **API:** wiring is integration-time. M7 ships register_phase_handler registry in durable/ (mirrors
  sources.registry.bind_resolver); api wiring deferred.

## Holistic table/migration plan (4 migrations, chained)
- M7.1: `account_run` (+ account_run_status enum). LangGraph checkpoint tables via saver.setup()
  (langgraph-managed, NOT Alembic — documented). AccountResearchGraph takes a checkpointer so tests
  use InMemorySaver (no DB); DB resume test uses AsyncPostgresSaver, skips w/o DB.
- M7.3: `campaign_run` (+ campaign_run_status + campaign_phase enums mirroring core.CampaignPhase) +
  `campaign_phase_checkpoint` + `adjustment_journal`.
- M7.4: `idempotency_ledger`.
- M7.5: `budget_event` + ALTER account_run ADD budget_cap_cents (campaign_run already has caps).
- M7.2: no tables (RecursionPolicy = config).

## Durable-internal types (NOT in core; live in durable/)
AccountResearchGraph, AccountRunResult, RecursionPolicy(config), SpawnGuard, CampaignRun,
phase-handler registry, checkpoint store, idempotent() + ledger repo, BudgetEngine impl.

## Isolated DB for this branch (IMPORTANT — avoid trampling shared localhost:5432)
Created database **`clue_m7`** on localhost:5432 (CREATE DATABASE clue_m7 via asyncpg as clue).
Run ALL DB-touching commands with `CLUE_DATABASE_URL=postgresql+asyncpg://clue:clue@localhost:5432/clue_m7`.
NOTE: `_db_available()` returns False when CLUE_DATABASE_URL is UNSET (so `make check`/CI skip DB
tests and never touch the shared `clue` DB). Only set the env to clue_m7, NEVER to `clue`.

## M7.1 (ENG-131) — DONE (committed; Linear → In Review)
LangGraph + AsyncPostgresSaver per-account orchestrator-worker graph. Files:
- migration `79d56a0f4425_account_run_table` (account_run + account_run_status enum, off head eab62cbb1366).
- durable/enums.py (AccountRunStatus), durable/spans.py (M7 span names — NOT in obs), durable/
  account_run.py (repo: insert/ensure/get/save_plan/save_references/set_status), durable/planning.py
  (compute_gap_fields + build_plan clustering by field-class), durable/workers.py (WorkerRegistry),
  durable/graph.py (AccountResearchGraph: plan→fan_out(Send)→collect→handoff; AccountRunStore seam +
  DbAccountRunStore; AccountRunResult references-only; resume-correct run() via aget_state; reducer
  `_accumulate` on aspect_results; postgres_checkpointer() ctx-mgr), durable/__init__.py exports.
- pyproject.toml: added langgraph>=0.2 + langgraph-checkpoint-postgres>=2 (the one guarded-surface
  touch — a dep add, not a contract change; flagged to user).
- tests/durable/: conftest (FakeAccountRunStore + StubAspectWorker + rollback_conn/migrated_db),
  test_planning (4 pure), test_account_graph (10 pure, InMemorySaver), test_account_run_db (5 DB-gated).
Key decisions: LangGraph checkpoint tables are framework-managed via saver.setup() (NOT Alembic);
graph takes a checkpointer so tests use InMemorySaver (no DB). Worker bodies are M8's; M7.1 ships the
skeleton + worker→store→reference contract. Per-step idempotency dedup deferred to M7.4 (run()'s
resume gives super-step-level no-re-spawn via LangGraph checkpoint).
Verification: make check green (395 passed/298 skipped/0 fail; lint, mypy 114, contracts 10/0).
db-smoke reversible (single head 79d56a0f4425) on clue_m7. 19 durable tests pass with DB on.
Adversarial review (3 lenses + verify): 2 findings, both DOC-only (no behavioral bugs) — fixed:
(1) AccountRunStatus/account_run docstrings claimed PENDING→PLANNING→RUNNING but begin() is atomic
PENDING/created→RUNNING; aligned docs, kept all 7 enum values (spec+DB parity, staged-lifecycle use).
(2) AccountRunStore.fail() is forward-designed for M7.3 (a crash is resumable not terminal); clarified docstring.

## Rebase reconciliation (commit 0a828db) — DONE
User rebased m7 onto updated beat0 (now includes M6 PR#9, M9 contract-delta PR#10, ENG-165 reuse_scope).
- Two alembic heads (my 79d56a0f4425 + ENG-165's 82831d3fa4c5, both off eab62cbb1366). Re-pointed my
  account_run migration down_revision → 82831d3fa4c5 (linear chain, matches rebase; NOT alembic merge).
- FreshnessState now has EXPIRED (M9). Hardened gap-detection: any non-FRESH winner is a gap (was STALE-only).
- Recreated clue_m7 FRESH (drop+create) — old one had pre-rebase schema. db-smoke reversible on linear chain.

## M7.2 (ENG-135) — bounded recursion knob. IMPLEMENTED, gate-green, under review.
- config/schema.py: TierRecursionCaps{max_depth 0..2, max_aspect_workers, max_facet_workers_per_aspect}
  + RecursionPolicy{by_tier, default_caps(depth0), eligible_classes=(account.resonance, contact.facet)};
  caps_for(tier)/is_eligible(aspect). Defaults: top depth2, high depth1, unlisted depth0. Wired into
  ConfigOverlay/Config/loader._merge/__init__ like BudgetCaps (policy-as-data, per-ICP overridable).
- durable/recursion.py: SpawnGuard (single hard chokepoint) + SpawnDecision + SpawnDenyReason
  (not_eligible/depth_exceeded/count_exceeded/budget). may_spawn order: eligibility→depth→count→budget.
- durable/graph.py: recursion CONTAINED INSIDE aspect_worker node via internal asyncio (NOT LangGraph
  Send recursion) — keeps M7.1 topology/tests/resume intact. _run_worker_subtree (recursive, gathers
  granted facets concurrently, returns (results, depth_reached)); _grant_facets (SpawnGuard chokepoint
  + cap_hit per denial); _run_one_worker (shared aspect/facet isolation); _dispatch caps level-1 at
  max_aspect_workers; soft cap injected via AspectContext.params["recursion"]; facet requests ride
  WorkerResult.detail["facet_requests"]. DbAccountRunStore(recursion_policy), AccountResearchGraph(recursion_policy).
- durable/spans.py: SPAN_CAP_HIT + ATTR_FACET_COUNT/DEPTH_REACHED/CAP_HIT_REASON.
- build_plan(recursion_policy=) records per-tier depth allowance in plan_json.
- Tests: test_recursion_policy (5), test_spawn_guard (7), test_account_recursion (8 graph-level).
Verification: make check 416 passed/308 skipped/0 fail; 39 durable tests pass w/ DB on clue_m7.
Adversarial review (3 lenses + verify): 4 findings, all fixed:
(1) HIGH — budget not decremented across sibling facet grants in _grant_facets (two 60c facets both
    passed a 100c envelope). Fixed: decrement `remaining` per grant; added test_budget_envelope_is_shared.
(2) MEDIUM — _emit_fanout_summary used graph_node_span("recursion") violating that helper's
    plan|fan_out|collect|handoff contract. Fixed: added SPAN_FANOUT_SUMMARY constant.
(3) LOW — no test for max_aspect_workers level-1 cap. Fixed: added test_max_aspect_workers_caps.
(4) NIT — eligible_classes prefix-matching unclear. Fixed: clarified field doc (kept the name).
NOTE: custom span attrs are stringified by obs redaction (depth reads back as "0", not int 0) —
tests coerce with int().
M7.2 DONE: committed; Linear ENG-135 → In Review; PAUSED for user review.

## M7.3 (ENG-141) — campaign-run state machine. DONE (committed; Linear → In Review; PAUSED).
The outer durable state machine over the 8-phase sequence (reverse_profiling → … → handoff), the
scheduler under the per-account graphs (M7.1). Honors the M6↔M7 agreement exactly: NO separate tier
table; campaign_phase_checkpoint carries payload_json + a read-back API (CampaignRun.await_checkpoint)
that M6.4's tier-checkpoint handler writes its review payload into.

Files:
- migration `ce08f0be1c20_campaign_run_state_machine_m7_3_eng_141` (off head 79d56a0f4425):
  3 enums — `campaign_phase` (mirrors CORE core.CampaignPhase, parity-tested), `campaign_run_status`
  (active|paused|completed|failed) + `phase_checkpoint_status` (in_progress|awaiting_input|committed|
  failed) (durable-internal). Tables: `campaign_run`; `campaign_phase_checkpoint` (UNIQUE(campaign_run_id,
  phase) = the (campaign_run,phase) idempotency shape; committed_at "iff committed" CHECK computed in SQL
  via CASE so the upsert can't violate it); `adjustment_journal` (append-only via reject trigger +
  **monotonic `seq` GENERATED ALWAYS AS IDENTITY** — ordered by seq, NOT created_at). NB: chose a journal
  TABLE over the spec's illustrative `adjustments_json[]` column (one source of truth, immutable audit).
- durable/enums.py: +CampaignRunStatus, +PhaseCheckpointStatus.
- durable/campaign_run.py: repos + row models (campaign_run / checkpoint upsert+read-back / journal
  append+list). upsert_checkpoint computes committed_at in SQL (no Python clock).
- durable/phases.py: PhaseHandlerRegistry (mirrors WorkerRegistry; api-root binding; durable imports
  no phase package).
- durable/campaign.py: PHASE_SEQUENCE=tuple(CampaignPhase) + next_phase; CampaignRunStore protocol +
  DbCampaignRunStore (in-memory-testable seam, like AccountRunStore); CampaignRun
  (start/advance/run_to_completion/pause/resume/adjust/await_checkpoint/submit_checkpoint/status/
  pre_run_estimate). Crash-resume = two durable steps per phase (COMMITTED checkpoint, then transition);
  a COMMITTED-checkpoint re-entry short-circuits (handler NOT re-run). PAUSED→AWAITING_INPUT = durable
  human/budget gate. pre_run_estimate delegates to an injected BudgetEngine (M7.5 owns math; raises
  BudgetEngineNotConfigured if none).
- durable/scheduler.py: AccountScheduler — Semaphore(max_parallel) + per-entity single-flight via an
  injectable lock_factory (default = entity_lock M2.4). Wraps AccountResearchGraph.run for the deep phase.
- durable/spans.py: +ATTR_PHASE, +ATTR_PHASE_STATUS (phase span name from frozen obs.phase_span).
- durable/__init__.py: exports all M7.3 symbols.
- tests/durable/: test_campaign_phase_sequence (pure), test_campaign_state_machine (in-memory; 27 incl.
  review regressions), test_account_scheduler (concurrency cap + single-flight via _TrackingGraph),
  test_campaign_run_db (DB-gated: 3 enum parities, repo round-trips, checkpoint read-back+committed_at
  invariant, journal append+immutability). conftest: +FakeCampaignRunStore, +RecordingPhaseHandler,
  +FakeBudgetEngine.

Verification: make check green (452 passed / 319 skipped after fixes; lint+format, mypy 119, contracts
10/0). 86 durable tests pass on clue_m7. db-smoke reversible, single head ce08f0be1c20.

Adversarial review (Workflow, 4 lenses + per-finding verify): 9 confirmed of 23 raw; all addressed:
- HIGH (×2 lenses) — `_to_cost` crashed on NaN ("Decimal('NaN') >= 0" raises InvalidOperation OUTSIDE
  the try) and accepted "Infinity" as a cap → fixed with `is_finite()` guard (one check closes both);
  same guard added to `_to_float_cutoffs`. Regression test over {NaN,nan,Infinity,inf,-5,notanumber}.
- MED — submit_checkpoint partial-crash (commit + resume are separate txns) left run PAUSED+COMMITTED,
  recoverable only via resume() → submit_checkpoint now self-heals (COMMITTED & PAUSED at current phase
  → flip ACTIVE + replay _transition_after). Test added.
- MED — re-submitting the same embedded adjustment duplicated the audit journal → diff-guard: apply an
  embedded cutoff/cap edit only when it actually changes the run (no-op resubmit = no journal row).
  Docstring softened (advance is idempotent; exactly-once bracketing of ALL effects across a crash is
  M7.4's idempotency-ledger job). Test added.
- LOW — added tests: unknown/garbage action fails safe (stays suspended, edits still apply),
  run_to_completion(max_steps) + no-progress guard, fakes isinstance-conform to their runtime_checkable
  protocols (CampaignRunStore/BudgetEngine/PhaseHandler).
- ALSO found+fixed BEFORE the review (a flaky DB test): adjustment_journal order was nondeterministic —
  rows in one txn share now() (transaction timestamp), so the created_at,id tiebreak was the random
  uuid → added the monotonic seq column.

## M7.3 → M7.4 follow-ups (bound to the next issue)
- submit_checkpoint's embedded adjustments are made idempotent by a *diff guard*, which is sufficient for
  UI-retry / no-op resubmit but does NOT bracket the crash-window between the adjust txn and the commit
  txn perfectly. The architecture's answer is M7.4: wrap submit_checkpoint's effectful section (and
  advance()'s phase body) in `with idempotent(phase_key(campaign_run, phase)): …` once the
  idempotency_ledger lands. phase_key already exists (core.idempotency); campaign_phase_checkpoint is the
  per-phase durable record M7.4 keys on (idempotency_key column already populated).
- (refuted-but-noted) FAILED-checkpoint disposition isn't durable from its checkpoint alone (re-runs the
  not-yet-committed phase on re-entry) and there's no same-campaign-run driver lock; both are benign /
  M7.4-ledger + single-driver-per-run invariants, not M7.3 defects.

## Next: M7.4 (ENG-147) idempotency ledger + idempotent() ctx manager. NOT started.
