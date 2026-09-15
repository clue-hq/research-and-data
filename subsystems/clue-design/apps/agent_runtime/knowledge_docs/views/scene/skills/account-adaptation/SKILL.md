---
name: account-adaptation
description: Use when scene creative addresses a named target company, adapts an approved ad for an account, or requests account-specific variants.
---

# Account adaptation

Compose this supporting skill with the selected communicative playbook; keep that
family in `playbook`. Read `knowledge/scene/direction-contract.md` and use the
existing direction record, without adding account fields or opaque research IDs.

Separate the context before writing:

- Advertiser: who speaks, with its approved kit, product evidence and voice.
- Target identity: the exact company name/domain and the supplied or retrieved
  source that identifies it. An ambiguous name needs a specific identity gap,
  not a guessed company/domain or logo.
- Account facts: only what supplied or actually retrieved evidence says about
  that target. Metadata and a logo do not establish its needs, stack or results.
- Persona/use-case hypothesis: a proposed audience or relevance angle, recorded
  as an assumption, not an established account fact.
- Campaign intent: the message and real next step this creative should serve.
- Relationship evidence: what supports any customer, partner or endorsement
  statement. Co-placement and visual similarity establish no relationship.

Put actual source descriptions/excerpts in `evidence` and bind factual `copy`
through `evidence_refs`. Bare claim IDs without accessible values/evidence cannot
support copy. A supplied name/domain can support an identity-specific invitation;
record in `assumptions` that personalization is identity-only when account research
is absent. Keep hypothetical relevance out of factual claims. Missing required
proof belongs in `review_needs`; narrow the argument or report that concrete gap.
Account relevance needs an argument beyond a name swap. Carry it in artwork
copy, requested companion channel copy, or both, within the available evidence.

When adapting approved creative, inspect its current scene with page/node/geometry
queries and view its render. For variants, put the advertiser kit, effective type,
palette and successful message/artwork groups in `preserve`, with intended changes
in `vary`. A user-approved size belongs to that inspected composition; never
transfer it to another brand as a default. Recompose and
remeasure for longer target names or different images without losing the intended
reading order. Vary messaging only when evidence changes the argument.

Choose the identity treatment from campaign intent, supplied direction and
relevant examples. Two supported options are an advertiser × target group near
the top, or a target logo/recognizable favicon integrated as a primary identity
anchor. Make that identity belong to the message; a detached footer badge does
not fulfill a requested prominent treatment. These are flexible choices, not
mandatory templates or fixed coordinates. Balance visible logo ink optically,
with authentic variants and clear space; equal boxes do not imply equal weight.
Keep each logo independently placeable and replaceable, with a native text or
geometry separator. Preserve the advertiser's voice, palette and visual system
unless a deliberate departure is requested. A requested × group is allowed
without a forced disclaimer or addressing caption. It does not support written
customer, partner or endorsement claims. CTA presence follows the actual next
step; an awareness ad need not have one.

For a target logo, use `fetch_logo(domain, company_name)` after a page/artboard
exists. On a pageless scene, first compile only explicit page/artboard dimensions
as source preparation, then fetch and view before the first complete direction.
Creative nodes and new imagery spend wait for validated direction. Inspect the
returned identity, `cache_hit`, provider/source
evidence, missing cells and failures. Honor cached provenance; refresh only for
the tool's wrong/outdated-logo condition. View the actual returned ID using
`view(target="asset:<asset_id>")`. Choose the suitable complete `*_lockup` for
the surface first; a recognizable returned mark/favicon can suit the deliberate
target-anchor treatment, but cannot replace an explicitly required wordmark.
Honor the tool's fit/availability rules. Never recolor, stretch, recreate or
generate a company mark, or flatten both marks into a fabricated combined logo.

Successful returned IDs are registered in the current scene's assets and are
valid `source_roles` with `role="logo"`, bound to independent `authentic_image`
layers. They are not newly added to the opening `source_assets.json` or numbered
reference catalog. Use their returned IDs directly; invent no asset/reference IDs.
Validate before composition; if a direction was already validated, revise it with
a reason and validate again before using the added source.
Use layer `purpose` and `preserve`/`vary` to describe the identity relationship;
put its unresolved source/composition checks in `review_needs`. Candidate
preflight does not add an advertiser logo: author and reviewer own that choice,
including any deliberate omission. A missing required mark remains a gap.
Place it in its own empty leaf frame/image node through
`asset(action="place", asset_id=..., node_id=..., fit="contain")`; inspect the
result. `needs_review` registers nothing. An unavailable or unsuitable logo permits
a named text-only treatment when the request allows it; a required exact logo
remains a gap needing a supplied asset.

The direction's `copy` contains only native artwork text, including a text
separator. When companion channel copy is requested, keep it out of the image
and direction schema. Include it as a separately labeled draft in the existing
`finalize_run` summary alongside the honest creative status; a loose final chat
message or file alone may not reach the handoff. Apply the same source limits
to that draft. Never report it published or claim delivery through an unreviewed
or failed handoff; name the remaining review gap.

Review the complete argument under `knowledge/scene/review.md`: exact identity,
relationship implications, evidence-scoped copy, placement-size reading order,
logo pixels, independent editable layers and every preserved property. Keep
unresolved checks explicit. Engine audience/slot operations are primitives;
this skill provides neither a connected account picker nor all-account content
scaling. Report only the variants actually made and reviewed.
