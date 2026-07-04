# Lumen DSL Vetted Block Catalog

A library of pre-proportioned, pre-spaced, **validator-passed** blocks to
**ASSEMBLE** designs from — instead of inventing proportions from primitives every
run (which overcrowds layouts and fails preflight on `LUMV0810`/`0903`/`0904`).
Every fenced `text` example in this folder is a self-contained doc (`page` +
one clipped root `artboard` + the block + `#slot:` fixture lines) that personally
returned `{"ok": true}` from `.context/p02-validate.py`. The only warnings are
`LUMB0613`/`LUMB0614` (platform font not embeddable/subsettable) — environmental,
never failing — plus a non-fatal `LUMV0801` bounds *warning* on the dense A4
one-pager. Use these as the ground truth for correct Lumen DSL syntax + token use.

## Files

| File | Scope |
|------|-------|
| [`patterns.md`](patterns.md) | **Full-artifact compositions** — assemble one of these first, per surface. |
| [`layout.md`](layout.md) | Structural shell blocks — hero, header, footer, divider, section band. |
| [`actions.md`](actions.md) | Buttons, button rows, eyebrows/badges (the calls to action). |
| [`data-display.md`](data-display.md) | Information surfaces — card, stat tile, benefit row/item, logo lockup. |

## Block index

### `patterns.md` — full-artifact compositions (start here)
| Block | Use it for |
|-------|-----------|
| Social square ad (1080×1080) | A square social/display ad: one focal message + 3 proof stats + one CTA. |
| Full-canvas poster (1080×1080) | A LIGHT-content big-canvas ad: one focal message + CTA, no stats, distributed. |
| Image hero (1080×1350) | A **photo-led** editorial hero/poster: full-bleed image + scrim + headline (text-over-image, scrimmed). |
| A4 one-pager (A4 portrait) | A printed/PDF sell-sheet: header + hero + **vertical** 3-up benefits + CTA footer. |
| Landscape flyer (1200×628) | A wide banner/email hero: left message + CTA, right proof-stat panel. |
| Postcard (6×4 in) | The smallest surface: brand + recipient, one headline, one line, one CTA. |

### `layout.md` — structural shell
| Block | Use it for |
|-------|-----------|
| Hero | The single focal message of a social square — eyebrow + headline + subtitle + CTA. |
| Header | Top band of a one-pager: brand lockup left, contact/nav right (`x(sb)`). |
| Footer | Closing band: tinted card with contact + CTA, a rule, and a legal line. |
| Divider | A horizontal rule (a `rect`, since there is no `divider` node); plain or labeled. |
| Section band | A full-bleed tinted band wrapping one focal idea (eyebrow + header + body). |

### `actions.md` — actions
| Block | Use it for |
|-------|-----------|
| Primary CTA button | The single solid, high-contrast primary action of a section. |
| Secondary / outline button | A subordinate action — transparent fill + border, visibly lower priority. |
| Button row | A primary + a fallback action side by side (filled stays dominant). |
| Eyebrow / badge — Variant A (overline) | Default anti-cliche overline above a headline. |
| Eyebrow / badge — Variant B (rule + label) | A short accent rule before the overline label. |
| Eyebrow / badge — Variant C (tinted pill) | Only for genuine status badges ("NOW IN BETA"). |

### `data-display.md` — information surfaces
| Block | Use it for |
|-------|-----------|
| Card | One self-contained idea on a `$surface.card` — title + short paragraph. |
| Stat tile | One spotlight metric — big numeral + short label. Use 1–3, stop at three. |
| Benefit row (3-up) | Three peer benefits **across a wide surface** (1080+); terse descriptions only. |
| Benefit item | One full-width chip + title + description; **stack these** for benefits on A4. |
| Logo lockup | A hero-scale brand identity row — mark + wordmark (`$type.title`). |

## How to compose

1. **Pick a full pattern** from `patterns.md` that matches the requested surface
   (square / A4 / landscape / postcard). It is already correctly proportioned and
   spaced for that surface and has passed the validator.
2. **Swap copy through the `#slot:` lines only.** Edit each slot's `sample(...)` /
   `worst_case(...)`; keep the slotted node's fixed `s(W,H)` unless the worst_case
   grows — if it does, re-validate. Fixtures attach **only** via a
   `#slot:<key> sample("…") worst_case("…")` line indented one level under the
   `page` (never as node properties, never under the artboard).
3. **Swap in component blocks** from `layout.md` / `actions.md` / `data-display.md`
   when you need a region the pattern doesn't have (e.g. drop in a Card, replace a
   solid CTA with a Button row). Keep each component's calibrated `s(W,H)` and the
   shared token choices below so regions line up and stay inside the box.
