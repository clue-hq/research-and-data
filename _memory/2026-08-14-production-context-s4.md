# Production context S4 — governed Client-KB reads

**Date:** 2026-08-14
**Branch:** `platform/onboarding-integration`
**Status:** HISTORICAL PRELIMINARY `@1`; reclassified by the amended S4-A–E roadmap

> Amendment: this note records the already-published `@1` implementation and composition. It does
> not mean amended S4 is complete. `@1` remains immutable compatibility evidence; S4-A/B are
> recorded in `2026-08-14-production-context-s4a-s4b.md`, and S4-C/D/E remain required for the
> frozen final `@2` contract, production cutover, and privacy/security/replay closure.

## Delivered

- Added `list_client_knowledge@1`: a bounded, effect-free reader over the exact account-wide
  Client-KB version pinned on the active turn. It supports topic, exact field, and opaque cursor
  filtering and consumes the S1 `client_knowledge_over_cap` cursor.
- Added `inspect_client_claim@1`: exact in-checkpoint claim membership plus bounded value,
  evidence, freshness, verification, source, and lineage metadata. Foreign, unknown,
  wrong-version, superseded, and retention-expired claims all return the same refusal.
- Workspace, project, and client remain constitution-derived trusted arguments. The new
  `client_kb_version` marker removes the version from model-authored schemas and restores it only
  from the S3 `client_knowledge` artifact domain pin (with the existing trusted trial focus-ref as
  a compatibility source).
- Source URL inspection exposes only the public origin and an exact-value SHA-256 digest; it does
  not expose credentials, query strings, fragments, or paths. Values, evidence, and provider/
  artifact refs are byte-bounded; no page body or provider call is reachable.
- Registered both tools centrally, retained both on trial and production surfaces, and advanced
  the immutable production resources to Head-of-ABM `v24`, Stage-0 skill `v11`, and Recipe #1
  `v7` with exact schema hashes and pin requirements.
- Extended the claim reader so S4 can prove historical version membership while still excluding
  retention-expired and explicitly superseded rows. Existing callers keep their prior default.

## Verification

- Fresh isolated PostgreSQL database: `clue_context_s4_20260814`, migrated to Alembic head
  `b2f815da0f31`. Retain it for review; it contains synthetic test-only state.
- Real claim-store/binding S4 acceptance:
  `CLUE_DATABASE_URL=postgresql+asyncpg://localhost:5432/clue_context_s4_20260814 .venv/bin/pytest -q tests/api/test_client_knowledge_tools_s4_db.py`
- The combined live-DB S4, central toolbelt, production read/bootstrap/turn, and projection matrix
  passed 41/41. The entire pilot-budget regression file also passed 14/14 on this same isolated
  current-head database.
- Focused authority/catalog/profile/recipe/schema tests passed. Repository-wide Ruff, mypy (662
  source files), and all 25 import contracts passed. The broad remaining suite passed with DB tests
  intentionally skipped after excluding three independently classified baseline files.
- The monolithic shared-environment run had five unrelated failures: three pilot-budget tests hit
  the shared database's stale `field_definition` schema (`research_scope` missing), while the
  logging-discipline and workspace-rename guards point to tokens already present at `HEAD`. The
  three DB failures pass on the isolated database; S4 did not change either static-guard file.
- `git diff --check`, recipe JSON validation, one Alembic head (`b2f815da0f31`), and targeted Ruff
  checks are clean.

## Decisions and boundaries

- These reads are deliberately zero-write, zero-provider-spend operations. Live provider traffic
  is neither needed nor permitted for S4; the authoritative acceptance is against durable
  PostgreSQL claims produced by the existing recon pipeline.
- S5 remains responsible for a durable multi-product catalog and human project-product selection.
  S6 remains responsible for refresh/observability/full production acceptance.
