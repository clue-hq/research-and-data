# Unseeded website capture and library proof

The real ingestion API captured a new brand from only `https://linear.app/` in
103 seconds. This used an empty disposable database, the standard embedded
fleet worker, real network capture and the real asset engine. No captured
snapshots, evidence objects, images, logo records or finished brand pack were
injected. All optional model stages were disabled, with provider keys blank
in the test process. No live workspace was modified.

## What the run proved

| Evidence | Result |
|---|---|
| Automatically selected and durably saved pages | 4: homepage, customer index, OpenAI story, Ramp story |
| Asset registry | 83 records: 40 raster images, 24 vectors, 15 fonts, 4 other |
| Supporting-page-only assets | 32 records, now reachable through the common registry |
| Supporting-byte integrity | 32/32 retrieved through the durable blob seam and SHA-256 matched |
| Agent asset search | Found a supporting-page asset through the real workspace manifest and `search_assets` |
| Reusable section artifacts | 36 draft fragments; no releases or approval bypass |
| Kit status | Draft; structural `product_ready=true` is not visual approval |
| End-to-end rendered fidelity | Not verified |

The prior implementation saved supporting dependencies with snapshots and
fragments but registered only homepage asset jobs. The shared evidence builder
now registers supporting captured images/fonts through the same engine and
governed registry path, deduplicating by digest. Homepage occurrences take
precedence. Other occurrences keep their exact asset URL, capture time and
referring-page provenance. Homepage brand/logo/grammar evidence is unchanged.
Video remains in snapshot/fragment custody; it is not misrepresented as an image.

## Failures and limits

- URL-pattern discovery missed product pages on this unfamiliar site. Coverage
  reports `missing_page_roles=["product"]`; four pages do not satisfy the intended
  homepage-plus-products-plus-customer coverage. Broader observed-link semantic
  classification is still needed.
- Homepage and customer-index fragment coverage is partial; Ramp capture and
  fragment coverage are partial. Job completion does not mean complete capture.
- Supporting assets still lack the optional semantic descriptions generated
  for homepage evidence. Search currently uses available record metadata.
- The agent inventory remains bounded at 2,000 asset records. Capture budgets
  and page limits remain in force.
- Existing cross-job asset upserts can replace curated asset metadata. This
  change preserves within-run homepage precedence; it does not resolve that
  separate lifecycle problem.
- The four live brand workspaces and their assets were not updated. Model-run
  generation still requires the standard runtime prerequisite; no sandbox was
  bypassed to obtain this capture result.

## Regression and supervision evidence

The implementer first reproduced missing supporting registration, then verified
163 focused capture/evidence/fragment/page-plan checks. The final new test module
passed 9 checks, including real engine → durable registry → agent search. Synthetic
fixtures in those regressions are test inputs, not runtime brand seeds.

Parent review found that an initially parametrized malformed-byte test exercised
only empty bytes. It was corrected to separately test malformed base64 and digest
mismatch before acceptance. Parent then independently ran the real URL-only proof
and durable hash/search checks above.

An exploratory broader API run stopped at the known unchanged batch-publishing
Tailwind-dependency failure after 22 passes. That failure is not counted as passing.
No dependency installs or unrelated fixes were made.

## Retained local evidence

All captured public-source bytes and raw logs stay in ignored local setup:

- `.local-setup/website-capture/fresh-url-linear-20260920/scope.json`
- `offered.json`, `latest-job.json`, `result.json`, `assets.json` in that directory
- `durable-library-verification.json`, `capture-status-verification.json` there
- `.local-setup/website-capture/fresh-url-linear-proof.py`
- `.local-setup/website-capture/fresh-url-linear-20260920.log`

The test DB is `clue_web_fresh_20260920_1815`, migrated to `d27183d13445`.
Raw asset counts include responsive renditions and utility media; they are not
counts of unique, suitable hero images.
