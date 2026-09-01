import type { NodeId, Operation, ParentRef, Scene } from "../engine/scene/contracts";
import { moveNodeToParent } from "../engine/scene/operations";
import { rootFrameId } from "./scene-hydrate";
import {
  canAlignNodes,
  canDistributeNodes,
  canGroupNodes,
  canUngroupNode,
  isNodeFreehand,
  isNodePinned,
  parentInfoForNode,
} from "../engine/scene/sceneQueries";

/**
 * AD4.B step 4 (§1.5 Arrange): the pure decisions behind the Arrange section —
 * what each of its fourteen buttons may do, and the ONE operation a z-order
 * button writes.
 *
 * WHAT IS AND IS NOT DECIDED HERE. Every eligibility RULE is the engine's
 * (`canAlignNodes` / `canDistributeNodes` / `canGroupNodes` / `canUngroupNode`
 * in `sceneQueries.ts`) and every operation is the engine's builder
 * (`moveNodeToParent`); this module owns only the composition — which gate
 * answers which button, and the index arithmetic a z-order step needs, which is
 * the one thing the engine exposes no helper for. The gates are called, never
 * re-implemented: a rule that changes upstream moves these buttons with it.
 *
 * ── THE `move_node` INDEX SEMANTICS (verified, not assumed) ───────────────
 * `Scene::move_node` (`crates/lumen-core/src/operations.rs:517-566`) is
 * REMOVE-THEN-INSERT: it validates `index` against the pre-detach child list,
 * then calls `detach_node_from_parents` and inserts at `index` into what is
 * left. So for a SAME-PARENT reorder the index counts against a list of length
 * n-1 that no longer contains the moved node:
 *
 *     siblings [a, b, c, d], moving b (i = 1, n = 4)
 *       forward  → index i+1 = 2   →  [a, c] · b · [d]  =  [a, c, b, d]
 *       front    → index n-1 = 3   →  [a, c, d] · b     =  [a, c, d, b]
 *       backward → index i-1 = 0   →  b · [a, c, d]     =  (for c: [a, c, b, d])
 *       back     → index 0
 *
 * (The engine also clamps a same-parent over-run to the post-detach length, but
 * nothing here relies on that: every index below is in range by construction.)
 *
 * WHICH END IS "FRONT". Later in `children` paints on top — the MVP editor's
 * own `ArrangeSection` (`subsystems/clue-design/apps/editor/src/components/
 * inspector/ArrangeSection.tsx:94-97`, READ-ONLY) sends
 * `moveAfterEdit(node, siblings[siblings.length - 1])` for "To front" and
 * `moveBeforeEdit(node, siblings[0])` for "To back". That editor expresses
 * z-order as `move_before`/`move_after` STRUCTURED EDITS against an anchor
 * sibling; this lane uses the plain `move_node` operation instead, because the
 * inspector's shipped write seam takes `Operation[]` and one batch is one undo
 * frame. The resulting document is the same; only the transport differs.
 *
 * THE EDGE-DISABLE AND THE MATH ARE ONE STATEMENT. `arrangeEnablement`'s
 * `zOrder` flags are literally "does `zOrderOperation` produce an operation",
 * so a button can never be offered for a step that would write nothing (or
 * hidden from one that would).
 *
 * ── RULING L19: ALIGN/DISTRIBUTE ALSO NEED COMMIT-REACHABILITY ────────────
 * The engine's `canAlignNodes`/`canDistributeNodes` and the engine's own
 * COMMIT are not the same predicate, and the gap is visible in the shipped
 * document. The gates ask `isNodeDirectGeometryEditable`, which says yes for
 * any unlocked node that is not solver-managed — including every child of a
 * PLAIN `frame`. But `alignDistributeCommitOperation`
 * (`engine/scene/alignDistribute.ts:140-157`) can only express a move two
 * ways: `position_mode === "absolute"` → an `absolute_box` update, or
 * `isNodeFreehand` → a `transform` update. A plain-frame child is NEITHER, so
 * the commit returns `null` for it and `alignNodesOperations` yields an EMPTY
 * batch. That is exactly the seeded ad: the artboard is a plain `frame` and
 * none of its four children carries a `position_mode`, so the live browser
 * proof found six Alignment buttons and two Distribution buttons ENABLED that
 * committed zero operations — no request, no version, no error. §1.5 says
 * buttons disable honestly, so that enablement was a lie.
 *
 * The fix here is ADDITIVE and stays on the enablement side: on top of the
 * engine's gates, every member must also be commit-reachable —
 * `isNodePinned(scene, id) || isNodeFreehand(scene, id)`, both IMPORTED from
 * `sceneQueries` so the "which shapes can commit" rule is still stated in one
 * place upstream and never re-derived here. The ENGINE IS READ-ONLY on this
 * lane: its gate/commit inconsistency is recorded for the founder, not fixed.
 * If the engine later teaches the commit a third shape (or tightens its own
 * gates), this composition loosens with it rather than against it.
 */

