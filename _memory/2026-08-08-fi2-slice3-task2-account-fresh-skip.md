# FI-2 slice 3 — Task 2: §6.1 fresh-skip in the account entity-research runtime (2026-08-08)

Commit `6eba0cab` on `platform/frontend-integration` (base `6626edf3`). No migration (head `870fe4f2af87`).

- `platform/api/clue_api/account_entity_research.py`: `state()` does one `current_values` read
  (`WorkspaceScope.for_workspace`, never `claim.workspace_id`) + one species read over the admitted
  account-axis fields. Born-complete iff `project_neutral` AND fresh AND evidence span AND no conflict;
  `project_relative` never. `assess()` folds those claim ids into `claim_refs` and adds
  `skipped_field_reasons` (`<field>:existing_claim_fresh`, rides `coverage_json` — no column, no migration);
  unresolved reasons use the contact vocabulary plus the account-only
  `existing_claim_project_relative`. The finalization engine gained `result_evidence_fields`, accepts a
  cited live span-bearing claim as a completed field's evidence, and independently re-checks freshness
  (`evidence_complete`) + species (`policy_scope_respected`).
- `platform/agents/clue_agents/account_entity_research.py`: additive `AccountExistingClaimProjection`
  (mirrors the contact one, plus `research_scope` + `born_complete`), `existing_claims`,
  `skipped_field_reasons` — all defaulted, no consumer breaks.
- Species via `clue_api.frontend_read.account_detail.field_species` (imported, not restated). Tidy end
  state = move it beside `list_effective_fields` in `claimstore.registry`; deferred to avoid a mid-slice
  file collision.
- Tests: `tests/api/test_account_entity_research_fresh_skip_db.py` (6, two-project fixture; two run the
  full M8D runtime). Red-first verified by stashing the source files: 5/6 fail without the change.
- Gate on throwaway DB `clue_fi2_s3_t2`: touched suites + tests/fleet + tests/claimstore green; whole
  `tests/api` 748 passed / 1 pre-existing environmental failure
  (`test_agent_registry_wiring::...c61_backend`, reproduces with the change stashed); ruff/mypy/lint-imports
  clean. One non-reproducible flake in `tests/fleet/test_b4_composed_run_db.py` (30s `lease_ttl`, load-
  sensitive) — passed on every re-run.
- Handoffs: (a) Task 3 must keep the guard's "first Exa call includes every primary Exa field" consistent
  with any admission-level bundle shrink (today the shrink is downstream of the guard, so nothing breaks);
  (b) `AssessAccountCoverageInput.result_refs` is `min_length=1`, so a job with literally zero results
  cannot close coverage — an all-born-complete job still relies on the committee call producing one
  (production's Sumble scope accepts a `claim:` office reference; the R5 test fixture is stricter).

## Fix round 1 (commit `bf1ef028`)

Review Critical: the governed prompt (`account/v1/prompt.md:28-30`) allows only retained result refs
as buying-unit evidence, so an all-known account had no legal path to coverage — the earlier test's
`claim:` ref is not what a prompt-obedient agent does.

- `AssessAccountCoverageInput.result_refs` lost `min_length=1`; the engine's set-equality against the
  persisted result set remains the authority. `assess` refuses an empty close unless every completed
  field is borrowed (guard proven by a forged-state test).
- `semantic_validation_error` made public in `entity_research_tools`; bound as
  `handle_validation_error` on all four account engine tools, and the `repairable` wrapper converts
  an in-body `ValidationError` into the same bounded `ToolException`.
- Skip reasons: any result row (not just `outcome='found'`) disqualifies a field from
  `existing_claim_fresh`.
- Tests 6 → 9, incl. the required zero-provider-call job (0 results, 0 spend, `NEEDS_REVIEW` +
  `committee_not_researched`, `all_passed()`), the refused empty close, and the tool-degradation case.
- Gate re-run green (same throwaway DB); only the pre-existing `test_agent_registry_wiring::…c61_backend`
  environmental failure remains.
- Still open elsewhere: prompt amendment (next governed C6 bump), Exa first-call guard (Task 3),
  `field_species` relocation to `claimstore.registry` (Task-4 close-out), R5 committee fixture.
