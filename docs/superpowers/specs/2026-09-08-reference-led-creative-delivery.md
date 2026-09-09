# Next steps: reference-led editable creatives

Status: execution plan after the localhost ad-library test. This updates the sequence in the original control plan; it does not report a successful creative or authorize production rollout. Work remains in the same local feature branch.

## Outcome and present evidence

Deliver modern creatives derived from the brand's own references, with editable headline, support copy, logo placement and buttons; raster artwork and original UI/photos may remain independent image layers. Aim for 3–4 minutes per finished creative once the brand library is prepared.

Verified locally: 12 real Conduit LinkedIn ads are stored; all 12 byte endpoints decoded; one immutable ad-style card contains six groups. The real runtime selector chose two relevant product-interface ads and their exact pixels materialized into reference manifests. Collection and style analysis took about 72 seconds. The same onboarding job has now succeeded and linked 12 generated backgrounds. Their visual fidelity and usefulness have not yet been reviewed; do not equate job completion with creative acceptance or re-offer the job.

That proves input availability, not creative quality. Earlier creatives were rejected. PE-15 repaired current-run asset viewing. Other infrastructure repairs and their regression evidence remain separate from aesthetic acceptance.

## What we will do next

1. **Review the generated asset bank, then capture one baseline (PE-7).** Inspect all 12 generated backgrounds against their source references and mark useful/rejected outcomes with reasons. Retain the evidence. Then use a normal business brief with no manual attachment. Record which references the current engine selects, views and forwards; generation versus reuse; rendered output; editable Scene; and timings. This answers what enabling the missing input path changes before rewriting the engine.
2. **Prove one improved layered creative (PE-3, PE-4, PE-5, PE-6, PE-8).** Pin the same brief, brand kit/card and selected reference pixels. Fix demonstrated reference-selection and prompt contradictions; pilot one creative owner with all required tools and a compact layer plan. Request fresh artwork and two retained alternatives without prescribing visual style, scene, palette or fixed layout. Compare candidate and baseline, then prove editing in the browser.
3. **Expand creative range and brand coverage (PE-9).** Only after a convincing exemplar, exercise the five families and brand/format matrix below. Recompose each format. Keep every failure visible; do not select only the best render.
4. **Make the fast path and onboarding reliable (PE-16, PE-17, PE-18).** Improve automatic collection/refresh, safe artwork concurrency and provider capabilities. Measure 3–4 minutes end to end; source/catalog work and offline pregeneration are outside that interactive clock and reported separately.
5. **Close with evidence (PE-10).** Link the accepted editable examples, original sources, retained variants, tests, real export files, timing/cost receipts, and unresolved limits. Website editor changes and production rollout follow separately.

The first working block should end with an inspectable matched comparison and ideally one accepted editable exemplar. The following validation block covers range, reliability and speed. A two-day sprint can establish a proven slice and specific residuals; it cannot credibly guarantee every brand/format or a production latency percentile.

## Ownership and architecture

- **Existing Head of ABM handoff:** business intent, audience, objective, constraints, brand/resource pins and governed source claims. Its implementation remains with the separate Fable effort.
- **Creative DeepAgent candidate:** one owner for reference inspection, creative direction, proposed copy, layout, artwork requests, final inspection and focused repair. Use Aryan's website solo implementation as an ownership pattern while retaining the native Scene editor. Verify actual tool/model traces; a framework argument alone does not prove that implicit helpers are disabled.
- **Reference curator:** bounded background decisions about missing own-brand coverage, relevant provider searches and whether further collection adds useful variety. Add actual registered tools/profile authority before calling it an agent. Fetching pages, downloading bytes, deduplication and storage remain Fleet jobs.
- **Existing shared seams:** governed tools, scoped Postgres records, durable asset storage, generation ledger and project-owned Scene artifacts. No parallel pipeline, provider SDK imports across subsystems, or second authoritative layout schema.

The recommended approach is reference-led layered composition with reuse of exact owned assets. Generating a flattened ad and recovering layers afterward is reserved for concept exploration because text removal, occlusion reconstruction and accurate layer recovery are unreliable. Reusable approved compositions may later accelerate proven families, but must not become the only layouts the agent can produce.

## Every image and layer has an explicit contract

| Element | How it is produced | What must remain editable or verifiable |
| --- | --- | --- |
| Original reference ads | Harvested original bytes | Brand/source/platform/ad identity, digest, dimensions and inspectable reference use |
| Backgrounds, textures, visual atmosphere | Generated or reused raster artwork | Independent placement, size/crop and replacement; fresh versus reused status |
| Foreground artwork, illustrations, mockup treatment | Generated companion or existing owned asset | Independent layer where useful; actual alpha when requested; coherent geometry/lighting with the composition |
| Product UI and photographs | Prefer authentic owned image/SVG assets | Correct source pixels and relevant product view; no invented functionality, metrics or testimonials |
| Logo and partner marks | Exact owned asset | Separate position, size, visibility and allowed color treatment; identity preserved |
| Headline, support copy and CTA labels | Native Scene text | Content/font/style/size editing, copy fit and persistence; no required copy baked into artwork |
| Buttons, cards, badges and ornaments | Native shapes/groups/paths or real SVG | Appropriate independent editing; distinguish SVG/native geometry from vector-looking raster |
| Variants | Separate generated/reused asset records | Unique IDs, same scope, lineage, discoverability and swapping without destroying text/logo edits |
| Final creative and exports | Canonical editable Scene plus derived preview/export | Project/thread/version lineage, saved source document, rendering parity and actual downloaded export |

Do not split every visible thing into separate generated images. Components sharing shadows, reflections or occlusions can remain one artwork layer. Related generated layers use existing Scene boxes, canvas/aspect, scale, ordering and crop/placement properties, plus shared perspective/lighting intent. Generate sequentially when one layer genuinely depends on another's pixels.

