# M13.3 — Source-yield + scoring learning loop (design + plan)

**Date:** 2026-06-27. **Branch:** `m13.3/learning-loop` off `integration/m13` (head `f9483ab9aafa`). **DB:** throwaway `clue-pg-m133` :5443.

## What M13.3 is
The feedback loop: reweight per-(ICP, field-class, source) **source profiles** (M4.6) and the fit/intent **scoring rubric** (M3.4) from measured outcomes (verification survival + dispositions) — as **versioned config revisions, never in-place mutation**, human-gated, bounded step, backtest-guarded. The loop is a *config writer*; the engine (M4 planner, M6 scorer) is unaware it exists.

## The three locked decisions — concrete realization
- **D4 (source_yield) — extend in place, read-only.** The `source_yield` table already has `freshness_seconds` + `disposition` columns; `get_source_yield` just didn't read them. Extend `SourceYieldStat` (`sources/source_yield.py`): add `avg_freshness_seconds: float|None` (SQL `AVG(freshness_seconds)`), and `@property cost_per_surviving_claim` (= `cost_cents/claims_verified`) + `@property freshness_score` (normalized recency). **No migration.** Additive → M13.4 (reads as-is) unaffected. `downstream_signal` is NOT a `SourceYieldStat` field — the **loop** computes it in `review/` (`get_source_yield` × `read_labeled_dataset`, attributing each disposition outcome to its frozen `contributing_source_keys`), so `sources/` stays disposition-unaware.
- **D2 (config_revision) — full audited ledger; promote writes the existing stores.** New `config_revision` table (governance ledger). `promote()` writes the real versioned store — rubric → `icp.create_icp_spec(..., scoring_rubric=payload, activate=True, parent_version=...)`; source-profile → `icp.register_source_profile_override(...)` — then stamps the row `promoted` + `applied_version`. The engine reads the existing stores (`get_active_rubric` / `serve_source_profile`), never `config_revision`. Reproducibility holds for free: in-flight runs read their pinned `icp_spec_version` / override `version`; new runs pick up the promoted version.
- **D3 (backtest) — core.BacktestGate interface, concrete at api.** `review` may NOT import `verification`/`discovery_scoring`/`evals`, so `BacktestGate` (+ `BacktestVerdict`) live in `core/learning.py`; the concrete impl at `api/` reads `labeled_dataset`, re-scores each labeled account under baseline vs proposed rubric with the pure `icp.rubric.score`, and folds a discrimination metric (mean fit/intent of accepted − rejected) into M9.6's `check_regressions`/`Regression`/`scoreboard`. **Gap:** the M9.6 golden set is verification-only (no scoring-accuracy fixtures); the labeled dataset IS the scoring golden set (human disposition = ground truth), so no new golden table for V1.

## Files
- `core/enums.py`: + `ConfigRevisionTarget(source_profile|scoring_rubric)`, `ConfigRevisionStatus(proposed|promoted|rejected)`, `PromotionMode(auto|human)`. Mirrored as DB enums + parity tests.
- `core/learning.py` (new): `BacktestGate` Protocol + `BacktestVerdict` (the only cross-package seam; injected at api). Re-exports `evals.Regression` shape or restates it.
- `core/__init__.py`: export.
- migration (hash id off `f9483ab9aafa`): `config_revision` table + 2 enums. (No source_yield migration.)
- `sources/source_yield.py`: extend `SourceYieldStat` + `get_source_yield` (D4).
- `review/yield_metrics.py` (new): `SourceYield`/`YieldMetrics` value types + `compute_yield(conn,...)`.
- `review/reweight.py` (new): deterministic, bounded source-profile + scoring-rubric reweighters (+ explanation).
- `review/config_revision.py` (new): `ConfigRevision`/`SourceProfileRevision`/`ScoringRubricRevision` types + the ledger repo (record/load/promote).
- `review/learning.py` (new): `LearningLoopImpl` (compute_yield / propose_source_profile_revision / propose_scoring_rubric_revision / promote) holding the injected `BacktestGate`.
- `review/__init__.py`: export.
- `api/backtest_wiring.py` (new): the concrete `BacktestGate` (labeled_dataset re-score + check_regressions).
- `api/learning_wiring.py` (new): build the `LearningLoopImpl` with the gate injected.
- `api/__init__.py`: export.
- tests: enum parity; source_yield extension; compute_yield (DB); reweighters (unit, bounded/explainable); config_revision + promote + reproducibility (DB); backtest gate blocks a regressing rubric (DB).

## Reweighting (deterministic, bounded, explainable)
- **Source-profile:** per source, continuous merit = `prior(weight) × precision × (1+downstream_signal) / (1+cost_norm)`; map to ordinal HIGH/MEDIUM/LOW but **cap the move to ±1 level/run** (bounded step). Ordinal weights have a floor (LOW), so a 0-precision source down-weights but never zeroes (AC). Explanation = per-source {old, new, merit, precision, downstream_signal, cost}.
- **Scoring-rubric:** per fit/intent signal, nudge the weight toward signals whose value discriminates accepted-vs-rejected in the labeled set; **cap the per-weight delta** (bounded). Via `icp.reweighted(rubric, fit_weights, intent_weights, feedback_basis=explanation)`. Explanation = per-weight {field_key, old, new, delta, accepted_mean, rejected_mean, n}.

