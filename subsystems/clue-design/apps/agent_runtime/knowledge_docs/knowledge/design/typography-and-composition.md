# Typography And Composition

Status: supported now, recognized but not lowered, and future scaffold.

## Supported Now

Current Lumen text support can produce useful previews when the agent stays
conservative:

- Use short headlines.
- Keep headline boxes wide enough for expected copy.
- Prefer `style($type.headline)` and `style($type.body)` when a Brand Kit is
  available.
- For a voice the kit does not cover — or any no-kit run — choose a family
  from the curated font library (see `design/font-library.md`) with
  `font("Family",size,weight,align)`; do not default everything to Inter.
- Use `hug` height for text likely to wrap, or make fixed-height boxes large
  enough for measured line height. When a text box has a **fixed/fill height**
  (a banded or split-panel layout), use `valign(center|bottom)` to place the copy
  vertically inside it; on hug height `valign` is a no-op (use auto-layout `y(c)`
  to center children in a container instead) — see `lumen-dsl/text.md`.
- Use `wrap_text(true)` on body copy and long headlines.
- Use `max_lines(...)` on ad headlines and compact cards so overflow is
  diagnosed early.
- Use `lh(...)` for hierarchy: tighter headlines such as `lh(1.05)` to
  `lh(1.15)`, relaxed body copy such as `lh(1.3)` to `lh(1.45)`.
- Use `ls(...)` sparingly; positive values can widen labels and increase
  overflow risk.
- Use `dir(rtl)` only when the content is truly right-to-left. Phase B records
  direction, but full bidi shaping remains future work.
- Keep body text at readable sizes.
- Avoid placing text partially outside parent frames.
- Use high contrast and simple hierarchy.

### Typography v1 — case, decoration, ellipsis, spacing (taste first)

These are now fully supported (compile → measure → render). Each is a scalpel, not
a default — reach for it only when it earns the composition:

- **Uppercase + wide tracking = an eyebrow/kicker, never body.** `case(upper)
  tracking(180)` on a short label (`"field report"`, `"case study"`) reads as a
  crisp section marker. Author the content in natural case and let `case(upper)`
  do the work — the stored words stay editable. **Never all-caps a sentence or
  paragraph**: caps destroy word-shape and slow reading. One tracked eyebrow per
  design.
- **Underline is one deliberate accent, not link styling.** Use `underline(true)`
  on a *single* element — the classic is a text CTA ("Read the case study"). Never
  underline headlines or body, never as blue-link decoration, and never more than
  once per design. If everything is underlined, nothing is emphasized.
- **Strike is for a semantic before/after** — a slashed old price next to the new
  one (`strike(true)` on `"$1,200"` beside `"$690"`), a struck "sold out". Never
  decorative; a strike always says "this was replaced/withdrawn".
- **The two-color headline is THE span move — one accented phrase per headline.**
  Mark the phrase with `[[…]]` and give it a `span(...)`:
  `headline text "Every [[outage]], mapped before it spreads." … span(fill(#e11d48), weight(800))`
  colors and bolds one phrase against the node's ink — the editorial two-color headline.
  Pull the accent from **the kit palette** (`span(fill($accent.primary), weight(800))`)
  when branded, a raw hex otherwise. Rules of restraint: **exactly one accent
  phrase per headline** (two accents = no accent); **never rainbow-span** a line
  into many colors; **never span body copy** — spans are a headline/display move,
  not a way to highlight sentences. A **weight-only** span (`span(weight(800))`,
  no color) bolds a single keyword when a color accent would be too loud. Underline
  and strike spans follow the same single-accent discipline as their whole-node
  forms above (one deliberate underline; a strike only for before/after). Spans are
  headline-only for a reason: at body size the color shifts read as noise, not
  emphasis.
- **Truncation is layout honesty, not content editing.** `truncate(true)` (with
  `max_lines(n)` or `wrap(false)`) ends the cut line with `…` for variable-length
  or slot copy whose worst case you can't fully control. It does **not** silence
  overflow — when copy is actually cut, layout still reports `LUMV0904`/`LUMV0903`.
  Prefer **rewriting the copy to fit**; truncate is the graceful fallback, not a
  way to cram. With no cut point it is inert and warns `LUMV0905`.
- **Paragraph spacing vs line-height — keep them distinct.** `lh(...)` sets rhythm
  *within* a paragraph (tight headlines `1.05`–`1.15`, relaxed body `1.3`–`1.45`);
  `para_spacing(n)` adds air *between* stanzas split on `\n`. A multi-stanza body
  is `lh(1.35) para_spacing(16)`. Do **not** fake stanza breaks with empty lines,
  and do not inflate `lh` to stand in for paragraph gaps.
- **Text strokes render as display-type outline.** A single solid `stroke(...)` on
  a big display numeral/word (stroke behind fill) is an outline-type move for
  posters — first solid stroke only. Keep it to hero display type; outlined body
  copy is unreadable.
- **Italic is an editorial voice move, not a default.** `italic(true)` earns its
  place on a **serif pull-quote** (Fraunces/Lora/Newsreader/Source Serif 4), on a
  **caption or attribution**, or as **emphasis on a phrase inside body/subhead copy**
  via a span (`span(italic(true))` on one `[[…]]` run). Sans italics are for *inline
  emphasis only* — a leaning sans headline reads as a slide-deck accident. **Display
  faces have no italic by design** — don't reach for it there and don't fake a slant;
  ask for italic where there is no face and it renders upright + `LUMS0105`. And keep
  **one emphasis system per canvas**: pair italic with the two-color span move only
  sparingly — an italic phrase *or* an accent-color phrase, rarely both on the same
  line.

Good text box patterns:

```text
headline text "Let neurosurgeons focus on surgery." p(64,88) s(620,hug) style($type.headline) lh(1.08) wrap_text(true) max_lines(2)
body text "Insight Health handles calls, scheduling, and patient routing." p(64,240) s(600,hug) style($type.body) lh(1.35) wrap_text(true) max_lines(3)
cta_text text "Book a Demo" p(0,0) s(fill,hug) style($type.cta) max_lines(1)
```

Bad patterns:

```text
headline text "Very long headline..." p(40,40) s(300,24) font("Inter",64,800,left)
body text "Long paragraph..." p(40,120) s(300,24) font("Inter",18,400,left)
```

Those compile, but Phase B layout should flag overflow and the visual critic
should request a layout repair.

For Phase A visual quality, a reviewer should reject:

- clipped text
- text that crosses frame boundaries
- long lines that run off the page
- tiny unreadable supporting copy
- decorative type that reduces clarity

## Supported But Heuristic

Phase B supports line height, letter spacing, wrap, max lines, and text
direction in the scene contract and DSL. Measurement is deterministic and
shared by layout/export/diagnostics, but it is still heuristic. Do not treat it
as final browser/PDF font shaping.

## Future Scaffold

Future typography work should add:

- non-Latin and RTL shaping
- rich text spans
- print/PDF font embedding and subsetting
