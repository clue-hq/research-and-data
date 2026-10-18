---
name: print-bleed-marks
description: Bake print bleed and crop marks INTO the design as canvas content — grow the page into a press sheet, extend edge art through the bleed, and draw trim ticks as scene nodes — so a plain/normal export (no print profile options) is already print-ready. Use when the user asks to "add bleed marks", "add bleed", "add crop marks", "prepare this for offset printing", or wants marks visible on the canvas itself. NOT for the standard print-export route (page bleed metadata + print PDF profile) — that is knowledge/export/print-geometry.
---

# Print bleed & crop marks — baked into the canvas

The user wants the design itself to become a **press sheet**: artwork extended
through the bleed, trim ticks drawn at the corners, everything visible on the
canvas and present in ANY export — including a plain PDF/PNG export with no
print options selected. This skill is the sanctioned exception to the
"never author marks as scene content" rule in `knowledge/export/print-geometry`:
that rule protects the METADATA route; this skill IS the baked route, applied
only when the user explicitly asks for it.

## Choose the route first — they are mutually exclusive per page

| Route | What carries bleed/marks | When |
|---|---|---|
| **Metadata** (`knowledge/export/print-geometry`) | `#page:` `bleed(x,y,w,h)` + the print PDF export profile draws marks at export time | Default for print documents. Design stays trim-sized; marks appear only in print-intent exports. |
| **Baked sheet** (this skill) | The scene itself: bigger page, extended art, mask + tick nodes | User asks for bleed/marks ON the design, or wants a normal export to be the print file. |

**Never combine them on one page.** A baked page must keep `bleed(...)` /
`safe_area(...)` page metadata UNSET, and the user must export it as a normal
export (or print finish "None"). Metadata bleed on an already-baked page makes
the export pipeline add a SECOND bleed and a second set of marks around your
baked ones — a double-geometry file no printer can use.

## The sheet construction — three zones

All constants in canonical layout points. **A `px` page's canonical bounds are
numerically 1:1 with its px size** (a 1080×1080px page is a 1080×1080pt
artboard; the px size is kept for raster output) — so for px and pt pages the
same numbers go into `size(...)` and into child geometry.

```
b = 9pt   bleed width        (3.175mm ≈ 3mm standard, exactly 0.125in)
m = 9pt   mark margin        (paper-white strip that holds the ticks)
t = 18pt  total pad per side (t = b + m)
g = 3pt   gap between the bleed line and each tick (ink-free safety)
```

```
┌────────────────────────────── sheet = old artboard + 2t per axis ──┐
│  mark margin (m) — masked PAPER WHITE                              │
│  ┌─────────────── bleed line ────────────────┐   the 8 ticks run   │
│  │  bleed strip (b) — edge art EXTENDS here  │   from the sheet    │
│  │                                           │   edge ACROSS both  │
│  │                                           │   zones, over the   │
│  │                                           │   extended art      │
│  │  ┌──────────── trim line ─────────────┐   │                     │
│  │  │  the original design, unchanged,   │   │                     │
│  │  │  shifted by (+t, +t)               │   │                     │
│  │  └────────────────────────────────────┘   │                     │
│  └────────────────────────────────────────────┘                    │
└─────────────────────────────────────────────────────────────────---┘
```

With the original artboard at W×H pt, after the transform:
**trim rect** = `[18, 18, W, H]`, **bleed line** = `[9, 9, W+18, H+18]`,
**sheet** = `(W+36) × (H+36)` pt.

Page `size(...)` growth per axis (2t = 36pt), in the page's own unit:

| Page unit | Add to size() per axis | (t per side in page units) |
|---|---|---|
| `pt` | +36 | 18 |
| `px` | +36 | 18 |
| `mm` | +12.7 | 6.35 |
| `in` | +0.5 | 0.25 |

Child geometry (`p`/`s`) is always pt: every top-level child shifts by +18.

## The procedure — reason element by element, never blanket-scale

### 0. Inventory before touching anything

`inspect` the page. Write down: page unit + size, artboard pt bounds (W×H),
whether the page carries `bg(paint)`, and for EVERY top-level child its id,
kind, `p()`, `s()`, and which trim edges it touches (coordinate 0 or W/H).
Classify:

- **EDGE-TOUCHING** — a fill/band/wash/photo frame that visually meets a trim
  edge. It must be EXTENDED through the bleed on exactly those edges.
- **INTERIOR** — text, logos, QR codes, buttons, anything not meeting an edge.
  It only shifts; it NEVER enters the bleed.
- **FULL-BLEED** — background washes/photos covering the whole page. Extend on
  all four sides (to the bleed line `[9,9,W+18,H+18]`).
- **FILL-SIZED** — any top-level node with `s(fill, …)` or `s(…, fill)`. Pin it
  to its current explicit pt size FIRST, or it will stretch across the new
  sheet including the mark margin.

Page `bg(paint)` needs no conversion: it paints the whole grown sheet, and the
margin mask (step 4) whitens the outer strip. Leave it as-is.

### 1. Grow the page

```text
#page:page_1 size(<w + growth>, <h + growth>, <unit>)
```

