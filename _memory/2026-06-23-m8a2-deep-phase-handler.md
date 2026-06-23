# M8A.2 — `DeepPhaseHandler` (the `CampaignPhase.DEEP` handler) — implementation

**Date:** 2026-06-23 · **Branch:** `m8a/deep-handler` (off `m8a/orchestrator` = M8A.1) · **Spec:**
`docs/specs/M8A-campaign-run-deep-orchestration.md` §M8A.2 · **Plan:**
[[2026-06-23-m8a-implementation-plan]] · trunk note [[2026-06-23-m8a1-orchestrator-implementation]].

The `core.PhaseHandler` for `CampaignPhase.DEEP`. Resolves the human-approved high-tier accounts and
drives the M7 scheduler with the M8A.1 orchestrator bound as the per-account `run_one`, owning
per-account FAILED isolation + the budget-verdict → phase-status mapping. New file only — does **not**
edit `orchestrator.py` (the parallel-split rule: M8A.3/M8A.4 own that file).

## What shipped
- **`api/deep/handler.py`** — `DeepPhaseHandler` (`phase = CampaignPhase.DEEP`). Injected seams:
  - `high_tier_resolver: HighTierResolver = Callable[[PhaseContext], Awaitable[Sequence[AccountSpec]]]`
    — D-B lives in the concrete (claimstore `account.scoring.tier ≥ cutoff` keyed by committed
    `cutoff_version`); the handler imports no claim store, just calls the resolver. Wired at M8A.6.
  - `scheduler: DeepAccountScheduler` + `orchestrator: DeepAccountOrchestrator` — structural
    Protocols (conventions §2) so the handler is fake-testable without the heavy real graph; static
    conformance lines assert `durable.AccountScheduler` / `AccountDeepOrchestrator` satisfy them.
  - `checkpointer_factory: CheckpointerFactory` — yields the saver `run_accounts` requires (the
    `run_one` path bypasses the graph, so it is unused on this path, but the kwarg is required).
    Prod = `durable.postgres_checkpointer`; tests inject `InMemorySaver`.
  - `finalize_failed_account: FinalizeFailedAccount = Callable[[RunId], Awaitable[CostCents]]` — the
    isolation backstop. Prod binding `db_finalize_failed_account` reads `account_run.cost_cents`
    then `set_status(FAILED)` in one txn, returning the recovered cost. Default module binding
    `_DB_FINALIZE_FAILED_ACCOUNT` (lazy).
  - `run(ctx)`: resolve specs → (empty → COMPLETED no-op) → `_isolated` wrapper per account →
    `scheduler.run_accounts(..., run_one=_isolated)` inside the checkpointer cm → aggregate.
    `_isolated` catches a hard raise (recover cost via finalize) AND the not-found short-circuit
    (`result.sub_phase is None` → finalize, use `result.cost_cents`). PAUSED iff any account's
    `budget_stop is GRACEFUL_STOP`; else COMPLETED. Payload references-only:
    `{deep_count, accounts_failed, accounts:[{account_run_id, entity_id, tier, status,
    cost_cents(str), committee_member_ids, coverage, claim_ref_count}]}`.
- **`api/deep/__init__.py`** — exports the handler + seam types.
- **Tests** — `tests/api/deep/test_deep_phase_handler.py`, 10 fake-driven (no DB): registry dispatch
  + protocol conformance; resolve+process-all; hard-raise isolation (+ recovered partial cost);
  not-found soft-fail; GRACEFUL_STOP→PAUSED; DENY→partial COMPLETED; references-only payload (no
  `value_json` leak, JSON-serialisable); empty set no-op; checkpointer opened; resume path
  (committee=None → member ids from contacts, coverage None).

## Key design decisions (verified against the M8A.1 base)
- **Budget-stop seam is forward-compat via `getattr`.** M8A.3 (parallel branch) adds
  `AccountDeepResult.budget_stop: BudgetVerdict | None`; on this base the field does not exist, so
  `_budget_stop(result)` reads it with `getattr(..., None)` → always `None` here (no admission yet →
  never paused, correct), lights up automatically once M8A.3 merges. This is the agreed seam (see
  [[2026-06-23-m8a3-handoff]]): DENY→partial COMPLETED, GRACEFUL_STOP→PAUSED. Tests exercise it via
  a `_ResultWithStop(AccountDeepResult)` subclass (adds the field; parent's `extra="forbid"` only
  bans non-schema fields, a subclass field is in-schema).
