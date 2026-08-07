# 4c-B+ browser e2e verdict (2026-07-05, opus agent, 2 agent turns)

Env: editor :3002 / API :8002, engine 33373a37f9e0 both sides. Console
clean (0 errors/warnings) after every major step. 15/15 PASS.

## Scenario A — badge replay on doc_0aa02265835943eb8b391c21016de774

| Step | Result | Evidence |
|---|---|---|
| Load + hard reload | PASS | no disabled-canvas banner; design renders; badge pre-turn at (176,1088) — i.e. still OFF-CANVAS from run_8e7b9f64's accepted turn |
| Agent move to top-right (run_e0bb1733) | PASS | 1 iteration, critic ok accepted conf 0.9, 0 issues, no wedge, no 400s |
| **DSL vs landing** | **PASS** | DSL `#badge p(884,48) s(148,40)` → absolute_box (884,48,148,40) — **exact page-space agreement** (old semantics: 88pt off / off-canvas) |
| Accept / undo / redo | PASS | ⌘Z → (176,1088); ⌘⇧Z → (884,48), curl-confirmed |
| Free drag, zero sibling motion | PASS | badge 884→783.6; organizer/yc_mark/organizer_label/hero/eyebrow/cta byte-identical; inspector "Pinned (freehand)" |
| Reload persistence + persisted undo | PASS | (884,48) after reload; Document-history Undo restored (176,1088,180) exactly |
| Net-unchanged | PASS | final box = pre-turn box |

## Scenario B — toggle lifecycle on a fresh document (run_58685f0c)

| Step | Result | Evidence |
|---|---|---|
| Toggle present, default OFF, hint text | PASS | Document section checkbox |
| ON → agent design → Accept | PASS | event card; `layout_managed_editing: true` auto-persisted on doc-id mint |
| Accept-seam skipped | PASS | **3 stack containers survive Accept** (artboard/card/cta, layout_mode stack) |
| Managed drag, no silent freeze | PASS | child unmoved; containers stay stack; inspector "Layout-managed child" + Detach |
| OFF → first-gesture freeze | PASS | drag moved child freely; containers stack→**free** (curl); one ⌘Z restored |
| Toggle persists across reload | PASS | checkbox + GET agree (false) |

Best-draft-wins observed live: run_58685f0c exhausted 3 iterations
(completed_with_warnings) yet surfaced a clean, renderable proposal that
accepted — no invisible-draft proposal.

## Notes for future tests
- Freeze shows in `node.layout.layout_mode` (stack→free), NOT
  `node.kind.kind` (stays auto_layout).
- Playwright `page.mouse` reaches the CanvasKit overlay; synthetic
  Pointer/KeyboardEvents do not. `window.__lumenEditorDebug.
  getEngineScene()` gives authoritative computed bounds.
- After a fresh page load, toolbar ⌘Z is empty (local history);
  persisted undo drives through the Document-history Undo control.
- USER-REPORTED during the run (recorded in ../..//agent-improvement/
  2026-07-05-accommodation-edits.md): the accepted top-right landing
  crowded the YC lockup (strict edit scope forbids neighbor nudges) and
  `s(148,40)` shrank the frozen pill under its label's width (frozen
  children keep baked offsets; critic missed the overflow at conf 0.9).

Screenshots: A1-loaded, A4-proposal-preview, A5-before-drag,
A5-badge-selected, B1-toggle-exists, B3-proposal, B4-accepted-render,
B7-toggle-persisted-off (.png, this directory).