## ACs to hit
compute_yield reconciles vs hand-checked counts; reweight emits a NEW versioned revision (parent linked), prior version unchanged + readable, pre-promotion run reads its original (reproducibility); rubric reweight is decomposed/explainable; promotion gated (out-of-bounds → human; in-bounds → auto); backtest blocks a golden-set-regressing rubric; bounded step (a rejected-only source down-weights but isn't zeroed).

## Implementation notes (as built)
- **Backtest metric = ranking accuracy (AUC).** The M9.6 golden set has NO scoring-accuracy fixtures, so the labeled dataset IS the scoring golden set (disposition = ground truth). `api/backtest_wiring.py` re-scores each labeled account under baseline vs proposed via `icp.score_entity`, computes per-dimension AUC (Mann-Whitney; ties=0.5), encodes AUC as a MechanismMetric recall (`detected=round(AUC*10_000)`), and runs M9.6 `check_regressions`. Effective resolution 1/10_000; inconclusive (no accepted+rejected split) → `passed=True` (fail-open — a separate bounds/human gate still governs).
- **Source reweighter uses precision + downstream** (not the full `prior×precision×(1+ds)/(1+cost)` merit in the design note above); cost/freshness are computed + surfaced in the per-source explanation rationale, not (yet) in the up/down decision. Bounded ±1 ordinal level, LOW floor.
- **`ICPCreatedFrom.FEEDBACK_REWEIGHT`** added (core enum + `ALTER TYPE icp_created_from ADD VALUE` in the migration) so a promoted rubric reweight stamps an accurate, queryable provenance on its new icp_spec version. Note: editing an already-applied migration means **a fresh DB is required** to pick up the ALTER (caught in dev).

## Critical review (2 adversarial agents) + fixes applied
Both reviews found the headline machinery sound (bounded-step, rubric discrimination + explainability, compute_yield attribution + D5 scoping, ledger idempotency, AUC backtest genuinely blocks, layering, locked decisions). **Three real bugs the green build hid — all FIXED in `learning.py`/`config_revision.py`:**
1. **Stale rubric proposal reverted intervening non-rubric ICP edits.** `_apply_rubric` carried forward the *parent* version's slots while archiving the current active. **Fix:** refuse a stale proposal (`get_active_icp().version != rev.icp_spec_version → PromotionBlocked`); carry the **active** slots forward. Reproducibility unchanged.
2. **Non-atomic promote** (concurrent/double promote double-applied, orphaning a store version; `mark_promoted` return ignored). **Fix:** `get_config_revision(..., for_update=True)` (row lock) + raise `PromotionBlocked` if `mark_promoted` returns False.
3. **`mark_rejected` wrote the rejecter into `promoted_by`** (wrong audit column). **Fix:** set only `status='rejected'`; dropped the `rejected_by` param.
**Test gap fixed:** added `test_propose_and_promote_source_profile_is_versioned_and_bounded` (the source-profile propose→promote→reproducibility path + the explanation jsonb round-trip), which had NO coverage.

## Remaining minor follow-ups (documented, non-blocking)
- Source reweighter ignores cost/freshness in the merit *decision* (only in the explanation) — fold them into `_bounded_level` if a cost-aware reweight is wanted.
- `propose_*` accumulates open proposals (a 2nd propose chains a new child off the 1st) — fine for an audit ledger; add propose-idempotency-on-identical-payload if churn matters.
- Source-profile target has NO backtest/human gate (always within_bounds) — intended (bounded ±1, no golden scorer), but it auto-promotes ungated.
- `_apply_source_profile`'s `MAX(version)+1` is read-then-write — fails closed under concurrency (unique-slot collision), not corruption; single-writer-promote assumption holds for V1.

## Verification (DONE)
- ruff format+check clean; mypy clean (263 src files); import-linter **11/11 KEPT**.
- Full suite **exit 0** (1888 collected, 0 failed) on a pristine DB; db-smoke up→base→up single head `15b6b816abe4`.
- New tests: `tests/review/test_learning_unit.py` (9, reweighters/labels/source_yield properties, no DB) + `tests/review/test_learning_db.py` (8, DB: enum parity, compute_yield, rubric+source-profile propose/promote/reproducibility, human gate, idempotency, backtest blocks/passes).

## Next
M13 is complete (M13.1–M13.4). Integrate `m13.3/learning-loop` into `integration/m13` (one `alembic merge` not needed — single linear migration off `f9483ab9aafa`), wire `register_reviewed_phase_handler` + `build_learning_loop` + the DSAR cascade at a production app-assembly when one exists, then the broader M9/M10 backlog deferrals.
