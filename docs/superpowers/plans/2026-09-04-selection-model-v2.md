# Selection Model v2 (units, drill-down, deep select) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Every node on the ad canvas is reachable and movable by pointer, however deep: click selects the outermost unit (button or group) under the pointer or else the deepest element; double-click drills one level toward the pointer and opens the caret only when the selection is already the text; Cmd/Ctrl-click selects the deepest element directly and cycles through the stack on repeat; Alt-click and Escape walk up. Plan 3's "second click walks up" is removed because it cannot coexist with double-click drilling.

**Architecture:** All decisions stay pure in `adapter/scene-selection-ladder.ts` (renamed functions, same file) and `adapter/scene-text-edit.ts`'s double-click effect, proven over the harvested ad fixture; `scene-artifact-canvas.tsx` only routes events. The engine's hit stack (outer→inner) is the sole input. Drag geometry, freeze-on-grab (C-9), the lock, the hover outline and the inspector are unchanged.

**Tech Stack:** TypeScript / React (Next 16), `node:test` via `npx tsx --test`; no new dependency.

**Spec:** Founder rulings 2026-09-04 (chat): the six-rule model below, agreed after the Plan 3 review ("the current plan 3 implementation is not very practical enough"). Plan 3's memo `_memory/2026-09-04-plan3-selection-ladder.md` records what is being replaced.

## Global Constraints

- One Opus implementer per task; the controller reviews every diff and re-runs every test first-hand. Commit locally, never push, no AI attribution, never `git stash`; stage by explicit path (untracked golden PNGs live under `subsystems/clue-design`).
- Frontend only, under `apps/frontend/src/features/design-editor/`. Commands run from `apps/frontend`: `npx tsx --test <file>` for one file, `npm test` for all, `npm run lint` (React Compiler rules: no ref reads in JSX, derived values below every hook).
- The hit stack from the engine is outer→inner (`HitResult.stack`, last member = deepest). "Representable" keeps its AD2.5 meaning: `sceneSelectionFor(node, root) !== null` (a node with an inspector schema; the root frame is not).
- Plan 3's `buttonLabelId` / `isButtonShaped` (an auto-layout whose ONLY present child is text) stay as they are.
- No existing test outside the two files named in Tasks 1–2 changes; inside them, Plan 3's tests are rewritten to the new rules and each removed case is named in the commit body.

## The rules (founder, 2026-09-04)

- **R1 Click target.** Walk the stack outer→inner; the FIRST node that is a unit (a button-shaped auto-layout or a `group`) and representable is the target. If no unit is on the path, the target is the deepest representable node (`representableHit`). Pass-through containers (frames, non-button auto-layouts) never win a click while something deeper is under the pointer; they win only when the pointer is on their own empty area (they are then the deepest hit).
- **R2 Drill.** Double-click: with selection S and deepest representable hit D, if S is a proper ancestor of D, select the representable child of S on the path to D (the next level down). Otherwise, if S is D and D is text, open the caret (the lock and run-gate refusals as today). Otherwise nothing (the preceding pointer-down already selected the click target).
- **R3 Deep select.** Cmd/Ctrl-click selects D. If the current selection is already in the stack's representable list, it selects the next SHALLOWER representable node instead (cycle), wrapping from the outermost back to D. The press that follows drags whatever was selected. **Amendment (controller, after Task 1):** the root frame IS representable — `sceneSelectionFor` answers the *canvas* schema for it, not null — so the cycle would climb into the artboard. Ruling: the deep-select cycle EXCLUDES the root frame (Escape and Alt-click still reach it); it wraps from the outermost non-root node back to D. Walk-up and Escape keep Plan 3's behaviour (a direct child walks up to the root/canvas selection, then Escape clears).
- **R4 Walk up.** Alt-click walks up from the click target; Escape walks up from the selection and clears at the root. Unchanged from Plan 3. The "second click on the selected node walks up" rule and its 4 px slop are REMOVED.
- **R5 Hover.** The hover outline previews the R1 click target (unchanged rule, new function name).
- **R6 Drag.** A press drags the node the click selected (the click target, or the deep-select target). Freeze-on-grab stays. **Amendment (controller, Task 4 live proof):** a press on a node that is ALREADY selected keeps that selection and drags it, even when R1 would have resolved the click to an enclosing unit. Concretely: when the selected node is in the hit stack at or deeper than the R1 click target, the press target is the selection. Without this, the label reached by drill-down could never be dragged — the press re-selected the plate and moved it (found live on the Brex ad, document v98→v99, undone). An ancestor selection (the footer, above the plate) still yields the click target. The hover preview follows the same rule, so it never previews the plate while the label under the pointer is the selection.

