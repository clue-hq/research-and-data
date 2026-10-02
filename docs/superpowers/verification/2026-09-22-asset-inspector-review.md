# Asset inspector review — 2026-09-22

Scope: San Diego, `asset-ingestion/improvements`. The founder requested automatic
saving, branded controls, an explicit When to use section, responsive stress
testing, and a comparison with the standalone Fredericton pilot on port 3056.

## Findings and corrections

- The old checkbox inputs inherited general detail-field input sizing, including
  full width and text-field height. Replaced that coupling with a reusable native
  checkbox, scoped 16 px geometry, token-based neutral colors/radius/focus, and a
  single-column list whose labels wrap as words.
- Removed both Save actions. One workspace-owned edit queue now handles title,
  description, type, roles and user context. Text debounces for 500 ms; blur and
  closing flush pending edits. Writes serialize per asset and retain edits made
  during a slow response. Failure retains the draft, shows a retry action and
  prevents closing from discarding it. Server metadata is merged by revision.
- The inspector uses the existing Base UI dialog primitive for focus containment,
  return focus, Escape, outside press and background scroll locking. Its header
  and close control remain visible while the full-height details body scrolls.
- Usage guidance is an explicit section under Description. Placement and avoidance
  have their own headings. Missing or pending analysis has an honest empty state.
  Source reference, observations, source-specific interpretations and overrides
  remain available in separate disclosures.
- Read-only sessions expose disabled classification/role controls and no edit
  pencils. The preview preserves the entire artwork with contain sizing.
- No API/schema, model, prompt, provider request or stored asset data changed.

## Verification

Live read-only inspection used the authenticated frontend at localhost:3033.
An isolated localhost:3043 harness rendered the actual inspector components and
edit queue with synthetic metadata and persistence, avoiding writes to the user's
assets. The following are browser checks, not an assertion of live save acceptance.

| Viewport | Check |
| --- | --- |
| 320 × 568 | Small portrait, contained stacked layout |
| 390 × 844 | Long content and narrow labels |
| 640 × 360 | Short landscape, reachable fixed close control |
| 820 × 1180 | Stacked breakpoint |
| 821 × 768 | Desktop breakpoint |
| 1024 × 600 | Short desktop, independent content scrolling |
| 1440 × 900 | Wide desktop |

Across these sizes, the dialog stayed within the viewport, the body had no
horizontal overflow, and all five checkboxes measured 16 × 16 px. Stress content
included a 120-character unbroken title, approximately 10,800-character
description, 4,000-character note and 400-character source URL. Empty and read-only
states were checked. The live building preview and details were inspected after
hot reload as well.

The persistence harness simulated a 1,200 ms response and a first-write failure.
The draft remained visible with an error; Retry succeeded. Rapid role changes,
text edits and immediate close preserved the final combined patch. Keyboard Space
toggled a role; Escape flushed and closed; opening from a button restored focus
to that button on close. Shift-Tab remained within the open dialog.

- `npm run design-system:build`: passed.
- Brand-context model/repository tests: **106 passed**, including six new edit
  queue tests for debounce, concurrency, failure/retry, per-asset isolation,
  reset/assignment ordering and close flushing.
- `npm run lint`: passed with two existing unused-variable warnings in
  `canvasOperations.ts`.
- `npm run build`: passed in an isolated copy, preserving the live dev `.next`.
- Standalone `tsc --noEmit --incremental false`: not green because of existing
  test typing errors; no diagnostics in the changed inspector files.
- `git diff --check`: passed.

Drafts are in memory. This work does not promise recovery from browser/process
termination, and it does not regenerate historical asset analysis.

## Was the pilot actually referenced?

**The specification and field structure referenced it; equivalent output quality
was not demonstrated by the previous validation.**

The September 21 handoff records reading the full founder transcript and copying
the pilot-derived asset-context specification. The specification asks for useful
human descriptions and usage guidance plus separate agent observations and
interpretations. That intent is present in the production schema and prompt.
However, the prior verification report explicitly limits its model-quality proof
to a synthetic analytics image, and says authenticated browser-to-provider
acceptance was not performed. There is no recorded representative pilot parity
evaluation in those artifacts. This is an evidence limit, not a claim about every
unrecorded action in the original implementation session.

For this review, inspected the live pilot, its actual classification prompt and
four stored outputs: website wordmark, inbox screenshot, building photograph and
split Before/After ad. Pilot source paths, in the sibling Fredericton checkout:

- `experiments/brand-context-agent-v1/assets.py`, `classify` (around line 275)
- `experiments/brand-context-agent-v1/visual_review.py`
- `deliverables/brand-context-pilot/v2/assets.json`

The pilot prompt explicitly asks for concise, specific guidance, including
`use_when`, `how_to_use`, `avoid_when`, `crop_and_placement` and
`background_suitability`. It separates visual observations from audience/usage
interpretations. The four inspected records identify `x-ai/grok-4.6`; the pilot
also has a visual-review correction pass. Its final library is therefore not
evidence of what a single initial generation prompt alone produces.

The current production `_SYSTEM_PROMPT` in
`subsystems/clue-design/apps/api/lumen_ingestion/describe.py` requests literal
description, usage/avoidance/placement, observations and occurrence-specific
interpretations, but has no explicit brevity target or worked pilot examples.
The live inspected production records identify `deepseek/deepseek-v4.1-flash` and
`asset-context-v1`. Matching fields is insufficient to claim matching quality.

## Open generation-quality defect

Read-only browser and isolated database inspection found a concrete mismatch:
`asset_ing_a99a08190a65a455` visibly contains the Wynwood House wordmark (512 × 137),
but its persisted generated title/description describe a human portrait. It has
no human override. This is already wrong in generated storage, not a frontend
rendering mix-up. The exact provider/input cause has not been established.

The building record `asset_ing_42cb166b88686f37` has a much longer description than
the pilot examples. Its placement and usage now appear explicitly in the UI,
but this presentation change does not improve the generated wording itself.

The earlier provider verification also recorded an initial structured response
that incorrectly described a portrait before a revised request passed one
synthetic sample. The new mismatch means that single sample did not establish
general reliability. Next generation work needs to inspect the actual analyzed
preview/request, reproduce this failure, and compare a representative logo/photo/
screenshot/ad set against pilot-style expectations before any wider reanalysis.
No paid calls, backfill, prompt change, worker restart or database mutation was
performed in this inspector review.
