# Selection Ladder — Implementation Plan (Editor Quality Plan 3)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** On the scene (ad) canvas, a button is selected as one unit on the first click and its label edited on double-click, a second click / Alt-click / Escape walks the selection up one ancestor, and a hover outline shows the click target before the click.

**Architecture:** Frontend only, engine untouched. One new pure module, `adapter/scene-selection-ladder.ts`, holds every decision (button shape, ladder hit, walk-up, hover target, Escape effect, breadcrumb ancestry) and is unit-tested over the harvested ad fixture. `sceneDoubleClickEffect` learns the button rule. `scene-artifact-canvas.tsx` wires the decisions into its existing pointer-down / pointer-up / pointer-move / Escape handlers and renders the hover outline through the existing `SelectionChrome` with a `variant="hover"`. `representableHit` keeps its contract for its other consumers; the canvas's pointer paths switch to `selectionLadderHit`.

**Tech Stack:** TypeScript, React 19 (React Compiler lint active), node:test via `npx tsx --test`; no new dependencies.

**Spec:** `docs/superpowers/plans/2026-09-04-editor-quality-roadmap.md` — Plan 3, item E (root cause verified there).

## Global Constraints

- Frontend gate from `apps/frontend`: `npm run design-system:build && npm run lint && npm run build`; lint has exactly 2 pre-existing warnings (`snapPosition`, `snapExtent`) and 0 errors — record before/after. Unit tests: `npx tsx --test <file>`; design-editor glob `npx tsx --test "src/features/design-editor/**/*.test.ts"`.
- Rulings (controller, 2026-09-04): **R1** a *button-shaped* container is a node with `kind.kind === "auto_layout"` whose children (those present in the scene) are exactly ONE node with `kind.kind === "text"`. **R2** walk-up = the nearest REPRESENTABLE ancestor (`sceneSelectionFor(node, rootFrameId) !== null`); the root frame is the ceiling — walking up from it yields `null`. **R3** the three walk-up gestures: a click that lands (via the ladder) on the node that is ALREADY selected and ends without a drag (pointer travelled < 4 px and no preview was shown); Alt/Option-click (walks up from the ladder hit, no press starts); Escape when no gesture is live and no caret is open (at the root frame Escape CLEARS the selection). **R4** hover outline = same colour as the selection outline (`SELECTION_OUTLINE_COLOR`), stroke 1, `strokeOpacity` 0.55, no handles, never drawn on the selected node itself, `data-scene-hover-outline` attribute, `pointer-events: none` like the selection chrome. **R5** the inspector breadcrumb is NEW inspector UI: only its pure ancestry helper ships in this plan; rendering waits for a founder-approved preview (same gate as Plan 4 item G). The Layers section already offers ancestor selection by click.
- No new copy anywhere. No engine (Rust/wasm) change. `representableHit`'s behaviour and tests stay untouched.
- Commit locally per task with the message given; never push; no AI attribution trailers; never `git stash`.

---

### Task 1: The pure ladder module

**Files:**
- Create: `apps/frontend/src/features/design-editor/adapter/scene-selection-ladder.ts`
- Test: `apps/frontend/src/features/design-editor/adapter/scene-selection-ladder.test.ts`

**Interfaces:**
- Consumes: `representableHit(stack, scene, pageId)` from `./scene-selection`; `rootFrameId(scene, pageId)`, `sceneSelectionFor(node, rootFrameId)` from `./scene-hydrate`; `parentInfoForNode(scene, nodeId)`, `nodeDisplayName(node)` from `../engine/scene/sceneQueries`; fixture `HARVESTED_AD_PAGE`, `AD_PAGE_ID` from `./__fixtures__/scene-nodes` (hierarchy: `frame_ad_root` › `auto_row_copy` (auto_layout "Copy row") › `group_proof` › `text_proof_stat`; `text_headline` is a text node elsewhere in the tree).
- Produces (all exported):
  - `isButtonShaped(scene: Scene, nodeId: NodeId): boolean`
  - `buttonLabelId(scene: Scene, nodeId: NodeId): NodeId | null` — the single text child of a button-shaped node, else null.
  - `selectionLadderHit(stack: NodeId[], scene: Scene, pageId: PageId | null): NodeId | null`
  - `selectionWalkUp(scene: Scene, pageId: PageId | null, nodeId: NodeId): NodeId | null`
  - `sceneHoverTarget(args: { stack: NodeId[]; scene: Scene; pageId: PageId | null; selectedNodeId: NodeId | null }): NodeId | null`
  - `escapeSelectionEffect(args: { gestureLive: boolean; textEditing: boolean; selectedNodeId: NodeId | null; scene: Scene | null; pageId: PageId | null }): { kind: "reset-gesture" } | { kind: "select"; nodeId: NodeId | null } | { kind: "none" }`
  - `selectionBreadcrumb(scene: Scene, pageId: PageId | null, nodeId: NodeId | null): { nodeId: NodeId; label: string }[]`
  - `WALK_UP_CLICK_SLOP_PX = 4`

