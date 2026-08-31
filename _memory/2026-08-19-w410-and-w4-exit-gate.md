# 2026-08-19 — W4.10 keyboard audit DONE + W4 exit gate PASSED

Branch: `integration/frontend-design-part-iv-v2` (istanbul). Plan:
`docs/superpowers/plans/2026-08-17-website-editor-integration.md`. Contract:
`docs/specs/website-editor-integration/web-inspector-mapping-contract.md`.
Process: audit + adjudication by the controller (Fable, inline); the exit-gate browser
sweep executed by an Opus verifier from a written checklist
(`.context/w4-exit-gate-checklist.md`, report `.context/w4-exit-gate-report.md` —
.context is gitignored scratch; durable facts are here and in the contract/plan).

## W4.10 — node-op keyboard audit (wired NOTHING, per the task's own rule)

Recorded as **contract §7 item 8**. Headline: ruling 29's "keyboard-only for now" was an
intent, not a shipped surface — **the web editor has NO keyboard path for node
delete/duplicate/reorder anywhere**:
- Engine op vocabulary fully present: `InsertNode`/`RemoveNode`/`MoveNode`
  (`subsystems/clue-design/crates/lumen-web/src/ops.rs:53-67`) — substrate ready.
- Source `WebEditorApp.tsx:855-872`: only ⌘Z/⇧⌘Z (focus/busy-guarded).
- Bridge `web_bridge.py:557-570`: rich-text Escape/⌘-Enter; Escape clears selection.
- Our stack: same undo/redo global (`use-inspector-writes.ts:142`), Enter/blur commits,
  W4.7 Escape-abandons-draft, rich-text keys, menu arrows. No node-op keys.
- Scene editor contrast (`EditorApp.tsx:1294` Delete/Backspace deletes) confirmed as the
  origin of ruling 29's premise — inapplicable to web.
Entering scope needs a founder ruling on the affordance; §4's ruling-29 line should be
re-worded "agent-only (no keyboard or UI path)" when that lands.

## W4 exit gate — PASSED (recorded in the plan)

Consolidated sweep on the final union (three lanes + chat-flow + page-root engine fix):
- **§1: 22/22 live** — rows 1,3,4,5,6,7,11,12,13,14,15,16,17,19,20,22,25,26,34,40,41,R3.
  Every write engine-verified (version bump + class/prop delta) then undone. Row 12
  (replace image) presence-only per its lane-B full multipart proof; row 34 proven on
  the lane-C seeded doc `doc_b778a805…` (trunk doc has no custom-component node),
  including Escape-abandons vs committed-edit both directions.
- **§2: 6/6 absent** — size "13", Tile, Critical, icon = Layout+Layers only, section
  Link-to, text vertical alignment.
- **§3: 5/5 provably inert** — font family, hex/custom tab, canvas bg opacity, stroke,
  header lock: engine version + JSON unchanged after interaction.
- Chat-route union spot-check green (same schemas serve; URL write-back tracked).
- Both docs restored node-identical (trunk v94→136, lane-C doc v24→26 — undo is a
  forward version; content byte-identical to pre-sweep snapshots).

## Non-gate observations from the sweep (recorded, not fixed)

1. The seeded page's sections tile 100% of `<body>` — no exposed page background to
   click at any viewport; the sweep dispatched the click on the body element and the
   root-selection path is genuinely live. Real-world consequence: on a fully-tiled page
   the click-empty-background entry to the Canvas schema is unreachable (no affordance
   gap on the seeded design itself; worth remembering for W5's walk).
2. Post-undo inspector shows pre-undo values until reselect — the ALREADY-RULED accepted
   drift (per-node inspector keying, founder-observed remount defect trade-off). Not new.
3. Section direction toggle buttons have no accessible name (a11y minor).
4. Console noise beyond the known pair: 404 for `asset_fixture_logo/bytes` (fixture
   asset without bytes), CSP `navigate-to` warning inside the custom-component srcdoc.
   Benign dev noise; note for W5.

## Next

W5 acceptance: the 42-item contract walk in the browser producing
`acceptance-record.md`, the formal visual-parity pass against the reference PNGs, root
`make check` (NB: 5 pre-existing backend failures recorded in
`_memory/2026-08-19-chat-flow-slice6-closeout.md` are other lanes'), founder sign-off.
Open founder decisions queue: artifact-identity URL param (chat-flow); node-op
affordance (§7 item 8); §7 items 1–6.
