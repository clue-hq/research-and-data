# 2026-08-31 — gallery card thumbnails (design documents), plan close-out

Branch `integration/frontend-design-part-iv-v2`. Six-task SDD plan
(`.superpowers/sdd/2026-08-31-gallery-card-thumbnails/`) plus two deferral-closure
batches. This note closes it: what shipped, the rulings, the ops facts, and the
live browser walk that verified the whole thing end to end.

## What shipped

| Layer | Thing |
|---|---|
| Migration | `be0659753362` — `design_document_thumbnail`, PK `(workspace_id, document_id, version)`, FK-free both ways, pointer rows only (bytes live in the design blob store under `{workspace_id}/design/{sha256}`) |
| Generator | `subsystems/clue-design/apps/api/lumen_api/document_thumbnails.py` — `web_thumbnail_png` (Playwright Chromium, Tailwind runtime inlined, 1448×1086 @ scale 0.5 → 724×543), `png_from_export_result` + `downscale_png` (engine Skia PNG, max edge 724), `first_page_ids`, typed `ThumbnailUnavailable(code, message)` |
| Route | `GET /documents/{document_id}/thumbnail?v=` in `lumen_api/main.py` — kind-dispatched on `doc_kind`, lazy, cached by `(document, version)`, typed 502 `thumbnail.*` on every failure |
| BFF | `/api/clue/design/*` passthrough (needed no handler change — the query string already forwarded; binary body + caching headers proven by test) |
| Frontend | `features/design-editor/adapter/gallery.ts::designThumbnailPath` composes the versioned URL from the list read's `documentId` + `currentVersionId`; both gallery card `Image`s are `unoptimized`; a failed load falls back through `onError` to the ruled empty preview frame |

## Rulings on the record

1. **PNG for both kinds** — a browser screenshot is the only faithful raster of Tailwind
   HTML; the engine's own Skia PNG is the only faithful raster of a scene.
2. **Lazy, read-path only.** Generation lives inside the GET. There is no write-path hook
   anywhere, so the editor's edit loop is untouched (measured below).
3. **Version-keyed cache.** `?v=` equal to the current version ⇒
   `Cache-Control: private, max-age=31536000, immutable`; any other `v` ⇒ current bytes,
   `no-store`. An edit bumps the version, so the URL changes and the card self-refreshes.
4. **Empty frame is the FALLBACK, not the universal state.** Ruling 2's old "real documents
   have no thumbnails" is superseded; `onError` keeps the empty frame reachable.
