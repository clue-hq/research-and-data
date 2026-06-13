# Lumen Layout Recipes

Status: supported now, recognized but not lowered, and future scaffold.

## Supported Now

Use these conservative recipes for product-quality ABM artifacts.

### Square Social Ad

Use a single clear message, one CTA, and generous margins. Keep text away from
edges. The canonical page must be square; do not draw a fake square artboard
inside another page.

Recommended structure:

- `page ... size(1080,1080,px)`
- full-page background frame
- vertical message stack using `al(v,...)`
- CTA button using `al(h,x(c),y(c),...)`
- optional right-side or lower visual panel
- brand/proof row aligned with `x(sb)` or `x(c)`

Example skeleton:

```text
page linkedin_square size(1080,1080,px)
  bg fr p(0,0) s(1080,1080) fill($surface.brand)
    content al(v,x(s),g(28),pad(0)) p(72,88) s(560,hug)
      headline text "Let neurosurgeons focus on surgery." p(0,0) s(fill,hug) style($type.headline) lh(1.08) wrap_text(true) max_lines(2) slot(campaign.headline)
      body text "Insight Health handles calls, scheduling, and patient routing." p(0,0) s(fill,hug) style($type.body) lh(1.35) wrap_text(true) max_lines(3) slot(offer.primary_message)
      cta al(h,x(c),y(c),pad(14,28)) p(0,0) s(220,56) fill($surface.inverse) rd($radius.md)
        cta_text text "Book a Demo" p(0,0) s(fill,hug) style($type.cta) slot(campaign.cta)
```

### A4 One-Pager Section

Use sections with clear vertical rhythm. Make headings shorter than the
available text box and use `hug` height for body copy. Prefer vertical stacks
with systematic gaps over individual manual y coordinates.

```text
page one_pager preset(a4,portrait)
  section al(v,x(s),g(18),pad(24)) p(18,18) s(174,hug) fill($surface.card) rd($radius.lg)
    eyebrow text "For specialty clinics" p(0,0) s(fill,hug) style($type.eyebrow) wrap_text(true)
    headline text "Recover missed calls without adding front-desk load." p(0,0) s(fill,hug) style($type.headline) wrap_text(true) max_lines(3)
    body text "AI phone agents answer, qualify, schedule, and route patient requests." p(0,0) s(fill,hug) style($type.body) wrap_text(true) max_lines(4)
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

## Future Scaffold

Future layout docs should include:

- responsive/variant recipes
- repeater/conditional regions
- dense stat/table modules
- multi-page brochures
- pagination rules
- editorial grid systems
