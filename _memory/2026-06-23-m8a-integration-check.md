# M8A.2 / M8A.3 / M8A.5 integration check (on m8a/orchestrator)

**Date:** 2026-06-23 · **Branch:** `m8a/orchestrator` (= `origin/m8a/orchestrator` c71d26e + integration commit `68b24dc`, local-only, not pushed).
**Task:** verify the three M8A pieces merged into `m8a/orchestrator` (via PRs #19 M8A.5, #20 M8A.3, #21 M8A.2, on top of M8A.0 + M8A.1) are *properly integrated*; fix if not.

## State found
- The merge was textually clean (no conflict markers) and the gate was already green (contracts 11/0, api/deep tests 35/35). M8A.0 (durable seams) + M8A.1 (orchestrator trunk) underneath.
- **M8A.3 ↔ orchestrator/handler: already wired.** `AccountDeepOrchestrator.__init__` takes `config: DeepPhaseConfig` + `budget: BudgetEngine`; `_profile_contacts` does the `check(scope=ACCOUNT)` admission + committee-size cap + intra-account semaphore. The orchestrator records `budget_stop` on `AccountDeepResult`; the handler maps RUN-scope `GRACEFUL_STOP → PhaseResult(PAUSED)` (handler `run`, the `paused = any(... GRACEFUL_STOP)` line) and `DENY → partial-but-COMPLETED`.
- **M8A.1 durable references: already wired.** The orchestrator persists per-stage `references_index` into `account_run` via `run_io.DbAccountRunIO.save_references` (resume reads the folded index + `sub_phase`).
- **THE GAP — M8A.5 ↔ M8A.2 handler: NOT wired.** `build_handoff_skeleton` was **dead code in the runtime path** — called only by its own tests. The handler still emitted its *interim* inline manifest (carrying only a `claim_ref_count`), so the spec-required references-only `references_index` (M8A.5 AC: "references_index contains only claim ids") never reached `PhaseResult.payload`. The handler code literally said so: `_succeeded_outcome` comment "M8A.5 is a parallel branch, so the function does not exist on this base — the inline manifest is the interim form," and the module docstring "(M8A.5 — folded into this payload when it lands)". The fold was never completed after M8A.5 merged.

## Fix (commit 68b24dc)
- **handler.py**: `_succeeded_outcome` now emits `build_handoff_skeleton(result).manifest()` (the purpose-built M8A.5 `DeepCompleteManifest` — per-section claim-id index, ids only) + the budget-derived `status`. Dropped the now-duplicate `_committee_member_ids`/`_coverage_view` helpers (DRY — the skeleton owns that). `_budget_stop` reads the now-merged `AccountDeepResult.budget_stop` field directly (was a forward-compat `getattr`). `_failed_manifest` aligned to the `DeepCompleteManifest` key shape. Refreshed the stale "when it lands / until it merges" M8A.3/M8A.5 docstrings.
- **handoff_skeleton.py**: added `AccountHandoffSkeleton.committee_member_ids` — **resume-robust**: sourced from `committee.members` on a fresh run, else from the profiled `contacts` when the committee result is `None` (a resumed run). This preserves the handler's prior member-id sourcing (the resumed-account test depends on it) now that the skeleton is the single manifest producer.
- **tests**: updated to the new manifest shape (`account_entity_id` not `entity_id`; assert the `references_index` index, not `claim_ref_count`); added `committee_member_ids` to the skeleton's pinned field-set test.

## Verification
`make check` green end-to-end: **lint, typecheck (200 src files), contracts 11/0, 843 passed / 607 skipped** (skips = DB-gated tests, unaffected — the api/deep change is in-memory/fakes). api/deep suite 35/35.

## Net
All three (M8A.2/.3/.5) are now genuinely integrated: the handler drives the orchestrator (M8A.3 budget admission inside), maps the budget verdict, and emits the M8A.5 references-only `DeepCompleteManifest` (with `references_index`) as the per-account payload. No other M8A.2/.3/.5 cross-wiring gaps found. **Remaining M8A:** M8A.4 (exactly-once spend) + M8A.6 (composition root + AC-6/AC-4) still unbuilt (per the spec). Local commit only — user pushes/merges.