export type ZOrderAction = "front" | "forward" | "backward" | "back";

export interface ArrangeEnablement {
  /** The PRIMARY node's four z-order steps (`selectedIds[0]`). False at the
   * relevant edge of the stack, for a locked node, for the page's root frame,
   * and whenever the node or its parent cannot be resolved. */
  zOrder: Record<ZOrderAction, boolean>;
  /** `canAlignNodes` (2+ nodes, every one direct-geometry-editable) AND every
   * member commit-reachable — RULING L19. Without the second half a plain-frame
   * child enables a button that writes nothing. */
  align: boolean;
  /** `canDistributeNodes` (the same per-node rule at a floor of 3) AND the same
   * L19 commit-reachability. */
  distribute: boolean;
  /** `canGroupNodes`: 2+ unlocked, unique, same-parent, non-solver-managed. */
  group: boolean;
  /** A SINGLE selected id that `canUngroupNode` accepts (an unlocked
   * container), EXCEPT the page's own root frame. Two containers are not "a
   * single container". */
  ungroup: boolean;
}

const NOTHING: ArrangeEnablement = {
  align: false,
  distribute: false,
  group: false,
  ungroup: false,
  zOrder: { back: false, backward: false, forward: false, front: false },
};

/**
 * Is this node the page's own root frame — the artboard?
 *
 * The artboard is not a layer: §5 gives the page exactly one root frame, and
 * every structural verb the Arrange section offers is meaningless (z-order) or
 * destructive (ungroup — it would DISSOLVE the artboard into the page, leaving
 * a page of loose nodes) when aimed at it. The check is the page's OWN root
 * frame rather than "parented by a page", so a hypothetical second top-level
 * node — which this document does not have today — is still a normal layer.
 *
 * ONE predicate for both refusals deliberately: z-order and ungroup were
 * disagreeing about the artboard, and a shared statement cannot drift.
 */
function isPageRootFrame(scene: Scene, nodeId: NodeId, parent: ParentRef): boolean {
  return parent.kind === "page" && rootFrameId(scene, parent.id) === nodeId;
}

/** Where a z-order step would put the node: its own parent, and the insertion
 * index in the post-detach sibling list. `null` is the whole refusal set — an
 * unknown node, a locked one, the artboard, an unresolvable parent, or a step
 * that would run off the end of the stack. */
function zOrderTarget(
  scene: Scene,
  nodeId: NodeId,
  action: ZOrderAction,
): { index: number; parent: ParentRef } | null {
  const node = scene.nodes[nodeId];
  // §4: a locked node writes nothing, here as everywhere else on this lane.
  if (!node || node.locked) {
    return null;
  }
  const parentInfo = parentInfoForNode(scene, nodeId);
  if (!parentInfo) {
    return null;
  }
  // The artboard is not a layer in anyone's stack: reordering it against its
  // own page means nothing.
  if (isPageRootFrame(scene, nodeId, parentInfo.parent)) {
    return null;
  }
  const { index, siblings } = parentInfo;
  // The post-detach list this index counts against.
  const last = siblings.length - 1;
  const isFront = index === last;
  const isBack = index === 0;
  switch (action) {
    case "front":
      return isFront ? null : { index: last, parent: parentInfo.parent };
    case "forward":
      return isFront ? null : { index: index + 1, parent: parentInfo.parent };
    case "backward":
      return isBack ? null : { index: index - 1, parent: parentInfo.parent };
    case "back":
      return isBack ? null : { index: 0, parent: parentInfo.parent };
  }
}

/**
 * The ONE operation a z-order button writes, or `null` when the step would do
 * nothing. Built through the engine's own `moveNodeToParent`.
 */
