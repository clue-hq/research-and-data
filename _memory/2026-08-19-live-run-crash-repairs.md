# Three live-run crash repairs — 2026-08-19 (run `accdce64-de08-5e9f-953c-1eee0cfcabae`)

Follows `2026-08-19-exa-reserve-without-dispatch-settlement.md`. The first real live comprehensive
run crashed all five jobs. Three distinct defects, one class: a raw exception escaped where
governed handling belonged. No commit (orchestrator commits); no live-DB writes; services untouched.

## D1 — artifact anchor insert was not concurrency-safe (2 jobs, IntegrityError)

`libs/clue-storage/clue_storage/artifacts.py::record_artifact`. `ON CONFLICT (storage_key)` names
one arbiter index, but `artifact` also carries the composite unique constraint
`artifact_execution_anchor (storage_key, workspace_id)` — the FK target for every
`(artifact_key, workspace_id)` evidence citation. Postgres speculative insertion arbitrates only the
named index, so a writer whose arbiter probe found nothing and whose composite-index insert then
collided with a *concurrently committing* twin raised
`duplicate key … "artifact_execution_anchor"`. Trigger live: two **parallel `enrich_account` calls in
one model wave** (own connections) both resolved the same account's Sumble `/organizations`
document → byte-identical response → same content address.

Fix: run the upsert inside `conn.begin_nested()` and retry once on `IntegrityError`. By the time the
violation surfaces the winner's row is committed, so the retry resolves through the arbiter and
keeps the resurrect + row-lock (DSAR erase/purge serialization) guarantees unchanged. Reproduced
exactly with 12 barrier-synchronised writers (legacy: 1–11 of 12 failed per round; fixed: 0/12 over
6 rounds). Regression: `tests/storage/test_artifacts_db.py::
test_concurrent_writers_of_identical_bytes_all_record_one_row` (red 3/3 with the fix removed).

## D2 — a `None` finalization proposal crashed pydantic (2 executions, ValidationError)

`platform/agents/clue_agents/entity_research_runtime.py`. A model turn that burned its whole 16 384
output-token budget on reasoning returned an `AIMessage` with no tool call and no structured output,
so the graph ended with no `structured_response` and `run()` called
`ResearchFinalizationProposal.model_validate(None)`.

Fix, two parts: (1) new `aafter_model` hook (`can_jump_to=["model"]`) refuses an empty turn back to
the model as the ordinary `EntityResearchGovernedToolRefusal` (`code="empty_model_turn"`) and jumps
to the model, bounded by module constant `_MAX_EMPTY_TURN_REPAIRS = 3`; the refusal is durable
without a new journal kind because it rides the message history the next `model_started` records.
(2) exhausted repairs now raise the typed `EntityResearchFinalizationRejected`, never a raw
`ValidationError`. Regressions in `tests/agents/test_entity_research_runtime_r3.py` (both red
without the fix, with the exact live pydantic error).

## D3 — over-long `research_intent` raised a bare `ValueError` (1 job)

The follow-up `research_account_deep` path in
`platform/api/clue_api/exa_entity_research_tools.py::ExaAccountSemanticResearchAction.execute`
appends the model's `follow_up_reason` and the prior result context to the planning sentence; that
overflowed the resolver's 1000-character cap and `compile_exa_deep_request` raised a bare
`ValueError` through the tool, failing the execution.

Fix: the resolver raises the new typed `ExaDeepRequestBoundExceeded(ValueError)` (still a
`ValueError`, so `pack_exa_deep_field_bundles`' greedy split is unchanged); the action converts it
into `EntityResearchGovernedRejection("research_request_shape_rejected", …)`. Nothing is reserved or
dispatched before the refusal. Regressions in `tests/resolvers/test_exa_deep_wire_e0.py` and
`tests/api/test_comprehensive_account_execution_db.py`.

## Live proof that the new settlement machinery works (F1/F4)

* F1 — `sumble-account-operation:f5e26e3e-…` (`sumble_tech_stack`, `{core.primary_tech_stack}`,
  job `0589f9e5-…`): `reserved_at 20:01:11.593788`, `dispatched_at 20:01:11.618816`, **no result
  row**, settlement fold `0.000000` at `20:01:13.671136`. The
  `sumble_unbounded_charge_exceeded_authorized_cap` refusal (event 1539) rendered as
  `governed_research_rejection` / `recoverable: true` and did not suspend the job.
* F4 — event 1560 (`assess_account_coverage`, job `5f274942-…`) refused with
  `engine_authority_rejection` naming only the ten outstanding `…@exa_deep` pairs; both of that
  job's Sumble operations are dispatched + folded, so their pairs are correctly absent. Event 1506
  (an earlier execution) shows the same list *including* `core.primary_tech_stack@sumble_tech_stack`
  and `account.hiring_velocity_eng@sumble_jobs`, i.e. before/after of the terminal-attempt predicate.

## Verification / residuals

* Green: `tests/storage`, `tests/agents`, `tests/resolvers`,
  `tests/api/test_comprehensive_account_execution_db.py`,
  `tests/integration/test_comprehensive_research_harness_db.py` (5×3),
  `tests/contact_research`, `tests/fleet`, `tests/api -k "sumble|artifact|exa|entity_research"`.
  ruff + ruff-format clean on changed files; project `uv run mypy` clean (732 files).
* Pre-existing, reproduced identically at HEAD: `tests/api/test_fi2_62_bundle_shrink_db.py` (3) and
  `tests/integration/test_fi2_slice3_economics.py` (2 — already recorded on the settlement lane).
* Throwaway DB `clue_live_crash_checks` created, used, dropped.
* Open: the harness drives jobs sequentially over one connection, so no harness-level test can
  reproduce D1's concurrency window — the storage-level contention test is the exact regression.
* Open: the D1 retry is one attempt. A pathological >2-way pile-up on the same key would still need
  a second retry; not observed, and the winner is always committed before the violation surfaces.
