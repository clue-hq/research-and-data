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
 */
export function resolveInspectorThemeColors(
  options: readonly ThemeColorOption[] | undefined,
): readonly ThemeColorOption[] {
  return options && options.length > 0 ? options : INSPECTOR_THEME_COLORS;
}
