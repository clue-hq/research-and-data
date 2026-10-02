/**
 * Slice 2 (R-A1): where the annotation comment box sits.
 *
 * Same shape of decision as `web-rich-text-toolbar.logic.ts::computeToolbarPosition`
 * — DOM reads (the iframe's bounding rect, the card's measured size, the window
 * size) are parameters so the math is testable under `tsx --test`, which has no
 * DOM — but a different rule, because the two point at different things: the
 * toolbar floats ABOVE a text range it must not cover, while the comment box
 * sits BESIDE the element it is about, top-aligned with it, so the element stays
 * fully visible while you type about it.
 */

export interface Box {
  width: number;
  height: number;
}

export interface FrameRect {
  left: number;
  top: number;
  width: number;
  height: number;
}

/** The annotated element's rect, in the iframe's own viewport coordinates —
 * exactly the `geometry.viewport` the bridge reports. */
export interface ElementRect {
  x: number;
  y: number;
  width: number;
  height: number;
}

/** Gap between the element and the card, and between the card and an edge it
 * would otherwise cross. */
export const GAP = 12;

function clamp(value: number, low: number, high: number): number {
  return Math.max(low, Math.min(high, value));
}

/**
 * Place the card beside the element it is about — and, crucially, NEVER outside
 * the iframe's own horizontal band.
 *
 * Fix round 1: the first version only asked whether the card fit in the
 * VIEWPORT, so any element reaching the canvas's right edge flipped the card
 * left across the canvas boundary and onto the inspector pane. The band is the
 * iframe, not the window: prefer the element's right side, else its left side,
 * else drop BELOW the element and clamp horizontally inside the frame. The
 * viewport clamp still runs last, so a card can never be pushed off screen
 * either.
 */
export function computePopoverPosition(
  iframe: FrameRect,
  el: ElementRect,
  box: Box,
  viewport: Box,
): { left: number; top: number } {
  const frameLeft = iframe.left;
  const frameRight = iframe.left + iframe.width;
  const elementLeft = frameLeft + el.x;
  const rightSide = elementLeft + el.width + GAP;
  const leftSide = elementLeft - box.width - GAP;

  let left: number;
  let top: number;
  if (rightSide + box.width <= frameRight) {
    left = rightSide;
    top = iframe.top + el.y;
  } else if (leftSide >= frameLeft) {
    left = leftSide;
    top = iframe.top + el.y;
  } else {
    // Nothing fits beside a full-bleed element, so sit under it, aligned to its
    // left edge and held inside the frame.
    left = clamp(elementLeft, frameLeft, frameRight - box.width);
    top = iframe.top + el.y + el.height + GAP;
  }

  return {
    left: clamp(left, 0, viewport.width - box.width),
    top: clamp(top, 0, viewport.height - box.height),
  };
}
