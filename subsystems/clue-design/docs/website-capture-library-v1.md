# Website capture library V1

Status: implemented in the isolated website-capture branch; not deployed to the four running instances. Acquisition is not a visual-fidelity pass.

## Trigger and refresh

First-time onboarding calls the existing guarded `POST /brand-kits/ingest/website` seam. New requests default to `discover_pages: true`. The same default applies to manual Re-extract. The onboarding trigger still enqueues only when the workspace has no prior ingestion job; it does not replay failed or completed jobs automatically. Re-extract is the deliberate refresh/retry path and creates a new draft kit version behind the existing human approval gate. Old frozen job requests retain their recorded single-page behavior.

## Request and bounded plan

The request retains `url`, `name`, and `brand_kit_id`, and adds:

- `page_urls`: up to 19 explicit supporting page URLs. Every URL passes the network guard before enqueue and at fetch time.
- `discover_pages`: defaults to true at the API; direct capture callers default to false for compatibility.

Automatic discovery follows observed same-origin links: up to two product pages, one customer index, and two customer stories. It can discover stories from the selected customer index. It does not invent routes or follow unrelated links. The entry page plus explicit and discovered pages cannot exceed 20. Category selection is a first bounded heuristic, not a relevance or completeness guarantee. Operator-selected URLs can supplement it.

Per-page byte and candidate limits still apply. `LUMEN_SITE_LIBRARY_FRAGMENT_MINT_CAP=240` bounds each library's visible fragment pool and its separate dormant pool. `LUMEN_FRAGMENT_MINT_CAP=40` remains the per-page bound and the legacy ingestion-wide pool. Round-robin allocation prevents a dense homepage from consuming all slots before supporting pages.

## Evidence and outcome

A successful capture retains original HTML, stylesheets, downloaded dependencies, screenshot, geometry and diagnostics. The snapshot metadata includes CSS keyframe names, video/poster URLs, missing video assets, canvas count and script count. Source scripts are not approved for replay, and `canvas_runtime_recovered` remains false. Copying a canvas does not recover a WebGL program.

The private job evidence contains `page_coverage`, including each page's acquisition and fragment-minting status. The existing ingestion-job DTO's `outcome` member exposes a bounded `website_capture` summary: page URLs, roles, acquisition status, asset counts, fragment outcomes, missing categories, and `fidelity_verified: false`. A missing supporting page is reported as failed and does not discard successful pages. HTTP error pages are refused rather than counted as captured originals.

This is currently API-visible coverage. The existing frontend job schema does not render this new summary; a source-library coverage panel remains a separate frontend integration step. A succeeded ingestion job must never be described as verified website reproduction.

## Readiness boundaries

1. Captured: original source evidence was acquired, possibly with explicit gaps.
2. Minted: reusable fragments passed dependency and sanitizer checks; still draft until human release.
3. Fidelity verified: rendered output matches frozen source at the tested sizes and interaction states. No capture operation sets this automatically.

CSS motion can be retained where its selectors and dependencies remain supported. Video requires saved bytes. Arbitrary JS, canvas/WebGL, third-party embeds and private application state require separate supported reconstruction; they are not made executable by scraping. Generated images must carry derived provenance and cannot replace missing originals in a fidelity benchmark.
