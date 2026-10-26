# Asset context and bulk upload

Date: 2026-09-21

Review/reference branch: `ICP-definition/head-of-ABM-improvements`

Implementation base: latest `origin/research-streaming`, on a fresh feature branch.

Status: **Proposed contract for founder review; no implementation or live enrichment run yet.**

## Intended experience

Assets collected from a website, harvested from the company's published ads, or uploaded by a user appear in the existing Brand Context → Assets section. Each asset has a useful type, a human description with when-to-use guidance, and detailed context the design agent can retrieve. Users can upload several assets in a floating dialog, accept suggested types or set them individually/in bulk, and return to their work while analysis finishes.

Implementation order follows the request: improve website/ad ingestion and agent consumption first; add manual bulk upload next. Both use the same enrichment contract.

### Description coverage and model — founder direction, 2026-09-21

The founder wants each ingested image described and displayed in the frontend, with no separate batch action. A 100-image cap is acceptable only if technically necessary. The selected description model is **`deepseek/deepseek-v4.1-flash`** through the existing OpenRouter gateway.

Recommended execution decision: **no additional total-image cap for descriptions**. Remove the top-16 selection; process every distinct eligible asset registered by this ingestion. Keep existing page/capture and file-validation boundaries: this does not turn ingestion into an unlimited crawl of every linked page. Deduplicate repeated occurrences by asset/input identity while retaining all relevant source-use context.

Process one image per model request, starting automatically when its bytes and source context are available. The founder's revised concurrency requirement is **15 concurrent description requests by default**, configurable upward, replacing the earlier recommendation of five. Coordinate with the existing shared provider limits; any lower effective provider allowance must be visible rather than silently presented as 15. This limits simultaneous work, not the number of images that receive descriptions. An available execution slot immediately takes the next image; there are no fixed-size waves, provider Batch API, or user-triggered follow-up batches.

Save each result independently and refresh that asset's frontend description as soon as it is persisted. Track completed/total progress for the same ingestion operation. Description work is fully complete only when all eligible assets succeed; exhausted retries or missing previews produce explicit partial/failed status and per-asset retry. A failed image does not discard successful descriptions. The underlying durable scheduling remains an implementation detail so closing the page or restarting a worker does not lose work.

