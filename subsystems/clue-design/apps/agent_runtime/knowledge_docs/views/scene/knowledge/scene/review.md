# Scene review

Judge the actual current rendered scene at full view and final placement size.
Check idea/copy, evidence and attribution, hierarchy, readable contrast, brand
identity, authentic product crop, independent editable layers and reference
treatment. Compare the reference's visual invariants against the actual rendered
relationships, not merely matching palette or motif. Read the relevant playbook
and shared resources again if a revision raises a new question; discovery remains
available throughout review. A missing CTA is not a defect when the objective
needs none; a present CTA must have the right next step, brand-supported form,
measured label and readable local contrast. Check placement-specific overlays
through `knowledge/scene/placement.md`, never a universal bottom exclusion band.

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
  "support":{"status":"nonfactual","evidence_refs":[],"reason":"An invitation, with no empirical product promise.","source_limits":"No product behavior is asserted."},
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

For **every occurrence**, including `claim_kind=positioning`, judge the full
sentence's subject, scope, modality and implied product promise. Matching feature
nouns is insufficient; examine limiting and contrary evidence. Support status is
`supported`, `nonfactual`, `unsupported` or `unverified`. A supported factual
judgment cites evidence IDs declared for that copy block; nonfactual explains
why the words assert no verifiable product or empirical promise. Give one concise
reason and `source_limits` describing what the source does and does not establish,
including contrary observations. An evidence ID only links your declared source
and excerpt: the runtime does not independently verify those strings or their
meaning. Inspect the supplied source itself; never treat schema validation as proof.

Readability status is `readable`, `unreadable` or `unverified`, with a concise
placement-specific reason covering all fragments of that occurrence. Examine
each occurrence in the existing current full preview and feed proxy, including
overlap, clipping, local contrast and small support/attribution. There is no
universal font-size threshold. Whole acceptance requires complete passing copy
coverage, support and readability, bound to this direction, scene and preview.
An incomplete rejected review can retain partial rows and unresolved judgments.

For a seeded, validated `intent=edit` turn, `scope="scoped_edit"` may review only
the named edit and relevant copy, retaining unchanged unrelated text. Keep the
existing target/operation scope checks and report collateral changes. A passing
scoped review can support `edit_applied`; it never permits final `accepted` or
claims to certify the whole creative. Reuse the registered current critique in
`finalize_run` by omitting `critique_json`; no additional reviewer round is required.
