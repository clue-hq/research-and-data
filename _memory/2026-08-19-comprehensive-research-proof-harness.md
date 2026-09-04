# Comprehensive account-research proof harness — 2026-08-19

Follows `2026-08-19-comprehensive-research-integrity-settlement-repair.md` and
`2026-08-19-exa-reserve-without-dispatch-settlement.md`. Branch
`platform/comprehensive-account-contact-research`. **Uncommitted; three new test files only. No
production code was changed.**

## What was built

The founder's ratified success criterion made mechanical — five Accounts end to end, three times
consecutively, with zero manual database intervention — with fake provider transports.

- `tests/integration/test_comprehensive_research_harness_db.py` — the harness.
- `tests/integration/comprehensive_harness_support.py` — per-cycle seeding: a **fresh project run
  with its own sealed generation-1 discovery batch holding five accounts**, plus one human-confirmed
  21-field comprehensive directive over all five. The A1 fixture is reused for Stage-0/ICP/readiness
  only; it cannot itself hold five accounts (module-constant batch/plan/item ids, and its sealed
  reader asserts exactly one account). A fresh run per cycle is forced by the substrate:
  `create_discovery_batch` refuses to replace a sealed generation.
- `tests/integration/comprehensive_harness_providers.py` — the provider doubles. All three shipped
  clients already expose an injectable I/O seam (`ExaDeepHttpAcquisitionTransport`; `SumbleClient`
  and `SumbleV9CommitteeClient` both take `http`), so the harness rebinds exactly those three
  constructor names for the duration of one driven job and nothing else.

Execution runs through the production composition: `build_account_research_fleet_composition` over
`ProductionAccountResearchProviderActions`, driven via the real fleet task/lease substrate and the
real `AccountResearchFleetWorkHandler`. Only the LLM (scripted `BaseChatModel`) and the three
provider sockets are doubles; the committee lane needs no gateway at all (`agent_deferred` roles).

Run: `CLUE_DATABASE_URL=…/clue_harness_checks uv run pytest
tests/integration/test_comprehensive_research_harness_db.py -q`. ~17 s, ruff + mypy clean.

## Result

Three identical green cycles. Per account, every cycle: `state=terminal`, outcome `needs_review`,
21/21 coverage rows closed, committee axis terminal, zero pending provider operations, non-zero
spend. Adversity settles honestly: a truncated Exa bundle (`sierra`) leaves its three rows as
`not_researched` gaps with terminal `(field, exa_deep)` attempts; a Sumble Jobs HTTP 422
(`willamette`) settles `account.hiring_velocity_eng` as a terminal attempt and reaches the agent as
a governed `provider_rejected` refusal; an empty Sumble committee (`front-range`) records
`confirmed_empty_discovery` and coverage `committee_status=complete`.

## Production defect found — NOT fixed here

**Exa Deep's atomic budget reservation is sized from the wrong bound, so a comprehensive account
deterministically suspends.**

- `ProductionAccountResearchProviderActions.resolve` reserves
  `exa_deep.cost_cents * ceil(len(exa_fields) / EXA_OUTPUT_MAX_FIELDS)` for the whole
  `research_account_deep` call (`platform/api/clue_api/entity_research_provider_wiring.py`,
  `_source_reservation` + the `exa_reserve` / `cost_cents_reserved_per_bundle` computation),
  i.e. it assumes the plan splits only on Exa's 8-alias cap.
- `compile_exa_deep_acquisition_plan` (`platform/api/clue_api/exa_deep_acquisition.py:969-998`)
  splits whenever `compile_exa_deep_request` raises, and
  `validate_exa_output_schema` also caps **total nested properties at
  `EXA_OUTPUT_MAX_PROPERTIES = 10`**
  (`subsystems/research/clue_research/resolvers/exa/deep_contract.py:350`). Several §3.1 rows are
  object-valued, so the 12 outstanding Exa-owned rows really compile into **4** bundles, not 2.
- Consequence: reserved 20c, settled 4 × 7c = 28c, and
  `DbEntityResearchToolBatchCoordinator.completed`
  (`platform/api/clue_api/entity_research_parallel.py:377-381`) raises
  `EntityResearchParallelAdmissionError: settled provider cost exceeds its atomic reservation`.
  `AccountResearchFleetWorkHandler.handle` (`account_research_fleet.py:1429-1439`) converts it to
  `supervisor_suspended` — deterministic on replay, so the account never settles.
- Pinned by `test_the_comprehensive_exa_reservation_under_reserves_its_own_bundle_plan`, which
  fails the moment the reservation is sized from the real plan (the intended fix).
- The main harness therefore prices its fake bundles at 1c (`HARNESS_BUNDLE_COST_DOLLARS`), a
  legitimate provider price inside the declared per-call budget, so the rest of the pipeline stays
  provable while the defect is owned elsewhere.

## Notes and residuals

- `account.total_funding` settles `unsupported:unsupported_grounding` on every account. This is
  correct honest-gap behaviour for a synthetic scalar the retained passage does not support, not a
  defect — but it means the harness has a fifth, unplanned honest-gap case.
- The recorded v9 people/teams fixtures are personalized per account. Reusing them verbatim makes
  one contact entity (LinkedIn URL is the workspace-scoped strong key) hold contradictory immutable
  professional facts, and the committee worker correctly raises `ProfessionalFactReplayConflict`.
- Provider request/operation ids carry a per-cycle token: `committee_acquisition_snapshot` has
  `UNIQUE NULLS NOT DISTINCT (source_key, provider_operation_id)` and account-gap replay re-checks
  the stored provider request id.
- Consecutive cycles must chain directives (`predecessor_id`); the second draft is otherwise refused
  with `successor must name the latest directive version`.
- Committee `committee_status` is `needs_review` (not `complete`) on productive accounts because the
  Teams-sourced candidate is counted ambiguous. Quality signal, not an execution blocker.
- Verified on the throwaway DB `clue_harness_checks` (created here, still present; drop with
  `DROP DATABASE clue_harness_checks`). Tunis untouched; no service restarts; no live DB mutated.
