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
{"direction_digest":"<returned by validate_creative_direction>","checks":[
  {"section":"preserve","index":0,"status":"met","notes":"What the current pixels show"},
  {"section":"review_needs","index":0,"status":"deviation","notes":"The retained treatment is still missing"}
]}
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
