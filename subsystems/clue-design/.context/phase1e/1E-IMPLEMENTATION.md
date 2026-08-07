# Phase 1e — Agent visibility of freehand state (completes Phase 1)

Date: 2026-07-03 · Branch: `agents/editing-roundtrip-v0` · Commit: `dad5456`
Plan: `.context/editing-research/PHASE-1-PLAN.md` §1e
**Closes deferred Phase-0 item 4. Phase 1 (1a–1e) is complete.**

## What shipped (all in `apps/agent_runtime/lumen_deepagent/`)

- **`_node_brief`** (tools.py) — every node brief the agent reads (page
  trees, slot bindings, diagnostic subtrees) now carries
  `position_mode`/`absolute_box`/`base_anchor` when the node is pinned and
  `layout_mode: "free"` when a container is Free. Surfaced **only when
  set**: managed briefs gain zero keys, so pre-freehand context stays
  byte-identical — the same skip-when-default discipline the engine's
  serde uses.
- **`_scene_summary`** — a `freehand` block (`pinned_nodes`,
  `free_containers`, one-line note) present only when the scene has
  freehand state. This flows into `curated_context` → the director sees
  "the human has pinned things here" at a glance before choosing an
  action mode.
- **`query_geometry`** (`inspect view="geometry"`) — pinned nodes report
  their pin alongside transform/size/computed.
- **`SEEDED_CONTINUATION_RECIPE`** (prompts.py) — the freehand rules ride
  every seeded author instruction:
  - `absolute_box` is human-owned page-space geometry; never move a
    pinned node (transform x/y are ignored while pinned — the box wins);
    design AROUND the pin.
  - Content/style edits on pinned nodes stay fair game (`#id text(...)`,
    colors, fonts).
  - `base_anchor` = where the layout had the node at detach; the offset
    to `absolute_box` is the human's deliberate nudge — intent, not error.
  - Free-container children are hand-placed: no re-stacking/re-flowing.
  - LUMV0800/0801/0902-4 warnings on freehand nodes are ADVISORY.

Note: the DSL cannot author the freehand fields (by design — pinning is
a human/editor act via the 1c structured edits), so the prompt rules are
about respecting state the agent can see but not create.

## Gates

4 new tests in `test_seeded_continuation.py` (§4 Phase 1e): briefs expose
the fields only-when-set and managed briefs gain no keys; the scene
summary surfaces and omits the freehand block correctly; `query_geometry`
shows the pin; the recipe carries the rules. **Full Python suite: 190
passed, 4 skipped.** Python-only change — no engine/editor surface
touched, no rebuilds needed.

## Phase 1 wrap-up

1a fields+parity → 1b solver honors pins (no snap-back) + clip policy →
1c invertible detach/reattach/convert ops → 1d editor unlock + gestures +
render policy (M1 interaction beat, browser-proven by an Opus 4.8 agent)
→ 1e agent visibility. The full loop now closes in both directions: the
human freehands on the agent's design without snap-back, and the agent
continues the design while treating the human's placements as intent.

## Natural next steps (Phase 2 / backlog, per MODA-EDITOR-PLAN)

- Live validation of the reconciliation story: a real seeded agent turn
  on a pinned scene (the sprint_fixtures `freehand_targets` +
  `targeted_edits` benchmark — deferred from 1b to here, now meaningful).
- `?document=` loader so accepted ops persist against real documents.
- Per-turn Compare/Revert on the stored edit_envelopes inverses.
- Deferred 1d fast-follows: pinned-drag guide snapping,
  auto-detach-on-drag, Free/Stack conversion UI.
- The PNG↔SVG image-fit disparity (its own item).
