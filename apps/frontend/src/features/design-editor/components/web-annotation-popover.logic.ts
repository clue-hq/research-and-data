/**
 * Slice 3 (R-A1): where the annotation comment box sits.
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

/** Gap between the element and the card, and between the card and a viewport
 * edge it would otherwise cross. */
export const GAP = 12;

/**
 * Prefer the element's right side; flip to its left when the card would leave
 * the viewport there. The top is the element's top, clamped so a card anchored
 * to something near the bottom of a tall page still lands on screen whole.
 */
export function computePopoverPosition(
  iframe: FrameRect,
  el: ElementRect,
  box: Box,
  viewport: Box,
): { left: number; top: number } {
  const right = iframe.left + el.x + el.width + GAP;
  const left =
    right + box.width <= viewport.width
      ? right
      : iframe.left + el.x - box.width - GAP;
  const top = Math.min(
    Math.max(0, iframe.top + el.y),
    viewport.height - box.height,
  );
  return { left: Math.max(0, left), top };
}
