# W4.5 — Canvas background token on the page root (lane A, trunk)

Date: 2026-08-18. Branch `integration/frontend-design-part-iv-v2`. Contract row 1
(`docs/specs/website-editor-integration/web-inspector-mapping-contract.md`).

## What shipped

- `web-inspector.tsx` `CanvasControls`: the existing Background `ColorControl` is wired the
  W4.0 way — `options={themeColors}` from `useThemeColors()`, `onTokenChange` →
  `setValue("tokenBackgroundColor", label)`, trigger color
  `themeColorForToken(themeColors, state.tokenBackgroundColor) ?? state.backgroundColor`.
  Hex/Custom tab stays §3-inert. No other canvas view change.
- `adapter/apply.ts`: **no new kind**, only a docstring citing row 1 (see below).
- `adapter/hydrate.ts`: **no change** (its `bgColor` → `tokenBackgroundColor` mapping is
  kind-agnostic and already served the root).
- Tests: 4 apply + 2 hydrate over a new harvested root fixture. 569 → 576.

## Root-cause finding (why apply needed no code)

`lumen-web` builds **every page root as a Container**
(`subsystems/clue-design/crates/lumen-web/src/doc.rs::WebDoc::new`), and the canvas schema is
chosen by node **ID** (`hydrate.ts::inspectorSelectionFor` → "canvas" for `page.root`), never
by kind. W4.4's `TOKEN_BACKGROUND_KINDS = {container, section}` therefore already covered
row 1. The new tests pin that implicit dependency: narrowing the set to sections would
silently kill the page background.

## The two upstream gaps that keep row 1 inert end to end

Both live outside the inspector; recorded in-code at the `CanvasControls` comment.

1. **Nothing can select the page root.** `render_page` (same crate, `src/render.rs`) renders
   only `root.children` into `<body>` — no element carries `data-node-id="root"`. The canvas
   bridge's click handler resolves `closest("[data-node-id]")` and a background click therefore
   *clears* the selection; `adapter/layers.ts` starts the tree at the root's children, so the
   Layers list has no root row either. With no `selectionId`, W3.1's null contract drops every
   event the canvas Background emits. Verified live: picking a token moves the swatch, document
   stays at v47.
2. **`root.classes` is dropped by the renderer.** Even a written `bg-<token>` on the root paints
   nothing. Verified live: the doc's root has carried `bg-surface-canvas` (#F8FAFC) since the
   fixture seed and `<body>` renders with no class and a white background.

Closing row 1 end to end needs a `lumen-web` change (render the root element, or hang its
classes on `<body>`) plus a selection path (a root row in `buildWebLayerRows`, or a bridge
background-click → root rule). Neither is in W4.5's permitted scope ("the only permitted view
change is wiring the existing Background ColorControl"), so this is a founder/controller ruling,
not an implementation choice. Until then the control is honest-but-inert — the same posture it
had before the wiring, now showing the document's real tokens instead of the dummy six.

## Fixture provenance

`HARVESTED_PAGE_ROOT_V47` in `adapter/__fixtures__/web-nodes.ts` — doc
`doc_31126145a0aa4753920629ae323a301b`, workspace `ws_8040294627e146ae93f753ec0d3e1726`,
design API :8010. One `set_node_classes` op took the document 46 → 47 to put the real
`surface-canvas` theme token on the root (the exact class the popover writes), so the hydrate
test runs against real bytes rather than a hand-written shape.

## §2 padding delta

Nothing to do: the dummy's canvas view ships Background + Layers only — no padding boxes.
