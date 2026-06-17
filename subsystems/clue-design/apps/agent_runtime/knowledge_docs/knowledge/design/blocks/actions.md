# Lumen DSL Vetted Blocks — Actions (buttons, button rows, eyebrows/badges)

Pre-proportioned, pre-spaced action blocks. ASSEMBLE these — do not re-invent
proportions from primitives. Every fenced `text` example below was personally run
through `.context/p02-validate.py` and returned `{"ok": true}` (only the
environmental `LUMB0613`/`LUMB0614` font warnings remain — those never fail a
block).

Shared rules these blocks encode (so the agent stops overcrowding and stops
failing `LUMV0902/0903/0904`):

- A button is a **fixed-width `al(h, x(c), y(c), pad(...))`** with a single label
  child sized `s(fill,hug) align(center)`. The container's `al(x(c),y(c))` centers
  the label BOX; `align(center)` (alias `text_align(center)`) centers the GLYPH
  inside that box (text-anchor=middle) so the label sits dead-center even when the
  box is wider than the text. Centered labels use `align(center)` + hug height;
  text heights hug. Keep `style($type.x)` as-is — `align()` is a standalone text
  property that sets horizontal alignment independently of the type role.
- A slotted label takes a **definite width from its fixed-width button** plus a
  **hug height** (`s(fill,hug)` inside a fixed button: the button supplies the
  definite width, `text_fit` hugs the glyph-tall height off the node's own line
  height). Do NOT give a slotted label a hug WIDTH (that trips `LUMV0902`).
- One primary action per section; a secondary action is visibly subordinate
  (outline, not filled). Generous outer padding (`pad(96)` square / `pad(48)`+ A4)
  keeps ~60-70% whitespace.

---

## Primary CTA button

**When to use:** the single primary action of a section/artifact — solid, high
contrast, centered label. Exactly one per section.

**When to use / Content budget:** CTA label 2-3 words, `max_lines(1)`. Solid
`fill($surface.inverse)` (dark button on a light/brand surface), `rd($radius.button)`.
Button is a fixed `s(340,76)` `al(h, x(c), y(c), pad(20,40))`; the label is
`s(fill,hug) align(center)` (fill the button's width, hug the glyph-tall height,
center the glyph) at `style($type.cta)`. Centered labels use `align(center)` + hug
height; text heights hug — the button's `y(c)` vertically centers the hugged box,
and `align(center)` horizontally centers the glyph inside the fill-width box.

```text
page primary_cta_demo size(1080,1080,px)
  artboard al(v, x(s), y(c), g($space.stack.loose), pad(96)) p(0,0) s(fill,fill) fill($surface.page) clip(true)
    content al(v, x(s), g($space.stack.default), pad(0)) p(0,0) s(888,hug)
      headline text "Ready when you are." p(0,0) s(888,hug) style($type.headline) lh(1.08) wrap_text(true) max_lines(2) slot(campaign.headline)
      cta al(h, x(c), y(c), pad(20,40)) p(0,0) s(340,76) fill($surface.inverse) rd($radius.button)
        cta_text text "Book a Demo" p(0,0) s(fill,hug) align(center) style($type.cta) max_lines(1) slot(campaign.cta)
  #slot:campaign.headline sample("Ready when you are.") worst_case("Ready when you are.")
  #slot:campaign.cta sample("Book a Demo") worst_case("Start Free Trial")
```

Validator proof:
```json
{ "ok": true, "stage": "preflight", "errors": [], "warnings": ["LUMB0613", "LUMB0614"] }
```

---

## Secondary / outline button

**When to use:** a subordinate action that should not compete with the primary CTA
— a transparent fill with a border, so it reads as visibly lower priority.

**When to use / Content budget:** label 2-3 words, `max_lines(1)`. Transparent fill
via `fill(#00000000)` (fully transparent — there is no `$transparent` token), a
border via `stroke($border.strong, $stroke.width.firm)`, and `rd($radius.button)`.
Stroke-width tokens (`$stroke.width.*`) are valid ONLY inside `stroke(...)`; putting
one inside `s(...)` raises `LUMB0301`. Same fixed `s(340,76)` button geometry and
`s(fill,hug) align(center)` label as the primary, so a primary and a secondary line
up pixel-for-pixel.

