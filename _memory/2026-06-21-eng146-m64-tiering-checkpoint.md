# 2026-06-21 — ENG-146 / M6.4: Tiering + human checkpoint (interrupt-based)

## Goal
Convert M6.3 Pass-A scores into **tier assignments** and run the **durable human checkpoint** — the
`interrupt()`-style gate where the client reviews provisional scores + a pre-run cost estimate and
adjusts cutoffs / raises budget / approves before any Pass-B spend. Tiering is a *pure policy over
the stored score object*, not an agent. Branch `eng-133-m6.2` (M6 work continues here); per-branch DB
`clue_m6` (host PG :5432, isolated from the parallel worktrees' clue_m5/clue_m7/clue_m9/shared clue).

## Files (src/clue_research/discovery_scoring/tiering/) — new subpackage, mirrors scoring/
- `config.py` — `TieringConfig.pass_b_bands_cents: {tier -> cents}` (per-tier Pass-B cost band; D7,
  policy-as-data; default {high:500, medium:200}; unmapped tier = not deep-eligible) + `band_cents()`.
- `results.py` — `AccountScoreView` (pure tiering input: fit/intent + fit/intent_claim_id +
  evidence_claim_ids), `AccountTierView` (+tier; `from_view`), `TierAssignment` (persisted decision),
  `CheckpointReview` (the durable review payload), `CheckpointDecision` (+`from_params`, defensive),
  `CheckpointAction {APPROVE,PAUSE}`, `CheckpointStatus {AWAITING,RESUMED}`,
  `CHECKPOINT_DECISION_PARAM="checkpoint_decision"`.
- `engine.py`:
  - `cutoff_version(cutoffs)` — content hash `"v-"+sha256(canonical_json)[:16]` → the
    `(account, cutoff_version)` idempotency key (stable for same cutoffs, distinct on any change).
  - `assign_tiers(views, cutoffs)` — pure deterministic `{account_id -> tier}` over M3.4 `assign_tier`.
  - `tier_distribution(assignments, cutoffs)` — count per tier, lists every named tier incl 0s.
  - `estimate_cost(distribution, config) -> core.Estimate` — (accounts/tier × band); unmapped tier
    = 0 spend / 0 projected-deep; `cost_per_account_cents` = blended per-deep.
  - `load_score_views(conn, *, scoring_run, client_id)` — read the M6.3 score object back (live
    FIT/INTENT claims for the scoring run; survivor-resolved + deduped; tenant-scoped → D5-safe).
  - `persist_tier(conn, *, view, tier, cutoff_version, run_id, client_id, icp_key, icp_version)` —
    write/replay/supersede one tier claim, ICP-scoped (mirrors M6.3 `_write_score_object`).
  - `TIER_FIELD = "account.scoring.tier"`.
- `phases.py` — `TierCheckpointPhaseHandler` (phase=TIER_CHECKPOINT), **re-entrant**:
  load spec+rubric (FAILED if missing, parity with scoring) → resolve cutoffs (decision override else
  rubric.tier_cutoffs) → `load_score_views` → `assign_tiers`/`tier_distribution`/`estimate_cost` →
  `effective_cap` (decision raise/lower over ctx) → `over_cap`. **approve & within cap** → persist
  per-account tier (per-account savepoint isolation, commit outside try) → `PhaseResult(COMPLETED)`
  (advance to deep). **else** (no/pause action, or over-cap approve) → `PhaseResult(PAUSED)` + review
  payload. `_tier_checkpoint_run_id(ctx, cversion)` = uuid5(campaign_run, icp_key, icp_version,
  cversion) (distinct ns from discovery/scoring).

## Key design calls
- **Reserved field, not a new table.** Per-account tier = a tenant-private claim on the new reserved
  `account.scoring.tier` (added to `claimstore/packs.py` CORE_PACK, same `account.scoring.*` family as
  fit/intent so `stamp_reuse` classifies it tenant-private via the `account.scoring.` prefix and the
  fail-closed write boundary holds). `extraction_method=HUMAN` (the human checkpoint decision), tier-1,
  no tier_plan. **No alembic migration** (field rows are runtime registry data; head unchanged
  `82831d3fa4c5`).
- **M7 boundary respected (M7 not built).** The run-level checkpoint record (proposed cutoffs, tier
  distribution, cost estimate, status, decision) is returned in `PhaseResult.payload` for M7's
  `campaign_phase_checkpoint.payload_json` to persist ("co-owned with M7's phase store" — the spec's
  words). The **per-account** decision IS durably persisted by M6.4 (the tier claim). The resume
  decision arrives via `ctx.params["checkpoint_decision"]` (the secure-input seam). Same deferral
  discipline M6.1–6.3 used for M7-owned run-level state.
- **Idempotency `(campaign_run, 'tier_checkpoint')`.** Review is deterministic in (stored scores ×
  cutoffs × config) → crash re-entry re-presents identical state. Tier write idempotent on the
  cutoff-derived `run_id` → resume applies at most once; a cutoff change → new run → supersedes prior
  tier (one live winner per ICP, append-only history kept).
- **Persist only on approve-within-cap.** pause / no-action / over-cap never writes tiers.

## Verification (all green, on isolated clue_m6)
`make check`: ruff format+check, mypy (129 src files), import-linter (10/0 — tiering/claim_writes
import only core/claimstore/identity/icp; no sibling-worker edge). Alembic single head `82831d3fa4c5`
(M6.4 adds NO migration). **751 passed / 14 skipped** (was 723/14 at M6.3 → +28 M6.4 tests, no
regression). DB: isolated `clue_m6` (CLUE_DATABASE_URL).
- `test_tiering.py` (16): pure assign_tiers determinism + cutoff re-tier; distribution; estimate
  (band×count, unmapped=not-deep, override); cutoff_version stable/distinct; decision parsing
  (action/cap/cutoffs/malformed + non-finite-cap degrade); DB persist_tier idempotent+ICP-supersede,
  D5 two-ICP no-cross-supersede, tenant-private+isolation, load_score_views unscored/merge-collapse/
  loser-skip.
- `test_tier_checkpoint_phase.py` (12): suspend+review payload (per-account fit/intent+evidence,
  exact cutoffs+version, distribution, estimate); cutoff-adjust re-tiers+re-estimates NO re-spend;
  approve→COMPLETED+persists (tenant-private, cutoff_version, errors==0); approve-with-adjusted-cutoffs
  supersedes prior; pause→PAUSED no-persist; over-cap→PAUSED graceful then raised-cap→COMPLETED +
  ==-boundary; non-finite-cap→no-crash; re-entry idempotent; deterministic review; no-rubric→FAILED.

## Adversarial audit (5-lens multi-agent review + refute pass) → fixes applied
8 findings confirmed (11 dismissed). All addressed:
1. **[BUG, fixed] inf/nan `budget_cap_cents` crashed the durable phase.** `Decimal(str(float("inf")))`
   *succeeds* (→ `Infinity`); `Decimal("NaN") >= 0` signals; `CostCents` (finite) rejects inf — so
   `CheckpointDecision.from_params` raised instead of degrading. Fix: `parsed.is_finite()` guard
   (short-circuits before the `>= 0` compare). Tests: pure degrade over inf/-inf/nan/"Infinity"/"NaN"
   + handler-level inf-cap→COMPLETED-not-crash.
2. **[DRY, fixed] `persist_tier` + `_claim_icp_key` duplicated M6.3 `_write_score_object` verbatim**
   (a hard conventions §2 / CLAUDE.md rule). Extracted the shared "one live winner per ICP" write
   protocol to **`discovery_scoring/claim_writes.py`** (`write_icp_scoped_claim` + `claim_icp_key`);
   both M6.3 `_write_score_object` and M6.4 `persist_tier` now build only their value_json+stamped
   claim and delegate the read→replay→supersede-by-ICP→insert. Full M6.3 suite re-run green (behavior
   preserved). +1 src file (mypy 128→129).
3. **[tests, added] approve-with-adjusted-cutoffs supersedes prior approve through the handler**
   (cross-cutoff re-tier: new cutoff_version, 3 live + 6 history, each live tier = cversion_B).
4. **[tests, added] `load_score_views` merge-collapse** (two pre-merge entities → one survivor view)
   **+ pre-merge-loser skip** (live claim on the merged-away loser → skipped, no crash).
5. **[tests, added] over-cap equality boundary** (estimated == cap is WITHIN cap; cap-1 halts).
6. **[tests, strengthened] `proposed_cutoffs`/`cutoff_version` asserted == the exact (default/adjusted)
   cutoffs** (was truthy-only); happy-path approve pins `errors == 0`.

## Follow-ups
- **Cost-estimate snapshot durability** is in the payload (M7-persisted), not an M6.4-owned row —
  the documented M7 co-ownership boundary. When M7 lands, `campaign_phase_checkpoint.payload_json`
  stores it; confirm the audit-trail read path then.
- **load_score_views merge edge:** if a merge moves the score claim off the survivor *after* scoring,
  the live-claim-for-run read on the survivor misses it (skipped defensively). Same class as M6.3's
  deferred per-merge resolution; not expected within one campaign run between scoring and checkpoint.
- **M6.5 coverage hook:** `CheckpointReview.coverage` is a `None` placeholder for the M6.5 coverage
  report to populate through this payload (M6.5's stated seam).
- **api wiring:** `TierCheckpointPhaseHandler` exported; registration into `CampaignRun` is M7 at the
  api composition root — not in this package.
- Next: ENG-150 (M6.5 — coverage-confidence estimator); M7 wires the durable suspend/resume + phase store.
