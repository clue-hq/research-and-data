# Brand facts from the captured sections (trial gap items 1, 2 and 4) — plan

**Status:** APPROVED in principle by the founder 2026-10-17 ("proceed with your plan in that way"). Tasks 5 and 6
are founder-triggered (a re-capture needs a yes with a time estimate; moving a site to a new kit needs a go).
**Source:** `docs/superpowers/verification/2026-10-17-puck-trial-gap-audit.md` items 1, 2, 4;
`.superpowers/sdd/2026-10-16-s2a-2/theme-investigation.md` (facts 1–6; git-ignored, read it first).
**Rule for this plan (founder):** simple over engineered. No new subsystems; each task is a bounded change
with a test that fails first.

## 1. What is wrong today (read 2026-10-17)

1. **Heading colour.** The trial measured Garner's heading ink (#014036, forest) from the rendered sections and
   drew agent-section headings with it. Production's ingestion never measures a heading colour:
   `lumen_ingestion/normalizer/typography.py:303-305` hard-codes `text.primary` as the colour of the display,
   headline and title roles, and `TYPE_MEASUREMENT_FIELDS` (`typography.py:390`) has no colour. The capture
   already reads each heading sample's computed `color` (`capture/parse.py:1239-1262`, hint `heading-text`),
   but nothing turns it into a token. The theme would draw it: `site-kit/src/theme.ts:176` sets
   `--brand-ink-role-headline` to the role's colour token whenever that token is **measured**.
2. **Standard button.** The trial's standard button was the measured hero button (a pill, 42 px high).
   Production's `standardButton` (`site-kit/src/looks.ts:248-262`) reads `radius.button` (derived, 16 px) and
   a fallback padding, even when the kit holds measured filled buttons (kit v3: `solid.017660.c5e6`, a #017660
   pill, the most used). `lightVersion` (`theme.ts:90`) builds the dark-surface version from `surface.page`
   although v3 measured the real light pill (`solid.ffffff`: #FFFFFF / #0D2B25). Both kits' own rules say
   "buttons are pills; do not use radius.button".
3. **Card text.** Kit v3 already measures it (`solid.f9faf8.f271`, label #014036). Nothing to build; the
   Syracuse site is pinned to v2, which predates measured components (task 5).
4. **Captured images have no descriptions.** `lumen_api/site_brand.py:50-63` and `site-kit/src/brand.ts:34-51`
   give a captured image its alt text or `From the seller's section "…"`. Kit assets are described at
   ingestion (`lumen_ingestion/describe.py:326 describe_kit_assets`, cache `DescriptionStore` keyed by asset id,
   `LUMEN_INGESTION_DESCRIBE=1`, on by default). Captured images never go through it.
5. **Hero video.** The capture keeps a poster only if the seller had one (`capture/candidates.py:182-187`);
   Garner's has none. No `preload="metadata"`, no smaller rendition: the 4.2 MB file is sent whole.
   `ffmpeg`/`ffprobe` are in the backend image (`docker/backend/Dockerfile:59`, checked by `smoke.sh`).

## 2. Tasks

### Task 1 — Ingestion measures the heading ink (owner: implementer)

- **Where:** `lumen_ingestion/normalizer/typography.py` (the spec table and `TYPE_MEASUREMENT_FIELDS`),
  `normalizer/roles.py` (where colour clusters become tokens; the `heading-text` hint is in
  `ColorCluster.role_hints`), the token name `text.heading`.
- **Rule (the trial's, `trials/puck-spike/export/measure_brand.py:48-62`):** the heading ink is the colour of
  headings (h1/h2/h3 samples) that sit on a **light** background (relative luminance > 0.35 of the sample's
  `bg`), weighted by the sample's area; the most-weighted colour wins. Headings on dark backgrounds (a white
  h1 on a hero) are ignored. With no such sample there is no `text.heading` token and nothing changes.
- **Effect:** `text.heading` is a colour token with provenance `measured` (like `text.primary` from a custom
  prop). The display, headline and title roles take `text.heading` when it exists, else `text.primary` as today.
  `theme.ts:176` then draws it on light surfaces; `catalog.ts:250` shows it in brand.md's type-roles table, so
  the agent reads one consistent fact (the "do not recolor to text.primary" rule and the table stop
  disagreeing).
- **Tests (first, red):** a normalizer test with three samples — h2 #014036 on #F9FAF8 (area 20k), h1 #FFFFFF on
  #014036 (area 60k), h3 #014036 on #FFFFFF (area 5k) — yields `text.heading = #014036`, measured, and
  `type.headline.color == "text.heading"`; with only dark-background headings, no token and `text.primary`.
  A site-kit theme test: a kit with measured `text.heading` draws `--brand-ink-role-headline` from it on light
  surfaces and `initial` on dark ones; brand.md's table shows it.

### Task 2 — The standard button is the brand's own most-used filled button (owner: implementer)

- **Where:** `site-kit/src/looks.ts standardButton`, `theme.ts lightVersion`.
- **Rule:** when the kit has measured button looks (`buttonLooks(brand)` with `measured !== null`), the standard
  button takes the most-used **filled** look's parts (fill, label, border, radius, padding, height, font, icon
  gap) — `looks()` already orders by use. With none measured, today's standard stays. `lightVersion` prefers a
  measured filled look whose fill is light (relative luminance > 0.5) and whose label reads on it, over the
  page/inverse surface guess. The agent's brand.md "standard button" line says which look it is.
- **Tests (first, red):** a Garner kit v3 fixture (export from the lane DB, read-only:
  `docker exec clue-pg-trenton psql -U clue -d clue_trenton -Atc "select brand_kit_json from design_brand_kit where brand_kit_id='brand_kit_ing_ba0708281cb44f7c847dfb8949110103' and version=3"`
  → `site-kit/test/fixtures/kits/garner.v3.json`): `.brand-btn` draws `border-radius:9999px`, the measured height
  and padding, fill #017660; on `surface.brand` the light version is #FFFFFF with label #0D2B25. The existing
  `garner.json` (v2, no measured components) keeps today's output (tests unchanged).

### Task 3 — Captured images get descriptions at ingestion (owner: implementer)

- **Where:** the capture's fragment artifact (`lumen_api/fragments/artifact.py:118-180`, payload keys), the
  describe step (`lumen_ingestion/describe.py`, reuse `DescriptionStore` and the describer so a digest described
  once is never paid for twice), `site_brand.py clone_images`, `site-kit/src/brand.ts cloneImages`.
- **Rule:** after a capture stores a fragment, every `<img src="/asset-store/<digest>">` in it is described through
  the same describer and cache as kit assets (kind `captured_image`); the fragment payload carries
  `asset_descriptions: {digest: text}`. `clone_images` / `cloneImages` read that first, then the alt text, then
  today's fallback. Bounded by the existing describe cap; a describer failure keeps the fallback (never fails the
  capture). The clone card in brand.md lists the descriptions so the agent stops spending `view_asset` calls.
