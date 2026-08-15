# Stage-0 confirmed-run v2

Date: 2026-08-16
Branch: `platform/integration-onboarding-pilot`
Status: implementation checkpoint complete

## Implemented boundary

- Added `start_confirmed_project_run@2` with an empty model-authored input and a minimal output of
  project-run id plus `discovery` phase. Receipt and readiness ids remain internal durable lineage.
- Added no receipt service or persistence wrapper. The tool reads the exact already-materialized
  Stage-0 cards and immutable turn scope, constructs the five-input receipt manifest, and calls the
  existing content-addressed `compile_product_context` function directly.
- The five inputs are company Client-KB, selected product, product profile, Product-KB, and the
  human-approved active ICP. No agent/LLM/provider/research/claim/KB generation occurs.
- Context artifacts produced before the turn are now bound to that turn in `agent_artifact_ref`, so
  the later transition reads exact artifact keys/digests instead of recomputing mutable context.
- With budget controls disabled, the discovery-spend boundary is recorded internally as
  `record_only`/ready and creates no new `agent_gate`. Deterministic ids make the readiness decision
  and project run stable even when the tool is retried with a different operation id.
- The low-level historical run-start function still validates the receipt, readiness, ICP,
  Client-KB, product, project, and workspace lineage before creating/reusing the run.

## Immutable resource promotion

- Active Head-of-ABM profile: v30.
- Active Stage-0 interview skill: v17.
- Active Recipe #0: v11.
- Active run-start authority: `start_confirmed_project_run@2`.
- Historical v29/v16/v10 and `start_confirmed_project_run@1` bytes remain registered for exact
  replay but are unavailable to the active role.

## Verification

- Real isolated-PostgreSQL acceptance proves two calls with different operation ids create exactly
  one `product_context_version`, one internal discovery readiness row, and one `project_run`; it
  also proves no new claim or human-gate row is created.
- Adjacent PostgreSQL matrix: 29 passed across Stage-0 tools, immutable turn pins, product
  selection, ICP gate lifecycle, and turn journaling.
- Resource/registry/tool/contract matrix: 70 passed, 5 skipped database-only cases.
- Focused frontend contracts: 30 passed; complete frontend suite: 301 passed.
- Ruff check and mypy passed for all affected backend files; `git diff --check` passed.

## Failed attempts worth retaining

- Running a `-k start_confirmed_project_run_v2` selector matched no test and exited 5; the actual
  acceptance test is named `test_confirmed_run_v2_reuses_existing_context_and_creates_one_run_across_retries`.
- Running TSX inside the filesystem sandbox failed to create its local IPC socket; the same tests
  passed outside the sandbox. Invoking it through `npm exec` also collapsed the file arguments;
  invoking `apps/frontend/node_modules/.bin/tsx` directly preserved them.
- An earlier attempt to start a new compose database collided with the already-running named
  PostgreSQL container. Verification used a separately named database on the existing local server.

## Follow-on boundary

This checkpoint does not implement or browser-test provider-neutral discovery configuration or
Exa request compilation. The next slice should derive or confirm account count/search criteria,
then prove approved ICP to discovery execution and populated Accounts through browser, API, and
database evidence.

## Follow-up review and hardening

The two preceding contract/implementation slices were reviewed before starting discovery
configuration. The review found and fixed these incomplete boundaries:

- A legitimate idempotent replay failed after Recipe #1 advanced the project run beyond
  `discovery`. The low-level start now accepts later phases without rewinding them, while comparing
  the entire immutable run lineage so a colliding run id cannot be repurposed.
- The active `@2` path used the older opportunistic Recipe #1 canary. With that default-off, a run
  could be created without a discovery execution. Confirmed Stage-0 handoff now uses a dedicated
  router method which requires complete lineage and bypasses only that legacy canary; historical
  and opportunistic callers retain the existing routing behavior.
- Receipt inputs were selected by turn/workspace/media type alone. Reads now require the exact
  project binding and client binding, plus the selected-product binding on the product profile and
  Product-KB cards. Foreign, erased, duplicated, or incomplete materializations fail closed.
- The deterministic readiness id omitted readiness policy, workspace policy, and budget-control
  mode. Those authority dimensions now participate in the id. A mode change derives a distinct
  decision and cannot reinterpret or replace an existing immutable run.
- A missing execution router is now a precondition failure and a direct invocation fails before
  creating receipt, readiness, or run state.

Final review verification:

- 39/39 live PostgreSQL tests passed across Stage-0, turn-scope pins, product selection, ICP gates,
  turn submission, Recipe #1 cutover, and governed confirmed-run entry.
- The contract/resource/registry/privacy/trial matrix passed with five expected database-only
  skips; Ruff and mypy passed on all affected source files.
- The complete frontend suite passed 301/301, followed by design-system build, ESLint, TypeScript,
  and the production Next.js build.
- `git diff --check` passed.

Review failures worth retaining:

- The first broad database command ran inside the filesystem sandbox and reported every DB test as
  skipped because loopback access was denied. Re-running with explicit local PostgreSQL access
  produced the real 39-test result; all-skipped output must not be treated as verification.
- An initial adversarial test tried to mutate `agent_artifact_ref`, but the database correctly
  rejected that table as append-only. The test was rebuilt to seed the foreign product binding at
  insert time.
- The first forced-routing test used a legacy run without Stage-0 lineage; production correctly
  refused it. The corrected test separates incomplete-lineage rejection from the canary-bypass
  probe and exercises the shared concrete attachment path through the enabled router.
