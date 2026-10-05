---
name: account-identity-composition
description: Use when a scene creative includes a target company logo, advertiser and target pairing, or prominent account-name callout.
---

# Account identity composition

Compose with `account-adaptation` and the selected playbook. An ordinary one-to-one
pitch starts with **advertiser × target** as one identity group. “Big” means both
names are confidently recognizable together, not a giant target tile. An explicit
target-only request uses that treatment. A requested account-name callout, or a
brief permitting a name when a suitable logo is unavailable, uses ordinary native
copy; never imitate a wordmark. Record the chosen treatment in the direction.
Pairing identifies the intended pitch, not a partnership or customer relationship.
The advertiser's references determine the visual system and remaining composition.

## 1. Select original variants and their shared surface

Start with advertiser kit assets and the current workspace's `source_assets.json`.
Search that catalog by the target's name, domain and logo labels; a truncated
opening excerpt is not the complete catalog. Inspect matching original assets
with their `view_target` and provenance before acquiring replacements. Previously
fetched originals and traceable crops remain usable; a prior generated ad is not
logo authority. Then use `fetch_logo(domain, company_name)` for missing or
unsuitable variants. Fetch the exact advertiser too when its kit only has an
unsuitable social avatar.
Inspect returned provenance, missing cells, `cache_hit` and visible identity.
Refresh only under the tool's wrong/outdated-logo condition. `needs_review`
registers nothing. View relevant returned lockups with `view(target="asset:<id>")`;
parent, product, corporate and loyalty-program identities are not interchangeable.
If acquisition fails, check uninspected catalog candidates before declaring the
identity unavailable. A failed fresh fetch does not invalidate stored originals.
Do not repeat equivalent domains after an identity refusal or rate limit, relax
the identity match, or substitute native account text for required paired logos.
Name-only fallback requires permission in the actual request or supplied brief;
the agent's own direction cannot grant it.

Choose variants together on the intended advertiser surface. For a dark restrained
field, compare the authentic reversed target lockup with the advertiser's reversed
lockup first. Use that coherent light-ink pair when both are suitable. Choose a
multicolor treatment when the request or inspected advertiser examples call for
that color emphasis, rather than just because the logo is recognizable. On a
light field, compare suitable positive variants together. Original-asset selection
is not recoloring. If a reversed original is unavailable, keep another authentic
variant that suits the advertiser's field. Change the shared field only when
needed for legibility within the approved treatment; record any unmet variant request.

Inspect actual ink, transparent padding, baked-in plates and resolution. The
white/charcoal asset comparison is inspection only; place the unchanged original.
Prefer complete wordmarks. A supported authentic favicon fallback stays compact;
its frame cannot recover missing detail. A required unavailable exact mark stays
a gap. Never generate, redraw, recolor or stretch a logo, or add a duplicate symbol
beside a full lockup. A plate around one logo does not supply a missing variant.

## 2. For paired intent, build one readable phrase

Choose its location and connection to the message from the advertiser references.
Expand an existing identity region into the pair, rather than adding an unrelated
logo panel. Measure visible wordmark letters, not equal file/frame heights. Source
alpha bounds include symbols and descenders: use them to account for padding,
then compare the actual lettering in the render. Allocate the width each complete
lockup needs at comparable visible letter heights, preserving both aspect ratios.
A long name needs more width; squeezing it into the short mark's width makes its
letters too small. Reduce the whole group to fit rather than shrinking only it.

Use independent advertiser, quiet native `×`, and target nodes. Optically align
the letters on one line, give each authentic mark its clear space, and associate
them closely enough to read together. A constrained format can stack the group
deliberately. Match apparent weight as well as scale: a dense symbol may need less
height. View the pair in the full composition and at detail scale before accepting.

## 3. Compose the message and visual idea together

Size the headline and support as one message group before reserving artwork space.
Support must be a comfortable second read in the compact preview; choose its
measure, resolved type size, wrapping and brand-supported legible ink together.
For a restrained neutral-text reference, use the matching neutral text ink for
headline and support; select an accent for copy only when that emphasis is part
of the inspected treatment. Token availability alone is not that evidence.
Read `knowledge/scene/components.md` for checked layout/measurement.

Treat copy and imagery as dependent regions. Measure the wrapped headline and
support first; place an adjacent artwork region after the support's actual last
line plus the intended breathing room. Recompute that boundary after resizing
either region. An image's pale or transparent-looking pixels still occupy its
whole rectangle: for text-over-image, put the image behind the text and verify
local contrast; for separate regions, keep their content clear. Where a generated
image meets the neighbouring field, decide its edge under
`/.deepagent/skills/generative-imagery/SKILL.md`, or use a deliberate frame or bleed
supported by the references. View their boundary in the composite before accepting it.
Meet the minimum text size as well as visual hierarchy. Its floor
is a rejection threshold, not the final size or proof that every face reads well.

Choose one visual idea that supports the evidenced proposition. An attractive
unrelated product card is not proof of a different workflow. For a new concept,
vary the depicted idea as well as the crop. For a faithful variant or background
replacement, preserve the requested concept and change that layer only. Generate the
separate artwork under `/.deepagent/skills/generative-imagery/SKILL.md`, taking its look
from the advertiser's own imagery; keep original logos, factual product pixels and
native copy independent. A new backdrop
behind the same unrelated card does not make a new concept.

## 4. Bind, render and judge the whole ad

Record surface/variant choice, visible letter-height relationship, support
hierarchy, action decision and visual relevance in the existing direction's
`preserve`, `assumptions` and `review_needs`; no extra schema fields. Bind each
logo's `source_roles` role `logo` to an independent `authentic_image` layer, and
separator/copy to `native_text`. Returned logo IDs are assets, not reference-catalog
entries. Place original IDs in empty leaf frames with `fit="contain"`.
Direction revisions require validation with a reason before use.

Review against the original request and actual full/compact pixels, not only the
self-authored direction. Judge the pair's exact identities, coherent color and
optical weight; then connected message, readable support, meaningful artwork,
preserved advertiser character and honest account argument. A correct pair is
only one check. For paired intent, a plan prescribing an isolated target block
cannot self-approve that mismatch. Preserve explicit target-only/name-only intent.
Repair through checked tools and review fresh pixels under
`knowledge/scene/review.md`. Keep unmet requirements explicit; no automatic logo,
separator, CTA or successful review is supplied by preflight.
