# 2026-07-24 — Phase C2 field/source proposals

## Session start

- Workspace: `ashgabat`.
- Renamed the clean starting branch from `platform/workspace-restructure-v4` to the requested
  `platform/c2-field-source-proposals`.
- Verified the branch starts at the frozen C0 commit `421848f`.
- Governing specs: `docs/specs/PC-C0-step4-contract-freeze.md` and
  `docs/specs/PC-C2-field-source-proposals.md`.
- C2 owns its proposal stores/service, migration, generic tier-3 web resolver, proposal tools and
  projections, and the narrow ICP-synthesis un-drop path. Central registration/router aggregation
  remains integration-owned.

## Implementation direction

- Extend the existing field/source registries through one shared proposal-decision service; do not
  create alternate registries or approval machinery.
- Keep proposal payloads immutable and idempotent on canonical payload hash plus scope.
- Serialize decisions with a row lock; promotion writes the live registry and stamps the ledger in
  the same transaction.
- Compute authority in engine code. Agent tool calls may nominate but may not decide; human decision
  tools and policy-driven service calls are distinct.
- Reuse the existing waterfall `SourceGate`, `ClaimTagger`, adapter pipeline, snapshot sink, and
  resolver binding. The generic resolver does not create replacement governance seams.
- Preserve out-of-registry ICP concepts as durable proposal refs while leaving them out of active ICP
  slots until promotion.

## Implemented

- Added the C0-frozen proposal IDs/refs/status/authority contracts in `clue_core.proposals` and the
  C2 `ProposalPolicy` in `clue_config.proposals`.
- Added immutable `field_definition_revision` and `source_manifest_revision` ledgers in Alembic
  revision `316c84a7a3a4`, including scope FKs, canonical-payload dedupe, decision/applied-state
  checks, payload/decision immutability triggers, and reversible enum/table teardown.
- Added `clue_research.proposals` models, Postgres stores, and one decision service. Promotion
  writes the existing live field/source registry in the same transaction as the terminal decision.
  Policy promotion is limited to public tier 3. Contact/personal sources require human authority
  plus an injected compliance approval; credentialed sources require confirmed admin setup.
- Added policy-backed tier-3 yield demotion: the proposal retains audit metadata and the source is
  versioned inactive for future registry-derived plans; already materialized plan values are not
  rewritten.
- Added the four lane-local tool envelopes and two workspace-scoped proposal projections. Auth and
  rate-limit material is not projected. Central tool/projection registration was intentionally not
  changed because C0 assigns it to integration.
- Added `synthesize_icps_with_proposals`. Registered concepts still populate ICP slots; well-formed
  unknown concepts become durable proposal refs; malformed/unsafe concepts become terminal rejected
  audit records; the existing `synthesize_icps` remains backward-compatible.
- Added the distinct `generic_web` resolver using the existing Resolver, Firecrawl HTML adapter,
  snapshot sink, SourceGate, ClaimTagger, and waterfall write path. It is fixed at tier 3 and
  target-locked to an approved `(entity_id, field_key, URL/domain)`.

## Verification

- `uv run alembic heads` → exactly one head: `316c84a7a3a4`.
- `CLUE_DATABASE_URL=...:55432/clue make db-smoke` → clean up → base → head pass on an isolated
  throwaway Postgres 16/pgvector container.
- Targeted C2 DB/resolver/Stage-0 tests → 26 passed.
- Final `CLUE_DATABASE_URL=...:55432/clue make check`:
  - Ruff format/check passed.
  - mypy passed on 336 source files.
  - 23 dependency/import contracts passed, including the provider-SDK boundary.
  - pytest: `2276 passed, 20 skipped`.
- `git diff --check` passed.

## Closing state

- Branch: `platform/c2-field-source-proposals`.
- Base remains `421848f`; all C2 code, tests, migration, and this memory note are intentionally
  uncommitted per the user's instruction.
- No push or PR was created.
