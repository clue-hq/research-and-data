---
assumes: images/decide
---
# Imagery — Prompt Craft (the 5-component structure)

Once `knowledge/images/decide` says to generate imagery, write the prompt well. A vague
keyword bag ("business, technology, success, blue") produces generic stock-feel
filler. Specificity is what makes a generated image look art-directed. Every
`asset(action="generate_image")` prompt carries **five components**, in descriptive prose.

## The five components

1. **Visual content** — what the artwork contributes to this brief: a subject,
   illustration, material, texture or abstract field. Describe it concretely.
   An abstract reference can remain abstract; it does not require an invented
   person, setting or narrative scene.
2. **Medium / Style** — describe the observed treatment and intended medium:
   *editorial photograph*, *cinematic still*,
   *3D render*, *watercolor illustration*, *flat vector-style illustration*,
   *macro photograph*. This sets the whole look.
3. **Composition** — framing + angle + depth: *wide establishing shot*, *tight
   portrait*, *overhead flat-lay*, *shallow depth of field*, *subject off to one
   side*. If text will overlay the image, **compose for it** (see below).
4. **Lighting** — quality + direction + mood: *soft window light*, *dramatic side
   light*, *golden-hour backlight*, *clean studio softbox*, *moody low-key*.
5. **Quality / Render cues** — *high detail*, *premium*, *editorial*, *muted
   palette*, *photorealistic*. Keep these few and purposeful, not a pile of buzzwords.

Write them as one or two natural sentences, not a comma list. Prose beats keywords.

## Hard rules

- **No in-image text.** Models garble lettering, and all real copy comes from the
  design layer (it must be editable + on-brand). End every prompt with *"no text, no
  words, no letters, no logos, no watermarks."*
- **No readable screens.** The trap version of in-image text: "show the product" makes
  the model render a monitor/phone with a garbled fake UI — that fails review the same
  way. For product-in-context shots, prompt the screen *away*: angled/side view,
  distant, screen dimmed, or *"screen showing abstract soft-colored shapes"* — never a
  legible UI close-up.
- **Brand direction is one coherent instruction.** Pass palette + mood as
  `brand_notes` (e.g. `["deep navy + teal palette", "calm clinical confidence",
  "premium, uncluttered"]`). The provider joins these notes with the prompt.
  Describe relevant reference qualities in the prompt too, keeping both fields
  consistent with the brief and observed pixels.
- **Compose for the overlay.** If text/scrim will sit on the image, prompt for a clean
  area: *"ample uncluttered negative space in the lower third for text"*, *"subject on
  the right, soft empty background on the left."* This is what makes a scrimmed hero
  read cleanly (see `knowledge/images/placement`).
- **Aspect comes from the frame, not the prompt.** `asset(action="generate_image")` derives
  the aspect ratio from the target node's geometry — don't hardcode a ratio that fights the frame.
- **Select relevant reference pixels.** `asset(action="generate_image")` accepts
  `reference_asset_ids`: up to four inspected attachments, kit/library assets or
  scene assets. Omission uses turn attachments; [] uses none. A successful
  model/cache result reports exact `reference_inputs`. Viewing alone does not
  attach a library image. These inputs are style anchors, not exact source edits.
  Inspect the pixels and describe the qualities to carry forward: palette,
  texture, mood, edge character, depth and visual weight. Then describe the artwork
  and copy regions this brief needs. These observations guide a new image; they
  do not guarantee fidelity or preserve exact source content. Keep authentic
  logos and product UI as separate original asset layers, with native editable
  copy and buttons. Inspect the generated artwork and the composed result.

## Per-use-case templates

Fill the five components into the right skeleton:

- **Hero (full-bleed, text overlays):** `<medium and reference treatment> with <visual content chosen for the brief>, <composition with negative space for text>, <lighting or tonal depth>, no text.`
- **Product:** `<studio/editorial photograph> of <product>, <angle — three-quarter / overhead>, on <clean surface>, soft studio lighting, crisp detail, no text.`
- **Portrait / person:** `<natural editorial portrait> of <person + role + expression>, <framing — head-and-shoulders / environmental>, soft directional light, shallow depth of field, no text.`
- **Food:** `<appetizing overhead/45° photograph> of <dish>, natural soft light, fresh ingredients, shallow depth of field, no text.`
- **Texture / background:** `<macro photograph or abstract render> of <material/pattern>, even soft light, subtle and low-contrast (it sits behind content), no text.`
- **Illustration (raster):** `<flat / isometric / watercolor> illustration of <concept>, <limited brand-aligned palette>, clean composition, no text.` (For *icons* or simple flat marks use the library — `svg(icon:name)` — not the model; see `knowledge/images/decide`.)
