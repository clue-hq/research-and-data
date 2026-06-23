# M8A.3 — Fan-out bounding + budget admission at the contact chokepoint — implementation

**Date:** 2026-06-23 · **Branch:** `m8a/fanout-budget` (off `m8a/orchestrator`-equiv tip = M8A.0 + M8A.1 +
docs; created in this workspace as a NEW branch because M8A.2 is being implemented in parallel on
`m8a/orchestrator`) · **Spec:** `docs/specs/M8A-campaign-run-deep-orchestration.md` §M8A.3 · **Handoff:**
[[2026-06-23-m8a3-handoff]] (pulled onto this branch from `m8a/orchestrator`) · **Plan:**
[[2026-06-23-m8a-implementation-plan]] · builds on [[2026-06-23-m8a1-orchestrator-implementation]].

The budget-admission gate for the per-contact fan-out — the concrete cost dial (*fan-out-per-account ×
accounts-per-pass*, Doc C §5). The four fan-out bounds now all live at the single contact chokepoint.

## What shipped (3 files; NO config/durable/api changes)
- **`api/deep/orchestrator.py`** — the only behavioral change:
  - `AccountDeepOrchestrator.__init__` takes a **required** `budget: BudgetEngine` (injected, typed against
    the frozen `core` protocol).
  - `_profile_contacts` rewritten from a one-shot `gather(all)` into an **admit-then-launch loop**: before
    each member, `budget.check(scope=ACCOUNT, projected_cents=config.per_contact_estimate_cents,
    campaign_run_id, entity_id=account_entity_id, account_run_id=run_id)`; `ALLOW` → `create_task` under the
    `max_contacts_in_flight` semaphore; `DENY`/`GRACEFUL_STOP` → stop admitting and `break`. Returns
    `(results, budget_stop)`. `campaign_run_id` is now threaded into `_profile_contacts`.
  - `AccountDeepResult` gains `budget_stop: BudgetVerdict | None` (surfaced for the M8A.2 handler).
  - The four bounds, all config-driven, none hardcoded: (a) `committee_size_cap` slice (pre-existing), (b)
    `check(ACCOUNT)` admission (new), (c) per-tier `facet_subworker_budget` from `RecursionPolicy`
    (pre-existing), (d) `max_contacts_in_flight` semaphore (pre-existing).
- **`tests/api/deep/test_orchestrator.py`** — added a configurable `FakeBudgetEngine` (scripted verdicts,
  records every `check`, `raise_after` to simulate a failing engine) + a `budget` param on the `_orchestrator`
  helper (defaults to an ALLOW-everything fake, so the 9 M8A.1 tests stay green unchanged).
- **`tests/api/deep/test_orchestrator_budget.py`** (new) — 7 tests: DENY-after-K → partial-not-FAILED;
  GRACEFUL_STOP surfaced; all-ALLOW → no stop; projection is config-driven (+ scope/entity/run_id keys); bound
  (c) facet budget from policy; DENY-on-first-contact (K=0); budget.check-raises → no orphaned tasks.