- **No `orchestrator.py` edit** — keeps M8A.2 conflict-free with M8A.3/M8A.5. The handler self-builds
  the references-only manifest; M8A.5's `build_handoff_skeleton` folds the richer
  `(account,persona)`-keyed view + joined `profile_claims` in when it lands (fold-point commented in
  `_succeeded_outcome`).
- **`sub_phase is None` is the not-found signal** — the orchestrator's not-found short-circuit returns
  with the marker un-advanced; every other path (incl. resume) advances it ≥ ACCOUNT_PROFILED. So a
  resumed account is never mis-detected as failed.
- **Registration tested at the registry seam** (`PhaseHandlerRegistry().get(DEEP) is handler`), the
  exact lookup the state machine's `advance()` does; the full `advance()` path is M8A.6 integration.

## Adversarial review (workflow `wf_2aa8ec90-2aa`, 21 agents — 16 findings, 3 confirmed, all fixed)
1. **(critical) Hard-exception cost under-count** → FIXED. The `except` path previously returned
   `cost_cents=Decimal(0)`, discarding cost the orchestrator committed stage-by-stage before a crash
   (honest burn-down matters even pre-M8A.4). Changed the isolation seam from `mark_account_failed
   (-> None)` to `finalize_failed_account (-> CostCents)` (read persisted cost + set FAILED in one
   txn); the except path now reports the recovered cost. Test asserts 4 + 2(recovered) = 6.
2. **(major) Inline manifest vs M8A.5 `build_handoff_skeleton`** → DOCUMENTED (not a bug — M8A.5 is a
   parallel unmerged branch; the function doesn't exist). Added an explicit fold-point comment in
   `_succeeded_outcome` so M8A.5/M8A.6 wires it without rework.
3. **(minor) Untested resume path** (committee=None, contacts non-empty) → FIXED. Added
   `test_resumed_account_without_committee_lists_members_from_contacts`.

## Verification (all green)
- ruff (format+check), mypy (199 src files), import-linter **11/0** (`api/deep` composes
  `durable`+`profiling`+`config`+`db`; nothing but `api` imports it).
- `tests/api/deep/` = **19 passed** (9 M8A.1 + 10 M8A.2), all pure fakes, no DB.
- Full-suite note: the 6 full-suite failures observed were **environmental** — leftover LangGraph
  `checkpoint*` tables (from M7 `AsyncPostgresSaver.setup()` tests sharing the local `clue` DB, not
  Alembic-managed) tripping `test_no_domain_tables_at_m0_head` + DB-ordering flake on 5 others. None
  touch `api.deep`; 5/6 pass in isolation; dropping the checkpoint tables makes all 6 green. This is
  the documented M8A.0 shared-DB gotcha. **Run M7 checkpointer tests last / on a throwaway DB, or
  `DROP TABLE checkpoint_blobs, checkpoint_writes, checkpoints, checkpoint_migrations` before the
  M0-head test.**

## Follow-ups (downstream M8A issues)
- **M8A.3** adds `AccountDeepResult.budget_stop`; the handler's `getattr` mapping then activates with
  zero handler edit. Verify after merge that DENY→partial / GRACEFUL_STOP→PAUSED flows end-to-end.
- **M8A.5** `build_handoff_skeleton(result)` replaces/augments the inline manifest at the documented
  fold-point in `_succeeded_outcome` (still ids-only).
- **M8A.6** injects the concrete `high_tier_resolver` (claimstore D-B query — confirm the
  `tier_checkpoint` COMPLETED payload keys `cutoff_version`/`tier_distribution` against
  `discovery_scoring/phases.py`; the per-account list comes from `account.scoring.tier` claims, not
  the payload), the real `AccountScheduler` (M8A.0 callback bound to `orchestrator.run_one`),
  `postgres_checkpointer`, and registers the handler. The default `finalize_failed_account` already
  works against the DB; M8A.6 may keep or override it.
- **DRY note:** `db_finalize_failed_account` reads the row then sets status in one txn — when M8A.4
  reworks the spend transaction, reconcile whether finalize should also reconcile cost against the
  ledger (M8A.4 owns the authoritative `spent_cents`/ledger; M8A.2 only fixes the *phase-result*
  reporting).
