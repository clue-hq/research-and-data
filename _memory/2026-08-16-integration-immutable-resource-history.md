# 2026-08-16 — Integration: immutable agent-resource history

## Scope

Third slice of the in-progress merge of `platform/onboarding-integration` into
`platform/integration-onboarding-pilot`: preserve historical resource bytes and mint one combined
active Head-of-ABM profile, Stage-0 skill, and Recipe #0 revision.

## Database safety audit

- Computed the Denver collision hashes before resolution. The colliding profile/skill files differ
  at `head-of-abm@v24/v25` and `stage0-interview@v11/v12`; the canonical Denver Recipe #0 hashes are
  `98666370...e15b` for v7 and `f558458e...cfc3` for v8.
- The configured Singapore target is the existing `singapore_clue_pgdata` volume on port 55040.
  It contains a `clue` database with no Alembic schema, so no turn, manifest, recipe-revision, or
  execution tables exist and no queued/running resource pins can exist there.
- As a defensive pilot-lineage check, the retained `clue_fi2_final` database was queried in a
  read-only transaction. It contains zero active `agent_turn` rows with either Denver colliding
  profile hash and zero queued/running `recipe0-stage0` executions with either Denver colliding
  canonical recipe hash.
- No hash-keyed compatibility layer is required. The temporary `clue-pg-singapore` container used
  to expose the existing volume was stopped after the audit. No migration, seed, provider call, or
  database write was performed.

## Resource ruling implemented

- Pilot bytes are authoritative at profiles v24/v25, skills v11/v12, and recipes v7/v8. Their six
  raw SHA-256 values are pinned in `tests/agents/test_catalog.py`.
- Denver's non-conflicting profiles v26-v28, skills v13-v15, and recipe v9 remain byte-identical to
  `MERGE_HEAD`.
- Minted `head-of-abm@v29`, `stage0-interview@v16`, and `recipe0-stage0@v10`.
- The new lineage composes trusted readiness/synthesis @2, exact ICP confirmation, selected-Account
  launch with account-deep-steering v4, Client-KB and Product-KB readers, and human product
  selection. The @1 readiness/synthesis tools are not pinned by the active profile or recipe.
- Active backend/frontend profile references now use v29 and the conversation recipe uses v10.
  Historical resources remain catalogued for exact replay.

## Verification

- `tests/agents/test_catalog.py`: 8 passed, including immutable-byte and combined-union guards.
- Direct catalog materialization computed the v29 resource-manifest digest as
  `737557760bdd0d6972aea1415f54725e98c4fb81f42cb6251dfec49dc2a5ff98`.
- Structural profile/recipe checks passed, and JSON/YAML parsing confirmed the v29/v16/v10 union.
- Focused frontend run reached 10 passing tests; two test modules remain uncollectable because the
  separate gate-schema merge conflict still leaves markers in `chat-turn.ts`.
- Tool-authority and executable-recipe suites remain uncollectable because the separate backend
  composition conflict still leaves markers in `agent_execution_wiring.py`.

## Remaining boundary

- This slice does not resolve the shared gate/runtime/frontend schema conflicts. Re-run the blocked
  registry, tool-authority, recipe, and complete frontend checks after those later slices remove
  their markers.
