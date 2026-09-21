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


## Product-discovery follow-up: second real URL-only run

The shared discovery pipeline now considers tightly scoped, explicitly labelled navigation/footer lists when URL patterns cannot identify a product page. Labels come from a direct group heading or unambiguous ARIA association; whole-page prose and unrelated headings are not evidence. Existing URL/proof roles take precedence. Utility links, foreign origins, credentials, duplicates and over-budget pages remain excluded under the existing rules. No company names or site-specific routes were added to the implementation.

Parent-reviewed regressions include nested-list ownership, conflicting/duplicate/missing ARIA references, utilities, role precedence, query identity, same-origin checks and failed-capture coverage. All 46 focused checks passed independently (37 new, 9 existing). The implementer also caught a list-as-navigation borrowing an outside body heading, reproduced the failure, and closed that leak before handoff. Lint and whitespace checks passed.

A second real API run supplied only `https://linear.app/` in a new empty disposable workspace, with the same model-disabled capture setup. It completed in **147 seconds**:

| Page | Role | Sections admitted / segmented | Coverage |
|---|---|---:|---|
| Homepage | homepage | 17 / 18 | partial sections |
| `/intake` | product | 14 / 14 | captured, sections minted |
| `/plan` | product | 16 / 16 | captured, sections minted |
| `/customers` | customer index | 6 / 7 | partial sections |
| `/customers/openai` | case study | 7 / 7 | captured, sections minted |
| `/customers/ramp` | case study | 6 / 7 | partial capture and sections |

The registry read returned **152 asset records** and the run admitted **66 draft sections**. `missing_page_roles` is now empty; `fidelity_verified` remains false. Asset counts include renditions and utility media. No assets or page lists were supplied, no fragments were released, and the four live workspaces remain unchanged. The retained first run above documents the original miss; it was not overwritten.

Evidence: `.local-setup/website-capture/fresh-url-linear-product-20260920/{scope,result,latest-job,verification}.json`, sibling log/script, and `semantic-discovery-parent-tests.xml`. The initial readback used an incorrect top-level asset-kind field (records wrap their asset payload); that diagnostic field was removed, while the verified record count remains 152.

This closes the observed unfamiliar-product-slug gap, not every discovery case. Unlabelled or nonstandard navigation can still be missed; labels currently use the existing English role vocabulary. Supporting-page redirects can change the origin used by subsequent discovery, a separate existing issue. Missing media/sections, source reproduction, supporting-media descriptions and live four-brand acceptance remain open.

## Customer-image enumeration repair

The stored customer-index snapshot exposed twelve missing wordmarks whose URLs were carried by CSS custom properties. The candidate collector now tokenizes inline declarations, nested rules and registered custom-property initial values through the existing bounded asset-acquisition path. It preserves declaration order, each stylesheet's URL base, exact query identity, deduplication and the existing identity-first asset budget. Strings/comments that merely resemble `url()` are not fetch candidates. No company names or routes are special-cased.

The implementer ran 54 focused checks (12 new custom-property cases, 36 existing asset-slurp cases and 6 media cases); parent independently reran 18 custom-property/media checks. Peer review reproduced three extra edge cases (escaped URL function identifiers, registered defaults, malformed URLs), then verified all were fixed. Ruff and diff checks pass.

A frozen, hash-verified replay of `snap_79578c160535ad71` compared previous/current enumeration: 35 → 47 URLs, exactly twelve missing SVG references added, zero removed, no budget diagnostic. Evidence is `.local-setup/website-capture/custom-property-frozen-replay.json`. This proves enumeration, not a fresh download or visual acceptance. It used existing disposable-workspace source bytes; no new sources were fetched and no workspace assets were seeded.

Separate unresolved findings: external SVG/MP4 fragment suffixes need correct resource lookup and retained output suffixes; one video was correctly refused by the 50 MiB per-video cap. Those issues are not claimed fixed by custom-property enumeration.

## Third URL-only run: acquired media and ordered CSS verified

After the shared media/cascade/reference fixes, another fresh workspace received only `{"url":"https://linear.app/"}` through the real API and embedded worker. It completed in **175 seconds**, with all model stages disabled and no injected assets, snapshots or page list. The disposable database had only two completed fleet tasks before this run.

- Six pages were captured and durably saved; **164 asset records** and **67 draft sections** were created.
- The customer index now has **48 captured dependencies and 7/7 admitted sections**, up from 36 and 6/7 in the preceding run.
- All **12 previously missed customer SVG references** were found in this new capture. Parent read their actual stored bytes, checked SHA-256, matched each to a registry record, and found one by filename using the real agent asset-search tool.
- All **857 persisted stylesheet occurrences** across the six pages retain source order and raw source metadata. Parent checked each effective text against its recorded digest, and checked each page's HTML digest.
- Homepage remains 17/18 sections; Ramp remains 6/7 with partial acquisition. The large-video cap and homepage slot conflict are not closed by this run. No fragment was released, and `fidelity_verified` remains false.

This advances the customer-media fix from enumeration to real acquisition and reusable custody. It does not establish end-to-end visual or model quality. Timing is an observed run duration, not a controlled performance comparison against earlier runs.

Evidence: `.local-setup/website-capture/fresh-url-linear-custody-20260920/{scope,result,latest-job,verification}.json`, sibling capture log, `fresh-url-linear-custody-proof.py` and `verify-linear-custody.py`. The first two read-only search attempts used incorrect engine call/return shapes; correcting the required document id and `web_doc` key completed verification without rerunning capture. Provider/model calls and live workspace writes remained disabled.

External SVG/video fragment identity was separately repaired in commit `7ca33e20`; see `website-reference-identity-validation-2026-09-20.md`. The earlier unresolved note above describes the state at that earlier checkpoint.
