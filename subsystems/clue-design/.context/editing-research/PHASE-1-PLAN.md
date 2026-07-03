# Phase 1 — Freehand editing core (implementation plan)

Source of truth: `MODA-EDITOR-PLAN.md` §4 Phase 1 (the backlog) + `STUDY.md` §3
(the line-anchored design). Anchors re-verified on `agents/editing-roundtrip-v0`
2026-07-03 — all accurate. Entry state: Phase 0 (0a/0b/0c) complete; the agent
round-trip + Accept/Reject gate work; the ONLY missing beat of Milestone M1 is
**a human dragging/resizing an auto-layout child** — that is exactly this phase.

## The design in one paragraph (STUDY §3, unchanged)

Per-node **`position_mode: Managed|Absolute`** + **`absolute_box: Option<Rect>`**
on `Node` is the spine (Stance A). Graft per-container **`layout_mode: Stack|Free`**
on `AutoLayoutProps` for "free this whole section" (Stance C). Graft **one**
reconciliation field **`base_anchor: Option<Rect>`** = the solved box captured at
detach, so the agent can later tell "human nudged this 12px off where I'd put it"
(Stance B's signal, as one field — NOT a separate override document, NOT a
scene→DSL emitter). The solver honors Absolute by a **one-line generalization of
the already-tested out-of-flow path** that rotation accidentally exercises today.

## Why this is low-risk

- `Node.effects` (`scene.rs:281`) is the exact byte-parity precedent: a
  `#[serde(default, skip_serializing_if = …)]` field added without shifting old
  `current_scene_json`. The new fields follow it verbatim.
- The solver already pulls a rotated auto-layout child out of flow and honors its
  transform (`is_out_of_flow_transform`, `layout.rs:1508`; routed at `:264`),
  proven by passing tests. Absolute rides the same seam — a branch, not a subsystem.
- Render needs **zero** change: `write_geometry` fills `computed.layout_bounds`
  from `absolute_box`, and `render_box_for_node` already prefers `computed`.

## Increments (do → check → decide, same rhythm as Phase 0)

### 1a — Data model + serde-parity GATE (engine; highest risk first, zero behavior)
- `scene.rs:269-295` — add to `Node` after `locked`: `position_mode: PositionMode`
  (`Managed` default), `absolute_box: Option<Rect>`, `base_anchor: Option<Rect>`,
  all `#[serde(default, skip_serializing_if = …)]`. Add `enum PositionMode`.
- `scene.rs:477` `AutoLayoutProps` — add `layout_mode: LayoutMode` (`Stack`
  default), serde-defaulted. Add `enum LayoutMode`.
- `operations.rs:103-126` — mirror the four fields in `NodePatch` (FieldPatch /
  OptionalFieldPatch), skip-when-unchanged.
- **GATE:** existing persisted scenes + the W6 conformance/parity fixtures round-
  trip **byte-identical**; old scenes deserialize with the right defaults. If not,
  the defaults are wrong — fix before anything else. Exit: parity green, no behavior.

### 1b — Solver honors the fields (engine) + the LUMV0801 policy call
**DONE 2026-07-03** — see `.context/phase1b/1B-IMPLEMENTATION.md`. All gates
green (12 new solver/policy tests; workspace 499; Python 186; editor 351/352
at the 1a baseline); browser-e2e on CanvasKit proves pin-lands / sibling-reflow /
page-edge clip (Moda behavior) / no-snap-back-on-relayout / undo-restores-pin.
Two flags for 1d: editor canvas lacks node-level `clip` painting (server Skia
has it); pinned-text LUMV0902-4 stay errors until the 1d resize decision.
- `layout.rs:264` — widen: `is_out_of_flow_transform(child) || child.position_mode
  == Absolute`, so an Absolute child leaves the Taffy flex-children list exactly
  like a rotated one.
- `layout.rs:340-357` (absolute-routing) — lay Absolute nodes at `absolute_box`
  (page space) instead of `origin + transform`; call `write_geometry` with that
  box so `computed.layout_bounds` is correct.
- `layout.rs:150` `layout_node_at` — when the container's `layout_mode == Free`,
  route its children through the absolute path (generalizes the kind-switch at
  `:157-169`).
