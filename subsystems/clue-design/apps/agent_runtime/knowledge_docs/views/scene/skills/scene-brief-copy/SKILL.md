---
name: scene-brief-copy
description: Use when a new scene creative or ad is requested, including short requests with no supplied headline, campaign concept or CTA.
---

# Brief and copy

Read the user request, brand card, available evidence and asset inventory in one
gather. Shortlist two to four useful images from the inventory and view them
together before choosing a treatment; broaden only to resolve a named gap. Derive the
audience, single useful message, medium and appropriate action from this context.
For “make an ad,” choose a 1080 square awareness creative unless supplied context
implies another placement. Do not ask the user to become the copywriter.

Write one original headline and only the support needed to make it intelligible.
Prefer concrete product meaning to vague promises. Use provided claims accurately;
quotes, numbers and customer attributions need actual evidence. Keep source IDs
with factual copy. Missing proof is a reason to choose a positioning direction,
not to invent results. Optional CTA: omit it for awareness when the placement
already supplies an action; a proof or workflow story also need not end in a button.

Select one playbook by communicative job:

| Need | Playbook |
|---|---|
| A clear product position, category or point of view | type-led-positioning |
| The real interface or object explains the product | authentic-product |
| A supplied result or quote is the message | attributed-proof |
| A sourced before/after or process makes the value clear | workflow-contrast |

Read only the selected playbook. These are starting choices, not a template menu.
Already loaded shared guides need no second read through a wrapper skill. If the
user asks for new imagery or variants, carry that requirement into generated
layers and inspect the actual outputs; reusing an old image or substituting a
native flat field does not satisfy a new-artwork request.
If its evidence or assets are unavailable, pick a supportable direction and note
the limitation; ask only for a missing decision that makes the requested result
impossible. Preserve exact copy when the user supplies it; don't rewrite control
inputs to make the composition easier.

Write `/run_<id>/workspace/creative-direction.json` using
`knowledge/scene/direction-contract.md`, then call `validate_creative_direction()`.
Record concise assumptions there rather than asking routine aesthetic questions.
If validation refuses, repair the named fields; never proceed on an invalid
handoff. Give the author this record inline and its workspace path.
