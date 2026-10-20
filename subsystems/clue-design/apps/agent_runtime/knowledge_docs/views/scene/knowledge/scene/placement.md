# Scene placement and recomposition

Use the requested canvas and delivery surface. If unspecified, infer a useful
starting size from intent and record the assumption; dimensions alone do not
identify a channel's current safe area or prove that its overlays were checked.
These are supported authoring examples, not a statement of current ad-platform
requirements. Confirm supplied placement specs or available current platform
evidence before promising channel compliance.

The minimum text size in your instructions is a rejection floor, not the target
type scale. Keep judging hierarchy, contrast, actual glyphs and product detail.
The feed minimum doesn't fit print or other viewing conditions; record that
mismatch instead of changing units to evade it.

| Placement example | Explicit page dimensions | Decision to verify |
|---|---|---|
| Square feed | `size(1080,1080,px)` | Actual feed display scale and crop |
| Portrait feed | `size(1080,1350,px)` | Whether the intended feed preserves 4:5 |
| Story / full-screen vertical | `size(1080,1920,px)` | Current top/bottom chrome, captions and action overlays |
| Landscape creative | `size(1200,628,px)` | Requested ratio and small-display legibility |
| Personal cover example | `size(1584,396,px)` | Avatar overlap and desktop/mobile crop |
| Company cover example | `size(1128,191,px)` | Actual narrow-screen crop and profile overlays |
| Display ad examples | `size(300,250,px)`, `size(728,90,px)`, `size(160,600,px)` | Exact contracted slot, export and size constraints |
| A4 print | `size(210,297,mm)` | Trim, bleed and output requirements in `knowledge/export/print-geometry.md` |

The DSL grammar defines page syntax and units. Declare a real page and measured
frames before image generation. Pixel page units currently lay out in the same
numeric scene coordinates; do not treat print millimeters as pixel coordinates.
Keep editable source copy, identity, product images and generated art separate.

Recompose across aspect ratios instead of uniformly scaling a finished ad. Keep
the direction's important visual relationships while remeasuring headline lines,
support, labels and any CTA; adjust image frames and crops around meaningful
product content. An ultra-wide banner may need shorter copy or a different focal
relationship. A vertical version need not become a fixed three-beat ladder.

Adapt each message group as a unit using the procedure in
`knowledge/scene/components.md`. Reflow the real words at the new width before
placing the group's dependent elements. Headline and support may need different
measures; a narrower canvas does not justify preserving an accidental line break
or shrinking the explanation until it no longer works. An approved headline can
remain intact while support gains usable width and moves closer. Recheck the CTA
after that reflow. Judge the spacing between visible text and its companion
elements, not just the empty area allocated to their frames; generous whitespace
elsewhere does not require a large gap inside a closely related message.

Render and inspect both the whole composition and its intended display size.
Verify that headline, explanation and action connect in the intended order,
emphasized phrases survive reflow, and body copy remains usable rather than
merely clearing a technical minimum. The nominal-size review profile and the
preview's text-size table do not measure grouping, optical spacing or raster text.

Use a placement-specific overlay or supplied safe-area specification when one is
available. Review at the actual visible crop and display scale. In a story, check
the top and bottom interface; in a cover, check the avatar and viewport crop; in
a display slot, check the exact slot; in print, check trim and bleed. Do not apply
a universal bottom mask, fixed content band, or inherited social-safe-margin
percentage to every format. Without verified overlay evidence, record the
assumption and preserve practical breathing room around essential content.

Protect logo clearspace, the product detail named in copy, attribution and action
legibility wherever those elements occur. Edge-to-edge art can be appropriate;
essential pixels must survive the intended crop. Exact source extraction uses
the crop mechanics in `knowledge/scene/components.md`. Inspect the final rendered
composition after adaptation; a within-bounds scene alone does not prove a good
or platform-safe placement.
