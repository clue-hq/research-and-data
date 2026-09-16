---
name: account-identity-composition
description: Use when a scene creative includes a target company logo, advertiser and target pairing, or prominent account-name callout.
---

# Account identity composition

Compose with `account-adaptation` and the chosen playbook. Keep advertiser visual
language while choosing identity for this brief:

- **Advertiser × target:** independent authentic marks, native separator, optical
  balance and clear space. Honor a requested top group.
- **Target only:** integrate its identity with message/artwork; preserve advertiser
  voice without forcing its logo back in.
- **Account-name callout:** ordinary native copy in the message hierarchy, never a
  typeset imitation wordmark.

These are choices, not templates. A requested pairing needs no automatic
disclaimer; customer, partner and endorsement claims still need evidence.

## Inspect candidates, then choose the surface

Use advertiser kit assets and `fetch_logo(domain, company_name)` for the target.
If the advertiser kit supplies only an unsuitable favicon, use the same service
for its exact identity too. Do not make an authentic but illegible advertiser
mark smaller merely to hide its background or mismatch with another logo.
If pageless, compile only page dimensions, fetch and view, then validate the
complete direction before creative nodes or imagery spend.
Inspect source provenance, `cache_hit`, missing cells and identity; refresh only
under the tool's wrong/outdated-logo condition. View the suitable returned
`*_lockup` first with `view(target="asset:<asset_id>")`. Compare relevant returned
alternatives when that cell is unsuitable, recording why. The filename or cell
label cannot prove that a parent-company logo identifies the requested product.

Choose variant and surface together. Inspect ink, transparency, baked-in background,
aspect and resolution. A favicon can be a compact anchor under the tool's fallback
conditions; enlargement into a hero tile cannot recover detail. Prefer a suitable
complete lockup. With only a compact mark, compose at its supported scale and let
copy carry prominence. Use an allowed name callout when no suitable logo exists;
a required exact mark remains a gap needing a supplied asset.
`needs_review` registers nothing. Never redraw, recolor, stretch or generate marks.

## Build one visible group

Judge visible ink rather than equal frames. Align optical centers or baselines,
tune scale for dense versus slender marks, then clear space and separator weight.
Connect identity and message through alignment, proximity or meaningful artwork.
At feed size, identify who is speaking without consulting the brief. A target
wordmark must not overwhelm the advertiser in a paired treatment. Compare visible
ink and recognition, not just frame dimensions or nominal scale.

Try a suitable authentic variant on the intended field. A required contrasting
field should connect identity and message through its extent, alignment and
spacing. An isolated pill can look like an unrelated badge. Reconsider field and
grouping before adding a plate; preserve source backgrounds and mark proportions.
The target's available logo variant must not dictate the advertiser's entire
palette. Try another authentic variant or a coherent identity region before
turning the target into a dominant isolated capsule.

## Keep identity editable and verify the result

Returned IDs are scene assets, not new opening reference-catalog entries. Bind
each to `source_roles` role `logo` and an independent `authentic_image` layer.
Bind callout/native separator text to `copy` and `native_text` layers. Record
grouping in layer `purpose`, `preserve` and `review_needs`. Direction changes require
`validate_creative_direction(revision_reason=...)` before use. Place into its own
empty leaf frame/image node with
`asset(action="place", asset_id=..., node_id=..., fit="contain")`.

View the full feed preview: recognizable account, intended reading order, one
coherent ad. Inspect logo detail for blur, padding, contrast and source fidelity.
Authentic pixels and valid placement alone do not pass this judgment. Follow
`knowledge/scene/review.md`; preserve unresolved gaps. Preflight inserts no
advertiser logo, so review omissions against the brief.
