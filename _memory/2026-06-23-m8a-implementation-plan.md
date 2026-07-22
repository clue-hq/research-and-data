# M8A — Campaign-Run Deep Orchestration — implementation plan

**Date:** 2026-06-23 · **Spec:** `docs/specs/M8A-project-run-deep-orchestration.md` · **Design session:** [[2026-06-22-m8a-orchestration-design]] (verified facts) + workflow `wf_1288315a-c58` (design panel + judge scores + synthesis).
**Approach chosen:** C (hybrid) — a thin `DeepPhaseHandler` for `CampaignPhase.DEEP` delegating per-account to an `AccountDeepOrchestrator` that sequences `profile_account → discover_committee → bounded profile_contact fan-out` via **direct callables**, inside the existing `AccountScheduler` slot, all in a new **`api/deep/`** package. Rejected: B (parent LangGraph w/ 2nd Send super-step — unproven replay semantics in the most load-bearing durable file), A-as-written (false "reuse scheduler for free" — no callback seam; defers exactly-once).

This is the operational companion to the spec. The spec owns scope/AC/deps; this owns the code-level *how*, exact signatures, test plans, and merge order.

## Dependency DAG / parallelization
```
M8A.0 (durable: scheduler callback + sub_phase migration)   ← solo, separate worktree, lands first
   └─► M8A.1 (AccountDeepOrchestrator — trunk)
          ├─► M8A.2 (DeepPhaseHandler)         ┐
          ├─► M8A.3 (fan-out bounds + budget)  ├─ parallel (disjoint files)
          ├─► M8A.5 (handoff skeleton)         ┘
          └─► M8A.4 (exactly-once spend)  ← after M8A.3; co-touches durable/budget.py (coordinate w/ M8A.0 owner)
                 └─► M8A.6 (api composition root + AC-6/AC-4)  ← solo, LAST, only api-touching branch
```

## Shared conventions (every branch)
- `make check` + `make contracts` (import-linter 11/0) green before merge; DB-gated tests run with `CLUE_DATABASE_URL=postgresql+asyncpg://clue:clue@localhost:5432/clue` (rollback-isolated local `clue` DB).
- Feature branch off the integration tip; **never commit to `main`**; commit at green checkpoints; no AI attribution in messages.
- Workers/orchestrator return **references (claim ids), not blobs**; communicate only through the claim store.
- `orchestrator.py` / `handler.py` import **only `core` + the shared base + injected callables** — concretes are injected by `composition.py` (M8A.6). This keeps import-linter green and the units fake-testable.