5. **Kind dispatch on `doc_kind`, never payload shape** (a scene's `pages` is a map, a web
   doc's is a list, and the scene page picker answers `None` on a list *quietly*).
6. Superseded-version rows/blobs are **kept**; pruning is a recorded follow-up.

## Ops facts (also recorded in `DEV_STACK.md`)

- **`python -m playwright install chromium` is a once-per-machine prerequisite** for the
  repo `.venv`. Without it, every **web** thumbnail is a typed 502
  (`thumbnail.capture_failed`) and web cards show the empty frame. Ads are unaffected —
  they never touch a browser. This machine already had Chromium 149.0.7827.55.
- **The vendored Tailwind runtime is load-bearing for web thumbnails.** Missing ⇒
  `thumbnail.tailwind_runtime_missing` (502), never an unstyled screenshot.
  `LUMEN_TAILWIND_RUNTIME=/abs/path` overrides the search path; a **set-but-missing** path
  is a refusal, not a fall-through (verified live).
- **Dev DB:** `clue_istanbul_dev` (local Postgres, per `DEV_STACK.md`) was at
  `4c02d8eac29a` — exactly this migration's `down_revision`. A plain
  `alembic upgrade head` created the table cleanly. **No manual DDL and no dev-only
  drift was needed.** (The controller's fallback plan assumed the docker `clue` DB on
  55040, which is stamped with a foreign branch's `518a3784f3a4`; that DB is not what the
  runbook's stack uses.)
- **Stale-process trap, cost ~40 min this session:** `dev_stack.sh up` does not `down`
  first, so a design API left over from an earlier session kept port 8010 while the new
  uvicorn died with `[Errno 48] address already in use` — and `status` reported UP because
  *something* was listening. Symptom: the thumbnail route 404s and is absent from
  `/openapi.json`. Always `down` before `up`; a symptom row is now in `DEV_STACK.md`.
- The corrupted-`.next` single-route 404 bit twice; the runbook's fix (`down` →
  `rm -rf apps/frontend/.next` → `up`) worked both times.

## Live browser walk — 2026-08-31, real Chromium against the running stack

Driver: `/tmp/thumbwalk/walk.py` (Playwright, repo `.venv`, dev login per `DEV_STACK.md`).
Screenshots: `.superpowers/sdd/2026-08-31-gallery-card-thumbnails/walk/` (not committed).

Documents used, in workspace `ws_009a035fd48c4985891fee919254c31a`, project
`prj_277077f2b0c45429af405e565293ed05`:

| Document | Kind | Role in the walk |
|---|---|---|
| `doc_936f59fde061520ea4dc9636f94816c1` "CFO billing strategy session landing page" | web | the edit → version-bump proof |
| `doc_thumbwalk_linkedin_square_0001` "Stripe — LinkedIn square ad" | scene/ad | **seeded for this walk** (see below) |
| `doc_70c1d12a3888542a93832aee3797b08d` "Stripe landing page" | web | the forced-502 / empty-frame proof |
| `doc_45ee9a8dc3965a559df5552c76598d89`, `doc_2d7e5f0de32c521c9a57ff1fecb98d0a` | web | genuinely blank v0 documents (see the honesty note) |

| # | Check | Result | Evidence |
|---|---|---|---|
| 1 | Gallery opens (chats-rail + `?surface=gallery`) | 6 artifacts, both kinds | `11-gallery-grid.png` |
| 2 | Web card shows the page's above-the-fold artwork | yes — nav, headline, hero gradient; matches the editor render exactly | `14-web-card.png` vs `20-editor.png` |
| 2 | Ad card shows the ad artwork letterboxed in 4:3 | yes — 724×724 natural into a 154×115 frame | `13-ad-card.png` |
| 2 | List rows carry the same artwork | 40×32 images in 44px rows, both kinds | `16-list-rows-zoom.png` |
| 3 | First load is `200 image/png` + `private, max-age=31536000, immutable` | all 6 | `net-gallery.json` |
| 3 | A reload re-requests nothing | **0 of 6** requests reached the BFF *or* the design API on reload and on re-navigation (6/6 did on the cold first load) | `net-cache.json`; counted from both `/tmp/browser_frontend.log` and `/tmp/browser_design_api.log` |
| 3 | Exactly one `document_thumbnail_generated` per document | 6 documents, 6 events, across two full page loads | design API log |
| 4 | Edit → version bump → new `?v=` → fresh artwork | inspector write (header section background → `Surface-accent #D8351E`); version **4 → 5**; card URL `?v=5`; card artwork now shows the red header | `24-web-card-after-edit.png` |
| 5 | Forced failure ⇒ typed 502 ⇒ **ruled empty frame** | `502 {"code":"thumbnail.tailwind_runtime_missing"}`; the card renders the empty frame (`#EEF0F3`), no broken-image glyph, the other 5 cards and the gallery are unaffected | `30-forced-502-card.png`, `31-forced-502-gallery.png` |
| 5b | Recovery | restoring the runtime → next gallery read regenerates; no poisoned cache row | `32-recovered-gallery.png` |
| 6 | Edit-loop latency unchanged | inspector write round-trip **606 ms**, with the generation-event count **unchanged** across the write; the new PNG appeared only on the next gallery read | step output + design API log |

**Measured numbers**

- Cold generation: web ~**2.0 s** (Chromium launch + 400 ms Tailwind settle + shot);
  scene ~**0.94 s** (engine PNG export + downscale).
- Warm serve through the BFF: **50–105 ms**.
- Typed-502 refusal: ~**0.98 s** (the render runs before the runtime check).
- Blob sizes: web `724×543` **74.8 KB – 112.9 KB**; ad `724×724` **497.3 KB**;
  a blank v0 web document **2.3 KB** (a single flat colour).
- `design_document_thumbnail` after the walk holds one row per version, including the
  superseded `v3` alongside `v4`/`v5` — the no-pruning ruling, visible.

**Honesty note worth keeping.** Two web documents sit at `current_version = 0` with ~390
bytes of scene JSON — they were never generated. Their thumbnails are real: a single flat
`#BAC8DA`, which is what those documents actually look like. They are *not* the empty
frame, and the two states are visually distinguishable (`#BAC8DA` vs `#EEF0F3`). A grey
card is therefore not automatically a failure — check the API log before assuming one.

**Seeded dev data (synthetic, this walk only).** The dev DB held no scene/ad document at
all, so the ad half of ruling 5 had nothing to prove itself against.
`scripts/seed_ad_document.py` was run through a thin driver that repointed its hardcoded
anchors at this DB's real ids (the script's own workspace/project/brand-kit/asset do not
exist here). Rows created:

