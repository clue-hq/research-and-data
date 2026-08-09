# 2026-08-08 — FI-2 slice 3, Task 4: the canonical economics fixture + slice close-out

Branch `platform/frontend-integration`, base `14c0c380`. Spec `docs/specs/FI-2-workspace-account-layer.md`
§9 slice-3 AC (+ §6); plan `docs/specs/FI-2-slice3-implementation-plan.md` Task 4. **No migration** —
single alembic head `9398ae4467e3`, unchanged.

Commits:

- `5db3cfe8` — the canonical economics fixture (`tests/integration/test_fi2_slice3_economics.py`, 6 cases)
- `7f5b5bcf` — relocate `field_species` to `claimstore.registry` + the third fail-closed species default

## 4a — what the fixture proves, clause by clause

One workspace, one account (`Cascade Gastroenterology Associates`), two projects. **P2** is the A1
trial fixture's project (`clue_api.trial.account_deep_fixture` — real project run, real
human-confirmed directive, real selected tier); **P1** is a second real `project` row whose earlier
research is on file as claims attributed through `run_lineage`. Both hold a `project_account`
membership, so "two projects, one account" is true at every layer the read surface uses.

| §9 AC clause | Test | Asserted through |
| --- | --- | --- |
| P2 spends **zero** on fresh neutral fields; ledger cites P1's claims | `..._p2_spends_zero_on_the_fresh_neutral_facts_p1_already_bought` | coverage `skipped_field_reasons` = `{f}:existing_claim_fresh` for all 4; coverage `claim_refs` = P1's exact claim ids; **both** operation ledgers empty; zero Exa HTTP; job spend = 1.25 (the committee call alone) |
| P2 **fully researches** relative fields | `..._p2_researches_the_project_relative_field_p1_already_answered` | species read back through `resolve_research_scope` over the effective registry; the field is absent from `born_complete_account_field_keys` while P1's claim is *fresh*; one `sumble_jobs` operation naming exactly that field; two live claims, one per lens |
| P1's lens is **untouched** | `..._p1s_lens_is_untouched_by_p2s_research_tier_and_narrative` | P2 researches **and then re-tiers and re-positions** the same account/ICP/persona; P1's tier, `account.value_narrative` and `account.scoring.fit` are byte-identical and still live under the `project_run_ids` lineage predicate; `read_account_detail` gives each project its own section |
| A stale neutral fact is refreshed **once**, both lenses see it | `..._a_stale_neutral_fact_is_refreshed_once_and_serves_both_lenses` | two expired facts ⇒ exactly two operations (`exa_deep`→pain, `sumble_jobs`→moves) and nothing for the two still-fresh fields; the structured refresh becomes the merge winner (`fresh`, new claim id, new value) and is served from `detail.neutral_facts`, which is unpartitioned by project |
| The **R5 guard** refusals | `..._the_live_guard_refuses_a_re_buy_and_an_empty_bundle` | taken against the *composed run's own* `definition.context`: borrowed-field re-buy and empty `field_keys`, both `AccountResearchAuthorityError` (repairable, not suspending) |
| Launch estimate stays **gross** | `..._the_launch_estimate_stays_gross_on_an_already_answered_account` | the real `AccountResearchFleetLauncher` on the two-project fixture: a netted `expected_estimated_cost_cents` is refused, the gross one launches, `spent_cents == 0` |

### Composition choices worth knowing

- **The live route only.** Per the Task-3 handoff, nothing here asserts
  `exa_deep_all_fields_already_known` or `AccountResolverBindings.audit_refs`: that provider
  (`ExaDeepAccountResolverProvider`) is on the M8D R1 quarantine list and has no production caller.
  The three surfaces asserted are the R5 guard, the coverage ledger, and the operation ledgers.
- **Both operation ledgers are checked, and both discriminate.** `entity_research_provider_operation`
  is the composed reservation every action writes (with `field_keys`); `external_research_operation`
  is the `ExaDeepAcquisitionCoordinator`'s. The fixture wires the **production**
  `ExaAccountSemanticResearchAction` (real coordinator, recorded response over a fake transport) for
  `research_account_deep`, so the Exa ledger genuinely fills (clause 4 asserts `== 1`) and the
  `== 0` assertions elsewhere are not vacuous.
- `_run_p2` stands in for the one production mint site it bypasses: it launches the envelope
  directly (as every M8D runtime suite does) and then `record_run_lineage`s the research run exactly
  as `AccountResearchFleetLauncher` does inside its launch transaction. Without it the lens
  predicate has nothing to join P2's own claims on.
- The relative field is `account.project_angle`, **declared** `PROJECT_RELATIVE` via `register_field`
  and threaded into the fixture's deep ICP (`deep_field_keys=(*DEEP_FIELD_KEYS, _ANGLE)`) so a
  human-confirmed directive may legitimately ask for it. `account.scoring.fit` (relative by the
  ratified `account.scoring.*` key rule) is P1's *score* in clause 3. Both species arms exercised;
  neither hardcoded.
