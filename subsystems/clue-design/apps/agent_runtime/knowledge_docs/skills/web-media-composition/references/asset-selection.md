# Asset role, custody and rendition selection

Read this when labels are generic, multiple renditions appear, a pinned asset is blurry, or the intended placement exceeds its source pixels.

## Inputs and evidence

Use the current workspace's brand card/library, the affected source section, observed source URL and capture association, available asset provenance/license/digest, and intended responsive layout. Frozen evaluation files and screenshots are reference evidence; their existence does not register assets or release sections. Never create brand-specific seed packs to make an onboarding gap disappear.

For each candidate, distinguish recorded metadata from your visual inference. Record:

- **Identity and role:** what appears in the pixels, which product/customer/person/company it represents, and where the source used it. A UI avatar is not a testimonial portrait; a customer property photo does not establish an endorsement by another account.
- **Custody:** exact asset id, origin, source URL/capture if exposed, digest, license/usage notes, and original/generated/reference-only status. Missing metadata remains unknown. Do not strip crop queries, fetch guessed originals, or circumvent source and readiness refusals.
- **Placement:** painted width/height at each target viewport, intended density and enlargement/transform, crop/focal point, transparency, source frame and semantic relationship to adjacent copy.

`search_assets` searches label, filename, title, description, usage and tags. A failed semantic query may reflect poor labels. Try observed ids or source/product terms, inspect returned candidates and inventories, then report insufficient retrieval. Do not infer “the brand has no imagery” from one empty search.

## Resolution decision

For a raster painted at W by H CSS pixels at density D, require at least ceil(W × D) by ceil(H × D) usable source pixels. Use the **painted** box for contain sizing, the enlarged source required by cover cropping, and any transform scale. Evaluate each responsive crop at its largest required size. A high-resolution desktop asset may still lose the relevant UI or focal subject on mobile.

Pass those source requirements as `min_width_px` and `min_height_px`; use measured response dimensions, not an optimizer URL's width parameter. For example, a 600 × 400 placement at 2× requires 1200 × 800 source pixels. A 480 × 720 image fails even though it is the family's largest member. Reducing the painted size to a suitable, source-consistent placement can be legitimate; merely increasing CSS dimensions or sharpening it does not add original evidence.

`resolution.meets_requested_pixels` is advisory. False/unknown still returns a record, and `ready` does not mean suitable. Unknown raster dimensions require measurement evidence before a sharpness claim. SVG can scale geometrically, but inspect embedded rasters, missing resources, and small-size legibility; do not apply raster-width arithmetic blindly to vectors.

## Rendition semantics

General searches select the largest ready member of a **proven** same-source family. `rendition_family.matched_asset_id` identifies the member that matched the query. Exact-id queries preserve that exact record and expose alternatives; they are not an instruction to mutate a component's asset reference.

The current grouping recognizes conservative Next optimizer cases. Different inner source/crop parameters, outer non-width parameters, deployment, capture date or aspect ratio remain distinct. Missing family metadata means grouping was not established. Do not merge by filename, apparent similarity, or an assumed original URL. Inspect the preferred rendition as well as its role; more pixels cannot repair the wrong subject or crop.

If inadequate, choose in order: a verified better same-role source; a suitable alternative whose meaning fits the brief; a smaller honest placement; or a recorded acquisition/coverage gap. A source refresh belongs to governed brand-context ingestion. It does not authorize bypassing network/custody gates or silently substituting a generated customer/product image.

## Register using the actual origin

| Result origin | Web tool action |
|---|---|
| `library` | `asset(action="use_library_asset", asset_id="...")` |
| `brand_kit` | `asset(action="use_brand_asset", asset_id="...")` |
| `document` | Already registered; reference the existing id |

Use the returned id in the applicable authoring lane. Typed markup uses `data-asset`; raw fragment composition uses registered `/asset-store/<digest>` references under the custody gate. Load `create-website` or `repair-cloned-sections` for that lane instead of mixing syntaxes. Nonready, source-cap, unreadable-preview or missing-byte results remain gaps; a search hit is not a successful placement.