- [ ] **Step 1: Write the failing tests**

```ts
import assert from "node:assert/strict";
import { it } from "node:test";
import type { Scene } from "../engine/scene/contracts";
import { AD_PAGE_ID, HARVESTED_AD_PAGE } from "./__fixtures__/scene-nodes";
import { representableHit } from "./scene-selection";
import {
  WALK_UP_CLICK_SLOP_PX,
  buttonLabelId,
  escapeSelectionEffect,
  isButtonShaped,
  sceneHoverTarget,
  selectionBreadcrumb,
  selectionLadderHit,
  selectionWalkUp,
} from "./scene-selection-ladder";

/**
 * Editor Quality Plan 3 (item E): the selection ladder. Every case runs over
 * the harvested ad; the one shape the harvest lacks — a BUTTON, an auto-layout
 * whose only child is text — is made by moving the real headline into the real
 * copy row (AD2.4's one-field-edit technique), never by inventing a node.
 */

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
  assert.equal(buttonLabelId(HARVESTED_AD_PAGE, "auto_row_copy"), null);
  // A text node, a group and the root frame are never buttons.
  assert.equal(isButtonShaped(scene, "text_headline"), false);
  assert.equal(isButtonShaped(scene, "group_proof"), false);
  assert.equal(isButtonShaped(scene, "frame_ad_root"), false);
});

it("button-first: a hit on the label selects the BUTTON, while representableHit still says the label", () => {
  const scene = sceneWithButton();
  const stack = ["frame_ad_root", "auto_row_copy", "text_headline"];
  assert.equal(representableHit(stack, scene, AD_PAGE_ID), "text_headline");
  assert.equal(selectionLadderHit(stack, scene, AD_PAGE_ID), "auto_row_copy");
});

it("everything else keeps deepest-leaf first click", () => {
  // The harvest's row is not a button, so its text descendant wins as before.
  const stack = ["frame_ad_root", "auto_row_copy", "group_proof", "text_proof_stat"];
  assert.equal(selectionLadderHit(stack, HARVESTED_AD_PAGE, AD_PAGE_ID), "text_proof_stat");
  assert.equal(selectionLadderHit([], HARVESTED_AD_PAGE, AD_PAGE_ID), null);
  assert.equal(selectionLadderHit(["line_divider"], HARVESTED_AD_PAGE, AD_PAGE_ID), null);
});

it("R2: walk-up climbs to the nearest representable ancestor and stops at the root frame", () => {
  assert.equal(selectionWalkUp(HARVESTED_AD_PAGE, AD_PAGE_ID, "text_proof_stat"), "group_proof");
  assert.equal(selectionWalkUp(HARVESTED_AD_PAGE, AD_PAGE_ID, "group_proof"), "auto_row_copy");
  assert.equal(selectionWalkUp(HARVESTED_AD_PAGE, AD_PAGE_ID, "auto_row_copy"), "frame_ad_root");
  assert.equal(selectionWalkUp(HARVESTED_AD_PAGE, AD_PAGE_ID, "frame_ad_root"), null);
  assert.equal(selectionWalkUp(HARVESTED_AD_PAGE, AD_PAGE_ID, "no_such_node"), null);
});

it("hover: the ladder hit, unless it is the selected node itself", () => {
  const stack = ["frame_ad_root", "auto_row_copy", "group_proof", "text_proof_stat"];
  assert.equal(
    sceneHoverTarget({ stack, scene: HARVESTED_AD_PAGE, pageId: AD_PAGE_ID, selectedNodeId: null }),
    "text_proof_stat",
  );
  assert.equal(
    sceneHoverTarget({ stack, scene: HARVESTED_AD_PAGE, pageId: AD_PAGE_ID, selectedNodeId: "text_proof_stat" }),
    null,
  );
  // Over a button, the hover target is the button (what a click would select).
  const scene = sceneWithButton();
  assert.equal(
    sceneHoverTarget({
      stack: ["frame_ad_root", "auto_row_copy", "text_headline"],
      scene,
      pageId: AD_PAGE_ID,
      selectedNodeId: null,
    }),
    "auto_row_copy",
  );
  assert.equal(
    sceneHoverTarget({ stack: [], scene: HARVESTED_AD_PAGE, pageId: AD_PAGE_ID, selectedNodeId: null }),
    null,
  );
});

it("R3 Escape: a live gesture resets; a caret is left alone; otherwise the selection walks up, and clears at the root", () => {
  const base = { scene: HARVESTED_AD_PAGE, pageId: AD_PAGE_ID };
  assert.deepEqual(
    escapeSelectionEffect({ ...base, gestureLive: true, textEditing: false, selectedNodeId: "group_proof" }),
    { kind: "reset-gesture" },
  );
  assert.deepEqual(
    escapeSelectionEffect({ ...base, gestureLive: false, textEditing: true, selectedNodeId: "group_proof" }),
    { kind: "none" },
  );
  assert.deepEqual(
    escapeSelectionEffect({ ...base, gestureLive: false, textEditing: false, selectedNodeId: "group_proof" }),
    { kind: "select", nodeId: "auto_row_copy" },
  );
  assert.deepEqual(
    escapeSelectionEffect({ ...base, gestureLive: false, textEditing: false, selectedNodeId: "frame_ad_root" }),
    { kind: "select", nodeId: null },
  );
  assert.deepEqual(
    escapeSelectionEffect({ ...base, gestureLive: false, textEditing: false, selectedNodeId: null }),
    { kind: "none" },
  );
  assert.deepEqual(
    escapeSelectionEffect({ scene: null, pageId: null, gestureLive: false, textEditing: false, selectedNodeId: "x" }),
    { kind: "none" },
  );
});

it("breadcrumb: representable ancestry from the root frame down to the node, with display names", () => {
  const crumbs = selectionBreadcrumb(HARVESTED_AD_PAGE, AD_PAGE_ID, "text_proof_stat");
  assert.deepEqual(
    crumbs.map((crumb) => crumb.nodeId),
    ["frame_ad_root", "auto_row_copy", "group_proof", "text_proof_stat"],
  );
  assert.equal(crumbs[1].label, "Copy row");
  assert.deepEqual(selectionBreadcrumb(HARVESTED_AD_PAGE, AD_PAGE_ID, null), []);
  assert.deepEqual(selectionBreadcrumb(HARVESTED_AD_PAGE, AD_PAGE_ID, "no_such_node"), []);
});

it("the same-spot walk-up slop is four screen pixels", () => {
  assert.equal(WALK_UP_CLICK_SLOP_PX, 4);
});
```

