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
redraw, recolor or typeset a substitute logo. A recognizable authentic target
favicon may be a deliberate account identity anchor; it cannot replace an
explicitly required readable wordmark. Choose a supplied variant that fits its background. Missing
variants are gaps; a white plate is not the absent reversed logo. Preserve the
source logo's aspect and real clearspace guidance. Inspect visible ink against
the local background, including transparent padding and texture; containing the
file does not prove the visible mark is readable. Choose a contrasting authentic
variant or repair the surrounding composition. A group of separate unchanged
real logos and a native separator is valid; do not fabricate a merged or redrawn
company mark.

Related headline, support and action should read as one message group. Establish
that relationship through proximity, alignment and reading order suited to the
reference; unrelated regions need their own separation. A group can be asymmetric
and need no visible card or vertical stack. A headline and its explanation should
not become separate islands merely because each fits its own frame.

Work through the actual copy and its dependent layout together:

Size supporting copy with the approved headline, actual font and inspected brand
reference before allocating the image region. A kit's body role may describe
website text, not a scaled ad. Establish both the first read and a comfortable
second read: tiny support fails legibility, but enlarging it until it competes
with the headline fails hierarchy. Consider visible letter size, weight,
contrast, copy length and grouping together; nominal font size alone cannot
choose the right relationship across different faces or brands.

When a user supplies a corrected composition, inspect its current resolved
typography and keep that relationship for this design's repairs and requested
variants. The saved scene is evidence of that local choice, not a global brand
preference or proof that another run has learned it. For a fresh design, inspect
the references and preference context actually available to that run. Do not
transfer one brand's chosen size or type ratio to unrelated brands or formats.

The diagnostic `resolved_font_size * viewing_width / page_width` explains how
type scales; it is not a universal size target. Meet the minimum text size
alongside visual hierarchy; report a conflict with an approved treatment rather
than silently overriding that treatment.
Preserve an approved headline and change support only as far as needed for the
second read. Give it enough width and height to wrap comfortably; a natural
single line is also valid. Use a supplied size token or checked explicit edit,
then inspect the resolved size because a role may override an authored fallback.
Reflow related spacing after type changes and compare the whole composition at
the same viewing scale; stop when the explanation is readable and subordinate.

1. Use brand tokens and the kit's available families/weights. Choose headline
   width from meaningful phrase breaks and the intended focal scale. Choose
   support width from its own words and available space; it need not match the
   headline width. If support wraps awkwardly, inspect whether a wider measure
   improves it before reducing type size. Prefer content-hugging text height;
   reserve fixed-height slots only when the composition needs them. Kit role
   sizes are source values, not universal ad sizes. No fixed width, line count,
   type ratio or margin fraction follows from this procedure.
2. After preflight, use `inspect(view="geometry", target=<node_id>)` for the
   related text and container nodes. `computed.layout_bounds` describes the
   allocated box; `computed.render_bounds` is not a glyph-ink silhouette.
   `computed.text_lines`, when present, gives each measured painted line box,
   including horizontal/vertical alignment, in page-space unrotated coordinates.
   For ordinary untransformed text, compare the last headline line with the
   first support line and the support's last line with the action. Check the
   visible ink in the current render too: line boxes are not pixel-tight optical
   bounds. Missing/stale geometry, font fallback, heuristic measurement or
   transformed ancestors limit what those numbers establish.
3. Repair the cause of a disconnected group: excess fixed-height slack, a stale
   vertical offset, an unnecessarily narrow support box, or unrelated padding.
   Preserve an approved headline when the support's measure and position are the
   problem. Adjust dependent positions after reflow; don't leave the CTA at its
   old coordinate after the paragraph above it changes height. Use an existing
   auto-layout group's `g(...)`/`pad(...)` where it expresses the relationship,
   or repair the affected parent-relative positions together. Inspect the tree
   before reparenting; structural grouping is not proof of visual grouping.
   When inspection reports a pinned node, honor its authoritative `absolute_box`;
   changing ordinary position fields alone may not move it.
4. If the direction includes a CTA, keep its native label and any button geometry
   in one coherent component, with content-driven padding and brand-supported
   corners. Measure the actual label, then check the whole component's relation
   to the message it acts on. Avoid an independently floating label or detached
   action island. A text CTA needs no invented button frame; a creative without
   a CTA needs no reserved action row.

For emphasis within a sentence, prefer a supported span in one native text node
so the phrase reflows together. The DSL's `[[phrase]]` plus `span(...)` supports
solid/token fill, weight, italic and decorations; it cannot change a span's family,
size or leading. Use only supplied faces. Weight/italic can change line breaks,
so remeasure after emphasis changes. `span(...)` is creation syntax; later edits
use checked structured span operations. A content edit clears old spans: restore
the intended emphasis against the new words. See `knowledge/lumen-dsl/text.md`
for exact syntax and limits. Separate native nodes are appropriate for distinct
independent text roles; coloring one phrase alone is not a reason to split a
headline into manually positioned pieces. Review product names and phrase breaks
after every width change, and revise validated copy explicitly if words change.

Quotes and metrics use independent native text with source-backed qualification
and attribution where needed. Their treatment follows the inspected examples,
not a compulsory card. Use native connectors only when the relationship is real.

Page before spend: on a pageless document compile explicit page dimensions before
logo or image operations. Required authentic target-logo acquisition permits
page-only source preparation before the first complete direction: fetch and view
the real logo, then validate the direction with its returned asset ID. Creative
nodes and artwork construction, including new imagery spend, follow validated
direction. Reserve artwork as an empty leaf `fr`.
For a real raster/logo asset, `asset(action="place", ...)`
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

Author through `compile_dsl_block`, `apply_structured_edit` or other checked
operations only. To change an element that already exists, use
apply_structured_edit or a compile_dsl_block modify line; they are the same
engine operation. Prefer apply_structured_edit for one named element: it is
checked and can be strictly scoped. Use compile_dsl_block for new structure. The
DSL grammar/directives and artboard-frame reference are authoritative mechanics.
Reparenting changes parent-relative placement and paint order. Inspect the new
tree and geometry; an unindexed `parent(...)` can move content before its former
background. For deliberate ordering, use `before`, `after` or indexed `parent`
from `knowledge/lumen-dsl/directives.md`, then check the result. Managed siblings
paint in stored order; pinned absolute nodes use a separate page pass above
managed content and escape ancestor clipping (the page still clips them).
Use measured geometry for repairs.
After changes: preflight, render, view the actual composite and repair the
specific failure. Components that compile still need visual judgment.
