# M13.4 — observability surface (Track C, `m13.4/observability-surface` off `m13/base`)

**Status: complete + verified.** Read-only `ObservabilitySurface` (six Doc C §6/§5/§7 panels) shipped,
all acceptance criteria covered, full suite green. See the brief in
[[2026-06-26-m13-parallelisation]] (BRIEF — M13.4) and the M13.1 contract context in
[[2026-06-26-m131-review-surface-plan]].

## What shipped
- **`src/clue_research/review/observability.py`** — the `ObservabilitySurface` impl + panel
  projections (`CampaignProgress`/`PhaseProgress`, `CostBurnDown`, `PreRunEstimate`,
  `VerificationHealth`/`VerificationHealthCounts`, `RunPhaseState`) + the injected reader Protocols
  (`CampaignStateReader`, `CostBurnDownReader`, `PreRunEstimator`, `VerificationHealthReader`,
  `CoverageReportReader`) + their in-memory fakes + `observability_is_client_facing`. Read-only:
  the only write is the optional `cost_estimate` snapshot in `pre_run_estimate(conn=...)`.
- **`src/clue_research/api/observability_wiring.py`** — the api-root concretes over durable/M9/M6
  (`DurableCampaignStateReader`, `BudgetEngineBurnDownReader`, `BudgetCapsPreRunEstimator`,
  `ClaimScanVerificationHealthReader`, `CheckpointCoverageReportReader`) + `build_*` factories +
  `build_observability_surface` + static conformance asserts. Exported from `api/__init__.py`.
  Does **not** touch `api/composition.py`.
- **Migration `0f2f5df21591`** (hash id, `down_revision = c48ebe0a1e62`) — the `cost_estimate`
  append-only snapshot table (named non-neg CHECKs, `(campaign_run_id, computed_at DESC)` index,
  no new PG enum). db-smoke (up→base→up) green, single head.
- **Config (M13.4-owned additions to `config/`):** `observability_client_facing: bool = True`
  top-level scalar on `Config`/`ConfigOverlay` (the D7 exposure flag); `VerificationHealthThresholds`
  shape in `config/schema.py` + the field on `Config`/`ConfigOverlay`; both wired in `loader._merge`
  (the bool uses `is not None` so an explicit `False` overrides the default `True`).
- **`core/observability.py`** (the one sanctioned Wave-1 core add) — `CoverageReport` +
  `UnsearchedChannel` projection (Doc C §7 honesty surface). Exported from `core/__init__.py`.
- **`claimstore.claims_for_runs(conn, run_ids, *, scope, …)`** — additive campaign-scoped claim scan
  (sibling of `entities_with_field_claim`); keeps the verification-health SQL behind the claimstore
  seam. Exported from `claimstore/__init__.py`.
- **Tests:** `tests/review/` (`conftest.py` + `test_observability.py` 15 pure unit + 5 DB-gated
  `test_observability_db.py`) and `tests/api/test_observability_wiring.py` (9 DB-gated). +29 tests.

## Decisions / deviations (documented, per the M13.1 "document divergence" discipline)
1. **Coverage bridge = Option A (core projection).** No persisted coverage table exists (M6.5
   `coverage_report()` computes at query time), so Option B (SQL row) was infeasible. Put the minimal
   `CoverageReport` in `core/observability.py`. The api-root reader reads the **serialized
   `discovery_scoring.CoverageReport` already persisted on the M6.4 `tier_checkpoint` payload**
   (`payload['coverage']`, written by `discovery_scoring/phases.py:534`) and maps it — no
   discovery-run-id/spec resolution, no fresh recompute.
2. **Verification health — strong-binding = at-rest column scan ([M9.4×M13.4], locked).** The
   `ClaimScanVerificationHealthReader` materializes the campaign's claims (`claims_for_runs` over the
   account-run ids from `list_account_runs`) and feeds them to **`obs.metrics.record_verification_health`**
   (the at-rest `claim.identity_binding` scan) — never summed with the live per-classification view.
   Faithfulness pass = the tier-4-VERIFIED proxy that same emitter computes.
3. **Corroboration pass rate = `claim.verification_status` proxy** (VERIFIED over VERIFIED+FLAGGED),
   computed in the same scan. The authoritative mode-aware M9.2 `conflict_flag` rate is a documented
   **follow-up** (would need a verification-side reader; not required by the AC, which names
   corroboration a secondary "added M9.2 signal").
4. **Pre-run estimate uses the *pure* `durable.budget.project_spend`** (uniform-score model,
   confidence 0.5), NOT the durable `BudgetEngine.estimate` (which persists `campaign_run.estimated_cents`)
   — so a "read"/estimate never mutates the domain. `cost_burndown` still binds to the live
   `BudgetEngine.burn_down` (the authoritative `spent_cents` counter), the single shared materialization.
5. **`VerificationHealthThresholds` added to config** (beyond the brief's "just the exposure flag")
   — necessary for the AC "fixture drop raises the configured alert"; modelled as policy-as-data
   alongside `MergePolicy`/`FreshnessTtls`. Small, additive.

## Verification
- `ruff check`/`format`, `mypy` (245 files), `lint-imports` (**11/11 KEPT** — `review` imports no
  sibling worker; the api wiring is the exempt root) all clean for M13.4 files.
- `make db-smoke` green (up→base→up, single head `0f2f5df21591`).
- Full suite **1825 passed / 14 skipped / 0 failed** on a clean throwaway DB.
- Throwaway DB for checks: `clue-pg-m134` on **:5438** (the worktree's :5432 + :5436/:5437 are taken).

## Follow-ups / notes for integration
- **`review/README.md` is stale** ("may import only core/config/obs"). The executable import-linter
  allows `review` → `claimstore/identity/icp/sources` (which M13.4 uses). M13.1 owns the README fix
  (its Stage 2 plan) — left untouched here per the don't-touch rule.
- **Pre-existing alembic E501 debt on the base:** M13.1's `c48e…` migration has ~6 real >100-char
  lines that `ruff check .` flags (older migrations only *look* long via byte-counting unicode em-
  dashes — they pass). My new migration is clean. Not mine to fix (M13.1 file); flag for integration.
- **`api/composition.py` join (deferred to integration):** nothing registers/serves the surface yet
  (no HTTP router shipped — only the read API + wiring, per scope). The integration root constructs
  `build_observability_surface(budget=<the deep run's BudgetEngine>, …)` and gates exposure on
  `observability_is_client_facing(client_id)`.
- **Corroboration → conflict_flag** precise rate (follow-up #3 above) when an M9.2 reader is wanted.
- LangGraph `checkpoint_*` tables (durable graph `AsyncPostgresSaver`) pollute a *re-run* of
  `tests/db/test_db_migrations.py::test_no_domain_tables_at_m0_head` on a shared DB — pre-existing,
  unrelated to M13.4 (`cost_estimate` downgrades cleanly). A fresh DB / first run is green.
