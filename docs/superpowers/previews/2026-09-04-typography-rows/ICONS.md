# Typography rows — icon sources

Companion to `index.html` (Editor Quality Plan 4, item G — founder preview).
**Nothing here is shipped.** No icon file is added and no inspector control
lands in Plan 4; this table exists so the icon decision is made on evidence
rather than on a screenshot.

Local icons live in `apps/frontend/public/icons/chat-shell/inspector/shared/`
and are loaded by name through `InspectorIcon`
(`apps/frontend/src/features/chat-shell/components/inspector-primitives.tsx`),
whose `InspectorIconName` union is the vocabulary a new icon must join.

## The rows

| Row | Icon | Library · version · licence | File path (repo-relative) | Vendored? | Rationale |
| --- | --- | --- | --- | --- | --- |
| Line height | `move-vertical` | inspector local set (authored in-house, no upstream licence) | `apps/frontend/public/icons/chat-shell/inspector/shared/move-vertical.svg` | **yes** | A vertical double-headed arrow is the "how far apart, top to bottom" glyph, which is exactly what a line-height multiplier sets. It is already in the set, already in `InspectorIconName`, and — decisively — it pairs with `move-horizontal` on the very next row, so the two distance rows read as one pair in one drawing style. Reused meaning is this panel's own house style: `ArrangeControls` already uses the same `align-top`/`align-middle`/`align-bottom` glyphs for *both* Layer order and Alignment. |
| Letter spacing | `move-horizontal` | inspector local set (authored in-house, no upstream licence) | `apps/frontend/public/icons/chat-shell/inspector/shared/move-horizontal.svg` | **yes** | The horizontal twin of the row above, and the conventional tracking glyph. Vendored, in the name union, no new asset. |
| Max lines | `rows-3` | lucide-react · 1.28.0 · ISC | `apps/frontend/node_modules/lucide-react/dist/esm/icons/rows-3.mjs` | **no** — would be added as `rows-3.svg` in `apps/frontend/public/icons/chat-shell/inspector/shared/` in the existing `align-*` export style (viewBox trimmed to the artwork, `stroke="#5E636C"`, round caps/joins, `fill="none"`) and added to `InspectorIconName` | A framed box divided into three bands: "the box holds N lines". It is about a *count of lines inside a box*, which is what a max-lines cap means, and it collides with nothing in the set. |
| Wrap | `wrap-text` | lucide-react · 1.28.0 · ISC | `apps/frontend/node_modules/lucide-react/dist/esm/icons/wrap-text.mjs` (a re-export; the node list lives in `.../icons/text-wrap.mjs`) | **no** — would be added as `wrap-text.svg` in `apps/frontend/public/icons/chat-shell/inspector/shared/` in the same style, and added to `InspectorIconName` | The universal wrap glyph (a line turning back on itself under two full-width rules). The local set has no wrapping glyph of any kind, and no local icon comes close enough to bend. |
| Resize | `scan` | inspector local set (authored in-house, no upstream licence) | `apps/frontend/public/icons/chat-shell/inspector/shared/scan.svg` | **yes** | Resize mode is a statement about the *box*, and `scan` is the set's box-with-corner-brackets glyph — a frame being measured. It is vendored, it is currently unused by either inspector (nothing references `name="scan"`; the radius control uses the separate `radius-scan.svg`), so adopting it introduces no collision at all. |

### Rejected candidates, one line each

- **`unfold-vertical`** (lucide, line height) — the strongest lucide option (a
  midline with arrows pushing up and down), but it needs a new file and a new
  name for a distance the vendored `move-vertical` already draws.
- **`align-vertical-space-around`** (lucide, line height) — one block between
  two rails reads as *distribute one item in a container*, which is the
  Alignment family's meaning and would collide with the row directly above.
- **`align-vertical-distribute-center`** (local, line height) — vendored, but it
  is the *distribute* glyph in the alignment vocabulary; using it for leading
  would make the same drawing mean two different things two rows apart.
- **`space`** (lucide, letter spacing) — a single spacebar-shaped stroke; at
  12px it is one nearly-flat line and reads as nothing.
- **`arrow-left-right`** (lucide, letter spacing) — two offset arrows; in every
  other product this is *swap / exchange*, not tracking.
- **`list-ordered`** (lucide, max lines) — a numbered list; it would be read as
  an ordered-list authoring feature, not a line cap.
- **`square-dashed`** (local, resize) — the same drawing as `scan` at 16px, but
  it is already spoken for: the ad panel's Layers rail uses it for **Group**.
- **`move-vertical`** (local, resize) — already taken by Line height above, and
  a resize *mode* is not a single axis.

### Two facts worth knowing before you decide

- **The shipped icon files hardcode their stroke colour and the set is not
  consistent.** `move-vertical` and `align-middle` are `#5E636C` (the field
  label colour); `move-horizontal` and `scan` are `#1C2028`. So in the preview
  the Letter spacing and Resize glyphs sit darker than their own labels. That is
  today's product, not a preview artefact — but it is the kind of thing that
  gets noticed once four icons appear in one section.
- **Any new icon is a three-step addition**, not a file drop: the `.svg` under
  `public/icons/chat-shell/inspector/shared/`, a new member of
  `InspectorIconName`, and the redraw into the local export style (the local set
  is trimmed-viewBox, stroke-width 1; lucide is 24×24, stroke-width 2 — at 12px
  they land within ~0.1px of each other, so the two families do sit together).

## What the founder is deciding

Three things, and only these three:

1. **The rows.** Line height, Letter spacing, Max lines, Wrap and Resize as
   typography controls on the ad text inspector — the right set, in this order,
   with Line height and Letter spacing two-up and Max lines and Wrap two-up
   (founder ruling 2026-09-04). The duplicate Vertical alignment row was dropped
   by the same ruling: that control already ships as the second group of the
   Alignment row and needs no decision. One row does carry a second question:
   **Resize** overlaps the already-shipped "Fit to text" button in the Layout
   section, which makes the same statement in one click — do both belong on the
   panel?
2. **The icons.** The five glyphs above, at the panel's 12px, in front of each
   label. Four are already in the product (`move-vertical`, `move-horizontal`,
   `align-middle`, `scan`); two are not (`rows-3`, `wrap-text`).
3. **The icon source.** That when the local set has no glyph, the icon comes
   from **lucide-react 1.28.0 (ISC)** — already a dependency of the frontend —
   redrawn into the local `align-*` export style and vendored into
   `public/icons/chat-shell/inspector/shared/`, rather than being drawn from
   scratch or imported as a React component at runtime.

One piece of chrome on the page is **not** lifted from the panel and needs its
own yes/no: the **0.05 stepper** on the Line height field. The shipped inspector
has no spinner on any field. The preview draws it from the panel's own
`select-chevron` glyph so it speaks the existing language, but the control
itself is authored for this preview.
