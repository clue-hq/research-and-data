# 2026-08-20 — brand-kit website ingestion: exhaustive, highest-quality image extraction

Branch `integration/frontend-design-part-iv-v2`. Founder-ordered fix. Parent commit
`2ebb3976`.

## The defect

Website ingestion enqueued exactly `node.attributes["src"]` and capped the harvest at 12,
so a brand on an image CDN handed us its **thumbnail**. Live evidence, Stripe kit
`brand_kit_ing_813df4f30f2d429a853dbccae2277a5a` (workspace `ws_8040294627e146ae93f753ec0d3e1726`),
every version v1–v7: **13 images, nine of them 296x1xx**, because each `src` carried
`?w=296&q=90` — including `platform-graphic-background_2x.png`, a retina asset fetched at
296px. The single URL with no width param (`Stripe.jpg?q=80`) came back **2048x1024**. The
pipeline stored whatever it asked for; it asked for the small one.

These assets are reused directly in generated microsites and later as reference images for
the image-generation tool, so this was a real quality loss.

Three root causes, all verified before touching anything:
1. `capture/static.py::_collect_assets` — `src` only. No `srcset`, no `<picture><source>`,
   no CSS `background-image`, no favicon fetch.
2. `capture/parse.py::_parse_images` — `cap = 12`.
3. `capture/rendered.py` — a fixed `10 x 800px = 8000px` scroll, starving below-fold lazy
   loading.

## The constraint that shaped the design

`_collect_assets` decides which URLs are DOWNLOADED; `_parse_images` looks bytes up **by
URL** (`_download_by_url`) and an asset with no bytes is dropped outright
(`evidence_builder.queue` returns `None` without a sha). If the collector downloaded the
widest `srcset` URL while the parser still resolved the bare `src`, **every image would lose
its bytes and the kit would come out with zero images**.

So the choice is implemented ONCE, in a new module `capture/imgsrc.py`, imported by both
sites. Pinned two ways in `apps/api/tests/test_ingestion_image_sources.py`:
`test_the_collector_and_the_parser_agree_on_every_image_url` (behavioural, end-to-end over
MockTransport: every parsed image must carry bytes AND its URL must be one the snapshot
downloaded) and `test_the_collector_and_the_parser_call_the_same_chooser` (structural
identity pin).

## What changed

**New `capture/imgsrc.py`** — the shared chooser plus the two caps that belong next to it.
`image_source_ladder(node, base_url)` returns an ordered, absolutized, deduped candidate
list, best first:
1. widest `srcset` candidate — `w` descriptors ranked by pixel width; if no `w` descriptor
   exists anywhere, `x` descriptors ranked by density. `<picture><source srcset=…>` entries
   are read in document order ahead of the `<img>`'s own `srcset`, as a browser does.
   Descriptor families are never mixed (a `2x` never out-ranks a `1600w`).
2. `upgrade_width_params(url)` — a CDN width-param upgrade of the best URL so far. `w` /
   `width` / `sw` raised to `TARGET_IMAGE_WIDTH = 2048`; every other param preserved; an
   explicit `h` / `height` / `sh` scaled by the same factor so the crop is not silently
   changed. Never downgrades, never invents a param the CDN did not already prove it
   honours.
3. the bare `src` — **always the last rung**, so the new machinery can never do worse than
   the old.

`MAX_CANDIDATES_PER_IMAGE = 3` bounds the ladder (the last rung is reserved for `src`).
`background_image_urls(tree, stylesheets, base_url)` harvests `background`/`background-image`
`url(...)` from inline `style` attrs and fetched stylesheets, resolved against the *sheet*
URL, skipping `@font-face` (a `src:` declaration never matches the background regex) and
`data:` URIs, capped at `MAX_BACKGROUND_IMAGES = 40`.

**`static.py::_collect_assets`** — enqueues the whole ladder per `<img>`, the background
URLs, and `link[rel=icon]` / `link[rel='shortcut icon']` (kind `logo`). Logo collection
still uses the bare `src` deliberately: `_parse_primary_logo_candidates` scores by `src`,
and a lockup is vector or small, so the ladder buys nothing there; the ladder re-adds those
URLs anyway and the URL-level dedup keeps the earlier `logo` kind.

