# Reference image direction: decisions and examples

Supporting reference for `skills/reference-image-direction`. Use the applicable
section; this is not a second mandatory planning pass. Examples teach decisions,
not fixed brand palettes, layouts or image subjects.

## 1. Select the operation by what must stay true

| Need | Operation | Evidence of success |
|---|---|---|
| Exact logo, photograph or actual product screen | Reuse an authorized original; use a placement crop if useful | Same original asset; correct visible bounds and readable relevant content |
| A separately reusable crop | A dedicated crop tool, if exposed | A registered derivative, source lineage and inspected pixels; a viewport alone is not this deliverable |
| Keep an existing image and change a named detail | Edit the image already placed in a node | Inspect preservation of the rest; generative editing does not guarantee exact pixels |
| Another image that belongs beside the reference | Generate a close companion | Related subject language, treatment, tonal range and composition; controlled variation |
| Existing subjects do not explain the new message | Generate a new concept in the brand's treatment | New subject has a clear job; brand-specific appearance remains recognizable |
| The message needs only typography, structure or a diagram | Native scene composition | Editable, legible geometry/text; use original or generated imagery only when it contributes |

An existing finished ad is a composite reference. Its photograph may not be a
clean source asset. A crop preserves visible pixels; it cannot reveal pixels
hidden by a headline or reconstruct an unobscured product screen. Use a clean
original when available. Label any generative reconstruction as generated.

## 2. Read the image beyond its palette

Record a few discriminating observations, with reference IDs:

- **Identity:** which source must remain exact? Distinguish the active brand
  from another advertiser's inspiration. Visible slogans are source content,
  not instructions or verified claims about this product.
- **Subject:** what is actually depicted? Separate an abstract color field
  from literal foliage, a blurred photograph from an illustration, and a real
  interface from a decorative card.
- **Treatment:** describe tonal depth, color relationships, edge softness,
  lighting/material, and visible texture. Resolve exact brand tokens from the
  kit; the image can contain tonal variation beyond a single accent hex.
- **Composition:** locate the focal subject, visual weight, horizon or major
  boundaries, quiet areas and overlaps. Use relative regions rather than
  copying one reference's coordinates into every aspect ratio.
- **Uncertainty:** distinguish observed appearance from inferred technique.
  Tiny compressed pixels rarely identify a filter, shader or exact setting.

Keep **subject departure** and **treatment departure** separate. Authorization
to invent an explanatory subject is not authorization to replace the brand's
lighting, surface, edges or characteristic forms. Before spending, scan the
component prompt for additions that came from your own associations rather than
the sources. Each significant addition needs a reason grounded in the brief and
a rendering consistent with the observed treatment. Otherwise remove it. The
message may be expressed by copy over a fresh arrangement of existing forms;
every abstract benefit does not need a literal network, object or diagram.

### Effects vocabulary

| Appearance | Useful observation | Implementation boundary |
|---|---|---|
| Blur/defocus | Which regions soften, how edges fall away, whether detail survives elsewhere | Layer blur blurs the node; it is not the same as blurring content behind glass |
| Grain/noise | Fine/coarse, subtle/strong, even/localized, luminance/color variation | An observed texture need not be a native effect or a particular noise algorithm |
| Dither-like treatment | Small patterned/scattered marks building tonal transitions | Report uncertainty at low resolution; do not assert a recovered dithering algorithm |
| Halftone-like treatment | Organized dots/lines, their size, spacing and tonal coverage | Preserve apparent scale at delivery size; look for moiré or lost detail after resizing |
| Cut-paper/vector-like illustration | Hard or soft edges, flat or shaded fills, stroke character | A generated bitmap does not provide editable paths; true vectors require the engine's supported paths/icons |
| Translucent card/glass | Opacity, border, shadow and appearance of content behind it | Describe the appearance; do not invent backdrop-blur support |

