# 2026-09-04 — Selection model v2: units on click, drill on double-click, Cmd/Ctrl deep select

Plan: `docs/superpowers/plans/2026-09-04-selection-model-v2.md` (founder ruling 2026-09-04: "the
current plan 3 implementation is not very practical enough" — every layer must be selectable and
movable, however deep). Commits `e96548e26`, `a0b4700e4`, `ca8e7a170`, `71d995917`, `2d2477525`;
frontend only, engine untouched. SDD with Opus implementers, every diff reviewed and every test
re-run first-hand by the controller. Supersedes Plan 3's ladder (`2026-09-04-plan3-selection-ladder.md`).

## The rules (R1–R6, plan header)
- **R1 click** — the OUTERMOST unit (button-shaped auto-layout or `group`) on the hit path, else the
  deepest representable node. Frames and ordinary stacks are pass-through: they win a click only on
  their own empty area.
- **R2 double-click** — with an ancestor selected, drill one representable level toward the pointer;
  with the text itself selected, open the caret (lock/run-gate refusals unchanged); a selection
  unrelated to the hit re-syncs to the click target. Rung B's "drill OUT to the top-level container"
  and Plan 3's "button double-click opens the label's caret" are gone.
- **R3 Cmd/Ctrl-click** — the deepest node; repeated at the same spot, one shallower per click,
  wrapping to the deepest. The ROOT FRAME is excluded from the cycle (it is representable as the
  canvas selection; Escape reaches it) — found by Task 1, ruled by the controller.
- **R4 Alt-click / Escape** — walk up (Plan 3's, unchanged). Plan 3's "second click on the selected
  node walks up" and its 4 px slop are REMOVED: a double-click is two clicks at one spot.
- **R5 hover** — previews what a press would act on; silent over the selection.
- **R6 press** — drags what the click selected; **amendment from the live proof:** a press on the
  node that is ALREADY selected keeps it (when it sits in the hit stack at or below the R1 target),
  so a label reached by drill-down is draggable inside its button. Without it the press re-selected
  the plate and moved the plate (Brex ad v98→v99, undone with ⌘Z).

## Where
`adapter/scene-selection-ladder.ts` (`isUnit`, `selectionClickTarget`, `selectionDrillDown`,
`deepSelectTarget`, `selectionPressTarget`, `sceneHoverTarget`, `selectionWalkUp`,
`escapeSelectionEffect`), `adapter/scene-text-edit.ts` (`sceneDoubleClickEffect` now takes the
engine's `stack` + `pageId`), `components/scene-artifact-canvas.tsx` (pointer-down routes to the press
target or the deep-select target; `walkUpRef` gone). Tests: 9 ladder cases, 46 text-edit cases;
`npm test` green, lint clean.

## Live proof (colombo, Brex ad `doc_f8668063…`, its CTA `cta_plate` › `cta_label`; evidence
`/tmp/plan5-evidence-keep/`)
- Click on the label → `cta_plate`. Double-click → `cta_label` selected, no caret. Double-click again
  → caret (the stage's chrome hides while the caret is open); Escape closes it, label still selected.
- Cmd-click ×3 from the label → `cta_plate` → `footer` → `plate` (the card): one shallower per click.
- Alt-click on the label → `footer` (walk-up from the plate).
- With the label selected, hover over it → no hover outline; a 20 px press-drag moved the LABEL
  (outline 161.5 → 181.5 stage px), the plate stayed, document v100 → v101; ⌘Z restored it.

## Not proven live
- The GROUP-as-unit rule (R1) is pinned by the harvested-fixture tests only: the Apollo ad no longer
  carries a group node (v275), and the Brex ad has none.

## Open
- Container escape hatches (drag a child OUT of its container, unwrap a container keeping its
  children, delete-container-only) are the next plan the founder asked about; not this one.
- Overlapping SIBLINGS at one point cannot be drilled (none contains the others): Cmd-click cycling
  and the Layers panel are the routes.