### Task 3b (added after the Task 4 live proof): the press keeps the selection

**Files:**
- Modify: `apps/frontend/src/features/design-editor/adapter/scene-selection-ladder.ts` (new `selectionPressTarget`; `sceneHoverTarget` over it)
- Modify: `apps/frontend/src/features/design-editor/adapter/scene-selection-ladder.test.ts`
- Modify: `apps/frontend/src/features/design-editor/components/scene-artifact-canvas.tsx` (`handlePointerDown`'s plain-click branch)

**Interfaces:**
- Produces: `selectionPressTarget({ stack, scene, pageId, selectedNodeId }): NodeId | null` — the R1 click target, unless `selectedNodeId` sits in `stack` at an index ≥ the click target's index, in which case `selectedNodeId`. `sceneHoverTarget` returns `selectionPressTarget(...)` unless it equals the selection (then null).

- [ ] **Step 1: Tests** (append to the ladder test file)

```ts
it("R6: a press on the already-selected node keeps it, even inside a unit; an ancestor selection yields the click target", () => {
  const scene = sceneWithButton();
  const stack = ["frame_ad_root", "auto_row_copy", "text_headline"];
  // Nothing / something unrelated selected: the click target (the button).
  assert.equal(selectionPressTarget({ stack, scene, pageId: AD_PAGE_ID, selectedNodeId: null }), "auto_row_copy");
  assert.equal(selectionPressTarget({ stack, scene, pageId: AD_PAGE_ID, selectedNodeId: "group_proof" }), "auto_row_copy");
  // The label is selected (reached by drill-down): a press on it drags the LABEL.
  assert.equal(selectionPressTarget({ stack, scene, pageId: AD_PAGE_ID, selectedNodeId: "text_headline" }), "text_headline");
  // The button itself selected: the button.
  assert.equal(selectionPressTarget({ stack, scene, pageId: AD_PAGE_ID, selectedNodeId: "auto_row_copy" }), "auto_row_copy");
  // An ANCESTOR of the click target selected: the click target, not the ancestor.
  assert.equal(selectionPressTarget({ stack, scene, pageId: AD_PAGE_ID, selectedNodeId: "frame_ad_root" }), "auto_row_copy");
  // Hover follows the press rule and stays silent on the selection itself.
  assert.equal(sceneHoverTarget({ stack, scene, pageId: AD_PAGE_ID, selectedNodeId: "text_headline" }), null);
  assert.equal(sceneHoverTarget({ stack, scene, pageId: AD_PAGE_ID, selectedNodeId: "group_proof" }), "auto_row_copy");
});
```

- [ ] **Step 2: Implement**

```ts
/**
 * R6: what a plain press acts on. R1's click target — unless the node that is
 * ALREADY selected sits under the pointer at or below that target, in which
 * case the press keeps the selection and drags it. This is what makes a label
 * reached by drill-down movable: without it the press re-selected the button
 * and moved the button (Brex ad, live proof 2026-09-04). An ancestor selection
 * does not survive: pressing a child inside a selected container selects the
 * child, the ordinary R1 answer.
 */
export function selectionPressTarget({ stack, scene, pageId, selectedNodeId }: {
  stack: NodeId[]; scene: Scene; pageId: PageId | null; selectedNodeId: NodeId | null;
}): NodeId | null {
  const target = selectionClickTarget(stack, scene, pageId);
  if (target === null || selectedNodeId === null) {
    return target;
  }
  const selectedAt = stack.indexOf(selectedNodeId);
  return selectedAt >= stack.indexOf(target) ? selectedNodeId : target;
}
```

`sceneHoverTarget` calls `selectionPressTarget` with the same arguments and returns null when the answer equals `selectedNodeId`. In `handlePointerDown`, the non-modifier branch becomes `selectionPressTarget({ stack: result.stack, scene, pageId, selectedNodeId: activeSelectedNodeId })`; Alt-click keeps walking up from that target. The existing hover memo already passes `selectedNodeId`.

- [ ] **Step 3: Gates and commit** — the ladder test file, `npm run lint`, `npm test`; commit the three files with `feat(design-editor): a press on the selected node keeps it — the drilled label is draggable inside its button`.

---

### Task 1: The pure module — click target, drill, deep select

**Files:**
- Modify: `apps/frontend/src/features/design-editor/adapter/scene-selection-ladder.ts`
- Modify: `apps/frontend/src/features/design-editor/adapter/scene-selection-ladder.test.ts`

**Interfaces:**
- Produces: `isUnit(scene, nodeId): boolean`; `selectionClickTarget(stack, scene, pageId): NodeId | null` (replaces `selectionLadderHit`); `selectionDrillDown({ stack, scene, pageId, selectedNodeId }): NodeId | null`; `deepSelectTarget({ stack, scene, pageId, selectedNodeId }): NodeId | null`; `sceneHoverTarget` (unchanged signature, now over `selectionClickTarget`); `selectionWalkUp`, `escapeSelectionEffect`, `buttonLabelId`, `isButtonShaped` unchanged. `WALK_UP_CLICK_SLOP_PX` and `selectionLadderHit` are deleted.

- [ ] **Step 1: Rewrite the tests** (replace the file's Plan 3 cases; keep the `sceneWithButton` helper and the R1 button test)

```ts
import assert from "node:assert/strict";
import { it } from "node:test";
import type { Scene } from "../engine/scene/contracts";
import { AD_PAGE_ID, HARVESTED_AD_PAGE } from "./__fixtures__/scene-nodes";
import { representableHit } from "./scene-selection";
import {
  buttonLabelId,
  deepSelectTarget,
  escapeSelectionEffect,
  isButtonShaped,
  isUnit,
  sceneHoverTarget,
  selectionClickTarget,
  selectionDrillDown,
  selectionWalkUp,
} from "./scene-selection-ladder";

function clone(scene: Scene): Scene {
  return JSON.parse(JSON.stringify(scene)) as Scene;
}

/** `auto_row_copy` becomes a button: its only child is `text_headline`. */
function sceneWithButton(): Scene {
  const next = clone(HARVESTED_AD_PAGE);
  for (const node of Object.values(next.nodes)) {
    node.children = node.children.filter((id) => id !== "text_headline");
  }
  for (const page of Object.values(next.pages)) {
    page.children = page.children.filter((id) => id !== "text_headline");
  }
  next.nodes.auto_row_copy.children = ["text_headline"];
  return next;
}

it("R1: an auto-layout whose only child is text is button-shaped; the harvest's row is not", () => {
  const scene = sceneWithButton();
  assert.equal(isButtonShaped(scene, "auto_row_copy"), true);
  assert.equal(buttonLabelId(scene, "auto_row_copy"), "text_headline");
  assert.equal(isButtonShaped(HARVESTED_AD_PAGE, "auto_row_copy"), false);
  assert.equal(isButtonShaped(scene, "text_headline"), false);
  assert.equal(isButtonShaped(scene, "group_proof"), false);
});

it("units are buttons and groups; frames, stacks and leaves are pass-through", () => {
  const scene = sceneWithButton();
  assert.equal(isUnit(scene, "auto_row_copy"), true);
  assert.equal(isUnit(HARVESTED_AD_PAGE, "group_proof"), true);
  assert.equal(isUnit(HARVESTED_AD_PAGE, "auto_row_copy"), false);
  assert.equal(isUnit(HARVESTED_AD_PAGE, "frame_ad_root"), false);
  assert.equal(isUnit(HARVESTED_AD_PAGE, "text_proof_stat"), false);
});

it("R1 click: the OUTERMOST unit on the path wins; without a unit, the deepest representable node", () => {
  const scene = sceneWithButton();
  assert.equal(selectionClickTarget(["frame_ad_root", "auto_row_copy", "text_headline"], scene, AD_PAGE_ID), "auto_row_copy");
  // The harvest's row is not a unit but `group_proof` is: the group wins over its member.
  const stack = ["frame_ad_root", "auto_row_copy", "group_proof", "text_proof_stat"];
  assert.equal(representableHit(stack, HARVESTED_AD_PAGE, AD_PAGE_ID), "text_proof_stat");
  assert.equal(selectionClickTarget(stack, HARVESTED_AD_PAGE, AD_PAGE_ID), "group_proof");
  // No unit on the path: deepest representable.
  assert.equal(selectionClickTarget(["frame_ad_root", "auto_row_copy", "text_proof_stat"], HARVESTED_AD_PAGE, AD_PAGE_ID), "text_proof_stat");
  // A pass-through container is the target only on its own empty area.
  assert.equal(selectionClickTarget(["frame_ad_root", "auto_row_copy"], HARVESTED_AD_PAGE, AD_PAGE_ID), "auto_row_copy");
  assert.equal(selectionClickTarget([], HARVESTED_AD_PAGE, AD_PAGE_ID), null);
});

it("R2 drill: from an ancestor, one representable level toward the pointer; from the leaf, nothing", () => {
  const stack = ["frame_ad_root", "auto_row_copy", "group_proof", "text_proof_stat"];
  assert.equal(selectionDrillDown({ stack, scene: HARVESTED_AD_PAGE, pageId: AD_PAGE_ID, selectedNodeId: "auto_row_copy" }), "group_proof");
  assert.equal(selectionDrillDown({ stack, scene: HARVESTED_AD_PAGE, pageId: AD_PAGE_ID, selectedNodeId: "group_proof" }), "text_proof_stat");
  assert.equal(selectionDrillDown({ stack, scene: HARVESTED_AD_PAGE, pageId: AD_PAGE_ID, selectedNodeId: "text_proof_stat" }), null);
  // Not an ancestor of the hit: nothing to drill.
  assert.equal(selectionDrillDown({ stack, scene: HARVESTED_AD_PAGE, pageId: AD_PAGE_ID, selectedNodeId: "text_headline" }), null);
  assert.equal(selectionDrillDown({ stack, scene: HARVESTED_AD_PAGE, pageId: AD_PAGE_ID, selectedNodeId: null }), null);
  // The button: plate selected, a double-click on the label drills to the label.
  const button = sceneWithButton();
  assert.equal(selectionDrillDown({ stack: ["frame_ad_root", "auto_row_copy", "text_headline"], scene: button, pageId: AD_PAGE_ID, selectedNodeId: "auto_row_copy" }), "text_headline");
});

it("R3 deep select: the deepest node, then one shallower per repeat, wrapping to the deepest", () => {
  const stack = ["frame_ad_root", "auto_row_copy", "group_proof", "text_proof_stat"];
  const at = (selectedNodeId: string | null) =>
    deepSelectTarget({ stack, scene: HARVESTED_AD_PAGE, pageId: AD_PAGE_ID, selectedNodeId });
  assert.equal(at(null), "text_proof_stat");
  assert.equal(at("text_proof_stat"), "group_proof");
  assert.equal(at("group_proof"), "auto_row_copy");
  // The root frame is not representable, so the cycle wraps from the row.
  assert.equal(at("auto_row_copy"), "text_proof_stat");
  // A selection outside the stack starts over at the deepest.
  assert.equal(at("text_headline"), "text_proof_stat");
  assert.equal(deepSelectTarget({ stack: [], scene: HARVESTED_AD_PAGE, pageId: AD_PAGE_ID, selectedNodeId: null }), null);
});

it("R4 walk-up climbs to the nearest representable ancestor and stops at the root frame", () => {
  assert.equal(selectionWalkUp(HARVESTED_AD_PAGE, AD_PAGE_ID, "text_proof_stat"), "group_proof");
  assert.equal(selectionWalkUp(HARVESTED_AD_PAGE, AD_PAGE_ID, "group_proof"), "auto_row_copy");
  assert.equal(selectionWalkUp(HARVESTED_AD_PAGE, AD_PAGE_ID, "auto_row_copy"), null);
  assert.equal(selectionWalkUp(HARVESTED_AD_PAGE, AD_PAGE_ID, "nope"), null);
});

it("R5 hover: the click target, unless it is the selected node itself", () => {
  const stack = ["frame_ad_root", "auto_row_copy", "group_proof", "text_proof_stat"];
  assert.equal(sceneHoverTarget({ stack, scene: HARVESTED_AD_PAGE, pageId: AD_PAGE_ID, selectedNodeId: null }), "group_proof");
  assert.equal(sceneHoverTarget({ stack, scene: HARVESTED_AD_PAGE, pageId: AD_PAGE_ID, selectedNodeId: "group_proof" }), null);
});

it("Escape: a live gesture resets; a caret is left alone; otherwise the selection walks up, and clears at the root", () => {
  const base = { scene: HARVESTED_AD_PAGE, pageId: AD_PAGE_ID };
  assert.deepEqual(escapeSelectionEffect({ ...base, gestureLive: true, textEditing: false, selectedNodeId: "group_proof" }), { kind: "reset-gesture" });
  assert.deepEqual(escapeSelectionEffect({ ...base, gestureLive: false, textEditing: true, selectedNodeId: "group_proof" }), { kind: "none" });
  assert.deepEqual(escapeSelectionEffect({ ...base, gestureLive: false, textEditing: false, selectedNodeId: "text_proof_stat" }), { kind: "select", nodeId: "group_proof" });
  assert.deepEqual(escapeSelectionEffect({ ...base, gestureLive: false, textEditing: false, selectedNodeId: "auto_row_copy" }), { kind: "select", nodeId: null });
});
```

Read the existing test file first: keep any Plan 3 Escape / walk-up assertions that the fixture supports verbatim where they still hold, and check the fixture's real ancestry (`text_proof_stat` under `group_proof` under `auto_row_copy` under `frame_ad_root`; if the memo's chain differs, use the fixture's) before trusting the ids above.

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd apps/frontend && npx tsx --test src/features/design-editor/adapter/scene-selection-ladder.test.ts 2>&1 | tail -8`
Expected: fails on the missing exports (`isUnit`, `selectionClickTarget`, `selectionDrillDown`, `deepSelectTarget`).

- [ ] **Step 3: Implement**

Replace the module's ladder functions (keep `presentChildren`, `isButtonShaped`, `buttonLabelId`, `representable`, `selectionWalkUp`, `escapeSelectionEffect`; delete `WALK_UP_CLICK_SLOP_PX` and `selectionLadderHit`); rewrite the header docblock to the six rules:

```ts
/** R1: a node the click treats as one thing — a button (Plan 3's shape) or a group. */
export function isUnit(scene: Scene, nodeId: NodeId): boolean {
  const node = scene.nodes[nodeId];
  if (!node) {
    return false;
  }
  return node.kind.kind === "group" || isButtonShaped(scene, nodeId);
}

/** The stack's representable members, outer→inner. */
function representableStack(stack: NodeId[], scene: Scene, pageId: PageId | null): NodeId[] {
  return stack.filter((id) => representable(scene, pageId, id));
}

/**
 * R1: the click target. The OUTERMOST representable unit on the path wins; a
 * path without a unit selects the deepest representable node. Pass-through
 * containers therefore win a click only on their own empty area, where they
 * are the deepest hit.
 */
export function selectionClickTarget(stack: NodeId[], scene: Scene, pageId: PageId | null): NodeId | null {
  const candidates = representableStack(stack, scene, pageId);
  const unit = candidates.find((id) => isUnit(scene, id));
  return unit ?? candidates[candidates.length - 1] ?? null;
}

/**
 * R2: one level down toward the pointer — the representable child of the
 * selection on the path to the deepest hit. Null when the selection is not a
 * proper ancestor of the hit (nothing to drill into).
 */
export function selectionDrillDown({ stack, scene, pageId, selectedNodeId }: {
  stack: NodeId[]; scene: Scene; pageId: PageId | null; selectedNodeId: NodeId | null;
}): NodeId | null {
  if (selectedNodeId === null) {
    return null;
  }
  const candidates = representableStack(stack, scene, pageId);
  const at = stack.indexOf(selectedNodeId);
  if (at === -1 || at === stack.length - 1) {
    return null;
  }
  return candidates.find((id) => stack.indexOf(id) > at) ?? null;
}

/**
 * R3: Cmd/Ctrl-click — the deepest representable node; when the selection is
 * already one of the stack's representable members, the next SHALLOWER one,
 * wrapping from the outermost back to the deepest.
 */
export function deepSelectTarget({ stack, scene, pageId, selectedNodeId }: {
  stack: NodeId[]; scene: Scene; pageId: PageId | null; selectedNodeId: NodeId | null;
}): NodeId | null {
  const candidates = representableStack(stack, scene, pageId);
  if (candidates.length === 0) {
    return null;
  }
  const deepest = candidates[candidates.length - 1];
  const at = selectedNodeId === null ? -1 : candidates.indexOf(selectedNodeId);
  if (at === -1) {
    return deepest;
  }
  return at === 0 ? deepest : candidates[at - 1];
}
```

`sceneHoverTarget` calls `selectionClickTarget`. Write the docblocks in the file's voice (why, then what); name Plan 3's removed rule and this plan's date.

- [ ] **Step 4: Run the tests**

Run: `cd apps/frontend && npx tsx --test src/features/design-editor/adapter/scene-selection-ladder.test.ts 2>&1 | tail -6`
Expected: all pass. (`npm test` will fail on the callers until Tasks 2–3 land; that is expected between tasks.)

- [ ] **Step 5: Commit**

```bash
git add apps/frontend/src/features/design-editor/adapter/scene-selection-ladder.ts apps/frontend/src/features/design-editor/adapter/scene-selection-ladder.test.ts
git commit -m "feat(design-editor): selection model v2 decisions — outermost unit on click, drill one level, deep select with cycling

Replaces Plan 3's ladder decisions: the click target is the outermost unit
(button or group) on the path or else the deepest node; double-click drills one
representable level toward the pointer; Cmd/Ctrl-click deep-selects and cycles
shallower. The second-click walk-up and its 4 px slop are removed (they cannot
coexist with double-click drilling). Removed tests: button-first (superseded by
R1), same-spot slop."
```

---

### Task 2: Double-click = drill, then caret

**Files:**
- Modify: `apps/frontend/src/features/design-editor/adapter/scene-text-edit.ts` (`sceneDoubleClickEffect` ~line 149–191 and its docblock ~line 100–148)
- Modify: `apps/frontend/src/features/design-editor/adapter/scene-text-edit.test.ts` (the double-click cases ~line 100–290)

**Interfaces:**
- Consumes: `selectionDrillDown`, `selectionClickTarget` (Task 1), `representableHit`.
- Produces: `sceneDoubleClickEffect({ gestureDisabled, stack, pageId, scene, selectedNodeId })` — the `nodeId` input becomes `stack: NodeId[]` + `pageId: PageId | null`; the effect union is unchanged (`edit` / `select` / `locked` / `none`).

- [ ] **Step 1: Rewrite the double-click tests.** Keep the fixtures and helpers; replace the Plan 3 and drill-out cases with:

```ts
const stackToHeadline = ["frame_ad_root", "auto_row_copy", "text_headline"];
const stackToStat = ["frame_ad_root", "auto_row_copy", "group_proof", "text_proof_stat"];

test("R2: a double-click on a selected text node opens an edit session on it", () => {
  assert.deepEqual(
    sceneDoubleClickEffect({ gestureDisabled: false, stack: stackToStat, pageId: AD_PAGE_ID, scene: HARVESTED_AD_PAGE, selectedNodeId: "text_proof_stat" }),
    { kind: "edit", nodeId: "text_proof_stat" },
  );
});

test("R2: with an ancestor selected, a double-click drills one level and opens no caret", () => {
  assert.deepEqual(
    sceneDoubleClickEffect({ gestureDisabled: false, stack: stackToStat, pageId: AD_PAGE_ID, scene: HARVESTED_AD_PAGE, selectedNodeId: "auto_row_copy" }),
    { kind: "select", nodeId: "group_proof" },
  );
  assert.deepEqual(
    sceneDoubleClickEffect({ gestureDisabled: false, stack: stackToStat, pageId: AD_PAGE_ID, scene: HARVESTED_AD_PAGE, selectedNodeId: "group_proof" }),
    { kind: "select", nodeId: "text_proof_stat" },
  );
});

test("R2: the button — plate selected drills to the label; label selected opens the caret", () => {
  const scene = sceneWithButton();
  assert.deepEqual(
    sceneDoubleClickEffect({ gestureDisabled: false, stack: stackToHeadline, pageId: AD_PAGE_ID, scene, selectedNodeId: "auto_row_copy" }),
    { kind: "select", nodeId: "text_headline" },
  );
  assert.deepEqual(
    sceneDoubleClickEffect({ gestureDisabled: false, stack: stackToHeadline, pageId: AD_PAGE_ID, scene, selectedNodeId: "text_headline" }),
    { kind: "edit", nodeId: "text_headline" },
  );
});

test("the caret's refusals hold: a locked node decides nothing, a locked run says so", () => {
  const scene = sceneWithButton();
  scene.nodes.text_headline.locked = true;
  assert.deepEqual(
    sceneDoubleClickEffect({ gestureDisabled: false, stack: stackToHeadline, pageId: AD_PAGE_ID, scene, selectedNodeId: "text_headline" }),
    { kind: "none" },
  );
  assert.deepEqual(
    sceneDoubleClickEffect({ gestureDisabled: true, stack: stackToHeadline, pageId: AD_PAGE_ID, scene: sceneWithButton(), selectedNodeId: "text_headline" }),
    { kind: "locked" },
  );
});

test("a double-click whose selection is neither the hit nor its ancestor re-selects the click target", () => {
  assert.deepEqual(
    sceneDoubleClickEffect({ gestureDisabled: false, stack: stackToStat, pageId: AD_PAGE_ID, scene: HARVESTED_AD_PAGE, selectedNodeId: "text_headline" }),
    { kind: "select", nodeId: "group_proof" },
  );
});

test("a double-click on nothing, or with no scene, decides nothing", () => {
  assert.deepEqual(sceneDoubleClickEffect({ gestureDisabled: false, stack: [], pageId: AD_PAGE_ID, scene: HARVESTED_AD_PAGE, selectedNodeId: "group_proof" }), { kind: "none" });
  assert.deepEqual(sceneDoubleClickEffect({ gestureDisabled: false, stack: stackToStat, pageId: AD_PAGE_ID, scene: null, selectedNodeId: null }), { kind: "none" });
});
```

Delete the drill-OUT tests ("a non-text hit drills out to its top-level container", "a hit that is already top-level drills nowhere", "a double-click on nothing drills out from the current selection", "a double-click on nothing with nothing selected decides nothing", the three "Plan 3:" cases) and rewrite "selection-for-inspection survives the lock: the drill-out still works" to the new rule (a locked run still DRILLS — selection is not a write — but refuses the caret). Keep every non-double-click test untouched.

- [ ] **Step 2: Run to verify they fail**

Run: `cd apps/frontend && npx tsx --test src/features/design-editor/adapter/scene-text-edit.test.ts 2>&1 | grep -E "^ℹ (tests|pass|fail)"`
Expected: the new cases fail (old signature).

- [ ] **Step 3: Implement**

```ts
export function sceneDoubleClickEffect({ gestureDisabled, stack, pageId, scene, selectedNodeId }: {
  gestureDisabled: boolean;
  /** The engine's hit stack under the double-click, outer→inner; empty for nothing. */
  stack: NodeId[];
  pageId: PageId | null;
  scene: Scene | null;
  selectedNodeId: NodeId | null;
}): SceneDoubleClickEffect {
  if (!scene) {
    return { kind: "none" };
  }
  const deepest = representableHit(stack, scene, pageId);
  if (deepest === null) {
    return { kind: "none" };
  }
  // R2, first: one level toward the pointer. Selection is never a write, so a
  // locked run still drills — only the caret below is gated.
  const drill = selectionDrillDown({ stack, scene, pageId, selectedNodeId });
  if (drill !== null) {
    return { kind: "select", nodeId: drill };
  }
  const selected = getNode(scene, selectedNodeId);
  if (selected && selected.id === deepest && selected.kind.kind === "text") {
    if (selected.locked) {
      return { kind: "none" };
    }
    if (gestureDisabled) {
      return { kind: "locked" };
    }
    return { kind: "edit", nodeId: selected.id };
  }
  // Neither the hit nor its ancestor is selected (the pointer-down that
  // preceded us normally made that true): re-sync to the click target.
  const target = selectionClickTarget(stack, scene, pageId);
  return target !== null && target !== selectedNodeId ? { kind: "select", nodeId: target } : { kind: "none" };
}
```

Rewrite the docblock: Rung B's "drills out to its top-level container" is superseded by R2 (drill IN one level); keep the lock/C-9 paragraphs that still hold. Drop the `topLevelAncestorId` and `buttonLabelId` imports if unused.

- [ ] **Step 4: Run the file's tests**

Run: `cd apps/frontend && npx tsx --test src/features/design-editor/adapter/scene-text-edit.test.ts 2>&1 | grep -E "^ℹ (tests|pass|fail)"`
Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add apps/frontend/src/features/design-editor/adapter/scene-text-edit.ts apps/frontend/src/features/design-editor/adapter/scene-text-edit.test.ts
git commit -m "feat(design-editor): double-click drills one level toward the pointer, then opens the caret

Rung B's drill-out to the top-level container and Plan 3's button shortcut are
replaced by the founder's rule: with an ancestor selected a double-click selects
the next level under the pointer; with the text itself selected it opens the
caret (lock and run-gate refusals unchanged). Removed tests: the four drill-out
cases and the three Plan 3 button cases (superseded)."
```

---

### Task 3: Canvas wiring — deep select in, second-click walk-up out

**Files:**
- Modify: `apps/frontend/src/features/design-editor/components/scene-artifact-canvas.tsx` (imports ~line 60–64; `walkUpRef` ~line 1276–1281 and its reset in `resetGesture` ~line 1316; `handlePointerUp` ~line 1541–1560; the hover memo ~line 1505–1512; `handlePointerDown` ~line 1777–1795; `handleDoubleClick` ~line 1852–1873; the gesture-host docblock ~line 1680–1700)

**Interfaces:**
- Consumes: Task 1's `selectionClickTarget`, `deepSelectTarget`, `selectionWalkUp`, `sceneHoverTarget`, `escapeSelectionEffect`; Task 2's `sceneDoubleClickEffect(stack, pageId, …)`.

- [ ] **Step 1: Rewire**
  - Imports: drop `WALK_UP_CLICK_SLOP_PX`, `selectionLadderHit`; add `deepSelectTarget`, `selectionClickTarget`.
  - Delete `walkUpRef`, its reset line in `resetGesture`, and the whole "Plan 3 R3: the second click …" block in `handlePointerUp` (the `candidate` logic). Nothing else in `handlePointerUp` changes.
  - `handlePointerDown`, after the hit test:

```tsx
    // R3: Cmd/Ctrl-click deep-selects (and cycles shallower on repeat);
    // otherwise R1's click target. Either way the press that follows drags
    // what was just selected (R6).
    const hitNodeId = event.metaKey || event.ctrlKey
      ? deepSelectTarget({ stack: result.stack, scene, pageId, selectedNodeId: activeSelectedNodeId })
      : selectionClickTarget(result.stack, scene, pageId);
    // R4: Alt/Option-click walks up from the click target and starts no press.
    if (event.altKey && hitNodeId !== null) {
      commitSelection(selectionWalkUp(scene, pageId, hitNodeId) ?? hitNodeId);
      return;
    }
```

  and the rest of the handler as it is (press target, lock notice, freeze, `beginPress`). Verify that `modifiersOf(event).meta` reaching the gesture machine on a Cmd-click press changes nothing about the drag (read the reducer's use of `meta`); if it does anything, report it rather than masking the modifier.
  - `handleDoubleClick`: pass `stack: result ? result.stack : []` and `pageId` to `sceneDoubleClickEffect` instead of `nodeId`.
  - Hover memo: `sceneHoverTarget` call unchanged (its rule is now R1).
  - Update the gesture-host docblock's ladder lines (R1–R6 in one short paragraph; note Plan 3's second-click walk-up is gone and why).

- [ ] **Step 2: Gates**

Run: `cd apps/frontend && npm run lint 2>&1 | tail -4 && npm test 2>&1 | tail -5`
Expected: lint 0 errors (2 pre-existing warnings); all tests pass (one pre-existing jsdom skip). `grep -rn "WALK_UP_CLICK_SLOP_PX\|selectionLadderHit\|walkUpRef" apps/frontend/src` returns nothing.

- [ ] **Step 3: Commit**

```bash
git add apps/frontend/src/features/design-editor/components/scene-artifact-canvas.tsx
git commit -m "feat(design-editor): canvas selection v2 — Cmd/Ctrl deep select, drill on double-click, second-click walk-up removed

Click resolves to the outermost unit or the deepest node; Cmd/Ctrl-click
deep-selects and cycles; double-click hands the engine's stack to the
drill-then-caret rule; Alt-click and Escape keep walking up. The Plan 3
same-spot second-click walk-up is removed because a double-click is two clicks
at one spot."
```

---

### Task 4: Live proof and records (controller)

- [ ] On the Brex ad (`doc_f866806343…`, whose `cta_plate` is a proper button) and the Apollo ad: click the CTA → plate; double-click → label selected (`data-scene-selection-outline` = label, no caret); double-click again → caret; Escape → caret closes; Cmd-click on the label → label; Cmd-click again → plate; Cmd-click again → the plate's parent; Alt-click → parent; a press-drag on the selected label moves it inside the plate (freeze-on-grab), document version advances by one; click on the Apollo group's dot → the group; double-click → the dot. Screenshots to `/tmp/plan5-evidence-keep/`.
- [ ] Memo `_memory/2026-09-04-selection-model-v2.md`; amend `_memory/2026-09-04-plan3-selection-ladder.md` with a superseded note; roadmap header line.