**`parse.py`** — `_parse_images` walks the SAME ladder and takes the first rung that
produced bytes, falling back down to `src`; the locator says
`dom :: img :: hi-res rendition` when the chosen URL is not the element's own `src`, so
provenance stays honest about which rendition we hold. Background images join the same
candidate pool with `kind_hint="illustration"` and locator `dom :: css background-image`,
and are dropped (never fabricated) when no bytes arrived. Cap `12 → IMAGE_CANDIDATE_CAP =
50`; the LUMI0504 message now names the cap. `_parse_dom` surfaces the favicon as a
**fallback** mark, appended AFTER apple-touch-icon (normalizer `emit` fills `logo.mark` from
the first mark, and a 180px touch icon beats a 32px favicon), and only when bytes exist.

**`rendered.py`** — `_scroll_until_settled(page)` replaces the fixed loop: scroll 1000px,
settle 200ms, re-read `scrollHeight`/`scrollY`/`innerHeight` in one `evaluate`, stop after
two consecutive steps that are both at the bottom and not growing. Bounded twice so an
infinite-scroll feed cannot hold the capture: `60 x 1000px = 60_000px` of page AND `12s`
wall clock, then a final `600ms` so the last lazy batch actually fetches.

Unchanged on purpose: every `net.py` byte cap, the 15s timeout, `DEFAULT_CONCURRENCY = 8`,
the `<=4px` tracking-pixel filter, the logo scoring/threshold, and all three dedup layers.

## Live before/after — https://stripe.com, both runs 2026-08-20, same page

Driven through the real `capture_website(force_render=True)` → `parse_site` path. "Before"
was the identical probe run against a throwaway worktree at parent `2ebb3976`
(`git worktree add --detach /tmp/istanbul-imgbaseline HEAD` — **never `git stash`**, the
`.git` dir is shared across ~20 worktrees).

| | before | after |
|---|---|---|
| snapshot downloads | 50 | 149 |
| parsed images | 13 (cap hit, `skipped 34`) | **49** (no cap hit) |
| 296px-family images | **9** | **0** |
| largest image | 2048x1024 (the one un-parameterised URL) | 2784x1949 |
| logos | 3 (top-scored primary had **no bytes**) | 4 (primary now HAS bytes) |
| colors / type samples / fonts / geometry | 1199 / 20 / 1 / present | 1199 / 20 / 1 / present |

The nine 296px thumbnails came back as their real renditions: the four
`enterprise-accordion-*` at **2460x1060**, `platform-graphic-background_2x` at **2460x1064**,
the four `*-fallback_2x` at **2468x1038**, `DatavizStatic3x` 768x300 → **2304x900**,
`ConnectBentoBackground` 1242x454 → **2484x908**, `payment-bento-background` 860x712 →
**1632x1352**. The stored DB baseline (kit v6, approved) matches the "before" column exactly:
9 x 296px, then 768, 860, 1242, 2048.

### Through the shipped pipeline — kit v8, DRAFT

`POST /brand-kits/ingest/website` on the restarted 8010 (job
`ingest_8da461bedf9d4e4ea4403c1da0a84620`, succeeded 13:26 UTC) published
**v8 as a DRAFT**. v6 remains the approved version; nothing was approved.

`assets.images`: **13 → 48** (49 parsed, one pair collapsed by the content-addressed dedup —
two Stripe merch thumbnails share bytes). Width histogram: `<300px` 7, `300–799` 10,
`800–1499` 15, `1500–2047` 1, `>=2048` **15**. **Zero** images from the `?w=296` family
remain; the seven sub-300px ones are genuinely small source assets (a 64x64 icon, a QR code,
merch thumbnails) where the CDN clamped `w=2048` to the original — which is the intended,
honest behaviour. Several came back **wider than the 2048 target** (`w=2460`, `2464`, `2468`,
`2484`, `2784`, `2304`): those are the *widest srcset* rung winning, with the upgrade
correctly declining to downgrade them.

