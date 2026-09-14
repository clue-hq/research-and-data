# Shared scene composition and native components

Compose from the message and inspected advertiser-relevant references. Identify
the visual invariants first: focal scale, type/image relationships, reading order,
material behavior, characteristic spacing and authentic identity treatment.
Translate those relationships to this content; no full-page skeleton is binding.
Establish one dominant
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
variants are gaps; a white plate is not the absent reversed logo. Preserve the
source logo's aspect and real clearspace guidance. Inspect visible ink against
the local background, including transparent padding and texture; containing the
file does not prove the visible mark is readable. Choose a contrasting authentic
variant or repair the surrounding composition. Do not manufacture a new lockup.

Use brand tokens and the kit's actual type families and weights. Let the real
headline determine its measure and line breaks. Text height hugs content;
width follows the composition. Don't shrink support to excuse overcrowding.
At placement size the headline must be readable and support must still function.
Kit role sizes are source values, not universal ad sizes. Measure the actual
words at the intended output and preview size, then choose hierarchy and line
breaks from the direction. There is no compulsory headline width, type ratio,
margin fraction, card count or two-column split.

If the direction calls for a CTA, build its observed form with native text and
independent geometry when appropriate. Measure label width and height before
adding content-driven padding and brand-supported corner treatment. A text CTA
needs no invented button frame; a creative with no CTA needs no reserved CTA row.
Quotes and metrics use independent native text with source-backed qualification
and attribution where needed. Their treatment follows the inspected examples,
not a compulsory card. Use native connectors only when the relationship is real.

Page before spend: on a pageless document compile the explicit page size, real
copy, existing assets and sized artwork reservation together. Reserve artwork
as an empty leaf `fr`. For a real raster/logo asset, `asset(action="place", ...)`
accepts that frame or an existing image: it changes the leaf to an image in
place, preserving its ID, parent/order and geometry. It cannot consume a frame
with children or create a missing target. Missing asset IDs remain errors.
Path-backed vector assets remain native vectors.

Small mechanical example, using the public tool calls (dimensions illustrate
the reservation only; they are not a composition template):

```python
import json

compile_dsl_block(source='''page sample size(640,240,px)
  artwork fr p(11,23) s(480,128) rd(12) clip(true)
  caption text "Independent native copy" p(11,170) s(480,hug) font_size(20)
''')
# When new artwork is needed; [] deliberately uses no references in this example.
generated = json.loads(asset(action="generate_image", target_node_id="artwork",
    prompt="An isolated folded paper form, no text or logos", reference_asset_ids=[]))
art_id = generated["image"]["asset_id"]
view(target=f"asset:{art_id}")
# After inspecting a successful real output:
asset(action="place", asset_id=art_id, node_id="artwork", fit="contain")
```

For a known existing asset, skip generation and place its real ID into the same
reservation; kit assets use `asset(action="use_brand_asset", asset_id=..., node_id="artwork")`.
Direct DSL `image asset(<real_asset_id>)` is also valid. If a frame must remain a
viewport/container, retain it and add an image child only once its real asset ID
is available, using the checked DSL directives. An `image`/`img` declaration
always needs `asset(...)`; no dummy ID or blank image is needed before placement.
Don't generate a flattened complete ad. Text, CTA, logo and product pixels remain
independent layers.

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
Reparenting changes parent-relative placement and paint order. Inspect the new
tree and geometry; an unindexed `parent(...)` can move content before its former
background. For deliberate ordering, use `before`, `after` or indexed `parent`
from `knowledge/lumen-dsl/directives.md`, then check the result. Managed siblings
paint in stored order; pinned absolute nodes use a separate page pass above
managed content and escape ancestor clipping (the page still clips them).
Use measured geometry for repairs and keep unrelated existing content intact.
After changes: preflight, render, view the actual composite and repair the
specific failure. Components that compile still need visual judgment.
