# M6A D1 — Durable discovery-batch substrate

Status: **implemented; D1 gate evidence recorded in §11**

Parent plan: `docs/specs/M06A-exa-websets-sumble-discovery-integration.md`

Predecessor contract: `docs/specs/M06A-D0-contract-freeze.md`

Scope: provider-neutral PostgreSQL lifecycle state, content-addressed evidence references,
replay/idempotency, external-wait scheduling, SQL-derived completion, and an immutable batch seal

Out of scope: Exa or Sumble HTTP calls, credentials, provider response parsing, webhook ingress,
live polling, provider-specific normalization, and production account-field materialization

## 1. Outcome and binding invariants

D1 supplies the closed, durable generation that discovery completion must use. Provider completion
alone cannot create a seal: every operation, event, page, item, candidate decision, required field
decision, cost, and final manifest must pass the fourteen-condition SQL barrier before the database
writes one immutable `discovery_batch_seal`. D1 also gives the project runtime a non-completing
external-wait state. The discovery handler that makes the exact current seal a hard prerequisite
for returning `COMPLETED` is intentionally D5 scope; D1 does not falsely claim that later binding.

The binding invariants are:

1. The immutable discovery plan is pinned to one workspace, project run, ICP version, provider
   policy, field policy, and provider-contract version.
2. One semantic request in one observation window has one durable operation and therefore one
   paid-dispatch identity. A replay consumes that row and its artifacts rather than dispatching
   again.
3. Raw provider bodies live only in the shared content-addressed artifact store. Relational rows
   contain lifecycle, hashes, lineage, and references; claims remain the factual truth store.
4. External provider time is `WAITING_EXTERNAL`, not a human pause and not phase completion. A
   scheduled or event-driven wake re-enters the same discovery checkpoint.
5. All fourteen completion predicates are derived by one SQL query under the seal transaction's
   `FOR UPDATE` batch lock. No caller supplies a readiness boolean.
6. A successful operation must exhaust its pages and materialize every item. An explicitly
   accepted terminal failure may have no response page or candidate, but it still needs durable
   request, submit, final disposition, cost, and reconciliation evidence.
7. Sealing closes the entire generation. The database rejects later operation, page, item,
   candidate, field, or edge mutations. A late provider event may be appended only when born
   processed with `late_after_seal`; it cannot rematerialize state.
8. Every repository read/write is workspace-scoped, and child tables use composite workspace
   foreign keys. A raw artifact is never reused across workspaces.

## 2. Ownership and dependency boundary

| Concern | Implementation owner | Boundary |
|---|---|---|
| Shared wait/scheduler contracts and `WAITING_EXTERNAL` result status | `libs/clue-core/clue_core/discovery.py`, `clue_core.enums` | Pure contracts; no DB, provider, or worker import |
| Durable tables, constraints, triggers, and downgrade | `alembic/versions/283ab57486e8_durable_discovery_batch_substrate.py` | Provider-neutral PostgreSQL only |
| Scoped repositories, artifact capture, replay, barrier, seal, and status projection | `subsystems/research/clue_research/durable/discovery.py` | `clue_core`, existing DB transaction seam, existing storage/artifact seam |
| Project-run checkpoint behavior | `subsystems/research/clue_research/durable/project.py` | Accepts only a reference-only `DiscoveryExternalWait` during discovery |
| Provider transport | D2/D3 adapter packages | Must persist through D1; cannot write claims or decide seal readiness |
| Identity/claim materialization | D4 composition | Consumes durable item snapshots and writes through existing identity/claim seams |

`clue_research.durable.discovery` has no Exa, Sumble, HTTP, scoring, or provider SDK import. This is
intentional: D2 and later providers can be replaced without changing lifecycle or sealing.

## 3. Durable schema

Migration `283ab57486e8` is a single child of `933c7b604f1c` and creates one Alembic head.