- [ ] **Step 2: Run to verify failure**

Run (from `apps/frontend`): `npx tsx --test src/features/design-editor/adapter/scene-selection-ladder.test.ts`
Expected: fails to import `./scene-selection-ladder`.

If a fixture fact differs (e.g. `text_headline` is not where assumed, or `auto_row_copy.name` is not "Copy row"), read `__fixtures__/scene-nodes.ts`, fix the TEST's expectation to the fixture's truth and record it — do not change the fixture.

- [ ] **Step 3: Implement**

```ts
import type { NodeId, PageId, Scene } from "../engine/scene/contracts";
import { nodeDisplayName, parentInfoForNode } from "../engine/scene/sceneQueries";
import { rootFrameId, sceneSelectionFor } from "./scene-hydrate";
import { representableHit } from "./scene-selection";

/**
 * Editor Quality Plan 3 (item E) — the selection ladder, as pure decisions.
 *
 * `representableHit` (AD2.5) picks the topmost node under the pointer that has
 * an inspector schema. Inside a button that is always the label text, so the
 * button itself was selectable only in its padding; there was no hover
 * feedback and no way to reach a parent from the canvas. This module adds the
 * rungs the roadmap ruled: button-as-a-unit on the first click, walk-up
 * (second click / Alt-click / Escape), a hover target, and the breadcrumb's
 * ancestry. The component around it owns events; everything decidable is
 * decided here and proven over the harvested ad.
 */

/** Pointer travel (screen px) under which a press-and-release counts as a click. */
export const WALK_UP_CLICK_SLOP_PX = 4;

function presentChildren(scene: Scene, nodeId: NodeId): NodeId[] {
  const node = scene.nodes[nodeId];
  return node ? node.children.filter((id) => scene.nodes[id] !== undefined) : [];
}

/** R1: an auto-layout whose ONLY child is a text node. */
export function isButtonShaped(scene: Scene, nodeId: NodeId): boolean {
  return buttonLabelId(scene, nodeId) !== null;
}

/** The button's label — its single text child — or null when `nodeId` is not a button. */
export function buttonLabelId(scene: Scene, nodeId: NodeId): NodeId | null {
  const node = scene.nodes[nodeId];
  if (!node || node.kind.kind !== "auto_layout") {
    return null;
  }
  const children = presentChildren(scene, nodeId);
  if (children.length !== 1) {
    return null;
  }
  return scene.nodes[children[0]].kind.kind === "text" ? children[0] : null;
}

function representable(scene: Scene, pageId: PageId | null, nodeId: NodeId): boolean {
  const node = scene.nodes[nodeId];
  if (!node) {
    return false;
  }
  const root = pageId ? rootFrameId(scene, pageId) : null;
  return sceneSelectionFor(node, root) !== null;
}

/**
 * The first-click selection: `representableHit`, promoted to the parent when
 * the hit is a button's label and the button is itself representable.
 */
export function selectionLadderHit(
  stack: NodeId[],
  scene: Scene,
  pageId: PageId | null,
): NodeId | null {
  const hit = representableHit(stack, scene, pageId);
  if (hit === null) {
    return null;
  }
  const node = scene.nodes[hit];
  if (node?.kind.kind !== "text") {
    return hit;
  }
  const info = parentInfoForNode(scene, hit);
  if (!info || info.parent.kind !== "node") {
    return hit;
  }
  const parentId = info.parent.id;
  if (buttonLabelId(scene, parentId) === hit && representable(scene, pageId, parentId)) {
    return parentId;
  }
  return hit;
}

/** R2: the nearest representable ancestor; null from the root frame or an unknown node. */
export function selectionWalkUp(
  scene: Scene,
  pageId: PageId | null,
  nodeId: NodeId,
): NodeId | null {
  let current: NodeId = nodeId;
  if (!scene.nodes[current]) {
    return null;
  }
  for (;;) {
    const info = parentInfoForNode(scene, current);
    if (!info || info.parent.kind !== "node") {
      return null;
    }
    if (representable(scene, pageId, info.parent.id)) {
      return info.parent.id;
    }
    current = info.parent.id;
  }
}

/** R4: what the hover outline shows — the click target, unless it is already selected. */
export function sceneHoverTarget({
  stack,
  scene,
  pageId,
  selectedNodeId,
}: {
  stack: NodeId[];
  scene: Scene;
  pageId: PageId | null;
  selectedNodeId: NodeId | null;
}): NodeId | null {
  const hit = selectionLadderHit(stack, scene, pageId);
  return hit !== null && hit !== selectedNodeId ? hit : null;
}

export type EscapeSelectionEffect =
  | { kind: "reset-gesture" }
  | { kind: "select"; nodeId: NodeId | null }
  | { kind: "none" };

/** R3: Escape — a live gesture resets (ruling C-2, unchanged); a caret owns its own Escape; otherwise walk up, clearing at the root. */
export function escapeSelectionEffect({
  gestureLive,
  textEditing,
  selectedNodeId,
  scene,
  pageId,
}: {
  gestureLive: boolean;
  textEditing: boolean;
  selectedNodeId: NodeId | null;
  scene: Scene | null;
  pageId: PageId | null;
}): EscapeSelectionEffect {
  if (gestureLive) {
    return { kind: "reset-gesture" };
  }
  if (textEditing || !scene || selectedNodeId === null || !scene.nodes[selectedNodeId]) {
    return { kind: "none" };
  }
  return { kind: "select", nodeId: selectionWalkUp(scene, pageId, selectedNodeId) };
}

/** R5: the representable ancestry, root frame first, ending at `nodeId`. Empty for null/unknown. */
export function selectionBreadcrumb(
  scene: Scene,
  pageId: PageId | null,
  nodeId: NodeId | null,
): { nodeId: NodeId; label: string }[] {
  if (nodeId === null || !scene.nodes[nodeId]) {
    return [];
  }
  const chain: NodeId[] = [nodeId];
  let current = nodeId;
  for (;;) {
    const up = selectionWalkUp(scene, pageId, current);
    if (up === null) {
      break;
    }
    chain.unshift(up);
    current = up;
  }
  return chain.map((id) => ({ nodeId: id, label: nodeDisplayName(scene.nodes[id]) }));
}
```

