---
name: a4-poster
description: Author an A4 print poster or flyer end-to-end — the 595x842pt page, press-safe color, bleed through our own print machinery, type floors, and the self-audit checklist. Use whenever the brief asks for an a4 poster, a4 flyer, printed poster, print flyer, or a leaflet.
required_decisions: poster_kind, offer_cta, bleed_route, brand_adherence
selection_policy: deterministic
---

# A4 poster & flyer

A printed page has no scroll, no hover, and no second chance. Someone reads it
across a room or holds it for a few seconds, and then it gets cut by a blade
that lands within about a millimetre of where you asked. So this format is
governed by two things a screen format never worries about: what survives the
cut, and what survives the ink. Everything below serves those two.

## Composes with

This skill decides; the craft skills execute. Read beside it:

- `skills/brand-and-tokens` — role tokens, never guessed values.
- `skills/brand-imagery` — the kit-asset / generate / deliberately-none call.
- `skills/clarify-design-brief` — derive before you ask.
- `skills/print-bleed-marks` — **only** on the baked route below. It owns the
  press-sheet transform. Never invent bleed syntax anywhere else.

Pin these knowledge files into the frame payload instead of hunting for them
mid-run: `knowledge/export/print-geometry` (trim, bleed, safe area, and the
rules a print run gates on), `knowledge/design/blocks/patterns` (the validated
A4 one-pager proportions), `knowledge/design/layout-recipes` (the archetype
canon), `knowledge/design/foundations` (squint test, 60-30-10, contrast
floors), `knowledge/design/font-library`, and `knowledge/lumen-dsl/grammar` +
`text`.

## Defaults & required decisions

- Surface: `page poster_a4 preset(a4,portrait)`, which lays out as
  **595 x 842 pt**. A4 is 210 x 297 mm. The engine converts millimetres to
  points at 72/25.4, so the true bounds are 595.28 x 841.89 pt, and the corpus
  writes that as 595 x 842. Author against the point bounds. The physical size
  stays in the page's export metadata.
- `page poster_a4 size(595,842,pt)` gives the identical bounds and is the form
  to use when you are taking the **baked** bleed route, because then the sheet
  growth is one clean arithmetic step in points.
- Margin: `pad(48)` is the validated default, giving a **499pt** content column.
  **36pt is the hard floor** — below that the page stops reading as a printed
  document. Anything above 54pt is a taste choice, not a print requirement.
- The safe area is a 14pt inset. `pad(48)` already clears it by 34pt, so a
  design that respects the margin cannot fail the safe-area rule.
- One poster = one message and one ask. A flyer may add supporting detail. A
  wall poster may not.
- Brand adherence: **strict** = kit tokens/faces/assets only · **balanced** = kit
  defaults + limited complementary accents · **loose** = brand-inspired, kit
  still recognizable.

Before authoring, check the brief against this table. Each row maps 1:1 onto
`ClarificationQuestion`. If a material decision is missing, ask once — a single
batched `request_clarification` round. Otherwise proceed on the defaults and
call `record_gap(area="agent_protocol", …)` for each assumption you apply.
Derive answers before you ask: read the prompt, prior turns, the document, and
the brand card first (`skills/clarify-design-brief`).

| id | question | why_it_matters | options | default |
|---|---|---|---|---|
| `poster_kind` | Wall poster or flyer? | A wall poster is read at distance and carries one message; a flyer is read in the hand and may carry supporting detail. | wall poster · flyer | flyer |
| `offer_cta` | What is the one ask, and what standing detail does it need? | A printed page cannot be clicked, so the ask only works if the date, place, or URL is on the page. | a URL · a date and place · a phone number | the account URL |
| `bleed_route` | Bleed as page metadata, or baked into the artwork? | The two routes are mutually exclusive per page, and combining them produces a double-geometry file no printer can use. | metadata · baked | metadata |
| `brand_adherence` | How tightly must this hold the kit? | It decides whether a non-kit display face is allowed. | strict · balanced · loose | balanced |

## Bleed — pick the route, then use OUR machinery

Never invent bleed syntax. There are exactly two supported routes and they are
mutually exclusive on one page.

**Metadata route (the default).** The design stays trim-sized. Bleed and safe
area ride a `#page:` modify line after the page's children, and the print PDF
profile draws crop marks at export. For a 595 x 842 page the two lines are:

```text
#page:poster_a4 bleed(-8.5,-8.5,612,859) safe_area(14,14,567,814)
```

That is 3mm (8.5pt) of bleed per side and a 5mm (14pt) safe inset, exactly as
`knowledge/export/print-geometry` states them.

Every fill that touches a trim edge is then authored out to the bleed extent,
so a full-width top band becomes `p(-8.5,…) s(612,…)`. Tag it `bleed(true)`.
That flag downgrades the `LUMV0801` overflow error to a declared-intent
warning. Edge art that stops at the trim line is a print failure, not a taste
call: the blade's tolerance exposes white paper slivers.

**Baked route (only when the user asks for marks on the canvas).** Read
`skills/print-bleed-marks` and follow it exactly. In summary, for A4 it grows
the page by 36pt per axis to a **631 x 878** sheet, shifts every top-level child
by (+18, +18) so the trim rect is `[18,18,595,842]`, extends edge art out to the
bleed line `[9,9,613,860]`, then appends a `print_margin_mask` group and a
`crop_marks` group of eight halo-and-core ticks. On this route the page's
`bleed(...)` and `safe_area(...)` metadata stays **UNSET** and the user exports
normally.

## Press-safe color and effects

- **Prefer solid, well-separated colors over subtle gradients.** A gentle tonal
  ramp that looks smooth on a screen bands on press. Two colors that differ only
  slightly in value print as the same color. Keep a real value gap between any
  two areas that must read as different.