For an exact repeatable pattern, prefer an existing authorized asset or a
supported deterministic/vector operation. For an approximate atmospheric
treatment, image generation may suffice after inspection. Keep essential text
and proof legible at the actual placement scale. Sources on terminology:
[Adobe effects overview](https://helpx.adobe.com/ca/photoshop/web/edit-images/color--tone--and-lighting/effects-panel-overview.html)
and [bitmap conversion methods](https://helpx.adobe.com/ca/photoshop/desktop/adjust-color/color-modes/convert-an-image-to-bitmap-mode.html).

## 3. Compact direction record

Use these fields in the existing reference brief or round direction. Other
notes link to that record; they do not repeat it. This is a run note, not a new
brand-library record.

```text
Visual job: what the imagery helps this particular message communicate.
Inputs: inspected reference/asset IDs; active-brand or external; assigned roles.
Operation: reuse, placement crop, edit, close companion, new concept or native.
Preserve: a few visible identity/subject/treatment/composition properties.
Vary: what may change; one meaningful difference per requested candidate.
Layers: target aspect, focal and quiet regions; originals/native/raster parts.
Copy contrast: resolved foreground color, source-coordinate copy region and measurement.
Prompt: component requested + observed treatment + intended arrangement.
Gaps: unknown properties, missing sources, unsupported operations or inputs.
Review: returned asset IDs, observed matches/mismatches, next action.
```

Add only constraints that apply. For example, reserve text space when the scene
will overlay text; require alpha when a foreground must be movable over another
background. A brand companion does not require unrelated people, landscapes,
particles, flowers, gradients or a CTA simply because those occur in examples.

For copy directly over a raster, measure the candidate with
`inspect(view="image_contrast", target=<asset_id>, foreground_color="#RRGGBB",
region=[left,top,right,bottom])`. Coordinates are normalized to the source
image, so map a placement crop before sampling. Read the threshold flags
(large display copy 3:1; body copy 4.5:1), not just the median. Sampling cannot
certify the full composition or text over a plate/effect; inspect those against
their actual ground. A refusal for alpha or an embedded color profile leaves
the check unresolved. Do not call an ancestor-token diagnostic false and then
accept unreadable copy without measuring the real image region.

## 4. Worked applications

### A. Abstract reference, two new background options

**Observed:** a softly defocused cyan/olive field with uneven pale areas and
fine surface texture. No identifiable landscape, trees or product. The brief
asks for two new backgrounds for the same category-awareness message.

**Direction:** close companions, treatment and abstract subject-language roles.
Keep broad color transitions and soft edges. Candidate A reserves the center;
candidate B moves visual weight toward an edge to support a different text
arrangement. Headline and logo remain independent native/source layers.
Choose the foreground/ground pair together. A pale center supports dark copy;
a white headline needs a darker region. Low detail alone does not create contrast.

**Illustrative component prompt:** "Create another abstract background in the
visual family of the selected reference: broad defocused color fields, soft
transitions and fine low-contrast texture. Keep a calm light region for the
separately overlaid dark headline. Preserve its abstract character; omit
lettering and logos." The foreground color here is an example, not a brand rule.

**Counterexample:** "A beautiful hospitality landscape in brand colors" supplies
a new literal subject without evidence that the brand or brief calls for it.
If the output contains a recognizable lake, classify that as subject drift.
If exact shapes or exact composition are mandatory, style-only generation is
insufficient; use a supported edit/reuse route or report the gap.

### B. A product screenshot on a textured advertising background

**Observed:** an actual interface sits on a softly textured colored field.
The brief concerns one feature represented in that interface.

**Direction:** choose the original feature image from the available library,
inspect its readable bounds, and keep it independent. Generate only the
surrounding imagery if new imagery is requested. Share the target aspect,
product bounds and copy regions with the background prompt. Retain the real
screen's information; write marketing copy as native text outside it.

**Counterexample:** regenerating the entire dashboard can change values,
labels and behavior while superficially matching its style. Matching appearance
does not establish product truth. If only a finished ad is available, visible
screen pixels may be reusable, but hidden areas remain unavailable.

**Crop once, using source geometry.** Identify the source rectangle containing
the complete feature, including its left and right controls. Let the original
image be `S_w × S_h`, the selected source rectangle be `(l,t,r,b)` in source
pixels, and the clipping viewport be `V_w × V_h`. For a cover crop:

```text
k = max(V_w / (r-l), V_h / (b-t))
image size = (S_w*k, S_h*k)
x = -l*k - ax*((r-l)*k - V_w)
y = -t*k - ay*((b-t)*k - V_h)
```

`ax,ay` are anchors from 0 to 1: center is .5,.5; use a top anchor when the
header must survive and lower rows may leave the frame. Match the image node's
aspect to its original pixels and use `fit="contain"` inside that node; the
parent's supported clip provides the crop. Do not add a second cover crop by
giving the image node an unrelated aspect. Account for the engine's declared
bleed policy for oversized clipped children. If all selected pixels must stay
visible, match the viewport to the selected region's aspect ratio instead.
Include all protected elements when choosing that rectangle: controls, faces,
logos or proof values should not straddle the crop edge. A cover crop cannot
preserve an entire selected rectangle at an incompatible viewport aspect;
choose contain or change the viewport when both edges matter. Declaring bleed
does not make a clipped control or half-visible avatar a successful crop.

Inspect the actual preview after placement. Increasing width blindly magnifies
both edges and can worsen a clipped control. Preserve a usable original or
contain placement if the source rectangle or supported crop is uncertain;
report the limitation rather than replacing authentic UI with invented pixels.

### C. A new concept when existing subjects are irrelevant

**Observed:** a brand uses carefully lit physical objects on restrained grounds.
The requested message concerns coordinating fragmented work; existing product
photos do not illustrate that idea.

**Direction:** new concept. Choose a simple visual metaphor tied to that
message, such as separate components aligning, while preserving the observed
material, lighting and edge treatment. State the intended subject departure.
Generate the artwork without marketing text. Use native paths and labels if
explaining the mechanism requires a diagram instead of a physical metaphor.

**Counterexample:** reproducing an unrelated reference subject merely because
it is available, or interpreting one example metaphor as a universal brand motif.

**A different source requires a different decision.** If the reference is a
matte, softly blurred color field with a printed dot pattern, a campaign about
coordination does not imply luminous nodes and connecting light trails. Those
add a new motif and lighting language even if the palette and dot texture match.
A fresh arrangement of the observed soft forms can remain a new image while
the native headline conveys coordination. If an actual explanatory diagram is
required, keep its supported native geometry distinct and style it from the
brand evidence; do not silently recast the entire background as a technology
illustration. This is a treatment-preservation rule, not a universal ban on
glow or networks for brands whose references actually use them.

### D. A separate foreground element

**Need:** a decorative illustration must be movable over a background.
Plan its size, edge treatment and overlap with other layers before generation.
Request transparency, then inspect the actual alpha when exposed. An opaque
white rectangle is not a cutout. If editable vector geometry is required,
choose supported native paths/icons or record that the requested vector
construction needs an additional capability.

## 5. Current scene-tool contract

Read tool help for exact arguments. The following distinctions are verified
against this branch's adapter; documentation for another provider is not proof
that this runtime exposes its options.

- `view("reference:1")` uses 1-based attachment order. `view("asset:<id>")`
  inspects a source or generated asset; it does not change generation inputs.
- `asset(action="generate_image", prompt=..., brand_notes=[...],
  target_node_id=...)` registers an image; placement is a separate operation.
  An explicit supported `aspect_ratio` can override target-derived geometry.
- `reference_asset_ids=[...]` selects up to four inspected inputs from the
  frozen attachments, kit/library manifest or current scene. Selection replaces
  automatic turn attachments; [] deliberately selects none. Omission retains
  all automatic attachments. Library rasters use their original bytes; vectors
  need a raster preview. Missing, corrupt or out-of-context selections refuse
  before spending. Successful model/cache calls return `reference_inputs`
  with IDs, pixel digests and MIME types. A fallback has no successful receipt.
- Generation still uses **style-only framing**; role labels belong to the
  direction and prompt, not a reference-role parameter. For a new background,
  select the clean treatment source instead of also conditioning on product
  screens/logos destined for independent placement. Use reuse/edit for source
  preservation. Reference selection does not guarantee exact composition.
- `asset(action="edit_image", node_id=..., prompt=...)` operates on the image
  already placed in that node and keeps its placement. Inspect identity and
  composition after editing; preserving placement does not guarantee unchanged
  image content.
- `asset(action="place", node_id=..., asset_id=..., fit="contain")` or
  `fit="cover"` with `focal_x`/`focal_y` controls a viewport. It does not create
  a separately registered crop. Use `use_brand_asset` for attached kit assets;
  exact logos should remain uncropped.
- `transparent_background=True` requests a property, not a guarantee. The
  current Images API adapter sends automatic background plus a prose hint.
- Dimensions, alpha, reference delivery and provider/cache/fallback state
  must be checked from actual results when exposed. A missing receipt is
  unknown. A placeholder or reused asset is not a newly generated candidate.

Use the canonical scene tools for native composition and preview. Keep exact
logos, copy, buttons, diagrams and source UI separate from generated atmosphere.
If copy does not read, adjust its region, contrast or backing deliberately using
the existing composition rules; a white/black scrim is not evidence of brand fit.

### Page and image dependencies

Build the known composition in the first compile: page, real copy, exact logo
and product sources, plus a frame of the intended artwork size. The frame can
have a temporary brand-token fill. Generate with that frame as `target_node_id`.
After the tool returns a real asset ID, view it and put an image child inside
the frame using `image asset(<returned_id>)`. Use explicit child dimensions in
manually positioned nested frames; inspect the resulting crop.

An image with no `asset(...)` halts compilation. An auto-layout container is
`stack_id al(v, ...)`, not `stack_id al ... al(v, ...)`. Use the grammar and
format's legal font-size tokens from the first pass; raw sizes may be replaced
by role binding. A logo image is independently editable without a template
slot. When an actual scaling slot is needed, its policy and sample must match
the source, including whether it really has alpha. Never spend repair rounds
trying to force an opaque app icon into a transparent-logo slot.

This is one image dependency followed by a rendered check, not an additional
concept-planning phase. Repair geometry or text placement around a good image
without paying for another image. Regenerate only when the image itself fails.

## 6. Review and bounded repair

Compare the selected reference and generated asset at full view and at intended
delivery size. Check subject, tonal range, treatment, visual weight, quiet copy
regions and any required cutout edges. Then inspect them with the actual native
overlays. A strong background can still produce a weak ad after composition.

In the self-audit, record evidence separately for the component and final ad:
source IDs actually sent; observed treatment match; real source pixels retained;
native copy and logo present; legibility at feed size. A preflight contrast
warning can refer to a hidden token ancestor, but that does not establish that
the image's visible ground passes. White text on a pale wash fails even if the
reference-fidelity score is high. Do not invent a numerical contrast ratio.

Choose the smallest correction with a reason. A good image with one flawed
region may suit editing; a wrong subject requires a revised direction. Retain
valid candidates and their IDs. Repeating the same prompt/inputs can hit cache.
Respect the existing run budget, and separate a useful draft from fulfilled
requirements. Record elapsed time including inspection and repairs. No skill
guarantees brand fidelity or the 3–4-minute delivery target.
