---
name: reference-image-direction
description: Use when a scene creative needs new imagery based on visual references, a close brand companion, a new concept in the brand's style, or correction of artwork that matches the palette but misses the reference.
---

# Reference image direction

Turn the current brief and visible references into a useful image direction.
Work inside the **design agent's current creative** using its supplied brand kit,
assets and attachments. Brand harvesting, library expansion and brand-agent
development belong to a separate workflow.

`skills/generative-imagery` owns tool mechanics and variant custody;
`skills/reference-conditioned-ads` owns the whole ad's reference interpretation.
This skill owns the missing decision between **seeing a reference and asking
for particular new imagery**. Read the [decision guide and worked examples](/knowledge_docs/knowledge/images/reference-direction.md)
for an unfamiliar operation, ambiguous effect, or capability gap.

## Defaults & required decisions

1. **Inspect once, select deliberately.** Batch `view("reference:<n>")` and
   relevant `view("asset:<id>")` calls. Prefer original brand imagery over old
   generated experiments. Verify pixels, not tags: an abstract field is not a
   landscape; a product screen is not a background. Mark identity, subject,
   treatment and composition roles. Unknown pixels remain unknown.
2. **Choose the job and operation.** Connect imagery to this audience and
   message: atmosphere, product evidence, or an explanation. Reuse/crop exact
   sources; edit a placed image for a named correction; generate a close
   companion or a new concept. Separate permission to change the **subject**
   from permission to change the **visual treatment**. A new concept does not
   authorize new lighting, materials or motif language. Rearrange observed
   forms when that suffices; native copy can carry the message without a
   literal visual metaphor. Native type/geometry may be sufficient when no
   new image is requested.
3. **Use one compact handoff (about 200 words).** Put this record in the existing reference brief
   or round direction, then pass its path and decisions to the author:
   `job; selected IDs/roles; operation; preserve; vary; layers; copy contrast;
   review gaps`. Link it from other run notes. Preserve discriminating subject,
   tonal, edge, texture-scale and spatial qualities; uncertainty stays explicit.
   This record replaces a separate imagery-planning document.
   Before generation, compare the component prompt to the inspected sources:
   identify any newly invented motif, lighting or material and why the brief
   requires it. If it changes the treatment without evidence or permission,
   remove it. A concept word such as “connected” is not evidence of how this
   brand depicts connection.
4. **Plan foreground and background together.** Specify aspect, subject bounds,
   quiet copy region and its required tone. Quiet means low detail, not pale:
   white copy needs a sufficiently dark region; dark copy needs a light one.
   Choose an authentic wordmark/lockup whose existing colors work there. A
   favicon is not a substitute for a recognizable wordmark. Keep source UI,
   logo, native text and any button independent. Native paths/icons are vectors;
   generated illustrations remain raster.
5. **Send the selected pixels.** Use `reference_asset_ids=[...]` on
   `asset(action="generate_image", ...)`: up to four inspected attachments,
   kit/library assets or current scene assets. Select only useful treatment
   inputs for a new background; leave authentic UI for its own layer. Omission
   uses all turn attachments; [] deliberately uses none. Viewing alone does not
   attach. Prompt for the required component and observed treatment; leave
   artistic details to the model. Read `reference_inputs` and `mode` on return.
6. **Build with real asset IDs.** Compile the page, actual copy/logo and a
   artwork frame with explicit pixel width/height first. An unresolved `fill`
   frame cannot reliably supply the requested aspect ratio; pass the intended
   aspect explicitly if necessary. Generate against that frame, inspect the result,
   then add its image node with the returned ID. An image declaration requires
   `asset(...)`; a frame can reserve geometry before generation. Use legal size
   tokens and the existing format skill. The guide covers this staging step.

## Self-audit checklist

View each new image and the final composition. Check subject, treatment, tonal
depth, texture scale, baked-in content, crop and dimensions. At feed size, read
every required line and recognize the brand. For text over an image, use
`inspect(view="image_contrast", target=<asset_id>, foreground_color="#RRGGBB",
region=[left,top,right,bottom])` with the resolved ink color and the copy box
mapped into normalized **source** coordinates. Check at least 3:1 for large
display type and 4.5:1 for body copy. The returned threshold flags use unrounded
measurements. This samples source pixels, not the final composite: account for
cropping, plates and effects separately. Transparent or color-profiled inputs
need a composited check; a refused measurement is not a pass. Repair the color,
placement or ground when the measured region fails. Then view the final render.
A dismissed token-ancestor warning or a visual guess cannot establish contrast.

Judge distinctive qualities separately: matching the dots or palette cannot
compensate for unsupported lighting or motifs. View the source and candidate
together; name both retained qualities and introduced ones. Reject an invented
treatment that changes the brand's character even when the image looks polished
and the text is editable. Preserve successful components and repair the failed
component; do not rationalize the departure from the campaign message.

If the reference uses a logo variant absent from the kit, report that gap.
The existing `fetch_logo` tool can look for a real published variant, after a
page exists. Never redraw/recolor a logo or treat a white plate as equivalent
to the reference's white wordmark. Use a supplied authentic variant where its
ink is legible when no appropriate published variant is available.

For a failed candidate, name the mismatch and change the relevant instruction
or use a supported edit. An identical request can return cached pixels. Preserve
valid alternatives. A placeholder is not new model artwork. Verify requested
alpha rather than assuming it. Stop within the run's budget and report missing
requirements honestly. A successful call establishes delivery, not brand fit.