## Key design decisions (both adversarially validated — see Review)
- **A budget stop is a *finished partial*, not a pause of the account.** Both `DENY` and `GRACEFUL_STOP`
  advance the marker to `CONTACTS_COMPLETE` / status `DONE` (the stage-3 save is byte-identical to M8A.1). The
  difference is carried *only* by `budget_stop` on the result: the **M8A.2 handler** maps `GRACEFUL_STOP` →
  `PhaseResult(PAUSED)` (suspend the phase) and `DENY` → continue the batch with partial coverage. Rationale:
  GRACEFUL_STOP = "finish the in-flight unit, stop at the next checkpoint" — the in-flight *unit* is the
  account (finished as a partial); the checkpoint stop prevents *further* accounts. This keeps M8A.3's save
  path identical to the trunk and **avoids a references_index overwrite-on-resume hazard** (a re-run stage 3
  would re-fold already-profiled contacts' now-empty `claim_refs` over the persisted ids).
- **`committee_contacts` persists the FULL discovered committee, not the admitted subset.** This is the M8A.1
  resume work-list contract; narrowing it would drop members on a legitimate stage-3 resume and destroy the
  coverage denominator (profiled 2 of 5). The admitted set lives separately in the `contact:<id>` ref keys +
  `result.contacts`.
- **`budget` is a required ctor arg** (not `| None`): cost governance is non-negotiable, and a required arg
  means no dead "skip admission" branch. (Contrast `pre_spend_gate`, which is `| None` only because the
  committee/contact callables don't accept it on this base — that lands at M8A.6 with #1.)

## Adversarial review (5-lens → verify; workflow `wf_dfb1b110-7fb`, 9 agents)
4 raw findings → 2 confirmed, 2 refuted:
- **CONFIRMED (major), fixed:** *orphaned tasks on `budget.check()` exception.* `create_task` schedules
  eagerly, so a `check` raising mid-loop (or one `_one` raising in the gather, which doesn't cancel siblings)
  left tasks detached. **Fix:** wrapped the admit loop + gather in `try/except BaseException:` that cancels
  every launched task and `gather(..., return_exceptions=True)`-drains before re-raising. Covers both the
  check-raises orphan and the happy-path sibling leak; also forwards a cancellation of `_profile_contacts` to
  its children. New test `test_budget_check_exception_cancels_admitted_tasks_no_orphans` proves no task is left
  pending (uses `raise_after=2` + a delayed contact fake + `asyncio.all_tasks()`).
- **CONFIRMED (nit), added:** DENY-on-first-contact (K=0) edge test — cheap lock-in (no distinct code branch).
- **REFUTED:** "resume after DENY re-checks denied contacts" — false: DENY advances to `CONTACTS_COMPLETE`, so
  resume *skips* stage 3 wholesale (no re-check); the suggested "collapse the work-list to admitted" fix would
  break the M8A.1 resume contract + coverage denominator. Validates the two design decisions above.
- **REFUTED:** "missing resume-after-DENY test" — duplicates `test_full_resume_is_a_no_op` (DENY persists no
  distinct resume state; `budget_stop` is transient, never persisted); exercises zero new code.

## Verification (all green)
- ruff format + lint, **mypy (198 src files)**, **import-linter 11/0** (`api/deep` still imports only
  `core`+`config`+injected callables; the three new core imports are `BudgetEngine`/`BudgetScope`/
  `BudgetVerdict`).
- `tests/api/deep/` = **16 passed** (9 M8A.1 unchanged + 7 M8A.3). All pure-Python fakes, no DB.
- Did NOT run the full DB suite to completion: three Conductor workspaces (phoenix/charlottetown/this) were
  each running `pytest` against the shared local `clue` DB concurrently (the M8A.0-noted cross-workspace
  contention) — a confounded signal, and this change touches no DB path. Static gates + the 16 api/deep tests
  + a 28-test non-DB sweep (api+config+seams) are the authoritative gate for a DB-free change.

## Follow-ups (downstream M8A issues)
- **M8A.4** (exactly-once, after this branch, co-touches `durable/budget.py`): the sequential admit reads
  spend-so-far while launched peers haven't `record()`-ed → bounded over-commit window (paired with
  `max_contacts_in_flight`). Closing that window (a reservation) + the single-transaction charge are M8A.4. The
  admission `check` seam is left open here exactly for it to wrap.
- **M8A.2** (handler, parallel on `m8a/orchestrator`): reads `AccountDeepResult.budget_stop` → `GRACEFUL_STOP`
  ⇒ `PhaseResult(PAUSED)`, `DENY` ⇒ partial-coverage `COMPLETED`. The field name/type (`budget_stop:
  BudgetVerdict | None`) is the contract these two branches integrate on.
- **`per_contact_cap_cents`** is in `DeepPhaseConfig` but NOT yet wired: `profile_contact` accepts no
  per-contact `budget_cap_cents` on this base, so the sub-envelope carving has no sink. Wire it when the worker
  grows the param (M8A.6) or reconcile against `estimate()` (the spec's recommended flat-config default).
