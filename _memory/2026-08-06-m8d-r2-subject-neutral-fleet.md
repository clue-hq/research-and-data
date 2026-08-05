# 2026-08-06 — M8D R2 subject-neutral fleet/job contract

## Outcome

Implemented and accepted M8D R2 on `platform/c8-account-profiling-integration`.

Account and contact research are separate R0-authorized durable runs projected onto one
`entity_research_job` fleet kind, one queue/lease implementation, and one handler. The immutable
run/job envelopes retain exact tenant/project/product/run/selection/subject/profile/checkpoint and
budget authority. Exact launch replay is no-op; changed authority fails closed.

## Durable execution

- Added migration `022b1154b3aa` with run, job, wait, finalization, and event tables plus immutable
  authority triggers and JSON/indexed-scope alignment constraints.
- Added live three-part fencing across domain state, the exact claimed fleet task, and the generic
  work-lease generation.
- External wait atomically persists checkpoint/state and closes the task; exact callback wake
  reopens the same task without duplicating it.
- Accepted receipt is the only terminal authority. Run cancellation requires one accepted receipt
  per nonterminal job, rewrites queued/claimed/waiting task observation, revokes in-flight leases,
  and prevents late-callback resurrection.
- Account/contact caps and concurrency remain separate per run/job. Provider budget reservation
  and settlement remain R9-owned; R2 makes no provider call or spend.
- `build_multi_work_worker` has an optional entity handler seam, but production does not bind it
  until R3 supplies the governed `create_agent()` driver. The R1 fail-loud quarantine remains.

## Verification

- Focused R0/R1/R2 battery: green.
- R2 pure, Postgres lifecycle, exact replay, wait/wake, cancellation, concurrency and fencing:
  green.
- Fresh disposable database migration upgrade -> downgrade to pre-R2 -> upgrade: green.
- Ruff and mypy over R2 production/source-specific tests: green.
- Wider fleet run: all R2/existing cases green except the already-recorded shared-database
  `core.work_email` field-definition drift in `test_b4_composed_run_db.py`, before fleet execution.

## Durable references

- `docs/specs/M8D-R2-subject-neutral-fleet-acceptance.md`
- `platform/fleet/clue_fleet/entity_research.py`
- `alembic/versions/022b1154b3aa_m8d_r2_entity_research_jobs.py`
- `tests/fleet/test_entity_research_r2_db.py`

## Next boundary

R3 composes the shared role-configured LangChain `create_agent()` runtime, Postgres checkpointer,
exact context/tool allowlists, typed finalization, journaling, and bounded facet contract onto this
handler. It must not add a second fleet or remove R1 quarantine before the replacement is bound.
