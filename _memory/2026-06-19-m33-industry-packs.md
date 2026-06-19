# 2026-06-19 — M3.3 Industry Packs Framework (ENG-115)

## Goal
First submodule of M3 (ICP & Research-Schema Compiler). Branch
`akeshri516/eng-115-m33-industry-packs-framework-field-set-source-profile` (Linear-named, by user
request, so git ↔ Linear stay in sync). Build order for M3: M3.3 → M3.1 → M3.2 → M3.4, pausing for
user review after each submodule.

## What M3.3 delivers (staged-flow §9 "two prior sets" per pack)
A pack catalog + registration framework on top of the M1 substrate. A pack carries:
1. **field-set half** — `<pack>.*` `field_definition` rows authored into the M1.3 registry by
   REUSING `claimstore.{register_field, load_pack, SeedField, list_fields, get_field}` (packs are
   authors, not a parallel store — DRY). `get_pack_field_set` = `list_fields(pack=namespace)`.
2. **source-profile half** — versioned config tables (NOT the `config/` pydantic seam — that's
   M4-owned and a different shape). Weighted `source_key` priors per (pack, optional field_class),
   plus per-client/per-ICP overrides (override > pack default). `source_key`s are opaque STRING
   refs into M4's `source_manifest` namespace (M4 not built; validation late-bound via
   `validate_pack(..., known_source_keys=...)`).

## Files
- `alembic/versions/0005_pack_catalog_source_profile.py` — `pack`, `source_profile`,
  `source_profile_override` tables. Reuses the M1.3 `field_class` PG enum (NO new enum → no
  enum-parity burden). `weighted_sources` JSONB `[{source_key,weight,rank}]`. Unique slots use
  **`NULLS NOT DISTINCT`** (pg15+) so a NULL field_class/icp_key is ONE slot (a plain UNIQUE treats
  NULLs as distinct). `id bigint GENERATED ALWAYS AS IDENTITY` PK.
- `src/clue_research/icp/source_profile.py` — `SourceWeight`(high/medium/low ordinal + `.prior`
  float), `WeightedSource`, `ResolvedSourceProfile` (`.default` + `.by_field_class` +
  `.for_field_class()` fallback); `register_source_profile`, `register_source_profile_override`,
  `get_source_profile` (resolution: latest version per slot via `DISTINCT ON`; override replaces
  slot whole; matching icp_key > client-wide NULL icp_key). `is_valid_source_key` public helper.
  `SourceProfileRedefinitionError` (append-only; idempotent identical re-register).
- `src/clue_research/icp/catalog.py` — `Pack`/`PackSourceSlot` (frozen dataclasses, authoring),
  `PackRecord` (pydantic read DTO); `register_pack_catalog` (validate → upsert pack row →
  `core.register_pack(namespace)` activating the dormant seam → `load_pack` → register source
  slots; idempotent); `list_packs`/`get_pack`/`get_pack_field_set`/`get_pack_source_profile`/
  `validate_pack`. `PackRedefinitionError`, `PackValidationError`, `UnknownPackError`.
- `src/clue_research/icp/packs.py` — 3 starter packs as data (frontier_ai, healthcare_practice,
  data_infra) with source weights VERBATIM from staged-flow §7c; `load_starter_packs`.
  `frontier_ai` also contributes `account.resonance.research_prestige` (pack=None canonical) to
  prove a pack can register a resonance/facet field-class (Doc C §2; acceptance crit 7).
- `src/clue_research/icp/__init__.py` — public seam (re-exports).
- `tests/icp/{conftest,test_models,test_packs_framework}.py` — 19 tests (one per acceptance
  criterion + pure model tests). Harness mirrors claimstore (rollback_conn, require_icp_db, reuses
  tests.db.conftest run_async/_db_available).

## Key decisions
- **pack_key ≠ namespace** (conventions §3): `healthcare_practice` (pack_key) has field-key
  namespace `healthcare`. `field_definition.pack` stores the NAMESPACE; NO FK to `pack.pack_key`.
- **Source profiles → Postgres tables, NOT `config/`.** Config reader analysis: `config/schema.py`
  `SourceProfile` is M4-owned, flat per-pack weights, in-memory `OverlayStore` (no durable
  append-only versioning). M3.3 needs durable, versioned, FK-from-icp_spec, M13-writable rows.
- **icp/ MAY import claimstore** (the shared substrate). The `icp/README.md` stub said "only
  core/config/obs" — that was WRONG/self-contradictory; authoritative M0.1 + conventions §2 +
  the actual import-linter contracts (no contract restricts icp→claimstore; independence covers only
  resolvers/adapters/verification/discovery_scoring) all permit it. **Corrected the README**
  (flagged for user). icp does NOT import `clue_research.db` (functions take `conn` param like
  claims.py/registry.py).
- weight stored as ordinal string in JSONB (high/medium/low per docs); M13 can later write numeric
  behind the same JSONB column with no migration.

## Verification (live DB: container `clue-postgres-m1` on :5433, CLUE_DATABASE_URL set)
- `make check` GREEN: ruff format+check, mypy --strict (57 files), import-linter (5/5 KEPT),
  **244 passed** (225 M1 + 19 new icp). `make db-smoke` (up→down→up) clean — 0005 reverses.
- Gotcha hit & fixed: `COALESCE(CAST(field_class AS text),'*')` in a unique-index expression failed
  ("functions in index expression must be marked IMMUTABLE" — enum→text cast is STABLE). Switched to
  `NULLS NOT DISTINCT`.
- Gotcha: `test_db_migrations::test_no_domain_tables_at_m0_head` failed because the shared :5433
  container had STRAY `account_entity`/`contact_entity` tables (cruft from a prior session, created
  by NO committed migration). Dropped them; not an M3.3 issue. (If reusing that container, watch for
  cruft.)

## State / follow-ups
- M3.3 staged (`git add -A`), NOT committed yet (running adversarial review first, then commit).
- ENG-115 → In Progress in Linear (move to Done after commit + user review).
- Adversarial review workflow `wf_e4511141-cd2` running at time of writing — apply confirmed
  findings before commit.
- After commit: PAUSE for user review before starting M3.1 (ENG-104).
- For M3.1: `icp_spec` table will FK/reference the pack catalog (validate enabled packs) and embed
  the scoring-rubric slot (M3.4). The source_profile_override tables here are referenced from
  icp_spec per spec.