- **Never `#000000` for a large dark field.** Use a near-black such as
  `#0a0a0f`. The press profile builds a deep rich black out of it. A pure
  `#000000` fill separates to the K plate alone, so a big panel prints as a
  flat washed grey. Pure `#000000` stays correct for small text, hairline
  rules, and the crop-mark core.
- **No screen-only effects.** A `glow(...)` is a lit-screen move and prints as a
  muddy halo. `shadow(...)` and `blur(...)` cannot be expressed as vector in a
  PDF, so they rasterize at the profile dpi while the rest of the page stays
  vector. That leaves a visible quality seam on the printed sheet. Separate
  regions with a rule, a real border, or a change of surface instead.
- Keep the accent to roughly 10% of the page (60-30-10). Ink coverage that reads
  as bold on screen reads as heavy and wet on paper.

## Layout skeletons (pick one, name it in the direction)

Each is an archetype from `knowledge/design/layout-recipes` — recompose it, never
pour copy into the shell.

1. **Poster hero** — the **vertical-poster** at A4, for a wall poster. Root
   `al(v,x(s),y(s),g($space.stack.loose),pad(48)) s(fill,fill)`: a hug `header`
   `s(499,hug)`, a `main s(499,fill)` that absorbs all the slack, and a hug
   `footer s(499,hug)` pushed to the page bottom. Because a poster's content is
   sparse, give `main` the anchor `y(c)` so the focal block centers and the slack
   splits into symmetric top and bottom margins.
2. **Flyer sell-sheet** — the validated A4 one-pager in
   `knowledge/design/blocks/patterns`. Same header / `main` / footer frame at
   `pad(48)`, but `main` takes `y(s)` because the content nearly fills the page:
   hero, then a **vertical** 3-up benefit list (number chip `s(56,56)` + `g(20)`
   + a `s(423,hug)` text column, summing to 499), then a footer with one CTA
   `s(260,64)` and the contact line. **Never three benefits across on A4** —
   three description columns cannot clear the body-text width floor at 595pt and
   you get a guaranteed `LUMV0810`.
3. **Banded poster** — the **banded** archetype, for a claim that has real
   proof. `g(0)` on the root so the bands touch, a dark claim band, a lighter
   proof band, a footer band. Give exactly ONE band `fill` height and fix the
   others, so the slack lands in one place.

## Type

- Headline: `style($type.headline)` at its role default (56). **Do not step it
  up.** The role's size is tuned for a document-scale page, so on A4 it already
  dominates. The step tokens exist for the 1080-class canvases, not for this
  one. On a wall poster with a ≤3-word headline you may go to
  `font_size($type.size.6xl)` (64), and then re-measure.
- **The headline width trap.** At 499pt a single over-wide word overflows
  `LUMV0810` at any height. "Recover every missed patient call." does not fit.
  "Recover missed patient calls." does. Drop the over-wide word. Never add
  height or raise `max_lines` to paper over it.
- Body: `style($type.body.small)` at `s(499,hug) max_lines(3) lh(1.4)`.
  **`$type.body` overflows a 499pt column** even for a short sentence. Reserve
  it for wide canvases.
- Floors: anything a reader must read holds at `$type.size.md` (16). Legal
  lines, credits, and captions may drop to `$type.size.xs` (12) and no lower.
  Print tolerates smaller type than a screen does, because the page is held or
  walked up to. But 12pt is where legibility ends.
- Kit faces first. A library display face may carry the headline when adherence
  is not strict — **Anton**, **Bebas Neue** (caps only), **Archivo Black**,
  **Bricolage Grotesque** for impact, or **Fraunces** / **Playfair Display** for
  an editorial poster; exact name, listed weights
  (`knowledge/design/font-library`). One display voice plus one workhorse.
  Banned: defaulting to `font("Inter",…)` as a decision, and any family off the
  library list (Arial/Helvetica/Roboto/Open Sans do not resolve).

## Self-audit checklist

Score each test **0–2** into `critique.json` (the `VisualCritique` shape), and
only **after looking at the render** — never from geometry alone. Write it up
like this:

- One `acceptance_notes` line per test: `"<test-name>: <score> — <why>"`.
- Every score below 2 also becomes an `issues[]` entry. Name the test in
  `message`, give a `target` and a `suggested_repair`, and use the category
  shown in parentheses below.
- Any `0` on tests 1–6 means `accepted=false`.

Score with facts and measurements against the named test, never with adjectives.
Write "headline is 4 words at 56pt" or "body copy measures 3.1:1 against the
page", not "looks clean" or "feels balanced". A weak design passes an adjective
and fails a measurement, which is exactly why the measurement is the score.

1. `single-focal-point` — squint: one mass, one landing spot. (`hierarchy`)
2. `arms-length-legibility` — the message reads from across a room, and nothing a reader must read sits below 16pt. (`typography`)
3. `safe-area-clearance` — every text node and the logo sit inside the 14pt safe inset; with `pad(48)` you are 34pt clear. (`clipping`)
4. `edge-art-reaches-the-bleed` — every fill touching a trim edge extends to the bleed line on the chosen route, or the design has no edge art at all. (`overflow`)
5. `press-safe-color` — no large pure-black field, no screen-only effect, and adjacent colors differ by a real value step. (`contrast`)
6. `one-ask-with-its-standing-detail` — exactly one CTA, and the date, place, or URL it needs to be actionable on paper. (`request_satisfaction`)
7. `brand-adherence-followed` — the chosen level actually holds (tokens, faces, assets). (`brand_fit`)

## Override

Explicit user instructions beat every rule above. Record each override with
`record_gap`.