- **Tests (first, red):** with a fake describer, a captured fragment with two images stores two descriptions, a
  re-capture of the same digest makes no describe call; `clone_images` prefers the stored description;
  site-kit `brandData` likewise.

### Task 4 — Hero video: a poster, `preload="metadata"`, and a smaller rendition (owner: implementer)

- **Where:** capture transport for video sources (`capture/candidates.py`, the fetch/store step for `video`
  dependencies), `site-kit/src/clone.ts fillClone` (video attributes at fill), the fragment payload.
- **Rule:** at capture, for each stored video source: with `ffmpeg` on PATH, write a poster (the frame at 1 s,
  JPEG, same width) and, when the file is over 1.5 MB, one rendition at most 1280 px wide (`-crf 28`,
  `-preset veryfast`, `-movflags +faststart`, no audio); both registered as assets and named in the payload
  (`video_renditions: {source digest: {poster, rendition}}`). Without `ffmpeg`, nothing is made and a diagnostic
  says so. At fill, every `<video>` gets `preload="metadata"`, a `poster` when one is known, and its `<source>`
  points at the rendition when one exists (the original stays stored). Nothing changes for sellers' videos that
  already have a poster except `preload`.
- **Tests (first, red):** `fillClone` adds `preload="metadata"` and swaps the source; a capture unit test with the
  real `ffmpeg` (skipped when absent) makes a poster and a rendition smaller than the source for a 2 MB
  synthetic mp4; the preview renderer serves the poster on request (Task 7's served-on-request path).

### Task 5 — Re-capture Garner and move the Syracuse site (owner: controller, founder-triggered)

- Ask the founder for the re-capture with the estimate (15–20 min; one describe call per captured image).
- Compare kit v4 against v3: `text.heading` = #014036, the standard button a #017660 pill, card text #014036,
  image descriptions present, hero poster present.
- With the founder's go, repin the Syracuse site to v4 (`POST /documents/{id}/brand-kit`). Known effect: the
  section's stored card style name `solid.1` does not exist in v3+ and falls back to the standard card; the agent
  rewrites it on its next turn.
- Conduit and Clue need the same re-capture to gain the measured facts; ask separately.

### Task 6 — Live check (owner: controller)

In the in-app browser on the Garner Syracuse site: the agent section's headings are forest, a brand-section button
is a pill, the hero shows its poster before the video plays, the FAQ (if restored) reads as before. Then the
three-workspace check after Conduit's re-capture.

## 3. Gates

Named test files only (never the clue-design `apps/api/tests` folder): the normalizer tests, `test_site_render.py`,
`test_site_turn_ports.py`, `site_brand` tests, the fragment artifact tests, site-kit `npm test`, site-editor
`npm test`; the frontend gate (`design-system:build`, `lint`, `build`) with the lane stack down; bundles rebuilt;
lane restarted. Rough size: about a day for Tasks 1–4.
