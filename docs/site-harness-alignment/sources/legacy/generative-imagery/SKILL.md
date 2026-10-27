---
name: generative-imagery
description: Use whenever a design needs generated imagery, reference-conditioned artwork, or multiple image variants that remain separate from editable copy and branding.
---

# Generative imagery

Whether a surface earns an image at all is `skills/brand-imagery` +
`knowledge/images/decide`. This skill is the craft of the image itself: how to
prompt for it, how to keep it on-brand, and how to use what comes back. The
five-component prompt template lives in `knowledge/images/prompts`; the scrim
rule and the placement idioms live in `knowledge/images/placement`.

For scene imagery guided by visual references, first use
`skills/reference-image-direction` to choose the operation, observed qualities
to preserve and component boundaries. Reuse that direction here; this skill
continues to own the generation/placement mechanics and variant custody.

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

A precise prompt improves the chance of useful artwork; provider capability,
reference delivery and output variation also matter. Inspect what came back
before deciding it fulfills the brief. A successful tool call is not a quality
verdict.

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
   hexes, and `accent` names the most vivid brand color. The palette anchors brand coherence; local contrast, lightness and visual
   weight still need inspection in the composed design.
2. **The brand's existing imagery.** Before generating, look at what the
   brand already uses — the kit's `images` inventory on the brand card,
   and the reference images attached to this turn. `view("asset:<id>")`
   and `view("reference:<n>")` show you the real pixels. Describe what
   you see in plain words: is their imagery photographic or illustrated?
   Grainy or clean? Warm or cold? Dense or airy? Those observed words go
   into the prompt verbatim.
3. **Reference images on the call.** `reference_asset_ids` selects up to four
   inspected attachments, kit/library assets or scene assets for this component.
   Omission uses the turn attachments; [] uses none. Viewing an asset does not
   select it. Successful model/cache calls report exact `reference_inputs`. The
   platform already tells the model the references are STYLE references
   only: match their palette, texture, mood, and edge character, generate
   a new image, do not copy, crop, or edit them. So the prompt's job
   changes. Record the few observed qualities that matter, then specify the visual
   content, composition, tonal depth and quiet copy regions the brief needs. An
   abstract reference can remain abstract; a new image does not require a new
   literal scene. Viewing a reference without
   calling generation does not produce reference-conditioned artwork. A source
   logo/UI asset is not sent as a reference merely because you viewed it.

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
  the call, and `preserve_transparency=True` when you place it. Check the
  returned alpha: a provider can ignore the transparency request. The current
  Images API transport requests automatic background, so transparency is not
  guaranteed. Report an unmet transparent-asset requirement rather than treating
  an opaque rectangle as a cutout. Used like
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
  for palette and mood; the prompt can describe reference treatment as well as
  visual content and composition. Keep the two consistent.
- One generation, then look. `view("asset:<asset_id>")` what came back
  before placing it. Judge it with the same eyes you use on your own
  renders: palette right, composition right, nothing baked in that the
  engine should own.
- If it is wrong, change the PROMPT. There is no seed to reroll — an
  identical request is served from the generation cache, so the same
  prompt, brand notes, references, and geometry return the same picture.
  Name what was wrong in the new prompt: "less pink, calmer center, no
  objects".

## Requested artwork variants

When the brief requires generated artwork and multiple variants, produce that
number of distinct artwork assets. Existing source screenshots, kit backgrounds
and native gradients do not substitute for requested new imagery. If the brief
requests two options, the required output is two real image assets plus a scene
with independent native overlays, not two flattened finished ads.

Choose useful differences in composition, subject treatment, visual weight or
camera/crop direction from the brief and observed references. Keep the business
message and source assets constant. Do not default every brand to an abstract
wash: a photographic prop, illustration, material or atmospheric field must have
a clear job in this particular concept.

1. Author the page first. Generate each option with a substantively different
   prompt and a clear label. An identical request can hit cache; changing only
   the label is not a new visual direction.
2. Each prompt reserves the intended native-copy and source-asset regions. Keep
   the main headline, support, CTA/button, logo and product UI out of the artwork.
   Source UI/photos and the exact logo remain their own original image layers;
   generated pixels must not invent testimonials, metrics or product behavior.
3. View every returned asset and read its mode, model, dimensions and fallback
   evidence. A placeholder is not a real variant; a cache hit is not a fresh
   provider call. Check for copied lettering, marks, unintended UI and poor copy
   contrast. Repair within the run budget or report the requirement as unmet.
4. Compare the options, keep both registered assets in the scene, and place the
   stronger one in an independent image node. The unplaced alternative must stay
   in the scene assets map through save so it can reach the workspace library.
5. Report the returned asset IDs and labels, the selected option and any failure.
   Inspect the final composition with its native overlays, not just the artwork.
   Availability through the editor's Replace image action requires a saved asset;
   do not claim the user can swap an alternative that was discarded.

## 6. Placement rules

- A ground places full-bleed with fit cover, focal point set by where
  the calm area is.
- A spot illustration places as its own node, sized deliberately, never
  stretched to fill.
- Text over any generated image gets a scrim or sits on the image's calm
  area. Both is best.
- One atmosphere per design. A wash plus a texture plus a glow is mush.

## 7. When generation fails

A failed or empty generation can leave a useful editable draft, but it does
not fulfill a brief that requires real generated artwork. When the model
answers with text and no image, the platform already retried once for
you, so a fallback means it failed anyway.

The tool tells you it fell back. The call still reports `status: ok`, but
`image.mode` is `"placeholder"`, `image.fallback` names the reason, and a
`hint` says the turn is not blocked. That placeholder is not real imagery
and must not ship as if it were.

React honestly: use a flat token ground, note the gap in your report, and
return the design as an incomplete draft. State which requested artwork
variants are missing; do not label that experiment successful.

## 8. Before you place it — the three questions

1. Would this brand's own design team have made this asset?
2. Is everything the engine should own (text, logo, buttons) OUT of it?
3. Are required copy, branding, buttons and authentic product evidence
   independently present in their intended layers? Artwork can carry the
   concept and atmosphere; exact editable content belongs to its own nodes.
