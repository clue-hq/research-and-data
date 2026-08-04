# 2026-08-04 — M8B E0-R1 provider-valid Exa request

## Scope

- Closed E0-R1 only: Exa Search Deep request compilation and request-contract acceptance.
- Did not close E0-R2 response/evidence semantics, E1 durable acquisition, E2 materialization,
  production composition, or live-provider acceptance.
- Made no credential lookup and no paid provider request.

## Decisions and implementation

- Rechecked the current Exa Search coding-agent reference on 2026-08-04.
- Replaced deprecated `numSentences` / ignored `highlightsPerUrl` and unbounded `text=true` with
  typed `contents.text.maxCharacters=10000` and query-guided
  `contents.highlights.maxCharacters=2000`. These are account-deep product budgets, not provider
  maxima.
- Encode each admitted dotted registry field key as reversible `f_<ascii-hex>` on the provider
  wire. The fixed prompt contains exactly the alias-to-field mappings, and response normalization
  decodes aliases before the provider-neutral seam.
- Enforce the documented output-schema budget before dispatch: at most eight root fields, ten
  declared properties in total, and two named property levels. Reject unsafe nested names,
  unsupported schema composition, malformed required sets, and over-budget schemas.
- Compile nullable schemas as one standard `type: [T, "null"]` union, add `null` to nullable enums,
  never mutate registry input, and require every top-level output field to admit a null evidence
  miss.
- Amended the A0 request/response goldens and digests because the reversible alias is part of both
  wire directions. Updated the A0, E0, and parent M8B acceptance status without representing E0-R2
  as complete.

## Verification

- E0/A0 focused tests: 23 passed, including the final exact-map and top-level-null checks.
- Broader regression command over Exa, Parallel isolation, A1 fixture, planner, and source-profile
  serving passed; only its explicitly DB-dependent tests skipped.
- `mypy`: success across 501 source files.
- `ruff check` and scoped `ruff format --check`: passed.
- import-linter: 24 contracts kept, 0 broken.
- Final full `pytest -q` had only two non-E0-R1 failures:
  - DSAR integration could not open sandbox-blocked localhost Postgres (`PermissionError` on
    `::1:5432`).
  - the existing memory-boundary backstop reports
    `platform/api/clue_api/trial/stage0_runtime.py`; E0-R1 did not touch that file.
- `git diff --check` passed for every E0-R1 file.

## Remaining

- E0-R2 must prove unchanged-golden normalization, paid all-null hard-miss settlement,
  field-faithful evidence selection, value-schema validation, citation preservation, and hard
  disablement of resolver-time HTTP before E1 composition.
- No live canary is authorized; V1 remains the first paid-provider acceptance boundary.
