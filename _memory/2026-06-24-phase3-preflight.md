# 2026-06-24 — Phase-3 (M10 ∥ M11 ∥ M12) pre-flight kickoff

## Goal
Set up parallel development of M10 (compliance), M11 (tier-4 synthesis), M12 (value narrative/handoff)
in three worktrees. M8/M8A/M9 are done + merged to `origin/main` (PR #22, `18d7fab`).

## State / decisions
- Synced local `main` to `origin/main` (`18d7fab`). The old local `main` was an EMPTY orphan
  "Initial commit" (no common ancestor, 1 vs 110) — `git reset --hard origin/main` in the main
  worktree (`/Users/aryankeshri/conductor/repos/research-and-data`). Single alembic head confirmed:
  `3df3b2f629fd`.
- Feasibility (verified by an 11-agent workflow + spot-checks): parallel is FEASIBLE and machine-
  enforced (import-linter independence contract — `compliance`/`synthesis`/`narrative` can't import
  each other). Only cross-sibling edges are SOFT/store-mediated. **M12←M11 is SOFT** — M12 builds
  against fixture verified `account.*` current_values; zero M12 code change at integration.
- The risk is SHARED SURFACES, not dependencies. Neutralised by a pre-flight commit set PF-0..PF-8 on
  `integration/phase3-preflight` BEFORE forking. Full plan: `docs/specs/_phase3-preflight.md`.
- **Two user decisions:** (D-OBJ) objection (Art. 21) = MERGE/substrate exclusion, not a use-gate
  reason; (D-EXP) retention `EXPIRED` = M10.5 tombstone-before-read. They UNIFY: M10.5 supersedes
  (objected | expired) claims before the merge read; the non-superseded filter excludes them; M12
  needs no special-case; no `merge` ranking change. EXPIRED ≠ STALE (40d sensitive claim is FRESH by
  90d TTL but EXPIRED by 30d retention).

## Done this session (branch `integration/phase3-preflight`, NOT pushed)
- **PF-0** (`d683690`): green the base — ruff lint/format fixes on the `3df3b2f629fd` merge migration
  + AC-6 test. Base green: ruff/mypy(203)/11 contracts.
- **PF-1** (`fdcaa64`): ONE core contract-delta (signatures only, no migration, no behavior):
  - NEW `core/compliance.py`: `UseGate.evaluate(claim)->UseDecision`, `UseDecision`,
    `is_outreach_promotable(claim, decision)`. **Put in a NEW module, NOT `core/verification.py`** —
    that module's docstring says the use-gate is "deliberately not here" (Doc D §5 separability).
  - `core.enums.UseReason` = allowed/sensitive_locked/use_class_disallowed_for_regime. **No `objected`**
    (D-OBJ → substrate, not gate).
  - `is_outreach_promotable` named apart from existing accuracy-only `core.claim.is_promotable`/
    `can_be_promoted` (real collision); takes `(claim, decision)` because the use verdict is a SIDE
    TABLE (PF-2), not a claim column.
  - Promoted `AgeOutCandidate` + `due_for_age_out` from `verification/freshness.py` onto
    `core.verification.Freshness` (M10.5 reads via core). `record_re_research_candidates` NOT promoted
    (takes AsyncConnection → would add a DB dep to core). `verification/freshness.py` + `__init__.py`
    now import/re-export the type from core.
  - `core.handoff.AccountHandoff` additive+defaulted: icp_spec_version, campaign_run_id, assembled_at,
    coverage_confidence, field_conflicts.
  - Green: ruff/mypy(204)/11 contracts; core type tests pass (42 passed, 15 DB-skipped).
- Docs: wrote `docs/specs/_phase3-preflight.md` (the checklist/owner's source of truth) + added
  "Phase-3 pre-flight overrides" callouts to M10/M11/M12 specs.

## PF-2…PF-8 outcomes (same session) — investigation re-scoped the checklist
- **PF-6** `9e06ade`: realigned `account.operational_pain`/`account.strategic_moves` tier_plans
  `("exa","parallel")`→`("exa_deep","parallel_task")` (only those are registered source_keys; provider
  is a separate column). Added a no-DB guard test. Left the dangling `"exa"` on deterministic fields
  (recent_funding/hiring_velocity) — `no_resolver→empty` is safe; LLM-filling a deterministic field is
  the anti-pattern.
- **PF-7** `4fab273`: `api/composition.py` `RESEARCH_PACK_LOADERS` registry (replaces the flat
  load_research_packs body) + `VERIFICATION_GATE_ORDER` constant (use_gate last) + 3 per-milestone
  wiring scaffolds (`api/{synthesis,compliance,narrative}_wiring.py`).
- **retrieval seam** `4fab273`: froze `core.retrieval.ClientKnowledgeChunk` + `ClientKnowledgeRetriever`
  (M12←M5; narrative can't import stage0, so the seam lives in core). M12 stubs the impl.
- **PF-8 DROPPED (was harmful):** `exa_deep` is `entity_scope=BOTH` BY DESIGN — it's the tier-4
  synthesis engine for `contact.facet` too (M8.5/M10; merged AC-6 test uses `_FACET_SOURCE="exa_deep"`).
  Tightening it to account-only breaks merged code. Firewall = M11 field-routing/resolver-assertion,
  not a manifest edit. Corrected the doc + M11 spec callout + (TODO) the M11 Linear comments.
- **PF-3/PF-4 confirmed, NO base code:** merge already excludes superseded (`merge_claims` merge.py:210
  `superseded_by is None`; `current_values` :311 `WHERE … superseded_by IS NULL`). M10.5 tombstone-by-
  supersede works with zero merge change. 40d fixture + sweep = M10.5.
- **PF-2 / PF-5:** recorded decisions (side-tables; tombstone=`ExtractionMethod.HUMAN`). No base code.
- All green after each commit: ruff, mypy (208), 11 contracts, PF-6 test + import smoke.

## TODO (next)
- Correct the 3 M11 Linear comments (ENG-143/148/155) re: PF-8 dropped (they said tighten to
  entity_scope=account — now wrong).
- User to review PF-1 (core delta) + PF-6/PF-7 before forking.
- Then fork WS-A=m11, WS-B=m10, WS-C=m12 off the frozen base. Integrate M11→M10→M12.
- Branch `integration/phase3-preflight` now has 6 commits (PF-0,1,docs,6,7); NOT pushed.

## Verification performed
`make`-equivalent: `uv run ruff format/check`, `uv run mypy` (204 files clean), `uv run lint-imports`
(11 kept/0 broken), targeted `pytest` of core handoff/claim/promotion + freshness (pass/skip on no-DB).
Did NOT run full `make test`/`db-smoke` (needs Postgres up).
