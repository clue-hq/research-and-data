# The committee axis settles when the provider has no such organization (2026-08-20/21)

Follow-on to `_memory/2026-08-20-seven-fix-night-close-out.md`. Not committed — orchestrator
reviews and commits.

## The live failure

Run `dc86340f`, 2026-08-20 21:36:47 IST, account "Greater Chicago Specialty Physicians LLC".
`discover_buying_committee` composed correctly (input validation passed after `8f6af4d5`) and died
inside committee input resolution:

```
SumbleCommitteePreparationError: Sumble organization snapshot has no exact matched organization
→ execution_failed → job requeued (worker_error:SumbleCommitteePreparationError)
```

Sumble's organization index has no exact match for a small Chicago physician group. World fact
about provider data, same species as the 402 that already folds terminally.

## Classification of every `SumbleCommitteePreparationError` raise site

`platform/api/clue_api/sumble_committee_inputs.py::DurableSumbleCommitteeInputResolver.resolve`
(14 sites): 12 are authority/integrity and keep suspending; 2 are world facts and now refuse
recoverably —

- L~300 `ready Sumble organization identity is absent…` → `committee_provider_identity_absent`
- L~333 `…has no exact matched organization` → `committee_provider_organization_unmatched`

`sumble_committee_preparation.py::SumbleCommitteePreparer` (8 sites): all authority/integrity,
unchanged. That DEEP-path preparer is not the M8D tool path; it keeps suspending on everything,
including the two new world facts, because the new class is a **subclass** of
`SumbleCommitteePreparationError` (no `except` clause anywhere changes behaviour).

Deliberately NOT converted: `"Sumble organization snapshot is malformed"` — the artifact is
digest-verified, so a non-object payload is a truth violation. Also unconverted (and still
suspending, correctly): `SumbleSchemaDrift` from `matched_organization_id` when the provider
reports `matched_count >= 1` with no identifiable row — a *charged* match we cannot identify.

## Terminal disposition mechanism (the interesting decision)

The refusal happens **before any provider operation row exists** — nothing reserved, dispatched or
charged — so there is nothing to `settle_terminal`/fold, and stamping a `dispatched_at` to reuse
the fold machinery would fabricate an attempt the provider never received (exactly what the
settlement contract refuses).

Chosen: a new append-only ledger `entity_research_account_committee_unavailable`
(migration `612428f3731f`), one row per *journalled* committee tool request that the engine refused
on a durable world fact — `(tool_request_id PK, research_run_id, job_id, workspace_id,
account_entity_id, source_keys, reason_code, detail)`. Unfabricatable (the tool_request row only
exists because the agent really made the call under this job's authority), idempotent on replay
(`ON CONFLICT DO NOTHING`), zero cost, no operation invented.

`read_account_research_execution_completeness` unions its source keys into
`terminal_committee_source_keys` (new helpers `committee_axis_unavailable_source_keys` /
`…_reasons`), so `assess_account_coverage` and `finalize_account_research` — which share that
reader — both close. A real committee *result* still takes precedence
(`committee_result_exists` short-circuits), so recording terminal can only unblock closure, never
foreclose a better outcome if the agent later enriches and re-attempts.

Coverage: `_committee_coverage_status` now reports the world-fact reason codes as the review flags
instead of the mute `committee_not_researched`, so a review item names *why*.

## Files

- `alembic/versions/612428f3731f_committee_axis_provider_unavailable.py` (new)
- `platform/api/clue_api/sumble_committee_preparation.py` — `SumbleCommitteeProviderIdentityUnavailable` + the two reason-code constants
- `platform/api/clue_api/sumble_committee_inputs.py` — two raise sites re-typed
- `platform/api/clue_api/sumble_entity_research_tools.py` — `execute` converts *that class only*; `_record_committee_axis_unavailable`; `_committee_unavailable_detail` (names the next call, per the loop rule)
- `platform/api/clue_api/account_entity_research.py` — the two readers, the union, the coverage flag
- `platform/agents/catalog/entity-research/account/v3/manual.md` + `tests/api/test_entity_research_cutover_r10.py` — the two refusal codes
- `tests/api/test_committee_provider_unmatched_organization_db.py` (new, 7 tests)

## Red-proofs (all re-run by reverting production code, then restored)

1. revert the resolver typing → the real-durable-chain resolver test fails
2. revert the `execute` conversion → 4 tests fail (refusal, sibling reason code, terminal axis, e2e settle)
3. revert the completeness union → 2 fail (terminal axis, e2e settle)
4. revert the coverage reason wiring → the e2e settle test fails

## Verification

`tests/api/test_committee_provider_unmatched_organization_db.py` 7 passed; regression suites
green (`test_committee_scope_engine_composition_db`, `test_committee_provider_returned_floor_db`,
`test_committee_agent_inference_acceptance_db`, `test_account_entity_research_r5_db`,
`test_comprehensive_account_execution_db`, `test_entity_research_cutover_r10`,
`test_account_entity_research_fresh_skip_db`, `test_sumble_committee_preparation_o2`,
`test_account_deep_launch_o2`, `tests/agents`, plus `tests/api -k "committee or sumble or coverage
or account_entity or entity_research"`). ruff format/check clean, mypy 733 files clean,
lint-imports 26/26. Migration up→down→base→up on a throwaway DB, single head `612428f3731f`.

## Noticed, not fixed

- `matched_organization_id` can raise `SumbleSchemaDrift` straight out of the resolver — a *raw*
  escape today, so it suspends. That is the correct disposition (charged-but-unidentifiable match
  is a truth failure), but it escapes untyped rather than through a governed species. Worth
  re-typing to an explicit truth species one day for symmetry.
- `committee_provider_identity_absent` is recorded terminal like its sibling. If the job still has
  an admitted Sumble structured field, `enrich_account` could establish the identity and a later
  committee call would supersede the gap — the refusal detail says so. Accepted risk of closing
  slightly early; strictly better than today's job death, and never a wedge.
