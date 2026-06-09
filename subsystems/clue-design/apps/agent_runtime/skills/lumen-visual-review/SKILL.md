---
name: lumen-visual-review
description: Use when reviewing Lumen SVG or PNG previews for visual quality, request satisfaction, brand fit, clipping, overflow, spacing, hierarchy, and repair instructions.
---

# Lumen Visual Review

Use this skill to review rendered Lumen previews. The design must be judged as
a user-facing ABM artifact, not as a compiler artifact.

## Review Inputs

Use all available context:

- original user request
- artifact goal
- loaded knowledge snippets
- scene/page/slot summary
- compiler diagnostics
- preflight diagnostics
- export diagnostics
- SVG/PNG preview artifact
- brand-kit summary or notes

## Acceptance Rule

Accept only when the design:

- satisfies the user's stated artifact type and dimensions
- communicates the requested message
- has clear hierarchy
- has readable typography
- has enough spacing
- has no clipping or obvious overflow
- has coherent alignment
- uses brand styling consistently
- has meaningful semantic slots for future ABM content
- would be reasonable for a human user to inspect and approve

Do not accept a design only because compile/preflight/export succeeded.

## Issue Categories

Use these categories:

- `hierarchy`
- `spacing`
- `alignment`
- `contrast`
- `clipping`
- `overflow`
- `brand_fit`
- `visual_balance`
- `semantic_slot_coverage`
- `request_satisfaction`
- `compiler_repair`

## Common Product Failures

Watch for the failures observed in early Lumen demos:

- requested square or custom dimensions but the actual page/export is not that
  size
- text runs outside the artboard
- large text overwhelms the composition
- CTA, logo, image, or copy collides with another element
- headings are clipped or cropped
- hierarchy is unclear
- design uses placeholder visuals without accounting for actual asset size
- model declares success without inspecting the rendered result
- quoted text includes accidental literal newlines or unsupported syntax

## Output

Return structured critique in this shape:

```json
{
  "accepted": false,
  "summary": "The headline is clipped and the CTA is too close to the lower edge.",
  "issues": [
    {
      "severity": "error",
      "category": "clipping",
      "target": {
        "page_id": "page_square",
        "node_id": "headline"
      },
      "message": "The headline overflows past the right edge of the canvas.",
      "suggested_repair": "Reduce the headline font size and constrain the text box width, or split the headline into two lines."
    }
  ],
  "repair_instruction": "Preserve the current layout direction. Repair the headline width and CTA spacing only.",
  "acceptance_notes": []
}
```

If accepted, still include concise `acceptance_notes` explaining why it passes.

## Review Style

Be specific and direct. The coordinator will pass your findings verbatim to the
DSL author. Avoid vague comments such as "make it better." Give actionable
repairs tied to visible issues and likely node/page targets when possible.
