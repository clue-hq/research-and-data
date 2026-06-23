# M8A.4 — Exactly-once spend on the committee/contact path (ENG-170)

**Date:** 2026-06-23 · **Branch:** `m8a/exactly-once` (off `m8a/orchestrator` @ `a002007`, which has
M8A.0/.1/.2/.3/.5). New branch because m8a/orchestrator is being worked in parallel (user).
**Spec:** `docs/specs/M8A-campaign-run-deep-orchestration.md` §M8A.4 · **Plan:**
[[2026-06-23-m8a-implementation-plan]] §M8A.4 · depends on M8A.1 (orchestrator) + M8A.3 (admission).

## The hole this closes (verified first-hand)
- **No deep code calls `BudgetEngine.record` today.** The orchestrator only `check`s (admission);
  it never `record`s. So `campaign_run.spent_cents` is **never moved by the DEEP phase** → the
  client hard cap (`check(RUN)`) is blind to deep spend. This is the core gap.
- **`profile_account` does NOT write `account_run.cost_cents`** (verified: `profiling/account.py`
  returns cost in `AccountProfileResult.cost_cents`, writes no run row). The orchestrator's
  `_io.save` → `save_references` (account_run.py:189) is the **only** writer of `cost_cents` today.
  → so making `record` the single writer is clean (remove the orchestrator's cost SET).
- `budget.py::record` docstring **explicitly defers** airtight exactly-once to "the M8 claim-write
  path … commit the charge and finish the ledger in ONE transaction." M8A.4 IS that path.
- `run_io.py` docstring already anticipates: "the boundary M8A.4 tightens to also enclose the spend."

## Verified seams
- `discover_committee(conn, ...)` / `profile_contact(conn, ...)` / `fill_contact_field(conn, ...)`
  **all take a conn** and write claims on it → the orchestrator already owns the per-stage
  transaction (committee stage opens `session_factory() as conn`; each `_one` opens its own).
- `claim_idempotency_step(conn, ...)` / `finish_idempotency_step(conn, ...)` are conn-taking module
  fns (durable.idempotency, exported). `DbIdempotencyStore` docstring blesses "write the claim and
  call finish_idempotency_step inside one transaction" for effect-atomicity.
- `add_run_spend(conn,…)`/`add_account_spend(conn,…)` (durable.budget_event) are conn-taking.
- `api/deep` is **import-exempt** (under `api`, NOT in the independence set) → may import
  `durable.idempotency`, `durable.budget`, `profiling` freely. (Confirmed: orchestrator already does.)
- `core.BudgetEngine` is FROZEN (record has no conn). → do NOT touch it. Add conn to the **concrete**
  `durable.BudgetEngine.record` + `BudgetStore.add_spend` (additive, conn defaults None = today).
- `idempotency_key(scope, *parts)` + `IdempotencyScope.ACCOUNT_STEP` exported from `core`.
- `DeepPhaseConfig`: `per_contact_estimate_cents=50`, `per_contact_cap_cents=200` (the latter unused).

## Design (Approach: single-transaction spend step + local reservation, no migration)
The exactly-once **unit** = one committee discovery / one contact profile / (best-effort) one account
charge. Each runs as: `claim ledger → worker writes claims → record(conn) → finish ledger`, all on
**ONE conn**, committed by the orchestrator's `async with session_factory() as conn`. A crash rolls
back the whole unit (claims + charge + ledger-claim-row) → re-execute fresh; a success commits
atomically → REPLAY skips re-spend. This is stronger than the M7.4 `idempotent()` CM (separate txns,
leaves `in_progress` recovered by staleness) — here a rollback un-does the in_progress insert too.

### New seam — `api/deep/spend.py` (injected, fake-testable)
- `Spendable` Protocol: `cost_cents`, `claim_refs` (AccountProfileResult/CommitteeResult/
  ContactProfileResult all satisfy; `_Ready` wraps already-done work).
- `StepOutcome`: `replayed`, `claim_ids: tuple[str,…]`, `cost_cents`, `result: Spendable|None`.
- `ExactlyOnceSpend` Protocol: `run_step(conn, *, key, campaign_run_id, account_run_id, entity_id,
  work: Callable[[conn], Awaitable[Spendable]], stale_after) -> StepOutcome`.
- `DbExactlyOnceSpend(budget: durable.BudgetEngine)`: claim → REPLAY(return recorded ids+cost,
  no body/charge) / CONFLICT(raise) / EXECUTE(`result=await work(conn)` → `record(conn=conn, ACCOUNT,
  account_run_id)` → `finish(conn, SUCCEEDED, {claim_ids}, cost)`). Holds the **concrete** engine so
  record is conn-aware; the orchestrator's `budget` (core-typed) stays for `check`.
- `deep_step_key(account_run_id, step)` = `idempotency_key(ACCOUNT_STEP, account_run_id, step)`;
  steps `"account"|"committee"|f"contact:{id}"`.

### Single-writer reconciliation
- `record` is the SOLE writer of `account_run.cost_cents` (+ `campaign_run.spent_cents`) for ALL deep
  spend. The orchestrator's references-fold STOPS writing `cost_cents`.
- `durable/account_run.py`: add `fold_references(conn, id, *, references_index, status)` (refs +
  status + updated_at, **no cost_cents**). `save_references` stays (M7 graph still uses it).
- `api/deep/run_io.py`: `AccountRunIO.save` → `fold(conn, id, *, references_index, status, sub_phase)`
  (takes a conn so it shares the spend's transaction; drops `cost_cents`). `load` keeps reading
  `cost_cents` (record-owned) for the resume seed.
- Stage transactions: committee stage folds refs+work-list+marker in the SAME conn as the committee
  spend (so the member-id work-list is never lost vs the ledger). Contact refs are rebuilt on resume
  from each contact's ledger `result_ref` (claim_ids) via REPLAY → a final fold+marker after gather.
- Reconciliation invariant (AC2): `account_run.cost_cents == SUM(ledger cost_cents_charged)` at
  `contacts_complete` (every spend does record(cost)+finish(cost) off the same value).

### Local reservation (AC3) — NO schema change, does NOT touch `projected`
`check(ACCOUNT)` reads committed `cost_cents`; concurrent launched-not-yet-recorded peers aren't in
it → N concurrent admits could overshoot. Guard in `_profile_contacts`, using `decision.cap_cents`:
after an ALLOW, if `cap>0 and committed + reserved + estimate > cap` → stop admitting (partial/DENY).
`reserved += estimate` at admit; on a contact's charge-commit `reserved -= estimate; committed +=
actual`. Single-threaded asyncio → safe. Kept OUT of `projected_cents` so M8A.3's
`test_admission_projects_per_contact_estimate_from_config` (asserts projected==config) stays green and
the engine remains the single cap authority. FakeBudgetEngine returns `cap_cents=0` → guard inert in
existing tests (0 = uncapped).

### Account axis (out of scope for atomicity, per spec)
profile_account opens its own txns; the orchestrator charges its cost via a short
`run_step` (work returns the precomputed result) so it gets a ledger row (reconciliation anchor) +
record. Atomicity-with-its-own-claims is the M7 graph's domain; a crash before the account record
under-counts the account portion (accepted — spec: "account-axis cost path unchanged, only
reconciled"). The marker gates re-entry; REPLAY prevents double-record on resume.

## Cost accounting on resume
Seed `cost = state.cost_cents` (record-owned, read by `load`); `if not outcome.replayed: cost +=
outcome.cost_cents` (replayed spends are already in the seed → never double-add). Refs built from
`outcome.claim_ids` (authoritative for both EXECUTE and REPLAY).

## Files
1. `durable/budget.py` — `record`/`DbBudgetStore.add_spend` += optional `conn` (additive, pass-through).
2. `durable/account_run.py` — `fold_references` (refs+status, no cost).
3. `api/deep/spend.py` — NEW (Spendable/StepOutcome/ExactlyOnceSpend/DbExactlyOnceSpend/_Ready/key).
4. `api/deep/run_io.py` — `save`→`fold(conn, …, no cost)`; load unchanged.
5. `api/deep/orchestrator.py` — inject `spend`; 3 stages via run_step on a shared conn; reservation.
6. `api/deep/__init__.py` — export spend symbols.
7. Tests: `tests/durable/conftest.py` FakeBudgetStore.add_spend +conn; update
   `tests/api/deep/test_orchestrator*.py` (`_orchestrator` injects FakeExactlyOnceSpend; io.save→fold);
   NEW `tests/api/deep/test_exactly_once_spend.py` (in-mem: replay-skips-recharge, reconciliation,
   reservation); NEW `tests/durable/test_budget_reconciliation.py` (DB: crash-injection
   spent==SUM(ledger), single-writer cost_cents).

## No migration (reservation is in-memory; uses existing idempotency_ledger + spent/cost columns).

## Status: design locked; implementing.
