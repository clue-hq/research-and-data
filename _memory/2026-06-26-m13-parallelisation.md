# M13 parallelisation plan (Wave-1 = 3 parallel tracks; Wave-2 = M13.3)

**Context:** M13.1 Stage 1 (the core contract-delta + review tables migration) is committed on
`m13.1/review-surface` (`dc2e3a6` + `e061d07`). Shared base for all forks: **`m13/base`** at that tip
(contracts + migration only, no M13.1 impl). Alembic head on the base: **`c48ebe0a1e62`**.
See [[2026-06-26-m131-review-surface-plan]].

## The 4 load-bearing decisions (FINAL, user 2026-06-26)
1. **Durable suspend = Option B** (REVIEW campaign phase + `AWAITING_INPUT`). *Done in Stage 1.*
2. **`config_revision` (M13.3) = full audited schema** (the spec's column list), NOT a thin link.
   **Settle the columns when M13.3 is built** (earlier code in front of you) → M13.3 is Wave-2.
3. **Backtest gate (M13.3) = Option (a)**: a tiny `BacktestGate` interface in `core/`; `review/`
   depends only on the interface; the concrete impl (calls `verification/` eval harness) is assembled
   + injected at the `api` root. The repo's established pattern (M9.4 binding classifier, M9.1
   pre-spend gate, M12.3 handoff-readiness reader all do interface-in-core / impl-at-api).
4. **Shared yield seam = (i) extend** `SourceYieldStat`/`get_source_yield` in place (add
   `freshness_score`, `cost_per_surviving_claim`, `downstream_signal`) — no rename collision, the
   equality test passes trivially (one helper both sides call). Caveat: the `downstream_signal` term
   joins M13.2 dispositions; pre-materialize *only that term* later if the join gets expensive.
   **Sub-decision ([M9.4×M13.4]):** M13.4's verification-health "strong identity-binding share" uses
   the **at-rest column scan** (`obs.metrics.record_verification_health`) as authoritative — the
   durable, born-correct, policy-stable truth; the live per-classification view
   (`verification.identity_binding` counters) is reserved for internal regression-alerting. **Must
   not be summed.** Decide at the start of M13.4.

## Why the Wave-1 freeze is minimal
The only cross-issue seam the parallel tracks need is **`core.ReviewDispositionEmitter`** (M13.1→M13.2)
— already frozen in Stage 1. Everything else each Wave-1 issue builds is self-owned in its package
subtree + its own migration + its own `api/*_wiring.py`. So **no extra core freeze is required to
fork Wave-1.** (M13.3's contracts — `config_revision`, `BacktestGate`, `LearningLoop`, the
`source_yield` extension — are settled at Wave-2, per decision 2.)

## Wave-1 — 3 parallel tracks (fork off `m13/base`)
- **Track A — M13.1 impl** (this workspace, `m13.1/review-surface`): Stages 2-6 (review/ projection +
  surface + repo; api/review phase handler + wiring; handoff gate; tests; docs).
- **Track B — M13.2 disposition capture** (`m13.2/disposition-capture`).
- **Track C — M13.4 observability surface** (`m13.4/observability-surface`).

## Wave-2 — M13.3 (after M13.2 merges)
Forks off a base that already has M13.2's `labeled_dataset` + M13.4's `source_yield` extension. Settle
`config_revision` (full schema), the `core.BacktestGate` interface (impl injected at api), the
`LearningLoop` contract, and extend `source_yield`. Lands config-only (engines read versioned config).

## Coordination rules (so the worktrees don't collide)
- **File ownership.** Each issue owns its own NEW module files. Shared edit points: `review/__init__.py`
  (A + B both export → a small union merge at integration, like the M10/M11/M12 merge); `core/` is
  **frozen** after Stage 1 (the only sanctioned Wave-1 core add is M13.4's optional small coverage
  projection — additive, no other track touches it).
- **Migrations.** Each new migration uses an Alembic **hash id**, `down_revision = c48ebe0a1e62`. If
  >1 issue adds a migration, one `alembic merge` at integration (never hand-renumber). Gate:
  `alembic heads` == 1 + `make db-smoke` on a clean throwaway DB.
- **The api composition root is the single join** (done at integration, last): wires M13.2's concrete
  emitter into M13.1's surface, M13.4's annotation/coverage readers, the resume hook, the
  M10.5→DispositionStore tombstone cascade. Nothing imports `api`.
- **Integration branch:** `integration/m13` off `m13/base`; merge A/B/C (then D), one alembic merge,
  full `make check` + `db-smoke`.
- **DB for checks:** worktree's own `make db-up` (:5432) is taken; use an isolated throwaway per
  worktree (M13.1 used `clue-pg-m131` :5436). Each worktree spins its own (unique name/port).

---

