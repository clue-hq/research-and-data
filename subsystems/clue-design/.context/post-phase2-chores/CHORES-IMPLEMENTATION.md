# Post-Phase-2 chores — the three parked items, closed

Branch `agents/editing-roundtrip-v0`: `0542efb` (C1) + `09ea20c` (C2) +
`496ed06` (C3) + records. Browser-verified on the live stack (claude-opus-4.8
+ playwright-mcp), document `doc_9c2cea1d…`.

## C1 — `selected_node_id` back-compat drop (`0542efb`)

Coordinated API + editor removal after the one-release window 2c promised.
API: field off `AgentTurnPreviewRequest`, singular fallback out of
`editor_target_node_ids`, prompt context + turn logging key on
`target_node_ids`; a legacy sender's extra key is ignored by pydantic
(regression-tested), never a 422. Editor: `EditorAgentRequest.selectedNodeId`
gone; both runners stop sending it (chips mirror the selection, so the
primary selection reaches the server as a target chip).
**Gate A live: the POST body carried `target_node_ids` and no
`selected_node_id`.**

## C2 — local undo/redo now persists (`09ea20c`)

The W3 gap: undo/redo replaced the scene client-side only; the server kept
the undone ops until the next batch's reconcile flagged a false divergence.
The engine computes batch inverses all along — they were dropped at commit.
Now: `EditorHistoryFrame` carries `inverseOperations` + `persisted`; all
three commit sites thread the engine's inverses (direct edits, structured
edits, agent Accept via the preview state); `undo()` posts the INVERSE batch
through the ordinary `enqueueForPersistence` path (append-only history, no
new endpoint, base_version stays queue-managed), `redo()` re-posts the
original. A persisted batch with no computable inverse warns
`EDITOR_UNDO_NOT_PERSISTED` instead of drifting silently.
**Gate B live: edit → v1, Cmd+Z → v2 (server text reverted), Cmd+Shift+Z →
v3 (returned); 3 `/operations` POSTs, all 200, zero 409s; reload showed the
redone state — the server followed local history.**

## C3 — diagnostics visible outside the panel (`496ed06`)

`DiagnosticsAlertPill` (EditorChrome) renders in the topbar whenever
error-severity diagnostics exist in the shared slot and the Diagnostics
panel isn't the active mode; click opens the panel. Reuses the existing
error accent + the pill radius token. Unit-tested on the export-failure
path (error raised while panel mode is "export" → pill with count → click
lands on the diagnostic).
**Gate C live: pill absent at every healthy checkpoint.** One nuance
verified deliberately: an accepted turn's advisory error note (LUMD0212)
did not raise the pill because the accept's successful export preview
overwrites the shared diagnostics slot (pre-existing behavior; advisory
stays visible via the panel's preflight-result rendering, and the accept
chat message announces it). The pill's actual target — sticky
persistence-class errors — survives those overwrites by design
(diagnosticsPolicy) and will raise it.

## Gates

Editor suite 417 total / 1 known EditorCanvas env-split case; API suite 84
passed; tsc at baseline. Browser e2e: all three gates passed, zero console
errors across the session. Evidence in `browser-e2e/`.

## Follow-up candidates spotted (not in scope)

- Agent-quality: the gate's turn emitted DSL with an unsupported `parent`
  property (LUMD0212) and burned its repair budget — same family as the
  ref-grammar items; candidate for the grammar escalation/knowledge pass.
  (The turn still surfaced as an acceptable proposal via the
  completed_with_warnings mapping — the agent-quality track fix observed
  working live.)
- The accept → export-preview success path overwrites non-sticky advisory
  diagnostics in the shared slot; if advisory notes should outlive it,
  extend diagnosticsPolicy's sticky classes.
