# Phase 2c — Selection-as-chat-context chips + compensating-edit contract

Cheap, high-value, no new backend infrastructure (the async/SSE plumbing from
2b is untouched). Chip the layers you want the agent to change; the turn
scopes to them and reports what it preserved.

## Backend (`3f9946a`)

- **`target_node_ids`** added to `AgentTurnPreviewRequest`. The singular
  `selected_node_id` stays one release for back-compat. `editor_target_node_ids`
  prefers the plural, falls back to the singular, de-dupes (order preserved).
- **`editor_instruction` is now the Moda §1.6 compensating-edit contract.**
  When targets are named: *"Scope every change to these target node id(s): …
  Do not touch any other node — every untouched node must stay
  byte-identical."* Then, always: *"Make a compensating edit: apply the change,
  then re-fit and verify — text must still fit (no overflow), nodes must not
  newly overlap, the surrounding layout must be preserved. State both what you
  changed and what you preserved."* Targetless turns keep the softer "prefer
  targeted repairs" but still carry the compensating contract.
- The context JSON carries `target_node_ids` so the agent sees the chips.

## Frontend (`db551a6`)

- **`useTargetChips` (new hook)** owns the target set. Selecting a node adds a
  chip (deduped); deselecting never drops one (the set is deliberate, distinct
  from the transient canvas selection); chips for deleted nodes are pruned;
  labels stay fresh from the live scene (Moda two-layer "layer name" / node-id
  display). Chips persist across turns.
- **EditorApp** owns the hook, feeds `targetNodeIds` into `useAgentTurn`, and
  passes chips + remove/clear to the panel. Workflow state lives in the hook,
  not the component (frontend-practices #2).
- **`EditorAgentRequest` gains `targetNodeIds`**; both the sync and streaming
  runners send `target_node_ids`. `useAgentTurn` threads it into every turn
  (live + resume).
- **`AgentChatPanel`** renders the chip strip above the composer (name + id,
  per-chip remove, "Clear"). CSS reuses the teal `agent-scope-chip` palette —
  no new token values (frontend-practices #3).

## Design note — accumulate vs mirror-selection

The chip set *accumulates* selections and persists across turns (the plan's
"multi-select → multiple chips … persists across turns"), rather than merely
mirroring the single live selection. This is what makes chips worth more than
the existing `selected_node_id`: you can target several layers deliberately.
The canvas is single-select, so chips are built one selection at a time; a
future canvas multi-select would populate several at once. Inspecting-by-
clicking does accumulate chips — the "Clear" affordance and per-chip remove
keep that manageable; tightening this (e.g. explicit pin) is a 2e polish item.

## Gates

- Full API suite green (82); +3 deterministic prompt-contract tests
  (plural-wins/fallback/dedupe, targets → byte-identical scoping + contract,
  targetless → soft targeting + contract).
- Editor suite **390 / 391** (+6: 4 `useTargetChips`, 2 chip render); the 1 is
  the known pre-existing `EditorCanvas` env-split case. tsc at baseline.
  (Same rolldown transform-cache flake as 2b recurred — spurious cross-file
  "Unexpected JSX expression" under full-suite parallelism; `rm -rf
  node_modules/.vite` + a single-file warm-up run clears it. tsc, the
  authoritative parser, accepts every file. Not a code issue.)
- Browser e2e (chip-targeted edit): see below.

## Browser e2e evidence (PASS — all steps, run succeeded)

Real stack (API :8002, editor :3002, both at `db551a6`, handshake OK),
driven via Playwright MCP by a claude-opus-4.8 agent on the seed document
(`?document=doc_demo`). Zero console errors throughout. Screenshots in
`browser-e2e/`.

- **Chip on select (primary gate):** selecting the "Contact Name" node
  (Layers panel row) produced a chip in the `.agent-target-chips` strip —
  name "Contact Name" + `<code>node_contact_name</code>` + a remove button
  (`2c-e2e-1-chip-appears.png`).
- **Persist + remove:** pressing Escape flipped the live selection to
  "none" but the chip **persisted**; the remove button cleared it (strip
  gone), and re-selecting restored it (`2c-e2e-2-chip-persist-remove.png`).
  Only one selectable layer exists in the seed doc, so the multi-chip
  "Editing 2 layers" path wasn't exercised in-browser (covered by the
  `useTargetChips` unit tests).
- **Request carries targets (primary gate):** the POST to `/agent/turns`
  body contained `"selected_node_id":"node_contact_name",
  "target_node_ids":["node_contact_name"]` (`2c-e2e-3-targeted-turn.png`).
- **Compensating edit landed:** the turn **succeeded** (stop_reason
  `accepted`) with a single scoped operation `update_node node_contact_name`
  (DSL `#node_contact_name text("Jordan Ellis")`) and a summary naming the
  preservation ("the single element intact and no layout changes … the
  targeted patch succeeded"). Nothing outside the chipped node was touched
  (`2c-e2e-4-settled.png`). Run `run_be05012842…`, status succeeded.

Anomalies (all cosmetic / expected): the seed doc must be opened via
`?document=doc_demo` (test setup, not a 2c defect); only one selectable
layer so multi-chip wasn't shown live; the review bar surfaces an internal
trace run id distinct from the authoritative POST run id.