export function zOrderOperation(
  scene: Scene | null,
  nodeId: NodeId,
  action: ZOrderAction,
): Operation | null {
  if (!scene) {
    return null;
  }
  const target = zOrderTarget(scene, nodeId, action);
  return target
    ? moveNodeToParent(nodeId, target.parent, target.index)
    : null;
}

/**
 * Ungroup: exactly one id, `canUngroupNode` accepts it, and it is NOT the
 * page's root frame.
 *
 * The engine's gate answers "is this a container?", which the artboard truly
 * is — so on its own it says yes, and ⇧⌘G on a selected artboard would dissolve
 * it, scattering its children across the page and leaving the document with no
 * frame. The panel cannot reach that state (the artboard renders the canvas
 * schema), but the keyboard can, and the refusal belongs where every consumer
 * inherits it rather than in one caller.
 *
 * An unresolvable parent refuses too: we cannot prove such a node is not the
 * artboard, and fail-closed is the posture the z-order side already takes.
 */
function ungroupEnabled(scene: Scene, ids: readonly string[]): boolean {
  if (ids.length !== 1) {
    return false;
  }
  const id = ids[0]!;
  if (!canUngroupNode(scene, id)) {
    return false;
  }
  const parentInfo = parentInfoForNode(scene, id);
  return parentInfo !== null && !isPageRootFrame(scene, id, parentInfo.parent);
}

/**
 * RULING L19: can the align/distribute COMMIT actually express a move for this
 * node? `alignDistributeCommitOperation` has exactly two branches — a pinned
 * node commits an `absolute_box`, a freehand node commits a `transform` — and
 * returns `null` for anything else, so a node outside both shapes silently
 * contributes no operation to the batch.
 *
 * Both predicates are the ENGINE's (`isNodePinned` / `isNodeFreehand`, imported
 * from `sceneQueries`), named in the same order the commit tests them, so this
 * reads as a mirror of the branch set rather than a second opinion about it.
 * (`isNodeFreehand` already subsumes `isNodePinned`; the pinned half is stated
 * anyway because the commit states it, and a future divergence upstream should
 * show up here as a change, not as silence.)
 */
function isCommitReachableForAlign(scene: Scene, nodeId: NodeId): boolean {
  return isNodePinned(scene, nodeId) || isNodeFreehand(scene, nodeId);
}

/**
 * What the Arrange section may offer for this selection.
 *
 * `scene` is nullable because the session's is: before a document loads there
 * is no document to arrange, and every button is honestly off rather than
 * live-looking and silently refused.
 */
export function arrangeEnablement(
  scene: Scene | null,
  selectedIds: readonly string[],
): ArrangeEnablement {
  if (!scene) {
    return NOTHING;
  }
  const primary = selectedIds[0] ?? null;
  const ids = [...selectedIds];
  // L19: the engine's gate is necessary but not sufficient — every member must
  // also be a shape the align/distribute commit can express.
  const commitReachable = ids.every((id) => isCommitReachableForAlign(scene, id));
  return {
    align: commitReachable && canAlignNodes(scene, ids),
    distribute: commitReachable && canDistributeNodes(scene, ids),
    group: canGroupNodes(scene, ids),
    ungroup: ungroupEnabled(scene, ids),
    zOrder: {
      back: primary !== null && zOrderTarget(scene, primary, "back") !== null,
      backward:
        primary !== null && zOrderTarget(scene, primary, "backward") !== null,
      forward:
        primary !== null && zOrderTarget(scene, primary, "forward") !== null,
      front: primary !== null && zOrderTarget(scene, primary, "front") !== null,
    },
  };
}

/**
 * ⌘G / ⇧⌘G, decided as a pure function of the event — the half of the keydown
 * handler that has rules, extracted so it can be tested without a DOM (the
 * `canvasWriteTarget` / `createSceneReplaceImageHandler` precedent; the runner
 * is `tsx --test` over `.ts` only, so a hook is never component-tested here).
 *
 * The typing-target skip is the ⌘Z handler's, verbatim in rule
 * (`use-scene-inspector-writes.ts:379-387`): a focused input, textarea or
 * contenteditable keeps its own shortcuts. `null` means "not ours", which is
 * also what tells the caller NOT to `preventDefault` — the browser's own ⌘G
 * (Find Again) must survive every event this lane does not handle.
 */