- [ ] **Step 4: Run the tests**

Run: `npx tsx --test src/features/design-editor/adapter/scene-selection-ladder.test.ts src/features/design-editor/adapter/scene-selection.test.ts`
Expected: all pass (8 new + the existing selection cases untouched).

- [ ] **Step 5: Commit**

```bash
git add apps/frontend/src/features/design-editor/adapter/scene-selection-ladder.ts apps/frontend/src/features/design-editor/adapter/scene-selection-ladder.test.ts
git commit -m "feat(design-editor): selection ladder decisions — button-first hit, walk-up, hover target, Escape, breadcrumb ancestry"
```

---

### Task 2: Double-click on a button edits its label

**Files:**
- Modify: `apps/frontend/src/features/design-editor/adapter/scene-text-edit.ts` — `sceneDoubleClickEffect` (~line 148).
- Test: `apps/frontend/src/features/design-editor/adapter/scene-text-edit.test.ts` (append).

**Interfaces:**
- Consumes: `buttonLabelId(scene, nodeId)` from `./scene-selection-ladder` (Task 1).
- Produces: unchanged signature `sceneDoubleClickEffect({ gestureDisabled, nodeId, scene, selectedNodeId })`; a button-shaped `nodeId` now yields the LABEL's edit/locked/none decision.

