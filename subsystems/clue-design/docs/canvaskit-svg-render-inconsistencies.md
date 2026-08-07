# CanvasKit vs SVG Render Inconsistencies

Date: 2026-06-15
Branch: `editor/canvaskit-polish-v0`
Status: observed during manual compare QA

## Evidence

- Manual compare mode was exercised against an agent-generated `linkedin_square`
  artboard.
- Local screenshot evidence from this QA pass, stored outside this worktree:
  - `/Users/aryankeshri/Documents/brilliant-design/lumen-compare-after-font-fallback.png`
  - `/Users/aryankeshri/Documents/brilliant-design/lumen-inspect-after-headline-edit.png`
  - `/Users/aryankeshri/Documents/brilliant-design/lumen-after-canvas-cta-click.png`
  - `/Users/aryankeshri/Documents/brilliant-design/lumen-after-cta-text-edit.png`
- Agent run evidence:
  - `.lumen-runs/run_295c0f0c7ade44108a99e33a52ba1800/final.json`
  - `.lumen-runs/run_295c0f0c7ade44108a99e33a52ba1800/iterations/003/preview.svg`
- Server log evidence:
  - `/tmp/lumen-canvaskit-polish-backend.log`
  - `/tmp/lumen-canvaskit-polish-frontend.log`

## Basic Canvas Editing Evaluation

The following basic editor changes were evaluated against the generated
`linkedin_square` scene:

- Layer-tree selection worked for text nodes. Selecting `text headline` moved
  the inspector to the expected node.
- Inspector text editing worked for selected text. The headline was changed to
  `Never Miss Patient Calls.` and the editor generated a canonical
  `update_node headline` operation.
- Direct canvas selection worked for at least one visible text node. Clicking
  the CTA area selected `text cta_text`, and the layer tree highlight moved to
  the corresponding node.
- Inspector text editing also worked after direct canvas selection. The CTA was
  changed from `Book a Demo` to `Schedule Demo`.
- Direct drag/move did not work for the selected generated text node. The node
  remained layout-managed, the inspector showed canvas handles as disabled, and
  no geometry operation was emitted. This means basic content edits are possible,
  but direct manual repositioning of generated auto-layout children is not yet
  usable.

Conclusion:

- Basic text selection and text content edits can be made in the editor canvas.
- Basic direct layout changes by dragging are not available for generated
  layout-managed children and need a separate layout-aware editing slice.

## Real Render Differences

### 1. SVG Preview Falls Back To Serif For Inter Text

Observed:

- CanvasKit canvas renders the ad headline/body as sans-serif.
- SVG export preview renders the same headline/body as a serif face.

Likely cause:

- CanvasKit explicitly registers `/fonts/InterVariable.ttf` under `Inter`.
- SVG export emitted `font-family="Inter"` only.
- When the SVG is displayed as an image/blob, it does not reliably inherit the
  editor page's loaded font context, so Safari falls back to a serif font.

Status:

- Fixed in `crates/lumen-export/src/svg.rs` by emitting a browser-safe fallback
  stack for Inter: `Inter, Arial, Helvetica, sans-serif`.
- Regenerated SVG preview rendered with sans-serif text during manual QA.

### 2. Canvas Text Metrics And SVG Browser Text Metrics Can Diverge

Observed:

- Text placement and line wrapping are broadly similar, but the SVG side looks
  heavier/larger once it falls back to the serif face.
- Even after the fallback-stack fix, CanvasKit text and browser-rendered SVG
  text may not be pixel-identical because they use different rasterizers and
  shaping paths.

Likely cause:

- CanvasKit uses SkParagraph plus the registered Inter font.
- SVG export writes positioned `<text>` and `<tspan>` elements.
- The browser image renderer resolves and rasterizes those text nodes
  independently.

Implication:

- The target should be same font family, same line breaks, same approximate
  bounds, and visually equivalent weight/size. Pixel-perfect equality should not
  be required unless text is converted to paths or fonts are embedded.

### 3. CTA Text Appears In SVG Export But Is Missing Or Too Faint On Canvas

Observed:

- The export preview shows the CTA label `Book a Demo` inside the blue CTA.
- The CanvasKit canvas screenshot shows the blue CTA shape, but the CTA text is
  not visibly rendered on top of it.

Likely causes to inspect:

- CanvasKit text drawing order, clipping, opacity, or fill resolution for that
  specific text node.
- Text color contrast after brand-token resolution.
- A text measurement/line-height mismatch causing the text to be clipped inside
  the CTA container.

Status:

- Not fixed yet. Needs node-level inspection of the generated CTA text node,
  its computed bounds, fill, clipping parent, and draw order.

### 4. Emoji/Icon Glyphs Render In SVG But Not CanvasKit

Observed:

