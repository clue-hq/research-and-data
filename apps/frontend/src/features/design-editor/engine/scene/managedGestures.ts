import type { NodeId, Rect, Scene } from "./contracts";

/**
 * Phase 4c-C: pure drop-target math for drag-to-reorder inside a Stack
 * auto-layout container. Kept separate from `gestureMachine.ts` (which stays
 * geometry-agnostic) and from `canvasOperations.ts` (which builds committed
 * operations, not structured edits) — this module only reads solved
 * `computed.layout_bounds` (page space) and never mutates anything.
 */

/** How far outside the container's bounds (page-space units) the pointer may
 * stray before a reorder gesture cancels (returns `null`, no indicator). */
const OUTSIDE_CANCEL_MARGIN = 40;

export type ReorderPlacement = "before" | "after";

/** The insertion indicator line, in page space: a segment perpendicular to
 * the stack's main axis, spanning its cross-axis extent (inside padding),
 * positioned at the insertion point. */
export interface ReorderIndicator {
  /** Which coordinate `position` is (same convention as `SnapGuide.axis`):
   * "x" → a VERTICAL line at x=position spanning y=from..to (row-stack
   * insertion slots); "y" → a HORIZONTAL line at y=position spanning
   * x=from..to (column-stack insertion slots). */
  axis: "x" | "y";
  /** The main-axis coordinate the line sits at. */
  position: number;
  /** The cross-axis span the line is drawn across (padding-inset). */
  from: number;
  to: number;
}

export interface ReorderDropTarget {
  /** The index the dragged node would occupy in the container's children
   * array after the move (dragged node excluded from the count). */
  index: number;
  /** The existing sibling the move is anchored to. */
  anchorId: NodeId;
  /** Whether the dragged node lands before or after `anchorId`. */
  placement: ReorderPlacement;
  indicator: ReorderIndicator;
}

/**
 * Resolves where `draggedId` would land if dropped at `pointPageSpace` inside
 * `containerId` — a Stack auto-layout container. Returns `null` when the
 * container/dragged node can't be resolved, the container has no solved
 * geometry, or the pointer strayed more than `OUTSIDE_CANCEL_MARGIN` outside
 * the container's bounds (cancel semantics: the caller commits nothing).
 *
 * Compares the pointer's main-axis coordinate against each (non-dragged)
 * sibling's `computed.layout_bounds` midpoint, in document order, and picks
 * the first sibling the pointer is "before" (main-axis coordinate less than
 * that sibling's midpoint). Falling through every sibling means "after the
 * last one".
 */
export function reorderDropTarget(
  scene: Scene,
  containerId: NodeId,
  draggedId: NodeId,
  pointPageSpace: { x: number; y: number }
): ReorderDropTarget | null {
  const container = scene.nodes[containerId];
  if (!container || container.kind.kind !== "auto_layout" || !container.computed) {
    return null;
  }
  const bounds = container.computed.layout_bounds;
  if (
    pointPageSpace.x < bounds.x - OUTSIDE_CANCEL_MARGIN ||
    pointPageSpace.x > bounds.x + bounds.width + OUTSIDE_CANCEL_MARGIN ||
    pointPageSpace.y < bounds.y - OUTSIDE_CANCEL_MARGIN ||
    pointPageSpace.y > bounds.y + bounds.height + OUTSIDE_CANCEL_MARGIN
  ) {
    return null;
  }

  const direction = container.kind.direction;
  const isRow = direction === "row";
  const padding = container.layout?.padding ?? [0, 0, 0, 0];
  // padding tuple is [top, right, bottom, left] (matches the Rust core).
  const [padTop, padRight, padBottom, padLeft] = padding;

  const siblings = container.children.filter((id) => id !== draggedId);
  const siblingBoxes = siblings
    .map((id) => {
      const node = scene.nodes[id];
      return node?.computed ? { id, box: node.computed.layout_bounds } : null;
    })
    .filter((entry): entry is { id: NodeId; box: Rect } => entry !== null);

  const pointerMain = isRow ? pointPageSpace.x : pointPageSpace.y;

  // Cross-axis span for the indicator: the container's own bounds, inset by
  // the padding on the cross axis.
  const crossFrom = isRow ? bounds.y + padTop : bounds.x + padLeft;
  const crossTo = isRow ? bounds.y + bounds.height - padBottom : bounds.x + bounds.width - padRight;

  if (siblingBoxes.length === 0) {
    // An empty (or dragged-node-only) container: the only slot is index 0,
    // anchored... nowhere. Callers require a real anchor id, so this can
    // only be reached when the container has no other children; there is no
    // valid move target (nothing to anchor `move_before`/`move_after` to).
    return null;
  }

  let insertBeforeIndex: number | null = null;
  for (let i = 0; i < siblingBoxes.length; i++) {
    const { box } = siblingBoxes[i];
    const midpoint = isRow ? box.x + box.width / 2 : box.y + box.height / 2;
    if (pointerMain < midpoint) {
      insertBeforeIndex = i;
      break;
    }
  }

  if (insertBeforeIndex !== null) {
    const anchor = siblingBoxes[insertBeforeIndex];
    const gapPosition = mainAxisGapPosition(siblingBoxes, insertBeforeIndex, isRow, bounds, "before");
    return {
      index: insertBeforeIndex,
      anchorId: anchor.id,
      placement: "before",
      indicator: { axis: isRow ? "x" : "y", position: gapPosition, from: crossFrom, to: crossTo }
    };
  }

  // Falls through: after the last sibling.
  const lastIndex = siblingBoxes.length - 1;
  const anchor = siblingBoxes[lastIndex];
  const gapPosition = mainAxisGapPosition(siblingBoxes, lastIndex, isRow, bounds, "after");
  return {
    index: siblingBoxes.length,
    anchorId: anchor.id,
    placement: "after",
    indicator: { axis: isRow ? "x" : "y", position: gapPosition, from: crossFrom, to: crossTo }
  };
}

/** The main-axis coordinate the indicator line sits at: midway in the gap
 * between the sibling before and after the insertion point, or at the
 * container's content edge when inserting at the very first/last slot. */
function mainAxisGapPosition(
  siblingBoxes: Array<{ id: NodeId; box: Rect }>,
  index: number,
  isRow: boolean,
  containerBounds: Rect,
  placement: ReorderPlacement
): number {
  const leadingEdge = (box: Rect) => (isRow ? box.x : box.y);
  const trailingEdge = (box: Rect) => (isRow ? box.x + box.width : box.y + box.height);
  const containerLeadingEdge = isRow ? containerBounds.x : containerBounds.y;
  const containerTrailingEdge = isRow ? containerBounds.x + containerBounds.width : containerBounds.y + containerBounds.height;

  if (placement === "before") {
    const after = siblingBoxes[index].box;
    const before = index > 0 ? siblingBoxes[index - 1].box : null;
    const beforeEdge = before ? trailingEdge(before) : containerLeadingEdge;
    return (beforeEdge + leadingEdge(after)) / 2;
  }

  // "after" the sibling at `index` (the last sibling).
  const before = siblingBoxes[index].box;
  const after = index < siblingBoxes.length - 1 ? siblingBoxes[index + 1].box : null;
  const afterEdge = after ? leadingEdge(after) : containerTrailingEdge;
  return (trailingEdge(before) + afterEdge) / 2;
}
