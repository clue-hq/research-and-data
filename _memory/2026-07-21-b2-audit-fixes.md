# 2026-07-21 — B2 audit fixes (branch `platform/b2-storage`, after the lane close-out)

A critical code audit of the B2 lane (transcript attached in-session) found 8 issues — 1–6
blocking integration, 7–8 medium. All 8 are fixed in three commits on top of `153927d`:

- `91bc74e` — findings 1–4, 7 (storage substrate + DSAR)
- `ff560be` — findings 5–6 (run-scoped snapshots + scrapling economics)
- `4a9b383` — finding 8 (millicredits)

## The lifecycle design (findings 1/3/4/7, one coherent mechanism)
The **artifact row is the serialization point**; migration `d0c2e361f7d4` adds
`artifact.purged_at`, the erased-unpurged partial index, and the two tenancy CHECKs.

1. **Writers: row before blob.** `flush_snapshots` = `record_artifact` (upsert, now
   `ON CONFLICT DO UPDATE SET erased_at/purged_at = NULL` — takes the row lock AND resurrects an
   erased row, finding 4) → `storage.put` only if `not exists`. The sink is **never drained by a
   flush** — captures live for the run; a rolled-back transaction's retry re-flushes and
   reconverges (finding 1 upload half). `SnapshotSink.clear()` is end-of-run hygiene only.
2. **Erasure: two-phase.** Phase 1 in-txn: `erase_if_unreferenced(conn, key)` — `SELECT … FOR
   UPDATE` on the artifact row, recount live citers under the lock (finding 3: two erasures of
   the last two citers serialize; a concurrent claim insert blocks via FK `KEY SHARE` vs
   `FOR UPDATE`), then `mark_erased` (which also **nulls `source_url`**, finding 7). Phase 2
   post-commit: `purge_erased_artifacts(conn, storage, keys=…)` — re-check under the lock,
   `storage.delete` while holding it, stamp `purged_at`; if a claim re-cited in the window it
   **un-erases instead of deleting**. DSAR ops purge their own keys after their txn commits;
   `RetentionSweep.sweep_expired` purges with `keys=None` (scan-all → crash recovery).
   Without an injected backend the intent (`erased_at`) is still stamped — a later storage-wired
   sweep converges (test updated to assert exactly this).
3. **Orphans:** `StorageBackend.list_blobs()` (new, fs+S3) + `sweep_orphan_blobs(conn, storage,
   grace=24h)` collects blobs with no artifact row older than the grace window (abandoned
   rolled-back uploads). Not scheduled anywhere yet — operator/api-root task.
4. **Tenancy (finding 2), structural:** CHECK `artifact_key_encodes_scope`
   (`storage_key = COALESCE(workspace_id,'public') || '/' || content_sha256`) + CHECK
   `claim_artifact_scope_compatible` (claim may cite `public/…`, its own workspace's key, or —
   when the claim itself is public-footprint — its capture-context workspace's key; the audit's
   cross-tenant citation is now an IntegrityError). Cross-tenant *serving* of a ws-scoped key on
   a public claim remains the presign-policy follow-up (lane note #4).

## Run-scoped snapshots (finding 5)
`clue_storage.context`: `bind_snapshots(sink, storage)` CM + `current_snapshot_sink()` /
`current_storage()` (ContextVars — task-local, so concurrent runs are isolated; proven in
`tests/storage/test_context.py`). `resolve_field` / `resolve_fields` / `run_pipeline` default
their `snapshots`/`storage` params from the ambient binding; the waterfall re-binds its resolved
sink around `resolver.resolve` so capture and flush share one sink by construction;
`ScrapeResolver` reads the ambient binding when constructed sink-less (the production shape —
the registered resolver must NOT hold a sink). **api-root wiring is now: wrap each run in
`bind_snapshots(SnapshotSink(workspace_id=run's ws), storage)` — no per-callsite threading.**

## Scrapling economics (finding 6)
New seed manifest `scrapling_site` (tier 2, **cost 0**, provider `scrapling`, adapter key
`scrapling_html`). `register_scrape_resolver` picks the source key from the backend
(`isinstance(backend, ScraplingScrapeBackend)` → scrapling_site; else firecrawl_site) and
returns the bound key. Stage-0 tier plans name both siblings; the unselected one is a
NO_RESOLVER walk-past at zero spend. Claims/cost/estimates/provider yield now attribute
truthfully.

## Millicredits (finding 8)
`to_millicredit_burn_down` derives `remaining = max(cap − spent, 0)` in credit space when
`has_cap` (impossible-balance case cap 0.10¢/spent 0.05¢ now shows 1/1/0, not 1/1/1). New
`load_millicredit_burn_down(conn, panel, workspace_id=…)` = the combined rate+panel read
(`None` when no rate configured).

## Verification
- `make check` green ×2: ruff · mypy (290 files) · import-linter 18 kept / 0 broken ·
  **2026 passed** (was 2006 pre-fix — ~20 new tests).
- Full suite green on a clean throwaway DB (`clue_b2_fix`, dropped after).
- Alembic up → down → base → up green on throwaway `clue_b2_smoke2` (dropped); single head
  **`d0c2e361f7d4`** (chain … → d091e3962833 → b2df6d050fc5 → d0c2e361f7d4).
- fs↔S3 contract suite (incl. new `list_blobs` test) green on both legs (MinIO reachable).
- Workspace DB `clue_puebla` upgraded to the new head. Known pre-existing quirk (also in the
  audit transcript): a handful of sources/resolvers tests fail when run **solo** against the
  long-lived DB (committed seed-row residue vs in-test re-registration, e.g. `apollo`
  `SourceManifestRedefinitionError`); full-suite runs and clean DBs are green.

## Residuals / follow-ups (documented, non-blocking)
- **Cache-hit re-cite window:** a per-run `ArtifactCache` hit stamps `artifact_key` without
  re-capturing; racing an erasure it can land a claim citing a just-purged blob. The purge's
  un-erase handles the marked-but-unpurged case; the purged case is edge-of-edge (per-run cache
  lifetime vs DSAR timing). Revisit if caches ever outlive runs.
- **`sweep_orphan_blobs` needs a scheduler** (api-root/ops), like the retention sweep.
- Sink/cache are **transaction-scoped on rollback**: a caller that rolls back and retries keeps
  the same sink (it re-flushes) but must treat a cache that stamped keys from a rolled-back
  flush with care — the FK fails loud, never silent.
- api-root wiring task (lane note #1) updated: inject storage into DSAR/sweep AND
  `bind_snapshots` per run; `register_scrape_resolver` without a sink.
