# Creative direction record (schema version 1)

Write one compact JSON record to the run workspace's `creative-direction.json`.
Use `validate_creative_direction()` before construction. This is the shared
direction record; do not repeat it in separate creative/imagery/reference briefs.
For a required authentic target logo on a pageless scene, only explicit page
dimensions may be compiled first as source preparation. Fetch and view the real
logo, then include its returned registered ID in the first complete direction.
Creative nodes and new imagery spend still require validated direction.
Round `direction.md` can refer to it and contain only the repair delta.
The tool returns the direction digest and indexed review requirements. Carry
that result into current-scene review. A semantic revision after validation uses
`validate_creative_direction(revision_reason="what changed and why")`; the new
direction needs fresh review. Reformatting the same JSON is not a revision.

Required fields:

- `schema_version`: 1; `objective`, `audience`: concrete strings.
- `playbook`: one registered ID from `knowledge/scene/catalog.md` or the discovered
  skill metadata. The catalog derives from skill descriptions; new registrations
  need no Python enum change. `intent`: `native`,
  `reuse`, `edit`, `close_companion`, `new_concept` or `palette_only`.
- `copy`: list of `{id, role, text, claim_kind, evidence_refs}`. New creatives
  need copy; an `edit` intent may use an empty list for a logo/geometry-only change. Roles
  are headline/support/cta/attribution; claim kind is positioning/assertion/quote/
  statistic. Assertion/quote/statistic needs evidence IDs. A quote also requires
  an attribution copy block sharing its evidence ID. CTA is optional.
- `evidence`: list of `{id, source, excerpt}`. Point to supplied or actually
  retrieved evidence. These are model-authored source descriptions, not
  independently verified evidence handles. Record limiting/contrary evidence
  honestly; a screenshot of controls does not establish a universal product rule.
- `source_roles`: list of `{asset_id, role}`. Role is source/treatment/composition/
  logo/product; asset IDs must be available in this run's sources.
- `preserve`, `vary`: string lists of visible properties; no contradictory entry.
  Resolve source/kit differences here before authoring. Compare the actual
  supplied color values, including `brand_colors.json` when needed, with the
  observed treatment. Name deliberate departures in `vary`/`assumptions` and
  leave an unavailable required treatment as a gap. A near-white promise with a
  visibly gray chosen fill is a conflict, even when its token is valid.
- `layers`: list of `{id, kind, purpose, placement, ...}`. Kinds are native_text,
  native_geometry, authentic_image, generated_image. Native text binds `copy_id`;
  every copy block needs a native text layer. Authentic images require `asset_id`
  in source_roles. Generated layers can name ordered `reference_asset_ids` and
  aligned `reference_roles` (source/treatment/composition, at most four).
- Each layer's `placement`: `{x, y, width, height, fit}` as fractions of the
  artboard within 0..1; fit is contain or cover (default contain). Translate
  these into artboard layout points; these are intent, not locked boxes.
- Artboard `placement`: `{width, height, unit}` with unit px/pt/mm/in.
- `review_needs`: nonempty list of specific checks. The first item is the person's
  request in their own words. `assumptions`: concise list.

Keep real logo/product images independent; generated conditioning cannot certify
their exactness. Select evidence and product sources according to the chosen
family and actual message. Registered evidence prerequisites are data in the
scene manifest: authentic-product requires an independent supplied product image;
attributed-proof requires sourced quote/statistic and attribution linked to that
proof. These prerequisites apply to new work and edits. Retain the relevant
unchanged proof/source bindings in this direction during a narrow repair; the
round delta names which existing components to mutate. Including unchanged
attribution in the direction does not authorize a collateral change. Intent=edit
alone never permits missing required evidence. Other unchanged components may be
omitted when their evidence and bindings are not needed for the selected work.
Visible proof still needs honest qualification and attribution; a family name
cannot certify evidence. A statistic's metric and necessary subject, comparison
and qualifying context must survive in the visible layers, not only this record.
Do not invent context the source does not supply. Revisit the relevant skills at any stage and amend
this same record explicitly if the copy, intent, sources or layer plan changes.
Call the same validator after a revision, before using the changed record. It checks structure, references, available assets and registered
evidence prerequisites, not a family-specific layout or a required CTA. It cannot prove
truth or visual quality. Review sources and the final composition.

Whole-creative review binds this declared copy to the actual exported native
text inventory, including repeated and separately authored occurrences. Planned
layer IDs need not equal final node IDs. If the authored words change beyond
whitespace reflow, revise this record with a reason before reviewing. The
`positioning` label exempts no sentence from support review: implied product
promises require evidence too. Follow `knowledge/scene/review.md` for occurrence
bindings, support/source limits, explicit `source_gaps` assessment, placement
readability and scoped edit review. Passing candidate review requires
`source_gaps: []`; recording a gap while labeling copy supported or nonfactual
does not resolve it.