- [ ] **Step 1: Write the failing tests** (append; reuse the file's existing imports/helpers; if the file has no scene-clone helper, add the same `clone` + `sceneWithButton` as Task 1's test, verbatim)

```ts
test("Plan 3: a double-click on a button opens the caret on its LABEL", () => {
  const scene = sceneWithButton();
  assert.deepEqual(
    sceneDoubleClickEffect({ gestureDisabled: false, nodeId: "auto_row_copy", scene, selectedNodeId: "auto_row_copy" }),
    { kind: "edit", nodeId: "text_headline" },
  );
});

test("Plan 3: a button whose label is locked decides nothing; a locked run says so", () => {
  const scene = sceneWithButton();
  scene.nodes.text_headline.locked = true;
  assert.deepEqual(
    sceneDoubleClickEffect({ gestureDisabled: false, nodeId: "auto_row_copy", scene, selectedNodeId: null }),
    { kind: "none" },
  );
  const unlocked = sceneWithButton();
  assert.deepEqual(
    sceneDoubleClickEffect({ gestureDisabled: true, nodeId: "auto_row_copy", scene: unlocked, selectedNodeId: null }),
    { kind: "locked" },
  );
});

test("Plan 3: a double-click on a non-button container still drills out as before", () => {
  // The harvest's row is not a button: the existing top-level drill-out holds.
  assert.deepEqual(
    sceneDoubleClickEffect({ gestureDisabled: false, nodeId: "group_proof", scene: HARVESTED_AD_PAGE, selectedNodeId: "group_proof" }),
    { kind: "select", nodeId: "frame_ad_root" },
  );
});
```

Check the last expectation against the file's existing "drills out to its top-level container" test and use that test's own expected id if it differs (the drill-out rule is unchanged; only its expected value is fixture-dependent).

- [ ] **Step 2: Run to verify failure**

Run: `npx tsx --test src/features/design-editor/adapter/scene-text-edit.test.ts`
Expected: the first two new tests fail (a button falls through to the drill-out rule today); the third passes.

- [ ] **Step 3: Implement** — in `sceneDoubleClickEffect`, after `const node = getNode(scene, nodeId);` and BEFORE the `if (node?.kind.kind === "text")` rule:

