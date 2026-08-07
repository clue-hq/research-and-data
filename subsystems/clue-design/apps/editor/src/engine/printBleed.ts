import type { PageSize, Rect } from "./contracts";

/**
 * Print guide defaults for pages created from a print preset (print
 * workstream W3). Values are in the page's canonical pt space — the space
 * `PageSize.width/height` live in after `normalizePageSize` (which converts
 * every source unit to pt). A 3mm bleed outset and a 5mm safe-area inset are
 * the industry-standard commercial-print defaults.
 */
const PT_PER_MM = 72 / 25.4;

/** 3mm bleed outset in pt (≈8.5039pt). */
export const DEFAULT_BLEED_PT = 3 * PT_PER_MM;
/** 5mm safe-area inset in pt (≈14.1732pt). */
export const DEFAULT_SAFE_AREA_PT = 5 * PT_PER_MM;

/** The bleed rect for a page: outset by `bleed` on every side, so it origins at
 * negative coordinates and grows the page box by `2 * bleed` in each axis. */
export function printBleedRect(size: PageSize, bleed: number = DEFAULT_BLEED_PT): Rect {
  return {
    x: -bleed,
    y: -bleed,
    width: size.width + bleed * 2,
    height: size.height + bleed * 2
  };
}

/** The safe-area rect for a page: inset by `inset` on every side. Clamped so a
 * tiny page never produces a zero/negative box. */
export function printSafeAreaRect(size: PageSize, inset: number = DEFAULT_SAFE_AREA_PT): Rect {
  return {
    x: inset,
    y: inset,
    width: Math.max(1, size.width - inset * 2),
    height: Math.max(1, size.height - inset * 2)
  };
}
