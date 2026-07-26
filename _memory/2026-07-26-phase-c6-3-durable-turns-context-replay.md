# 2026-07-26 — C6.3 durable turns, context, replay, and privacy

## Outcome

C6.3 is complete on `platform/c6-deepagent-runtime`. It adds the durable, body-free substrate a
real agent runtime needs, but no model loop, governed tool bridge, plan compiler, delegation
runtime, finalize authority, route, or feature flag. C6.4 is next.

## Implemented

- Added reversible migration `7e9269ed8a81` from C5 head `ed7a01cd8845`.
- Added normalized append-only tables for:
  - agent turns/events and parent execution identity;
  - exact profile/resource-manifest refs;
  - artifact refs, subject bindings, no-resurrection tombstones, and retention;
  - context bundles, exact L1–L7 layer rows, and included/excluded refs;
  - thread-message refs, terminal model-call receipts, finalization receipts, and privacy events.
- Added structural composite constraints for workspace/execution/thread/finalization/context
  locality and exact content-addressed artifact key/hash alignment.
- Added `DeterministicAgentContextAssembler` and independent L1–L7 sources:
  - stable ordering and versioned per-layer hard budgets;
  - conservative `utf8-bytes-v1` counting;
  - required identity/project/turn authority fails instead of truncating;
  - compiled-card/domain/artifact refs, read-only seed files, exact exclusions and aggregate hash;
  - raw attachments are pointers only.
- Added durable artifact DB+CAS persistence/read verification, explicit subject binding, append-only
  history serialization, model/finalization receipt idempotency, and body-free cold replay.
- Added agent DSAR handling: tombstone/purge subject-bound blobs, block replay/resurrection, close
  live backends, and remove affected isolated execution roots through anchored/no-follow cleanup.
- Production workspace output snapshots now use the durable artifact adapter; the old in-memory
  storage-only sink remains only as a focused test/backward-compatible helper.

## Important decisions

- Journals contain ids, exact versions, refs, hashes, counts, relative paths, states, and reason
  codes only. Prompt/card/message/memory/model/file bodies remain in their owning stores.
- Cold replay checks storage existence but never loads bodies. It reports exact profile/resource
  manifest, policy/counter version, all seven budgets and refs, and live/erased/purged/missing
  blockers.
- Scoped-memory tombstones and artifact tombstones fail replay closed.
- Artifact tombstones permanently prohibit reusing the same workspace-scoped content address.
- Subject reachability is indexed explicitly; DSAR never scans model/context bodies.
- C6.3 records a finalization envelope but does not apply success authority. C6.4 owns honest
  finalize validation and execution-state transition.

## Failures found and resolved

- The first live DB history test rejected an advisory-lock key containing `NUL`; PostgreSQL text
  cannot encode it. The scope key is now length-framed and SHA-256 hashed before `hashtextextended`.
- SQL row reconstruction initially passed strings into strict enum fields. Durable readers now
  reconstruct `AgentRole`/`AgentTurnStatus` explicitly.
- The first post-suite migration smoke failed at the older C5.3 downgrade guard because the
  DB-enabled suite had intentionally left pre-materialized nodes in the used test DB. This was
  not a C6.3 migration failure. The dedicated container schema was reset and clean up→down→up
  smoke passed, matching the repository convention.

## Verification

- Ruff format/check across `alembic`, `libs`, `platform`, `scripts`, `subsystems`, and `tests`:
  green (835 Python files).
- Mypy: 409 source files, green.
- Import-linter: 24 contracts kept, 0 broken.
- Full DB-enabled repository suite: green; 2,559 tests collected.
- C6.3 DB end-to-end covers durable/idempotent turn, history, context, model and finalization
  receipts; body-free replay; cross-workspace denial; append-only mutation rejection; DSAR;
  workspace deletion; replay blocking; and no-resurrection.
- `uv run alembic heads`: one head, `7e9269ed8a81`.
- Clean isolated Postgres `make db-smoke`: up→down→up green.
- `git diff --check`: green before close-out.

## Next

Proceed with C6.4 only: validated plan compiler, governed C5 tool bridge, stable operation
identities, delegation records/fresh-wake child construction, honest finalize authority, and the
crash/authority/replay matrix. Do not begin Stage-0 feature routing (C6.5) early.
