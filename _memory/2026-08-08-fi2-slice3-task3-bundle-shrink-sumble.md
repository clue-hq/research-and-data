# 2026-08-08 — FI-2 slice 3, Task 3: §6.2 bundle shrink + §6.3 Sumble freshness

Branch `platform/frontend-integration`. Spec `docs/specs/FI-2-workspace-account-layer.md` §6.2/§6.3;
plan `docs/specs/FI-2-slice3-implementation-plan.md` Task 3. **No migration**; single alembic head
`9398ae4467e3` (the plan's "head `870fe4f2af87`" is stale — Lane B's auth migration landed on top).

## Situation inherited

A previous agent was interrupted mid-test-write; its partial work is the WIP checkpoint `49f98ec5`,
which then went **behind** the Lane B merge `81fd5ab1`. History was NOT rewritten — this session
built forward with four new commits on top.

Commits produced (in order):

- `c81c7cba` — harden the §6.2 bundle-shrink implementation
- `98bdf0bb` — complete the §6.3 Sumble freshness tests
- `edff5bcc` — §6.2 tests (bundle shrink, first-call authority, gross estimate)
- `2b3d45ea` — correct and test the §6.3 species guard

(Two unrelated Lane E doc commits, `c1e6e688`/`32eb8078`, landed concurrently between `edff5bcc`
and `2b3d45ea`. Docs/_memory only — no code overlap.)

## WIP hunk-adoption verdicts

| WIP hunk | Verdict |
| --- | --- |
| `exa_deep_preparation` — borrowed-set exclusion from the bundle + `exa_deep_all_fields_already_known` reason code | **KEPT**, proven by new tests; **FIXED** the `WAITING_EXTERNAL`/`FAILED_EXTERNAL` early returns, which dropped the `<field>:existing_claim_fresh` skip refs every other return carries |
| `account_entity_research` — `existing_account_claims` / `born_complete_account_field_keys` extraction (one borrowed-set derivation shared by state read, guard, bundle) | **KEPT** — this is the load-bearing DRY move; mutation-tested |
| `account_entity_research` — R5 guard `already_known` refusal + `primary - borrowed` | **KEPT** (both mutation-proofed); **FIXED** the two-connection read into one snapshot (the borrowed set and the prior-call history answer the same question and could be split by a concurrent write) |
| `account_research_fleet_launch` — 20-line "netting deliberately not done" comment mid-loop | **KEPT the decision, REWROTE the argument** (moved to the equality check it governs; added two verified facts + a replay hazard the WIP missed — see below) |
| `account_gap_enrichment.AccountGapReason.STALE` | **KEPT** (JSON payload enum, no DB enum, no migration) |
| `sumble_account_gaps` — stale ⇒ eligible ladder branch | **KEPT**, red-proofed |
| `sumble_account_gaps` — project-neutral species enforcement (beyond contract) | **KEPT but its justification was FACTUALLY WRONG and is corrected**; now tested |
| `sumble_entity_research_tools` — `SumbleAccountGapEligibilityError` ⇒ `EntityResearchGovernedRejection` on the M8D path | **KEPT**, red-proofed |
| 8 incidental files (`account_research_fleet`, `account_research_wiring`, `committee_eligibility`, `entity_research_tools`, `exa_contact_compiler`, `external_research_wake`, `recipe_wiring`, `sumble_committee_inputs`) | **KEPT as-is** — verified pure `ruff format` reflow, zero semantic change, already at HEAD; reverting would be churn |
| `tests/api/test_fi2_63_sumble_freshness_db.py` (365 lines, "INCOMPLETE") | 4 of 5 cases **KEPT**; the 5th **REWRITTEN** (it could never have passed — see below); one case added |

## Decisions

**Estimate netting (§6.2 should-have / spec §11 item 3) — deliberately NOT done, now argued
correctly and pinned by a test.** The WIP refused to net and gave three reasons; two were right,
one was weak, and it missed the strongest. Verified facts:

