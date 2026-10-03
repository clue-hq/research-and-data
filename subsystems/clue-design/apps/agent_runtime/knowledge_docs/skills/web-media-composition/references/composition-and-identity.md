# Source composition, art direction and identity

Read this for product staging, photographic backgrounds, transparent imagery, logos, or generated alternatives.

## Preserve the source composition

Compare the source section's pixels and inspected HTML/CSS. Record its visible crop and object position, display ratio, surrounding whitespace, corner treatment, shadow/border, clipping parent, overlap and stacking order. Source measurements govern; no radius, crop, layout, palette or layering rule belongs to a named regression brand.

Separate what is **inside the image** from what CSS supplies. A product screenshot may already contain rounded corners, UI chrome, shadows or transparent margins. Double rounding can cut controls; wrapping an alpha image in an opaque panel can destroy its intended silhouette. Preserve source alpha and edges. When the available view cannot establish alpha or baked geometry, state the uncertainty rather than calling the crop exact.

`view("asset:<id>")` supplies decoded **preview** alpha counts, visible bounds and
a white/charcoal inspection comparison for non-opaque previews. Its hash identifies
the inspected bytes, not an unavailable original; the comparison surfaces are not
placement assets. A thumbnail can lose original edge detail. Alpha alone does not
classify composition: rounded corners or a slight fade can make a finished
product/background composite non-opaque. Identify the visible background in the
pixels and compare the source's actual staging before choosing a treatment.

Choose per asset, even when several images currently share one CSS class:

| Evidence | Scoped treatment |
| --- | --- |
| Image already includes the product and intended brand field | Preserve that composite. Remove an unintended padded outer rim only for its placements; retain a backdrop if the source uses it through transparent edges. Do not crop into the product to hide the rim. |
| Product artwork has transparent space, shadows or independent foreground parts | Preserve the source's separate brand background and layering. Match source positioning and crop deliberately; alpha bounds are not a safe auto-trim rectangle. |
| Preview/source relationship or composition is unclear | Keep the asset unchanged, inspect source placement and name the uncertainty. Do not infer a new layer arrangement from a filename, alpha percentage or shared class. |

Use separate scoped treatments when a mixed image group requires different
staging. Compare the repaired rim plus product size, controls, shadows and edge
blending at desktop/tablet/phone. Fixing the border by flattening every background
or shrinking all product imagery fails the original request.

Keep product UI readable and recognizable. Preserve navigation, labels, meaningful states and device proportions. Do not redraw a dashboard, edit its metrics, stretch it, or crop out the feature the copy describes to fill an attractive box. If a new crop is requested, retain the original asset and label the selected treatment as an adaptation; verify that the product story remains true.

Stage independent elements independently: decorative background, product screenshot, frame/shadow, foreground accents, copy and logos. Reuse an existing composite when the source is intentionally composite; do not invent editable layers it does not contain. An adaptation can retain the original screenshot inside a new arrangement, but it must not be reported as the original complete composition.

At every viewport verify paint order, clipping, readable contrast and subject visibility. A landscape hero replaced with a flat color or an arbitrary split layout is a material composition change, even if the palette and font match.

## Background and art-direction decision

Describe the source field in concrete terms: subject/environment, horizon or vanishing point, scale, focal location, negative space, palette, light, texture, gradient direction/stops, and relationship to foreground content. Preserve the source CSS gradient/texture when it already works. Do not replace characteristic scenery with generic decoration simply because asset retrieval was inconvenient.

Use **reuse** when an existing asset meets meaning, pixels and usage. Use **deliberately none** when the source/brief supports a type-led composition. Use **generated derivative** when a newly authored decorative/photo field serves the brief and the relevant source is unavailable or a variation is requested. Authentic reused imagery is a complete valid outcome; generation is not required every turn.

The web tool accepts:

`asset(action="generate_image", prompt=..., aspect_ratio=..., width=..., height=..., transparent_background=..., label=..., alt=...)`

It does not accept scene-only `target_node_id`, `brand_notes`, or explicit reference-image arguments. Brand notes/style conditioning are resolved internally; do not promise a particular attached reference was used without its returned provenance. Describe subject, source-derived composition, lighting, texture, palette and necessary negative space in the prompt. Keep logos and page copy separate. For a decorative field request no text or logos. Preserve exact product/customer assets outside the generation.

Read diagnostics and generation provenance, then inspect the returned pixels. This tool can fall back to a deterministic placeholder if the provider is unavailable; a returned id is not proof of successful model generation. Label a new generated field as a derivative in the plan/review, record its asset id and source inspiration, and retain the originals. Never claim it was captured from the company's site, shows a real named customer, proves a product capability, or restores a missing original.

## Logo and customer identity

First use the seller's selected kit/library assets and view the actual logo on its intended surface. Distinguish a full wordmark/lockup, bare symbol, product mark, customer/partner mark and unrelated program/sub-brand. Do not turn a decorative arrow into the seller identity or repeat seller wordmarks as generic proof imagery.

For a target/customer/partner with a verified domain, the governed tool is `fetch_logo(domain, company_name=None, force_refresh=False)`. It returns proven family cells: `light_lockup`, `dark_lockup`, `light_mark`, `dark_mark`; “light” means for a light background. Missing cells are valid. Inspect the result; choose completeness and surface contrast for the placement, not merely the first id. Alternatives retain their rejection/selection reasons. Use force refresh only when the user reports a wrong/outdated logo.

If identity is ambiguous or `needs_review` is returned, leave the logo absent and name the gap. Do not substitute a loyalty program, infer a domain from a company name, recolor a dark asset into a nonexistent variant, typeset/draw a wordmark, or generate a logo. A named customer image/logo still needs the existing evidence for any testimonial or endorsement claim.

When the account is bound and a fetched mark is proven for it, `bind_account_logo(account_id, asset_id)` can persist the association; respect any refusal. A binder-unavailable response means a page asset may exist without a durable account binding. `asset(action="use_account_asset")` registers a logo from the account card. Keep the account derivation markers required by the chosen authoring lane; placement alone is not verified identity or reusable account binding.
