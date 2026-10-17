# Scene review

Judge the result in this order, before completing the contract below:
1. Does it do what the person asked? Read their actual message again first, not
   your plan.
   - For a revamp, compare with the version you looked at before changing
     anything: the ad must be visibly reworked. If it reads as the old ad with
     one change, the request is not met.
   - For a new direction, judge it as a new ad.
   - A targeted edit doesn't come here; it follows the system prompt's
     targeted-edit routine.
2. Is anything broken: readability, overflow, overlaps, logos, claims and
   evidence? The checks below cover these.
3. Does it match your plan in creative-direction.json? The plan is checked last.
   It can't certify its own choices, and it can't excuse missing the request. If
   your plan and the person's request disagree, the plan is wrong: revise it with
   a revision_reason, validate it, and review again.

The first item in `review_needs` is always the person's request in their own
words. Acceptance requires it to be met.

Judge the current full and compact previews before completing the contract below.
Name the first read, its comfortably readable explanation, and what the artwork
adds. Recognizing known words or deciphering enlarged text is not comfortable
reading. Judge paired-logo authenticity separately from palette, optical weight
and grouping. A native button can be valid while detached from its message.
Lost essential product content, unreadable support or a broken message group
requires rejection and a coherent repair, not an advisory polish warning.

## Candidate critique contract — read before writing

Write `<active round_dir>/critique.json` as one `SceneVisualCritique` JSON object.
This is the canonical candidate contract; legacy callers keep `VisualCritique`.
Required outer fields: `accepted` (boolean), `summary` (string).
Optional outer fields: `issues` (list, default []), `repair_instruction` (string/null),
`acceptance_notes` and `requirement_coverage_notes` (string lists, default []),
`confidence` (0–1 number, default 0), `reference_fidelity` (object/null),
`direction_review` (object/null; required for acceptance).
Each issue: `severity` = `info|warning|error|blocker` (default warning),
`category` = `hierarchy|spacing|alignment|contrast|clipping|overflow|page_dimensions|typography|brand_fit|asset_use|imagery|visual_balance|semantic_slot_coverage|request_satisfaction|compiler_repair|tool_failure`,
`message` and `suggested_repair` (strings), optional `target` (object/null) with
optional `page_id`, `node_id`, `slot_key` (strings/null).
On reference turns supply `reference_fidelity`: `score` (integer 0–3), `reasons`
(string), `regressed_to_house_style` (boolean). Inspect references against current
pixels: 0 ignored, 1 palette only, 2 visual system with missed details, 3 faithful.

