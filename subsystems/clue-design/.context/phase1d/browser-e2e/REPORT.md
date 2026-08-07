# Phase 1d browser e2e — CanvasKit, real editor + engine

Run by an **Opus 4.8 subagent** driving Playwright against the dev servers at
commit `af87f44` (handshake verified). **ALL 7 STEPS PASS** — every step
asserted against both engine truth (`getEngineScene()`) and the live
UI/render. No source files modified by the run.

## Steps and key numbers

1. **Stacked baseline** — clipping gray stack (30,90) 150×160; children
   solved at (30,90) / (30,140) / (30,190). `1d-01-stacked.png`
2. **Detach via UI** — Layers→rect_b showed "Layout-managed child" +
   **Detach**; after click: state "Pinned (freehand)", handles Enabled,
   inspector X/Y/W/H live at 30/140/120/40; engine `position_mode:
   absolute`, `absolute_box` = `base_anchor` = (30,140,120,40); zero
   motion for the detached node, rect_c closed the slot to (30,140).
   `1d-02-detached.png`
3. **Pinned canvas drag** — +140/+70 px gesture → box (30,140)→
   (108.215,179.107), `computed`==box, `base_anchor` unchanged (records
   the detach point), siblings untouched. `1d-03-dragged.png`
4. **Drag past the page edge** — box x→303.752 (spans 303.75–423.75mm,
   fully past the 210mm page). Honored, no blocking anything; **magenta
   fill render-clipped at the artboard edge while selection chrome sits
   off-page — the Moda reference behavior.** `1d-04-page-edge-clip.png`
5. **Parent drag carries the pin** — stack drag committed a guide-snapped
   delta (-30,+47)mm; rect_b's box moved by the SAME delta (difference
   0.0mm), in-flow children followed identically.
   `1d-05-parent-drag-carries-pin.png`
6. **Re-attach** — pin/anchor/mode cleared; rect_b re-flowed into its
   stack slot (stack origin +50); inspector back to "Layout-managed
   child" + Detach. `1d-06-reattached.png`
7. **Undo chain + atomicity** — undo#1 restored the pin (pre-reattach
   box); undo#2 reverted the ENTIRE parent-drag batch (container + pin
   carry) in ONE frame — the atomicity contract holds.
   `1d-07-undo-chain.png`

## Test-harness findings (for future browser e2e — not product bugs)

- Playwright's synthetic `page.mouse` does NOT drive the CanvasKit canvas
  (passive-listener preventDefault warnings; commits nothing). The
  interaction surface is `data-testid="canvaskit-interaction-layer"`
  (React pointer handlers + setPointerCapture): dispatch native
  `PointerEvent`s to that fixed element for the whole gesture — which
  also allows drags past the canvas edge.
- `data-testid="selection-overlay"` is graphics-only chrome
  (`pointerEvents: none`, full-canvas bounds) — not usable to locate a
  node. Calibrate a page→screen transform from the rendered A4 frame
  instead (origin + px/mm from the artboard rect).
- Grabbing a container means hitting its bare fill; children hit-test on
  top of it (consistent with the paint-order hit stack).
- Console: only passive-listener warnings from synthetic events + a
  benign Next.js dev-tools line; zero engine/render errors across the run.
