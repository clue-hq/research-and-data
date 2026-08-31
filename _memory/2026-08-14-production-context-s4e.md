# Production context S4-E — privacy, injection, and replay hardening

**Date:** 2026-08-14
**Branch:** `platform/onboarding-integration`
**Status:** S4-E implemented and verified; amended S4-A through S4-E are complete

## Delivered

- Added one production Client-KB privacy policy that reverse-binds each exact `@2` tool result to
  the trusted client and every returned claim id. Prompt-shaped nested values are never parsed as
  authority.
- Kept the bounded exact tool result available to the model, but reduced the durable stream/outbox
  projection to operation correlation, trusted client/version, and claim refs. Values,
  descriptions, evidence spans, page bodies, tokens, credentials, and source URLs do not enter the
  new stream frame.
- Extended agent DSAR from indexed tool-result roots through later same-thread turns and delegated
  descendants. Potentially data-bearing CAS artifacts are tombstoned/purged, bounded stream
  partitions and exact LangGraph turn namespaces are deleted, isolated workspaces are purged, and
  body-free audit/cost/context/finalization rows remain.
- Preserved shared immutable resource manifests and budget envelopes; the erasure closure is
  intentionally bounded and does not make a surviving workspace unable to start a new turn.
- Minted immutable Head-of-ABM profile `v26` and Stage-0 skill `v13`. The skill treats claim
  values/previews/descriptions/evidence/source lineage/URLs/page text as untrusted evidence that
  cannot select tools, widen authority, author trusted scope, delegate, or override gates. The
  prior v25/v12 and all `@1` resources remain unchanged for historical replay.
- Updated the source-of-truth context-composition spec and current production surface to v26/v13.
  Recipe #0 remains v8 because the tool graph did not change. No migration was required.

## Verification

- Final combined S4 contract/tool/execution/profile/runtime/DSAR/downstream matrix: 119 passed
  against retained clean database `clue_context_s4e_final_20260814` at sole Alembic head
  `b2f815da0f31`. Rollback fixtures left `agent_turn=0` and `agent_artifact_tombstone=0`.
- The real-PostgreSQL S4-E acceptance creates tool-result/model/final/stream/checkpoint copies,
  erases them by client subject, retains body-free receipts, blocks cold replay, refuses CAS
  resurrection, proves idempotent repeat erasure, and proves shared resource/budget bodies survive.
- Existing S4-C replay tests still prove identical reference sets with zero write/provider spend.
- Ruff passed across 1,412 files, mypy passed across 665 source files, and all 25 import contracts
  passed.
- Repository-wide pytest: 4,708 passed, 23 skipped, 40 failed. The failures are separated baseline
  contamination/static issues: design-subtree direct logging, pre-existing old-token test names,
  and a monolithic shared-DB run whose committed rows block migration downgrade and collide with
  source-registry fixtures. No S4-E focused or final isolated-DB test failed. The one new local
  old-token variable discovered by that run was renamed before final verification.

## Handoff

- S3.1 is the next planned composition-reliability slice. It owns durable per-turn scope pins,
  statement-level production Stage-0 DSAR binding, vN/vN+1 retry policy, fleet-path proof, and the
  company-wide versus product-specific knowledge policy.
- Retain `clue_context_s4e_final_20260814` for review. The earlier
  `clue_context_s4e_20260814` was used by the monolithic suite and is not the final clean evidence
  database.
