# Production context S4-C — trusted Client-KB tools

**Date:** 2026-08-14
**Branch:** `platform/onboarding-integration`
**Status:** S4-C implemented and verified; S4-D and S4-E remain

## Delivered

- Implemented `list_client_knowledge@2` and `inspect_client_claim@2` over the S4-A exact-version
  reader, conforming to the unchanged S4-B input/output schema hashes and byte boundaries.
- Kept `@2` behind `build_client_knowledge_v2_tools`; the central registry, Head-of-ABM profile,
  surface policy, skill, and recipe remain on frozen `@1` until S4-D.
- Added a production-only input authority policy. `@2` receives the client from the constitution,
  the workspace from `ToolContext`, and the version only from the validated paired
  `client_knowledge` project-context artifact. It does not accept the legacy trial focus-ref
  fallback; `@1` compatibility still does.
- Added bounded typed list/claim materialization, v1 omission-to-v2 continuation, deterministic
  v2 pagination, source-origin sanitization, exact value hashes, freshness, lineage, and the frozen
  non-oracular refusal classes.
- Corrected the shared tool runner to validate durable outputs in JSON mode. Strict UUID, enum,
  datetime, Decimal, and tuple contracts now survive both fresh execution and stored replay while
  invalid outputs still raise `ToolContractViolation` before cache completion.
- Clarified the roadmap refusal wording: unavailable workspace/client/version scopes share
  `client_knowledge_unavailable`; unknown/foreign/outside-version/non-member/expired refs inside a
  valid pinned scope share `client_claim_not_found`.

## Verification

- Frozen S4-B plus pure S4-C authority/schema tests: 13 passed.
- Real PostgreSQL S4-C acceptance: 5 passed on retained DB
  `clue_context_s4ab_20260814`; rollback fixtures left it reusable.
- Broader S1-S4 + governed execution + complete toolbelt matrix: 101 passed.
- Authority/profile/recipe/model-schema matrix with DB cases enabled: 48 passed, zero skipped.
- Repository formatting: 1,409 files; Ruff passed; mypy passed for 664 source files; all 25 import
  contracts passed through `.venv/bin/lint-imports`.
- `make contracts` itself could not initialize the sandbox-blocked user-level uv cache; the exact
  underlying `lint-imports` command passed 25/25. This is an environment wrapper failure, not an
  import-contract failure.
- No provider/browser call was made: S4-C is an effect-free durable-claim read and authority slice;
  production composition/live model use belongs to S4-D/S4-E/S6.

## Handoff

- S4-D alone may register and grant `@2`, using new immutable profile/skill/recipe revisions and an
  atomic production cutover. Do not change the frozen `@2` schemas or silently mark them default.
- S4-E must still prove durable DSAR reach, prompt-shaped evidence isolation, and full replay
  privacy before S4 is called complete.