| Table | Durable responsibility |
|---|---|
| `discovery_plan` | Immutable versioned plan JSON and canonical plan SHA-256 |
| `discovery_batch` | One project-run generation, lifecycle state, aggregate realized cost, and seal time |
| `discovery_operation` | Semantic request identity, provider ids, spend state, receipt/artifact refs, polling and reconciliation timestamps |
| `discovery_provider_event` | Idempotent event receipt, signature result, raw artifact, provider/receipt time, and processing disposition |
| `discovery_page_receipt` | Immutable resource/cursor receipt and page hash; first page uses `__first_page__` |
| `discovery_item_snapshot` | Immutable raw item lineage and normalization terminality |
| `discovery_page_item` | Exact ordered membership proof between page receipts and item snapshots |
| `discovery_candidate_link` | Item-to-account admission, merge survivor, or exclusion decision |
| `discovery_field_resolution` | Per-account logical-field state, winner, reason, and review reference |
| `discovery_field_claim` | Normalized many-to-many edge from a field resolution to its supporting claims |
| `discovery_field_source_item` | Normalized many-to-many edge from a field resolution to source item snapshots |
| `discovery_batch_seal` | One immutable, content-hashed completion record per batch |
| `discovery_artifact_subject` | Workspace/subject index for raw and manifest artifacts, including tombstone state |
| `discovery_wake_outbox` | Transactional, deduplicated scheduled/event/manual/crash-recovery wake requests |

Every table carries `workspace_id` even where it is derivable. Composite foreign keys bind children
to the same-workspace parent. Provider operation ids are unique only when non-null; planned rows do
not collide through SQL null semantics. Page, item, plan, and seal constraints also enforce hashes,
cursor coherence, terminal timestamps, cost non-negativity, resolution shape, and candidate shape.

The migration installs three database enforcement layers:

- plan, page, and seal rows reject update/delete as immutable;
- once a batch is sealed, all generation-child mutations are rejected, except a terminal
  `late_after_seal` event insert; and
- a sealed batch cannot be reopened or otherwise modified.

The downgrade removes all D1 objects, converts residual `waiting_external` checkpoints back to the
safe resumable `in_progress` state, rebuilds the pre-D1 enum, and restores the checkpoint coherence
constraint. The clean-database gate exercises the complete head → base → head chain.

## 4. Replay and paid-call idempotency

The replay hierarchy is structural rather than cache-by-convention:

- `discovery_plan`: stable id plus immutable plan hash;
- `discovery_batch`: unique `(workspace_id, project_run_id, generation)`;
- `discovery_operation`: unique
  `(workspace_id, source_key, request_fingerprint, observation_window)`;
- provider submission: deterministic provider external id, plus a partial unique index on a
  non-null `(source_key, provider_operation_id)`;
- provider event: unique `(workspace_id, operation_id, provider_event_id)`;
- page receipt: unique `(workspace_id, operation_id, resource_kind, request_cursor_key)`;
- item snapshot: unique `(workspace_id, operation_id, provider_item_id, item_sha256)`;
- candidate link: one row per `(workspace_id, batch_id, item_snapshot_id)`; and
- field resolution: one row per `(workspace_id, batch_id, account_entity_id, logical_field_key)`.

An exact replay returns the existing typed row. Reusing the same stable identity with different
immutable content raises `DiscoveryReplayConflict`. `find_reusable_discovery_operation` is the
D2 pre-dispatch lookup: after a process restart, the adapter must inspect the existing operation
and receipts before any provider create call.

## 5. Artifact, provenance, and erasure behavior

`capture_discovery_artifact` uses the existing `StorageBackend` and artifact registry. It computes
the content SHA-256, derives a workspace-scoped key, records the artifact metadata, and stores bytes
only if the content-addressed key is absent. JSON bodies with credential-shaped keys and source
URLs containing credentials or credential query parameters are rejected before capture.

Operation requests/receipts/manifests, event bodies, page bodies, item bodies, and final manifests
are referenced from PostgreSQL. The batch seal verifies that every required final artifact exists,
belongs to the workspace, is not erased/purged, and that the account-manifest hash matches.