- **DECISION (user, 2026-07-03): (a) downgrade→warning** for freehand nodes
  (Absolute, or child of a Free container) — same treatment for LUMV0800.
  User-verified against Moda: dragging a textbox past the page edge is honored
  and the overflow visually clips (screenshot in .context/attachments/qgfV8Q/).
  Managed/agent-owned content keeps today's hard error. Encode as a policy
  branch keyed on `position_mode`/`layout_mode`.
- Tests: a detached child lays out at its box and does **not** snap back; a Free
  container lays children at their baked transforms; managed siblings unaffected.

### 1c — Invertible ops (engine)
- Composite builders emitting `UpdateNode` patches:
  - `DetachToFreehand{node_id}`: read solved `computed.layout_bounds` → set
    `position_mode=Absolute`, `absolute_box`=that, `base_anchor`=that, bake
    Hug/Fill→Fixed from solved w/h.
  - `ReattachToLayout{node_id}`: clear `absolute_box`, `position_mode=Managed`.
  - `ConvertContainerToFree{node_id}` / `…ToStack`: set `layout_mode`; for Free,
    bake each child's `transform.x/y = computed - parent_origin`, `size=Fixed`.
- **Exact inverses in `inverse_for_operation` (`operations.rs:945`)** — Accept/Reject
  (0c) and future Compare/Revert ride on these. Test: detach→invert = byte-identical.

### 1d — Editor unlock + gestures (finishes Milestone M1)
- `sceneQueries.ts:183` `isNodeDirectGeometryEditable` — also true when
  `position_mode == Absolute` OR the parent container is `layout_mode == Free`.
- Point drag/resize commits (`canvasOperations.ts`) at `absolute_box` for Absolute
  nodes; `transformerMath.ts`/`gestureMachine.ts` are mode-agnostic (no change).
- Inspector X/Y/W/H live for Absolute; a **"Detach to freehand" / "Re-attach"**
  selection action.
- **DECISION (user, 2026-07-03):** explicit "Detach to freehand" toggle for v1;
  auto-detach-on-drag as the fast-follow.
- Browser e2e on **CanvasKit** (like 0c): detach an auto-layout child, drag it,
  confirm it stays; before/after render vs the fixtures.

### 1e — Agent visibility (closes deferred Phase-0 item 4)
- Extend `_node_brief` / `summarize_scene` (`tools.py`) to expose `position_mode`,
  `absolute_box`, `base_anchor`, container `layout_mode` — so the agent sees
  "human pinned this — preserve it" vs "I own this." Small prompt note (respect
  pinned boxes; use `base_anchor` to preserve offset across relayout).

## Sequencing & benchmark

Strict **1a → 1b → 1c → 1d → 1e** (each gates the next; 1a's parity result and 1b's
LUMV0801 call feed the rest). Commit + validate per increment. Benchmark: the
user's 3-fixture set at `apps/agent_runtime/evaluation/sprint_fixtures/`
(briefs+prompts with per-fixture `freehand_targets` / `targeted_edits`) as
before/after comparisons at 1b (solver still composes agent designs correctly)
and 1d (human freehand edits on those designs render correctly) — the same
do→check→decide discipline as Phase 0. Caveat from its README: the photo
fixture needs the LUMV0100 generate-before-page fix before it runs e2e.

## Risks (from STUDY §Validate-first / MODA §Risks)
- Serde byte-parity (gated in 1a).
- Editor↔server text-measurement parity when baking `absolute_box` — bake from the
  **canonical** pass (lumen-core), not the editor heuristic, so editor + preflight
  share it.
- LUMV0801 clip-overflow policy (decided in 1b).
- Semantic erosion on heavily-freehanded scenes — honest cost; `base_anchor` mitigates.

## Explicitly out of Phase 1 (deferred, per STUDY §Deferred)
Free-rect crop, reparent-on-drag with world-coordinate conversion (today MoveNode
jumps), multi-select group transform, scene→DSL emitter (never). The PNG↔SVG image
fit disparity is adjacent (persisted-fit is the same shape of work) but is its own
item — fold in only if it falls out naturally.
