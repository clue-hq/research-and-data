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
| `exa_deep_preparation` — borrowed-set exclusion from the bundle + `exa_deep_all_fields_already_known` reason code | **KEPT**, proven by new tests; **FIXED** the `WAITING_EXTERNAL`/`FAILED_EXTERNAL` early returns, which dropped the `<field>:existing_claim_fresh` skip refs. *Correction (fix round):* this is **not** "every return path". The two in-loop `REQUIRED_MISSING` returns (`exa_deep_effective_source_plan_missing`, `exa_deep_effective_field_schema_missing` — `exa_deep_preparation.py:173-177,188-192`) still return `bindings={}` with no `audit_refs`, so on those two paths the skips are dropped. They are hard-failure paths where the audit trail was judged not worth the churn, not an oversight the tests cover |
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
4. (New) A launch-time freshness probe is a *prediction*, and netting it breaks replay. Precisely
   (corrected in the fix round — the first wording named the wrong mechanism): the
   **caller-supplied** `expected_estimated_cost_cents` *already* enters `request_sha`
   (`account_research_fleet_launch.py:402`), so the launch identity is stable under replay. The
   hazard is the *other* side: a server-recomputed **netted** figure is computed fresh on every
   call, so when a borrowed claim expires between launch and replay the recomputed number no
   longer equals the caller's stored one and the `:260` equality check rejects a legitimate
   idempotent replay. It is replay-divergence against a stable identity, not identity poisoning.
   (The in-code comment at `account_research_fleet_launch.py:250-253` still carries the first
   wording. It reaches the right conclusion — a legitimate replay turning into a conflict — so it
   was left alone rather than widened beyond the ruled fix set; correct it in passing.)

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
directly, proving §6.3(b) left it raising `PreconditionFailed('sumble_account_gap_ineligible')`.
(*Fix round correction:* the tool object is **not** what an exact replay resolves —
`ReplayOnlyEntityResearchTool.invoke` raises unconditionally and never delegates to the wrapped
tool; replay is served from the idempotency cache above it. The direct invocation is still worth
pinning, as what the address resolves to when the quarantine lifts and what any non-registry caller
holds.)

## Tests added / completed

- `tests/api/test_fi2_62_bundle_shrink_db.py` (4) — borrowed field excluded from the Exa output
  schema *and* its directional question dropped; all-borrowed axis ⇒ `NOT_APPLICABLE` +
  `exa_deep_all_fields_already_known` + zero `external_research_operation` rows + zero HTTP;
  parametrised negative (stale claim / evidence-less claim ⇒ field stays in the bundle).
- `tests/api/test_fi2_62_first_call_authority_db.py` (4, was 3) — prompt-obedient omission of
  borrowed fields authorized; lazy omission of an unresearched primary field still refused (and the
  honest first call authorized); re-buy of a borrowed field refused; **fix round:** an empty
  `field_keys` call refused repairably.
- `tests/api/test_fi2_62_launch_estimate_db.py` (1) — gross-estimate contract pin.
- `tests/api/test_fi2_63_sumble_freshness_db.py` (8, was 5-and-broken) — premise, stale⇒eligible,
  fresh⇒refused, M8D governed skip, legacy path, relative-declaration refusal at the preflight;
  **fix round:** job-authority loss propagates, mis-declaration propagates (neither is a governed
  skip).

Test-fixture notes for successors: an `exa_deep`-sourced claim needs full
operation/snapshot/artifact lineage (DB trigger) — use `sumble_jobs` for a synthetic "already known"
claim; and a narrowed Exa response payload must have its **grounding narrowed with it** (the
provider contract refuses grounding naming a field the content lacks).

## Mutation evidence (each load-bearing behaviour)

| Mutation | Caught by |
| --- | --- |
| revert `exa_deep_preparation.py` to pre-WIP | 2 of 4 bundle cases |
| revert `sumble_account_gaps.py` to pre-WIP | **5** of the Sumble cases (the note first said 3; corrected in the fix round). Note this mutation is no longer runnable as a whole-file revert: `sumble_entity_research_tools` now imports `SumbleAccountGapNotEligible` from it, so the revert fails at import. Use the two behaviour mutations below instead |
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