`discovery_artifact_subject` provides scoped bind, enumerate, account-index, and tombstone paths.
The index includes source item artifacts and the final account/raw/claim/coverage manifests. The
tombstone path delegates byte deletion to the existing artifact lifecycle only when the object is
unreferenced; audit-safe reference state remains queryable.

## 6. External-wait lifecycle

`DiscoveryExternalWait` is a reference-only phase result containing the batch id, pending operation
ids, wake time, and a non-secret reason. The durable project state machine accepts it only for
`ProjectPhase.DISCOVERY` and writes a `waiting_external` checkpoint while keeping the project run
`ACTIVE` and in `DISCOVERY`. The scheduler request adds the workspace and project-run scope needed
to route that wake durably.

`DiscoveryWakeScheduler` is the provider-neutral protocol. `DbDiscoveryWakeScheduler` persists a
`DiscoveryWakeRequest` in `discovery_wake_outbox` with a stable dedupe key. Workers claim due rows
with `FOR UPDATE SKIP LOCKED` and mark them processed after they have triggered a fresh project-run
wake. Re-entering `ProjectStateMachine.run()` from `waiting_external` invokes discovery again and
does not require the human-resume path. A waiting result itself never advances the phase. D5 binds
the discovery handler's later `COMPLETED` result to the exact current seal before scoring.

## 7. Fourteen-condition transactional seal

`read_discovery_seal_readiness` is one SQL statement over the batch snapshot. `seal_discovery_batch`
locks the batch, checks for an identical existing seal, executes that SQL, converts false predicates
to the D0 blocker contract, and inserts both the content-hashed seal and batch transition in the
same transaction.

| # | SQL-derived predicate | Blocking evidence |
|---:|---|---|
| 1 | `plan_lineage_matches` | Plan/run/project/ICP/workspace mismatch or missing plan |
| 2 | `operations_terminal` | Planned-operation count mismatch or non-terminal operation |
| 3 | `dispatch_receipts_complete` | Missing request/submit/final/required-response artifact |
| 4 | `provider_events_accounted` | Any accepted event remains pending/unprocessed |
| 5 | `final_reconciliation_complete` | Operation lacks authoritative final reconciliation |
| 6 | `pagination_exhausted` | Missing succeeded-operation terminal page, broken cursor chain, or unset exhaustion |
| 7 | `items_materialized` | Page count/edge mismatch, missing raw artifact, or non-normalized/unpaged item |
| 8 | `candidate_identities_terminal` | Item has no admitted/merged/excluded candidate decision |
| 9 | `hard_identities_complete` | Admitted survivor lacks canonical name or primary domain |
| 10 | `required_fields_terminal` | Required logical field absent or in a blocking state |
| 11 | `claims_or_dispositions_complete` | Resolved winner lacks matching claim edge/entity, or terminal disposition lacks reason |
| 12 | `survivor_links_complete` | Pending candidate or invalid admitted/merged survivor relationship |
| 13 | `spend_reconciled` | Batch totals differ from operations or spend remains unknown/not-dispatched |
| 14 | `final_manifests_exist` | Required manifest absent, cross-workspace, erased/purged, or hash-mismatched |

The acceptance test flips every predicate false independently inside a savepoint and proves the
seal writer raises `DiscoverySealBlocked`. It also attempts to mutate an immutable page, rather
than using test-only SQL to bypass the barrier.

Concurrent seal attempts use independent transactions. The batch row lock serializes them; the
first writes the seal and the second returns that same typed seal only when its draft matches.
A different manifest draft raises `DiscoverySealConflict`.

## 8. Successful versus accepted-failure operations

`succeeded` and `accepted_terminal_failure` are both seal-terminal, but they are not evidence-
equivalent:

- `succeeded` requires a provider operation id, raw response manifest, exhausted terminal items
  page, and complete item/candidate/field materialization for anything returned;
