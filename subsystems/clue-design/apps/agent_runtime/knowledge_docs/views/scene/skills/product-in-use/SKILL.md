---
name: product-in-use
description: Use when an ad should show a credible person, team or task using the product in context, beyond an isolated screenshot or packshot.
---

# Product in use

Show the product doing a job in a recognizable situation. The context should
explain who it helps and when it belongs, not merely decorate the product.
Use authentic-product for an isolated demonstration; use case-study-narrative
when a real customer's experience and outcome are central. A stock meeting photo
beside a dashboard does not by itself establish use.

## Establish what the scene represents

Choose a supported user role, task, environment and visible product action.
Classify the scene as authentic customer evidence, an approved demonstration, or
an illustration. Keep that classification in the direction record. Product
capability evidence supports what the product does; it does not establish that a
depicted company or person uses it. Generated people and invented environments
must not acquire a customer's name, quote or implied endorsement.

Inspect the authentic product source before staging it. Check device, viewpoint,
interaction and scale: the person must plausibly see or reach the feature shown.
For software, identify the meaningful task state rather than showing a generic
home screen. For physical products, keep important form, packaging and operation
consistent with the actual source. Missing interaction imagery may call for a
separate product-and-context composition rather than a fabricated documentary view.

Inspect relevant company ads for the relationship between human activity and
product visibility: is the product central, a quiet enabler, or a readable inset?
Study crop, gesture, light, material, tone of copy and logo/CTA treatment. Record
observable preserve/vary choices in the per-run `creative-direction.json`, following
`knowledge/scene/references.md`; another
brand's office setting is not a universal B2B aesthetic. If no campaign pixels are
available, record the evidence gap and treat the result as a kit-derived direction.

## Compose around the use moment

State the supported use moment in one sentence: who is doing what with which
visible product state. Choose the asset that carries that moment. Add a companion
only when it clarifies something the leading asset cannot show. Name the visible
connection: attention or gesture toward the task, a credible device interaction,
or an explanatory inset tied to the same action. Sharing a frame does not connect
an office portrait to a product crop. If the sources cannot establish an interaction,
keep the scene illustrative and make the explanatory relationship clear; remove
context that adds no task meaning. Record this relationship in `preserve` and
`review_needs`, rather than merely requiring both assets to appear.

- **Task at the center:** an authentic or clearly illustrative use scene leads;
  native copy names the task and a small independent product detail clarifies the
  mechanism. Useful when the situation carries the idea immediately.
- **Product with context:** a large intact product source sits beside a cropped
  contextual image or native task cues that explain the same use moment. Give the
  product and its explanation distinct emphasis; an additional image is optional.
  Useful when the interface needs a frontal readable view.
- **Handoff between roles:** separate authentic product states or native task
  labels show one participant's action reaching another. Useful when coordination
  is the value; keep the cast and number of states small enough for one read.

Select an approach from the intended task and sources, without compulsory people,
device mockups, desk props or equal-width panels. Protect the leading action and
the detail that explains it when cropping or resizing. Compare the combined
palette, tonal contrast, lighting and edges with the approved brand and chosen
references. Harmonize authored surroundings or choose more compatible imagery;
preserve authentic product pixels. Native copy explains the useful moment;
invented elapsed time and guaranteed outcomes add no credibility.

## Construct and verify

Follow `knowledge/scene/components.md`: headline, support, task labels and any CTA
stay native; logo, product and setting remain independently placeable. Reuse
approved use photography when suitable. When new imagery is requested, generate
the contextual layer under `/.deepagent/skills/generative-imagery/SKILL.md` (product scene), inspect it, then
combine with authentic product pixels. Do not ask generation to recreate exact UI,
logos or a named customer's real event. Unsupported perspective or occlusion is
a reason to simplify the composition, not invent invisible editing capabilities.

Use `knowledge/scene/placement.md` to adapt square and portrait around the meaningful
action, preserving hands, product detail and readable copy. Review the whole image:
can the viewer connect the person or context to the specific product task? If
removing a companion leaves that meaning unchanged, simplify or replace it.
Check physical plausibility and factual product fidelity. If the task is
unsupported, change to a supported demonstration and record the missing-use
evidence. Choose the next-step CTA only when the destination and
campaign purpose warrant it.