## Verified anchors (don't re-derive)
- DEEP is a **stub**: `CampaignRun.advance()` raises `NoPhaseHandlerRegistered(DEEP)` (no handler registered). `CampaignPhase.DEEP` exists (`core/enums.py:210`); sequence `… tier_checkpoint → deep → verification → handoff`.
- `PhaseHandler` (frozen, `core/execution.py:82`): `phase: CampaignPhase; async run(ctx: PhaseContext) -> PhaseResult`. `PhaseContext{campaign_run_id, phase, client_id, icp_key, icp_version, budget_cap_cents, params}`. `PhaseResult{status∈COMPLETED/PAUSED/FAILED, accounts_processed, cost_cents, payload}`. Handlers register at api root via `durable.phases.register_phase_handler` (the registry never imports a handler).
- Exemplar handlers in milestone pkgs: `discovery_scoring/phases.py` (Discovery/Scoring/TierCheckpoint), `stage0/{reverse_profiling_handler,icp_handler}.py`.
- `AccountScheduler` (`durable/scheduler.py`): `run_accounts(specs, *, campaign_run_id, checkpointer) -> list[AccountRunResult]` (asyncio.gather, in-order; one raising propagates — caller owns isolation); `_run_one` wraps `_invoke` in `Semaphore(max_parallel)` + optional per-entity `lock_factory`; **`_invoke` hardcodes `self._graph.run(...)` — NO callback seam.** `AccountSpec{entity_id, tier, tenant_id, field_keys}`.
- `account_run` (`durable/account_run.py`): mutable, resume-safe (`ensure_account_run` no-ops on re-entry; id = LangGraph thread_id = `claim.run_id`); `save_references(... cost_cents, status)` **SETs** `cost_cents` (`:189`); `references_index` JSONB (aspect→claim ids). `AccountRunStatus` has no sub-granularity.
- Callables (all in `profiling/`, all already accept `pre_spend_gate`):
  - `profile_account(account_entity_id, icp_version, tier, run_id, *, pre_spend_gate=None, ...) -> AccountProfileResult` (`account.py:241`); account/resonance run as `AspectWorker`s through the M7 graph; uses fail-soft `RunContext.from_params`.
  - `discover_committee(conn, *, account_entity_id, run_id, tenant_id, sources, gateway, spec=None, role_model=None, relevant_personas=…, source_plan=None, budget_cap_cents=None, config=…, pre_spend_gate=None) -> CommitteeResult` (`committee/worker.py:194`). **Already gates** enumeration (`:259`) + role inference (`:311`). `CommitteeResult.members: tuple[CommitteeMemberRef{contact_entity_id, persona, role_on_committee, role_confidence, role_plausible, *_claim_id}]`; `.committee() -> tuple[core.handoff.CommitteeMember(profile_claims=())]`; `.coverage: CommitteeCoverage`.
  - `profile_contact(conn, *, contact_entity_id, account_entity_id, run_id, tenant_id, tier, spec=None, facet_subworker_budget=0, field_keys=None, binding_classifier=DEFAULT, use_class_tagger=DEFAULT, config=…, pre_spend_gate=None) -> ContactProfileResult` (`contact/worker.py:72`). Gate called in `fill_contact_field` (`contact/fill.py:155`). `binding_classifier` is the **M9.4 `classify_binding` injection point**.
- `core.handoff`: `ProfileClaimView` (:131 — `claim_id,value_json,evidence_span,source_tier,identity_binding,use_class`), `CommitteeMember` (:144), `AccountHandoff` (:185). `params_for_run(client_id,icp_key,icp_version,tenant_id) -> dict` + `RunContext` (`profiling/context.py`) — the #2 producer/consumer (already shipped).
- Budget: `core.BudgetEngine.check(scope∈ACCOUNT|PASS|RUN, projected_cents, campaign_run_id, entity_id, account_run_id) -> BudgetDecision{ALLOW|DENY|GRACEFUL_STOP}`; `record(...)` is **the single live increment** of `campaign_run.spent_cents` (+ `account_run.cost_cents` when `account_run_id` given) and its docstring (`budget.py::record`) **explicitly defers airtight exactly-once to "the M8 claim-write path"** = M8A.4.

---

## M8A.0 — durable seams (branch: `m8a/durable-seams`)
**Files:** `durable/scheduler.py`, `durable/account_run.py`, `durable/enums.py`, new migration `db/migrations/versions/<hash>_account_run_sub_phase.py`, `tests/durable/test_account_scheduler.py`, `tests/durable/test_account_run.py`.
**Steps:**
1. `durable/enums.py`: add `class AccountRunSubPhase(StrEnum){ACCOUNT_PROFILED, COMMITTEE_DISCOVERED, CONTACTS_COMPLETE}`. If cross-read by `core`, mirror in `core/enums.py` + enum-parity test.
2. Migration (hash id, chained off current head): `ALTER TABLE account_run ADD COLUMN sub_phase account_run_sub_phase NULL` (create the PG enum type first); reversible `downgrade()` drops column + type. Keep `account_run_status` untouched.
3. `account_run.py`: `async def set_account_sub_phase(conn, account_run_id, sub_phase: AccountRunSubPhase)`; add `sub_phase` to `AccountRunRow` + `_row_to_account_run` + `_SELECT_COLUMNS`. Add `set_account_sub_phase` to the `AccountRunStore` protocol + `DbAccountRunStore` (`durable/graph.py`).
4. `scheduler.py`: `run_accounts(self, specs, *, campaign_run_id, checkpointer, run_one: RunOne | None = None)` where `RunOne = Callable[[AccountSpec], Awaitable[AccountRunResult]]` (bind campaign_run_id/checkpointer at the call site via a closure, or pass them through). In `_run_one`, call `run_one(spec)` when provided else `self._invoke(...)`. Keep `_invoke` unchanged as the default.
**Tests:** callback path drives a fake callable under the semaphore+lock, results in input order; default path still calls `graph.run` (existing tests green); `sub_phase` round-trips + defaults NULL; `alembic upgrade→downgrade→upgrade` green; `alembic heads`==1; enum-parity + "no domain tables at M0 head" green.
**Gotcha:** the migration is the *only* migration in M8A — the M8 "no migrations" rule was for the parallel M8.1–M8.5 worktrees; M8A is the integration milestone where one additive, durable-owned migration is expected.