Verified 2026-09-21: [OpenRouter's model page](https://openrouter.ai/deepseek/deepseek-v4.1-flash) lists image input and structured outputs for this exact model. Use it for classification, human reference and agent context in the shared per-image analysis call. Configure it through existing `LUMEN_INGESTION_DESCRIBE_MODEL`; update the root/subsystem environment examples and local configuration consistently during implementation. This choice is specific to asset descriptions, not a change to the other onboarding/design models. Schema conformance and visual quality still need a live sample; documentation verification alone is not a successful inference test.

The model and coverage changes are recorded here; application configuration and runtime code have not yet changed. The conditional fallback of 100 images is not being adopted because bounded concurrency addresses load without discarding description coverage.

### Development branch and pilot separation

The founder wants implementation on the latest `research-streaming` code without importing Shank's standalone Conduit pilot. Keep this reference branch and workspace intact. Start a fresh feature branch (suggested name: `asset-ingestion/improvements`) in a new Conductor workspace from the freshly fetched `origin/research-streaming`.

Verified 2026-09-21: the remote tip is `ab31814a2` and matches the local remote-tracking ref; the checked-out local `research-streaming` in `jerusalem-v1` is older (`92a65d552`). Neither tree contains `experiments/brand-context-agent-v1/`, `deliverables/brand-context-pilot/` or `docs/brand-context-research-handoff-v1/`. These hashes are a snapshot: refresh before creating the implementation branch.

Carry only this design document to the new branch. Do not merge this entire reference branch, or replay its pilot/ICP experiment commits. Read the saved pilot here as reference when needed, then implement the agreed behavior in the production ingestion/metadata/frontend seams. The production feature must not import experiment modules or depend on the pilot deliverables.

At this snapshot the describer, description DAL, ad-onboarding module, Brand Context feature directory and editor asset-library adapter are identical between the reference branch and `origin/research-streaming`. The central design API differs; re-read its latest composition/job wiring, current instructions and migrations before implementation. Use isolated DB/Redis/ports for the new workspace's verification. Eventual integration should contain only feature code, focused tests/migrations/config and relevant feature documentation, with `research-streaming` as its target when publication is explicitly requested.

New-workspace handoff: restore only `docs/superpowers/specs/archive/2026-09-21-asset-context-and-bulk-upload-design.md` from the preserved `ICP-definition/head-of-ABM-improvements` branch, then commit that document on the new feature branch. A single-file restore copies that file's contents without bringing the source branch's commit ancestry or other files. No branch switch, new workspace or remote publication was performed while preparing this plan.

## What exists and what changes

| Surface | Verified current behavior | Proposed change |
| --- | --- | --- |
| Website capture | Captures the entry URL and supplied pages under capture budgets; this is not a guarantee of every image across an entire site. | Keep capture ownership and diagnostics. Enrich every eligible successfully ingested image, with explicit pending/failed/unsupported states. |
| Website description | All logos plus at most 16 selected images get `title`, a literal caption, one usage sentence and tags. Context is essentially brand/source, without the rich page-use evidence needed for classification. Existing rows are reused without prompt-version invalidation. | Versioned structured visual analysis for every eligible ingested image, using image + source occurrence context. Process continuously with bounded concurrency and publish each human/agent projection immediately on save. |
| LinkedIn ads | PDL resolves company identity before Adyntel harvest, with fallback. The current harvest selects static company image ads. Per-creative headline/commentary/provenance are stored; Ad DNA summarizes the collection. | Enrich each accepted creative using image and its stored copy/provenance. Keep Ad DNA as the separate collection-level summary. |
| Asset metadata | Workspace-scoped `design_asset_description` stores the four caption fields; AI cannot replace human-authored rows. | Extend the same domain with structured analysis, classification, revisions, status and field-level human overrides. |
| Agent | Kit card clips descriptions/usage; library manifests include existing caption fields. Website mode can search its manifest; scene mode has a bounded recent library. | Searchable compact metadata plus on-demand detailed context and visual inspection in both modes. Selected ad references include their own context. |
| Assets UI | Screenshot → mockup; most other kit images → background. Registry assets are labeled upload/generated and have no joined description. Reads stop at the first 200 records per image kind and return early without a kit. Detail edits are local state. | Separate type from source; join durable metadata; paginate; show assets without a kit; persist edits through the repository seam. |
| Upload | Single-file `POST /assets` and editor upload exist. Brand-kit asset ingestion is a different operation. No bulk upload button exists in this Assets panel. | Reuse asset custody with retry-safe per-file upload, metadata and enrichment scheduling. Add the floating upload dialog to this panel. |

Sources: [describer](../../../../subsystems/clue-design/apps/api/lumen_ingestion/describe.py), [description DAL](../../../../subsystems/design/clue_design/descriptions.py), [capture evidence](../../../../subsystems/clue-design/apps/api/lumen_ingestion/capture/evidence_builder.py), [ad onboarding](../../../../subsystems/clue-design/apps/api/lumen_ingestion/ad_library/onboarding.py), [ad runtime](../../../../subsystems/clue-design/apps/api/lumen_api/ad_runtime.py), [asset API/manifests](../../../../subsystems/clue-design/apps/api/lumen_api/main.py), [frontend repository](../../../../apps/frontend/src/features/brand-context/data/brand-context.repository.ts), [mapping](../../../../apps/frontend/src/features/brand-context/model/brand-context-mapping.ts).

## One enrichment contract, three inputs

Website ingestion, ad harvest and manual upload continue to own acquisition. After durable asset registration they request the same enrichment worker, bounded in simultaneous requests rather than total description count. Each image gets a structured multimodal LLM call using `deepseek/deepseek-v4.1-flash`, with validation and bounded retry. This is not a new browsing agent. All source context is supplied by the originating pipeline.

One analysis produces both presentations; human and agent descriptions are not independently generated stories. Preserve the pilot's distinction between observed facts and suggested uses. The pilot's keyword-generated product/document links are hypotheses, not verified associations to copy into production.

### Shared metadata

| Group | Fields / meaning |
| --- | --- |
| Identity | Workspace-scoped asset ID, accepted-original digest, MIME, dimensions, preview identity, schema version. Registry/storage remain authoritative for bytes, provenance and licensing. |
| Source | Website / LinkedIn ad / user upload / generated. Source occurrences retain page URL and locator, or creative ID and ad permalink, or upload identity; retain brand association when known. Source is never inferred from appearance alone. |
| Classification | Primary `creative_type`; zero or more `usage_roles`; reason/evidence; AI or human origin; uncertainty. |
| Human reference | `title`, `description`, `when_to_use`, optional `avoid_when`, concise placement/crop guidance, tags. |
| Agent context | Structured observations, use guidance, source-specific context, uncertain interpretations and original/preview distinctions, detailed below. |
| Lifecycle | Analysis revision; prompt/model/input fingerprints; queued/analyzing/ready/failed/unsupported status; diagnostic/retryability; field-level human overrides. |

**Type vocabulary proposed for review:** ad, logo, background, product image, product screenshot, photo, illustration, icon, badge/seal, other, unknown. A logo also needs a relationship qualifier: own brand, customer, partner, third party, unknown. Seeing a logo does not prove that relationship.

**Usage roles:** section background, hero image, card image, inline image, reference only. Multiple roles are allowed. This lets an asset be a product screenshot used in a card, or an illustration used as a section background. The UI displays these labels directly; users do not need to understand storage categories such as `raster_image` or `vector`.

Classifying an upload as `ad` does not label it a verified published ad. Classifying an upload as `logo` does not promote it to an approved brand-kit logo variant. Keep the existing brand-authority semantics.

### Detailed agent context

- **Observed visual content:** subjects, composition, colors, readable text, typography characteristics, logo placement, negative space, original transparency. Record illegible text as unknown; do not invent font names or measurements.
- **Observed source usage:** page/section/card placement and available surrounding heading/alt/caption; or advertiser, creative ID, headline and commentary from the ad record. Distinguish supplied ad copy from text actually visible in the image.
- **Recommended use:** when to use it, suitable layouts and pairings, crop/placement guidance, background suitability, what should remain intact, and when it is unsuitable.
- **Ad interpretation:** messaging angle, tone, CTA, visual hierarchy, copy density, product/use-case hypothesis, and specific design patterns that could inspire a new creative. Mark inferred audience as a hypothesis. Published status proves neither performance nor current approved strategy.
- **Boundaries and uncertainty:** missing context, unclear copy, ambiguous product/logo identity, reference-only guidance where appropriate, and preview transformations. An inspection matte or website CSS inversion is not a new original asset.

A source-free upload can still be analyzed visually. Leave website-placement history and published-ad provenance absent; offer an optional user note. Source text is untrusted evidence, never instructions to the worker.

### Source evidence and brand association

Website inputs must carry available DOM/CSS placement and surrounding text forward; a pixel-only call cannot establish whether a picture came from a card or section background. The capture layer already has locators and evidence pointers; enrich this handoff instead of making the describer recrawl pages.

Ad inputs use existing creative provenance, headline and commentary. Retain current company-identity checks and static-ad scope. Supporting video/carousel analysis is a separate extension, not an implied result of adding image descriptions.

Keep reusable visual observations attached to the workspace asset. Brand/product interpretations belong to the relevant source occurrence or existing brand association. The same bytes can appear on different pages or for different brands; do not merge these interpretations into a global brand claim. Unassigned uploads are workspace assets until associated explicitly; do not silently bind them to whichever kit is newest.

## Storage and execution

- Extend the existing description domain and DAL; do not create a second caption store or add rich prose to Rust scene/kit engine types. Preserve legacy `title`, `description`, `usage`, `tags` as compatible projections for old consumers.
- Validate the structured payload in Python and frontend Zod. Persist an analysis revision and retain the source references used. A design run consumes a fixed metadata revision alongside its asset/reference snapshot.
- Keep generated analysis separate from overrides. Changing a title/type must not prevent future AI updates to untouched fields; regeneration must never overwrite the user's chosen type or wording. Explicit reset-to-suggestion is distinct from an omitted field.
- Cache by original/preview digest, relevant source-context digest, schema/prompt/model configuration and brand association. A changed prompt or source occurrence makes the old generated analysis stale. It does not erase edits.
- Schedule through the existing durable fleet/job seams after custody. Reuse supported task infrastructure rather than adding an in-process fire-and-forget queue. Keep source asset registration and durable scheduling atomic or reconcilable through the existing transaction/job pattern.
- Asset usability and analysis status are distinct: an image can be available while description generation fails. Show partial progress and retry one failed analysis without downloading/uploading everything again.
- Retain bounded concurrency, spend accounting and retries. Replace top-16 selection with automatic continuous processing of every eligible ingested image, with a default allowance of 15 requests in flight, coordinated with shared provider limits. Document the new concurrency setting/default in root and subsystem environment examples when implemented, with local configuration parity. Do not tie description coverage to brand-card prompt size or introduce a 100-image cutoff. If an existing explicit spend limit or provider outage prevents completion, surface the actual reason and unfinished count; never report full success or silently omit images.
- Old human-authored description rows migrate as protected overrides. Existing legacy captions remain readable. Historical enrichment is a separately inspectable, resumable backfill with counts and a cost estimate; this proposal does not authorize an immediate paid backfill.

## Backend ↔ frontend contract proposal

These are additions to review, not claims about endpoints already implemented. Record the ratified shapes in [the Brand Context API contract](../../../../apps/frontend/docs/api-contracts/brand-context.md) during implementation.

| Operation | Proposed contract |
| --- | --- |
| Upload | Extend existing multipart `POST /assets` with an idempotency key, optional classification/usage/user note and explicit existing brand association. Replaying an identical file request returns the same asset/job; conflicting reuse of a key is rejected. Return existing asset payload plus enrichment status/reference. |
| Metadata read | Extend existing batch `GET /assets/descriptions` response additively with effective type, roles, human reference, agent context revision and status. Do not require one metadata request per grid tile. |
| Human edit | Extend existing governed `PUT /assets/{id}/description` mutation with optional classification, human-reference fields and explicit override reset semantics. Preserve legacy callers and omitted-field behavior. |
| Retry | Add an explicit retry operation for failed/stale asset analysis using the same durable worker and workspace authorization; return status/job reference. Exact route follows the existing design-job API conventions. |
| Repository | Add upload/update/retry operations beside reads; Zod-parse responses; browser requests use authenticated BFF and server-derived workspace. Extend fixture and HTTP adapters together. |

Bulk UI can coordinate bounded per-file uploads through this contract; a second all-or-nothing bulk custody API is unnecessary. A mixed batch reports per-file results. Classification selected before upload is stored with registration; edits during analysis persist as overrides. Refreshing the library fetches effective metadata instead of overwriting it with kit captions.

The Assets page must remain usable before any brand kit exists. Fetch workspace assets independently of kit selection and paginate the registry. Replace source-as-type filters with separate **Type**, **Used as**, and **Source** filters. Do not leave rename/type/description edits as local-only state.

## Design-agent consumption

Keep the compact brand card. Add short type/use summaries and metadata references to searchable asset inventory. Expose full effective context through the existing asset inspection/read boundary; add an equivalent searchable discovery path for scene mode, where only a recent bounded subset is currently supplied. Keep storage access in the API composition layer and hand immutable data to the agent runtime through established manifests/seams.

When published ads are selected as references, attach each selected creative's context and revision along with its image and the existing Ad DNA summary. This covers language and messaging as well as visual inspiration. Merely saving `agent_context` in Postgres would not satisfy the request.

Both scene and website design modes must be able to discover and inspect an older relevant asset. Do not solve this by dumping every long description into every prompt or preloading every image into a scene cache.

## Floating bulk-upload window

Entry: **Brand Context → Assets → Upload assets**. Use the existing modal/dialog primitives and canonical design tokens; no new page or route.

1. Drop multiple files or use a multi-select file picker.
2. Show a row per file: thumbnail, filename, detected format/size, Type (default **Auto-detect**), optional Used as, and status.
3. Let users select rows and apply a type/role to the selection; allow per-row correction. User choices win over later model suggestions.
4. **Upload assets** starts a bounded batch. Each row progresses through uploading → analyzing → ready, or shows its specific error and retry action. Successful files stay successful if another file fails.
5. Once bytes are safely uploaded, the user can close the dialog while server-side analysis continues. Keep the upload controller mounted outside the dialog so closing/reopening does not discard an active batch; distinguish closing the window from cancelling pending transfers.
6. New assets appear immediately in the grid with honest analysis status. Asset details show **Reference** (description, when to use, placement) and **Agent context** (expandable detailed analysis). Classification and human notes are editable and saved.

Suggested format scope pending the user's answer: PNG, JPEG, WebP, SVG, GIF and AVIF. PNG/JPEG/WebP/SVG have an established frontend path. The engine recognizes GIF, but frontend support is intentionally narrower today; AVIF also requires capability work. Additional HEIC/TIFF/BMP support needs explicit conversion coverage, not just `accept="image/*"`.

Preserve accepted originals and record transformations; SVG continues through existing sanitization and raster-preview handling. A derivative used for analysis or static placement is not a replacement for an animated original. GIF/animated WebP analysis must either inspect representative frames under a documented policy or state clearly that only a frame was inspected. Verify formats across upload, custody, preview, vision input, scene placement and website rendering before advertising support. Show actual server file-size/format limits in the dialog.

## Delivery and verification

1. **Metadata and worker:** reviewed schema, migration, compatible DAL/API, prompt, validation, source evidence handoff, durable scheduling/cache/overrides. No frontend integration before contract sign-off.
2. **Website + ads + agent:** invoke shared enrichment in both ingestion paths; retain Ad DNA; expose metadata to both design modes and selected references. Compare representative assets against the pilot.
3. **Manual uploads + Assets UI:** reusable uploader, format capability work, floating batch dialog, persisted classification/notes, pagination and kit-independent reads.
4. **Optional historical backfill:** enumerate existing assets and stale records, estimate cost, then run only under explicit scope approval.

Acceptance checks:

- Website background, screenshot-in-card, own logo, customer logo, published static ad and manual unknown-source image all retain correct provenance and distinct type/use labels.
- Human descriptions give concrete when-to-use guidance. Detailed context separates observations, supplied copy and interpretations; no fabricated copy, audience, brand authority or performance.
- Repeating a job/upload is idempotent; changed source/prompt triggers appropriate regeneration; editing during analysis cannot lose the human choice.
- A run with 137 eligible uncached images requests descriptions for all 137, permits 15 simultaneous calls by default when provider capacity allows, respects the configured concurrency limit, publishes individual results before the run finishes and needs no second user action. Repeated asset occurrences do not cause redundant identical analysis calls.
- Assets beyond the old top-16 and first-page UI limits remain discoverable; analysis failures preserve originals and are retryable. A partially failed run cannot report all descriptions complete.
- Scene and website agents retrieve the same revision of an asset's context; published-ad references carry per-creative language/design guidance.
- Mixed-success bulk upload, reopen, per-file retry, bulk classification and reload persistence work in the browser. No-kit workspaces can upload and view assets.
- Verify each advertised format end to end, including transparent SVGs and animated originals. Unsupported formats get a truthful per-file result.
- Workspace isolation, governed mutation and migration reversibility remain intact. Use an isolated runtime/database for live checks.

Run focused backend/DAL/runtime and frontend repository/controller tests for these behaviors, the required migration smoke on a clean workspace-local DB, and affected package gates. Frontend gate: design-system build, lint and build. Engine gates apply if format support changes Rust/helper/WASM code. A live provider sample should demonstrate actual quality after implementation; mocked schema tests alone cannot establish description quality.

## Review requested

Approve the shared metadata contract and floating-dialog flow, including separate **type**, **usage role** and **source**. Confirm the upload format scope. Existing paid backfill and video/carousel-ad ingestion are separate actions.

This review is required by [AGENTS.md](../../../../AGENTS.md): “Every screen/flow starts with an explicit contract-gap review with the founder … and gets sign-off before implementation.” The implementation has not started; this document makes the required review concrete.
