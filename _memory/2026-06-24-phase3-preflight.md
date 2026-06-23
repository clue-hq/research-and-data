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

## TODO (next) — owner = integration owner unless noted
- PF-2 side-tables (total decision, overrides M10 spec "extend claim row"); PF-3/4 the unified
  tombstone-before-read sweep (M1.2+M10.5); PF-5 tombstone=`human`; PF-6 fix `packs.py` tier_plan
  (`("exa","parallel")` → `("exa_deep","parallel_task")` for pain/moves; audit other `"exa"` plans);
  PF-7 split `api/*_wiring.py` + `RESEARCH_PACK_LOADERS` registry + freeze the verification order;
  PF-8 tighten exa_deep+parallel_task to `entity_scope=account`; freeze `retrieve_client_knowledge`.
- Then fork WS-A=m11, WS-B=m10, WS-C=m12 off the frozen base. Integrate M11→M10→M12.
- Update Linear issues for M10/M11/M12 with the pre-flight overrides (in progress).

## Verification performed
`make`-equivalent: `uv run ruff format/check`, `uv run mypy` (204 files clean), `uv run lint-imports`
(11 kept/0 broken), targeted `pytest` of core handoff/claim/promotion + freshness (pass/skip on no-DB).
Did NOT run full `make test`/`db-smoke` (needs Postgres up).
