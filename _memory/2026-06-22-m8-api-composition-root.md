# M8 api composition root — pack loading + worker registration + M9 governance injection

**Date:** 2026-06-22 · **Branch:** `m8/integrate-track-b` (local; **not pushed**) · builds on [[2026-06-22-m8-trackb-integration]] (the Track A+B merge this depends on).
The "one coordination point" the kickoff calls out — done once, after both axes merged. First real code in the M0.1 `api/` placeholder.

## What landed (`src/clue_research/api/composition.py`, re-exported from `api/__init__.py`)
`api` is the import-linter-exempt seam (NOT in the independence `modules` list; Rule 5 = nothing imports `api`), so it may import `durable`/`verification`/`profiling`/`sources`/`gateway`/`claimstore`/`identity`/`icp`/`core`. Verified `make contracts` 11/0.

- **`load_research_packs(conn)`** — core + deep-profiling + committee packs + `seed_source_manifests` (idempotent).
- **`build_profiling_workers(...)` / `build_worker_registry(...)`** — constructs both axes and registers them into the M7 `WorkerRegistry` (keyed on `worker.aspect`): account axis via `account_axis_workers(...)` (aspects `core`/`account`/`account.resonance` + packs, `pre_spend_gate` threaded in), `CommitteeAspectWorker` (aspect `committee`; `sources`+`gateway` injected), `ContactProfileAspectWorker` (aspect `contact.facet`; the binding adapter injected). Disjoint aspect keys → no collision. `build_research_graph(...)` wraps `AccountResearchGraph(workers=registry, recursion_policy=...)`.
- **`VerificationBindingClassifier` / `production_binding_classifier()`** — the **M9.4×M8.4 stamp**. Adapts `verification.classify_binding` (takes a built `Claim`) to M8.4's pre-claim `BindingClassifier.classify(BindingInput) -> IdentityBinding`. Adapter builds a minimal `_BindingClaimView` (id/entity_id/source_url/evidence_span — the ONLY fields `classify_binding` reads, via `handle_matches`/`count_identifier_matches`; the returned `Binding`'s id keys are discarded) and returns `.strength`. So a born `contact.facet.*` `identity_binding` is the authoritative M9 verdict, not the M8 default placeholder.
- **`build_pre_spend_gate(...)`** — `PreSpendGateImpl` (records a `gate_decision` per `check`); injected into the account axis (the **M9.1 routing**).

## Key seam facts (verified against code)
- Account-axis gate seam **already exists** (`aspect_worker.py:334` `_fill_field` calls `gate.check`) → **pure injection**. BUT it fires **only on the planner path** (`plan is not None`), and `plan` is computed **only when `spec is not None`** (line 315). The worker loads its spec from `ctx.params` (`client_id`/`icp_key`/`icp_version`) via `get_icp_version` (`aspect_worker.py:200-217`). So the M9.1 E2E needs a DB ICP whose pack `source_profile` authorizes the source.
- `classify_binding` is sync/DB-free; `BindingInput` (frozen pydantic) carries contact/evidence_span/source_url/source_key/manifest_prior/account_name/account_aliases.
- `WorkerRegistry` (`durable`) keys on `worker.aspect`; missing aspect → `WorkerResult(FAILED, reason="no worker registered")`, not a crash.

## Tests (`tests/api/`, 8, all green on the per-workspace DB :55100; conftest re-exports the profiling fixtures/doubles)
- `test_composition.py` — adapter is a structural `BindingClassifier`; both axes register under the 5 expected aspects; `load_research_packs` registers every class + manifests; the injected `classify_binding` **agrees with `DefaultBindingClassifier`** on the verified-handle (STRONG) / same-name (WEAK) fixtures.
- `test_governance_integration.py` — **M9.4**: a born facet `identity_binding` **equals `classify_binding(written, contact, …).strength`** (STRONG on verified-handle, WEAK + unpromotable on same-name). **M9.1 AC6**: the gate is injected into every account-axis worker, AND a true E2E (ICP pack profile authorizes a tier-2 source → worker spends) records `gate_decision = ('account.gate_probe','pass',2)` **before** the claim is written.

## Verification
`make check` green: **807 passed / 609 skipped**, mypy clean (196 files), **contracts 11 kept / 0 broken**. api+profiling DB suite **152/152** on :55100. Single alembic head; no migrations.

## STILL DEFERRED (worker-internal / M7 changes — NOT pure composition; documented in `api/composition.py` docstring)
1. **Committee/contact pre-spend-gate** — those workers have **no gate seam** (grep-confirmed). Wiring needs constructor params + `.check()` call sites in `committee/worker.py` (before role-inference LLM / `find_candidates`) and `contact/fill.py` (before `resolver.resolve`). The contact path is cleanly `(entity=contact, field=facet, tier=source)`-keyed; **committee people-enumeration is NOT naturally field-keyed → a genuine design choice** (what entity/field/tier to gate on) the milestone owner should make. Left out deliberately.
2. **Graph param-threading** — `AccountResearchGraph` only writes `ctx.params={"recursion":…}`; it does **not** thread campaign coordinates (`client_id`/`icp_key`/`icp_version`/`account_entity_id`) into the graph-built `AspectContext.params`. So committee/contact workers (which read those params) run today via their **direct callables** (`discover_committee`/`profile_contact`, which populate everything explicitly), not in-graph. Threading needs a small additive `durable.graph.run(...)` change. (Account axis is unaffected — it loads the spec from params, which the direct `profile_account` route populates.)
3. **Campaign-run orchestration** (account → committee → per-contact) — the larger unbuilt state-machine piece.
4. **Latent eval-fixture gap** (golden refs unregistered keys / singular `account.strategic_move`) — reconcile at M9.6 integration.
5. DRY follow-ups from [[2026-06-22-m8-trackb-integration]] (`aspect_key_for`→core, `SessionFactory` consolidation, `RunContext` in committee/contact, `normalize_host`/`_first_json_object`).

## Not done (policy)
Not pushed, no PR (local-only; user promotes `m8/integrate-track-b`). Linear ENG-132/136/142/149 not touched this session.
