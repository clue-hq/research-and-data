import type { WebTheme } from "../engine/webDocuments";

/**
 * W4.0: the document's real theme → the color picker's Theme-tab options,
 * replacing the dummy's fixture palette (whose Secondary/Tertiary/Subtle
 * names are not tokens any document has — the W3.2 caveat this closes).
 *
 * The LABEL is the write path, not the value: a theme pick reports the label
 * and `adapter/apply.ts` lowercases it back into the `text-<token>` facet
 * (R2, tokens only — the hex/Custom tab stays §3-inert). So token names
 * lowercase on ingest and the label is capitalize-first over that, making
 * `label.trim().toLowerCase() === token` true by construction.
 *
 * Values are CSS colors from the compiled theme and pass through VERBATIM —
 * the swatch's `background` takes any CSS color, and nothing downstream parses
 * them, so normalizing would only risk lying about the document's colors.
 */

export interface ThemeColorOption {
  /** Capitalize-first of the token name — the value the write path sees. */
  label: string;
  /** The token's CSS color, exactly as the theme serves it. */
  value: string;
}

/** The dummy labels tokens capitalized ("Dark", "Primary"); the one shared
 * rule, used both for hydrated token names and for picker option labels so
 * hydrated state and the option list agree. */
export function tokenLabel(token: string): string {
  return token.charAt(0).toUpperCase() + token.slice(1);
}

/** Theme → ordered options, in the server's token order. An entry without a
 * non-empty string color is skipped (no swatch is better than a blank one). */
export function buildThemeColorOptions(
  theme: WebTheme | null | undefined,
): ThemeColorOption[] {
  const options: ThemeColorOption[] = [];
  for (const [name, value] of Object.entries(theme?.tokens ?? {})) {
    if (typeof value !== "string" || value.length === 0) continue;
    options.push({ label: tokenLabel(name.toLowerCase()), value });
  }
  return options;
}

/** The honest closed-state swatch: a hydrated token label → its theme color,
 * or `undefined` when the token is not in this document's theme (the dummy
 * default then stands, unchanged). */
export function themeColorForToken(
  options: readonly ThemeColorOption[] | undefined,
  token: string | undefined,
): string | undefined {
  if (!options || !token) return undefined;
  const wanted = token.trim().toLowerCase();
  if (!wanted) return undefined;
  return options.find((option) => option.label.toLowerCase() === wanted)?.value;
}