## Fix round (review verdict APPROVE-WITH-FIXES, applied same day)

An independent review of `c81c7cba..67cea2c9` returned APPROVE-WITH-FIXES. Two behaviour fixes plus
three comment/doc corrections, applied in two commits (`72f800d6`, `e232aa5d`) and this amendment.

**I-2 — an empty `field_keys` Exa call could wedge a job (the highest-stakes finding).** Task 3's
`primary - borrowed` relaxation left a wholly-borrowed account with `primary == ∅`, and a
zero-field `research_account_deep` call then cleared authority:
`EntityResearchSemanticToolInput.field_keys` has no `min_length`, and `record`'s field/source
pairing check is itself guarded by `if semantic.field_keys and (...)`. The call reached
`ExaDeepSemanticAccountResearchAction.execute`, whose `or not request.field_keys` raises
`EntityResearchResultIntegrityError` — the **suspending** species under R10. Before the relaxation
the first-call rule refused the same call *repairably*. The guard now refuses an empty
`research_account_deep` as `AccountResearchAuthorityError`. It refuses an empty *call*; it does not
require a call — a wholly-borrowed account still closes with zero research calls (Task 2's
zero-result close, unchanged and still green).

**I-3 — the §6.3(b) conversion was far too wide.** `sumble_entity_research_tools` wrapped the whole
`starter.start(...)` in `except SumbleAccountGapEligibilityError`, but that type is raised at ~20
sites in `compile_sumble_account_gap_preflight`, including job-authority loss (`:319`),
discovery-seal conflict (`:330`), account-not-in-seal (`:334`), non-canonical account (`:339`) and
Task 3's own species guard — all previously **suspending**, and none of them repairable by the
agent. (The species guard's comment claimed a "loud refusal at the boundary" it was no longer
getting.) Narrowed: a new `SumbleAccountGapNotEligible` subclass names the eligibility **ladder**
refusal only (the fresh + confident + conflict-free skip — the actual §6.3(b) target), and only
that subclass converts to `EntityResearchGovernedRejection`. Everything else propagates and
suspends, as before Task 3. The legacy toolbelt path still catches the whole family for its
`PreconditionFailed` — unchanged, and it inherits the subclass for free.

Minor, ruled in: the R5 guard's "one snapshot" comment now says *one transaction* (`clue_db.transaction`
is READ COMMITTED; `repeatable_read_transaction` exists and is deliberately unused here); the
legacy-path test docstring no longer claims `ReplayOnlyEntityResearchTool` serves replay (its
`invoke` raises unconditionally and never delegates — the idempotency cache above it is the replay
path); and both fresh-skip species lookups default to `PROJECT_RELATIVE` (⇒ never skippable)
instead of `PROJECT_NEUTRAL`. The species default is unreachable today (`field_species` answers for
every declared field) — it is a fail-closed default, with no mutation evidence because there is no
way to reach it.

Fix-round mutation evidence (throwaway DB `clue_fi2_s3_t3_fix2`):

| Mutation | Caught by |
| --- | --- |
| delete the empty-`field_keys` refusal (`if not fields:` ⇒ `if False:`) | 1 case, exactly (`…_an_empty_exa_bundle_is_refused_repairably`); the other 6 §6.2 cases stay green, so the guard is narrow |
| widen the M8D `except` back to `SumbleAccountGapEligibilityError` | exactly the 2 new narrowing cases (authority loss, mis-declaration); the governed-skip case stays green, so the ladder path is untouched |

Fix-round gate: `tests/api tests/agents tests/fleet` on a fresh throwaway DB (`clue_fi2_s3_t3_fix`)
— 2 failures, both the documented pre-existing pair, re-confirmed by isolation:
`test_agent_registry_wiring.py::test_resolved_snapshot_materializes_through_c61_backend`
(environmental `WorkspaceSecurityError`, fails in isolation too) and
`test_b4_composed_run_db.py::test_composed_worker_drives_to_human_checkpoint_then_deep_quarantines`
(the load-sensitive 30s-lease flake; **passes** in isolation). `mypy` 583 files clean,
`lint-imports` 25/25, `ruff check`/`format` clean on touched files.