## BRIEF — M13.2 disposition capture (Track B, `m13.2/disposition-capture` off `m13/base`)
**Spec:** `docs/specs/M13-review-feedback-observability.md §M13.2`. **Priority 2 (High).**
**Goal:** normalize every review action (M13.1) AND every downstream sales outcome into one
append-only, idempotent `disposition` record + a provenance snapshot; expose the single
`labeled_dataset` read view M13.3 consumes.
**Owns:** `review/disposition.py` (the `FeedbackDisposition` record + the `DispositionType`/
`DispositionActor`/`DispositionOrigin` enums — in `review/`, NOT core), `review/disposition_store.py`
(the `DispositionStore` impl + the concrete `ReviewDispositionEmitter`), `review/labeled_dataset.py`;
a migration (hash id off `c48ebe0a1e62`) for `disposition` + `disposition_provenance` + the
`labeled_dataset` SQL view; `api/disposition_wiring.py` (build/register the store + the emitter).
**Binds to (frozen):** `core.ReviewDispositionEmitter` (implement it — M13.1's `apply_action` calls
it), `core.ReviewActionOutcome` (the emitter input); M12.2 provenance via `claimstore.claims_by_ids`
(`ProvenanceRef` has no source_key/field_key → re-resolve claim rows for `source_key`/`field_key`);
`identity.resolve_many`/`surviving_id` (key every disposition on a resolved `EntityId`, reject
unresolvable to an error queue — never best-guess); M10.5 erasure (provide
`DispositionStore.tombstone_for_contact`; the cascade is wired at the api root since `compliance`
can't import `review`).
**Decisions/gotchas:** name the record `FeedbackDisposition` (NOT `Disposition` — collides with
`identity.Disposition`). `natural_key` for idempotent capture: review-origin embeds `review_round`;
downstream-origin needs an adapter-supplied external dedup token. `labeled_dataset(...)` scopes by
`(icp_spec_version + icp_key + client_id)` (version restarts per `icp_key`, D5). Tombstone STAMPS
`tombstoned_at` (audited, not hard delete); `labeled_dataset` excludes stamped rows. CRM is a READ
source only — outcomes enter via `ingest_downstream` into Postgres, never write-through.
**Don't touch:** `core/` (frozen), M13.1's `review/surface.py`/`projection.py`/`repository.py`,
M13.4's files, the api `composition.py` (use your own `api/disposition_wiring.py`).
**Acceptance:** spec §M13.2 AC (one disposition per review action, idempotent on natural_key;
ingest_downstream resolves-or-rejects; provenance snapshot stable; labeled_dataset reproducible +
append-only; tombstone removes from dataset; no CRM in write path).

## BRIEF — M13.4 observability surface (Track C, `m13.4/observability-surface` off `m13/base`)
**Spec:** `docs/specs/M13-review-feedback-observability.md §M13.4`. Fully independent (read-only).
**Goal:** an `ObservabilitySurface` read API — phase progress, cost burn-down vs estimate vs cap,
pre-run estimate, per-source yield, verification health, coverage confidence — behind a per-client
exposure flag.
**Owns:** `review/observability.py` (the `ObservabilitySurface` impl + its projection types — these
are read-only, M13.4-owned, can live in `review/`), `api/observability_wiring.py`; a migration (hash
id off `c48ebe0a1e62`) for `cost_estimate`; the per-client **exposure flag** added to
`config/models.py` `Config` + `ConfigOverlay` (default client-facing).
**Binds to (frozen):** `core.BudgetEngine` (`burn_down`/`estimate` — injected), `sources.source_yield.
get_source_yield` (read AS-IS — do NOT extend it; M13.3 extends it in Wave-2; you just call the one
helper), `obs.metrics.*` (the at-rest counters), the campaign-run phase state (read via an injected
reader), coverage (M6.5).
**Decisions/gotchas:** verification-health "strong identity-binding share" = the **at-rest column
scan** `obs.metrics.record_verification_health`, NOT the live per-classification view — **never sum
them** (the [M9.4×M13.4] resolution). Coverage bridge: `review` can't import `discovery_scoring` —
promote a small `CoverageReport` projection into `core/` (additive; the one sanctioned Wave-1 core
add) OR read a persisted coverage row via SQL; pick at start. All panels are read projections — the
surface writes NOTHING to the domain (assert no domain mutation on any read call). Exposure flag is a
per-client config value, not two code paths.
**Don't touch:** `core/` (except the one additive coverage projection), `sources/source_yield.py`
(M13.3 extends it), M13.1/M13.2 files, the api `composition.py`.
**Acceptance:** spec §M13.4 AC (campaign_progress matches state machine; cost_burndown reconciles;
pre_run_estimate recomputes; verification_health raises the alert on a fixture drop; coverage_confidence
returns a % + a non-empty unsearched-channel list, never "100%/complete"; source_yield equals what
M13.3 consumes; exposure flag toggles visibility; no domain writes).
