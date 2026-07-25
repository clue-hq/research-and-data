# M8A.6 — DEEP-phase composition root + AC-6/AC-4 enforcement

**Date:** 2026-06-24 · **Branch:** `m8a/composition` (off `m8a/exactly-once` = the M8A.0–M8A.5 + M8A.4 chain).
**Spec:** `docs/specs/M8A-project-run-deep-orchestration.md` §M8A.6 · **Plan:** [[2026-06-23-m8a-implementation-plan]] §M8A.6 · prior: [[2026-06-23-m8a4-exactly-once-spend]], [[2026-06-22-m8a-orchestration-design]].

## What M8A.6 is
The one co-import point that wires the deep phase end to end: construct every concrete the M8A.1 orchestrator + M8A.2 handler are typed against, inject them, register `DeepPhaseHandler` so `CampaignRun.advance()` dispatches `CampaignPhase.DEEP`, and add the two deferred governance-enforcement tests (M9.1 AC-6 gate routing, M9.4 AC-4 born binding). New file: `src/clue_research/api/deep/composition.py`.

## The integration reality I hit (and resolved) — READ THIS FIRST
The spec/plan **assumed issue #1 (the committee/contact pre-spend-gate seams) was already merged** into the M8A chain ("Both seams already exist on the callables … M8A only injects"). **It was not.** On this chain's base (`54b8c50` deep-profiling merge), `discover_committee` / `profile_contact` / `fill_contact_field` did **not** accept `pre_spend_gate`. Issue #1 lived as two unmerged commits on `pre-spend-gate-committee-contact` / `m8a/handoff-skeleton`:
- **`f2cd4ff`** — *M9.1 Option C: enumeration pre-spend variant + committee/contact gate seams* (adds `pre_spend_gate` to the three callables + the `CommitteeAspectWorker`/`ContactProfileAspectWorker`; adds `PreSpendKind`/`EnumerationScope` core enums; the `gate_decision` enumeration-variant migration `c74c23defd01`; the `request_kind`/`enumeration_scope` columns + nullable `field_key`).
- **`60293f4` + `d551e60`** — the **M8 deep-profiling composition root** `api/composition.py` (`load_research_packs`, `build_pre_spend_gate`, `production_binding_classifier` / `VerificationBindingClassifier`, `build_worker_registry`, …) + the governance/composition tests.

Resolution (the work this branch did before M8A.6 proper):
1. **Cherry-picked `f2cd4ff`** (clean — it touches files M8A never touched). → committee/contact callables now gate.
2. **`alembic merge`** the two heads `ee97c497d31f` (M8A.0 sub_phase) + `c74c23defd01` (gate enum) — both off `089dc65b5814` → join `3df3b2f629fd`. db-smoke (up→base→up) green on isolated `clue_m8a6`; single head.
3. **Brought in the M8 composition root** via `git checkout d551e60 -- api/composition.py api/__init__.py tests/api/{conftest,test_composition,test_governance_integration}.py` (+ `tests/api/__init__.py`). These provide the M9-governance helpers M8A.6 reuses. 8/8 governance+composition tests pass on this branch.
4. **Wired the gate into the orchestrator** — `orchestrator.py` now passes `pre_spend_gate=self._pre_spend_gate` to the `discover_committee` + `profile_contact` work-lambdas (it previously only passed it to `profile_account`); updated the stale "gate not wired here" docstring.

## The composition (`api/deep/composition.py`)
- `build_deep_phase_handler(*, spec, gateway, committee_sources, …) -> DeepPhaseComposition` — defaults every concrete to its production binding; `pre_spend_gate` → `build_pre_spend_gate()` and `binding_classifier` → `production_binding_classifier()` are **never None** on the orchestrator (the required-collaborator enforcement). Returns a frozen bundle (`handler`, `orchestrator`, `scheduler`, `budget`, `pre_spend_gate`, `binding_classifier`) so tests can assert the wiring without private-attr reaches (they still do for `_pre_spend_gate`/`_binding_classifier` threading).
- `register_deep_phase_handler(…, register=register_phase_handler)` — builds + registers; `register` injectable so a test registers into a fresh `PhaseHandlerRegistry`.
- `build_high_tier_resolver(*, spec, session_factory, deep_tiers=None)` (D-B) — reads `ctx.params["tier_cutoffs"]` (campaign.py threads the `TierCutoffs` into every `PhaseContext`), re-derives the content-addressed `cutoff_version(cutoffs)`, and selects every account whose **live** `account.scoring.tier` claim names a **non-fallback band** at that version **for this ICP** (`value["icp_key"] == ctx.icp_key`). Scope `TenantScope.for_tenant(client_id)` (tier claims are tenant-private). Empty/band-less cutoffs → `()` (clean COMPLETED no-op).
- `build_account_axis_registry(...)` — registers **only** the account-axis aspect workers (`account_axis_workers(...)`). **Committee/contact are NOT graph aspects** (spec §M8A.6) — they run as the orchestrator's direct callables. The graph this backs is never `.run()` on the `run_one` path.
- Default `checkpointer_factory` yields an in-memory saver: `profile_account` owns its own durability and the `run_one` path never threads the checkpointer into a graph `run`, so it is unused on this path (correct + DB-free).