```ts
  // Plan 3 (item E): a button is selected as one unit, so the double-click
  // that used to land on its label now lands on the button — resolve it to the
  // label and let the text rule below decide (lock first, then the run gate).
  const labelId = node ? buttonLabelId(scene, node.id) : null;
  const target = labelId !== null ? getNode(scene, labelId) : node;
  if (target?.kind.kind === "text") {
    if (target.locked) {
      return { kind: "none" };
    }
    if (gestureDisabled) {
      return { kind: "locked" };
    }
    return { kind: "edit", nodeId: target.id };
  }
```

and DELETE the original `if (node?.kind.kind === "text") { … }` block (its three branches are now the block above, applied to `target`). Add `import { buttonLabelId } from "./scene-selection-ladder";`.

- [ ] **Step 4: Run the tests**

Run: `npx tsx --test src/features/design-editor/adapter/scene-text-edit.test.ts src/features/design-editor/adapter/scene-selection-ladder.test.ts`
Expected: all pass, including the file's existing double-click cases.

- [ ] **Step 5: Commit**

```bash
git add apps/frontend/src/features/design-editor/adapter/scene-text-edit.ts apps/frontend/src/features/design-editor/adapter/scene-text-edit.test.ts
git commit -m "feat(design-editor): double-click on a button edits its label"
```

---

### Task 3: Wire the ladder into the canvas — click, walk-up, Escape, hover outline

**Files:**
- Modify: `apps/frontend/src/features/design-editor/components/scene-artifact-canvas.tsx` — `handlePointerDown` (~1558), `handlePointerUp` (~1462), `handlePointerMove` (~1420), the Escape `useEffect` (~1491), `handleDoubleClick` (~1677), the outline memo (~983), `SelectionChrome` (~2013) and its render site (~1831).
- Modify: `apps/frontend/src/features/design-editor/adapter/scene-canvas-view.ts` — add `HOVER_OUTLINE_WIDTH = 1` and `HOVER_OUTLINE_OPACITY = 0.55` next to `SELECTION_OUTLINE_WIDTH` (line ~655).
- Test: `apps/frontend/src/features/design-editor/adapter/scene-canvas-view.test.ts` (append one constant-pinning case).

**Interfaces:**
- Consumes (Task 1): `selectionLadderHit`, `selectionWalkUp`, `sceneHoverTarget`, `escapeSelectionEffect`, `WALK_UP_CLICK_SLOP_PX`.
- Produces: `SelectionChrome` gains `variant?: "selection" | "hover"`; no other exported surface changes.

- [ ] **Step 1: Pin the hover constants** (append to `scene-canvas-view.test.ts`)

```ts
it("Plan 3 R4: the hover outline is the selection colour, thinner and translucent", () => {
  assert.equal(HOVER_OUTLINE_WIDTH, 1);
  assert.equal(HOVER_OUTLINE_OPACITY, 0.55);
  assert.ok(HOVER_OUTLINE_WIDTH < SELECTION_OUTLINE_WIDTH);
});
```

Run: `npx tsx --test src/features/design-editor/adapter/scene-canvas-view.test.ts` → fails on the missing exports. Add to `scene-canvas-view.ts` right after `SELECTION_OUTLINE_WIDTH`:

```ts
/** Plan 3 R4: the hover outline — the selection colour, 1px, translucent, no handles. */
export const HOVER_OUTLINE_WIDTH = 1;
export const HOVER_OUTLINE_OPACITY = 0.55;
```

Re-run → passes.

- [ ] **Step 2: Hover state and outline** in `scene-artifact-canvas.tsx`

Imports: add `HOVER_OUTLINE_OPACITY, HOVER_OUTLINE_WIDTH` to the `scene-canvas-view` import and
`import { WALK_UP_CLICK_SLOP_PX, escapeSelectionEffect, sceneHoverTarget, selectionLadderHit, selectionWalkUp } from "../adapter/scene-selection-ladder";`.

State, next to `ownSelectedNodeId` (~line 608): `const [hoverNodeId, setHoverNodeId] = useState<NodeId | null>(null);`

Outline memo, right after `selectionOutline` (~line 1000):