Everything else held: colours 42, typography 12, numbers 13, radii 10, spacing 22, stroke
widths 8 — identical to v6/v7; shadows 3 → 4; brief present (11 keys, comparable size); fonts 1.

Unplanned bonus: Stripe's JSON-LD-declared Organization logo is served from the same URL as
its `link[rel=icon]`. That URL was never fetched before, so the highest-scoring primary logo
candidate carried **no bytes** and the primary slot was filled by a lower-ranked candidate.
The favicon fetch fills it.

Background-image harvest contributed **0** on stripe.com — Stripe keeps no CSS `url()`
backgrounds. Proven live elsewhere: basecamp.com 40 (cap), mailchimp.com 40 (cap),
airbnb.com 0 (no stylesheets at the static tier).

## Cost — flag for the founder

The founder accepted "roughly double" the fetch count. Measured on stripe.com it is **~3x**
(50 → 149 downloads) because most Stripe `<img>`s spend all three rungs: upgraded-widest,
widest, bare `src` — and only the first is ever used. A staged collector (fan out rung 1 for
every image, then a second round for only the images whose rung 1 failed) would bring this
back to ~1x for two batched rounds instead of one. **Not done** — it changes
`_collect_assets`'s documented "ONE concurrent batch" property and its overlap test, and the
founder had already accepted the simple version. Recorded as the first optimisation to reach
for if ingestion latency or bandwidth becomes a complaint.

## A second consumer of these renditions

`dcd4d47a` added `_brand_style_references`, which feeds up to two of the kit's brand **images**
(never a logo) to the text-to-image provider as style anchors. So the harvest this wave
widened is now read not only by generated microsites but by the T2I path as well — the
296px-thumbnail defect would have been anchoring every generated image to a 296px reference.
Worth remembering before anyone considers narrowing the harvest for cost.

### Latent defect found while checking that adjacency — NOT FIXED, not this lane

`img-tools` asked whether the two references actually surface high-resolution renditions.
They do **now**, but by luck, not by design. Verified chain:

- `normalizer/emit.py::add_images` assigns `img.{index}` sequentially over `evidence.images`,
  and `parse._parse_images` sorts its candidates by `(area, file_size)` **descending** before
  emitting. So the ordinal `img.N` sequence IS a quality ranking, best first (`img.1` is the
  og:image, appended by `_parse_dom` ahead of the sorted block).
- `web_substrate.py:3286` picks with `for image_key, image in sorted(images.items())` — a
  **lexicographic** sort over `img.1 … img.48`. Lexicographic order is
  `img.1, img.10, img.11, …, img.19, img.2, …`, so with `_BRAND_REFERENCE_MAX = 2` it takes
  **`img.1` and `img.10`** — never `img.2`, the actual second-best.

Live consequence, measured on the real kit:

