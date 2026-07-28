/**
 * Website-mode class facets — a partial lens over a Tailwind class string.
 *
 * Manual editing (the inspector) speaks in *facets*, not raw class strings: a
 * facet family (text color, background, display, gap, padding, …) knows how to
 * read its own value out of a class string and how to rewrite ONLY its own
 * utilities, leaving everything else — including utilities it doesn't
 * understand — verbatim. This is Mutiny's partial-lens idea: the editor never
 * needs a complete Tailwind parser, only lenses onto the handful of properties
 * it exposes. Whatever the agent authored that we don't model round-trips
 * untouched through the escape-hatch textarea and through every facet edit.
 *
 * ── Contract (v1) ────────────────────────────────────────────────────────────
 * Each family is `{ parse(classes) → value | null, set(classes, value | null)
 * → classes }`:
 *   • `parse` returns the family's current *base* value, or null when absent.
 *   • `set(classes, value)` removes ONLY this family's utilities and appends the
 *     new one; `value === null` (or "") clears the family. All other tokens —
 *     including tokens from OTHER families that happen to share a prefix
 *     (`text-lg` vs `text-primary`) — survive verbatim and in order.
 *   • Round-trip: `parse(set(c, v)) === v` for any value the family accepts.
 *
 * ── Responsive / state variants ─────────────────────────────────────────────
 * A variant-prefixed token (anything containing `:`, e.g. `md:gap-8`,
 * `hover:bg-accent`) is treated as opaque: `set()` never removes it and
 * `parse()` never reports it. Manual editing operates on the *base* utility
 * only; responsive overrides are preserved but not surfaced in v1. Editing the
 * base gap of `gap-4 md:gap-8` to `6` yields `md:gap-8 gap-6`.
 *
 * ── Axis collapse (gap v1) ──────────────────────────────────────────────────
 * The gap family owns `gap-N`, `gap-x-N`, and `gap-y-N` for removal, but
 * `parse` reports only the base `gap-N`. Setting gap therefore collapses any
 * axis-split gaps into a single `gap-N` — intended for v1 (the inspector
 * exposes one gap control).
 *
 * Pure + framework-free so it is exhaustively unit-testable.
 */

/** A single-property lens over a class string. */
export interface ClassFacet {
  /** This family's current base value, or null when it isn't set. */
  parse(classes: string): string | null;
  /** Replace this family's utilities with `value` (null/"" clears it),
   * preserving every other token verbatim and in order. */
  set(classes: string, value: string | null): string;
}

/** Split a class string into non-empty tokens, dropping surrounding
 * whitespace. Order is preserved; runs of whitespace collapse to one space on
 * re-join. */
function tokenize(classes: string): string[] {
  return classes.split(/\s+/).filter((token) => token.length > 0);
}

/** A variant-prefixed token (`md:`, `hover:`, `dark:` …) is opaque to facets. */
function hasVariant(token: string): boolean {
  return token.includes(":");
}

interface FacetSpec {
  /** Parse a bare (variant-free) token into this family's base value, or null
   * when the token doesn't belong to the family. */
  parseToken(token: string): string | null;
  /** Whether the token belongs to this family for *removal* purposes. Defaults
   * to "parses to a value"; override when a family owns more tokens than it
   * reports (e.g. gap axes). */
  ownsToken?(token: string): boolean;
  /** Build the utility token for a value. */
  formatToken(value: string): string;
}

function makeFacet(spec: FacetSpec): ClassFacet {
  const owns = spec.ownsToken ?? ((token: string) => spec.parseToken(token) !== null);
  return {
    parse(classes: string): string | null {
      for (const token of tokenize(classes)) {
        if (hasVariant(token)) {
          continue;
        }
        const value = spec.parseToken(token);
        if (value !== null) {
          return value;
        }
      }
      return null;
    },
    set(classes: string, value: string | null): string {
      const kept = tokenize(classes).filter(
        (token) => hasVariant(token) || !owns(token)
      );
      if (value !== null && value !== "") {
        kept.push(spec.formatToken(value));
      }
      return kept.join(" ");
    }
  };
}

// ── shared vocab ─────────────────────────────────────────────────────────────

/** The fixed Tailwind font-size ramp — excluded from `textColor` (they share
 * the `text-` prefix) and the value set for the `textSize` family. */
export const TEXT_SIZE_RAMP = [
  "xs",
  "sm",
  "base",
  "lg",
  "xl",
  "2xl",
  "3xl",
  "4xl",
  "5xl",
  "6xl",
  "7xl",
  "8xl",
  "9xl"
] as const;
const TEXT_SIZE_TOKENS = new Set<string>(TEXT_SIZE_RAMP);

/** `text-align` values (the `textAlign` family). */
export const TEXT_ALIGN_VALUES = ["left", "center", "right", "justify", "start", "end"] as const;
const TEXT_ALIGN_TOKENS = new Set<string>(TEXT_ALIGN_VALUES);

/** Other non-color `text-*` utilities (text-wrap / text-overflow): excluded
 * from `textColor` so they survive verbatim; not an editable family in v1. */
const TEXT_NONCOLOR_TOKENS = new Set<string>([
  "wrap",
  "nowrap",
  "balance",
  "pretty",
  "ellipsis",
  "clip"
]);

/** Non-color `bg-*` utilities (size / position / repeat / attachment / clip):
 * excluded from `bgColor`. Gradient direction utilities (`bg-gradient-to-*`,
 * `bg-linear-to-*`) are excluded by prefix, not membership. */