```ts
  // Plan 3 R4: the hover outline — the same derivation as the selection
  // outline over the hover target, so it sits exactly where a click's outline
  // would. Never on the selected node (the hover target is already null there).
  const hoverOutline = useMemo(
    () =>
      artboard && hoverNodeId
        ? sceneSelectionOutline({
            artboard,
            pageId,
            preview: null,
            scene,
            selectedNodeId: hoverNodeId,
            viewport,
          })
        : null,
    [artboard, hoverNodeId, pageId, scene, viewport],
  );
```

`SelectionChrome`: add `variant = "selection"` to its props (`variant?: "selection" | "hover"`); the `<svg>` gets `data-scene-hover-outline={variant === "hover" ? outline.nodeId : undefined}` and keeps `data-scene-selection-outline` only for the selection variant; the `<rect>` uses `strokeWidth={variant === "hover" ? HOVER_OUTLINE_WIDTH : SELECTION_OUTLINE_WIDTH}` and `strokeOpacity={variant === "hover" ? HOVER_OUTLINE_OPACITY : undefined}`; handles are never drawn for the hover variant (`handles && variant === "selection"`).

Render site (~line 1831): directly BEFORE the existing `<SelectionChrome … outline={textEdit ? null : selectionOutline} />`, add
`<SelectionChrome outline={textEdit || gestureRef.current.kind !== "idle" ? null : hoverOutline} variant="hover" />`.

- [ ] **Step 3: Pointer move → hover** — in `handlePointerMove`, replace the early `if (!gestureArmedRef.current || gestureRef.current.kind === "idle") { return; }` with:

```ts
    if (!gestureArmedRef.current || gestureRef.current.kind === "idle") {
      // Plan 3 R4: an idle pointer hovers. Same coordinate chain as a press
      // (`handlePointerDown`), same ladder, and only a CHANGE reaches state.
      const element = stageRef.current;
      if (textEdit || !element || !artboard || !scene || engineStatus.engineDisabled) {
        if (hoverNodeId !== null) setHoverNodeId(null);
        return;
      }
      const bounds = element.getBoundingClientRect();
      const workspacePoint = screenToWorkspace(
        { x: event.clientX - bounds.left, y: event.clientY - bounds.top },
        viewport,
      );
      const scenePoint = sceneHitPoint(workspacePoint, artboard);
      const result = scenePoint ? controls.hitTest(scenePoint.x, scenePoint.y) : null;
      const target = result
        ? sceneHoverTarget({ stack: result.stack, scene, pageId, selectedNodeId: activeSelectedNodeId })
        : null;
      if (target !== hoverNodeId) setHoverNodeId(target);
      return;
    }
```

Also add `onPointerLeave={() => setHoverNodeId(null)}` on the same stage `<div>` that carries `onPointerMove` (~line 1803), and set `setHoverNodeId(null)` as the first statement of `beginPress` (a press ends the hover; the selection outline takes over).

- [ ] **Step 4: Click ladder + walk-up** in `handlePointerDown` / `handlePointerUp`

Add a ref next to `panDragRef`: `const walkUpRef = useRef<{ pointerId: number; nodeId: NodeId; x: number; y: number } | null>(null);`

In `handlePointerDown`, replace `const hitNodeId = representableHit(result.stack, scene, pageId);` with:

```ts
    const hitNodeId = selectionLadderHit(result.stack, scene, pageId);
    // Plan 3 R3: Alt/Option-click walks up from the hit and starts no press.
    if (event.altKey && hitNodeId !== null) {
      commitSelection(selectionWalkUp(scene, pageId, hitNodeId) ?? hitNodeId);
      return;
    }
    // A click on the node that is ALREADY selected is a walk-up candidate; it
    // is decided on release, once we know the pointer did not drag.
    walkUpRef.current =
      hitNodeId !== null && hitNodeId === activeSelectedNodeId
        ? { pointerId: event.pointerId, nodeId: hitNodeId, x: event.clientX, y: event.clientY }
        : null;
```

In `handlePointerUp`, after `endPanDrag(event); if (panned) { return; }` and BEFORE the gesture `up` dispatch, add:

```ts
    // Plan 3 R3: the second click on the same node walks up — only when the
    // press travelled less than the slop and drew no drag preview.
    const candidate = walkUpRef.current;
    walkUpRef.current = null;
    if (
      candidate &&
      candidate.pointerId === event.pointerId &&
      preview === null &&
      Math.hypot(event.clientX - candidate.x, event.clientY - candidate.y) < WALK_UP_CLICK_SLOP_PX &&
      scene &&
      candidate.nodeId === activeSelectedNodeId
    ) {
      const up = selectionWalkUp(scene, pageId, candidate.nodeId);
      if (up !== null) {
        commitSelection(up);
      }
    }
```

