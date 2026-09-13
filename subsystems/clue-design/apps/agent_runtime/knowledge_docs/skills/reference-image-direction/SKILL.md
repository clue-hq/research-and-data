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

1. **Inspect the actual inputs.** Read the brief and any existing reference
   notes, then use `view("reference:<n>")` for attached references and
   `view("asset:<id>")` for relevant source assets. Record their actual IDs.
   A filename, tag or palette is insufficient visual evidence. If pixels are
   unavailable, record that limitation rather than describe an imagined image.
2. **Explain the visual job.** In one sentence, connect the imagery to the
   audience, message and intended placement. Choose whether it establishes
   atmosphere, demonstrates a product, or explains an idea. A text-led brief
   can use native composition without a generated image.
3. **Choose an operation.** Reuse/crop for exact source pixels; edit for a
   named change to an existing image; close companion for a related visual;
   new concept for a different subject using the brand's treatment. Mark
   reference roles as identity, subject, treatment or composition. These are
   planning labels, **not additional tool arguments**.
4. **Describe what carries forward.** Name the visible subject, tonal
   relationships, edge character, effect scale and spatial arrangement that
   matter. Separate observations from uncertain interpretations. For a close
   companion preserve subject language and treatment; for a new concept name
   the permitted departure. Relevant originals outrank generic style adjectives.
5. **Plan the layers together.** Set the target aspect, focal region, quiet
   copy region and foreground/background relationship before independent
   generation. Keep exact logos, authentic product UI, marketing copy and
   buttons in separate layers. Native paths/icons are vectors; generated
   illustrations are raster assets even when they look vector-like.
6. **Write a short direction, then act.** Save or update `imagery-direction.md`
   with the visual job, inspected inputs/roles, operation, preserved qualities,
   allowed changes, layer plan, candidate differences and known gaps. Reuse
   it across variants. Prompt for the required image component using those
   observations; let the model resolve artistic details. The current generation
   adapter forwards turn attachments as style references automatically; viewing
   a library image does not attach it. Use the guide's capability checks.

## Self-audit checklist

View each returned image before placement. Compare subject, treatment, tonal
depth, composition and unwanted baked-in content against the selected inputs.
Read dimensions, alpha and generation/fallback evidence when available; an
unverified property remains unknown. Inspect the final native composition too.

For a failed candidate, name the mismatch and change the relevant instruction
or use a supported edit. An identical request can return cached pixels. Preserve
valid alternatives. Stop within the run's existing budget and report missing
requirements honestly. A successful call establishes delivery, not brand fit.
