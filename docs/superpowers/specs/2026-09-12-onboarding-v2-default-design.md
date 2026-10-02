# The new onboarding lane becomes the onboarding screen's pipeline

**Status:** design approved in chat by the founder, 2026-09-12. Branch `research-streaming`.
**Rulings (founder, 2026-09-12):** the new lane (`POST /onboarding`, `GET /onboarding/current`)
replaces the old Stage-0 setup behind the Welcome flow's setting-up screen; the user is released
into the app as soon as the four fast steps (overview, lineup, reviews, ICP synthesis) are done;
personas and per-product research continue in the background and land on the Brand context page.
Closes ledger A3, A4 and A5.

## 1. Today

`onboarding-screen` → `LiveSetupScreen` → `use-setup-progress` calls `startWorkspaceSetup()`
(`POST /api/clue/stage0/setup`) once, polls `readSetupStatus()` (`GET …/stage0/setup/current`)
every 1.5 s, derives the checklist rows from eleven Client-KB field states (`data/setup-groups.ts`,
`model/setup-items.ts`) plus the brand-kit ingestion job, and on `status == "complete"` (the old
fast lane) does `location.replace("/session/establish")`. The old recon is composed into the API
and worker whenever `CLUE_SELF_SERVE_PROVISIONING_ENABLED` is on.

## 2. Data seam (`features/onboarding/data/setup.ts`)

* `startWorkspaceSetup()` posts `POST /api/clue/onboarding` with
  `{ company_domain: <profile's company_website, normalised>, brand_id: null }` (the workspace's
  single brand is resolved server-side; a 409 `brand_unavailable` surfaces as the existing
  "isn't available" terminal). Replay-safe: the backend returns the live run for a repeat post.
* `readSetupStatus()` reads `GET /api/clue/onboarding/current` and parses the §7-frozen shape
  (`runId, status, steps[{kind, subjectRef, phase, status, startedAt, finishedAt, costUsd,
  failureCode}], costUsd`) into a new `SetupStatus`:
  `{ status: none|starting|running|complete|failed, steps, brand_kit_ingestion }`.
  `complete` is derived in the model: every `phase == "fast"` step terminal and none failed.
  `failed`: any fast step `failed`. The old `fields`/`official_site` members go.
* The generic `/api/clue/[...path]` BFF proxy already forwards both routes; no new BFF route.

## 3. Rows (`data/setup-groups.ts`, `model/setup-items.ts`)

The row table maps onto step kinds instead of field keys (labels reuse the screen's existing
copy tokens; wording below is the founder's to amend):

| Row id | Label | Steps |
|---|---|---|
| `company` | Understanding your company | `overview` |
| `products` | Your product lineup | `lineup` |
| `proof` | Customer proof | `reviews` |
| `audience` | ICPs and personas | `synthesis` (fast) + `persona` (background, shown as "continuing") |
| `brand-kit` | Brand kit | the design ingestion job, unchanged |

Row status: not started → running → done/failed from its steps; the audience row reads done when
the ICP turn is done and says personas continue in the background. Per-product research steps are
not rows: they land on the Brand context page.

## 4. Release and stall

`use-setup-progress` releases on the model's `complete` exactly as today; the stall bound and
the `none`-poll bound stay. The new lane's run row exists from the POST, so `none` only precedes
the first post.

## 5. Backend

* `CLUE_ONBOARDING_V2_ENABLED` default flips to `true` (settings + `.env.example`).
* `CLUE_SELF_SERVE_PROVISIONING_ENABLED` stops composing the old Stage-0 recon, scrape binder
  and official-site crawl in `projections_main.py` and `fleet_main.py`; those compose only under a
  new `CLUE_LEGACY_STAGE0_RECON_ENABLED=false`, kept until section G retires the old lane.
  Provisioning on no longer means old lane on (A4).
* No change to `onboarding_routes.py`; the brand-kit ingestion trigger already runs from it.

## 6. Tests

Model tests for the step→row derivation and `complete`/`failed` rules; data tests for the two
calls and the 409 mapping; source-contract test that the screen no longer names `stage0/setup`;
composition test that provisioning-on with the legacy flag off composes no recon handler.

## 7. Out of scope

Retiring the old Stage-0 endpoints (section G order); any visual change to the setting-up
screen.