Also clear `walkUpRef.current = null` in `resetGesture` and in the pointer-cancel handler if one exists. In `handleDoubleClick`, replace `representableHit(result.stack, scene, pageId)` with `selectionLadderHit(result.stack, scene, pageId)`. A double-click's first press may have queued a walk-up on the second press; that is fine — the walk-up runs on the second `pointerup` and the `dblclick` then resolves against the button and edits its label (Task 2). If in the live proof the walk-up visibly fires before the caret opens, guard it with `event.detail === 1` on the down (record it).

- [ ] **Step 5: Escape walks up** — replace the body of the Escape `useEffect` (~line 1491) so every fact it needs is read from refs (the listener is registered once):

Add a ref updated every render, right before the effect:
```ts
  const escapeContextRef = useRef({ scene, pageId, selectedNodeId: activeSelectedNodeId, textEditing: Boolean(textEdit) });
  escapeContextRef.current = { scene, pageId, selectedNodeId: activeSelectedNodeId, textEditing: Boolean(textEdit) };
```
(If the React Compiler lint refuses a ref write during render, move the assignment into a `useEffect` with no deps array — record which.)

Listener body:
```ts
      if (event.key !== "Escape" || typingTarget(event.target)) {
        return;
      }
      const context = escapeContextRef.current;
      const effect = escapeSelectionEffect({
        gestureLive: gestureArmedRef.current && gestureRef.current.kind !== "idle",
        textEditing: context.textEditing,
        selectedNodeId: context.selectedNodeId,
        scene: context.scene,
        pageId: context.pageId,
      });
      if (effect.kind === "reset-gesture") {
        event.preventDefault();
        resetGesture();
      } else if (effect.kind === "select") {
        event.preventDefault();
        commitSelection(effect.nodeId);
      }
```
`commitSelection` and `resetGesture` are component closures; if the effect's `[]` deps make them stale, route them through refs the same way (`commitSelectionRef`), and record it. The existing behaviour (Escape cancels a live gesture; an Escape inside an inspector field is ignored) must be preserved exactly — the `typingTarget` guard now runs first for every branch.

- [ ] **Step 6: Gate**

Run: `npx tsx --test "src/features/design-editor/**/*.test.ts"` then `npm run design-system:build && npm run lint && npm run build`.
Expected: all pass; lint 0 errors, the 2 pre-existing warnings. If the React Compiler flags a new `preserve-manual-memoization` or `set-state-in-effect` error, fix it per the repo's idiom (refs for listener context; stamped-and-derived state) and record the change.

- [ ] **Step 7: Commit**

```bash
git add apps/frontend/src/features/design-editor/components/scene-artifact-canvas.tsx apps/frontend/src/features/design-editor/adapter/scene-canvas-view.ts apps/frontend/src/features/design-editor/adapter/scene-canvas-view.test.ts
git commit -m "feat(design-editor): selection ladder on the canvas — button-first click, walk-up (click/Alt/Escape), hover outline"
```

---

### Task 4: Live proof and records (controller)

1. Open the Apollo ad (`doc_cf05190c…`, has a `cta_btn` auto-layout with a text label) in the artifact route, Edit mode.
2. Hover the CTA: `[data-scene-hover-outline]` names the CTA container before any click; screenshot.
3. Single click on the CTA label → selection is the CTA container (inspector title says the frame/auto-layout, not the text). Double-click → caret opens on the label text.
4. With the CTA selected, click it again without moving → selection walks to its parent column; Escape walks up again; Escape at the root frame clears.
5. Alt-click on the headline text → its parent is selected.
6. Records: `_memory/2026-09-04-plan3-selection-ladder.md` + README index line; roadmap status ticks Plan 3 with the breadcrumb noted as gated; ledger closed; SDD workspace removed.

### Task 5: the inspector breadcrumb — DECLINED (founder, 2026-09-04)

The founder reviewed the preview and declined it: the Layers section already shows and selects the ancestry, and the walk-up gestures need no UI. `selectionBreadcrumb` and its test were removed.
