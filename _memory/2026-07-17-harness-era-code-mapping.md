# 2026-07-17 — Harness-era doc set read + existing-code reuse mapping (analysis session)

## What happened
Full read of the harness-era doc set as revised through v1.2: harness architecture doc (22 REQs,
four planes, build steps 0–7, decisions register incl. 2026-07-17 fleet refinement + Doc R row),
Doc A (agent runtime, v1.2), Doc M (scoped memory), Doc S (content plane, v1.1), Doc R (repo
restructure + structlog, ratified 2026-07-17), doc-map README, plan-differences transcript,
CLAUDE.md/AGENTS.md, and the 07-03/07-06/07-07 memory notes. Then a full code inventory
(read-only subagent) to verify the docs' "current state → delta" claims against the tree.

**No code changed this session.** Deliverable = understanding playback + reuse map + clarifying
questions to founder (see below).

## Verified state (inventory findings)
- M0–M13 all shipped with tests + 43 alembic migrations; matches the docs' claims exactly.
- **Zero harness-era code exists**: no toolbelt/recipe/journal/SSE/deepagent/skill/fleet/memory/
  workspace/brand/product/thread code or tables. All of it is docs-only.
- Existing `manifest`/`outbox`/`harness`/`campaign` greps are pre-pivot concepts (source_manifest,
  M12.3 handoff_event outbox, eval harness, M7 CampaignRun) — do not confuse with harness-era
  namesakes.
- Uncommitted working tree: (a) founder's Settings slice — new `config/settings.py`
  (`CLUE_SYNTHESIS_MODEL`, `load_settings()`), gateway/models wiring, stage0 constant moved,
  `tests/test_config_settings.py`; (b) the entire harness-era doc set + 3 memory notes untracked;
  (c) AGENTS.md slightly stale vs CLAUDE.md (missing M10.5×M9.3 backlog item + newest framing).
- Branch `m13.3/learning-loop` is 1 commit ahead of origin/main (founder brief); main already
  merged the branch via PR #26 → Doc R's R1 "quiet point" (worktree quiescence) appears satisfied.

## Reuse map essentials (existing code → build steps)
- Step 0 fleet worker: NEW shell, but drives existing M7 durable machinery (campaign_run machine,
  scheduler, budget_event, idempotency_ledger) + M8A per-account graphs as jobs.
- Step 1 storage: NEW; `adapters/cache.py` ArtifactCache is the content-addressing precedent;
  `config/settings.py` (founder's fresh slice) is the intended config slot per REQ-07.
- Step 2 toolbelt: wraps existing near-tool-shaped handlers (stage0, discovery_scoring phases,
  `AccountDeepOrchestrator.run_one`, narrative handoff); convert silent-empty → PreconditionFailed
  (e.g. `api/deep/handler.py:252`); projection API reads existing tables; SSE generalizes the
  M12.3 outbox pattern.
- Step 3 ≡ Doc R R1: DRY backlog (normalize_host ×3, reference_time ×2, decode_jsonb_scalar ×5,
  BudgetTracker, claim_tagger hook → contact/fill.py rejoins waterfall, −~115 lines).
- Step 4: coverage ledger NEW (detection exists: durable/planning, waterfall StopReason, M9.5);
  propose_field clones M13.3 config_revision pattern (`register_field` exists; un-drop synthesis
  discards in `stage0/icp_synthesis.py`); ingestion rides adapters + ClaimExtractor seam;
  interview source = new source over existing registry (`register_source` exists); readiness spec
  enforced by existing M9.1 pre-spend machinery.
- Step 5: journal/recipes NEW tables; supervisor reads existing aggregates (M13.4, source_yield,
  verification health).
- Step 7: claim_derivation mirrors claim_support (M12); entailment mode extends M9.3 judge;
  re-check tool = view over M9 + snapshots.
- Doc M slice 1: NEW subsystem; reuses reuse_scope fail-closed tenancy pattern, config_revision
  for caps, M10.5 DSAR patterns.
- Backlog items cited as step prerequisites: api-root gate wiring (M9.1), binding pre-insert
  stamp (M9.4), merge retention-awareness (M9.5), verdict-rationale redaction (M10.5×M9.3).

## Questions posed to founder — rulings (2026-07-17, same day)
1. Execution posture: **still open** (not yet answered).
2. Commit posture for uncommitted docs/memory/Settings slice: **still open**.
3. Object-spine ownership: founder delegated the settlement with a binding principle — **do not
   multiply abstractions to satisfy import conventions; the conventions were stated somewhat
   blindly; maintainability/simplicity is the goal; design so invalid states are unrepresentable
   (constraints/types) rather than exception-handled**. Settlement proposed: one small
   `libs/clue-spine` lib (types + tables + plain CRUD functions, no protocol indirection) for
   workspace/brand/product/project; single-consumer tables (thread, campaign_artifact → platform
   shell; campaign, artifact_plan → content subsystem) live with their one owner.
4. **RULED: rename in the same pass as the spine.** `workspace_id` is the final name; migrate ALL
   old `tenant_id` (claim tenancy) and `client_id` (icp_spec, source_profile overrides,
   pre_spend_policy, client_policy, etc.) usages in code + schema. Wide but mechanical; must ride
   the same quiet point as Doc R R1 (conflicts with worktrees the same way).
5. **RULED: Doc M scope enum uses `project` from birth** (not Doc M's literal `campaign`); note
   the mapping at Doc M's next revision.
6. **RULED: Doc M slice 1 in parallel** with steps 0–2 provided it doesn't touch step-1/2
   surfaces (it doesn't — new tables + new package; only coupling is spine scope ids → spine
   lands first).

## Next
Founder to rule on execution posture (Q1) + commit posture (Q2) → then: commit docs; R0; R1
(+DRY); spine + workspace_id rename pass; R2 scaffolds; step 0. Update this note as rulings land.