- P1's claims are `sumble_jobs`-sourced (the Task-3 fixture gotcha: an `exa_deep` claim needs full
  operation/snapshot/artifact lineage, which a DB trigger enforces).
- The recorded Exa response only carries `account.operational_pain` and `account.strategic_moves`;
  a narrowed bundle must narrow its **grounding** with it (`_RecordingExaTransport` does, off the
  compiled `output_schema`, so "one refresh bought one field" is the wire truth).
- `tests/api/test_account_entity_research_r5_db._FixtureAccountProviders` gained an **additive**
  `field_values` kwarg (defaults preserved, existing callers byte-identical) so a suite can research
  a field the double does not already answer without copying 60 lines of claim/artifact plumbing.

### Discrimination evidence (each load-bearing clause spot-mutated, then reverted)

| Mutation | Caught by |
| --- | --- |
| `AccountExistingClaimProjection.born_complete` ⇒ `False` (nothing is borrowable) | 5 of 6 cases |
| `born_complete` drops the freshness check (a stale claim counts as fresh) | **1** case, exactly: the refresh-once case |
| `project_supersedable` ⇒ always `True` (pre-§6.4 cross-project destruction) | **1** case, exactly: the lens case (P1's tier vanishes) |
| R5 guard: `already_known = fields & borrowed` ⇒ `frozenset()` | **1** case, exactly: the guard case |
| R5 guard: `if not fields:` ⇒ `if False:` | **1** case, exactly: the guard case |
| launcher: `estimated_cost += budget_cap_cents` ⇒ `+= 0` (a netted estimate) | **1** case, exactly: the gross-estimate case |

## 4b — the relocation + the third fail-closed default

`field_species` moved from `clue_api.frontend_read.account_detail` to
`clue_research.claimstore.registry`, beside `list_effective_fields`, and is exported from
`clue_research.claimstore`. Pure relocation — same body, same behaviour; `account_detail` imports it
back, so nothing it serves changes. Call sites updated: `account_entity_research` (×2 uses, 1
import), `sumble_account_gaps`, `frontend_read.account_detail`, and
`tests/api/test_fi2_63_sumble_freshness_db.py`. Motivation: with the third call site, two
**research-path** modules were importing a FastAPI **BFF** module. `lint-imports` **25/25**.

Third species default harmonized: the finalization engine's `relative_borrowed`
(`account_entity_research.py`) defaulted an unresolvable species to `PROJECT_NEUTRAL` — failing
*open* (another project's claim could close a field whose species we cannot determine) — while the
§6.1 state read and the §6.3 Sumble ladder had already been flipped. Now `PROJECT_RELATIVE`, with
the same rationale comment. All three are unreachable today (`field_species` answers for every
declared field), so there is no mutation evidence; consistency is the point.

## 4c — gate

Throwaway DBs on 127.0.0.1:5432 (`clue_fi2_s3_t4`, `_gate`, `_wide`, `clue_t4_probe{,2,3}`), each
created and migrated per run. `alembic heads` = one (`9398ae4467e3`); **Task 4 added no migration**.

- `tests/integration` **alone on a fresh DB**: 21 passed.
- Touched suites (`test_fi2_62_*`, `test_fi2_63_sumble_freshness_db`, fresh-skip, R5, Sumble S1,
  toolbelt wiring): 46 passed.
- Slice-1 read layer (`tests/api -k frontend_read`): 102 passed.
- `tests/db`: 12 passed.
- Wide run on its own fresh DB (`tests/api tests/agents tests/fleet tests/claimstore
  tests/integration`): **2 failures, both pre-existing and re-confirmed by isolation** —
  `test_agent_registry_wiring::test_resolved_snapshot_materializes_through_c61_backend`
  (environmental `WorkspaceSecurityError: workspace parent directory does not exist`; fails in
  isolation too) and
  `test_b4_composed_run_db::test_composed_worker_drives_to_human_checkpoint_then_deep_quarantines`
  (the load-sensitive 30s-lease flake; **passes** in isolation, verified).
- `tests/narrative tests/discovery_scoring tests/api/deep` on the already-used `_gate` DB showed 2
  `tests/discovery_scoring/test_phase.py` failures — the **documented shared-DB pollution class**
  (`tests/discovery_scoring/*` is a named member). Proven not mine: on a virgin DB, both
  `tests/integration → tests/discovery_scoring` and `tests/db → tests/discovery_scoring` are fully
  green.
- `tests/test_workspace_rename_guard.py::test_no_tenant_id_or_client_id_tokens_remain` fails on
  untracked local `subsystems/clue-design/.context/attachments/…` files (verified in the failure
  output) — the known clue-design guard-exclusion follow-up, recorded since Task 1.
- `mypy` **583 files clean**; `ruff check` clean repo-wide; `ruff format --check` drift = **10
  files, byte-identical to the `14c0c380` baseline** (verified by stashing) — the M8C/M8D-era
  files, none touched here, deliberately not reformatted; `lint-imports` **25/25**.

Note: tests are outside the `mypy` files list (`pyproject.toml [tool.mypy] files`), so the new test
module is not type-gated; it is `ruff`-clean and follows the existing suites' typing conventions
(the `_FakeGateway` protocol mismatch is the same shape `tests/narrative/test_positioner.py` has).

## Founder-facing close-out list (whole slice)

1. **Re-scope spec §11 open item 3 (launch-estimate netting) — now with the committee-spend
   argument.** Task 3 argued netting is wrong today for four reasons (per-account cap with no
   per-field decomposition; the same figure is each job's own spend authority; the estimate is a
   caller-supplied input with no server-side proposal surface; a recomputed netted figure diverges
   on replay). Task 4 adds a fifth, and it is the empirical one: **a wholly borrowed account still
   spends.** The fixture's clause-1 job settles at 1.25 with *every* account field borrowed — the
   committee call is never skippable (it buys people, not fields). So a netted estimate of "the
   account axis is free" would be *wrong*, not merely conservative. The honest re-scope is: build an
   estimate **proposal** surface, net on both sides (proposal *and* per-job cap), and model the
   non-skippable committee leg — not "net the launcher".
2. **The §6.2 bundle-shrink clause is a phantom on the production path — decide how the spec should
   read.** §6.2 assigns the no-respend invariant to `exa_deep_preparation.py` ("excludes
   born-complete fields from the bundle; an empty account-axis bundle reserves nothing"). That code
   is real and tested, but its only builder is on the M8D R1 quarantine list with zero non-test
   callers, so it never runs in a composed run. What actually upholds the invariant live is the
   **R5 guard** (`AccountResearchExecutionGuard.authorize_tool`). Recommend amending §6.2 to name
   the guard as the enforcement point and mark the bundle compiler as quarantined-path-only, so the
   spec stops describing a path that does not execute. (Nothing is broken; the risk is a future
   reader trusting the wrong sentence.)
3. **Entity-research prompt amendment for the all-borrowed close (queued from Task 2, still open).**
   The governed account prompt (`account/v1/prompt.md:28-30`) allows only *retained result refs* as
   buying-unit evidence. A wholly borrowed account has no result of its own, so a prompt-obedient
   agent closes with zero results and an honestly unresearched committee (`NEEDS_REVIEW` +
   `committee_not_researched`). Production's Sumble scope validation already admits a `claim:`
   reference belonging to the account; sanctioning that in the prompt rides the next governed C6
   prompt bump. Until then the *completed* outcome on an all-borrowed account is only reachable by
   citing a claim the prompt does not sanction.
4. **New from Task 4 — an Exa-sourced refresh is bought and written but not yet *served*.** A tier-4
   synthesized claim is born `verification_status='unverified'`, and the merge withholds an
   unverified tier-4 claim by design. The M8D research job does not run verification: that is the
   separate VERIFICATION phase, which **no composed run currently reaches** (the M8D R11 DEEP-phase
   bridge, already on the repo backlog). Consequence for §6.1's economics: money spent refreshing an
   expired *qualitative* (Exa) fact does not move the account's current value until the bridge
   lands, so the same field stays stale to the fresh-skip and can be re-bought on the next run.
   Structured (tier ≤2) refreshes are unaffected. The fixture pins **both halves** of this, so the
   test will speak up the day the bridge changes it. Recommend tracking it as an explicit
   dependency of §6.1 rather than leaving it implicit in the R11 spec.

## Open / for the whole-slice reviewer

- The economics fixture is built on the **A1 trial fixture** (`seed_insight_health_account_deep_fixture`)
  rather than on slice 0's discovery+import canonical fixture
  (`tests/integration/test_fi2_slice0_two_projects.py`). Deliberate: the composed M8D run needs a
  real project run, a human-confirmed directive and a human-approved selected tier, all of which the
  A1 fixture already builds, and the launcher clause needs the same. The "two projects" half is real
  (a second seeded `project` row, its own memberships, its own lineage-attributed research). If the
  reviewer would rather the §10 canonical fixture be *the* substrate here, that is a rebuild of the
  A1 preconditions on the slice-0 fixture, not a small edit.
- `_FixtureAccountProviders.field_values` is the one change to an existing test-support class.
  Additive and default-preserving; `tests/api/test_account_entity_research_r5_db.py` and the
  fresh-skip suite were re-run green before and after.
- The `_gate`-DB `tests/discovery_scoring/test_phase.py` failures are the documented shared-DB class,
  proven by two virgin-DB control runs; if the reviewer wants that class properly fixed it is a
  separate piece of work (it predates FI-2).
