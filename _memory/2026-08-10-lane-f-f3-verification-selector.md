# Lane F / F3 — R11.3 verification account selector (branch `platform/lane-f-r11-bridge`)

Commit `67a9616d`, on top of F1 (`b7b9e7b0`/`34d17024`) + F2 (`bb7e8abd`). No migration.

## What landed

- **`platform/api/clue_api/entity_research_verification_resolver.py`** (new):
  `build_entity_research_account_resolver(*, session_factory=transaction, sink=None)` →
  `HighTierResolver`. Reads `read_latest_account_fleet_for_project_run` (§6c), then
  `DbEntityResearchJobStore.list_jobs` **on the borrowed connection** (one snapshot), and yields an
  `AccountSpec` per terminal ACCOUNT job whose `finalization_outcome ∈ {completed, needs_review}`
  (`ACCEPTED_FINALIZATION_OUTCOMES`, mirroring Lane E's `SYNTHESIZABLE_OUTCOMES`). Sorted by entity
  id. Exclusions (refused outcome, or the live job state for a nonterminal job) are censused to
  `research.verification.selector.{selected,excluded}_accounts` + one structured log — never raised.
  No fleet run, or one owned by another project → typed `EntityResearchRunMissing`.
- **Consumers swapped (both):** `run_composition.py` — one shared instance now feeding VERIFICATION
  and the HANDOFF retention sweep (DEEP stopped consuming it at F1); `toolbelt_wiring.py`
  `run_verification@1`, which additionally refuses up front with a typed
  `entity_research_run_missing` precondition (defense in depth; the resolver still raises).
- `build_high_tier_resolver` / `get_account_deep_launch` untouched — cleanup-PR inventory, with a
  supersession note on the function.

## Decisions worth not re-deriving

- **`AccountSpec.tier`** has no M8D equivalent (the confirmed fleet selection *is* the
  authorization; depth lives in the per-job authorization + its cap). Rather than invent a band,
  every spec carries the constant `ENTITY_RESEARCH_SELECTION_TIER = "entity_research_selection"`.
  Neither consumer reads `tier` — both use only `entity_id`.
- `contact_profiling_allowed=False` (an account job authorizes no contact axis; contact research is
  separately confirmed) and `research_directive=None` (M8D pins its directive by ref+sha on the
  selection, not as the legacy `ResearchDirectivePin`). `field_keys` =
  `authorization.effective_admitted_field_keys`; `budget_cap_cents` = the job row's immutable cap.
- Job scope == run scope by R2 construction, so the workspace guard on the fleet row covers jobs.

## Pre-existing defect found and fixed here

`RunVerificationTool` emitted a `verification_enabled` reference that `PhaseAccountsOutput` never
declared → `ToolContractViolation` on **every** invocation. Unreachable before this slice (the tool
could never resolve an account, but the violation fires on the success path too). Removed the key.
**Do not "fix" it by widening `PhaseAccountsOutput`:** the reviewed agent profiles pin
`run_verification@1`'s `output_schema_sha256`
(`platform/agents/catalog/profiles/research-specialist/*/profile.yaml`), so a schema change breaks
catalog resolution (`AgentCatalogError: tool 'run_verification@1' schema digest changed`, ~55 test
errors across `test_agent_registry_wiring` / `test_c8_*`). Surfacing the toggle in the tool result
needs a new pinned profile version — a governed change, tracked as a follow-up, not F3's.

## Verification

`tests/api/test_r11_verification_resolver.py` (11 tests, DB-backed on a throwaway `clue_f3`):
missing fleet run raises in both toggle states (with the empty-resolver "silent zero" pinned in the
same test as the shape being closed); foreign-project fleet = missing; accepted-outcome selection +
honest `AccountSpec` fields + census; a fleet that accepted nothing = honest empty; latest-run-only;
the composed DEEP→VERIFICATION drive in both toggle states (disabled records
`verification_enabled=false` + `accounts_skipped`); the tool's refusal + success in both states; the
HANDOFF sweep composes over the same resolver. Red proof: with the implementation stashed, the two
tool tests fail (no `entity_research_run_missing`).

Gates: ruff + format (repo-wide), `uv run mypy` (629 files clean), `lint-imports` (25/25),
`tests/architecture`, and the whole `tests/api` directory — 7 failures, byte-identical to the
pre-change baseline (agent_registry / agent_turn_db / c7_production_readers / exa_websets_d3 /
lane_d_b1_join_db ×2 / projections_app), all environmental/pre-existing on this branch.
