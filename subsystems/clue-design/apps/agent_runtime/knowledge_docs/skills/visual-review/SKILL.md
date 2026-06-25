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

The artifact must first be a **valid** preview — non-empty bytes, a real PNG/SVG
header, visible text nodes, recorded dimensions — per `knowledge/export/preview-quality`.
Never review (or accept) an artifact that fails those checks; repair from the export
output instead.

## Measured rubric — walk EVERY check

A `*` check is acceptance-blocking: a single clear failure means `accepted=false`.
Be specific and target-bound on every issue you raise.

- **Centering & alignment** `*` — every label / number / icon inside a button,
  pill, chip, or circle is OPTICALLY centered (roughly equal space on all sides);
  a glyph hugging an edge or sitting high/low is a failure. One alignment spine per
  stack: text left edges line up, no accidental indents; a "centered" block is
  centered as a whole.
- **Spacing rhythm** `*` — gaps consistent and intentional (related items tight,
  separate sections apart); no lone cramped pair beside a huge gap; even rows/columns
  evenly spaced.
- **Hierarchy & focal point** `*` — squint: ONE region dominates first (usually the
  headline); everything else is visibly subordinate.
- **Whitespace / density** — aim ~60–70% whitespace; reject BOTH overcrowding AND
  large dead zones (category `visual_balance`).
- **Contrast & legibility** `*` — no invisible or low-contrast text (light on light,
  dark on dark); readable at its size.
- **Typography** — sensible type scale; nothing oversized-and-overwhelming or too
  small to read.
- **Clipping / overflow** `*` — nothing cut off, off-canvas, or colliding.
- **Avoid AI clichés** — generic tinted eyebrow pills, blue→purple gradients,
  low-opacity circles behind everything, everything-boxed-in-cards. Prefer
  information on surfaces, scale contrast, asymmetry.
- **Request & brand** — matches the requested artifact type AND dimensions,
  communicates the message, covers the requested concepts; brand styling consistent
  (tokens, not raw guesses); meaningful ABM slots. Unresolved brand-governance
  diagnostics, raw branded surfaces, raw typography in branded scenes, logo misuse,
  and print/digital mode mismatch are quality failures even when the render is neat.
  For the full brand-rejection rubric (when does a branded design fail brand fit, and
  the concrete token repairs) see `knowledge/design-systems/brand-fit-critique`.

Do **not** accept just because compile/preflight/export succeeded, and never approve
without inspecting the rendered PNG.

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
