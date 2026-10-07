# Puck spike, phase 1: findings (2026-10-07)

Plan: `docs/superpowers/plans/2026-10-07-puck-spike-phase1.md`. Branch `spike/puck-phase1`.
Built and driven by hand (Claude, Opus); no model spend. Everything below was checked in a real
browser (Playwright, plus the in-app browser), on the dev server and on a production build.

## Verdict

**Go for phase 2.** Puck holds our clones, a coherent brand-token system and multipage sites
for two very different brands, with instant human editing and clean server-rendered publishing.
Every gate and test passed after fixes. None of the fixes needed a Puck change; all were in our
own wiring. Brand coherence is the founder's call. Screenshots are in `shots/`, and the editor is at
`http://localhost:3047/edit/garner-syracuse` and `/edit/conduit-atrium`.

## Gates

| Gate | Result | Evidence |
|---|---|---|
| G1 Puck in our stack (Next 16.2, React 19.2, Tailwind v4) | Pass | Utilities, arbitrary values, responsive variants and `@theme` tokens apply inside the editor iframe and on published pages (computed-style checks). The Tailwind-in-iframe issues reported upstream (#1026, #1515) did not reproduce. |
| G2 Clones render as captured | Pass | Garner and Conduit clones from stored HTML and scoped CSS. Fonts and media load, and the hero video plays. Side by side with today's engine (`shots/garner-v0-vs-engine.png`) they match. No CSS leaks in either direction (probe identical alone and between clones; clone headings identical with and without the probe). |
| G3 Brand kit becomes a theme | Pass | `export/check_tokens.py`: computed font family, size, weight, line height, letter spacing, brand surface colour, text colours and button radius equal each kit's values, published and in the editor at 1440, for both brands. |

## Tests

| Test | Result |
|---|---|
| T5 `ClonedSection` | Pass. Slot fields generated per clone; slots pre-filled with the clone's own wording; unchanged slots keep the captured markup exactly; text replacement for baked labels (C1's case) and link replacement for unslotted links; fragment picker; inline editing of clone text on the canvas. |
| T6 Own sections | Pass. StatsBand, FeatureSplit, ProofCard and CtaBand, using tokens only (surface, heading role, measured brand button), plus a brand-asset picker (kit assets plus the seller's captured photos). The same code renders on brand for Garner and Conduit. |
| T7 Shell and multipage | Pass. One header ("Prepared for" beside the logo, which fixes today's shell bug) and one footer per site, edited once in `/edit/<site>/_shell`. One edit reached both routes. Internal links (`/analysis`) resolve under the site's address. |
| T8 Pages built by hand | Pass. Garner / Syracuse (`/`, `/analysis`) and Conduit / Atrium (`/`, `/stories`), each mixing clones and our own sections. |
| T9 Human editing | Pass (`export/check_editing.py`, `check_shell_and_layout.py`). Inline edit in our section, inline edit in a clone, variant change, undo, image swap, reorder by drag, publish and reload. Keyboard reordering does not move sections; mouse drag does. |
| T10 Publishing | Pass after one fix. Published pages render on the server with no editor code; all four routes are clean at 1440 and 375 (no errors, broken images, font errors or horizontal overflow). |

## Bugs found and fixed (all in our wiring)

1. **Editor loading reset a clone's custom slots** to its defaults. Puck runs `resolveData` on
   load with every prop marked changed, so pre-fill now compares with the previous data.
2. **Inline clone edits were lost on undo.** The `setData` dispatch now records history.
3. **Clone text could not be clicked in the editor.** Puck disables pointer events inside
   components and re-enables them for `data-puck-overlay-portal`; editable slots now opt in.
4. **Published pages bundled the editor** (1.1 MB of JavaScript). Editor-only components are now
   injected by the editor route, so the published route has no client imports (503 KB, React
   runtime only).
5. **The brand button beat Tailwind utilities.** Theme component rules moved into
   `@layer components`.
6. **The "dark surface" rule was hard-coded** (wrong for Conduit's light cyan brand surface). It is
   now decided per brand from the surface colour's luminance.

## What the kit cannot express, and how it was filled

The kits record some brand facts as "unmapped". Two mattered:
- **Primary button.** Conduit's is "warm-dark with no kit token".
- **Heading ink.** Garner's headings are "forest ink, not `text.primary`".

`export/measure_brand.py` measures both from the brand's own rendered clones, and the theme
uses the measurements. Without this, our sections were visibly off-brand (black headings next to
Garner's forest ones). **Brand ingestion should own this step**: measure from clones whatever the
kit leaves unmapped.

Contrast also comes from the kit: the theme uses each kit's `contrast_pairs` for text on each
surface (dark ink on Conduit's cyan, white on Garner's green).

## Numbers

| | Garner / Syracuse `/` | Conduit / Atrium `/` |
|---|---|---|
| Sections | 5 (4 clones, 1 own) | 5 (3 clones, 2 own) |
| HTML | 0.89 MB | 1.25 MB |
| JavaScript | 0.50 MB | 0.50 MB |
| Fonts / images / media | 77 KB / 411 KB / 4.2 MB (hero video) | 201 KB / 490 KB / none |

**Page weight is the main production issue.** Each clone repeats most of its site's stylesheet
(90–220 KB per clone), so HTML reaches about 1 MB. A publish step should de-duplicate clone CSS.
The 0.5 MB of JavaScript is Next's React runtime; static-HTML publishing would remove most of it.
Garner's export also carries 88 font faces, most unused; publishing should keep only the faces the
page uses.

## What building by hand took (the job description for phase 2)

For each page, building it by hand meant:
1. Choosing the clones, in an order that tells the story.
2. Filling 15–30 slot values from the copy.
3. Adding text and link replacements for baked labels and audience links.
4. Choosing one or two of our own sections and their surface, heading role and image.
5. Checking the render at 1440 and 375.

Judgment calls that went wrong and were caught only by looking at renders:
- A duplicate photo across two sections.
- A picked image that was a background layer, not the product: captured images carry no
  description.
- Two copy claims that went beyond their source:
  - "0 plan design changes" became a new metric (metric mutation);
  - "take to the board" over-read "presentation-ready".

So phase 2 needs a cheap "look" step, and image metadata for captured photos.

## Puck limits met

- **Pre-1.0 APIs:**
  - select options aren't stored as the given values;
  - field panels render twice (one hidden);
  - `resolveData` has load-time semantics;
  - the editor logs a harmless `NaN` height warning.
- **No validation and no image upload.** Covered by our own contracts and the asset picker.
- **No site concept.** Multipage, the shared shell and link resolution are about 80 lines of ours
  (`lib/store.ts`, shell route).
- **Keyboard reordering didn't work in testing;** mouse drag does.

## Not covered by phase 1

- **Any agent work.** That's phase 2.
- **Account logos.** Syracuse's site doesn't resolve and Atrium has none on file.
- **Rich-text fields.**
- **Fluid type below 1440 is generated, not measured.** Kits only hold desktop sizes.
- **Atrium copy is seller-led on purpose.** Atrium has almost no research (headcount only), so
  nothing on the page claims anything about Atrium beyond its name.
- **Live publishing** to the page origin or custom domains.

## Files

- `export/`:
  - `export_brand.py`: kit, fonts, assets and clones from the lane DB;
  - `measure_brand.py`: kit gaps measured from clones;
  - `check_tokens.py` (G3), `check_editing.py` and `check_shell_and_layout.py` (T7, T9),
    `shoot.py` (screenshots and runtime checks).
- `lib/`:
  - `clone.ts`: slot filling, a copy of the engine's rules;
  - `theme.ts`: kit to theme;
  - `brands.ts`, `store.ts`.
- `puck/`:
  - `config.tsx`;
  - `sections.tsx` (our own sections);
  - `shell.tsx`;
  - `clone-editor.tsx`, `asset-picker.tsx` (editor-only).
- `data/sites/`:
  - `garner-syracuse.json`, `conduit-atrium.json`: the pages;
  - `garner-v0`, `conduit-v0`, `leak-*`, `tokens-*`: test fixtures.