### Key architecture fact that de-risked everything
`profile_account` is **self-contained** (`account.py:241`): it builds its own account-axis workers via `default_account_worker_builder` and `asyncio.gather`s them — it does **not** use the M7 graph, the global `WorkerRegistry`, or the scheduler checkpointer. So the `AccountResearchGraph`/`AccountScheduler` exist only for the M8A.0 bounded-parallelism + per-entity-lock slot (graph unused on `run_one`). The essential deep wiring is: pack-loading + the three callables + `BudgetEngine` + `DbExactlyOnceSpend` + `DbAccountRunIO` + the gate + the binding adapter.

### M9 governance reuse (no re-implementation)
- **AC-4 binding** — reuses universe-A's `production_binding_classifier()` / `VerificationBindingClassifier` (the `classify_binding`→`BindingClassifier` adapter that stamps the authoritative born `identity_binding` before insert). The deep contact callable (`profile_contact`) is handed it.
- **AC-6 gate** — reuses `build_pre_spend_gate()` (`PreSpendGateImpl`, records one `gate_decision` per `check`).

## Tests (all green on isolated `clue_m8a6`)
`tests/api/deep/test_deep_composition.py` (7): handler-is-DEEP-PhaseHandler; gate+classifier threaded into the orchestrator (non-None); account-axis registry **excludes** committee/contact; register→dispatchable; empty set → COMPLETED no-op; **high-tier resolver** selects only the named-band/committed-version/this-ICP account (fallback, wrong-version, wrong-ICP all excluded); **end-to-end** `CampaignRun.advance()` dispatches DEEP and transitions **DEEP→VERIFICATION** (DB-free via `FakeCampaignRunStore` + empty resolver).
`tests/api/deep/test_gate_routing_ac6.py` (2): the deep **committee enumeration** + **contact facet** spends each record a `gate_decision` (kind=`enumeration` field_key NULL / kind=`field` keyed on the facet) — driving the exact callables the orchestrator invokes, with the composition's gate; fails if a path skips the gate.
`tests/api/deep/test_identity_binding_ac4.py` (3): a deep contact's born facet `identity_binding` == `classify_binding` verdict — STRONG (verified handle) / WEAK+unpromotable (same-name); the composition's classifier is the `VerificationBindingClassifier` adapter.

## Scope note on the end-to-end AC
The spec's "advance tier_checkpoint→DEEP→VERIFICATION **and DEEP produces (account,persona)-keyed claims for a high-tier account through the real wired stack**" is covered **in aggregate**, not by one mega-test: the state-machine **dispatch + transition** is `test_advance_dispatches_deep_and_transitions_to_verification`; per-account **claim production through the orchestrator on a real DB** is the M8A.4 `tests/durable/test_deep_orchestrator_db.py`; **committee/contact produce gated, identity-bound `(account,persona)`/contact claims** is AC-6 + AC-4. A single full handler→scheduler→orchestrator→account+committee+contact DB run (shared-conn budget store + resolved committee candidate + facet resolvers, with the orchestrator's own-session commits) was judged high-scaffolding/low-marginal-coverage and not added.

## Verification
`make check` green (lint + mypy 203 src + import-linter **11/0**: `api/deep` imports durable+profiling+verification, nothing-but-`api` imports `api/deep`). Migration db-smoke green on isolated `clue_m8a6`, single head `3df3b2f629fd`. Full pytest run: see closing entry. **Local commits only, never pushed.**

## Commits (this branch, local)
- `00c61b9` cherry-pick f2cd4ff (M9.1 Option-C gate seams)
- `fa9072d` alembic merge (M8A.0 + M9.1 heads → `3df3b2f629fd`)
- `3ab3d1d` land M8 composition root + thread the gate through the deep orchestrator
- `8cee95d` M8A.6 composition root + AC-6/AC-4 tests
- (+ the end-to-end advance test, folded into the test commit / next commit)

## Follow-ups / deferred (unchanged-by-M8A.6 unless noted)
- **CLAUDE.md M9.1 AC-6 / M9.4 AC-4 deferrals are now CLOSED for the deep path** — the gate is injected + routed (committee enumeration + role inference + contact facet) and `classify_binding` stamps the born facet binding. Update those backlog lines when the branch integrates.
- **M8A.4 deferreds still stand** (RUN-cap re-check mid-deep-phase lives at the M7.3 pre-gate; `per_contact_cap_cents` sub-envelope still unread; per-contact `IdempotencyConflict` fails the account; committee holds its conn across discovery I/O). See [[2026-06-23-m8a4-exactly-once-spend]].
- **The DEEP handler is campaign-scoped** (holds one `ICPSpec`): production builds + registers one per `(client, icp)` at run start. A multi-ICP process would need a per-run handler factory or a spec-per-run load inside `run(ctx)` — not built (single-ICP path is correct + sufficient for the AC).
- **`load_research_packs` is a deploy-time prerequisite** — call once on a connection before the first deep run (registers `account.resonance.*` / `contact.facet.*` / committee field defs).
