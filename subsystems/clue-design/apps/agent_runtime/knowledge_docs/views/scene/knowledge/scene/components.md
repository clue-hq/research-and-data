# Shared scene composition and native components

Compose from the message and inspected brand sources. Establish one dominant
element, a clear second read and intentional space. Components are reusable
mechanics, not fixed proportions, mandatory cards or required layout patterns.
Recompose for the actual words, imagery and aspect ratio. Type-only is a valid
finished direction when imagery is optional; requested new artwork still needs
generation. CTA, eyebrow, benefit row and proof card are optional.

Use native editable text for copy, native geometry for frames, simple paths,
connectors and meaningful UI-independent diagrams. Use real independently
placeable images for logos and authentic product screenshots/photos. Never
redraw, recolor or typeset a substitute logo; a favicon does not replace a
readable wordmark. Choose a supplied variant that fits its background. Missing
variants are gaps; a white plate is not the absent reversed logo.

Use brand tokens and the kit's actual type families and weights. Let the real
headline determine its measure and line breaks. Text height hugs content;
width follows the composition. Don't shrink support to excuse overcrowding.
At placement size the headline must be readable and support must still function.

Page before spend: on a pageless document compile the explicit page size, real
copy, existing assets and sized artwork reservation together. New image nodes
require actual asset IDs: generate against the sized frame only after the page
exists, inspect the returned image, then insert it. Don't generate a flattened
complete ad. Text, CTA, logo and product pixels remain independent layers.

For an existing asset use `asset(action="place", asset_id=..., node_id=..., fit=...)`;
for a kit asset use `asset(action="use_brand_asset", asset_id=..., node_id=...)`.
Logos use contain with clear space; product crops preserve the relevant UI or
object. Don't destructively crop an asset just to rescue a preselected skeleton.
Read `knowledge/scene/references.md` when generating a component.

Image fit changes pixels inside the node, not the node's layout bounds. Keep a
product image node inside its intended viewport, with parent-relative geometry.
Use `place` with cover/focal for a verified crop or contain for the intact source.
Do not progressively enlarge and offset a child beyond its parent to guess a
crop; this causes bounds failures even with contain. A clipping parent does not
make overflow valid, and `bleed(true)` is not a repair for missing product content.
If the desired crop cannot preserve the meaningful UI, adapt the frame to the
whole source or choose a different source. Keep tabs, labels and proof named in
the copy readable; inspect geometry once and repair the complete image/frame
pair together instead of spending several compiles on coordinate nudges.

For exact source-pixel extraction, inspect the original image and its dimensions,
then use `asset(action="crop_image", asset_id=..., crop_rect=[left, top, right, bottom])`.
Use integer bounds in original pixels, not preview pixels:
`0 <= left < right <= source_width`, `0 <= top < bottom <= source_height`;
right and bottom are excluded. The source stays intact and the result is a new
image asset. Inspect it before explicitly placing it in an independent image node
with `asset(action="place", ..., fit="contain")`. Cropping cannot remove a background
baked inside the selected rectangle or recover missing/occluded product content.

An inspected reference's soft material, blur, tonal variation or texture is part
of its treatment. A flat brand-color rectangle does not preserve those properties.
Reuse appropriate source artwork or generate the separately placeable treatment;
use a flat field only when that is the intended and justified visual direction.

Author through `compile_dsl_block` or supported checked operations only. The
DSL grammar/directives and artboard-frame reference are authoritative mechanics.
Use measured geometry for repairs and keep unrelated existing content intact.
After changes: preflight, render, view the actual composite and repair the
specific failure. Components that compile still need visual judgment.
