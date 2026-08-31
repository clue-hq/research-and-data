---
name: generative-imagery
description: Prompt the image model well and use what it gives back — the five-question prompt, brand-coherent prompting from the kit's real palette, the asset types (abstract ground, transparent spot illustration, brand-themed scene, texture, design element), how the turn's references condition the call, placement, and the fallback. Use whenever a design needs imagery the engine cannot draw.
---

# Generative imagery

Whether a surface earns an image at all is `skills/brand-imagery` +
`knowledge/images/decide`. This skill is the craft of the image itself: how to
prompt for it, how to keep it on-brand, and how to use what comes back. The
five-component prompt template lives in `knowledge/images/prompts`; the scrim
rule and the placement idioms live in `knowledge/images/placement`.

## 1. Why the image decides the design

Look at any professional ad. The typography is simple. The layout is
simple. What makes it feel expensive is the imagery: a soft grain wash, a
confident illustration, a photographed texture. That layer cannot be drawn
with rectangles and gradients. It comes from an image.

You have an image generation tool — `asset(action="generate_image")`. It is
not a fallback for missing assets. It is one of your two hands. The engine
draws structure — plates, type, buttons. The image tool makes atmosphere —
grounds, textures, illustrations. A design that uses only one hand looks flat
or looks like mush. Use both, each for what it is good at.

One rule above all: never fake an image with shapes. A grain wash built
from forty translucent circles is mush. Generate the wash. Never bake
structure into an image either. Text, buttons, and logos belong to the
engine, where they stay sharp and editable. If your prompt contains words
you want rendered as text, stop — that part is the engine's job.

## 2. The prompt is the craft

The tool gives back exactly what the prompt deserves. A lazy prompt gets a
stock-photo cliché. A precise prompt gets an asset that looks
commissioned. The difference is never the tool. It is always the prompt.

A strong prompt answers five questions, every time:

1. **What is it?** Name the thing plainly: "an abstract background
   texture", "a flat line illustration on a transparent background",
   "a photographed close-up of brushed metal".
2. **What style?** Name the visual language: "soft iridescent film grain",
   "single-weight black outline, no shading", "editorial studio
   photography, hard shadow".
3. **What colors?** Name exact hexes from the kit. Never say "blue" —
   say the kit's own ground and accent values, e.g. "#635BFF on a
   #F6F9FC field".
4. **What composition?** Say where the visual weight sits and where it
   must stay calm: "energy concentrated in the top-right corner, lower
   half almost flat", "generous empty center for overlaid content".
5. **What must NOT be there?** Say it explicitly, every time it applies:
   "no text, no letters, no logos, no people, no products".

### Worked example — weak, then strong

- Weak: "yellow abstract background"
- Strong: "Abstract background texture. Vivid yellow #FEFF00 field with
  soft airbrushed blooms of pale pink #F5B8DF and lilac #EACADE drifting
  in from the top-left. Fine film grain across the whole surface. Lower
  right two-thirds stays calm and near-solid for overlaid content.
  No text, no letters, no logos, no objects, no people."

The weak prompt produces a random gradient. The strong one produces the
brand's actual ground. Ten extra words of precision beat ten retries.

## 3. Brand coherence: the image must look like it was always theirs

An image can be beautiful and still be wrong, because it belongs to a
different brand. Coherence is not a vibe. It is three concrete inputs you
already hold, and each one becomes words in the prompt:

1. **The kit's tokens.** Pull the real hexes from the brand card and name
   them in the prompt. The card's `color_roles` resolve `$surface.page`,
   `$surface.brand`, `$surface.inverse`, and `$text.primary` to actual
   hexes, and `accent` names the most vivid brand color. An image whose
   palette is the kit's palette cannot clash with the design it lands in.
2. **The brand's existing imagery.** Before generating, look at what the
   brand already uses — the kit's `images` inventory on the brand card,
   and the reference images attached to this turn. `view("asset:<id>")`
   and `view("reference:<n>")` show you the real pixels. Describe what
   you see in plain words: is their imagery photographic or illustrated?
   Grainy or clean? Warm or cold? Dense or airy? Those observed words go
   into the prompt verbatim.