### 2. Shift every top-level child by (+18, +18)

One `#<id> p(x+18, y+18)` modify per top-level child. Children of containers
are parent-local — they do NOT move. Rotated nodes shift the same way (p is
the pre-rotation origin).

### 3. Extend edge-touching art through the bleed — per element, with reasoning

For each EDGE-TOUCHING element, per touched side, move that side out by 9pt
past the trim to the bleed line. State the arithmetic as you go, e.g.:

> `top_bar` was `p(0,0) s(1080,14)` — touches top, left, right. After the +18
> shift it sits at `p(18,18)`. Extending left/right to the bleed line: x=9,
> w=1080+18=1098. Extending top: y=9, h=14+9=23. → `#top_bar p(9,9) s(1098,23)`.

Rules per element type:
- **Solid bands / washes**: stretch the rect (position out, size up). Safe.
- **Photos / images in clipped frames**: grow the FRAME to the bleed line;
  cover-fit re-crops the image automatically. Never stretch a bare image
  non-uniformly.
- **Gradients**: extend the geometry; leave stops alone (a 9pt continuation is
  visually invisible; recomputing stops shifts the composition).
- **Patterns/decor that would look wrong extended**: mirror or duplicate a 9pt
  slice rather than leaving paper — cut tolerance must always land on ink.
- **INTERIOR content**: never extend. Also check it still clears the trim by a
  safe inset (≥14pt from the trim line for text/QR/logos); flag to the user if
  the original design already violated this — do not silently move their content.

The extensions stay inside the artboard, so no LUMV0801 overflow fires and no
`bleed(true)` flags are needed. If overflow fires, an extension overshot the
sheet — fix the geometry, don't add flags.

### 4. Append the margin mask, then the marks — a `#page:` continuation

New children on an existing page ride a `#page:<id>` continuation block and
are APPENDED (insert-only, z-top — existing children are untouched). That
z-position is exactly right for both groups, in this order:

- **`print_margin_mask`** — four white rects covering the outer 9pt strips.
  This is what guarantees a paper-white mark margin no matter what the page
  bg or any overshooting art does beneath it.
- **`crop_marks`** — 8 ticks, each drawn as a PAIR: a 3pt-wide white halo
  underlay, then a 1pt pure-black `#000000` core on top (never a brand token —
  this is registration ink for the cutter). Each tick runs from the sheet edge
  INWARD across the margin AND the bleed strip, stopping 3pt short of the trim
  line (length t − g = 15pt), centered on its trim coordinate (18 − 0.5 = 17.5
  for the core, 18 − 1.5 = 16.5 for the halo). The halo is what keeps the mark
  visible ON TOP of art extended through the bleed — a bare black tick vanishes
  on a dark wash or photo. The 3pt stand-off from the trim line keeps mark ink
  off the finished piece under normal cut tolerance. Declared last so nothing
  can cover a tick.

With sheet Wc×Hc = (W+36)×(H+36) and trim `[18,18,W,H]` (halo first, core
second — declaration order is z-order):

```text
#page:page_1
  print_margin_mask gr p(0,0) s(Wc,Hc)
    pm_top    r p(0,0)      s(Wc,9) fill(#ffffff)
    pm_bottom r p(0,Hc-9)   s(Wc,9) fill(#ffffff)
    pm_left   r p(0,0)      s(9,Hc) fill(#ffffff)
    pm_right  r p(Wc-9,0)   s(9,Hc) fill(#ffffff)
  crop_marks gr p(0,0) s(Wc,Hc)
    cmh_top_l    r p(16.5,0)       s(3,15) fill(#ffffff)
    cm_top_l     r p(17.5,0)       s(1,15) fill(#000000)
    cmh_top_r    r p(W+16.5,0)     s(3,15) fill(#ffffff)
    cm_top_r     r p(W+17.5,0)     s(1,15) fill(#000000)
    cmh_bottom_l r p(16.5,Hc-15)   s(3,15) fill(#ffffff)
    cm_bottom_l  r p(17.5,Hc-15)   s(1,15) fill(#000000)
    cmh_bottom_r r p(W+16.5,Hc-15) s(3,15) fill(#ffffff)
    cm_bottom_r  r p(W+17.5,Hc-15) s(1,15) fill(#000000)
    cmh_left_t   r p(0,16.5)       s(15,3) fill(#ffffff)
    cm_left_t    r p(0,17.5)       s(15,1) fill(#000000)
    cmh_left_b   r p(0,H+16.5)     s(15,3) fill(#ffffff)
    cm_left_b    r p(0,H+17.5)     s(15,1) fill(#000000)
    cmh_right_t  r p(Wc-15,16.5)   s(15,3) fill(#ffffff)
    cm_right_t   r p(Wc-15,17.5)   s(15,1) fill(#000000)
    cmh_right_b  r p(Wc-15,H+16.5) s(15,3) fill(#ffffff)
    cm_right_b   r p(Wc-15,H+17.5) s(15,1) fill(#000000)
```

### 5. Verify — the same discipline as any authoring round

