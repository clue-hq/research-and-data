# W4.6 — icon schema trimmed to layout-only (contract 18b)

Branch `integration/frontend-design-part-iv-v2`, lane A's last §2 partition task.
Task brief: `.superpowers/sdd/2026-08-17-website-editor-integration/task-w46-brief.md`.
Report: `…/task-w46-report.md`.

## What changed

`web-inspector.tsx::IconControls` now renders exactly `LayoutSection(paddingAxes="two")`
plus the shared Layers section. Removed (absent, not disabled — ruling 18b): the Icon
section (icon select, icon color, background color, size, stroke) and the Link-to section.
The three icon option lists and the `InspectorDecoratedSelect` import went with them
(lint would otherwise flag them unused); the primitive itself stays in
`inspector-primitives.tsx` — presentation truth is not this task's to delete.

**No adapter change.** The brief's "verify before extending" question resolved to NO
extension: `adapter/apply.ts`'s `padding.x` / `padding.y` cases carry **no kind guard** at
all, because §5 gives the same Layout(-padding) section to embeds and every unmapped kind.
An icon-only allowlist would have broken §5. Icons were already writable for padding.

## Evidence

- Tests 587 → 593 (6 new: 5 in `apply.test.ts`'s W4.6 block, 1 in `hydrate.test.ts`).
  All passed against the unmodified adapter — they are characterization tests proving the
  padding path already serves icons; the implementation is view-only and has no renderer,
  so the browser pass is the proof for the section absence.
- New fixture `HARVESTED_ICON_V56` — `ficon` at doc version 56 (`px-2 text-primary`),
  produced by one `set_node_classes` op (55 → 56) that dropped `py-2` so R3's truthful
  zero has real bytes behind it.
- Browser (trunk stack 3030/8030/8010, doc `doc_31126145a0aa4753920629ae323a301b`):
  `data-selected-schema="icon:layout-only"`, panel = Layout + Layers only, zero `<select>`
  elements, two inputs (Padding X 2 / Y **0** — the truthful zero). Typing Y=7 wrote
  `py-6` (v56 → v57), rendered 24px, persisted through a full reload; restored to `py-2`
  (v58). Screenshots `/tmp/w46-0{1..4}-*.png`.

## Notes for the next agent

- `use-inspector-controller.ts` still carries `iconName` / `iconSize` / `iconStroke`
  presentation fields with dummy defaults. Nothing renders them now. Left in place
  deliberately: the controller is a shared chat-shell surface with sibling lanes live in
  it, and unused state fields are inert.
- `apply.ts::tokenTextColor` has no kind guard, so an icon `tokenTextColor` event would
  still write `text-<token>`. Unreachable after this task (the icon view emits no color
  event), but it is an unreachable-by-construction guarantee rather than an adapter
  refusal. Flagged, not changed — the guard sits in a file two sibling worktrees share.
- Browse quirk seen while verifying: the canvas iframe holds `document.activeElement`, so
  `press Enter` after a `fill` sometimes never reaches the padding input. Dispatching the
  native input + `keydown` events directly commits reliably. Automation artifact, not a
  product defect — the first edit committed through plain fill + Enter.
