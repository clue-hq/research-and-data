# M8 Track A — M8.1 Account Profiling → M8.2 resonance collectors — design plan

**Date:** 2026-06-22 · **Branch:** `m8/account-profiling` (off `m8/deep-profiling-v1` @ 5922a56 — the tiny seed).
**Scope:** the **account axis** of M8 (kickoff handoff [[2026-06-22-m8-kickoff-handoff]]): M8.1 (ENG-132, mode-M2 account
profiling, converge + target-lock) and M8.2 part-2 (ENG-136, `account.resonance.*` collectors as M8.1's resonance aspect).
The field-classes are already seeded ([[2026-06-22-m8-tiny-seed]]). **No migration** (no new tables — M8 adds only claim rows).

## The seam map (ground truth, read directly — not assumed)

M7 (`durable`) already owns the per-account orchestration; M8.1 supplies only the **worker bodies**. Confirmed from source:

- `core.execution.AspectWorker` — `aspect: str` + `async research(ctx: AspectContext) -> WorkerResult`. The contract M8.1 implements.
- `core.execution.AspectContext` — `entity_id, campaign_run_id, run_id, tier, aspect, field_keys, budget_envelope_cents, depth, params`. **Carries NO `tenant_id`/`client_id`/`icp`** — only `params={"recursion": {...}}` today (graph.py `_run_worker_subtree`). ← integration gap (below).
- `durable/workers.py::WorkerRegistry` — aspect→worker map; concrete workers register via `register_aspect_worker(worker)` at the **api root** (mirrors `sources.bind_resolver`). Graph `_run_one_worker` does `registry.get(ctx.aspect)`; an unregistered aspect → `WorkerResult(FAILED, detail={"reason":"no worker registered"})` (no crash).
- `durable/planning.py` — `compute_gap_fields` (reads `current_values`, returns non-FRESH deep fields) + `build_plan` (clusters gaps by **field-class**; `_aspect_key` = `field_class.value`, PACK→`field_namespace`). **The graph computes gaps + clusters; the worker is handed its `field_keys`.** M8 may NOT import `durable`.
- `durable/recursion.py::SpawnGuard` + `config.RecursionPolicy` — per-tier caps: `top`=depth2/8aspects/4facets, `high`=depth1/6/3, default=depth0/4/0; `eligible_classes=("account.resonance","contact.facet")`. `RecursionPolicy` lives in `config` (importable by profiling). Facet sub-workers requested via `result.detail["facet_requests"]=[{aspect,field_keys,estimated_cost_cents}]`.
- `sources.planner.plan_sources(conn, *, spec, entity, field, mode, tier_scope, entity_tier, budget_envelope, gateway, planner_model, config) -> OrderedSourcePlan`; `.tier_plan()` → ordered RUN source keys. Drive the waterfall via `field_def.model_copy(update={"tier_plan": plan.tier_plan()})`.
- `sources.waterfall.resolve_field(conn, entity, field_def, *, mode, run_id, tenant_id, budget_envelope, cost_so_far, ...) -> WaterfallResult`. **Writes claims itself** (`insert_claim`), stamps `research_mode`+`run_id`+`source_key`, stamps `reuse_scope` via `stamp_reuse` (**`tenant_id` REQUIRED for `account.resonance.*`** = TENANT_PRIVATE, else fail-loud), idempotent on `(entity,field,source,run)`, tier-4-absent → `NO_RESOLVER` empty (no crash). Returns `claim_refs` (ids).
- `core.verification.PreSpendGate.check(PreSpendRequest)->PreSpendDecision` + `assemble_target_lock(entity, field)->TargetLock`. `core.verification.TargetLock{entity_id, no_drift_instruction, canonical_domain, identifiers}` already exists. M8 may NOT import `verification` → codes against the `core` protocol, gate injected at api (None until then).
- `identity.get_account(conn, entity_id) -> AccountEntity|None` (+ `surviving_id`) — load the resolved account for target-lock. `core.AccountEntity{id, canonical_name, primary_domain, aliases, hq_geo, registry_ids, status, merged_into}`.
- `icp.spec.get_icp_version(conn, client_id, icp_key, icp_version) -> ICPSpec|None` — the planner's `spec`.
- `core.enums`: `ResearchMode.ACCOUNT_PROFILING` (=M2), `EntityType.ACCOUNT`, `WorkerStatus{OK,PARTIAL,FAILED,BUDGET_EXCEEDED}`, `FieldClass{CORE,ACCOUNT,ACCOUNT_RESONANCE,...,PACK}`.
- `core.handoff`: M8.1 writes claims; **M12** assembles them into `ProfileClaimView`/`AccountHandoff.account_profile_claims` (Output 2). M8.1's result = refs + coverage, NOT the handoff.
- Tests: `tests/db/conftest.run_async` + `rollback_conn(seed_core=...)` + `require_db` skip-gate (no `CLUE_DATABASE_URL` ⇒ skip, `make check` stays green); `tests/durable/conftest{FakeAccountRunStore,StubAspectWorker}`; fake resolvers via `sources.bind_resolver` + `clear_resolver_bindings` autouse.

## Module layout (new, under `src/clue_research/profiling/`)

- `context.py` — `RunContext` (typed reader of `AspectContext.params` → `client_id/icp_key/icp_version/tenant_id`, all optional) + loaders; the place that closes the params gap.
- `target_lock.py` — **pure** target-lock: `build_target_lock(AccountEntity) -> TargetLock`, `is_lockable(lock)`, `binds_to_entity(claim, lock) -> bool` (the validator that rejects a tier-4 claim whose `evidence_span` doesn't bind). Uses only `core` types.
- `aspect_worker.py` — `AspectProfilingWorker` (implements `core.AspectWorker`): the generic converge body. Per assigned gap field: PreSpendGate.check → target-lock guard → `plan_sources` (if spec) → waterfall `resolve_field` → post-fill target-lock + `claim_filter` validation → collect refs + coverage. DI: `session_factory, planner_config, gateway, planner_model, pre_spend_gate, mode, tier_scope, claim_filter`.
- `resonance.py` — M8.2: `ResonanceAspectWorker(AspectProfilingWorker)` with `aspect="account.resonance"` + the **sensitivity firewall** `claim_filter` (`_resonance_firewall_ok` rejects a resonance value carrying a named individual's special-category attribute → routes to `contact.facet.*`/M10); tier-3-review-then-tier-4 emphasis via `tier_scope`. `collect_resonance(...)` convenience.
- `account.py` — M8.1 account-level entrypoint `profile_account(conn, account_entity_id, *, spec, tier, run_id, tenant_id, budget_cap_cents, workers?, recursion_policy) -> AccountProfileResult`: gap-compute (claimstore `current_values` + spec deep fields) → cluster by `_aspect_key` → cap aspect count by `RecursionPolicy.caps_for(tier).max_aspect_workers` → run aspect workers **in parallel** (`asyncio.gather`, each its own session) → aggregate. `AccountProfileResult` + `AspectCoverage` result types.
- `__init__.py` / `README.md` — extend exports + status.

## Key design calls

1. **M8.1 = worker bodies; M7 = orchestration.** The worker fills `ctx.field_keys` (already the gap fields for its aspect) — it does NOT recompute gaps in the graph path. `profile_account` is M8's own account-level seam (the spec's named entrypoint, required by AC1–AC7) for direct/test/api-DEEP-phase invocation; it re-derives gaps+cluster from claimstore primitives + `config.RecursionPolicy` (NOT `durable`).
2. **Converge = single bounded pass.** The waterfall already converges per field (walk finite `tier_plan`, stop at first confident hit / exhausted / budget). The worker iterates its gap fields once, threads the budget envelope, re-reads `current_value` to classify filled-vs-empty for coverage. Terminates by construction (finite fields × finite tier_plan). Schema-complete / sources-exhausted / budget-cap are the three stop states (AC2).
3. **Target-lock = structural + pure validator.** (a) Pass the *resolved* `AccountEntity` (via `get_account`, following `surviving_id`); refuse to spend on an un-lockable entity (no domain/registry-id/name+geo) → field left empty-flagged (AC3 "queries entity-scoped"). (b) `binds_to_entity` is a pure validator shipped + unit-tested with a two-similar-companies fixture (AC3 "tier-4 claim not bound → rejected before write"). Tier-4 resolvers are absent until M11, so the validator is the gate M11's synthesis write-path will call; for now the worker applies it post-fill to exclude non-binding refs from its output + reports `target_lock_rejected`.
4. **Resonance firewall (M8.2 AC6) = pure `claim_filter`.** Same pattern: shipped + unit-tested; applied post-fill to exclude a resonance value carrying a named individual's special-category attribute. The field-def `validation` *declares* the firewall (seed); the collector *enforces* it.
5. **The params/tenant integration gap (flagged, like M9.1/M9.4 deferrals).** `AspectContext` carries no `tenant_id`/`client_id`/`icp`. The worker reads them from `ctx.params` (degrades gracefully + reports `PARTIAL` with a clear `detail.reason` if a tenant-private aspect lacks `tenant_id`, never crashes). **api-root follow-up:** the M7 graph must populate `AspectContext.params` (or extend `_GraphState`) with `{client_id, icp_key, icp_version, tenant_id}` when it builds the context — a one-line-ish durable change done at integration, NOT on this branch. `profile_account` takes them explicitly so all ACs are testable now.
6. **PreSpendGate + faithfulness judge wiring deferred to api** (M9.1 backlog): the worker accepts an optional injected `pre_spend_gate`; when None it proceeds (the global pre-spend policy already requires a strong key). The faithfulness judge runs as the downstream VERIFICATION phase, not inside M8.1.
7. **DRY follow-up (flagged):** `_aspect_key` (cluster rule) is a ~3-line mirror of `durable/planning._aspect_key` (can't import durable). Hoist `aspect_key_for(field)` to `core.field` later so durable + profiling share it (sibling of the `normalize_host`/`reference_time` consolidations).

## Tests (`tests/profiling/`)
- `test_target_lock.py` — pure: lockable/un-lockable; `binds_to_entity` two-similar-companies fixture (AC3).
- `test_resonance_firewall.py` — pure: named-individual special-category value rejected; clean account value passes (M8.2 AC6).
- `test_account_worker.py` (DB-gated) — `AspectProfilingWorker.research(ctx)` over fake resolvers: fills assigned fields, refs-not-blobs (no `value_json` in result), provenance (`research_mode=account_profiling`, non-null `source_tier`), idempotent re-run no double-write, budget-cap → BUDGET_EXCEEDED, sources-exhausted → empty-flagged + OK.
- `test_resonance_worker.py` (DB-gated) — resonance aspect writes tier-3-reachable claims with tenant stamping; tier-4-absent left empty (AC); new `account.resonance.<x>` row auto-picked-up (registry-driven, AC).
- `test_profile_account.py` (DB-gated) — AC1 (every deep field filled-or-flagged), AC2 (terminates: exhausted + low-budget), AC4 (aspects parallel + refs-only), AC6 (top-tier full aspect set vs lower-tier strictly-smaller, asserted vs `RecursionPolicy`), AC7 (idempotent re-run).
- `test_graph_integration.py` (DB-gated, imports `durable` — tests may) — register real workers into `WorkerRegistry`, run `AccountResearchGraph` (real `DbAccountRunStore`) → references_index populated, failing aspect isolated.
- `test_import_contracts` — covered by `make contracts` (profiling imports core/config/obs + claimstore/identity/icp/sources only).

## Status — DONE (implemented + verified; committed on `m8/account-profiling`, local only)

Shipped under `src/clue_research/profiling/`:
- `target_lock.py` — `build_target_lock` / `is_lockable` / `binds_to_entity` (pure; tier≥3 binding, same-name trap; ≤2-char geo tokens skipped).
- `context.py` — `RunContext.from_params` (reads client/icp/tenant from `AspectContext.params`; fail-soft) + `params_for_run` (producer).
- `aspect_worker.py` — `AspectProfilingWorker` (the converge body): per gap field → tenant guard → target-lock guard → `plan_sources` → `PreSpendGate.check` (injected) → `resolve_field` (sole composer) → post-fill target-lock + `claim_filter` validation → refs + `AspectCoverage`. `ProfilingFieldDisposition` enum = the converge stop states.
- `resonance.py` — `ResonanceAspectWorker` (firewall `claim_filter` + full tier band) + `resonance_firewall_ok` (named-individual special-category screen) + `collect_resonance`.
- `account.py` — `profile_account` (gap-compute via claimstore + cluster by `aspect_key_for` + cap aspects by `RecursionPolicy.caps_for(tier).max_aspect_workers` + parallel fan-out + aggregate) + `AccountProfileResult` + `account_axis_workers` (the api-root registration set) + `default_account_worker_builder`.

Tests (`tests/profiling/`, 47): pure (target_lock 12, firewall 6, context 8, imports 1) run in `make check`; DB-gated (account_worker 8, resonance_worker 5, profile_account 6, graph_integration 1) skip without `CLUE_DATABASE_URL`. **All 47 pass on the local `clue` DB.** `make check` green: lint (ruff) clean, mypy 178 files OK, contracts **11/0** (profiling imports no durable/verification — also belt-and-suspenders `test_imports.py`), 749 passed / 562 skipped no-DB.

### Design decisions worth remembering
- **M7 owns orchestration; M8.1 = worker bodies.** `durable.planning.compute_gap_fields`/`build_plan` already cluster by field-class → aspect keys are `core`/`account`/`account.resonance`/`<pack>`. So workers are **field-class-keyed** (NOT a single `account.profile` super-aspect — the understand-workflow synthesis got that wrong; `graph._dispatch`/`_aspect_key` confirm field-class clustering). `graph_integration` test proves the real worker runs in `AccountResearchGraph` via the `account` key.
- **The waterfall `resolve_field` is the only composer** — pass `tenant_id`, never re-`insert_claim`/`stamp_reuse`. Target-lock/firewall are POST-fill screens (exclude from refs; claim stays unpromotable in the store) + pure validators unit-tested directly (tier-4 synth write-path wiring is M11).

### Integration follow-ups (flagged, deferred — like M9.1/M9.4)
1. **`AspectContext.params` gap (the one real coordination point):** the M7 graph populates `params` with only `{"recursion":…}` today; the **api root** (or a small `durable` change) must add `{client_id, icp_key, icp_version, tenant_id}` so graph-driven workers can load the ICP spec (planner) + write tenant-private resonance. Until then a graph-driven resonance aspect fails-soft to `TENANT_REQUIRED` (empty/flagged). `profile_account` takes them explicitly (all ACs testable now). Use `profiling.params_for_run` on the producer side.
2. **api-root wiring:** `for w in account_axis_workers(pack_namespaces=…): register_aspect_worker(w)` + `load_deep_profiling_pack(conn)` + inject `PreSpendGate`/judge. Register the generic worker per enabled pack namespace (packs are open → can't enumerate in `profiling`).
3. **DRY:** `aspect_key_for` mirrors `durable.planning._aspect_key` (can't import durable) — hoist to `core.field` later (sibling of the `normalize_host`/`reference_time` consolidations).
4. **Cross-aspect budget:** `profile_account` passes `budget_cap_cents` as each aspect's envelope; a true shared cross-aspect budget is the M7.5 `BudgetEngine` (injected at the graph layer).
5. **Cosmetic:** several new-file docstrings were auto-wrapped to ≤100 and read slightly ragged (orphan words) — lint-clean; a `/simplify` reflow is a trivial follow-up.

### Adversarial audit + fixes (7-dimension review → per-finding verify; 10 confirmed / 16 refuted)
Fixed in this session (all re-verified green):
- **Target-lock substring false-binds (HIGH×3 + LOW) — the real anti-hallucination bug.** `binds_to_entity` used bare `in` substring matching → `acme.co` bound to `acme.co.uk`, `acme.com` to `notacme.com`, `"Acme"` to `"Acme Robotics"` (name-prefix trap), `ABC123` inside `ABC123456789`, geo `York` to `Yorktown`. Rewrote `target_lock.py` with `_host_present` (DNS-host boundary `(?<![a-z0-9.-])…(?![a-z0-9.-])`), `_token_present` (alnum-token boundary, for registry ids + geo), and `_name_is_complete` (word-bounded match NOT continued by a Capitalised word, using original-case text — closes the prefix trap a `\b` alone can't). +6 regression tests.
- **Expensive-modality tier gate (MEDIUM).** A top-deep account named `"top"` silently skipped VIDEO/AUDIO because the M4 planner default gates expensive modalities to `{"high"}` (band-name inconsistency: M6 tiering uses `high`/`medium`, M7 recursion uses `top`/`high`). Added `DEEP_PROFILING_PLANNER_CONFIG` (= M4 default but `gate_expensive_entity_tiers={"top","high"}`), used as the default for all M8 workers (medium stays gated — correct).
- **Pre-spend gate wrong tier (LOW).** Used `ordered_sources[0].tier` which may be a SKIP source; now uses the first `RUN` source's tier (matches what the waterfall consults).
- **Test coverage (MEDIUM×2 + LOW×2):** added stale-field-is-a-gap, profile_account-follows-merge-to-survivor, unregistered-field-flagged, fill-then-budget-cap.

**Refuted (16, correctly):** the `_validate_written` "fallback returns all refs" (unreachable — scope always matches), the parallel-session "hazard" (production uses separate transactions; only the shared-conn test pattern is constrained, by design), disposition accounting nuances, etc.

**Note on the shared-DB:** the full-suite-with-DB run had 5 failures in `claimstore`/`adapters`/`db` (NOT profiling) — environmental shared-`clue`-DB pollution + an `asyncio.run` event-loop error from running migration up/down tests + concurrent Conductor workspaces on `localhost:5432/clue`. My profiling suite passes on the same DB; changes are additive (git status: only new files + the `profiling/__init__.py` export extension). Authoritative gate = `make check` (no DB) green.

See [[2026-06-22-m8-kickoff-handoff]] §3, [[2026-06-21-m7-durable-execution]], [[2026-06-20-m46-source-planner]] + [[2026-06-20-m41-waterfall]].
