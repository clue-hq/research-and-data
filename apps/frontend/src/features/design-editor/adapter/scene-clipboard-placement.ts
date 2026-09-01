import type { NodeId, PageId, ParentRef, Scene, Transform } from "../engine/scene/contracts";
import { getNode, isNodeLayoutManaged, parentInfoForNode } from "../engine/scene/sceneQueries";
import type { SceneClipboardPayloadV1 } from "./scene-clipboard";

/**
 * Scene clipboard Task 4 — where a paste lands.
 *
 * A pure decision: scene structure in, one `PastePlacement` out. No DOM, no
 * clipboard API, no React, and — the point of the injected accessor below — no
 * layout solve. Task 7 composes this with the Task 1–3 serializer/codec/re-mint;
 * nothing here composes anything the other way around.
 *
 * TWO SHAPES, and the difference is not cosmetic:
 *   `into-layout` — an INDEX insert into an auto-layout container. The solver
 *   owns the child's position, so the placement authors NO transform. The
 *   variant has no transform field, deliberately; giving it one would invite a
 *   caller to write geometry the next solve immediately overwrites.
 *   `freehand`   — a parent plus a PARENT-RELATIVE transform.
 *
 * THE F9 LESSON (AD4.C ruling C-11), which this file exists to not repeat: a
 * node's `transform` is relative to its parent's computed origin, NOT page
 * space. The v1 canvas drag/resize builders wrote page-absolute coordinates
 * straight into that transform, and every node under a non-zero-origin parent
 * (`group_proof`'s children in the seeded ad — the founder's "the dot refuses
 * to move" repro) jumped by the parent's origin. So here: compute the
 * page-space target FIRST, then rebase it into the parent's frame before it
 * ever becomes a transform.
 *
 * ORIGINS ARE INJECTED, NEVER READ. `parentComputedOrigin` is an argument, and
 * this module reads no `computed` block of its own — which is what keeps the
 * planner pure and testable AD4.C-3a style (the harvested fixtures carry
 * `computed: null` on every node, so there is nothing to read anyway). Note it
 * is keyed by the PARENT container's id, unlike the child-keyed
 * `sceneQueries.parentComputedOrigin(scene, childId)`: a pasted node does not
 * exist in the scene yet, so the parent is the only thing that can be named.
 */

export type PastePlacement =
  | { kind: "into-layout"; parent: ParentRef & { kind: "node" }; index: number }
  | { kind: "freehand"; parent: ParentRef; transform: Transform };

export type PastePlacementMode =
  /** ⌘V / ⌘D: step +10 x/y off the copied box, once per generation. */
  | { kind: "paste-cascade"; generation: number }
  /** A pointer drop: the payload is CENTERED on the dropped page point. */
  | { kind: "drop-point"; pagePoint: { x: number; y: number } }
  /** Paste with nothing to cascade from: centered in the visible viewport. */
  | { kind: "viewport-center"; center: { x: number; y: number } };

/** The cascade step, in page points, applied once per generation. */
export const PASTE_CASCADE_STEP = 10;

export function planPastePlacement(args: {
  scene: Scene;
  pageId: PageId;
  selectedNodeId: NodeId | null;
  payloadBounds: SceneClipboardPayloadV1["bounds"];
  mode: PastePlacementMode;
  parentComputedOrigin: (nodeId: NodeId) => { x: number; y: number };
}): PastePlacement {
  const { scene, pageId, selectedNodeId, payloadBounds, mode } = args;

  const selected = getNode(scene, selectedNodeId);
  // A locked node is not a paste target and not a parent donor either: the
  // human has said "don't reason about this one", so the paste goes to the
  // page rather than silently reaching inside it.
  const usableSelection = selected && !selected.locked ? selected : null;

  // Ruling 2: pasting with an auto-layout container selected means "put it in
  // the row", an index insert at the end. A pointer drop is exempt (R4) — the
  // human named a point, and honouring it beats honouring the selection.
  if (
    usableSelection &&
    usableSelection.kind.kind === "auto_layout" &&
    mode.kind !== "drop-point"
  ) {
    return {
      kind: "into-layout",
      parent: { kind: "node", id: usableSelection.id },
      index: usableSelection.children.length,
    };
  }

  const parent = freehandParent(scene, pageId, usableSelection?.id ?? null);
  const target = pageSpaceTarget(payloadBounds, mode);
  // The rebase. A page parent's origin is (0,0) by definition, so page-parented
  // pastes never consult the accessor at all.
  const origin =
    parent.kind === "node" ? args.parentComputedOrigin(parent.id) : { x: 0, y: 0 };

  return {
    kind: "freehand",
    parent,
    transform: {
      x: target.x - origin.x,
      y: target.y - origin.y,
      // Position-only: a paste never invents rotation, skew, or a flip. The
      // re-minted subtree keeps whatever its own nodes carried.
      rotation: 0,
      skew_x: 0,
      skew_y: 0,
      flip_x: false,
      flip_y: false,
    },
  };
}

/**
 * The container a freehand paste lands in: the selected node's own parent when
 * that selection is something the human can actually place things beside, and
 * the page otherwise.
 *
 * A solver-MANAGED selection falls through to the page on purpose: its parent
 * is an auto-layout row, so a freehand sibling dropped in there would be
 * re-flowed on the next solve and the authored transform thrown away.
 */
function freehandParent(scene: Scene, pageId: PageId, selectedId: NodeId | null): ParentRef {
  const pageParent: ParentRef = { kind: "page", id: pageId };
  if (!selectedId || isNodeLayoutManaged(scene, selectedId)) {
    return pageParent;
  }
  // A node with no parent at all is a scene-invariant violation, not the
  // planner's to repair — the paste still has to land somewhere, so: the page.
  return parentInfoForNode(scene, selectedId)?.parent ?? pageParent;
}

/** The paste's top-left in PAGE space, before any parent rebase. */
function pageSpaceTarget(
  bounds: SceneClipboardPayloadV1["bounds"],
  mode: PastePlacementMode,
): { x: number; y: number } {
  switch (mode.kind) {
    case "paste-cascade": {
      const step = PASTE_CASCADE_STEP * mode.generation;
      return { x: bounds.x + step, y: bounds.y + step };
    }
    case "drop-point":
      // R3: the pointer names the CENTRE of the pasted box, not its corner.
      return {
        x: mode.pagePoint.x - bounds.width / 2,
        y: mode.pagePoint.y - bounds.height / 2,
      };
    case "viewport-center":
      // The copied box's own x/y are irrelevant here — only its size is.
      return {
        x: mode.center.x - bounds.width / 2,
        y: mode.center.y - bounds.height / 2,
      };
    default: {
      // Exhaustiveness: a new mode must decide its own anchor, loudly.
      const unreachable: never = mode;
      throw new Error(`unhandled paste placement mode: ${JSON.stringify(unreachable)}`);
    }
  }
}
