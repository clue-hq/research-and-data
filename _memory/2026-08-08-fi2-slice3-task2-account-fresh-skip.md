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
