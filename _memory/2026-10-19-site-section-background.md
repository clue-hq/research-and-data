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

## Later 2026-10-19 — inspector polish, security fixes, merges (toward the PR to main)
- Inspector: Open in a new tab / Show in the header|footer / header placement are checkboxes (web
  inspector's `checkboxRow`); a button's Text row only for a copied button's words with no slot
  (founder: "keep row for those only"); Content fields switched off for every section (kept built).
- Plan 6 prompt + skill lines committed (founder: "commit these changes", 32cb9f75e). The two
  10-15 base-prompt lines were already in harness.py (live workspaces only).
- Group 4.5: K3-6/S4-1/S4-3/S7-3 were already fixed 10-15; K3-7 editor fallback done (34e2bcdd7:
  1 MB headers); PSL listing of edit.deeppresence.ai owed by the founder (runbook §9 step 10).
- Security (founder: fix before launch): S5-1 c32a1fef7 (AST import/require check + bundler
  resolves only the section), S3-1 4fb8318c2 (render page answers ONE string, Python measures it,
  page codes allow-listed), K5-5 2b0d42e10 (theme compiled only in site-kit's exact shape).
  Still open from that group: K3-2, S3-2.
- Merged origin/main (a58494274, clean) and origin/research-streaming (9a2e7e058). RS minted its
  own head-of-abm v72 / manual v18 / stage0 v45: collided numbers keep RS content; re-minted
  v75 / manual-*@v21 / stage0@v48 (3-way merged chapters, generated ones rebuilt, checksums
  recomputed); alembic join 00d525936b30; lane DB clue_trenton upgraded to it.
- CI lint now green: trials/ and docs/benchmarks/ excluded from ruff; tests/site_editor E501 allowed.
  mypy: 5 errors + 1 broken import contract are PRE-EXISTING on main and research-streaming.
- Merged build broke on RS's asset-library Logo search binding; Logo tab now shows only when the
  library provides it (site editor unchanged) — 7d7520091. Frontend design-system/lint/build green.
- In-app browser refused localhost:3029 after the stack restart (pane permission?), server fine.
