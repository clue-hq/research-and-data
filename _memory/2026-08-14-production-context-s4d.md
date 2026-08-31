# Production context S4-D — production toolbelt composition

**Date:** 2026-08-14
**Branch:** `platform/onboarding-integration`
**Status:** S4-D implemented and verified; S4-E remains before S4 is complete

## Delivered

- Registered immutable Client-KB readers `@1` and `@2` in the central toolbelt, with strict
  artifact-bound `@2` selected as the name default and `@1` retained for exact historical replay.
- Made authority version-aware: only `list_client_knowledge@2` and
  `inspect_client_claim@2` are admitted to the Head-of-ABM model surface; `@1` remains visible in
  capability inventory but role-unavailable.
- Minted Head-of-ABM profile `v25` and Stage-0 skill `v12` with exact `@2` schema pins. The skill
  preserves bounded on-demand discovery/inspection guidance and forbids model-authored scope.
- Minted Recipe #0 `v8`, replacing only the two Client-KB tool requirements/allowlist entries with
  `@2`. Kept `v7` unchanged and moved the shared production/trial conversation recipe pin to `v8`.
- Updated production composer/read surfaces to return `head-of-abm@v25` and added explicit static
  proof that the real `project_conversation` surface resolves profile `v25`, skill `v12`, and the
  two strict `@2` tools.
- Updated the source-of-truth plan with the implemented S4-D evidence. No provider, coordinator,
  feature-flag, or test-mode branch was introduced, and no migration was required.

## Verification

- Focused Client-KB contract/authority/catalog/profile/surface/recipe/toolbelt matrix passed.
- Complete S0-S4 context, governed-tool, authority, recipe, and PostgreSQL acceptance matrix passed
  against retained isolated DB `clue_context_s4ab_20260814`, with DB cases executing.
- Project-turn, Home bootstrap/read surfaces, Stage-0 C5 interaction slot, Lane-D fleet kickoff,
  recipe promotion, omission resolution, and routing-honesty DB regression matrix passed.
- Recipe promotion proves revisions 1-7 are superseded and only immutable revision 8 is promoted;
  the v7 artifact and both `@1` descriptors remain resolvable for replay.
- Repository gates passed: Ruff format/lint (1,409 files), mypy (664 source files), and all 25
  import contracts.
- A repository-wide pytest sweep reached 100%. Three DB tests failed only because that unprivileged
  run was sandbox-blocked from localhost; all three passed when rerun against the isolated DB.
  The only remaining failures are the two recorded baseline static guards: design-subtree direct
  logging and older `client_id` test tokens. No S4-D changed file appears in either offender list.

## Handoff

- S4-E must trace and erase every durable inspected-fact copy, harden prompt-shaped evidence as
  untrusted data, and prove replay cannot resurrect erased values before S4 is called complete.
- The legacy trial still shares the active Head-of-ABM profile/recipe and therefore sees `@2`, but
  `@2` deliberately has no focus-ref fallback: without S3's paired Client-KB artifact the call
  fails closed. Do not reintroduce the `@1` fallback into `@2`.
- Keep the isolated database retained for review; rollback fixtures left it reusable.
