# 2026-06-22 — M7.5 (ENG-153) Budget caps & cost-governance engine

Branch `m7/durable-execution`. Last issue of M7. Baseline at kickoff: `make check` 471 passed /
326 skipped / 10 contracts; 112 durable DB tests on `clue_m7`; single head `df78df38b168`; db-smoke
reversible. Isolated DB: `CLUE_DATABASE_URL=postgresql+asyncpg://clue:clue@localhost:5432/clue_m7`
for ALL DB-touching commands (NEVER the shared `clue`).

## What M7.5 is
Implement the `core.BudgetEngine` seam (already frozen in `core/execution.py`: `estimate` / `check`
/ `record` / `set_campaign_cap` / `burn_down`; verdicts `BudgetVerdict.{ALLOW,DENY,GRACEFUL_STOP}`,
scopes `BudgetScope.{ACCOUNT,PASS,RUN}`, value types `Estimate`/`BudgetDecision`/`BurnDown`). The
single chokepoint for spend authorisation + the live cost accounting that feeds the client surface
(M13.4) and the learning loop (M13.3). Caps are policy-as-data (`config.BudgetCaps`, already wired).

## Key existing facts (verified)
- `campaign_run` already has `budget_cap_cents` + `spent_cents` (M7.3 migration). `account_run` has
  `cost_cents` (= the per-account *spent*; no separate spent col needed) but NO `budget_cap_cents`.
- `BudgetCaps` (config/schema.py) exists, wired into Config/ConfigOverlay/loader as `budget_caps`:
  per_campaign_hard_cap_cents, per_account_cap_cents: dict[tier->CostCents], per_contact_cap_cents,
  pass_a_cap_cents_per_account (default 5). M7.5 *builds on it* (do not rename).
- `CampaignRun` already injects an optional `budget_engine`: `pre_run_estimate` delegates to
  `estimate`; `adjust(budget_cap)` flows to `set_campaign_cap`. `FakeBudgetEngine` stub in conftest.
- M7.2 `SpawnGuard.may_spawn` already takes `remaining_budget_cents` + denies reason BUDGET — the
  per-account spawn-denial. M7.5 provides the cap that feeds the envelope; no SpawnGuard change.
- obs has `record_cost_burndown`, METRIC_COST_CENTS / METRIC_COST_CAP_CENTS, record_phase_progress.

## Design decisions (the non-obvious ones)
- **Three scopes, all real:** ACCOUNT = per-account deep cap (`account_run.budget_cap_cents` row
  override → else policy.per_account_cap_for(tier)); DENY on breach. PASS = the cheap Pass-A
  per-account ceiling (`pass_a_cap_cents_per_account`); DENY on breach. RUN = the campaign hard cap
  (`campaign_run.budget_cap_cents`); GRACEFUL_STOP on breach (never DENY/kill). No per-pass *spend
  counter* in V1 (no column for it) — PASS check is a per-account-rate guard, documented.
- **Run-scope STOP iff `spent + projected >= cap`** (>=, slightly conservative — can't spend the last
  cent to land exactly on cap; keeps spend strictly under the hard cap). This makes the projected=0
  pre-gate fire exactly when a cap was lowered below current spend (`spent >= cap`). Account/Pass
  scope DENY iff `spent + projected > cap` (strict; exact-fit allowed there).
- **Estimate math:** deep_fraction(cutoff)=clamp(1-cutoff,0,1) (uniform-score assumption,
  documented; `Estimate.confidence` default 0.5 signals it). Nested tiers sorted by cutoff desc, each
  account priced once at its TOP qualifying tier's CAP (conservative upper bound — the honest default
  for a pre-run ceiling). pass_a = N × pass_a_cap_cents_per_account. estimated = pass_a + pass_b.
  Empty cutoffs → Pass A only. estimate() best-effort persists `campaign_run.estimated_cents`
  (UPDATE no-ops if run absent) so burn_down can show spent-vs-estimate.
- **record() = the single live increment** of campaign_run.spent_cents (+ account_run.cost_cents when
  account_run_id given). Called once per ledger charge (inside the `idempotent` EXECUTE branch; NOT
  on replay) → spent ties exactly to ledger cost_cents_charged. FOLLOW-UP: M7.1 save_references also
  SETS account_run.cost_cents; in the integrated M8 flow record() is the live writer and the final
  SET reconciles (total == sum of charges). Settle single-writer ownership when M8 wires it.
- **M7.3 graceful-stop coupling = a budget pre-gate in `advance()`:** before a spend phase
  (DISCOVERY/SCORING/DEEP/VERIFICATION), if budget wired and `check(RUN, projected=0)` ==
  GRACEFUL_STOP (spent>=cap), mark run PAUSED (cooperative, NOT an AWAITING_INPUT checkpoint — so
  resume() re-enters the SAME phase) and skip the handler. raise-cap via adjust + resume continues.
  reverse_profiling/icp_confirmed/tier_checkpoint/handoff ungated (setup/human/output). Existing M7.3
  tests unaffected (FakeBudgetEngine.check → ALLOW; engine None → gate skipped).
- **budget_event** is append-only audit (reject trigger + monotonic seq, like adjustment_journal):
  kinds check_deny / graceful_stop / breach_pending / cap_raised (cap_raised = any cap (re)set;
  breach_pending additionally when new cap < spent). Charges are NOT events (they live on the ledger
  + spent counters).