## M8A.1 — `AccountDeepOrchestrator` (branch: `m8a/orchestrator`, off M8A.0)
**Files:** `api/deep/__init__.py`, `api/deep/orchestrator.py`, `tests/api/deep/test_orchestrator.py`.
**Shape (import-light — core + injected callables only):**
```python
class AccountDeepResult(BaseModel):  # references-only
    account_run_id: RunId; entity_id: EntityId; tier: str
    account_refs: tuple[ClaimId, ...]; committee: CommitteeResult | None
    contact_results: tuple[ContactProfileResult, ...]; cost_cents: CostCents; sub_phase: AccountRunSubPhase

class AccountDeepOrchestrator:
    def __init__(self, *, profile_account, discover_committee, profile_contact,
                 set_sub_phase, get_sub_phase, config: DeepPhaseConfig,
                 sources, gateway, role_model, pre_spend_gate, binding_classifier, ...): ...
    async def run_one(self, spec: AccountSpec, *, campaign_run_id, checkpointer) -> AccountDeepResult: ...
```
**`run_one` body (resume-aware):**
1. read `sub_phase`; if `< account_profiled`: `await profile_account(spec.entity_id, icp_version, spec.tier, run_id=account_run_id, pre_spend_gate=…)` with account-axis params via `params_for_run(...)`; `set_sub_phase(account_profiled)`.
2. if `< committee_discovered`: `committee = await discover_committee(conn, account_entity_id=spec.entity_id, run_id=account_run_id, tenant_id, sources, gateway, role_model, spec, budget_cap_cents, pre_spend_gate)`; `set_sub_phase(committee_discovered)`.
3. if `< contacts_complete`: bounded fan-out (M8A.3 admission) over `committee.members[:committee_size_cap]`, intra-account `Semaphore(max_contacts_in_flight)`, `await profile_contact(conn, contact_entity_id=m.contact_entity_id, account_entity_id=spec.entity_id, run_id=account_run_id, tenant_id, tier, spec, facet_subworker_budget, binding_classifier, pre_spend_gate)`; `set_sub_phase(contacts_complete)`.
4. return references-only result.
**Tests (fakes):** M2→M3→M4 ordering; contact never before committee admits; crash@`committee_discovered` resumes at contact fan-out (no re-profile/re-discover); committee-size cap + semaphore honored; account-axis params present, committee/contact via explicit kwargs; import-linter green (no durable/profiling/verification source import).
**Note:** `discover_committee`/`profile_contact` take `conn` — the orchestrator runs each callable inside an injected `transaction()`/session-factory (injected, typed as a callable returning an async ctx mgr) so it stays import-light.

## M8A.2 — `DeepPhaseHandler` (branch: `m8a/deep-handler`, off M8A.1)
**Files:** `api/deep/handler.py`, `tests/api/deep/test_deep_phase_handler.py`.
```python
class DeepPhaseHandler:  # implements core.PhaseHandler
    phase = CampaignPhase.DEEP
    def __init__(self, *, scheduler: AccountScheduler, orchestrator: AccountDeepOrchestrator,
                 high_tier_resolver, checkpointer_factory): ...
    async def run(self, ctx: PhaseContext) -> PhaseResult: ...
```
**`run` body:** resolve high-tier accounts via `high_tier_resolver(ctx)` (D-B: claimstore `account.scoring.tier ≥ cutoff` keyed by committed `cutoff_version` from the checkpoint payload) → `AccountSpec`s → `scheduler.run_accounts(specs, campaign_run_id=ctx.campaign_run_id, checkpointer, run_one=orchestrator.run_one)`, each account wrapped in try/except (FAILED account → mark `account_run` FAILED, continue) → aggregate → `PhaseResult(COMPLETED, accounts_processed, cost_cents, payload=<refs manifest>)`; `PAUSED` on RUN `GRACEFUL_STOP`.
**Tests (fake registry/scheduler):** registering it → `advance()` dispatches DEEP (no `NoPhaseHandlerRegistered`); reads committed cutoff; one account raising doesn't fail the phase; RUN GRACEFUL_STOP → PAUSED; payload has no `value_json`.
**Build-time check:** verify the exact `tier_checkpoint` COMPLETED payload keys in `discovery_scoring/phases.py` (`cutoff_version`, `tier_distribution`, `tier_checkpoint_run_id`, …) — confirm the per-account list is NOT there before committing to the claimstore-query primary.

