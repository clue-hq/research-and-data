# 2026-08-14 — Stage-0 durable official-site crawl C1

## Outcome

- C1 is complete on `platform/onboarding-integration`; C2 has not started.
- Random-hash revision `6e7ba5968751` creates the eight frozen crawl tables and the missing
  `recon_run(id, workspace_id)` anchor. The migration is hand-written, reversible, and leaves one
  Alembic head.
- `PostgresCrawlRepository` implements the complete frozen repository protocol through
  transaction-sized, workspace-scoped operations. PostgreSQL `now()` owns deadlines/leases; page
  generation plus worker identity fences renewal, dispatch, provider results, persistence,
  completion, disposition, and recovery.
- The logical tier-2 `official_site` source is additive, provider `clue`, account-scoped, and
  zero-cost per derived claim. Historical `firecrawl_site`/`scrapling_site` entries are unchanged.

## Durable behavior and decisions

- PostgreSQL is the only frontier/ledger. Claiming is serialized per crawl run with a transaction
  advisory lock, enforces run/host capacity, and uses `FOR UPDATE SKIP LOCKED` for candidate rows.
- Exact parser-batch replay is deduplicated by a hash of the canonical batch plus ordinal. Repeated
  identical links at different batch positions remain separate URL observations while sharing one
  page node.
- Prepared attempt expiry fails the attempt and requeues the page. Dispatched unresolved expiry
  becomes `spend_unknown + reconciliation_pending`. Recorded success expiry keeps
  `persistence_pending`. Recovery claims receive a fresh page generation without rewriting the
  original attempt generation. A reconciliation that remains ambiguous is quarantined (the frozen
  graph has no self-transition) while retaining `spend_status=spend_unknown` for audit/progress.
- Page snapshots retain one URL/attempt provenance row even when artifacts deduplicate by content.
  The page-owned latest-snapshot FK is deferred to permit atomic scoped deletion of the deliberate
  page/snapshot cycle; all other scope relationships remain immediate and fail closed.
- Corpus checkpoints are append-only. A trigger verifies lowercase sorted unique snapshot UUIDs,
  same workspace/run membership, live artifacts, and recomputes the canonical snapshot-set SHA-256.
- C1 accepts outgoing links at the frozen seam but does not invent URL policy outcomes; C2 must
  normalize/safety-check them and call `record_discoveries` before C5 completes orchestration.

## Verification

- Retained isolated databases:
  - `clue_c1_official_site_20260814_001`: broad-suite evidence; intentionally contains unrelated
    full-suite residue after the diagnostic run.
  - `clue_c1_official_site_20260814_final`: clean accepted C1 state at head.
- Clean `make db-smoke` passed on the final DB (`head -> base -> head`).
- `alembic heads/current`: exactly `6e7ba5968751`.
- Official-site C0+C1 suite: 21 passed. It covers 10-way atomic claiming, stale fencing, discovery
  replay/provenance, cross-workspace fail-closed access, paid ambiguity recovery, success persistence
  recovery, URL snapshots, and immutable checkpoints.
- Official-site + source-registry + discovery-scoring integration suite passed: 284 tests.
- Scoped Ruff, mypy, `git diff --check`, and all 25 import-linter contracts passed.
- Repository-wide `make check`: lint, 641-source mypy, and 25/25 contracts passed; the monolithic
  DB-enabled pytest run ended `4478 passed, 23 skipped, 35 failed`. The failures were diagnosed as
  pre-existing merged-design/agent-resource tests plus shared-DB test contamination. Two
  DB-independent examples reproduce alone; migration downgrade was blocked by prior tests leaving
  protected `entity_research_job` rows. The clean final DB smoke and affected suites pass.

## C2 handoff

- Implement conservative URL identity, SSRF/redirect/domain/MIME/size/robots policy, sitemap
  inventory, alias verification, and deterministic category/priority assignment.
- Preserve raw discovered URL separately from fetch key. Do not alter the eight tables or frozen
  repository/fetcher/materializer payloads without an explicit C0 revision.
- C2 should turn `PageFetchResult.outgoing_links` into policy-decided `UrlObservation` batches;
  C1 deliberately does not admit provider-returned raw links itself.
