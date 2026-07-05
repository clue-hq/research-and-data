---
assumes: images/decide
---
# Imagery — Prompt Craft (the 5-component structure)

Once `knowledge/images/decide` says "generate a photo", write the prompt well. A vague
keyword bag ("business, technology, success, blue") produces generic stock-feel
filler. Specificity is what makes a generated image look art-directed. Every
`asset(action="generate_image")` prompt carries **five components**, in descriptive prose.

## The five components

1. **Subject** — what is literally in frame, concretely. *Who/what, doing what,
   where.* "A focused neurosurgeon reviewing a glowing 3D brain scan on a translucent
   display" — not "doctor, technology".
2. **Medium / Style** — name the medium: *editorial photograph*, *cinematic still*,
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
- **Brand tone goes in `brand_notes`, not the prompt.** Pass palette + mood as
  `brand_notes` (e.g. `["deep navy + teal palette", "calm clinical confidence",
  "premium, uncluttered"]`). The model conditions on them; the prompt stays about the
  scene.
- **Compose for the overlay.** If text/scrim will sit on the image, prompt for a clean
  area: *"ample uncluttered negative space in the lower third for text"*, *"subject on
  the right, soft empty background on the left."* This is what makes a scrimmed hero
  read cleanly (see `knowledge/images/placement`).
- **Aspect comes from the frame, not the prompt.** `asset(action="generate_image")` derives
  the aspect ratio from the target node's geometry — don't hardcode a ratio that fights the frame.

## Per-use-case templates

Fill the five components into the right skeleton:

- **Hero (full-bleed, text overlays):** `<editorial/cinematic photograph> of <subject + action + setting>, <composition with negative space for text>, <lighting + mood>, premium, no text.`
- **Product:** `<studio/editorial photograph> of <product>, <angle — three-quarter / overhead>, on <clean surface>, soft studio lighting, crisp detail, no text.`
- **Portrait / person:** `<natural editorial portrait> of <person + role + expression>, <framing — head-and-shoulders / environmental>, soft directional light, shallow depth of field, no text.`
- **Food:** `<appetizing overhead/45° photograph> of <dish>, natural soft light, fresh ingredients, shallow depth of field, no text.`
- **Texture / background:** `<macro photograph or abstract render> of <material/pattern>, even soft light, subtle and low-contrast (it sits behind content), no text.`
- **Illustration (raster):** `<flat / isometric / watercolor> illustration of <concept>, <limited brand-aligned palette>, clean composition, no text.` (For *icons* or simple flat marks use the library — `svg(icon:name)` — not the model; see `knowledge/images/decide`.)