## Plan (files)
1. config/schema.py — BudgetCaps += `default_per_account_cap_cents` + `per_account_cap_for(tier)`.
2. durable/enums.py — `BudgetEventKind`.
3. durable/spans.py — SPAN_BUDGET[_CHECK/_ESTIMATE/_EVENT] + ATTR_BUDGET_SCOPE/VERDICT/KIND/
   PROJECTED_CENTS/CAP_CENTS/REMAINING_CENTS.
4. migration `<hash>_budget_engine_m7_5_eng_153` off df78df38b168: CREATE TYPE budget_scope (mirror
   core.BudgetScope) + budget_event_kind (mirror durable enum); ALTER account_run ADD budget_cap_cents;
   ALTER campaign_run ADD estimated_cents; CREATE TABLE budget_event (append-only + seq + index).
5. durable/budget_event.py — repo: BudgetEventRow, RunBudgetState, AccountBudgetState, insert/list
   budget_event, get_run/account_budget_state, add_run/account_spend, set_estimated_cents,
   set_account_budget_cap.
6. durable/budget.py — BudgetStore Protocol + DbBudgetStore + BudgetEngine impl + errors.
7. durable/campaign.py — the budget pre-gate in advance(); optional burn_down passthrough.
8. durable/__init__.py — exports.
9. tests/durable/: test_budget_estimate (pure), test_budget_engine (FakeBudgetStore), 
   test_campaign_budget_gate (in-memory), test_budget_db (DB-gated parity/round-trip/append-only).
   conftest += FakeBudgetStore.

## Implemented — files as planned (all 9). Verified green before review:
`make check` 512 passed / 10 contracts; 166 durable DB tests on clue_m7; db-smoke reversible; head
`a6628f6432c6`.

## Adversarial review (Workflow, 5 lenses + per-finding verify, 39 agents): 34 raw → 15 confirmed.
ALL confirmed findings were LOW or NIT (no HIGH/MEDIUM survived verification — the engine is sound).
16 verify agents hit a transient spend limit; their underlying findings were dupes of confirmed ones
or by-design deferrals (judged manually). FIXED:
- **set_campaign_cap breach boundary `>` → `>=`** to match the inclusive RUN graceful-stop gate (at
  spent==cap the run IS stopped, so BREACH_PENDING must fire). +test (spent==cap).
- **record() / add_spend fail-loud on a missing run/account row** (was a silent no-op UPDATE,
  asymmetric with check/burn_down). add_run_spend/add_account_spend now return rowcount;
  DbBudgetStore.add_spend raises BudgetStateNotFound on 0 rows (run+account in ONE txn → atomic
  rollback). FakeBudgetStore mirrors it (no setdefault auto-create). +2 tests.
- **project_spend cumulative-boundary rounding** — round the cumulative count then take the marginal,
  so per-tier counts sum to round(n×total-share) (independent per-tier rounding could inflate by
  +1/tier, e.g. n=7 {0.5,0.25} gave 6 not 5). +test. Docstring softened: deep-count is the
  *expected* share (confidence 0.5), per-account priced at the cap — not a hard ceiling.
- **budget_event kind↔scope CHECK** added to the migration (check_deny⇒account/pass;
  graceful_stop/breach_pending/cap_raised⇒run) — the append-only audit is self-enforcing, not
  trusting the engine. +DB test (mismatch rejected).
- **DRY**: budget_event.py uses shared `core.factories.decode_jsonb` (dropped the 4th private copy;
  the shared one also handles str payloads → strictly more correct).
- +cap-gauge (METRIC_COST_CAP_CENTS) assertion; +pre_run_estimate-after-cutoff-adjust end-to-end test.
DOCUMENTED / DEFERRED (code notes added; benign today, M8 wiring):
- record() docstring: transactional caveat (airtight exactly-once needs charge+ledger in ONE txn =
  M8 claim-write path); routing is account_run_id-driven (scope/entity_id are protocol-symmetry).
- per_contact_cap_cents marked RESERVED — not enforced until M8 (no contact-run row at M7; per-entity
  contact spend governed by per-account + per-campaign cap).
- adjust(budget_cap) dual same-value cap write (campaign store owns column+journal; engine
  re-asserts + emits governance events) — idempotent, benign under single-driver; consolidation is a
  noted follow-up (cf. account_run.cost_cents single-writer).
- phase-scope PhaseResult.cost_cents is the *nominal* ledger charge (best-effort; the airtight charge
  is the account-step ledger) — already documented in _finalize_phase; burn_down's spent_cents is
  driven by record() (M8 wires worker→record).

## M7.5 → downstream follow-ups (for M8)
- Wire worker spend through `BudgetEngine.record(account_step)` inside the `idempotent` EXECUTE branch
  (the single live writer of spent_cents); settle account_run.cost_cents single-writer vs
  M7.1 save_references (record live + final SET reconciles; total == sum of charges).
- Add a contact/committee cap path honouring `per_contact_cap_cents` when M8 builds contact runs.
- The per-account `budget_exceeded` *marking* (AccountRunStatus.BUDGET_EXCEEDED) on a DENY is the M8
  worker/graph's job; M7.5 ships the DENY verdict + the enum.

## Closing state (2026-06-22): DONE, green, PAUSED for user review. Nothing pushed (local only).
`make check` **517 passed / 340 skipped / 10 contracts**, mypy clean, lint clean. **172 durable DB
tests** pass on clue_m7. db-smoke up→down→up reversible; single head `a6628f6432c6`. ENG-153 In
Progress in Linear (move to In Review after commit).