- The SVG preview shows a small emoji/icon at the beginning of the badge.
- The CanvasKit canvas badge appears to omit that glyph and only shows the
  text.

Likely cause:

- CanvasKit has Inter registered, but Inter does not cover color emoji glyphs.
- Browser SVG rendering can fall back to the platform emoji font.

Product decision needed:

- Either forbid emoji in generated design text and make agents use vector/icon
  nodes instead, or add a supported fallback/icon strategy for CanvasKit and
  export.

### 5. Some Elements Appear In CanvasKit But Not SVG Export

Observed:

- During manual comparison, the user reported that some visual elements are
  present on the editable canvas but missing from SVG/export preview.

Why this is serious:

- This is not a normal font-rasterization difference.
- It indicates that the CanvasKit draw descriptor path and the SVG export path
  may not be consuming the same resolved node set, paint set, clipping state, or
  visibility rules.

Likely causes to inspect:

- Node kind supported by CanvasKit but skipped or degraded by SVG export.
- Paint/effect type supported by CanvasKit but not represented in SVG.
- Parent clipping or group opacity applied differently.
- Export page filtering or artboard-child traversal skipping nodes that the
  canvas workspace still draws.
- Diagnostics such as unresolved assets/tokens causing export placeholders or
  omission while CanvasKit draws an editor fallback.

Status:

- Not fixed yet. Needs a node-by-node inventory comparing:
  - `WorkspaceModel` / CanvasKit draw descriptors;
  - SVG sidecar node IDs;
  - SVG `data-lumen-node-id` attributes;
  - active page/artboard children and computed geometry.

### 6. Some Elements Appear In SVG Export But Not CanvasKit

Observed:

- During manual comparison, the user reported that some visual elements are
  present in SVG/export preview but missing from the editable canvas.
- Concrete examples already seen:
  - CTA label `Book a Demo` is visible in SVG export but not visibly rendered
    over the blue CTA shape in CanvasKit.
  - Emoji/icon glyph in the badge is visible in SVG export but not CanvasKit.

Why this is serious:

- The export path may be correct while the editor canvas is hiding or failing to
  draw selected node types, text glyphs, or clipped children.
- If users edit against the CanvasKit view, they may not realize the downloaded
  artifact contains extra visible content.

Likely causes to inspect:

- CanvasKit text glyph coverage and fallback fonts.
- CanvasKit text clipping inside fixed-height or auto-layout containers.
- CanvasKit draw ordering, especially text inside frames/groups.
- Fill resolution differences where CanvasKit uses transparent or low-contrast
  paint while SVG uses a default/export fallback.
- Artboard clipping and transform math differences under workspace zoom.

Status:

- Not fixed yet. Needs generated-scene node inspection and a parity assertion
  that every exported visible node has a corresponding canvas descriptor.

## Compare UX Differences That Are Not Scene Render Bugs

### 7. Compare Mode Uses Independent View Scales

Observed:

- The Canvas side and the Export Preview side appear at different on-screen
  sizes.

Interpretation:

- This is viewport/fit behavior, not necessarily an artifact geometry mismatch.
- It still makes visual comparison harder because a user reads it as a render
  inconsistency.

Potential fix:

- Add a synchronized compare scale mode, or clearly fit both panes to the same
  normalized artboard size when Compare is selected.

### 8. Canvas Side Shows Editor Chrome That Export Preview Does Not

Observed:

- Canvas can show active artboard outlines, selection bounds, handles, slot
  badges, and diagnostics chrome.
- Export preview is intentionally artifact-only.

Interpretation:

- This is expected for normal editing, but it can confuse Compare mode.

Potential fix:

- In Compare mode, optionally hide selection chrome and editor-only artboard
  outlines on the canvas side, or add an explicit artifact-only comparison mode.

## Not Yet Evaluated

- Image placement parity between CanvasKit and SVG export.
- Gradient/filter/shadow parity for this specific generated scene.
- Text editing overlay parity against SVG export.
- Konva fallback parity for the same generated scene.
- PNG export parity against SVG preview after the font fallback change.

## Recommended Fix Order

1. Inspect the CTA text node on the CanvasKit side and determine whether the
   issue is clipping, draw order, fill resolution, or measurement.
2. Add a node inventory/parity check that compares canvas descriptors, SVG
   sidecar nodes, and actual SVG `data-lumen-node-id` attributes.
3. Decide whether generated text may contain emoji. If not, add agent guidance
   and diagnostics; if yes, add a real icon/font fallback strategy.
4. Improve Compare mode so both panes use synchronized artifact scaling and can
   hide editor-only chrome.
5. Add a layout-aware manual editing path for generated auto-layout children so
   users can reposition content through parent layout operations instead of raw
   child `x/y` edits.