## Follow-ups / handoff to Task 4

**Read this first — the original handoff pointed Task 4 at a quarantined code path.** The review
proved (and this note's first version missed) that *all* of Task 3's bundle-shrink code lives in
`ExaDeepAccountResolverProvider` (`exa_deep_preparation.py`), whose only builder,
`build_production_exa_deep_resolver_provider`, is on the M8D R1 quarantine's forbidden list at both
production roots (`test_m8d_r1_entity_research_quarantine.py::test_production_composition_does_not_reference_quarantined_collaborators`,
:80-99) and has **zero** non-test callers. So none of its artifacts — the
`exa_deep_all_fields_already_known` reason code, the `AccountResolverBindings.audit_refs` skip
refs — ever appear in a **composed** production run. `tests/api/test_fi2_62_bundle_shrink_db.py`
drives that provider directly and is a legitimate unit test of it; it is not evidence about a
composed run, and Task 4 must not read it as such.

**What actually upholds the §6.2 invariant on the live (composed) route** is the R5 guard, on the
M8D R6 fleet path: `AccountResearchExecutionGuard.authorize_tool` refuses any
`research_account_deep` naming a borrowed field ("cannot re-buy a field an existing fresh claim
already answers"), so the live Exa action is never asked for one and never reserves an operation
for one.

- **Task 4 (canonical economics fixture) must assert zero-spend through the LIVE route, i.e.:**
  1. the **R5 guard refusal** — a borrowed field in a `research_account_deep` call raises
     `AccountResearchAuthorityError` (and, since the fix round, an *empty* `field_keys` call raises
     it too, rather than reaching the provider and suspending the job);
  2. the **coverage ledger's `skipped_field_reasons`** — `<field>:existing_claim_fresh`, written at
     finalization by `account_entity_research.py:431` from `state.existing_claims`
     (`born_complete` ∧ completed ∧ not researched). This is the composed-run surface, and it is
     the one the money story reads;
  3. an **`external_research_operation` row count** for the account/run — zero rows for a borrowed
     field. On the live path those rows come from `ExaDeepAcquisitionCoordinator` as wired by
     `entity_research_provider_wiring.py`, so the count is a real composed-run assertion.
- **Task 4 must NOT assert** `exa_deep_all_fields_already_known`, `AccountResolverBindings.audit_refs`,
  or any other `ExaDeepAccountResolverProvider` artifact **in a composed run** — those are
  quarantined-path artifacts. (Asserting them in a direct-provider unit test is fine, and
  `test_fi2_62_bundle_shrink_db.py` already does.)
- The borrowed set is still one function —
  `clue_api.account_entity_research.born_complete_account_field_keys` — shared by the §6.1 state
  read, the R5 guard, and the (quarantined) bundle compiler. That DRY property is real on both
  routes.
- **Task 4 must NOT expect the launch estimate to shrink.** Assert the gross figure and read the
  saving off spend/coverage, per the decision above.
- The two negative §6.2 cases (stale / evidence-less) are *deliberately* pass-both-ways mutation
  guards, not red-first tests.
- Founder-facing: re-scope spec §11 open item 3 (estimate netting) as described above.
- Unchanged from Task 2: the prompt amendment for the all-borrowed close, and the
  `field_species` relocation from `clue_api.frontend_read.account_detail` to
  `claimstore.registry` (Task-4 close-out). It now has **three** call sites —
  `account_entity_research` (twice: the §6.1 state read and the finalization engine's
  `relative_borrowed` check) and `sumble_account_gaps` — plus the module's own internal use.
- Noticed while applying the fail-closed species defaults, **not** changed (outside the ruled fix
  set): the finalization engine's `relative_borrowed` derivation
  (`account_entity_research.py:~1344`) still defaults an unresolvable species to
  `PROJECT_NEUTRAL`, i.e. fails *open* there, while the §6.1 state read and the Sumble ladder now
  fail closed. Unreachable today for the same reason as the other two; harmonize it with the
  relocation.