4. **Respect the content budget** (next section). If content exceeds it, **drop
   content or stack vertically — do not shrink type or cram more in.** Smaller
   surfaces (postcard, flyer) carry *less* content, not the same content smaller.
5. **Re-validate after any structural change** with
   `.context/p02-validate.py`. Ship only what returns `ok==true`.

### Shared token choices (use the same token for the same role)
- Page/one-pager background `$surface.page`; bold hero `$surface.brand`; soft
  tint/chip `$surface.brand.subtle`; card `$surface.card`; quiet band `$surface.muted`.
- **Centering a label (CTA, numeral, monogram, badge):** put it in a container that
  centers on both axes (`al(h, x(c), y(c), ...)`) AND give the LABEL
  `align(center)` + a hug height: `... text "…" s(fill,hug) style($type.x) align(center)`.
  `align(center)` centers the glyph horizontally (the box need NOT hug the glyph);
  the hug height + the container's `y(c)` center it vertically. Do NOT use a hug
  WIDTH (`s(hug,…)`) — it trips a `LUMV0902` re-measure false-overflow.
- CTA button: `fill($surface.inverse)` + `rd($radius.button)`, a fixed-size
  `al(h, x(c), y(c), pad(...))` pill with an `s(fill,hug) align(center)` label.
- Number/initial chip: `$surface.brand.subtle` + `rd($radius.full)` on a fixed-size
  `al(x(c), y(c))` circle, with an `s(fill,hug) align(center)` glyph.
- Brand name in a header/footer band → `$type.label`; standalone hero identity →
  `$type.title` (Logo lockup). Eyebrow → `$type.eyebrow` `max_lines(1)`. Hero/section
  header (5–6 words) → `$type.headline` (not `$type.title`, which won't wrap).
- **Step the hero size to the surface.** `$type.headline` defaults to 56 (right for A4).
  On a large canvas keep the role but override the size with a step token so the headline
  dominates: `style($type.headline) font_size($type.size.6xl)` (64) on a landscape flyer,
  `font_size($type.size.7xl)` (80) on a 1080² square. Steps run `$type.size.xs`(12) →
  `9xl`(128); the role still supplies weight/color, and the size is a fixed value (no
  auto-scaling, so a human editor can resize freely). One element dominates per artifact;
  the hero must read visibly larger than any `$type.stat` (48) value.
- Body copy at print/narrow widths (≤~620pt) → `$type.body.small`; reserve
  `$type.body` for the wide square hero column.
- Divider rule = a `rect` `r s(fill,2) fill($border.subtle)` (numeric thickness —
  `$stroke.width.divider` is illegal inside `s(...)`).
- Personalized account/advertiser values live in the `account.*` slot namespace
  (`account.name`, `account.contact`, …); campaign/offer copy in `campaign.*` /
  `offer.*`; indexed peers in `benefit.N.*` / `stat.N.*`.
- Spacing rhythm: `g($space.section)` between major regions, `g($space.stack.loose)`
  between list rows, `g($space.stack.default)` between peers (headline→subtitle→CTA),
  `g($space.stack.tight)` for label→value (eyebrow→title, value→caption). Outer
  margin `pad(96)` (1080 square) / `pad(48)` (A4) / per-surface for flyer/postcard.

## Composition discipline (the whole point of the catalog)

- **One dominant focal region per artifact**; secondary regions are visibly
  subordinate (smaller type, lighter color, no competing CTA).
- **Aim for ~60–70% whitespace** with generous outer padding. Uncrowded reads as
  intentional and on-brand; dense reads as AI-generated and fails preflight.
- **One CTA per section/artifact.** A second action, if any, is an outline button.
- **Content budget (keeps it uncrowded AND keeps worst_case fixtures in the box):**
  eyebrow 2–4 words `max_lines(1)`; headline 4–8 words `max_lines(2)`; subtitle/lead
  6–12 words `max_lines(2–3)`; body 12–25 words `max_lines(3)`; benefit title ≤4
  words (≤2 ideal) `max_lines(1)`; benefit description ≤12 words `max_lines(2–3)`;
  CTA label 2–3 words `max_lines(1)`; stat = one numeral + ≤2-word label.
- **Never overcrowd.** Never more than 3 benefits in a row, and **on a portrait
  page never 3 *across*** — three description columns can't clear the body-text
  width floor at 595pt and you get guaranteed `LUMV0810`. Stack benefits vertically
  (full-width Benefit item rows) or use a 2-up. Prefer information on surfaces over
  boxing everything in cards. Build hierarchy with size + weight + color, not by
  cramming more elements in.