## M8A.3 — fan-out bounds + budget admission (branch: `m8a/fanout-budget`, off M8A.1)
**Files:** `api/deep/orchestrator.py` (contact-loop body), `config/schema.py` (+ `DeepPhaseConfig`), `tests/api/deep/test_orchestrator_budget.py`, `tests/config/test_deep_phase_config.py`.
**`DeepPhaseConfig`** (versioned, per-ICP overridable, beside `BudgetPolicy`/`RecursionPolicy`): `committee_size_cap: int`, `per_contact_estimate_cents: CostCents`, `per_contact_cap_cents: CostCents`, `max_parallel_accounts: int`, `max_contacts_in_flight: int`.
**Admission (per contact, in the orchestrator loop):** `d = await budget.check(scope=ACCOUNT, projected_cents=per_contact_estimate_cents, campaign_run_id, entity_id=account_entity_id, account_run_id)`; `ALLOW`→profile; `DENY`→stop admitting (partial committee + coverage note, NOT failure); `GRACEFUL_STOP`→propagate so handler returns `PAUSED`. The four bounds: committee-size truncation + `check(ACCOUNT)` + worker `facet_subworker_budget` + `Semaphore(max_contacts_in_flight)`.
**Tests:** DENY truncates loop → partial+coverage; RUN GRACEFUL_STOP→PAUSED; caps read from config (no hardcoded bound); all four exercised.

