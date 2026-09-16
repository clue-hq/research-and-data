---
name: account-identity-composition
description: Use when a scene creative includes a target company logo, advertiser and target pairing, or prominent account-name callout.
---

# Account identity composition

Compose with `account-adaptation` and the chosen playbook. For an ordinary
one-to-one pitch, start with **advertiser × target**: two authentic independent
marks and a native separator, composed as one identity group. The advertiser's
references supply the visual language. Choose the treatment before allocating
headline, artwork and whitespace:

- **Advertiser × target** is the default when both identities are available. Place
  the group near the start of the reading order, connected to the message. “Big”
  means both identities are confidently recognizable within this group.
- **Target only** follows an explicit target-only request or a deliberately chosen
  reference-led account callout. Keep advertiser voice and account relevance;
  record that choice rather than accidentally losing the advertiser.
- **Account-name callout** uses ordinary native copy when explicitly requested or when
  the brief permits a name instead of an unavailable suitable logo. Never imitate a wordmark with type.

These treatments do not fix the rest of the layout. An identity pair is an
account-directed pitch, not evidence of a partnership, endorsement or customer
relationship. Write the message accordingly; no automatic disclaimer is needed.

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
label cannot prove the requested identity: parent, product, loyalty-program and
corporate marks are not interchangeable. Verify the visible name against the brief.

Choose variant and surface together. Inspect ink, transparency, baked-in background,
aspect and resolution. A favicon can be a compact anchor under the tool's fallback
conditions; enlargement into a hero tile cannot recover detail. Prefer a suitable
complete lockup. With only a compact mark, compose at its supported scale and let
copy carry prominence. Use an allowed name callout when no suitable logo exists;
a required exact mark remains a gap needing a supplied asset.
`needs_review` registers nothing. Never redraw, recolor, stretch or generate marks.
Inspect the advertiser as carefully as the target: a square social avatar with a
baked-in tile is not a transparent wordmark. Fetch a suitable original when needed.
Do not add a detached symbol beside a complete lockup that already includes it.

## Compose the pair, then the ad

1. **Start from advertiser references.** Choose the group's location, surface and
   approximate prominence from an appropriate ad. Establish one shared alignment
   with the message. If the reference has a single advertiser mark, expand that
   identity region into a pair; do not add a second unrelated logo panel.
2. **Measure the artwork, not the file.** View both original assets and note the
   visible wordmark bounds inside each image. Start with comparable visible letter
   heights, preserving each aspect ratio. A wide name needs more width; a tall or
   dense symbol needs less height to feel equally prominent. Source padding and
   unequal aspect ratios make equal-size frames misleading.
3. **Build a compact horizontal group.** Advertiser, native `×`, target each gets
   its own node. Optically center the marks and separator on one line. Give both
   marks their required clear space; make the separator quieter than either mark.
   Size the whole group together until both names read at feed size. Prefer a
   complete wordmark at a comfortable size over a giant icon. A constrained format
   can use a deliberate stacked group with the same balance and close association.
4. **Connect identity to the idea.** Place headline and readable supporting copy as
   one message group; use the remaining field for relevant artwork or purposeful
   whitespace. The pair identifies the pitch; the headline carries its value. A
   single target mark filling the header while the advertiser sits elsewhere is a
   different treatment, even when both logos technically exist.
5. **Check the silhouette before detail.** View the full composition at feed size.
   Can you read advertiser, separator and target as one phrase, then the message?
   If one mark dominates, adjust its visible scale or choose another authentic
   variant; if the group feels detached, fix alignment/proximity. Preserve source
   pixels and brand clear space while changing layout, not the logos themselves.

Choose variant and field together. A contrasting region should include the group
and connect to the message, not become an isolated pill around one mark. The target
logo's available variant must not dictate the advertiser's entire palette. Keep
images, vector motifs and textures relevant to the chosen playbook; the pair alone
does not require extra decoration or a CTA.

## Keep identity editable and verify the result

Returned IDs are scene assets, not new opening reference-catalog entries. Bind
each to `source_roles` role `logo` and an independent `authentic_image` layer.
Bind callout/native separator text to `copy` and `native_text` layers. Record
grouping in layer `purpose`, `preserve` and `review_needs`. Direction changes require
`validate_creative_direction(revision_reason=...)` before use. Place into its own
empty leaf frame/image node with
`asset(action="place", asset_id=..., node_id=..., fit="contain")`.

## Review against the request, not just the authored direction

Compare the first rendered delivery with the original request and this treatment:
- Paired intent: advertiser, separator and target read as one balanced group.
- Identity fidelity: exact requested companies and suitable authentic variants;
  no accidental parent/product/loyalty-program substitution or duplicate symbol.
- Composition: clear reading order, readable supporting copy, connected identity
  and message, intentional use of remaining space and advertiser palette.
- Meaning: relevant account pitch backed by actual advertiser capabilities;
  pairing does not introduce a relationship claim.

View both the full feed preview and logo detail. Actual recognition, contrast,
clearspace and source fidelity decide success; valid placement and authentic pixels
alone do not. For paired intent, a direction that prescribed a giant isolated target block
cannot self-approve that mismatch. Judge deliberate target-only and name-only
treatments against their own request instead of converting them into a pair. Repair the direction and composition together through
checked tools, then review again. Follow `knowledge/scene/review.md` and preserve
unresolved gaps. Preflight inserts no advertiser logo or separator automatically.
