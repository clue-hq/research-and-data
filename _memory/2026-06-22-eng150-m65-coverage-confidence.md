# 2026-06-22 — ENG-150 / M6.5: Coverage-confidence estimator

## Goal
Produce the honest answer to "did we find all the accounts that fit?" — an estimated coverage
**band** ("~X–Y% found via these channels", never a false-precise point), plus the account-scope
channels **not yet searched**. A *trust* statement, deliberately separate from M6.1's *cost*-control
stopping rule (coverage only *reads* `stopping_reason`, never controls stopping). No claims written,
no new tables, estimation method swappable behind one seam. Branch `eng-133-m6.2` (M6 work continues
here); per-branch DB `clue_m6` (host PG :5432).

## Files (src/clue_research/discovery_scoring/coverage/) — new subpackage, mirrors tiering/
- `results.py` — `CoverageReport`, `CoverageBand` (low/point/high + `confidence` + `method` tag +
  `as_percent()`), `ChannelCurvePoint`, `ChannelObservation` (the pure estimator's per-channel
  input), `UnsearchedChannel`, `CoverageConfidence {none,low,moderate,high}`.
- `config.py` — `CoverageConfig` (policy-as-data, D7): band widths + per-`StoppingReason` penalties +
  `productive_yield_threshold` + `high_coverage_threshold` + **`coverage_ceiling` (`le=0.99`)**.
- `estimator.py` — pure deterministic `estimate_coverage(...)`:
  - `saturation_coverage(m)` — occupancy/species-accumulation model solving `(1-e^-x)/x = m` by
    bisection (100 steps, deterministic); coverage `= 1-e^-x`. Depends only on the aggregate marginal
    yield `m = distinct/captures`. Capped at `coverage_ceiling` (never asserts completeness).
  - `_band` — point = occupancy estimate; asymmetric band leans **down** (occupancy over-states under
    non-uniform channel sampling); confidence from `(stopping_reason, marginal_yield, point)`.
  - unsearched diff (universe − searched, geo-filtered), geo gaps, framing, recommendation.
- `report.py` — durable `coverage_report(conn, *, run_id, spec, ...)`: reads per-channel yield +
  `stopping_reason` + admitted/needs_review/rejected from `source_yield` (`disposition.kind='discovery'`,
  **latest row per `(run_id, source_key)` via `DISTINCT ON`** — replay-safe, never SUM), reads the
  account-scope universe from `source_manifest`, planned-order + geos from the ICP strategy. Returns
  `None` when a run has no discovery telemetry.

## Wiring
- `DiscoveryPhaseHandler` (phases.py): denormalises the run-level facts (`stopping_reason`, `admitted`,
  `needs_review`, `rejected`) onto each per-channel discovery `disposition` row so coverage is
  reconstructable by `run_id` alone (no M7 dependency).
- `TierCheckpointPhaseHandler` (M6.4): computes `coverage_report(discovery_run, spec)` and populates
  `CheckpointReview.coverage` + `payload["coverage"]` — backward-compatible (`None` when no telemetry).
- Exported `entity_scope_serves` from `clue_research.sources` (the owner of the "account OR both"
  scope rule); coverage's universe read reuses it (DRY).

## Key design calls
- **No new tables / no migration** (head unchanged `82831d3fa4c5`). Coverage is run-level metadata
  computed on read from existing telemetry; the report rides the checkpoint payload for M7 to persist
  (same M7-boundary discipline as M6.4's checkpoint record).
- **Saturation default depends only on aggregate `m`** (elegant, single-param, ties to M6.1's marginal
  yield). Method swappable behind `estimate_coverage` (D7). Honesty enforced structurally: band leans
  down + `coverage_ceiling` `le=0.99` (no config can render "100%").

## Adversarial audit (5-lens multi-agent workflow, 28 agents, refute pass) → 9 confirmed, all fixed
1. **[fixed] EXHAUSTED ≠ saturation.** `EXHAUSTED` (= "planned query set drained", NOT the
   marginal-yield rule) was grouped with `MARGINAL_YIELD` as "saturated", so an EXHAUSTED-with-high-yield
   run could never read LOW. Now `saturated = stopping_reason is MARGINAL_YIELD` only; added a
   "widen the query plan" recommendation for EXHAUSTED-while-productive. (findings 1, 2)
2. **[fixed] `distinct=0`/`records>0` mislabeled "no records returned".** That's maximal saturation
   (every record a re-find), not no-signal. NONE band now gates on `total_records<=0` only; a
   dedicated framing for the all-re-finds case (reachable via the re-discovery/import-hybrid seam). (4)
3. **[fixed] unseeded/partial registry → fabricated geo gaps.** A searched channel absent from the
   registry has UNKNOWN geo; geo gaps now require ≥1 registry-known searched channel (else `()`), so
   an empty registry no longer emits a spurious gap + contradictory "add a channel" advice. (5)
4. **[fixed] geo matching case-sensitive.** ICP `icp_filters` is free-form ('us') vs registry 'US' →
   `_norm_geo` (strip+casefold) on both sides for comparison; display keeps the ICP's casing. (6, 9)
5. **[fixed] `coverage_ceiling` allowed 1.0.** A config swap could make the band assert ~100%. Now
   `le=0.99` — a TYPE invariant, not just the default. (7)
6. **[fixed/doc] AC2 "ICP applicability".** Realised as the two axes `source_manifest` exposes
   (account `entity_scope` + `geo_coverage`); vertical/pack applicability deferred (safe direction —
   over-listing under-claims, never implies exhaustiveness). Documented in `_load_account_universe`. (3)
7. **[fixed/DRY] account-scope filter** duplicated the registry's scope rule → reuse
   `entity_scope_serves`. (8)

## Verification (all green, isolated clue_m6)
`make check`: ruff format+check, mypy (134 src files), import-linter (10/0). Alembic single head
`82831d3fa4c5` (M6.5 adds NO migration). **780 passed / 14–16 skipped** (was 751 at M6.4 → +29 M6.5
tests; +6 of those are audit-fix regressions). Skips are Redis-dependent lock tests (env), unrelated.
- `test_coverage.py` (24, no DB): band-not-point + determinism; saturation edges/monotonicity; ceiling
  never-completeness; budget-cap-high-yield=LOW vs marginal-exhausted=HIGH; unsearched=universe−searched;
  geo applicability + gaps + global-covers-all; found-nothing=NONE; curve/counts/clamp/aggregate; the 6
  audit-fix regressions (EXHAUSTED=LOW+widen; distinct0=max-saturation; zero-captures=NONE; geo-suppress;
  geo-case; no-config-100%).
- `test_coverage_report.py` (7, DB): reads telemetry+universe by run_id (account-scope only); None
  without telemetry; latest-row-per-source on replay; planned-channel curve order; geos-from-strategy;
  checkpoint payload includes coverage; checkpoint coverage None without telemetry.

## Follow-ups
- **Calibration is config-driven (D7).** The saturation method + confidence thresholds are starting
  points; tune once real campaign-size data exists. Method is swappable behind `estimate_coverage`.
- **Vertical/pack applicability** for the unsearched universe is deferred until `source_manifest`
  carries an industry/pack axis (currently account-scope + geo only).
- **M7 wiring:** `coverage_report` rides the checkpoint payload; when M7's run store lands, persist it
  to `campaign_phase_checkpoint.payload_json` and confirm the M13 observability read path.
- Next: M6 milestone (M6.1–M6.5) is complete; M7 wires durable suspend/resume + the phase/run store.
