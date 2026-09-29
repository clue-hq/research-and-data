# Read rendered layout evidence

Use this when a saved preview shows mismatched type, oversized whitespace,
hidden product media, bad crops or a doubled frame. First identify the affected
page and node from the current document. Read the already-rendered evidence:

1. `view("layout:375")` returns a compact section/fragment index; use 768 or
   1440 for the corresponding saved preview. Follow a row's `target`, such as
   `view("layout:375:node:<id>")`, for its measured text, images and containers.
2. Compare the relevant source/keeper and authored sibling at the same width.
   Record only the differing properties and their node IDs. Boxes are document
   CSS pixels; `rendered_path` is relative to the rendered node, **not** an edit
   path. Get stored copy-edit paths from the text inventory instead.
   Resolve `parent_container_id` and `ancestor_container_ids` in the returned
   node's `containers` map. Shared wrapper measurements appear once.
3. Pair measurements with readable preview strips and asset/source pixels.
   Choose a repair for the observed cause, then check the same properties after
   the next authorized preview. Reading layout never renders or changes a page.

| Symptom | Evidence to inspect | What it does not establish |
|---|---|---|
| Heading/body mismatch | Family stack, size, weight, line-height, letter-spacing; declared font faces and load status | A CSS family or loaded face is not proof of the actual glyph font. Trace the font asset/source before claiming a match. |
| Large blank region | Text and parent boxes; height/min-height; alignment and padding | Present text in a tall centered container is not absent copy. A zero-box `display:contents` owner reports unknown visibility. |
| Missing phone product | Image CSS visibility, natural dimensions, load state, object-fit and parent clipping at phone/tablet/desktop | A loaded asset or visible background does not prove its product UI is visible. |
| Extra rim or wrong crop | Image and ancestor background, padding, radius, object-fit/position; actual asset pixels | The collector does not classify alpha or a baked background. Reuse a finished composite without adding its frame again; retain separate background layers for transparent UI. |

Measurements are from the same browser page just after its default-state
screenshot, not synchronized animation frames or all interactive states.
Use the state receipts for behavior. CSS visibility includes box/ancestor
clipping, not occlusion or human legibility. No field is a design-quality verdict.

Bounds: first 48 reachable sections/fragments, 16 text owners and 16 images per
node, 5,000 scanned elements per node, three image ancestors and 32 declared
font faces. Read `complete`, omissions and failures. Unmeasured content stays
unknown. `layout.stale` refuses a changed document/page/preview iteration; an
author without render authority finishes its round for the director to preview.
Missing measurements do not justify blind restyling or a full-page regeneration.
