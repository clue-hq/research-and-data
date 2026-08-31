# Stage-0 provider-neutral discovery configuration (`@3`)

Date: 2026-08-16
Branch: `platform/integration-onboarding-pilot`
Status: Slice 4 implemented and locally verified; browser acceptance remains a separate checkpoint

## Shipped contract

- `start_confirmed_project_run@3` remains argument-free. It reuses the exact existing Stage-0
  Client-KB/product/profile/Product-KB/approved-ICP context and never asks the model for lineage,
  receipt, spend, or provider ids.
- `stage0-discovery-planning-policy@1` defaults company discovery to 10 accounts and caps it at 50.
  Concrete approved-ICP firmographics become a complete provider-neutral configuration without a
  human interruption.
- Genuinely missing search intent or must-have criteria returns
  `discovery_configuration_confirmation_required`. The agent may explain a proposal and call
  `open_discovery_configuration_gate@1`; this reuses `directive_confirmation` for discovery scope
  only and carries no amount, currency, product-context authority, or spend approval.
- The final scope is pinned once in append-only `project_run_discovery_configuration`. Run identity
  includes its canonical digest. Retry/concurrency reuses the same run and same receipt.
- Current Exa Websets acquisition reads the run receipt, packs all confirmed must/exclusion rules
  into bounded Exa criteria, and enforces the 50-account ceiling. Historical receipt-less runs keep
  their explicit legacy Exa strategy path.
- Active immutable resources are Head-of-ABM `v31`, Stage-0 skill `v18`, and Recipe #0 `v12`.
  Earlier resource bytes remain untouched.
- Exact model `openai/gpt-5.6-terra` now defaults to provider reasoning effort `high`; other GPT-5.6
  model ids retain the prior `none` baseline unless explicit config overrides them.

## Review defects found and fixed

- Live migration initially exposed SQLAlchemy interpreting literal `:v` as a bind parameter and
  asyncpg rejecting multi-statement prepared DDL. The revision now constructs the ICP ref safely
  and executes each function/trigger DDL statement separately.
- Durable JSON arrays were rejected by the strict tuple contract. One JSON-mode parser now handles
  both approved gate snapshots and stored run receipts while continuing to reject coerced scalar
  types.
- The restricted Stage-0 trial correctly withheld the new scope gate but the skill mistakenly made
  it mandatory, dropping the whole skill. The gate remains withheld while the shared procedure is
  still disclosed.
- Receipt immutability now rejects both update and delete. The database validator fails closed on
  absent/wrong JSON fields, malformed/duplicate criteria, stale/erased gates, gate-answer digest
  drift, and foreign answer authority; application reads independently recompute the configuration
  digest.
- Criteria and search intent are canonicalized before hashing; planning policies cannot configure
  a default above their maximum.

## Verification

- Ruff on all touched Python and migration files: green.
- Mypy on the new planning/run/Exa/gateway sources: green.
- Focused contract/catalog/registry/recipe/toolbelt/Exa/gateway matrix: green (DB-independent tests
  plus expected DB skips).
- Stage-0 ICP gate lifecycle, confirmed-run v2/v3, budget-control, and installed direct-SQL gate
  authority tests: 29 passed against an isolated database.
- The v3 integration test covers ambiguity -> 50-account proposal -> real human gate answer -> one
  immutable receipt -> retry-stable run.
- Alembic has one head `064ad0f43519`; clean upgrade -> base downgrade -> head upgrade passed on a
  newly named database. Both disposable Slice-4 databases were verified idle and removed after
  testing.
- Frontend: 302 tests passed; ESLint, design-system build, and Next production build passed.
- Browser/provider acceptance was not run in this implementation slice. The next checkpoint should
  exercise automatic 10-account and revised 50-account discovery through browser -> API -> DB ->
  Exa evidence.
