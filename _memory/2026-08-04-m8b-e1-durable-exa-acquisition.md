# 2026-08-04 — M8B E1 durable Exa acquisition

## Scope and boundary

- Branch: `platform/c8-account-profiling-integration`.
- Implemented M8B Slice E1 only: coalesced Exa account acquisition, generic durable operation /
  attempt / snapshot / result / receipt ledger, spend classification, freshness and replay.
- E2 still owns claim construction, target-lock verification, faithfulness, effective source-plan
  binding and production account-agent composition.
- No credential was read and no live or paid provider call was made; all transport was injected.

## Implementation

- Added provider-neutral external-research IDs, states, request lineage and snapshot-reference
  contracts in `clue_core.external_research`.
- Added Alembic revision `bc0612c57713`. It pins the exact workspace/project/run/account/ICP,
  confirmed A2 directive and optional override, source manifest, request/wire digests, reservation,
  dispatch lease and observation/freshness policy. Attempts, ready snapshots, retained result
  artifacts and provider-reported receipts are separate durable rows.
- DB triggers make request lineage and terminal records immutable and prevent `ready` unless the
  matching responded attempt, snapshot and receipt already exist.
- Added the generic durable DAL and included nonterminal external-research reservations in the
  cross-provider project-run spend guard.
- Added `ExaDeepAcquisitionCoordinator` and deterministic bundle compiler. The compiler greedily
  packs sorted admitted fields under E0's schema limits. The coordinator stores the request before
  an injected zero-retry dispatch outside a DB transaction, then stores the raw response, every
  retained result, normalization/grounding, request id and receipt before settling once.
- Added a dormant real HTTP transport that resolves `CLUE_EXA_API_KEY` only at call time, emits the
  already-compiled coalesced request and forces the shared HTTP wrapper to zero retries. It is not
  production-composed and was exercised only with injected HTTP doubles.
- Active leases join. Expired/crashed leases, unexpected post-dispatch errors, malformed successes,
  missing settlement data and cost above reservation quarantine as `spend_outcome_unknown` with no
  retry. Pre-dispatch and proven 400/401/402/403/404 outcomes terminate not charged.
- Exact replay and exact-wire/exact-directive fresh reuse return the immutable stored snapshot with
  zero HTTP. `load_exa_deep_snapshot` reads only artifact storage and has no transport dependency.

## Verification

- E1 DB acceptance: 4 tests passed. Coverage includes one call for two fields, exactly-once spend,
  immutable artifacts/attempt, fresh-process replay, cross-window freshness reuse, active join,
  crash quarantine, unexpected/malformed outcomes, known HTTP rejection and all-null paid miss.
- Combined A0/E0/E1 coordinator, HTTP-boundary and shared-helper acceptance: 58 tests passed
  against isolated Roseau Postgres on port 55010.
- Clean temporary database `clue_e1_smoke_final` passed full Alembic head -> base -> head and was
  removed.
- Scoped Ruff passes; full mypy passes over 508 source files; all 24 import-linter contracts pass.
- Broad pytest: 1,963 passed, 1,345 skipped. Two unrelated failures remained: a sandboxed attempt to
  reach default Postgres port 5432 (the same DSAR test passes against Roseau port 55010) and the
  pre-existing `memory_wiring.py` memory-boundary failure. Whole-repo Ruff also remains blocked by
  13 pre-existing unformatted files outside E1; all E1 Python files pass the project Ruff version.

## Closing state

- M8B roadmap marks E1 mechanically complete without a live canary.
- Next Exa slice is E2. It must materialize each field independently from the ready snapshot,
  retain E1 artifact/request/cost lineage, use the A1/A2 effective source plan and never add
  resolver-time network I/O.