```text
page secondary_cta_demo size(1080,1080,px)
  artboard al(v, x(s), y(c), g($space.stack.loose), pad(96)) p(0,0) s(fill,fill) fill($surface.page) clip(true)
    content al(v, x(s), g($space.stack.default), pad(0)) p(0,0) s(888,hug)
      headline text "See it in action first." p(0,0) s(888,hug) style($type.headline) lh(1.08) wrap_text(true) max_lines(2) slot(campaign.headline)
      cta al(h, x(c), y(c), pad(20,40)) p(0,0) s(340,76) fill(#00000000) stroke($border.strong, $stroke.width.firm) rd($radius.button)
        cta_text text "Watch the Tour" p(0,0) s(fill,hug) align(center) style($type.cta) max_lines(1) slot(campaign.cta)
  #slot:campaign.headline sample("See it in action first.") worst_case("See it in action first.")
  #slot:campaign.cta sample("Watch the Tour") worst_case("Watch the Tour")
```

Validator proof:
```json
{ "ok": true, "stage": "preflight", "errors": [], "warnings": ["LUMB0613", "LUMB0614"] }
```

---

## Button row (primary + secondary side by side)

**When to use:** a decision point that offers a primary AND a fallback action
(e.g. "Start Free" / "Talk to Sales"). The filled button stays dominant; the
outline button subordinate.

**When to use / Content budget:** each label 2-3 words, `max_lines(1)`. The row is
`al(h, x(s), y(c), g($space.md))` with a fixed width (`888`). Both buttons are
fixed `s(320,76)` so they add up inside the row (320 + 320 + `$space.md` gap < 888)
— give the row a definite width whenever its children are fixed-width, so the math
is checkable. Primary = solid `fill($surface.inverse)`; secondary = transparent
`fill(#00000000)` + `stroke($border.strong, $stroke.width.firm)`. NEVER make both
filled — equal emphasis defeats the hierarchy.

```text
page button_row_demo size(1080,1080,px)
  artboard al(v, x(s), y(c), g($space.stack.loose), pad(96)) p(0,0) s(fill,fill) fill($surface.page) clip(true)
    content al(v, x(s), g($space.stack.default), pad(0)) p(0,0) s(888,hug)
      headline text "Start free or talk to sales." p(0,0) s(888,hug) style($type.headline) lh(1.08) wrap_text(true) max_lines(2) slot(campaign.headline)
      actions al(h, x(s), y(c), g($space.md), pad(0)) p(0,0) s(888,hug)
        primary al(h, x(c), y(c), pad(20,40)) p(0,0) s(320,76) fill($surface.inverse) rd($radius.button)
          primary_text text "Start Free" p(0,0) s(fill,hug) align(center) style($type.cta) max_lines(1) slot(campaign.cta_primary)
        secondary al(h, x(c), y(c), pad(20,40)) p(0,0) s(320,76) fill(#00000000) stroke($border.strong, $stroke.width.firm) rd($radius.button)
          secondary_text text "Talk to Sales" p(0,0) s(fill,hug) align(center) style($type.cta) max_lines(1) slot(campaign.cta_secondary)
  #slot:campaign.headline sample("Start free or talk to sales.") worst_case("Start free or talk to sales.")
  #slot:campaign.cta_primary sample("Start Free") worst_case("Start Free")
  #slot:campaign.cta_secondary sample("Talk to Sales") worst_case("Talk to Sales")
```

Validator proof:
```json
{ "ok": true, "stage": "preflight", "errors": [], "warnings": ["LUMB0613", "LUMB0614"] }
```

---

## Eyebrow / badge pill (three variants — prefer the non-pill ones)

**When to use:** a small overline above a headline that names the audience, theme,
or status. The tinted pill is an AI cliche — **prefer variant A (plain overline)
or B (rule + label)**; reach for variant C (tinted pill) only when the content is a
genuine status badge ("NOW IN BETA", "NEW").

**When to use / Content budget (all variants):** 2-4 words, ONE short line,
`max_lines(1)`, `style($type.eyebrow)` (small-caps overline). Pair it with the
headline using `g($space.stack.tight)` so the eyebrow reads as attached to the
title. A slotted eyebrow takes a definite width and a hug height (`s(W,hug)`); `W`
is wide because platform type is large (888 for a full-width overline, 420 next to
a rule, `s(fill,hug)` inside a fixed pill). A centered pill label uses
`align(center)` + hug height; left-aligned overlines stay left (no `align`). Keep
the eyebrow visibly subordinate to the headline — it is small caps, not a second
headline.

