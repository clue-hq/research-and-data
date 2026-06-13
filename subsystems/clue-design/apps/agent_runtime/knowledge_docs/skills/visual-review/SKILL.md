---
name: visual-review
description: Review a rendered Lumen SVG/PNG preview as a user-facing ABM artifact and return a structured VisualCritique — judging hierarchy, spacing, alignment, contrast, clipping, overflow, brand fit, and request satisfaction. Use after a valid preview export.
---

# Visual Review

Judge the rendered preview as a **user-facing artifact**, not a compiler output.
A design that compiles, preflights, and exports can still be unacceptable.

## Inputs to use

Original request and artifact goal · loaded knowledge · scene/page/slot summary ·
compile / preflight / export diagnostics · the SVG text or PNG image · brand-kit
summary. Inspect the actual rendered pixels (PNG) or geometry (SVG) — never
"approve" without looking.

## Accept only when the design

- matches the requested artifact type **and dimensions**,
- communicates the requested message,
- has clear hierarchy and readable typography,
- has enough spacing and coherent alignment,
- has **no clipping or overflow**,
- uses brand styling consistently (tokens, not raw guesses),
- has meaningful semantic slots for future ABM content,
- would be reasonable for a human to inspect and approve.

Do **not** accept just because compile/preflight/export succeeded.

## Common product failures (reject these)

Requested square/custom size but the page/export isn't that size · text outside the
artboard · oversized text overwhelming the composition · CTA/logo/image/copy
collisions · clipped or cropped headings · unclear hierarchy · placeholder visuals
that ignore real asset size · success declared without inspecting the render ·
quoted text with accidental literal newlines · unresolved brand-governance
diagnostics, raw branded surfaces, raw typography in branded scenes, logo misuse,
print/digital mode mismatch.

## Issue categories

`hierarchy` · `spacing` · `alignment` · `contrast` · `clipping` · `overflow` ·
`page_dimensions` · `typography` · `brand_fit` · `asset_use` · `visual_balance` ·
`semantic_slot_coverage` · `request_satisfaction` · `compiler_repair` ·
`tool_failure`.

## Output — `VisualCritique`

```json
{
  "accepted": false,
  "summary": "The headline is clipped and the CTA is too close to the lower edge.",
  "issues": [
    {
      "severity": "error",
      "category": "clipping",
      "target": { "page_id": "page_square", "node_id": "headline" },
      "message": "The headline overflows past the right edge of the canvas.",
      "suggested_repair": "Reduce the headline font size or constrain the text box width; or split into two lines via max_lines(2)."
    }
  ],
  "repair_instruction": "Preserve the current layout direction. Repair the headline width and CTA spacing only.",
  "acceptance_notes": []
}
```

## Review style

Be specific and **target-bound**. The coordinator passes your findings verbatim to
the author, who will repair *surgically* — so name the node/page/slot and give an
actionable, smallest-possible repair. Never say "make it better." If accepted,
still give concise `acceptance_notes` on why it passes. Prefer repairs that change
one named element over anything that implies re-authoring the scene.
