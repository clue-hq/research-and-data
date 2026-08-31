# Stage-0 ICP presentation and pre-run Exa preflight (Slice 5)

Date: 2026-08-16
Branch: `platform/integration-onboarding-pilot`
Status: implemented and locally verified; browser/provider acceptance remains a separate checkpoint

## Scope ruling

- After synthesis, the Head of ABM must put the human-readable ICP synthesis in the normal
  assistant message of the same awaiting-input turn that carries the separate approval card. The
  card remains a decision control, not the synthesis presentation.
- This slice includes provider preflight so an unsupported confirmed configuration fails before a
  product-context receipt or project run exists.
- Per founder direction, this slice does not change client-company target exclusion, immutable
  turn-scope resolution, ICP numeric fidelity, readiness projection, or gate-answer/interview
  classification. Existing behavior in those areas was not reverted.

## Implementation

- Added immutable `synthesize_icps@3`. It reuses `@2` synthesis/storage and returns ordered,
  bounded presentations for the exact persisted drafts: name, rationale, target criteria, buying
  signals, discovery motion, and an explicit truncation marker. It creates no second synthesis or
  knowledge artifact.
- Promoted Head-of-ABM `v32`, Stage-0 skill `v19`, and Recipe #0 `v13`; `v31`/`v18`/`v12` remain
  immutable replay inputs. The active conversation recipe had incorrectly remained pinned to v11
  after Slice 4; it now correctly selects v13.
- Added the provider-neutral `ConfirmedDiscoveryPreflight` seam and implemented it with Exa's pure
  compiler. Fleet composition reuses the same Exa starter for pre-run validation and execution.
- `start_confirmed_project_run@3` validates provider support before receipt/readiness/run writes and
  again against the exact content-addressed run id immediately before insertion. Missing provider
  validation fails closed. No preflight performs a provider request.
- Reused the one firmographic renderer for both discovery planning and ICP presentation to avoid
  divergent user-visible criteria.

## Verification

- Focused catalog, runtime, authority, recipe, toolbelt, synthesis, discovery configuration, and
  Exa suites: green; DB-dependent cases skip without a configured database.
- Isolated PostgreSQL lifecycle suite: 14 passed. The rejecting-provider case exercises both
  preconditions and direct invocation and proves zero `product_context_version` and zero
  `project_run` rows; the valid path remains retry-stable.
- Broader Stage-0/budget/kickoff database matrix was green after one test-only missing import was
  corrected (58 collected cases).
- Ruff, mypy on the changed backend surfaces, and `git diff --check`: green.
- Frontend: 302 tests passed; ESLint, design-system token build, and Next production build passed.
  The first sandboxed frontend test attempt failed because `tsx` could not create its local IPC
  socket; the approved unsandboxed rerun passed.
- The exact disposable database `clue_singapore_slice5_20260816` was verified idle and dropped.

## Follow-up

- Run browser-to-API-to-database-to-provider acceptance from a fresh project: synthesize the ICP,
  verify normal assistant prose plus a separate approval card, approve it, and prove the resulting
  Exa request and discovered accounts. Do not claim this live acceptance from the implementation
  tests above.