const BG_NONCOLOR_TOKENS = new Set<string>([
  "cover",
  "contain",
  "auto",
  "center",
  "top",
  "bottom",
  "left",
  "right",
  "fixed",
  "local",
  "scroll",
  "repeat",
  "no-repeat",
  "repeat-x",
  "repeat-y",
  "repeat-round",
  "repeat-space",
  "clip",
  "origin",
  "blend"
]);

/** `display` values this family models. */
export const DISPLAY_VALUES = ["flex", "grid", "hidden", "block", "inline-flex"] as const;
const DISPLAY_TOKENS = new Set<string>(DISPLAY_VALUES);

/** `flex-direction` values (utility is `flex-<value>`). */
export const DIRECTION_VALUES = ["row", "col"] as const;

/** The spacing step list the inspector offers for gap / padding / margin. */
export const SPACING_STEPS = [
  "0",
  "1",
  "2",
  "3",
  "4",
  "6",
  "8",
  "10",
  "12",
  "16",
  "20",
  "24"
] as const;

// ── families ─────────────────────────────────────────────────────────────────

/** `text-<token>` where the token is NOT a size or an alignment/wrap keyword —
 * i.e. a theme color name (`text-primary`, `text-ink`, `text-slate-700`). */
export const textColorFacet = makeFacet({
  parseToken(token) {
    if (!token.startsWith("text-")) {
      return null;
    }
    const suffix = token.slice("text-".length);
    if (!suffix) {
      return null;
    }
    if (
      TEXT_SIZE_TOKENS.has(suffix) ||
      TEXT_ALIGN_TOKENS.has(suffix) ||
      TEXT_NONCOLOR_TOKENS.has(suffix)
    ) {
      return null;
    }
    return suffix;
  },
  formatToken: (value) => `text-${value}`
});

/** `text-<size>` from the fixed ramp. */
export const textSizeFacet = makeFacet({
  parseToken(token) {
    if (!token.startsWith("text-")) {
      return null;
    }
    const suffix = token.slice("text-".length);
    return TEXT_SIZE_TOKENS.has(suffix) ? suffix : null;
  },
  formatToken: (value) => `text-${value}`
});

/** `text-<align>` (left/center/right/justify/start/end). */
export const textAlignFacet = makeFacet({
  parseToken(token) {
    if (!token.startsWith("text-")) {
      return null;
    }
    const suffix = token.slice("text-".length);
    return TEXT_ALIGN_TOKENS.has(suffix) ? suffix : null;
  },
  formatToken: (value) => `text-${value}`
});

/** `bg-<token>` where the token is a color name (not a gradient direction or a
 * size/position/repeat keyword). */
export const bgColorFacet = makeFacet({
  parseToken(token) {
    if (!token.startsWith("bg-")) {
      return null;
    }
    const suffix = token.slice("bg-".length);
    if (!suffix) {
      return null;
    }
    if (suffix.startsWith("gradient-to") || suffix.startsWith("linear-to")) {
      return null;
    }
    if (BG_NONCOLOR_TOKENS.has(suffix)) {
      return null;
    }
    return suffix;
  },
  formatToken: (value) => `bg-${value}`
});

/** `display` (flex/grid/hidden/block/inline-flex) — bare utilities. */
export const displayFacet = makeFacet({
  parseToken: (token) => (DISPLAY_TOKENS.has(token) ? token : null),
  formatToken: (value) => value
});

/** `flex-direction` (`flex-row` / `flex-col`). Distinct from the `flex`
 * display utility, which this family ignores. */
export const directionFacet = makeFacet({
  parseToken: (token) =>
    token === "flex-row" ? "row" : token === "flex-col" ? "col" : null,
  formatToken: (value) => `flex-${value}`
});

/** `gap-N`, modeling `gap-x-N` / `gap-y-N` as removable but reporting only the
 * base gap (axis collapse, see file header). */
export const gapFacet = makeFacet({
  parseToken(token) {
    if (!token.startsWith("gap-")) {
      return null;
    }
    const rest = token.slice("gap-".length);
    if (!rest || rest.startsWith("x-") || rest.startsWith("y-")) {
      return null;
    }
    return rest;
  },
  ownsToken: (token) => token.startsWith("gap-") && token.length > "gap-".length,
  formatToken: (value) => `gap-${value}`
});

/** A `<prefix>-N` spacing family (padding / margin axes). */
function spacingFacet(prefix: string): ClassFacet {
  const lead = `${prefix}-`;
  return makeFacet({
    parseToken(token) {
      if (!token.startsWith(lead)) {
        return null;
      }
      const rest = token.slice(lead.length);
      return rest.length > 0 ? rest : null;
    },
    formatToken: (value) => `${prefix}-${value}`
  });
}

export const paddingXFacet = spacingFacet("px");
export const paddingYFacet = spacingFacet("py");
export const marginXFacet = spacingFacet("mx");
export const marginYFacet = spacingFacet("my");

/** All families keyed by name — convenient for the inspector's generic
 * controls and for tests iterating the set. */
export const webClassFacets = {
  textColor: textColorFacet,
  bgColor: bgColorFacet,
  textSize: textSizeFacet,
  textAlign: textAlignFacet,
  display: displayFacet,
  direction: directionFacet,
  gap: gapFacet,
  paddingX: paddingXFacet,
  paddingY: paddingYFacet,
  marginX: marginXFacet,
  marginY: marginYFacet
} as const;

export type WebClassFacetName = keyof typeof webClassFacets;
