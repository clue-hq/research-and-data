# 2026-08-08 — Lane E §7 ratified (D1–D4) + M12 ⇄ verification-toggle compat design approved

## Founder rulings (recorded into `docs/specs/FI-lane-E-on-completion-synthesis.md`, status → RATIFIED)
- **D1:** synthesize on {`completed`, `needs_review`}; stamp `research_outcome` into `value_json`. Never on `cancelled`.
- **D2:** PROJECT_NEUTRAL, **with amendment**: supersede key + `value_json` carry an explicit `project_id` dimension from day one, fixed `None` while neutral — key `(entity, field, workspace, project_id=None)` — so a future PROJECT_RELATIVE flip is a value change, not a key migration. Spec §2.5 updated in place.
- **D3:** E3 (Positioner composition) is IN the MVP; lands after FI-2 slice 3 finishes landing (T1 supersede gate already satisfied via `5fa0403c`+`6626edf3`).
- **D4:** acknowledged (empty VALUE_NARRATIVE section on every account view post-L1-fix).
- **Lane E is unblocked — E0 may start.**

## M12 ⇄ `CLUE_VERIFICATION_ENABLED` compatibility (new spec: `docs/specs/FI-M12-verification-toggle-compat.md`, design approved, awaiting founder spec review before implementation plan)
Investigation findings (two Opus read-only sweeps, 2026-08-08 — do not re-derive):
- The `784fb662` toggle is write-side only; the read side (`merge.py::_is_eligible`, `require_verified_tier4=True` at `merge.py:103,136-141`) never sees it. Judge off ⇒ tier-4 never VERIFIED ⇒ invisible everywhere.
- M12 breaks twice: Positioner *inputs* read through `current_values` (`positioner.py:263`) lose tier-4 evidence; its *output* is itself tier-4 and gets merge-excluded + handoff-filtered (`handoff.py:506` VERIFIED-only).
- Construction hazard: `Positioner.__init__` requires `judge:` (no default, no None-guard, `positioner.py:198`); judge call inline at `:463`.
- **Positioner has zero production callers** (tests only); `narrative_wiring.py` registers the field pack only; HANDOFF parked behind independent `c7_production_handoff_enabled` (default false). So this is a constraint on the upcoming E3 composition, not a retrofit.
- Merge-policy threading: every production read resolves to the single `DEFAULT_MERGE_POLICY` constant (`merge.py:115`); NO caller overrides `require_verified_tier4` or sets `fallback_to_unpromotable=True` anywhere (prod or tests). `clue_config.schema.MergePolicy`/`WorkspaceConfig.merge_policy` are imported by nothing (matches the [M9.2×M0.4] backlog note).
- Approved design: (A) judge optional in Positioner/Lane-E prose/handoff filter, skip+metric when None; (B) effective default merge policy derived from settings at one claimstore accessor (`require_verified_tier4 = settings.verification_enabled`) — global-when-off, founder-approved. REJECTED/WEAK exclusions stay on in both modes. Scope: ~1 focused day.

## Next
- Founder reviews `FI-M12-verification-toggle-compat.md`; then write the implementation plan (superpowers writing-plans) and implement.
- Lane E E0 can start independently.