3. **Reference images on the call.** When the turn has reference images,
   they condition the generation call automatically — you do not attach
   them, and there is no parameter that turns them on or off. The
   platform already tells the model the references are STYLE references
   only: match their palette, texture, mood, and edge character, generate
   a new image, do not copy, crop, or edit them. So the prompt's job
   changes. It no longer describes the style from scratch, and it does
   not restate in words what the references already show — that is
   redundant and it fights the pixels. It owns what the references do not
   decide: the subject, the composition, and where the calm area sits.

### Worked example of the coherence test

The brand's ads all use soft holographic washes. You need a stat-card
ground. Wrong: invent a neon gradient because it "looks good". Right:
"the same iridescent pastel wash family as the references, on the kit's
#FEFF00 yellow". The founder's test for your output is one question —
"does this look like an asset the brand's own design team would have
made?" Ask it of yourself first.

## 4. What you can generate — the asset types

Each type has a default recipe. Adapt the words, keep the shape.

- **Abstract ground** (full-bleed background). The recipe in §2's worked
  example. One ground per design. Always state where the calm area is,
  because your content will sit on it.
- **Spot illustration** (transparent background, placed INSIDE the
  design). "Flat illustration of [subject], single-weight black outline,
  minimal fill in [kit hexes], on a fully transparent background, no
  backdrop, no shadow, no text." Pass `transparent_background=True` on
  the call, and `preserve_transparency=True` when you place it. Used like
  a sticker: a coin stair, a key, a chart motif. It is a placeable
  element, never a ground.
- **Brand-themed illustration scene** (a panel or band). Same as spot,
  but composed: "a scene of [subject] inside a rounded panel of
  [hex] …". Say what story the scene tells in one clause.
- **Texture / material** ("photographed close-up of [material], even
  lighting, no objects"). For grounds behind photo-real product props.
- **Design element** (a single decorative part: a ribbon, a frame, a
  pattern strip). Name its exact place: "a thin horizontal strip of
  [pattern], designed to sit along the bottom edge".

## 5. Mechanics of the call

- Generate with `asset(action="generate_image", target_node_id=<frame>,
  prompt=…, brand_notes=…)`. It registers the asset and returns its
  `asset_id`; it does not place it.
- State the aspect ratio you need. Normally you state it by passing
  `target_node_id` — the frame the image will fill — and the ratio comes
  from that frame's geometry; an explicit `aspect_ratio` overrides it.
  The result reports the dimensions it actually produced whenever your
  ratio was NOT honored: `aspect_ratio_honored: false`, the measured
  `actual_width` and `actual_height`, and a `note`. Read that answer;
  silence means the ratio came back right. If it came back wrong, crop
  with placement (fit and focal point), do not stretch.
- The turn's reference images ride the call for you. References condition
  style; your prompt still owns content.
- `brand_notes` and the prompt are joined into one instruction before the
  call, so both reach the model. `brand_notes` is the conventional home
  for palette and mood; the prompt stays about the subject.
- One generation, then look. `view("asset:<asset_id>")` what came back
  before placing it. Judge it with the same eyes you use on your own
  renders: palette right, composition right, nothing baked in that the
  engine should own.
- If it is wrong, change the PROMPT. There is no seed to reroll — an
  identical request is served from the generation cache, so the same
  prompt, brand notes, references, and geometry return the same picture.
  Name what was wrong in the new prompt: "less pink, calmer center, no
  objects".

## 6. Placement rules

- A ground places full-bleed with fit cover, focal point set by where
  the calm area is.
- A spot illustration places as its own node, sized deliberately, never
  stretched to fill.
- Text over any generated image gets a scrim or sits on the image's calm
  area. Both is best.
- One atmosphere per design. A wash plus a texture plus a glow is mush.

## 7. When generation fails

A failed or empty generation never blocks the design. When the model
answers with text and no image, the platform already retried once for
you, so a fallback means it failed anyway.

The tool tells you it fell back. The call still reports `status: ok`, but
`image.mode` is `"placeholder"`, `image.fallback` names the reason, and a
`hint` says the turn is not blocked. That placeholder is not real imagery
and must not ship as if it were.

React honestly: use a flat token ground, note the gap in your report, and
finish the design. A missing image is a smaller flaw than a broken run.

## 8. Before you place it — the three questions

1. Would this brand's own design team have made this asset?
2. Is everything the engine should own (text, logo, buttons) OUT of it?
3. Does the design still read if this image were removed? If no —
   the image is carrying structure it should not carry. Rebuild the
   structure in the engine.