export function arrangeShortcut(
  event: {
    ctrlKey: boolean;
    key: string;
    metaKey: boolean;
    shiftKey: boolean;
  },
  target: { isContentEditable: boolean; tagName: string } | null,
): "group" | "ungroup" | null {
  if (!(event.metaKey || event.ctrlKey) || event.key.toLowerCase() !== "g") {
    return null;
  }
  if (isTypingTarget(target)) {
    return null;
  }
  return event.shiftKey ? "ungroup" : "group";
}

/**
 * The typing-target skip, stated ONCE for both keymaps below — the ⌘Z
 * handler's rule verbatim (`use-scene-inspector-writes.ts:379-387`): a focused
 * input, textarea or contenteditable keeps its own shortcuts. Shared rather
 * than repeated so the two shortcut functions cannot drift on which targets
 * are "typing".
 *
 * EXPORTED (clipboard Task 7) so the scene clipboard's copy/cut/paste/⌘D
 * handlers apply the SAME rule — the overlay textarea and every inspector
 * field must keep their native clipboard. One copy, three keymaps.
 */
export function isTypingTarget(
  target: { isContentEditable: boolean; tagName: string } | null,
): boolean {
  return (
    target !== null &&
    (target.isContentEditable ||
      target.tagName === "INPUT" ||
      target.tagName === "TEXTAREA")
  );
}

/**
 * §1.5's z-order shortcuts — ⌘] forward · ⌘[ backward · ⌥⌘] to front ·
 * ⌥⌘[ to back — decided as a pure function of the event, the `arrangeShortcut`
 * sibling above and for the same reason (the runner is `tsx --test` over `.ts`
 * only, so the hook itself is never component-tested; everything with a rule
 * lives here).
 *
 * ── WHY `code` AND NOT `key` (the whole reason this is not a one-liner) ────
 * `KeyboardEvent.key` is the CHARACTER the layout produces, and ⌥ changes it:
 * on a US layout ⌥] is "‘" (U+2018) and ⌥[ is "“" (U+201C). `KeyboardEvent.code`
 * is the PHYSICAL key and is unaffected by any modifier. So a keymap written
 * against `key` matches ⌘]/⌘[ and can never match ⌥⌘]/⌥⌘[ — which is exactly
 * what the MVP editor's `keyboardArrangeAction` does
 * (`subsystems/clue-design/apps/editor/src/engine/editorKeyboard.ts:44-60`,
 * READ-ONLY: `if (key === "]") return event.altKey ? "to_front" : "forward"`).
 * The SEMANTICS here are that precedent's, unchanged; the key IDENTITY is
 * corrected. `key` is kept only as a fallback for the unmodified pair, so a
 * layout that puts the bracket on some other physical key still gets ⌘]/⌘[
 * (the ⌥ pair cannot be rescued that way, by the same rewrite).
 *
 * ── WHY ⇧ DISQUALIFIES (a deliberate divergence from the precedent) ───────
 * The contract names four combos, all unshifted, and ⇧⌘]/⇧⌘[ are the macOS
 * browser's next/previous tab. Claiming them would `preventDefault` a browser
 * shortcut the contract never asked for, so a shifted bracket is simply not
 * ours. (The MVP editor ignores ⇧ here; it also never reaches a browser tab
 * strip.)
 *
 * `null` means "not ours", which is also what tells the caller NOT to
 * `preventDefault`: an edge-disabled step is a NON-EVENT (the caller checks
 * enablement), so at the bottom of the stack ⌘[ falls through to whatever the
 * browser does with it — the same posture a refused ⌘G takes with Find Again.
 */
export function zOrderShortcut(
  event: {
    altKey: boolean;
    code: string;
    ctrlKey: boolean;
    key: string;
    metaKey: boolean;
    shiftKey: boolean;
  },
  target: { isContentEditable: boolean; tagName: string } | null,
): ZOrderAction | null {
  if (!(event.metaKey || event.ctrlKey) || event.shiftKey) {
    return null;
  }
  if (isTypingTarget(target)) {
    return null;
  }
  if (event.code === "BracketRight" || event.key === "]") {
    return event.altKey ? "front" : "forward";
  }
  if (event.code === "BracketLeft" || event.key === "[") {
    return event.altKey ? "back" : "backward";
  }
  return null;
}