- Re-`inspect`: sheet size correct; every former edge-toucher now reaches the
  bleed line `[9,9,W+18,H+18]` on its touched sides; only the mask and ticks
  live in the margin; each tick centered on its trim coordinate, halo under
  core, stopping 3pt short of the trim line; page `bleed` metadata still unset.
- Where a tick crosses extended art (the bleed strip), confirm on the preview
  that the black core reads clearly on the white halo — that overlap is the
  point: the marks must be visible ON the design's extended background.
- `preflight_design` — must stay clean.
- Nothing INTERIOR moved relative to the design (only the uniform +18 shift).

### 6. Report to the user — always include the export guidance

State: trim size (unchanged), bleed 3mm, sheet size, which elements you
extended and how, marks at all four corners. Then the operating instruction:

> Export this page as a **normal export** (or print finish "None (trim only)").
> Do NOT also enable "Bleed + crop marks" / bleed metadata on this page — the
> bleed and marks are already part of the artwork, and the print pipeline
> would wrap a second set around them.

## Worked example — 1080×1080px page → 1116×1116 press sheet

Original: `page_1` 1080×1080px (artboard 1080×1080pt), page `bg(#faf5eb)`,
`top_bar r p(0,0) s(1080,14) fill(#e85d04)` (touches top/left/right),
`headline text … p(120,300)`, `qr … p(600,600) s(140,140)`. This exact block
compiles clean and a plain PDF export ships the finished sheet:

```text
#page:page_1 size(1116,1116,px)
#top_bar p(9,9) s(1098,23)
#headline p(138,318)
#qr p(618,618)
#page:page_1
  print_margin_mask gr p(0,0) s(1116,1116)
    pm_top r p(0,0) s(1116,9) fill(#ffffff)
    pm_bottom r p(0,1107) s(1116,9) fill(#ffffff)
    pm_left r p(0,0) s(9,1116) fill(#ffffff)
    pm_right r p(1107,0) s(9,1116) fill(#ffffff)
  crop_marks gr p(0,0) s(1116,1116)
    cmh_top_l r p(16.5,0) s(3,15) fill(#ffffff)
    cm_top_l r p(17.5,0) s(1,15) fill(#000000)
    cmh_top_r r p(1096.5,0) s(3,15) fill(#ffffff)
    cm_top_r r p(1097.5,0) s(1,15) fill(#000000)
    cmh_bottom_l r p(16.5,1101) s(3,15) fill(#ffffff)
    cm_bottom_l r p(17.5,1101) s(1,15) fill(#000000)
    cmh_bottom_r r p(1096.5,1101) s(3,15) fill(#ffffff)
    cm_bottom_r r p(1097.5,1101) s(1,15) fill(#000000)
    cmh_left_t r p(0,16.5) s(15,3) fill(#ffffff)
    cm_left_t r p(0,17.5) s(15,1) fill(#000000)
    cmh_left_b r p(0,1096.5) s(15,3) fill(#ffffff)
    cm_left_b r p(0,1097.5) s(15,1) fill(#000000)
    cmh_right_t r p(1101,16.5) s(15,3) fill(#ffffff)
    cm_right_t r p(1101,17.5) s(15,1) fill(#000000)
    cmh_right_b r p(1101,1096.5) s(15,3) fill(#ffffff)
    cm_right_b r p(1101,1097.5) s(15,1) fill(#000000)
```

The ticks deliberately CROSS the bleed strip: over the extended `top_bar`
orange, `cm_top_l`/`cm_top_r` read as black-on-white-halo marks sitting on the
art — visible proof on the canvas of exactly where the cut lands.

For a NEW design requested with baked marks: author the design normally at
trim size first (steps 1–6 in your instructions), then apply this transform as a final
pass — never design directly on sheet coordinates.

## Pitfalls

| Trap | Rule |
|---|---|
| Double geometry | Baked page ⇒ page `bleed(...)`/`safe_area(...)` metadata stays UNSET; user exports normally. |
| Planning a z-BOTTOM insertion | Impossible: continuations append at z-top, and a same-parent `parent(..., index:0)` reorder is currently a silent no-op. Never plan one — extend the EXISTING bottom wash in place; the margin mask makes z-order of new nodes irrelevant. |
| Page bg inks the margin | It does — and the `print_margin_mask` whitens it. Never skip the mask. |
| `s(fill,…)` top-level nodes | Pin to explicit sizes BEFORE growing the page. |
| Marks in a brand color | `#000000` core only. |
| Marks under art | Mask group, then marks group, declared LAST. |
| Bare black ticks over dark art | Always the halo pair (3pt white under 1pt black) — a naked tick disappears on a dark wash or photo in the bleed strip. |
| Tick touching/entering the trim area | Ticks stop 3pt short of the trim line (length 15pt from the sheet edge) — mark ink on the finished piece is a print defect. |
| Stretching photos | Grow the clipped frame; cover-fit re-crops. Never distort the image. |
| Un-doing later | Reversal is by hand: delete `print_margin_mask` + `crop_marks`, shrink the page, shift children back, re-trim extended art. Keep the node ids stable (`pm_*`, `cm_*`) so removal is surgical. |
| Digital-only surfaces | Never bake print furniture into a social/ad design the user didn't ask to print. |
