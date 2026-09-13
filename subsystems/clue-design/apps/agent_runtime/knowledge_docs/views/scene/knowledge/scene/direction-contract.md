# Creative direction record (schema version 1)

Write one compact JSON record to the run workspace's `creative-direction.json`.
Use `validate_creative_direction()` before delegation/authoring. This is the
shared handoff; do not repeat it in separate creative/imagery/reference briefs.
Round `direction.md` can refer to it and contain only the repair delta.

Required fields:

- `schema_version`: 1; `objective`, `audience`: concrete strings.
- `playbook`: one ID from this view's playbook catalog; `intent`: `native`,
  `reuse`, `edit`, `close_companion`, `new_concept` or `palette_only`.
- `copy`: list of `{id, role, text, claim_kind, evidence_refs}`. New creatives
  need copy; an `edit` intent may use an empty list for a logo/geometry-only change. Roles
  are headline/support/cta/attribution; claim kind is positioning/assertion/quote/
  statistic. Assertion/quote/statistic needs evidence IDs. CTA is optional.
- `evidence`: list of `{id, source, excerpt}`. Point to supplied or actually
  retrieved evidence. These are provenance references, not invented proof.
- `source_roles`: list of `{asset_id, role}`. Role is source/treatment/composition/
  logo/product; asset IDs must be available in this run's sources.
- `preserve`, `vary`: string lists of visible properties; no contradictory entry.
- `layers`: list of `{id, kind, purpose, placement, ...}`. Kinds are native_text,
  native_geometry, authentic_image, generated_image. Native text binds `copy_id`;
  every copy block needs a native text layer. Authentic images require `asset_id`
  in source_roles. Generated layers can name ordered `reference_asset_ids` and
  aligned `reference_roles` (source/treatment/composition, at most four).
- Each layer's `placement`: `{x, y, width, height, fit}` as fractions of the
  artboard within 0..1; fit is contain or cover (default contain). The author
  translates these into artboard layout points; these are intent, not locked boxes.
- Artboard `placement`: `{width, height, unit}` with unit px/pt/mm/in.
- `review_needs`: nonempty list of specific checks; `assumptions`: concise list.

Keep real logo/product images independent; generated conditioning cannot certify
their exactness. An authentic-product direction needs a real product image.
An attributed-proof direction needs sourced quote/statistic and attribution.
The validator checks structure, references and available assets. It cannot prove
truth or visual quality. Review sources and the final composition.
