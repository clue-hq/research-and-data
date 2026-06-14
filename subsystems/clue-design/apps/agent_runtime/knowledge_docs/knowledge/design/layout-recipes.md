# Lumen Layout Recipes

Status: supported now, recognized but not lowered, and future scaffold.

Use these conservative recipes for product-quality ABM artifacts. All positions
and sizes in child `p()`/`s()` values are canonical layout points (`pt`) and are
local to the containing artboard or parent. Physical print units and raster pixel
targets belong to the page/export declaration, not to child node geometry.

## Supported Now

### Square Social Ad

Use a single clear message, one CTA, and generous margins. Keep text away from
edges. The canonical page must be square; do not draw a fake square artboard
inside another page.

Recommended structure:

- `page ... size(1080,1080,px)` which lowers to `1080 x 1080 pt` layout bounds.
- page `background(...)` when available, or one clipped root `artboard` frame
  with `fill(...)`.
- vertical message stack using `al(v,...)`.
- CTA button using `al(h,x(c),y(c),...)`.
- optional right-side or lower visual panel inside the same root frame.
- brand/proof row aligned with `x(sb)` or `x(c)`.

Example skeleton:

```text
page linkedin_square size(1080,1080,px)
  artboard al(v,x(s),g(28),pad(72)) p(0,0) s(fill,fill) fill($surface.brand) clip(true)
    content al(v,x(s),g(28),pad(0)) p(0,0) s(560,hug)
      headline text "Let neurosurgeons focus on surgery." p(0,0) s(fill,hug) style($type.headline) lh(1.08) wrap_text(true) max_lines(2) slot(campaign.headline)
      body text "Insight Health handles calls, scheduling, and patient routing." p(0,0) s(fill,hug) style($type.body) lh(1.35) wrap_text(true) max_lines(3) slot(offer.primary_message)
      cta al(h,x(c),y(c),pad(14,28)) p(0,0) s(220,56) fill($surface.inverse) rd($radius.md)
        cta_text text "Book a Demo" p(0,0) s(fill,hug) style($type.cta) slot(campaign.cta)
```

### A4 Appointment / One-Pager

`preset(a4,portrait)` lowers to about `595 x 842 pt` layout bounds while export
metadata can still say `210mm x 297mm`. Author against the point layout bounds.
Do not place children as if the artboard were `210 x 297`.

Use a root frame with an artboard/page background, print-safe padding, and cards
that are local to the root frame. Prefer vertical stacks with systematic gaps
over individual manual y coordinates.

```text
page one_pager preset(a4,portrait)
  artboard al(v,x(s),g(18),pad(36)) p(0,0) s(fill,fill) fill($surface.page) clip(true)
    card al(v,x(s),g(14),pad(24)) p(0,0) s(fill,hug) fill($surface.card) rd($radius.lg)
      eyebrow text "For specialty clinics" p(0,0) s(fill,hug) style($type.eyebrow) wrap_text(true)
      headline text "Recover missed calls without adding front-desk load." p(0,0) s(fill,hug) style($type.headline) wrap_text(true) max_lines(3)
      body text "AI phone agents answer, qualify, schedule, and route patient requests." p(0,0) s(fill,hug) style($type.body) wrap_text(true) max_lines(4)
```

### US Letter One-Pager

Use `page letter size(8.5,11,in)` or the supported Letter preset when available.
The layout space is `612 x 792 pt`. Keep print margins in points, usually
`36-54pt`, and use root-frame padding instead of a separate margin rectangle.

```text
page letter size(8.5,11,in)
  artboard al(v,x(s),g(20),pad(54,48)) p(0,0) s(fill,fill) fill($surface.page) clip(true)
    header al(v,x(s),g(8),pad(0)) p(0,0) s(fill,hug)
      headline text "A faster path from inquiry to appointment." p(0,0) s(fill,hug) style($type.headline) wrap_text(true) max_lines(2)
      body text "Route calls, triage requests, and keep the front desk focused." p(0,0) s(fill,hug) style($type.body) wrap_text(true) max_lines(3)
```

### Landscape Social / LinkedIn Ad

For a wide digital ad, use the requested raster surface directly. A
`1200 x 628 px` page has `1200 x 628 pt` layout bounds and a default
`1200 x 628 px` raster export.

```text
page linkedin_wide size(1200,628,px)
  artboard al(h,x(s),y(c),g(40),pad(56,64)) p(0,0) s(fill,fill) fill($surface.brand) clip(true)
    message al(v,x(s),g(20),pad(0)) p(0,0) s(fill,hug)
      headline text "Answer every patient call." p(0,0) s(fill,hug) style($type.headline) wrap_text(true) max_lines(2)
      body text "Insight Health schedules, routes, and summarizes the next step." p(0,0) s(fill,hug) style($type.body) wrap_text(true) max_lines(3)
    proof fr p(0,0) s(360,420) fill($surface.card) rd($radius.lg)
```

### Email Hero

Use a compact header, a large headline, one supporting sentence, and a CTA.
Avoid detailed small text because current preview/export quality is not meant
for final email-client rendering.

### Direct Mail Header/Postcard

Use print-safe margins, visible brand block, recipient/account slot, and a
single concrete reason to respond. Avoid complicated pagination in Phase A.

## Supported Alignment Patterns

- `x(s)` start-aligns on the physical x axis.
- `x(c)` center-aligns on the physical x axis.
- `x(e)` end-aligns on the physical x axis.
- `x(sb)` distributes children on the row main axis.
- `y(c)` is the common way to vertically center children inside row buttons.
- For column layouts, `y(sb)` distributes vertical space when the container has
  a definite height.

Use `x(sb)` for nav/proof rows and `x(c),y(c)` for buttons. Use `stretch` only
on cross-axis alignment when a container has definite space.

## Repair Implications

If preflight reports an artboard-bounds or parent-containment problem, do not
repair only the most visible text node. The correct fix is often a bounded
`layout_cluster` repair: adjust the diagnosed parent/root frame and affected
descendants together using p/s, fill/hug/fixed sizing, auto-layout, padding, gap,
wrap, or conversion of a background-like rect into the page/artboard fill.

## Future Scaffold

Future layout docs should include:

- responsive/variant recipes
- repeater/conditional regions
- dense stat/table modules
- multi-page brochures
- pagination rules
- editorial grid systems
