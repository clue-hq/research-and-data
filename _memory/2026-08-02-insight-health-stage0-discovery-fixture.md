# 2026-08-02 — Insight Health/Aura Stage-0 discovery fixture

Branch: `platform/c8-exa-sumble-discovery`.

Implemented Slice P0 from the M6A Exa/Sumble discovery spec. The fixture prepares a realistic,
already-confirmed Stage-0 handoff so discovery can be tested without re-running Stage 0.

## Delivered

- `platform/api/clue_api/trial/discovery_fixture.py`: network-free, deterministic builder over
  prior Firecrawl search/scrape payloads.
- `scripts/08_seed_discovery_fixture.py`: requires an explicit migrated database URL and writes a
  non-authoritative reference bundle under `.context/discovery-fixtures/insight-health-aura/`.
- `tests/api/test_discovery_stage0_fixture.py`: pure input/evidence tests plus real
  Postgres/filesystem-artifact integration and exact replay/count checks.
- M6A spec and `scripts/README.md` document scope, commands, provenance, and pass/fail gate.

The fixture contains the Insight Health workspace/brand, Aura AI product, discovery project, human
website-onboarding receipt, four official-page artifacts, seven official-site Client-KB facts plus
the KB-version marker, a confirmed independent-U.S.-neurosurgery/spine ICP, immutable product
context, READY discovery-spend decision, and one active project run stopped at `discovery`.

Official-site facts are intentionally tier-2 scrape claims with exact source/evidence/artifact
provenance and `unverified` status. Published savings, ROI, compliance, and testimonial/customer
relationships are not treated as independently verified truth.

## Durable acceptance evidence

- Firecrawl searches were performed before seeding; the builder itself makes no network call.
- Isolated host database: `clue_discovery_fixture` on `127.0.0.1:5432`, migrated to head
  `933c7b604f1c`.
- Actual harvested pages seeded twice. Both runs returned the same client/claim/context/readiness/
  project-run ids.
- Persisted counts after replay: 8 product-scoped client claims (7 facts + KB marker), 4 artifacts,
  1 ICP version, 1 product context, 1 readiness decision, 1 project run.
- Every one of the 7 website facts has tier 2, scrape, unverified, `firecrawl_site`, artifact key,
  and evidence span; project run is `discovery/active`.
- Convenience refs: `.context/discovery-fixtures/insight-health-aura/fixture.json`.

## Verification

- `.venv/bin/ruff format --check <changed Python files>` — pass.
- `.venv/bin/ruff check <changed Python files>` — pass.
- `.venv/bin/mypy platform/api/clue_api/trial/discovery_fixture.py` — pass.
- `.venv/bin/pytest tests/api/test_discovery_stage0_fixture.py -q` without DB — `1 passed, 1
  skipped`.
- Same test with `CLUE_DATABASE_URL=.../clue_discovery_fixture` — `2 passed`.
- Initial real-DB run caught an invalid readiness actor value; changed it to the schema-approved
  `system` value, then reran green.
- `make check` remains open on 17 pre-existing repository formatting drifts outside this slice; no
  changed fixture file is among them.

Operational note: the Docker-daemon Postgres and the host-bound Postgres expose different database
catalogs in this environment. On 2026-08-02 the unused, empty `clue_discovery_fixture` database in
the Docker container was verified to have zero public tables and zero active connections, then
dropped. The authoritative host-bound `clue_discovery_fixture` remained intact with all eight
product-scoped fixture claims. No container or unrelated database was removed.

## Next boundary

Slice D0 subsequently landed as a separate local commit; see
`_memory/2026-08-02-m6a-d0-contract-freeze.md`. P0 is test setup; it does not authorize or perform
Exa/Sumble provider spend and does not relax the closed durable-batch/seal requirement.