1. `effort_policy.budget_cap_cents` is a per-account *cap*, not a per-field price — nothing
   decomposes it per field.
2. That same per-account figure is **each job's `budget_cap_cents`** (`account_research_fleet_launch.py`
   :483/:513) and its sum is what `approved_budget_cap_cents` must cover. Netting the sum without
   netting the per-job caps would approve a launch for *less authority than it hands out*.
3. `expected_estimated_cost_cents` is a **caller-supplied input**, equality-checked server-side.
   There is **no server-side estimate-proposal surface** for this launch at all —
   `LaunchAccountResearchTool.estimate` just echoes the input back. So netting breaks every existing
   caller and has no producer to move in step; the spec's "so the human approves an honest number"
   presumes a proposal surface that does not exist.
4. (New) A launch-time freshness probe is a prediction that enters the durably-replayed launch
   identity; a claim expiring between launch and replay would turn a legitimate idempotent replay
   into a conflict.

Consequence stated rather than hidden: the estimate is a **ceiling**, the fresh-skip materialises as
under-spend, and where the money went is already answerable from data (per-job spend + the coverage
ledger's per-field `…:existing_claim_fresh` reasons). Pinned by
`tests/api/test_fi2_62_launch_estimate_db.py` so implementing netting later is a *test-visible*
contract change. **Founder-facing:** §11 item 3 should be re-scoped to "build an estimate-proposal
surface, then net on both sides", not "net the launcher".

**Sumble species guard — kept, justification corrected.** The WIP said a *workspace* registry
override could declare a Sumble field project-relative. False: `register_workspace_field` accepts
only `client.*` keys and hard-forces `PROJECT_NEUTRAL`. The reachable hazard is a **declaration**
change (a new Sumble-approved field, or a re-declared one, carrying `project_relative`), which would
leave the ladder working while quietly meaning the wrong thing — the ladder reads the
*workspace-merged* current value, so "already answered" is only correct for a neutral field. Guard
kept, comment corrected, refusal now tested by flipping the registry row.

**Legacy Sumble toolbelt path.** `enrich_account_gaps@1` is in
`QUARANTINED_ENTITY_RESEARCH_TOOL_ADDRESSES`, so a *registry* invocation is refused with
`entity_research_agent_not_composed` long before eligibility runs — the WIP's 5th test asserted
`sumble_account_gap_ineligible` through `invoke_tool` and could never have passed. The test now
asserts both halves: the quarantine (so it cannot quietly lapse) **and** the tool object invoked
directly (still the live implementation a human path / exact replay resolves), proving §6.3(b) left
it raising `PreconditionFailed('sumble_account_gap_ineligible')`.

## Tests added / completed

- `tests/api/test_fi2_62_bundle_shrink_db.py` (4) — borrowed field excluded from the Exa output
  schema *and* its directional question dropped; all-borrowed axis ⇒ `NOT_APPLICABLE` +
  `exa_deep_all_fields_already_known` + zero `external_research_operation` rows + zero HTTP;
  parametrised negative (stale claim / evidence-less claim ⇒ field stays in the bundle).
- `tests/api/test_fi2_62_first_call_authority_db.py` (3) — prompt-obedient omission of borrowed
  fields authorized; lazy omission of an unresearched primary field still refused (and the honest
  first call authorized); re-buy of a borrowed field refused.
- `tests/api/test_fi2_62_launch_estimate_db.py` (1) — gross-estimate contract pin.
- `tests/api/test_fi2_63_sumble_freshness_db.py` (6, was 5-and-broken) — premise, stale⇒eligible,
  fresh⇒refused, M8D governed skip, legacy path, **new** relative-declaration refusal.

Test-fixture notes for successors: an `exa_deep`-sourced claim needs full
operation/snapshot/artifact lineage (DB trigger) — use `sumble_jobs` for a synthetic "already known"
claim; and a narrowed Exa response payload must have its **grounding narrowed with it** (the
provider contract refuses grounding naming a field the content lacks).

## Mutation evidence (each load-bearing behaviour)

| Mutation | Caught by |
| --- | --- |
| revert `exa_deep_preparation.py` to pre-WIP | 2 of 4 bundle cases |
| revert `sumble_account_gaps.py` to pre-WIP | 3 of the Sumble cases |
| revert `sumble_entity_research_tools.py` to pre-WIP | the governed-skip case, alone |
| drop `- borrowed` from the guard's `primary` | 2 first-call cases |
| drop the `already_known` re-buy refusal | the re-buy case |
| widen `born_complete_account_field_keys` to every existing claim | 4 cases across both §6.2 files |
| drop the species `raise` | the relative-declaration case |

## Gate (throwaway DB `clue_fi2_s3_t3`, dropped after)

- `ruff check` clean on all touched files; `ruff format --check` drift set is **byte-identical** to
  the `81fd5ab1` baseline (11 pre-existing files, none mine); `mypy` 583 files clean;
  `lint-imports` 25/25; `alembic heads` = one (`9398ae4467e3`).
- Touched suites (`tests/api/test_fi2_6*`, fresh-skip, R5, O2, S1, R6 launch, toolbelt wiring): green.
- `tests/api tests/integration tests/fleet tests/agents`: 1036 results, 2 failures — both
  pre-existing (below).
- **Full suite, my tree: 3917 results / 31 failures. Full suite, a clean `81fd5ab1` worktree on its
  own fresh DB: 31 failures.** The two sets differ by exactly two items:
  - baseline-only: `test_fi2_63b_the_legacy_toolbelt_path_keeps_its_precondition_failure` — the
    broken WIP test, **fixed by this session**;
  - mine-only: `tests/test_workspace_rename_guard.py::test_no_tenant_id_or_client_id_tokens_remain`
    — fails on untracked local `subsystems/clue-design/.context/attachments/…` files absent from the
    fresh baseline worktree. Documented in the Task-1 note; the known clue-design guard-exclusion
    follow-up, not this change.
- Everything else is the documented shared-DB pollution class. Notable members, all identical in
  both runs: `tests/db/test_db_migrations.py` (3), `tests/discovery_scoring/*` (11),
  `tests/sources/test_waterfall.py` (7), `tests/durable/test_account_run_db.py` (2),
  `tests/clue_obs/test_logging_discipline.py`, and
  `tests/api/test_agent_registry_wiring.py::test_resolved_snapshot_materializes_through_c61_backend`
  (fails in isolation too — `WorkspaceSecurityError: workspace parent directory does not exist`,
  environmental).
  `tests/fleet/test_b4_composed_run_db.py::test_composed_worker_drives_to_human_checkpoint_then_deep_quarantines`
  passes in isolation — the load-sensitive 30s-lease flake Task 2 recorded.

## Follow-ups / handoff to Task 4

- **Task 4 (canonical economics fixture) can rely on:** the borrowed set is one function,
  `clue_api.account_entity_research.born_complete_account_field_keys`; an all-borrowed account-axis
  produces reason code `exa_deep_all_fields_already_known` with **no** `external_research_operation`
  row; skips are audited as `<field>:existing_claim_fresh` on `AccountResolverBindings.audit_refs`
  on **every** return path; the R5 guard refuses re-buying a borrowed field.
- **Task 4 must NOT expect the launch estimate to shrink.** Assert the gross figure and read the
  saving off spend/coverage, per the decision above.
- The two negative §6.2 cases (stale / evidence-less) are *deliberately* pass-both-ways mutation
  guards, not red-first tests.
- Founder-facing: re-scope spec §11 open item 3 (estimate netting) as described above.
- Unchanged from Task 2: the prompt amendment for the all-borrowed close, and the
  `field_species` relocation from `clue_api.frontend_read.account_detail` to
  `claimstore.registry` (Task-4 close-out) — `sumble_account_gaps` now imports it from the
  frontend-read module too, so the relocation has one more call site.
