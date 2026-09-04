# 2026-08-20 — derived band claims dropped their Exa Deep lineage (live pilot escape)

## The failure
Live job, account BridgepointMD (comprehensive research, directive v10), 17:36:45 IST.
`assess_account_coverage` → `_derive_profile_fields` → `derive_account_fields` raised

```
asyncpg.exceptions.RaiseError: exa_deep claims require complete operation, snapshot,
request, and result artifact lineage
```

raw out of `INSERT INTO claim`. It escaped as `execution_failed` and requeued the job
(`entity_research_job_event`, `reason_code="worker_error:DBAPIError"`).

## Q1 — was the lineage missing? No. Real stamping bug.
Failing INSERT parameters (from `entity_research_agent_event.payload_json`):
`field_key='core.revenue_band'`, `source_key='exa_deep'`, `artifact_key` PRESENT,
`source_operation_ref/source_snapshot_ref/source_request_ref` all NULL,
`provenance_kind='platform_inferred'`.

Its source claim — `core.annual_revenue`, `claim c6b7d51d-005a-44ae-b795-45f4456812b1`,
entity `6b1ccc31…` — holds **all four** refs (operation `5eeddd0a…`, snapshot `84e3b632…`,
request `d5b7ef07…`, artifact `ws_d98ab74…/1c937a78…`). Every live `exa_deep` claim in the DB has
complete lineage. `account_field_derivation._derive_one` copied only `source_key` + `artifact_key`
via `revalidate_with`, minting a half-lineaged Exa claim that the `f9281fac77e1` trigger correctly
refuses. Fix: pass the three refs through from the source claim (never minted).

## Q2 — the escape
Rung 2, defence in depth: the `insert_claim` now runs inside a SAVEPOINT
(`conn.begin_nested()`) and a lineage refusal — matched narrowly by SQLSTATE `P0001` **plus** the
trigger's verbatim message (both messages of `claim_validate_external_research_lineage`) — settles
the row as `derivation_lineage_unprovable`: no claim, no invented ref, coverage reports the gap,
the agent walks on to finalization. Every other `DBAPIError` re-raises. The trigger is untouched
and remains the authority (same shape as `2030de45`).

## Files
- `platform/api/clue_api/account_field_derivation.py`
- `tests/api/test_account_field_derivation.py` (4 new tests)

## Notes for the next agent
- The exa path is only reachable with `CLUE_VERIFICATION_ENABLED=false` (the pilot's setting):
  `require_verified_tier4` otherwise keeps unverified tier-4 Exa claims out of the merge, so
  nothing derives over them. The new tests set it explicitly.
- `derive_account_fields` is the only claim-copy site in the repo that restates another claim's
  `artifact_key` (grep `artifact_key=source\.`); no sibling has the same bug.
- Regression run green: `test_account_field_derivation`, `test_comprehensive_account_execution_db`,
  `test_evidence_span_provenance_db`, `test_entity_research_tools_r4_db`, the three
  `tests/resolvers/test_exa_deep*` suites, `test_exa_deep_{acquisition_e1,materialization_e2}`.
  `uv run mypy` (733 files) and `ruff check`/`format` clean. Not committed — orchestrator commits.
