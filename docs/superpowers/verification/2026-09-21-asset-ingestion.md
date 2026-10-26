# Asset ingestion implementation and verification

Implemented in San Diego on `asset-ingestion/improvements` against the unchanged
[authorized design](../specs/archive/2026-09-21-asset-context-and-bulk-upload-design.md).
The full Fredericton ICP-definition transcript was read before implementation.
Comparison/publication target remains `origin/integration/design-improvement`.

## Delivered

- One structured asset analysis with observations separated from source-scoped
  interpretations, reusable guidance, provenance and explicit uncertainty.
- Field-level human overrides, reset-to-suggestion, input fingerprints, revisions,
  stale/queued/analyzing/ready/failed/unsupported states and retry diagnostics.
  Legacy captions remain readable; legacy human captions migrate into overrides.
- Every eligible ingested image enters continuous processing, with 15 concurrent
  slots by default. Shared Redis capacity leases coordinate asset jobs using the
  same provider credential. Existing provider retries, halt behavior and spend
  accounting remain in the shared caller; concurrent totals are protected.
- Website DOM/CSS occurrences and surrounding text, ad copy and creative provenance,
  and explicit upload notes feed the same worker. Ad DNA remains collection-level.
- Upload bytes, records, metadata, idempotency and durable fleet scheduling use
  existing custody/governed-tool seams. Completed analyses survive partial failure;
  failures and exhausted fleet recovery remain visible and individually retryable.
- Design runs pin effective metadata in Postgres. Scene and website modes search
  the complete paginated inventory and inspect the same context revision. They fetch
  bytes on inspection/placement; selected reference images carry their context.
- Kit-independent paginated Assets reads and batched metadata; independent Type,
  Used as and Source filters; durable editing/reset; a floating multi-file dialog
  with previews, selection, classification, actual server limits and per-file status.
  The screen owns its upload queue, which survives closing the dialog. A BFF
  precondition prevents queued uploads following a changed workspace cookie.

PNG, JPEG, WebP, SVG and GIF are advertised. Animated originals are retained;
analysis records that it inspected the first frame. AVIF is not advertised.
No engine source changed and no historical paid backfill ran.

## Database and runtime isolation

The user-requested source was the populated `clue_san-salvador` database in
`clue-pg-istanbul` on port 55040. The similarly named container's default database
was not the source. Dump/restore created `clue_san_diego` in the independent
`clue-pg-san-diego-assets` container at `127.0.0.1:55170`.

Verified clone counts: 2,622 workspaces, 916 design assets, 63 descriptions.
Migration `403bce58bdcf` was applied to the clone after a clean migration smoke;
these counts remained intact. The source database was unchanged. This operation
cloned Postgres, not historical filesystem/blob contents.

Tests used `clue_san_diego_assets`; migration smoke used the separate clean
`clue_san_diego_migration`. Redis is `clue-redis-san-diego-assets` on port 65170.
Root local configuration points at the clone and isolated Redis. No fleet worker
was started against the cloned database, whose historical tasks must not be
mistaken for newly authorized ingestion work. The temporary fixture frontend and
browser were stopped after verification; Postgres and Redis remain available.

## Verification

- 26 focused domain/DAL/authority/capacity checks passed, including continuous
  137-image processing, 15-slot refilling, independent persistence, replay,
  concurrent upload idempotency, rollback, overrides, tenant isolation and frozen
  run snapshots. Additional final DAL/capacity regression run: 5 passed.
- Ingestion/ads/spend suite: 67 passed, 1 existing optional helper test skipped.
  Concurrent spend test retains all 137 charges in the shared scope.
- Existing scene/web discovery checks: 53 passed. Added an explicit asset beyond
  501 recent entries: both modes discover and inspect the same revision, and
  searching triggers no byte materialization. API inventory check covers 1,001
  records over three pages.
- Five advertised-format integration cases passed through real custody, preview,
  structured-worker persistence, override/reset, original-byte retrieval, real
  scene PNG rendering and website HTML asset URLs. They include transparent SVG
  and animated GIF/WebP. Model responses in these format tests are deterministic.
- Updated composition tests create genuine durable run rows. The two previously
  stateless ad-reference tests and the lazy scene materialization test passed after
  updating their fixtures to the new contract. Explicit reference selection remains
  preserved. No runtime fallback was added for a missing durable run.
- Frontend: all 106 Brand Context tests passed; focused repository/queue/BFF run
  passed 23 tests, including 251 assets without a kit, 100-ID metadata batches,
  mixed upload failure/retry and workspace-switch rejection.
- Frontend token generation, lint and production build passed. Lint retains two
  pre-existing unused canvas-helper warnings. Changed root Python files pass Ruff;
  import contracts: 28 kept, 0 broken; Python compilation passed.
- Migration `upgrade head → downgrade base → upgrade head` passed on a clean
  San Diego-only database; Alembic has exactly one head.
- Fixture browser checks at localhost:3039 covered multi-file selection, previews,
  selective bulk classification, mixed supported/unsupported rows, upload status,
  and close/reopen preservation. A filter/header overlap found there was fixed.

## Live quality sample and limits

Three small OpenRouter calls used `deepseek/deepseek-v4.1-flash`, totaling
approximately $0.005407. The initial strict-schema response was structurally valid
but incorrectly described a portrait. A plain vision probe identified the actual
synthetic analytics image. The revised production request requires parameter
support, sets temperature zero, and prioritizes pixel observation; its structured
result correctly transcribed all four text strings and described the CTA, chart,
colors and layout. Audience remained a hypothesis and publication status absent.
This is a small quality sample, not a broad model-quality benchmark.

Local `.context/asset-provider-*` and `asset-vision-probe-*` files preserve the failed
and successful samples. The latter two calls drained to the isolated test database;
the first direct smoke's cost is retained in its local result rather than the DB ledger.

An authenticated browser-to-provider acceptance run was not performed. Browser
verification used fixtures; API/DB/helper and BFF checks were exercised separately.
The fixture shell exposes an existing sidebar-projects error when authentication
is disabled; it is outside this asset change.

Full root type-check is not green: the existing
`platform/api/clue_api/design_leg_wiring.py:1627` assignment treats a `Mapping` as
a `dict`. New asset code has no reported root mypy errors. No claim is made that
the entire repository test suite or full `make check` passed.

Local implementation commits: `9cc82d08d` (backend/worker/agent) and `8e725c2c2`
(Assets UI/repository/BFF). Nothing was pushed or published.
