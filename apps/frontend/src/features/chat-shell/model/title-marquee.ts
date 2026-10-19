/** The artifact header's title marquee: a name too long for its box is cut with an ellipsis, and on
 * hover it scrolls left through one whole loop — the name, a gap, then the name again — until its
 * first letter is back where it began, and stops there. It never scrolls back. */

/** Space between the end of the name and its repeat while it scrolls. */
export const TITLE_MARQUEE_GAP_PX = 32;
/** Scrolling speed: slow enough to read. */
export const TITLE_MARQUEE_PX_PER_SECOND = 40;

export type TitleMarqueePlan = { shiftPx: number; durationMs: number };

/** How far and how long to scroll, or null when the title fits its box. ``textWidth`` is the
 * name's full width (the box's ``scrollWidth``), ``boxWidth`` the width shown (``clientWidth``). */
export function titleMarqueePlan({
  textWidth,
  boxWidth,
}: {
  textWidth: number;
  boxWidth: number;
}): TitleMarqueePlan | null {
  if (Math.round(textWidth) <= Math.round(boxWidth)) return null;
  const shiftPx = Math.round(textWidth) + TITLE_MARQUEE_GAP_PX;
  return { shiftPx, durationMs: Math.round((shiftPx / TITLE_MARQUEE_PX_PER_SECOND) * 1000) };
}
