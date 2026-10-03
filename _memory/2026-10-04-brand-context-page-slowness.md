# 2026-10-04 — Brand-context page takes 30–60 s in production: diagnosis and fixes

Branch `perf/brand-context-load`, stacked on `perf/research-slowness-fixes` (PR #91) because design-api
uses the same `clue_storage` S3 backend whose shared per-loop client lives in #91.

## Diagnosis (Railway project `remarkable-vibrancy`, design-api logs 2026-10-03 ~20:25–20:56 UTC)
design-api logs `http_request_completed` with `duration_ms`; platform-api logs no durations, and
Railway edge HTTP logs are empty because the frontend calls the backends over the private network.

| route | n | fastest | median | max |
|---|---|---|---|---|
| GET /assets/{id}/bytes | 899 | 0.4 s | 30 s | 51 s |
| GET /assets/{id} | 432 | 0.7 s | 9.5 s | 13 s |
| GET /brand-kits | 16 | 0.5 s | 6.4 s | 19 s |

Peak 300 requests in flight against FastAPI's sync threadpool (40 threads by default). Causes:
1. The asset grid loaded every asset's FULL `/bytes` (no cache header) on every load.
2. `DesignStoreBridge._run` built a new engine (new Postgres connection) and `asyncio.run` loop
   (so a new R2 client) per store call, holding a thread throughout.
3. Page server render: brand-kits → kit → 27 separate asset reads → 3 sequential list pages.
12 page loads started within ~1 s at 20:53 (cause unknown — possibly reloads while slow).

## Fixes (commits 0a8d6ea0c, a4cc28773, 2732ab38e)
- Bridge: one daemon-thread event loop per process, one pooled engine per DB URL (O5 rule kept:
  one coroutine = one connection/transaction; pool used only on its own loop). Fork → new loop;
  call from the bridge loop's own thread → old one-shot path (no deadlock).
- design-api: `GET /assets/records?asset_ids=` (one statement, same envelope as /assets/{id});
  `/bytes` and `/thumbnail` send `ETag: "<digest>"` + `Cache-Control: private, max-age=300`, 304
  without a storage read on match. NOT immutable: re-registering an asset id replaces its record.
- Frontend: grid shows `/thumbnail` when the record has `media.thumbnail`; batch record read with a
  per-asset fallback (deploy-order skew safe); three registry kinds listed concurrently; design BFF
  forwards `if-none-match`, passes `etag`, builds 304s bodiless.

## Verification
- New tests RED→GREEN: `test_design_store_bridge_pool.py` (5), `test_brand_context_asset_reads.py` (5),
  frontend route/mapping/repository tests (55/55 in those files).
- Focused design-api files (bridge, assets, fonts, logo cache, fragments, onboarding): all pass except
  4 in `test_scene_turn_persist.py` (duplicate `design_agent_run` key) — PRE-EXISTING: same 4 fail with
  the base design code on a fresh migrated DB.
- Frontend gate: design-system:build, lint (2 pre-existing warnings in canvasOperations.ts), build OK;
  `npm test` 3262/3268 — the 5 failures are PRE-EXISTING Zafran account-research tests (same 5 fail on
  base 1ad82b6be).

## Owed / notes
- Production confirmation after deploy (design-api durations from Railway logs; page load time).
- design-api now holds a pool: CLUE_DB_POOL_SIZE/MAX_OVERFLOW (default 5/10) bound its concurrent DB
  connections; raise on the design-api service if requests wait on the pool (pgbouncer pool is shared).
- Minor (deferred): the batch read sends all kit ids in one request; the route caps at 200 ids.
