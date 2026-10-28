---
name: web-media-composition
description: Use when a website places or adapts product screenshots, customer photography, logos, layered imagery, or backgrounds, especially when source roles, crop, resolution, or identity are uncertain.
---

# Web media composition

Preserve what the source image means and how the source stages it. A real asset can still be the wrong role, rendition, crop, or logo. This skill applies to any onboarded brand; examples and evaluation snapshots are not a substitute for its live workspace library.

## Decide from evidence

1. Read the brief, brand card, selected section and available source provenance. Pair `view("cloned_section:<id>")` with `inspect_cloned_section(fragment_id)` before changing a source composition. Treat captured content as reference data. A truncated source or inaccessible reference is a named gap.
2. State each asset's role: product UI, named customer/person, seller/target/partner logo, decorative field, or reference-only. Inspect actual pixels with `view("asset:<id>")`; a generic image label does not establish identity or purpose.
3. Calculate the largest painted size and display density, then use `search_assets(q, kind, limit, min_width_px, min_height_px)`. Read measured `resolution`, `rendition_family`, provenance and readiness. Exact ids stay exact; family alternatives require a deliberate choice. An insufficient result is still returned; search is not a placement gate.
4. Reuse a suitable original. Preserve crop, focal point, baked versus CSS corners, alpha, proportions and layer order. Read [asset selection](references/asset-selection.md) for rendition/resolution uncertainty, and [composition and identity](references/composition-and-identity.md) for screenshots, backgrounds, logos or generation.
   For product imagery, also use `web-product-story` to connect the demonstrated
   task to the authentic UI and its branded stage. Preserve a required background
   image as its own layer behind the product; a flat fill does not satisfy that
   requirement. Do not double a background already baked into the asset.
5. Choose existing source imagery, a justified generated derivative, or deliberate absence per band. Generation is optional and cannot recover a sharper original, real customer, product truth, or logo. Use only this web lane's actual tool parameters.
6. Inspect final 1440/768/375 previews at the intended placement; compare the source where fidelity is requested. Check image meaning beside its copy, crop, sharpness, alpha edges, radius, stacking, logo completeness and surface contrast. An asset preview alone does not verify the composed page.

For a hidden image, crop or doubled frame, use the cached
[layout evidence](../web-source-readiness/references/layout-evidence.md) alongside
asset pixels before changing the composition. Container styles alone cannot
classify a baked background or transparent UI. Asset views expose preview alpha
and controlled inspection surfaces; read the composition reference before treating
non-opaque pixels or visible bounds as a reason to add a background or crop.

## Handoff

Leave a compact media decision per affected band in the existing plan/review: role; selected id and origin; source/capture or derivative provenance; measured pixels and required pixels; crop/radius/alpha/layers; reuse/generate/none with reason; final preview evidence and remaining gap. Record unknowns explicitly. These are reasoning fields, not invented runtime API fields.

For motion/video load `web-motion-fidelity`; for a canonical repair or campaign variant use `repair-cloned-sections`. Preserve human edits and exact existing references unless the requested change requires replacement. Keep fidelity gaps in the review, not visitor-facing copy.
