# Scene review

Judge the actual current rendered scene at full view and final placement size.
Read the supporting sentence in the compact placement preview without referring
back to the larger image or the known copy. If it is only decipherable when
enlarged, mark that occurrence unreadable and repair its resolved size, measure
and contrast. A readable headline does not certify its smaller explanation.
For a support-size repair, compare that occurrence before and after at the same
viewing scale, and verify that the approved headline and artwork are unchanged.
Then check the hierarchy in the whole composition: does the headline still lead,
or has enlarged support or its CTA become a competing headline? A larger number
does not establish an improvement. Compare against a supplied user correction
when available and retain that design's successful size, measure and grouping;
do not use it as a universal brand or platform rule. Reject both unreadably small
copy and an overcorrection that weakens the intended reading order.
Use `knowledge/scene/components.md` for sizing and dependent reflow.
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
with the observed symptom and coherent repair. Preserve successful user-edited
groups and source treatments. A visual repair may require replacing the chosen
concept or removing an optional element; adding decoration does not resolve a
missing visual argument.

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

The candidate critique also carries `direction_review`:

```json
{"direction_digest":"<returned by validate_creative_direction>","scope":"whole_creative","checks":[
  {"section":"preserve","index":0,"status":"met","notes":"What the current pixels show"},
  {"section":"review_needs","index":0,"status":"deviation","notes":"The retained treatment is still missing"}
],"copy_occurrences":[{
  "copy_id":"headline",
  "fragments":[{"page_id":"square","node_id":"actual_title","text":"Make the next step clear","join_before":""}],
  "support":{"status":"nonfactual","evidence_refs":[],"reason":"An invitation, with no empirical product promise.","source_limits":"No product behavior is asserted.","source_gaps":[]},
  "readability":{"status":"readable","reason":"All words are legible at this placement in the current full preview and feed proxy."}
}]}
```

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
the updated preview. The current compact-feed profile uses a conservative native
size floor at its declared display width. This is an internal review condition,
not a platform specification, a rendered glyph measurement, or proof that copy is
readable above the floor. It does not measure words inside images. The caller
selects the profile; changing page units, role names or the direction cannot waive
it. Without a profile, evaluate the actual requested viewing conditions visually.

For a seeded, validated `intent=edit` turn, `scope="scoped_edit"` may review only
the named edit and relevant copy, retaining unchanged unrelated text. Keep the
existing target/operation scope checks and report collateral changes. A passing
scoped review can support `edit_applied`; it never permits final `accepted` or
claims to certify the whole creative. Reuse the registered current critique in
`finalize_run` by omitting `critique_json`; no additional reviewer round is required.
