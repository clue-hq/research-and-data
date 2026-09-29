# Rich cards controlling product media

Use this route when captured cards contain a number, heading and explanation,
and selecting a card reveals its matching product image. Captured HTML can
contain every state while lacking the controller. A screenshot of the first
state establishes neither switching nor timing.

## Bind the evidence before composing

Record each observed control, its visible text, selected treatment and matching
registered asset. Keep source background and product layers distinct: inspect
whether the product image is transparent or already includes a backdrop before
adding another. Carry the approved Words and capability evidence into each
state; do not invent a fourth capability just because the source has four cards.
Measure the source card/media proportions, type, gaps and responsive order.

## Existing native route

Typed tabs accept one Text label per item, but that label can contain multiple
`span[class]` runs. They become one accessible tab button, not three separate
controls. For example, within a section:

```html
<div id="feature_switch" class="feature-switch" data-component="tabs">
  <div id="messages">
    <p><span class="feature-number">01</span><span class="feature-title">One inbox</span><span class="feature-description">Review incoming messages together.</span></p>
    <p>The matching product panel belongs here.</p>
  </div>
  <div id="handoff">
    <p><span class="feature-number">02</span><span class="feature-title">Assign with context</span><span class="feature-description">Keep the conversation with the handoff.</span></p>
    <p>The second matching product panel belongs here.</p>
  </div>
</div>
```

This illustrates grammar, not finished page copy or product evidence. Replace
panel text with the inspected registered imagery and supported explanation.
Use the real source's section layout and type, not this example's words.

The rendered group has `.lumen-tabs-list > .lumen-tab` controls and sibling
`[role="tabpanel"]` panels. Section-local custom classes can make label spans
block-level and arrange controls around a media panel. `display:contents` on
the list lets its buttons participate in the enclosing grid. Keep inactive
`[hidden]` panels hidden; a display override must not reveal every state.
Use the measured font family/weight and loaded kit fonts for rich spans, since
their label wrapper is not a heading node. Compare column heights: a shared
two-row grid does not reproduce independently sized source card columns exactly.

## Reuse and limits

Use the checked vocabulary repair lane when converting a pinned inert source.
It retains native tab behavior and portable custom class rules in the reusable
artifact; a new pin must be tested separately from the typed draft. Custom CSS
with ID selectors/local ID URLs, global declarations such as `@font-face`,
`@page` or `@property`, indirect animation names, cascade layers or unsupported
nested rules refuses minting.
The typed section stays on the page. Report the dependency; do not remove an
essential font or visual rule merely to force a successful mint. Use existing
kit font custody and classes when sufficient, or report the missing capability.
Preserve existing page CSS when making a scoped change; do not replace the
whole page just to install this interaction. Follow ordinary release authority.

Native tabs provide manual selection and arrow-key movement. They do not recover
the source's React/JavaScript or establish autoplay, progress timing or transition
fidelity. Inspect the final pin's every state, text/image pairing, loaded fonts,
crop/background layers, keyboard access, independent repeated instances and
phone/tablet reading order. Observe reduced-motion behavior too. Report a
manual equivalent as such; unresolved motion or geometry remains unverified.