- `design_document` `doc_thumbwalk_linkedin_square_0001` — the script's harvested tree
  (Frame / AutoLayout / Text / Image / Rect / Ellipse / Group / Line), engine-validated
  through `POST /documents`, brand-stamped `brand_kit_ing_f0a50e0f78ac464eb49399676b769730` v1,
  hero image `asset_ing_53f9b6455350e5b5` (a real 2048×1024 workspace asset).
- `agent_thread` `thr_thumbwalk_linkedin_square`, one `execution`
  (`5356a581-1483-5692-9ae3-6f7d203e1b89` — `uuid5(NAMESPACE_URL,
  'thumbwalk-linkedin-square-execution')`), and one `design_leg`
  (`84031554-10f5-5cab-8ae9-9a4cdc6890de` — `uuid5(NAMESPACE_URL,
  'thumbwalk-linkedin-square-leg')`) binding the thread to the document — the leg is
  what puts a document into the project's gallery feed.

**These rows are deliberately LEFT IN PLACE** (the seeded ad is the founder's demo artifact).
The complete teardown, in dependency-safe order, for whenever it is wanted — all four created
row kinds plus the thumbnail cache rows, which are FK-free and would otherwise dangle:

```sql
DELETE FROM design_leg   WHERE id = '84031554-10f5-5cab-8ae9-9a4cdc6890de';
DELETE FROM design_document_thumbnail
       WHERE document_id = 'doc_thumbwalk_linkedin_square_0001';   -- FK-free both ways
DELETE FROM design_document WHERE id = 'doc_thumbwalk_linkedin_square_0001';
DELETE FROM execution    WHERE id = '5356a581-1483-5692-9ae3-6f7d203e1b89';
DELETE FROM agent_thread WHERE id = 'thr_thumbwalk_linkedin_square';
```

(The blob bytes under `{workspace_id}/design/{sha256}` are content-addressed and are not
deleted by the above — same posture as the no-pruning ruling.)

Also still in the dev DB: the walk's inspector edit left the CFO landing page at
**version 5** with a red (`#D8351E`) header section — a real edit, not a fixture.

## Background full suite — FINISHED; 19 failures, triage with the controller

Kicked at close, never inline (the design suite is far too slow for a foreground gate):

```
cd subsystems/clue-design
PYTHONPATH=.:apps/api:apps/agent_runtime \
CLUE_DATABASE_URL=postgresql+asyncpg://clue:clue@localhost:55040/clue_thumb_t1 \
LUMEN_CORE_HELPER=$PWD/target/release/lumen-api-helper \
../../.venv/bin/python -m pytest apps/api/tests -q
```

- PID **36766**, log **`/tmp/design_api_fullsuite_20260831.log`**. **The run has since
  finished** (process gone; the log is complete). Final tally: **19 failures**, not the
  "2 at ~14%" this note first recorded mid-run. By file:

  | Failures | File |
  |---|---|
  | 7 | `apps/api/tests/test_custom_component_runtime.py` |
  | 5 | `apps/api/tests/test_custom_component_compiler.py` |
  | 4 | `apps/api/tests/test_custom_component_publish.py` |
  | 1 | `apps/api/tests/test_ad_assets_onboarding.py` |
  | 1 | `apps/api/tests/test_agent_custom_components.py` |
  | 1 | `apps/api/tests/test_asset_custody.py` |

  **None is thumbnail-related** — no failure touches `test_document_thumbnails.py`, the
  thumbnail route, or the generator. Triage was the controller's, from the log
  (`grep '^FAILED'` for the list); its verdict is the next bullet.
- **They are not this plan's tests.** Both plan-owned suites were re-run focused, on an
  isolated DB (`clue_thumb_t6`, migrated to head) so the background run was undisturbed:
  `apps/api/tests/test_document_thumbnails.py` **27 passed**, and
  `tests/design/test_document_thumbnails_dal.py` **3 passed**. Triage (controller,
  final-review re-check against the log): **17 of 19** die on the missing-`typescript`
  cause — the node toolchain the custom-component compile worker shells out to has no
  `typescript` installed (`ERR_MODULE_NOT_FOUND`; 15 log blocks + the
  `agent_custom_components` singleton's `transient_error` compile status). The other
  **2 singletons have distinct, pre-existing causes wanting their own triage**:
  `test_asset_custody.py::test_pure_python_reads_survive_a_wiped_cache` (a 404 from
  `/asset-store/{digest}` after a wiped cache) and
  `test_ad_assets_onboarding.py::test_an_empty_harvest_says_so_at_the_top_level` (a
  stage-vs-summary narration assertion). No commit in THIS PLAN'S WAVE
  (`d87b6ca2..4c08aca7`) touches any of the six failing files; the wider integration
  branch has touched the custom-component tests in earlier, unrelated waves. (Note the
  pre-existing Starlette/httpx `testclient` deprecation warning in the output — conftest
  noise, not this plan's.)
- `clue_thumb_t6` is a second throwaway; drop it alongside `clue_thumb_t1`.
- `clue_thumb_t1` (docker `clue-pg-istanbul`, port 55040, migrated to `be0659753362`) is the
  throwaway DSN for every DB-gated design run on this plan. **The controller drops it after
  the final whole-branch review, not before.**

## Open follow-ups (recorded, deliberately not built)

1. **Thumbnail pruning** — superseded-version rows/blobs accumulate. Use the design-subject
   `run_event` pruner discipline if volume ever matters.
2. **Warm-path generation** — a post-write background warm would hide the one-time cold-read
   latency. Only worth it if founders notice the first gallery paint.
3. **Chat-message artifact previews / share-OG images** can consume this route unchanged.
4. **Persistent browser process** — the route launches Chromium per generation (rare: once
   per version). If volume grows, lift `web_substrate`'s pooled-browser pattern.
5. **Concurrent first reads duplicate generation** — idempotent, wasted work only; no lock,
   by YAGNI.
6. `etag` is not in the BFF's `FORWARDED_RESPONSE_HEADERS`, so revalidation does not survive
   the proxy. Harmless under the immutable `?v=` scheme — recorded so nobody designs against it.
7. Two DEAD legacy renderers of `ProjectArtifact.imagePath` would mishandle the new URL if
   remounted (`projects/components/artifact-gallery.tsx` uses `next/image` *without*
   `unoptimized` → the 401 case; `artifact-viewer.tsx`'s Export link would download a
   card-sized thumbnail). Verified unimported today; latent only.
8. The plan's deferred-minors table (17 items from the task reviews) is in
   `.superpowers/sdd/2026-08-31-gallery-card-thumbnails/task-6-brief.md` and is the final
   whole-branch review's to-triage list.
