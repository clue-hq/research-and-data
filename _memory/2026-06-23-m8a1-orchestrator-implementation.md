# M8A.1 — `AccountDeepOrchestrator` (the per-account account→committee→contact trunk) — implementation

**Date:** 2026-06-23 · **Branch:** `m8a/orchestrator` (off `m8a/durable-seams` = M8A.0) · **Spec:**
`docs/specs/M8A-project-run-deep-orchestration.md` §M8A.1 · **Plan:**
[[2026-06-23-m8a-implementation-plan]].

The trunk the rest of M8A builds against. Pure composition: sequences the three M8 worker families
per high-tier account via their **direct callables**, resumable on the M8A.0 `sub_phase` marker.

## What shipped
- **`config/schema.py`** — `DeepPhaseConfig` (frozen): `committee_size_cap`, `max_contacts_in_flight`,
  `max_parallel_accounts`, `per_contact_estimate_cents`, `per_contact_cap_cents`. M8A.1 reads the first
  two; the rest are the **fixed interface** M8A.3 (budget admission) / M8A.2 (accounts-per-pass) consume
  — defined once in the trunk. Exported from `config`.
- **`api/deep/run_io.py`** — `AccountRunIO` Protocol (`ensure` / `load` / `save`, own-transaction) +
  `DeepRunState` (resume snapshot: sub_phase + references_index + cost) + `DbAccountRunIO` (binds the
  M7.1 repo + the M8A.0 sub-phase setter; `save` does `save_references` + `set_account_sub_phase` in one
  transaction). `_DB_ACCOUNT_RUN_IO_IS_AN_IO` conformance line.
- **`api/deep/orchestrator.py`** — `AccountDeepOrchestrator.run_one(spec, *, campaign_run_id)` →
  `AccountDeepResult`; `deep_account_run_id` (deterministic `uuid5(campaign:entity)`); `AccountDeepResult`
  (references-only: the three stage results + cost + final sub_phase + flattened `claim_refs`).
- **`api/deep/__init__.py`** — package surface.
- **Tests** — `tests/api/deep/test_orchestrator.py`, 9 fake-driven (no DB): ordering; resume@committee_
  discovered (no re-profile/re-discover, reloads members); full-resume no-op; committee_size_cap; max_
  contacts_in_flight; spec+explicit-kwargs+one-run_id; deterministic id; not-found short-circuit; empty
  committee. Plus `tests/api/{,deep/}__init__.py`.

## Key design decisions (verified against the actual base, origin/main)
- **Direct callables, not the M7 graph.** `profile_account` (account.py:241) takes `spec: ICPSpec` +
  `tenant_id` + `campaign_run_id` as **explicit kwargs** (it is self-contained, no checkpointer/graph),
  so the account axis needs **neither `params_for_run` nor the "#2" graph param-threading** — the plan's
  "#2 on the account axis" is moot here. committee/contact take a `conn` (orchestrator opens one via the
  injected `session_factory`).
- **Gate: `pre_spend_gate` → `profile_account` ONLY.** On origin/main, `discover_committee` /
  `profile_contact` do **NOT** accept `pre_spend_gate` — that seam is on the unmerged **#1** branch. So
  M8A.1 wires the gate only where the callable accepts it; committee/contact gate routing lands at
  **M8A.6** (when #1 merges). `profile_contact` DOES accept `binding_classifier` / `use_class_tagger`
  (M8.4/M9.4 are on main), defaulted to the profiling sentinels (M8A.6 injects `classify_binding`).
- **Resume = sub_phase chain + persisted member work-list.** On stage-2 completion the admitted member
  contact-ids are persisted under `references_index["committee_contacts"]`; on resume the fan-out reloads
  them (str→`EntityId(uuid.UUID)`) **without re-discovering** (the AC). The claim-store gap-recompute is
  the correctness backstop. `save` REPLACES the index, so the orchestrator load→mutate→saves the full
  dict (M8A.5's fold MUST do the same — documented on `AccountRunIO.save`).
- **Deterministic `account_run_id`** so a resumed DEEP phase re-derives the same id (the per-account
  analogue of the graph's `thread_id`). It is the shared `claim.run_id` for all three stages.
- **Not-found account short-circuits** (returns the FAILED account result without advancing into a
  stage-2 `ValueError`); the M8A.2 handler records it FAILED.

## Verification (all green)
- ruff + format, mypy (198 src files), import-linter (**11/0** — `api/deep` composes
  `durable`+`profiling`+`config`; nothing imports `api`).
- `tests/api/deep/` = **9 passed**; `tests/test_config_*` + `tests/test_seams.py` green. (All pure-Python
  fakes — no DB; `DbAccountRunIO`'s real wiring is integration-tested at M8A.6.)

## Adversarial review (20 agents, 4 confirmed — all minor/nit, all addressed)
1. (minor) orchestrator imported `DEFAULT_*` sentinels vs "only types" wording → docstring corrected
   (types + inert default-arg sentinels, no worker body).
2. (minor) no empty-committee test → added `test_empty_committee_completes_with_zero_contacts`.
3. (nit) not-found account advanced into a stage-2 raise → added the short-circuit guard + a test.
4. (nit) `save` REPLACES the index (not merge) → documented on `AccountRunIO.save` for M8A.5.

## Follow-ups (downstream M8A issues)
- **M8A.2** `DeepPhaseHandler`: bind `run_one` as the scheduler callback via a closure capturing
  `campaign_run_id` (`run_one=lambda acct: orch.run_one(acct, campaign_run_id=cid)`); resolve high-tier
  accounts; own per-account FAILED isolation.
- **M8A.3** budget admission in the contact loop (`BudgetEngine.check(ACCOUNT)`), reading the
  `per_contact_*` `DeepPhaseConfig` fields already shipped.
- **M8A.4** exactly-once: advance `sub_phase` inside the spend transaction via the **conn-taking**
  `account_run.set_account_sub_phase` (not the own-transaction `DbAccountRunIO.save`).
- **M8A.5** handoff fold: load→mutate→save the full `references_index` (never a partial), or it clobbers
  `committee_contacts`.
- **M8A.6** inject the concretes (`DbAccountRunIO`, real workers, `PreSpendGate` into committee/contact —
  needs #1 merged — `verification.classify_binding` as `binding_classifier`) + the AC-6/AC-4 tests.
