# 2026-08-14 — Stage-0 durable official-site crawl C0

## Outcome

- C0 is complete on `platform/onboarding-integration`; C1 has not started.
- The binding child contract is
  `docs/specs/FI-stage0-durable-official-site-crawl-C0-contract.md`.
- Executable provider-neutral authority is `clue_research.official_site`; its canonical fixture is
  `tests/fixtures/official_site/c0_contract_fixture.json`.
- C0 created no crawl migration/table, made no network/provider/browser call, and did not enable a
  production crawl. Current Stage-0 behavior remains the historical homepage/field-oriented path.

## Frozen decisions

- Eight table names, all domain enums, run/page/attempt transition graphs, strict immutable
  Pydantic payloads, `PageFetcher`, `CrawlRepository`, and
  `OfficialSiteCorpusMaterializer` are frozen as contract version
  `stage0-official-site-c0-v1`.
- PostgreSQL is the only frontier/ledger and dispatch clock. `begin_attempt` persists a prepared
  operation key, and `mark_attempt_dispatched` commits the DB-time dispatch boundary before I/O.
- `spend_unknown` pages enter `reconciliation_pending`. A distinct
  `claim_reconciliation` acquires a new page generation without rewriting the original attempt
  generation and cannot authorize a second provider call.
- Recorded provider successes that lose their persistence lease remain `persistence_pending`; a
  distinct `claim_persistence` obtains a new fence and resumes artifacts/snapshots without
  re-fetching.
- Provider results separate exact page bytes/links from body-free attempt metadata. Content hashes
  deduplicate artifacts only; URL-level snapshots/provenance remain distinct.
- Logical new claims will use tier-2 source key `official_site`. Historical `firecrawl_site` and
  `scrapling_site` claims remain immutable; C1 seeds the new manifest and no history is rewritten.
- Fast/background remain phases and immutable checkpoints of one crawl run. Sitemap discovery does
  not claim link-graph depth. URL identity stays conservative.

## Spike disposition and retained prerequisites

- Removed/rejected provider-owned Firecrawl recursion, multi-page aggregation, process-local crawl
  caching, the crawl-specific materialization bypass, monolithic input/budget expansion, and
  adapter-local paid retry behavior.
- Retained the Firecrawl v4 SDK dependency and updated the historical backend to its verified
  single-page `Firecrawl(...).scrape(...)` surface.
- Retained provider-neutral non-blocking synchronous resolver execution through
  `asyncio.to_thread`, self-serve startup source-registry loading, caller-transaction Stage-0
  pre-spend-gate binding, and privacy-safe lane failure logging.
- Unrelated Clerk/profile/frontend worktree changes were left untouched and out of C0 scope.

## Verification

- Targeted C0/prerequisite verification: 35 passed, 37 DB-gated skipped because
  `CLUE_DATABASE_URL` was unset. All provider-neutral contract, installed-SDK surface, historical
  adapter, and startup-composition tests executed; the skipped waterfall/governed Stage-0 cases
  require the C1 isolated database lane.
- Relevant Ruff format/lint passed.
- Full mypy passed: 639 source files.
- Import-linter passed: 25 contracts kept, 0 broken.
- `uv lock --check`, JSON fixture parsing, and `git diff --check` passed.
- A direct SDK introspection confirmed the installed v4 client instance exposes callable
  single-page `scrape`; no request was sent.

## Handoff

- C1 owns one reversible random-hash Alembic migration plus workspace-scoped repository
  primitives matching the frozen child DDL/seams.
- C1 must add the `recon_run` workspace anchor only if absent, keep exactly one Alembic head, use
  composite workspace FKs (including artifacts), and prove atomic claim, stale-generation fencing,
  reconciliation claiming, and cross-workspace failure on an isolated database.
- Any C1 request to rename tables/states or change `PageFetcher`, `CrawlRepository`, or the
  materialization payload reopens C0 and requires a contract-version/fixture/doc delta.
