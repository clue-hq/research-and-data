# 2026-07-21 — B2 storage lane built (branch `platform/b2-storage`)

Worktree `puebla`, branch `platform/b2-storage` cut from the treaty commit `e615e81`. The full
B2 lane (PB-B2 spec) is implemented and gate-green; **awaiting integration** onto
`platform/workspace-restructure` in the treaty order B2 → B3 → B1 (§4). Local commits only.

## Founder rulings this session (recorded in `docs/specs/PB-B2-storage.md`)
1. Claim↔artifact link = additive nullable ref column on `claim` (not a join table) —
   implemented as `claim.artifact_key text FK → artifact.storage_key` (the *deterministic*
   content-addressed key, so the sync chain stamps before any DB write; no id-remap problem).
2. DSAR × dedup = **refcounted deletion**, workspace-scoped keys (`{ws|public}/{sha256}`,
   never cross-tenant dedup). Blob deleted only at zero live citers; artifact row survives with
   `erased_at` as audit (no personal content).
3. Millicredit groundwork = rate mapping + read path only; **no ledger table** (A7's shape not
   guessed). Zero diffs under `durable/` — verified empty against branch base.
4. S3 leg = MinIO (real S3 API); SDK = aioboto3 confined to `clue_storage/s3.py` (contract 4c).
5. Snapshot boundary = the modality-adapter fetch seam only (tier-1 API JSON not snapshotted).
   **Plus scrapling** as a second, credit-free `ScrapeBackend` behind `CLUE_SCRAPE_BACKEND`
   (default `firecrawl` — behavior unchanged).
6. In-lane wiring via optional injected `StorageBackend` (the `Freshness` pattern); **api-root
   injection is an integration task** (see follow-ups).

## Commits (in order, after the spec commit `7ef4342`)
- `eea50b1` B2.1 — `libs/clue-storage`: async `StorageBackend` (put/get/delete/exists/presign),
  `content_address`/`artifact_key`, `FsStorage` (atomic, traversal-guarded, `file://` presign
  placeholder), `S3Storage` (lazy aioboto3; endpoint covers S3/R2/MinIO),
  `storage_from_settings` (fails loud on s3-without-bucket). `CLUE_STORAGE_*` settings +
  S3 secrets. Root-pyproject registration + 2 new import-linter contracts (18 total).
- `d974bce` B2.2 — migration `d091e3962833`: `artifact` table (REQ-07 columns + `erased_at`;
  UNIQUE `storage_key`; sha256 CHECK) + `claim.artifact_key` (immutable — append-only guard
  grown in the 0004/0008/651b lock-step; partial index for the refcount). DAL in
  `clue_storage.artifacts` (`record_artifact` upsert / `get_artifact` / `live_claim_count` /
  `mark_erased`).
- `530916e` B2.3 — snapshot wiring: `SnapshotSink` (sync capture — pure sha256 in the sync
  `run_chain`) + `flush_snapshots` (async: blob + row **before** claim insert, FK order).
  `core.Claim.artifact_key` (append-only contract delta); claimstore insert/select;
  `CachedArtifact.artifact_key` (cache hits keep the ref); `run_pipeline`/`run_chain`/waterfall
  `resolve_field` optional params; firecrawl `ScrapeResolver(snapshots=…)`.
- `4c1d85e` B2.4 — `ScraplingScrapeBackend` (scrapling `Fetcher` + markdownify, lazy behind
  `adapters/concrete` — Rule 4 additions + 2 sanctioned lazy-edge ignores);
  `Settings.scrape_backend`; `default_scrape_backend()` used by `register_scrape_resolver`
  when no scraper injected. **Live-verified** (scrapling 0.4.11 fetched a real page end-to-end).
- `4218550` B2.5 — DSAR hook in `_apply_tombstone` (the single chokepoint all erase/objection/
  retention paths funnel through): after audit+supersede, zero-refcount → `storage.delete` +
  `mark_erased`; metric `research.compliance.dsar.snapshot_erased`. `DataSubjectRightsImpl` /
  `RetentionSweep` take optional `storage`. Jana/Raj shared-snapshot test proves last-reference
  semantics. (`build_tombstone` deliberately does NOT copy `artifact_key` — the tombstone must
  not pin the blob.)
- `153927d` B2.6 — migration `b2df6d050fc5`: `millicredit_rate` (UNIQUE **NULLS NOT DISTINCT**
  `(workspace_id, version)` — the M9.1 NULL-slot gap closed up front) +
  `review/millicredits.py` (deterministic loader; `to_millicredits` exact-Decimal integer
  conversion, 1 credit = 1000 millicredits; `to_millicredit_burn_down` pure view over the
  M13.4 `CostBurnDown`).

## Verification (final state)
- `make check`: ruff · mypy (289 files) · import-linter **18 kept, 0 broken** · offline suite
  **1181 passed** (baseline was 1158).
- Full DB suite green on `clue_puebla` **and on rerun** (both exit 0, zero FAILED/ERROR).
- `make db-smoke` equivalent up→down→up green on throwaway `clue_b2_smoke`; single head
  `b2df6d050fc5` (chain: `98422adaaa38 → d091e3962833 → b2df6d050fc5`).
- fs↔S3 exit gate: the parametrized `tests/storage` contract suite runs green under FsStorage
  AND S3-on-MinIO, differing only in the `Settings` object.
- Recipe #1: scripts/01–06 completed end-to-end in stub mode (02 takes the chained
  `--client-entity-id` from 01's output — that's by design, not a failure).

## Environment (this workspace)
- Postgres 16/pgvector docker `clue-pg-puebla` on port 23763, db `clue_puebla`; Redis 7 docker
  `clue-redis` on 6379 (db idx 3); **MinIO** docker `clue-minio-puebla` on port 29000
  (clueminio/clueminio123, bucket `clue-test-artifacts`). `.env` carries
  `CLUE_TEST_MINIO_ENDPOINT=http://localhost:29000` — the S3 test leg skips gracefully when
  unset/unreachable (the reachable-DB-gate pattern).

## Follow-ups (integration-time, for the integrator on `platform/workspace-restructure`)
1. **api-root wiring commit for B2** (treaty §3.4): build one `StorageBackend` via
   `storage_from_settings()` at the composition root and inject it into (a)
   `DataSubjectRightsImpl`/`RetentionSweep` (`storage=`), (b) the deep-run/waterfall call
   sites (`resolve_field(snapshots=…, storage=…)` with a per-run `SnapshotSink(workspace_id=run's
   workspace)` shared with `register_scrape_resolver(snapshots=…)`), (c) any
   `run_pipeline(persist=True)` writers (M8) once they exist.
2. `alembic merge` with B3/B1 heads at integration (expected 3 heads; this lane contributes
   `b2df6d050fc5`).
3. Production deploy needs `clue-storage[s3]` extra (aioboto3) when `CLUE_STORAGE_BACKEND=s3`;
   scrapling live use needs nothing beyond the declared deps (basic `Fetcher` — no
   `scrapling install` browser download needed).
4. Public-footprint claims currently snapshot into the sink's constructed scope; if a run wants
   public-shared snapshot amortization across workspaces, that's a future policy decision (keys
   are already `public/{sha}` when the sink has no workspace).
5. `presign` on fs returns a `file://` placeholder — real signed-URL serving is the frontend
   phase (REQ-07 treaty §2.8), nothing consumes presign yet.
