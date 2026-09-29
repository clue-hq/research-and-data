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
| Heading/body mismatch | Family stack, size, weight, line-height, letter-spacing; per-text `font_usage` and declared faces | CSS aliases can differ while using the same face, or hide a fallback. Compare reported family/PostScript names with the source at the same width/role. File identity and weight/variation fidelity remain unverified. |
| Large blank region | Text and parent boxes; height/min-height; alignment and padding | Present text in a tall centered container is not absent copy. A zero-box `display:contents` owner reports unknown visibility. |
| Missing phone product | Image CSS visibility, natural dimensions, load state, object-fit and parent clipping at phone/tablet/desktop | A loaded asset or visible background does not prove its product UI is visible. |
| Extra rim or wrong crop | Image and ancestor background, padding, radius, object-fit/position; actual asset pixels | The collector does not classify alpha or a baked background. Reuse a finished composite without adding its frame again; retain separate background layers for transparent UI. |

Measurements are from the same browser page just after its default-state
screenshot, not synchronized animation frames or all interactive states.
Use the state receipts for behavior. CSS visibility includes box/ancestor
clipping, not occlusion or human legibility. No field is a design-quality verdict.

`font_usage` reports Chromium's actual family/PostScript name, custom-font flag
and glyph count for the measured element's child text nodes. Several fonts may
serve one element. A missing family in the CSS stack is not a fallback diagnosis
until the measured usage supports it; an unavailable probe is not evidence that
the font is missing. Compare source and authored elements before choosing a fix.
Match the source's face, responsive size, weight and line-height together. Font
names alone do not identify a stored asset, certify variable axes or synthetic
weight. Retrieve the source font asset
through the existing library/inspection path before changing a face declaration.

Bounds: first 48 reachable sections/fragments, 16 text owners and 16 images per
node, 5,000 scanned elements per node, three image ancestors and 32 declared
font faces. Font probes sample at most 48 distinct text owners across those
records, taking one from each section before further text; nested duplicate owners
share a receipt. `text_owner_id` exists only within this capture, not as an edit ID.
There are at most four font entries per owner and a two-second budget checked
between protocol calls, not a hard transport timeout. Read `glyph_font_capture`
and each text's `font_usage` for font coverage separately from layout `complete`.
Hidden text, caps, elapsed budget and unavailable Chromium support stay explicit.
Read `complete`, omissions and failures. Unmeasured content stays
unknown. `layout.stale` refuses a changed document/page/preview iteration; an
author without render authority finishes its round for the director to preview.
Missing measurements do not justify blind restyling or a full-page regeneration.