- `accepted_terminal_failure` requires an explicit terminal operation state, durable request,
  submit receipt, final failure/disposition receipt, known charged/not-charged outcome, final
  reconciliation, and pagination reconciliation. It does not fabricate a response page, item,
  candidate, or field row that the provider never produced.

This distinction permits a closed batch when policy explicitly accepts a terminal provider
failure, while keeping a retryable, unknown-spend, or undisposed failure unsealable.

## 9. Bounded query surface

The repository exposes typed scoped readers for plans, batches, operations, events, pages, items,
candidate links, field resolutions, seals, subject artifacts, and reusable requests.
`get_discovery_batch_status` returns counts, grouped states, at most 100 pending operation ids, next
poll time, current blockers, and the seal hash. It never returns provider bodies or unbounded rows.

## 10. D1 acceptance matrix

| Requirement | Acceptance proof |
|---|---|
| Create → wait → crash → resume → seal | Commit raw page/operation, dispose connection, reopen, find reusable operation, complete, and seal |
| No repeated paid request | Stable fingerprint lookup returns the committed operation across process/connection boundaries |
| Concurrent sealing | Two independent transactions return one identical seal; one seal row exists |
| SQL barrier cannot be faked | Fourteen independent false-predicate cases all block the production seal writer |
| Duplicate/out-of-order delivery | Replayed event/page/item ids converge; event arrival order is not lifecycle authority |
| Cross-workspace isolation | Scoped reads return no row and composite-FK writes fail |
| First-page uniqueness | Repeated `__first_page__` receipt returns the immutable original |
| Sealed-generation closure | Later operation/page/item/candidate/field mutations fail; late event is terminal/non-materializing |
| DSAR reachability | Account subject enumeration includes raw item and final manifest references |
| Accepted terminal failure | Seals with explicit evidence/reconciliation and zero fabricated items |
| Migration reversibility | Clean PostgreSQL full head → base → head succeeds with one head |
| Provider independence | No external call, credential, provider SDK, or provider-specific schema is present in D1 |

## 11. Gate evidence

Recorded 2026-08-02 on branch `platform/c8-exa-sumble-discovery`.

```text
CLUE_DATABASE_URL=postgresql+asyncpg://.../clue_d1_final_<run> \
  .venv/bin/alembic upgrade head
CLUE_DATABASE_URL=postgresql+asyncpg://.../clue_d1_final_<run> \
  .venv/bin/alembic downgrade base
CLUE_DATABASE_URL=postgresql+asyncpg://.../clue_d1_final_<run> \
  .venv/bin/alembic upgrade head
pass: complete clean-database head -> base -> head; final head 283ab57486e8

CLUE_DATABASE_URL=postgresql+asyncpg://.../clue_d1_final_<run> \
CLUE_D1_COMMITTED_GATE=1 \
  .venv/bin/pytest -q tests/durable/test_discovery_batch_d1.py
4 passed

CLUE_DATABASE_URL=postgresql+asyncpg://.../clue_d1_final_<run> \
  .venv/bin/pytest -q \
    tests/durable/test_project_state_machine.py \
    tests/durable/test_project_run_db.py \
    tests/storage/test_artifacts_db.py \
    tests/identity/test_workspace_locality.py \
    tests/test_beat0_contracts.py \
    tests/discovery_scoring/test_discovery_field_policy_d0.py \
    tests/api/test_discovery_stage0_fixture.py
86 passed
```

The static and import-contract commands are recorded in the closing `_memory/` note. D1 performs
no provider call, so this gate records no provider id or provider cost. The database names above
are dedicated scratch databases and are removed after closeout; the Stage-0 fixture database is
not modified or removed.

## 12. Explicit boundary into D2

D1 is complete without proving Exa behavior. D2 must add the typed Websets v0 transport and route
its real request/submit/final receipts through this substrate. D2 may not introduce a second
idempotency store, a provider-specific lifecycle table, an in-memory retry authority, or a bypass
around the D1 seal. Its live gate must prove that an exact repeated submit after restart causes no
second provider create call.