### Variant A — plain overline (default; no box, the anti-cliche choice)

```text
page eyebrow_overline_demo size(1080,1080,px)
  artboard al(v, x(s), y(c), g($space.stack.tight), pad(96)) p(0,0) s(fill,fill) fill($surface.page) clip(true)
    eyebrow text "WHY TEAMS SWITCH" p(0,0) s(888,hug) style($type.eyebrow) lh(1.1) wrap_text(true) max_lines(1) slot(section.eyebrow)
    headline text "Built for the work that matters." p(0,0) s(888,hug) style($type.headline) lh(1.1) wrap_text(true) max_lines(2) slot(section.title)
  #slot:section.eyebrow sample("WHY TEAMS SWITCH") worst_case("WHY GROWING TEAMS SWITCH")
  #slot:section.title sample("Built for the work that matters.") worst_case("Built for the work that matters.")
```

Validator proof:
```json
{ "ok": true, "stage": "preflight", "errors": [], "warnings": ["LUMB0613", "LUMB0614"] }
```

### Variant B — rule + label (distinctive; a short accent rule precedes the label)

A `48×4` accent rect (`fill($accent.primary) rd($radius.full)`) sits in an
`al(h, y(c))` next to the label, vertically centered via `y(c)`. The rule is a
`rect` with a numeric height (`4`) — there is no `divider` node, and
`$stroke.width.*` is illegal inside `s(...)`. The label box is `420` wide (smaller
than the full-width overline because the rule + gap take the rest of the row).

```text
page eyebrow_lined_demo size(1080,1080,px)
  artboard al(v, x(s), y(c), g($space.stack.tight), pad(96)) p(0,0) s(fill,fill) fill($surface.page) clip(true)
    eyebrow_row al(h, x(s), y(c), g($space.sm), pad(0)) p(0,0) s(888,hug)
      eyebrow_rule r p(0,0) s(48,4) fill($accent.primary) rd($radius.full)
      eyebrow_label text "WHY TEAMS SWITCH" p(0,0) s(420,hug) style($type.eyebrow) lh(1.1) wrap_text(true) max_lines(1) slot(section.eyebrow)
    headline text "Built for the work that matters." p(0,0) s(888,hug) style($type.headline) lh(1.1) wrap_text(true) max_lines(2) slot(section.title)
  #slot:section.eyebrow sample("WHY TEAMS SWITCH") worst_case("WHY GROWING TEAMS SWITCH")
  #slot:section.title sample("Built for the work that matters.") worst_case("Built for the work that matters.")
```

Validator proof:
```json
{ "ok": true, "stage": "preflight", "errors": [], "warnings": ["LUMB0613", "LUMB0614"] }
```

### Variant C — tinted pill (use only for genuine status badges)

A fixed `s(280,48)` `al(h, x(c), y(c), pad(10,20))` with `fill($surface.brand.subtle)`
and `rd($radius.badge)`. The label is `s(fill,hug) align(center)` — the slotted text
takes its definite width from the pill, hugs the glyph-tall height, and `align(center)`
centers the glyph inside the fill-width box (the pill's `y(c)` centers it vertically).
Use `$radius.badge` (NOT `$radius.button`/`$radius.card`) for the pill.

```text
page badge_pill_demo size(1080,1080,px)
  artboard al(v, x(s), y(c), g($space.stack.tight), pad(96)) p(0,0) s(fill,fill) fill($surface.page) clip(true)
    badge al(h, x(c), y(c), pad(10,20)) p(0,0) s(280,48) fill($surface.brand.subtle) rd($radius.badge)
      badge_text text "NOW IN BETA" p(0,0) s(fill,hug) align(center) style($type.eyebrow) lh(1.1) max_lines(1) slot(section.badge)
    headline text "Built for the work that matters." p(0,0) s(888,hug) style($type.headline) lh(1.1) wrap_text(true) max_lines(2) slot(section.title)
  #slot:section.badge sample("NOW IN BETA") worst_case("NOW IN BETA")
  #slot:section.title sample("Built for the work that matters.") worst_case("Built for the work that matters.")
```

Validator proof:
```json
{ "ok": true, "stage": "preflight", "errors": [], "warnings": ["LUMB0613", "LUMB0614"] }
```
