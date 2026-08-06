# 2026-08-02 — M6A D1 durable discovery-batch substrate

Branch: `platform/c8-exa-sumble-discovery`

Status: implementation and D1 acceptance gate complete; this note is part of the scoped local D1
closeout commit.

## Scope delivered

- Added provider-neutral discovery plan/batch/operation/event/page/item/candidate/field/seal tables
  in migration `283ab57486e8` (parent `933c7b604f1c`).
- Added workspace-composite FKs, replay/idempotency constraints, normalized page-item and
  field-claim/source-item edges, DSAR artifact-subject indexing, and transactional wake outbox.
- Added `PhaseStatus.WAITING_EXTERNAL` / `PhaseCheckpointStatus.WAITING_EXTERNAL`, reference-only
  `DiscoveryExternalWait`, scheduler protocol, and project state-machine re-entry semantics. The
  run remains `ACTIVE` and in `DISCOVERY`; no human resume or advance to scoring occurs.
- Added `clue_research.durable.discovery` as the only D1 repository path: scoped CRUD/replay,
  secret-safe content-addressed artifact capture, subject indexing/tombstoning, wake claiming,
  cost reconciliation, bounded status projection, and transactional sealing.
- Added one SQL statement deriving all fourteen D0 readiness predicates. The seal writer locks the
  batch, derives readiness and seal metadata, inserts the content-hashed seal, and marks the batch
  sealed in the same transaction.
- Added database triggers that make plan/page/seal immutable and close all child mutations after a
  generation is sealed. A late event may only be appended born processed as `late_after_seal`.
- Distinguished successful operations from accepted terminal failures: a successful operation
  needs terminal pagination/items; an explicitly accepted failure seals with request/submit/final
  disposition and reconciliation evidence without fabricated pages/items/candidates.
- Wrote the detailed implementation/acceptance record in
  `docs/specs/M06A-D1-durable-discovery-batch.md` and linked it from the parent M6A plan.

No Exa or Sumble call was made. D1 has no provider id or provider cost; D2 owns the first live Exa
submit.

## Defects found and corrected during acceptance

1. Reversible enum downgrade initially failed because the existing checkpoint CHECK was still
   typed against the old enum. The migration now drops/recreates that constraint around the enum
   rebuild; a full clean head -> base -> head passes.
2. A combined sealed-generation trigger referenced an event-only column on operation rows. The
   PL/pgSQL path now accesses the column only for event inserts.
3. Optional pending discovery fields incorrectly blocked the claim/disposition predicate. The
   barrier now evaluates only materialized/resolved values and terminal dispositions; optional
   unattempted fields do not masquerade as required.
4. Public-footprint claims correctly have `workspace_id IS NULL`; the resolution proof initially
   accepted only workspace-private claims. It now accepts public claims for the scoped account and
   same-workspace private claims while still rejecting a different workspace.
5. `asyncpg` could not infer nullable manifest parameter types. The barrier now casts all manifest
   bind parameters explicitly.
6. Accepted terminal failures originally inherited successful-operation page requirements. The
   terminal items-page requirement now applies only to `succeeded` operations.
7. Rollback tests reused one synthetic provider operation id after the committed crash/recovery
   case. The database correctly enforced global provider-id uniqueness; fixtures now derive a
   unique synthetic id per workspace, making the gate order-independent.

## Final verification

Dedicated clean database `clue_d1_final_019fc196`:

```text
alembic upgrade head
alembic downgrade base
alembic upgrade head
PASS; one head: 283ab57486e8

CLUE_D1_COMMITTED_GATE=1 pytest -q tests/durable/test_discovery_batch_d1.py
4 passed
```

The committed gate persists page/operation state, closes the first connection (simulated crash),
reopens a fresh connection, finds and reuses the operation, completes the batch, then races two
independent seal transactions. Both return one identical seal and the database contains one seal
row.

Adjacent real-Postgres regressions:

```text
pytest -q \
  tests/durable/test_project_state_machine.py \
  tests/durable/test_project_run_db.py \
  tests/storage/test_artifacts_db.py \
  tests/identity/test_workspace_locality.py \
  tests/test_beat0_contracts.py \
  tests/discovery_scoring/test_discovery_field_policy_d0.py \
  tests/api/test_discovery_stage0_fixture.py
86 passed
```

Static/dependency gates:

```text
ruff check <D1 changed Python surface>
ruff format --check <D1 changed Python surface>
PASS; 11 files formatted

mypy
Success: no issues found in 464 source files

lint-imports
24 kept, 0 broken (528 files, 4051 dependencies)
```

An offline broad suite run produced only the three pre-existing unrelated failures already present
before D1:

- compliance DSAR test does not honor the unavailable-DB skip and attempts the unreachable DSN;
- memory offline boundary test flags the existing `platform/api/clue_api/trial/stage0_runtime.py`
  private memory-store import; and
- resolver secret-string scan false-positives on the pre-existing
  `fixture-org-attributes-only-drift` string.

The first DB-backed broad run was not a valid aggregate gate because it ran migration smoke and
later DB suites against the same mutable catalog; the migration test intentionally downgraded that
catalog. D1 was therefore closed using an isolated clean migration database plus the explicit
targeted/adjacent real-Postgres gates above.

## Cleanup

- Removed host scratch databases `clue_d1_019fc196` and `clue_d1_final_019fc196` after confirming
  zero active connections.
- Removed the separate Docker-catalog scratch database `clue_d1_019fc196` after confirming zero
  active connections.
- Re-queried both catalogs: no database matching `clue_d1%` remains.
- Preserved the named `clue_discovery_fixture` database; it remains present and was not modified by
  cleanup.

## Next boundary

D2 may now add the typed Exa Websets v0 client and one real two-row paid submit. It must use the D1
operation fingerprint lookup, artifact/receipt paths, wait/wake seam, and seal barrier. It may not
add a provider-specific lifecycle table, second idempotency ledger, or test-only barrier bypass.