The phrase “platform images” here covers the brand/reference library, generated artwork, variants, thumbnails and final exports. These assets can later serve the website editor through the shared catalog; this project does not change website generation or redesign unrelated platform UI.

## Reference selection and labeling

Reuse stored titles, literal descriptions, free-form usage notes and sparse tags. Describe what is visible, why an asset may suit a brief, and where useful source regions are. Preserve human corrections and model/source provenance. Brand preferences, model observations and evidence-backed business claims are different kinds of information.

At the point of use, record the selected asset ID/digest, reason for selection, and intended role: visual inspiration, exact source to preserve, or authorized edit source. Pass the pixels to the model; descriptions alone are insufficient. User-selected references retain precedence.

Fix active brand/kit scoping before adding brands. Fix the current reuse of the first four harvested images across every style group. Make relevant older assets retrievable beyond the recent-24 manifest. Keep user-rejected examples and reasons available as scoped preference feedback; an ad's presence in an ad library does not establish performance.

Collect diverse material through bounded own-brand LinkedIn and Meta provider calls. Report no-results, identity mismatch, partial coverage and provider failures separately. A no-ad-history brand uses website/uploads honestly. Initial collection covers static assets; video/carousel support is not implied.

## Creative range and comparison

Evaluation examples, not hardcoded layout templates:

1. Typography-led awareness with generated brand atmosphere.
2. Product/dashboard demonstration with authentic UI.
3. Review or proof card using sourced/approved copy.
4. Device/mockup composition.
5. Partner or feature launch using badges, icons or vector ornaments.

After the first exemplar passes, use nine rotating cases: Conduit, a second authorized real brand, and a clearly synthetic no-ad-history fixture, each in 1:1, 4:5 and 16:9. Cover all five families, one long-copy case and one manual-reference precedence case across this matrix. Repeat the strongest candidate three times to reveal variance. If a second real brand is not available, test fixture mechanics and leave cross-brand quality unverified. Additional 9:16 placements need their own safe-area tests.

Freeze code, effective prompts/tools, model/settings, brief, brand kit/card, source pixel digests and output requirements for each comparison. Start with sequential batches of one fixed configuration. PE-2 is required before mixed-policy concurrent runs. Do not alter global configuration under active work.

## Three independent acceptance checks

**Reference use:** valid source pixels, correct brand identity, selected-source reasons, actual agent viewing/provider forwarding and honest generation/reuse receipts. A successful download alone does not pass.

**Visual quality:** compare brief, references and the rendered final Scene for brand treatment, composition, hierarchy, readability, relevant assets and meaningful variation. Proposed trial threshold: at least 4/5 in each anchored dimension and founder acceptance of the initial exemplar. Keep independent blind evaluation outside the production critical path initially. Agent self-scores are not acceptance. Add a separate production reviewer only if a measured comparison justifies its cost/latency.

**Editing and delivery:** edit headline/CTA; move/resize logo; alter button styling; replace background/foreground variants; crop/place imagery; test undo/redo; save; reload; reopen; inspect the actual downloaded export against the editor. Required copy stays native. Wrong brand/logo, invented proof, missing resources/layers, baked-in required copy, failed persistence/export or unresolved source references are failures regardless of visual scores.

Inspect both newly generated artwork and the final composition. Persist the reviewed Scene version and repair delta; a later edit requires a fresh check. Do not declare completion while outer/inner run states disagree.

## Speed and cost

The 3–4 minute target starts when the user submits the creative request and ends when its editable source and rendered preview are saved. It includes context selection, provider queueing, all model/tool calls, inspection, repair and save. Cold onboarding is measured separately.

Initial budget hypothesis: 25 seconds selection/composition; 90–120 seconds artwork while native layout is authored; 20 seconds assembly/render; 60 seconds inspection/focused repair/save; 15 seconds headroom. Total: 210–240 seconds. Reduce repeated discovery and model round trips; do not skip quality steps to hit a timer. A full regeneration may exceed this path and must be reported honestly.

PE-17 separates immutable provider production from serialized Scene registration, with preallocated unique IDs and durable cross-process idempotency. PE-18 verifies model availability, reference/edit/mask/alpha capabilities through the configured endpoint and benchmarks quality versus latency. Compare provider changes separately from harness changes.

Report fresh versus cached/reused artwork, per-creative versus batch latency, first-pass acceptance, repair rate, failures, model-call counts and available billed cost. Raw timings and sample size accompany any percentiles; a small control batch is not a production SLA.

## Ticket map

| Work | Ticket |
| --- | --- |
| Baseline/input readiness and conditional mixed-run isolation | PE-1, PE-2 |
| Brand-scoped, meaning-aware reference selection | PE-3 |
| One creative owner, flexible composition and coherent instructions | PE-4 |
| Artwork roles, native overlays and retained variants | PE-5 |
| Reference-aware visual and structural acceptance | PE-6 |
| First convincing matched creative comparison | PE-7 |
| Live editing, persistence and real export proof | PE-8 |
| Other families, brands, formats and no-ad-history fallback | PE-9 |
| Decision, source/resource pins and ABM handoff boundary | PE-10 |
| Existing resource/editor/typography/viewing repairs | PE-11, PE-12, PE-14, PE-15 |
| Existing exit-judge timeout follow-up | PE-13 |
| Onboarding, Meta, refresh, labels, catalog and partial recovery | PE-16 |
| Safe concurrent artwork production and duplicate-spend prevention | PE-17 |
| Provider capabilities, complete status and measured 3–4 minute target | PE-18 |

Prior A–D documents remain experiment history. This guide governs the next sequence. No new creative run, code/model change, deployment, teammate assignment or message is performed by writing this plan.
