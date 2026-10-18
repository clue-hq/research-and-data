# Site editor: whole section = Layers only; section Background selectable — 2026-10-19, trenton, site/publish-durability

Founder rulings this session (after plan 6):
- Arrange's Order row = the ad editor's Layer row style (icon tiles, layer-up/layer-down, half width each, label kept "Order") — d3a989562.
- Whole section selected (ours, copied, header, footer): only Layers (+ header placement). "For now": Content fields panel kept, switched off (`fields: null` in use-site-editing-session.ts).
- "Header background" row = every section's **Background** (its own outermost box: `root` or a copy's one top element), first under the section in Layers; opens the section-box panel.
- Canvas: first blank click → section; second blank click in the selected section → background (Figma drill-in). Same outlines as elements; dashed hover previews the next click.

Built (commits 2e4d4063d, 8f8588e6f, 2cf9fad88, 289e30939):
- protocol `selected.backgroundKey` (always when the section has one), `sectionBox` only when the background is selected; frame `canvasClicked` / `blankClickSelects`; app `selectedKeyOf`, Background Layers row.
- Section/background outline drawn by the `[data-puck-component]` wrapper's ::after (selected) / ::before (hovered) at measured CSS vars, z-index max — a CSS outline on the section was painted under a copied hero's positioned layers (reproduced by a pixel test, test_editor_section_background.py). Puck's `_DraggableComponent-overlay_` outline/tint off.
- Tests: frame-controller 126, frontend unit 3603, site_editor browser folder 64 — all green. Live-checked Oliver hero + header (nothing saved).

Notes for later:
- On Oliver's hero the visible gradient is an image layer inside the copy, so the Background's Fill (transparent) paints under it.
- Wrapper-drawn outline is re-measured on selection change, redraw and window resize only (not on image load).
