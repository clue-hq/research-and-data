import type { ThemeColorOption } from "@/features/design-editor/adapter/theme-options";

/**
 * The dummy's fixture theme palette, lifted verbatim out of
 * `inspector-primitives.tsx` (W4.0) so the fallback contract is testable
 * under the repo's no-DOM discipline. Values unchanged.
 */
export const INSPECTOR_THEME_COLORS: readonly ThemeColorOption[] = [
  { label: "Primary", value: "#44483F" },
  { label: "Secondary", value: "#D85A00" },
  { label: "Tertiary", value: "#00F59B" },
  { label: "Dark", value: "#1C2028" },
  { label: "Light", value: "#FFFFFF" },
  { label: "Subtle", value: "#EEF1F5" },
] as const;

/**
 * W4.0: the Theme tab renders the document's real theme when a caller supplies
 * it, and the fixture palette otherwise — so every mount not wired to a theme
 * (the chats route, the other schemas' controls, a document whose theme fetch
 * returned nothing) renders exactly as it does today. An EMPTY supplied list
 * falls back too: an empty Theme tab is a worse answer than the dummy's.
 *
 * RULING A23 (2026-08-21) qualifies that last sentence for a caller that IS
 * wired to a real palette source. The fixture exists because there was no data
 * source; once there is one, its absence must read as absence — six invented
 * colours in a live picker are not a better answer, they are a fabrication,
 * and the ad lane's custom-hex path commits them for real. `fixtureFallback:
 * false` is how such a caller says "this list is the whole truth".
 *
 * It is a PARAMETER rather than a change of the rule because
 * `INSPECTOR_THEME_COLORS` also serves the WEB lane's fallback, which is
 * unchanged: `use-web-editing-session.ts` memoizes `buildThemeColorOptions`,
 * which returns `[]` for a document with no theme, so flipping the empty-list
 * rule outright would have emptied the web inspector's picker too. Every web
 * call takes the default; only the ad lane opts out.
 */
export function resolveInspectorThemeColors(
  options: readonly ThemeColorOption[] | undefined,
  fixtureFallback = true,
): readonly ThemeColorOption[] {
  if (options && options.length > 0) {
    return options;
  }
  return fixtureFallback ? INSPECTOR_THEME_COLORS : [];
}
