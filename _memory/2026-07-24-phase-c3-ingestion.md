# 2026-07-24 — Phase C3 raw-material ingestion implemented

## State

- Branch renamed to `platform/c3-ingestion`.
- Started from the frozen C0 head `421848f`.
- All C3 work remains uncommitted at the user's request.
- No central tool registration, projection aggregation, cross-lane API construction, spec-index
  status edit, or Alembic merge revision was added.

## Implemented

- Shared C3 IDs/status/reference-only contract in `clue_core.ingestion`.
- Frozen `IngestionPolicy` in `clue_config.ingestion`.
- Random-hash Alembic revision `5ab2d13ca389` with `ingestion_job` and
  segment-addressable `ingestion_segment`.
- Text/Markdown, PDF, DOCX, PPTX, and injectable raster OCR adapters. OOXML reads have bounded
  uncompressed XML size; OCR defaults to local Tesseract behind `OcrBackend`.
- `clue_research.ingestion` engine/store/models:
  - content/context dedupe over live jobs;
  - raw artifact before extraction and canonical extracted artifacts before claims;
  - stable canonical character locators and evidence-backed claim refs;
  - self/product trust eligible at tier 1; target assertions capped at tier 3;
  - tenant-private writes, field/entity validation, explicit contact-facet use class, and mandatory
    production `ClaimTagger` before contact insert;
  - C4-owned born-correct product scope through injected `ClaimConstructionRoute`;
  - preferences/project instructions/unmapped concepts routed by injected, idempotent seams;
  - paid adapters gated through the existing `SourceGate` before provider execution;
  - row-locked normalization and claim stages, committed segment checkpoint, retry without
    re-normalization, and savepoint-backed all-or-nothing claim insertion;
  - fail-closed DSAR routing for claim-producing jobs, live C3 artifact ref counting under the
    artifact lock, post-erasure re-upload, and no resurrection by retry.
- Lane-local `submit_ingestion`, `retry_ingestion`, raw-byte upload router, and
  `ingestion_status`. The upload transport has injectable workspace/actor auth dependencies,
  bounded streaming reads, toolbelt invocation, reference-only responses, and typed refusal maps.

## Verification

- `make check` without DB: `1323 passed, 977 skipped`; ruff, mypy, and all 23 import contracts
  passed.
- Isolated disposable Postgres on port 55433:
  - `make db-smoke` passed upgrade-to-head, downgrade-to-base, and re-upgrade;
  - all 10 C3 DB tests passed;
  - full DB-enabled `make check` passed: `2280 passed, 20 skipped`, ruff, mypy, and 23 import
    contracts.
- `uv run alembic heads`: one head, `5ab2d13ca389`.
- `git diff --check`: passed.
- The disposable C3 container was stopped and auto-removed. The `dar-es-salaam` workspace's
  existing `clue-postgres` container was not modified.

## Integration-owned follow-ups

1. Register the two C3 tools and include the upload router at the API composition root.
2. Aggregate `ingestion_status` in the projection router/export surface.
3. Inject C2 proposal routing and C4 memory/project-state/product-aware claim construction.
4. Inject the production contact `ClaimTagger`, paid-extractor `SourceGate`, and compliance
   `ClaimErasureRoute`.
5. After C1/C2/C3 integrate, create an Alembic merge revision only if the combined graph has
   multiple heads, then run the shared Step-4 journeys.