`direction_review`: `direction_digest` (current validate_creative_direction result),
`scope` = `whole_creative|scoped_edit` (default whole_creative), `checks` and
`copy_occurrences` (lists, default []). Each check: `section` = `preserve|review_needs`,
`index` (nonnegative integer from the tool's indexed requirements),
`status` = `met|deviation|unverified`, `notes` (nonempty observed reason).
No duplicate section/index checks or duplicate page_id/node_id bindings.
Each copy occurrence: `copy_id` (declared ID), `fragments` (nonempty ordered list),
`support` and `readability` (objects/null). Each fragment has current `page_id`,
`node_id`, exact `text` and `join_before` = `""` or `" "` (default empty).
All fragments in a row belong to one page; repeat rows for repeated placements.
`support`: `status` = `supported|nonfactual|unsupported|unverified`, `evidence_refs`
(list of declared evidence IDs, default []), `reason` and `source_limits` (nonempty),
`source_gaps` (list/null). Each gap: `kind` =
`omitted_necessary_context|added_meaning|unresolved_contradiction`, `reason` (nonempty).
Put `source_gaps` INSIDE `support`, never beside it. `readability`: `status` =
`readable|unreadable|unverified`, `reason` (nonempty placement-specific observation).
Nested direction/copy objects forbid unknown fields. IDs/digest/notes must be nonempty.

A valid, deliberately unverified REJECTED example follows. Replace its digest,
indices, IDs and words with the current tool results; it is not a passing review.
```json
{
  "accepted": false,
  "summary": "Current source support and placement readability still need inspection.",
  "issues": [], "acceptance_notes": [], "confidence": 0,
  "direction_review": {
    "direction_digest": "<current validated direction_digest>",
    "scope": "whole_creative",
    "checks": [{"section": "preserve", "index": 0, "status": "unverified", "notes": "This preserved relationship has not yet been checked in current pixels."}],
    "copy_occurrences": [{
      "copy_id": "headline",
      "fragments": [{"page_id": "square", "node_id": "actual_title", "text": "Make the next step clear", "join_before": ""}],
      "support": {"status": "unverified", "evidence_refs": [], "reason": "Meaning has not yet been compared with available sources.", "source_limits": "Source scope and authority have not yet been inspected.", "source_gaps": []},
      "readability": {"status": "unverified", "reason": "This occurrence has not yet been read in the current placement preview."}
    }]
  }
}
```

Acceptance requires every `preserve` and `review_needs` item exactly once, all `met`.
Bind every declared copy ID and every nonempty native text node in exported pages
using `render_preview`'s complete inventory or `inspect(view="copy_review")`, not
its truncated text-size display. Use actual node IDs, not planned layer IDs.
Ordered fragments must reconstruct the declared words; only whitespace reflow may
vary. Hidden/unreachable text or unresolved binding cannot fulfill visible copy.
Every occurrence needs support `supported` or `nonfactual`, explicit
`support.source_gaps: []`, and readability `readable`. Supported factual copy
must cite evidence declared for that copy block. Unknown source authority may
limit a supported supplied assertion; it cannot excuse added factual meaning.
A rejected review may omit unfinished checks/rows/judgments and retain gaps;
present rows still need valid enums, current exact bindings and declared evidence.
It does not certify the unreviewed remainder. Never turn unverified into met/readable
just to register. Notes, empty gaps and schema validity are not proof of taste/truth.
Whole acceptance also needs clean current preflight, current preview/view and a
current registered accepted critique. A changed scene/direction needs renewed review.
A caller-selected native_copy_review_profile also applies; no score waives a failure.
A targeted edit writes no critique: it follows the system prompt's targeted-edit
routine and finishes with `edit_applied`. Whole-creative `accepted` is for a new ad
or a revamp.
After registration, omit `critique_json` in `finalize_run` to reuse that current review.
If `registered_review_current` is false, resolve `review_error` and renew the
critique after viewing current pixels; a new view alone does not renew review.
Don't repeat the same observation across reports; make each check concrete.
For preflight operation details, read the returned `full_report_path`; diagnostics
remain complete in the immediate result. Continue below for visual/source judgment.

## Visual and source judgment

Judge the actual current rendered scene at full view and final placement size.
Read the supporting sentence in the compact placement preview without referring
back to the larger image or the known copy. If it is only decipherable when
enlarged, mark that occurrence unreadable and repair its resolved size, measure
and contrast. A readable headline does not certify its smaller explanation.
Apply this to every meaningful occurrence, including a kicker, audience callout
and CTA. Judge the compact preview, not the inspector zoom. Reflow into available
space or remove optional copy before accepting text that only reads enlarged.
For paired identities, check that the advertiser is recognizable as the sender;
a target logo must not overpower a shrunken advertiser mark. An authentic asset
can still be an unsuitable variant, scale or surface for this composition.
For a support-size repair, compare that occurrence before and after at the same
viewing scale, and verify that the approved headline and artwork are unchanged.
Then check the hierarchy in the whole composition: does the headline still lead,
or has enlarged support or its CTA become a competing headline? A larger number
does not establish an improvement. Compare against a supplied user correction
when available and retain that design's successful size, measure and grouping;
do not use it as a universal brand or platform rule. Reject both unreadably small
copy and an overcorrection that weakens the intended reading order.
Use `knowledge/scene/components.md` for sizing and dependent reflow.
Review target facts and advertiser capability promises separately. An imperative
or invitation can still add an unsupported promise about coverage, availability,
compatibility or results. Compare each such implication with the actual excerpt;
if absent, record `added_meaning` and reject until sourced or removed. General
positioning, a slogan or industry fit is not evidence for a specific capability.
Check idea/copy, evidence and attribution, hierarchy, readable contrast, brand
identity, authentic product crop, independent editable layers and reference
treatment. Compare the reference's visual invariants against the actual rendered
relationships, not merely matching palette or motif. Read the relevant playbook
and shared resources again if a revision raises a new question; discovery remains
available throughout review. A missing CTA is not a defect when the objective
needs none; a present CTA must have the right next step, brand-supported form,
measured label and readable local contrast. Check placement-specific overlays
through `knowledge/scene/placement.md`, never a universal bottom exclusion band.

Read the composite as a short visual argument: identify its first read, the
support that belongs to it, and what the artwork explains. Headline and support
should read as one message group when the support completes that headline; judge
the visible lines, not unused space in a tall text frame. Check intentional line
breaks and emphasis, then the relationship of this group to imagery and any CTA.
Whitespace earns its place by strengthening hierarchy or reference treatment.
When copy, a corner image and a floating button feel like separate placements,
recompose their relationship using `knowledge/scene/components.md`.

For combined images, name what each contributes and how the combination makes
the message clearer. Test the weaker element by mentally removing it; if meaning
and brand recognition survive and hierarchy improves, simplify. For a metaphor,
name the relationship its visible forms express before reading the explanation
in the direction notes. Attractive shapes without that relationship do not prove
the concept works. Inspect the whole palette at once: independent product pixels
may retain their real colors, while authored type, fields and buttons follow the
selected treatment and explicit user corrections. Use actual supplied preference
context; do not infer that all later runs have learned a saved canvas edit.

Record failures in the existing critique issues and affected direction checks,
with the observed symptom and coherent repair. Preserve source
treatments. A visual repair may require replacing the chosen
concept or removing an optional element; adding decoration does not resolve a
missing visual argument.

For account adaptation, first read the original request and the complete current
feed preview before using the direction's checks as a checklist. State what the
viewer can identify and what useful proposition they can read; then compare that
observed argument with the requested audience/task. A self-authored identity-only
plan cannot narrow a request for account relevance. Matching that plan is not
acceptance evidence for the original brief. Repair the plan and composition when
the direction itself is the cause, using the existing revision/critique fields.

Review advertiser ownership and target identity separately.
Check a requested prominent top advertiser × target group or integrated target
logo/recognizable favicon anchor in the actual reading order. A detached footer
badge does not fulfill that request. Judge optical balance, clear space and the
message relationship, not equal boxes or fixed coordinates. Inspect source scale
and baked-in backgrounds: a magnified favicon or isolated contrast pill may be
authentic yet still weaken the composition. Compare relevant available variants
and the whole identity/message grouping before accepting either treatment.
Each authentic logo and the native separator must remain independently editable;
preserve advertiser
voice, type, palette and approved groups unless a departure was requested.
Candidate preflight adds no advertiser overlay, so evaluate any deliberate
omission against the direction and request; missing required identity is a gap.

Check exact identity against its source and logo pixels against the viewed asset.
A requested × treatment is allowed without a blanket disclaimer or addressing
caption. Co-placement is not evidence for written customer, partner or endorsement
claims. Read artwork and requested companion channel copy as one argument: a name
swap alone does not establish account relevance, and assumed pains, tools or results
cannot become facts. Identity-only is sufficient for an explicitly logo-only or
exact-copy adaptation. For requested audience/use-case relevance, remove the name
and logo mentally: the remaining artwork and requested companion copy must still
connect a supported advertiser capability to the supplied audience or task.
Name that task and mechanism in the review; a team label alone supplies neither
a mechanism nor a reason to act. Keep the target reader distinct from the buyers
that reader wants to reach. For explanatory geometry/artwork, identify the visible
relationship it adds; logos connected by an arrow do not prove a useful workflow.
Research gaps permit a hypothetical invitation, not silently reducing that request
to identity-only. A shared headline is valid when the complete argument does this;
otherwise record the unmet request and repair it, without inventing account facts.
Keep companion copy separately labeled as draft in the existing finalization
summary, outside the image and native-copy inventory; verify its source limits
and report any handoff/review gap without claiming publication. Missing required
proof or ambiguous identity remains a named gap. Revisit `account-adaptation`
for the account argument and `account-identity-composition` for source/composition
handling. Check long names and the complete composition at placement
size; neither a fixed logo row, mandatory CTA nor copy size establishes success.

When expected text or artwork is absent, first locate it in
`inspect(view="page", target=<page_id>)` or `node_tree`, then inspect its and its
ancestors' geometry with `inspect(view="geometry", target=<node_id>)`. Reconcile
the actual parent, child order and resolved placement with the current pixels
before diagnosing color. Managed siblings paint in stored order, later over
earlier; pinned absolute nodes paint in a separate page pass above managed
content, escape ancestor clipping and remain page-clipped. A sibling index is
therefore not a universal paint rank. Consider ancestor clipping, off-canvas
placement, node/ancestor opacity and the placed asset's alpha. The tree/geometry
views do not expose every paint property; when the available current scene and
source evidence cannot establish a cause, mark it unverified. Bounding-box
overlap or a native-text size row alone does not prove occlusion or visibility.
Name the observed absence separately from the supported cause, make any deliberate
repair through checked directives, inspect the resulting tree/geometry, render
and view again. Judge remaining contrast at placement size after visibility is
established; a color-only repair cannot fix confirmed coverage by later artwork.

Preflight validates mechanics, not taste or fidelity. Inspect the image itself;
do not accept because a tool returned success or a previous round looked good.
After a repair, the new scene needs its own render and view. Save the critique
for that round/current scene and name unresolved blockers honestly. A blocker
cannot be explained away as polish. Avoid retrying an identical failed treatment.

The earlier controls provide negative evidence: self-accepted white-on-pale copy,
an unsupported luminous motif, a substituted wordmark treatment, and a product
crop too small to communicate. Each is a distinct failure. Palette similarity,
native editability and valid export do not compensate for those failures.

Follow the runtime critique schema, including typed reference fidelity when the
turn requires it. Only finalize accepted when the current review and preflight
support acceptance; otherwise report a draft or failure and the specific gap.

Use the tool's indexed requirements; cover every `preserve` and `review_needs`
item once. Status is `met`, `deviation` or `unverified`, with a concrete observed
reason. Accepted requires all items met on the current direction and render.
These are your judgments, not automated proof of taste. A score cannot waive an
unresolved requirement, and a narrow repair does not remove whole-creative
requirements. If a different direction is justified within the user's scope,
revise it explicitly with a reason, validate it and review that result; retain
material departures in the final report. A rejected critique may be incomplete
while reporting the specific repairs needed.

Use the complete native-copy inventory returned by `render_preview`, or refresh
it with `inspect(view="copy_review")`. The forty-row text-size display is a
truncated aid, never the inventory. Bind every declared copy ID to current
`page_id`/`node_id` occurrences and exact words. Planned layer IDs may differ
from actual nodes. One row represents one complete occurrence on one page;
repeat the row for each repeated placement. Separately authored fragments are
ordered explicitly; `join_before` is `""` or a single space to reconstruct the
sentence. Only whitespace reflow may differ from the direction. Every nonempty
native text node in the exported pages needs coverage. Hidden and unreachable
text cannot satisfy a visible-copy promise; unsupported instance expansion or
unresolved opacity must remain a gap. A metric limitation such as rotation or
unresolved typography does not establish unreadability: judge its actual pixels.
Text inside authentic product images stays part of visual/source review, outside
this native-copy inventory.

For **every occurrence**, including `claim_kind=positioning`, read the exact
words with their companion copy. Identify subject, action, condition and outcome,
including scope and certainty. Short labels can assert a resource identity,
topic or partnership pairing without a measured outcome.

Compare that meaning with what inspected pixels depict, what supplied text
asserts, and what independent verification, if available, establishes. Catalog
labels/descriptions are supplied assertions; their presence, evidence IDs and
image-byte custody do not authenticate authorship or provenance. Support judges
faithfulness at that source scope, not external truth. A faithful restatement of
a supplied assertion can be supported while its authority remains unknown.

Compare relationships, not matching feature nouns. Depicted controls support
visible affordances; a mandatory hold or release condition needs evidence of
that relationship. Read implied timing, control, causality, availability and
authority before classifying the claim; imperative grammar or absence of a
measured outcome does not make those relationships nonfactual. An advertised resource identity/topic does not require its
unseen body to support that identity/topic. An invitation's language alone
promises neither the resource's language nor current availability; evaluate
those promises when the wording actually adds them.

For quantitative proof, read the number and its visible companions as one claim.
Identify what is measured, about whom or what, compared with what, and any material
unit, time window or condition supplied by the source. Keep the context necessary
to interpret that claim visible together, across native layers or intact authentic
source imagery. Matching values alone does not preserve meaning. Context recorded
only in evidence, assumptions or review notes is not visible qualification. If
necessary context is unavailable, narrow or omit the proof or report the gap;
never fabricate qualifiers to complete the claim.

Record `source_gaps` as a list of `{kind, reason}` assessments before choosing the
support status. Kinds are `omitted_necessary_context`, `added_meaning` and
`unresolved_contradiction`; each reason names the concrete contextual gap.
Use `[]` when the comparison reveals no such gap. A passing status cannot waive
a reported gap: candidate acceptance requires an explicit empty list for every
occurrence. Rejected reviews may retain gaps or omit the unfinished assessment.

Choose the existing support status from this comparison:

- `supported`: factual meaning matches the depicted or supplied assertion scope,
  with no added strength or unresolved contradiction. Cite evidence IDs declared
  for that copy block.
- `nonfactual`: contextual meaning is opinion, advice or invitation with no
  factual identity, relationship or product/empirical promise.
- `unsupported`: the words add a relationship, scope or certainty the source
  does not support, or conflict with the source.
- `unverified`: missing or ambiguous source material prevents deciding whether
  the words faithfully represent it.

Give one concise reason naming the meaning-to-source match or gap. In
`source_limits`, state the depicted, supplied-assertion or independently verified
scope actually available, unknown authority or behavior, and material contrary
observations. Unknown provenance can accompany a supported source-level claim;
a limitation cannot cure words that exceed their source. Inspect supplied
material itself; schema validation does not verify source strings or meaning.

Readability status is `readable`, `unreadable` or `unverified`, with a concise
placement-specific reason covering all fragments of that occurrence. Examine
each occurrence in the existing current full preview and feed proxy, including
overlap, clipping, local contrast and small support/attribution. There is no
universal font-size threshold. Whole acceptance requires complete passing copy
coverage, support and readability, bound to this direction, scene and preview.
An incomplete rejected review can retain partial rows and unresolved judgments.

When direction validation or the native-copy inventory reports a caller-selected
`native_copy_review_profile` / `review_profile`, its viewing assumption is part of
this run's contract. Check each fragment's `nominal_size_review` before accepting.
An unavailable or below-minimum measurement blocks whole-creative acceptance;
recompose, simplify, or remove optional copy through the checked tools and inspect
the updated preview. The compact-feed profile uses a conservative native size
floor at its declared display width. The stricter `legible-feed-v1` profile uses
10px nominal em at 360px display width (30 source px for a 1080px page). It rejects
the formerly accepted 17–25px source labels without imposing one final type size:
hierarchy, font appearance, contrast and wrapping still need judgment.
This is an internal review condition,
not a platform specification, a rendered glyph measurement, or proof that copy is
readable above the floor. It does not measure words inside images. The caller
selects the profile; changing page units, role names or the direction cannot waive
it. Without a profile, evaluate the actual requested viewing conditions visually.
