# Brand capture fidelity — design

**Date:** 2026-10-16. **Status:** approach approved by the founder in chat on 2026-10-16 ("please write a
detailed plan of action and completely solve this issue"), after the five-step order was presented.
**Fixes:** review findings S6-1 to S6-12 (`docs/superpowers/verification/2026-10-14-wave2-area-review-findings.md`
§S6) and walk defect 4 (published pages paint no page background; `_memory/2026-10-15-publishing-live-sites.md`).

## 1. The problem in one paragraph

The brand capture added for Wave 2 (A9, 12–13 October) reads a seller's site by guessing from where
things sit in the page and how CSS is written, instead of reading what the browser actually draws. So it
takes a section's text colour from the first text it finds (an orange eyebrow, a white quote card), drops
every colour written in `oklch()`/`lab()`/`color()` (Tailwind v4, shadcn/ui), calls a fully transparent
button "Filled", copies icon markup without the CSS that sized and coloured it, misses web components and
iframes, keeps one animation of two, re-parses stylesheets once per animation, and matches reveals by a
child-index path that a removed cookie banner shifts. Downstream, site-kit trusts the stored text colour
without checking it reads, and published pages paint no page background at all.

## 2. Principles

1. **Read what the browser draws.** Every colour the capture reports goes through the browser itself
   (a 1×1 canvas), so the format the CSS was written in no longer matters. Measured: Chromium 149 paints
   `oklch(0.546 0.245 262.881)` as `#155DFC`, clips out-of-gamut channels (`oklch(0.7 0.4 30)` → `#FF0000`).
2. **The colour behind an element is computed, not guessed:** every background from the element up to the
   first opaque one, composited; through shadow roots, slots and same-origin iframes; unknown (null) when a
   background image sits in between.
3. **A stored pairing must be readable.** Readability (WCAG 4.5:1) is checked where the kit is minted AND
   where it is drawn. Either check alone fixes what people see; both together mean a bad kit can never
   produce an unreadable page and a new kit never stores a bad pair.
4. **Existing kits are fixed by the draw-side checks without re-capture.** What only a capture can measure
   (band text, icon colours, oklch colours) reaches existing kits only through a re-capture, which runs
   only with the founder's explicit yes and a time estimate.
5. **Every fix starts from a failing test**, built from the review's own probe pages, run in both
   Playwright's and patchright's Chromium where the capture runs in both.

## 3. Decisions

| # | Decision | Why |
|---|---|---|
| D1 | The in-page colour reader is a canvas round trip (`fillStyle` → `fillRect` → `getImageData`), returning `#RRGGBB` or `#RRGGBBAA`. | It is exactly how the page paints, for every CSS colour syntax, now and future. Verified against Chromium 149 for oklch, oklab, lab, lch, hwb, color(srgb), color(display-p3), named colours. |
| D2 | The Python colour parser also learns oklch/oklab/lab/lch/hwb/color(srgb, srgb-linear, display-p3), clipping like the browser. | Stylesheet-declared colours (custom properties, declared roles, gradient stops, shadows) are parsed from CSS text, not from the canvas. Prototype conversions match Chromium's pixels exactly (§D1 list). |
| D3 | Section text colour = the colour covering the most text area (characters × font size) among text whose computed backdrop equals the section's own backdrop. | Headings and body outweigh a small eyebrow; text in a card with its own background is not on the band. Reproduces the review's two cases correctly (#333333 on cream, #FFFFFF on navy). |
| D4 | At mint, a band text colour below 4.5:1 is replaced by the better of `text.primary`/`text.inverse`, else black/white; diagnostic **LUMI0609** names the measured colour and the ratio. | The pairing is a promise to every site built from the kit. |
| D5 | site-kit's `inkRole` uses a kit pair only when it reads (≥ 4.5:1 when both are hex); otherwise the readable choice. | Fixes every existing kit at once; the Brand page, brand.md, `isDarkSurface` and band labels all read `inkRole`. |
| D6 | Published and live pages paint the brand page colour: `.brand-root` gets `background-color`/`color` from the page surface, and the document `<head>` gets `html{background-color;color;color-scheme}` with literal values. | `.brand-root` covers gaps between sections in the editor and on the page; the `html` rule covers overscroll and short pages, and `color-scheme` stops a dark-mode browser painting its own dark canvas and form controls. |
| D7 | Icon markup carries its computed paint: `fill`/`stroke`/`stroke-width`/caps/joins/fill-rule/opacities written as attributes where they differ from the parent; a paint equal to the icon's text colour is written `currentColor`. | CSS-class paint survives the cleaner; `currentColor` keeps the icon following the label's colour per state and surface. |
| D8 | A sprite `<use>` becomes a `<g transform="translate(tx ty) scale(sx sy)">` computed from the use box and the symbol's `viewBox`/`preserveAspectRatio`. | Draws the symbol at the size the page drew it, with only elements and attributes every checker already accepts. |
| D9 | Enumeration walks open shadow roots and same-origin iframes; the state pass finds a probe in any frame (`frame.query_selector` pierces shadow DOM); forced states resolve the CDP node from a JS reference (`DOM.requestNode`). | Web-component and iframe CTAs get measured, with their states. |
| D10 | Animations: each entry of a computed comma list is its own animation; quoted names are unquoted; each stylesheet is parsed once per capture. | S6-9, S6-11. |
| D11 | Reveals are re-found by a reference held in the page, not a child-index path. | A removed overlay can no longer shift what "after" reads. |
| D12 | Minting: a value used in several places of ONE style is named after what those places share (`…hover-pressed.fill`, `…padding`); the source address drops query and fragment; animation iteration counts are checked with the engine's own number grammar. | S6-4, S6-5, S6-12. |
| D13 | No engine (`crates/`) change. | Every icon element and attribute used (nested `g`, `transform`) is already accepted by `icon_svg_ok`, the cleaner and site-kit's `isSafeIconSvg`. |

## 4. Out of scope

- Re-capturing any real brand (Garner, Conduit, Clue) — a founder-gated step after the code lands.
- Cross-origin iframes (unreadable by design) and closed shadow roots.
- Gamut mapping beyond what the browser itself does (it clips; so do we).