## M8A.4 — exactly-once spend (branch: `m8a/exactly-once`, off M8A.1+M8A.3; coordinate w/ M8A.0 owner)
**Files:** `api/deep/orchestrator.py` (spend-step txn), `durable/budget.py` (single-writer + reservation), `durable/account_run.py` (reconcile SET), `tests/api/deep/test_exactly_once_spend.py`, `tests/durable/test_budget_reconciliation.py`.
**Work:** (1) wrap committee-admit and contact-field-fill so claim write(s) + `BudgetEngine` charge + M7.4 ledger `succeed()` commit in **one** transaction (closes the `budget.py::record` deferred window). (2) Make `BudgetEngine.record` the single live writer of `account_run.cost_cents` for committee/contact; reconcile the account-axis `save_references` SET to `SUM(ledger charges)` at `contacts_complete` (or report-only). (3) Per-account reservation: decrement-at-admit / reconcile-on-record bounding concurrent over-commit (with M8A.3's `max_contacts_in_flight`).
**Tests:** crash-injection between charge and ledger-finalize → on resume `spent_cents == SUM(ledger cost_cents_charged)` (no under-count/double-charge); exactly one writer of `cost_cents` (reconciliation assert); concurrent admits cannot exceed per-account cap beyond the reservation bound.
**Gotcha:** this is a *correctness* issue on the hard cap — prove with the transaction boundary + crash-injection test, not a convergence argument.

## M8A.5 — handoff skeleton (branch: `m8a/handoff-skeleton`, off M8A.1)
**Files:** `api/deep/handoff_skeleton.py`, `api/deep/orchestrator.py` (fold refs), `tests/api/deep/test_handoff_skeleton.py`.
**Work:** reuse `core.handoff` read-only; build references-only `(account,persona)`-keyed skeleton: account+resonance refs from `AccountProfileResult`; `CommitteeResult.committee()` shells; JOIN each member's `ContactProfileResult.profile_claims` (`ProfileClaimView`) by `contact_entity_id`; fold ids into `account_run.references_index` under `{account,resonance,committee,contact:<id>}`; carry `CommitteeCoverage` (band + unsearched channels). **No new table** (D-D: compute-on-read; M12.2 materializes).
**Tests:** each member keyed `(account,persona)` + `role_on_committee`; M12.2 can JOIN by `contact_entity_id`; `references_index` is ids-only (no blob leak regression); budget-capped account → partial, not FAILED; no scores/narrative/provenance_index computed.

## M8A.6 — composition root + AC-6/AC-4 (branch: `m8a/composition`, off M8A.2+M8A.4+M8A.5; LAST)
**Files:** `api/deep/composition.py`, `api/__init__.py`, `tests/api/deep/test_composition_integration.py`, `tests/api/deep/test_gate_routing_ac6.py`, `tests/api/deep/test_identity_binding_ac4.py`.
**Work:** construct + inject all concretes (`PreSpendGate` [#1] into both callables — **required, non-None**; `verification.classify_binding` as `binding_classifier`; `DbBudgetEngine`; `AccountResearchGraph`; `AccountScheduler` w/ M8A.0 callback bound to `orchestrator.run_one`; `CommitteeSource`s + `LLMGateway` + `role_model`; `RecursionPolicy`/`DeepPhaseConfig`; session factory; M12 hook). Build `DeepPhaseHandler(...)`; `register_phase_handler(...)`. `load_deep_profiling_pack(conn)` + register account/resonance `AspectWorker`s (committee/contact are NOT aspect-registered — they run as callables).
**Tests:** end-to-end `tier_checkpoint→DEEP→VERIFICATION` produces `(account,persona)`-keyed `unverified` claims; **AC-6** fails if any committee/contact spend skips `gate.check`; **AC-4** facet claim born `identity_binding` == `classify_binding` verdict (STRONG verified handle / WEAK unpromotable same-name); import-linter: `api/deep` imports durable+profiling+verification, nothing-but-api imports `api/deep`; no worker calls another worker.

## Risk register (carried from the judge panel — all owned by an issue)
- Exactly-once cost hole (`budget.py::record` separate txn) → **M8A.4** (single-txn + crash-injection test).
- `AccountScheduler` no callback seam → **M8A.0** (additive callback; default path unchanged).
- `account_run` no sub-phase → **M8A.0** (additive column + migration; M8A is the integration milestone where one migration is expected).
- Concurrent contact over-commit (`check` reads spend-so-far) → **M8A.4** reservation + **M8A.3** `max_contacts_in_flight`.
- `cost_cents` double-writer (graph SET vs `record` increment) → **M8A.4** single-writer reconciliation.
- Two checkpoint mechanisms drift → gap-recompute backstop (every stage gap-driven + waterfall-idempotent); ledger authoritative, marker advisory.
- tier_checkpoint payload lacks per-account list → **M8A.2** D-B (claimstore query keyed by committed cutoff_version; verify payload keys at build).
- Gate composed before #1 done → hooks already exist on both callables; M8A.6 makes the injected gate a required arg + AC-6 fails the build if any spend path skips it.
- Born-correct binding needs `classify_binding` injected (M9.4) → **M8A.6** injects + AC-4 (immutable column → classify BEFORE insert; the fill path already supports the injectable `binding_classifier`).

## Open decisions (defaults in spec §Cross-cutting): D-A package=`api/deep/`; D-B claimstore tier-query keyed by committed cutoff_version; D-C accept checkpoint duality (ledger authoritative); D-D no handoff table; D-E accept Redis-7 floor.

## TODO
- [x] verified facts + design panel + synthesis integrated
- [x] spec `docs/specs/M8A-project-run-deep-orchestration.md`
- [x] implementation plan (this doc)
- [ ] **awaiting user go-ahead** to create the M8A milestone + ENG issues (M8A.0…M8A.6) in Linear (Engineering team / "Research Subsystem" project `2c743aca-0c49-4b3b-b845-6ff23e957fd1`; new label `layer:deep-orchestration`; format `M8A.# — …` + spec backlink + blockedBy DAG).