| kit | `img.1` | `img.10` |
|---|---|---|
| **v6 (currently APPROVED)** | 2048x1024 | **296x124** |
| v8 (this wave's draft) | 2048x1024 | 2468x1038 |

So on the approved kit, half the style conditioning for every generated page was a 296px
thumbnail. This wave repaired that **incidentally** — by deleting every thumbnail from the
harvest — but the lexicographic sort is untouched and will resurface on any site with
genuinely small assets. v8 itself carries seven sub-300px images (a 64x64 icon, a QR code,
merch thumbs); none happened to land on a low-lex key, which is luck.

State it plainly for whoever fixes it: **this wave mitigated the symptom and left the defect
untouched.** The relief is contingent on the harvest containing no small assets at a low-lex
key, which is not a property anything enforces.

**A natural sort is necessary but may not be sufficient** (`img-tools`, verified at
`web_substrate.py:3291-3303`): the picker also skips silently on a missing/invalid digest, on
`not path.is_file()`, and on `OSError` — three `continue` guards. So even with correct
ordering it collects the first two *resolvable* entries, which on a kit published elsewhere
(blobs absent locally — an explicitly normal state per the docstring) can still land
arbitrarily deep in the ranking. Two candidate fixes, and whoever picks this up should say
which they are buying:
- **minimal** — natural/numeric sort key at `web_substrate.py:3286`, so the picker honours
  the ranking `emit` already built;
- **complete** — that, plus a quality floor on what may serve as a style anchor, so a
  resolvable-but-tiny image cannot become the anchor by default.

**Deliberately not applied here** — it is the web lane's file, outside this wave's ordered
scope, and the founder reviews diffs inline. `img-tools` independently declined to patch it
for the same reason (read-only brief). Surfaced from both lanes to the founder instead, so it
does not depend on either agent having quietly landed it.

Second cost consequence, downstream of this wave and **not** something it changed: the
describe stage runs one vision completion per asset, so 13 → 49 images is ~4x the
description spend and wall-clock per website ingestion (stripe.com: ~53 vision calls,
several minutes at the `LUMEN_INGESTION_DESCRIBE=1` recipe). If that becomes a complaint the
lever is describing only the top-N by area, not shrinking the harvest.

## Deferred / deliberately NOT done

- **Inline `<svg>` harvesting** — explicitly out of scope for this wave (founder). It needs
  its own serialization / sanitization / dedup design, and the logo path already captures
  the important case via `parsed._inline_svgs`.
- **`data-src` / `data-srcset` lazy-load attributes.** Extremely common with lazyload
  libraries, and not in the ordered scope. The rendered tier's new scroll budget covers the
  same ground for any library that swaps `src` on intersection; a library that never swaps
  is still missed. Cheap follow-up: add `data-srcset` / `data-src` as ladder rungs BELOW the
  real `src`.
- **Staged collector fetch** (above).
- The 40-URL background cap and the 3-rung ladder cap are guesses tuned to bound fan-out,
  not measured optima.

## Tests

New file `apps/api/tests/test_ingestion_image_sources.py`, 19 cases: widest-`w`, highest-`x`,
`<picture><source>`, CDN upgrade (params preserved / height scaled / never downgrades /
never invents), ladder dedup+bound, the two collector/parser agreement pins, the
upgrade-404 fallback (asset survives on `src` bytes), background-image from inline style +
stylesheet with `@font-face` excluded, background bytes reaching `parsed.images`, favicon
fetched + ranked below apple-touch-icon, cap-50 boundary (no diagnostic at 50, LUMI0504
`skipped 1 image(s)` at 51), plain-`src` no-regression, degenerate sources.

`test_ingestion_capture.py::test_image_cap_logic` updated to read `IMAGE_CANDIDATE_CAP`
rather than the literal 12.

Suite command (the platform root `.env` must **not** be sourced — env leakage breaks
ingestion expectations):

```
cd <repo root>
env -u CLUE_DATABASE_URL \
  PYTHONPATH=subsystems/clue-design:subsystems/clue-design/apps/api:subsystems/clue-design/apps/agent_runtime \
  .venv/bin/python -m pytest subsystems/clue-design/apps/api/tests subsystems/clue-design/apps/agent_runtime/tests -q
```

**Green:** the whole ingestion set (capture / image_sources / routes / brief / geometry /
normalizer / jobs / ui_api / describe / font_metrics / raster / deployment_config / uploads /
pdf) — 250 passed, 4 skipped — and all 621 of `apps/agent_runtime/tests`. Baseline before any
edit: 109 passed, 1 skipped on the required ingestion subset.

**Red in the whole `apps/api/tests` suite — none of it mine.** 22 failures at HEAD, of two
different kinds:

**(a) 20 genuinely pre-existing, and nothing to do with the fleet worker.** Re-run at parent
`2ebb3976` in the throwaway worktree: fail identically. Re-run at HEAD with 8010 **verified
down before and after**: still 20, same list. `test_agent_custom_components` (1),
`test_custom_component_compiler` (5), `test_custom_component_publish` (4),
`test_custom_component_runtime` (7), `test_asset_custody` (2), `test_asset_store_serving` (1).
The cause is a **missing local node toolchain**, not code rot: the constrained compiler worker
returns `CCI0002 … Cannot find package 'typescript'` → `transient_error` (emitted by
`custom_component_compiler.py::_infrastructure_result`, which stamps
`"category": "infrastructure"` — the code is telling you it is environment, not source), and
the dependent serving assertions then see 503/404.

**The fix, verified by exact test — not `npm install` in `subsystems/clue-design`, which has
no `package.json` and no lockfile at all and would simply error:**

```
cd subsystems/clue-design/apps/custom-component-compiler && npm ci
```

`custom_component_compiler.py:39-45` resolves the worker to
`parents[3]/apps/custom-component-compiler/compiler.mjs`; that directory owns the
`package.json` pinning `"typescript": "5.8.3"` and a `package-lock.json`, and its
`node_modules` is absent. `npm ci` (not `install`) because the lockfile is present and the
version pinned. Not this wave's to make. Thanks to `img-tools` for catching that my first
location would have sent the next reader down a dead end.

**(b) 2 that were MY bisect error — contention, not a regression. Corrected 2026-08-20 after
`img-tools` pushed back, and they were right.**
`test_api.py::test_agent_turns_async_persists_result_and_terminal_event` and
`test_design_toolbelt_documents.py::test_the_web_turn_worker_persists_through_the_governed_tool`
**pass at HEAD** once 8010 is confirmed down (verified 0 listeners before *and* after the run).
I had attributed them to the parallel image-generation lane's commits; that was wrong on the
evidence — those commits touch only `agent_runtime/`, `.env.example` and two SKILL/prompt
files, and both tests install a **process-local** stub (`app.state.web_turn_runner` /
`app.state.agent_turn_runner`) that short-circuits before any of that code. The real mechanism
is the trap below: both are `wait_for_run`-shaped async worker tests, so they are the most
lease-sensitive in the suite. My "green at `2ebb3976`/`a224b614`, red at HEAD" reading was a
race that happened to break the same way twice, because 8010 came back up 35 seconds into the
HEAD run. **Method lesson: when the suspected cause is a shared-resource race, a
commit-to-commit bisect proves nothing unless the shared resource is pinned in every arm.**

## THE SUITE TRAP — a running design API poisons `apps/api/tests`

The design API on 8010 runs with `LUMEN_EMBEDDED_FLEET_WORKER=1`. Its worker leases
`design_job` rows out of the **same** Postgres the tests write to, so it drains work the
tests enqueue: with 8010 up the suite showed **34** failures, with it down **20**. This is
the same class as the recorded "stale extra 801x listener poaches jobs" incident, except the
poacher is the *canonical* server.

Why the isolation does not save you (mechanism, from `img-tools`): the suite isolates by
**workspace id, not by database** (`apps/api/tests/conftest.py:22-25` — "Postgres is shared…
run this suite against a disposable `CLUE_DATABASE_URL`"), and the lease has **no workspace
predicate** — `platform/fleet/clue_fleet/queue.py:170-178` filters on `kind` (+ optional
`project_run_id`) then `ORDER BY priority, enqueue_seq LIMIT 1 FOR UPDATE SKIP LOCKED`. The
live worker is a separate process, so it holds none of the test's `app.state` stubs; when it
wins the 0.1s poll race it runs the REAL runner and the assertions about the fake runner's
output fail. `main.py:370-381` documents exactly this, diagnosed 2026-08-19/20.

**Run `apps/api/tests` with 8010 stopped, and check `lsof -nP -iTCP:8010 -sTCP:LISTEN`
returns nothing BEFORE and AFTER the run.** During this wave 8010 came back up 35 seconds
after I killed it (PID 70699, 13:53:35 UTC, PPID 1 — detached, not mine), which silently
re-confounded a run I had labelled clean and cost me a wrong regression attribution. The
after-check is the part I skipped and the part that would have caught it.

## Traps hit

- The design venv is at the **repo root** (`istanbul/.venv`), not
  `subsystems/clue-design/.venv`; `PYTHONPATH` entries are repo-root-relative.
- The `insight_static` fixture already carries images of its own, so a cap test that injects
  exactly `IMAGE_CANDIDATE_CAP` images overshoots. Compute the baseline first.
- Another agent is editing `apps/agent_runtime/tests/test_web_substrate.py` in this same
  working tree (image-generation lane). Commits here were path-scoped, never `git add -A`.
