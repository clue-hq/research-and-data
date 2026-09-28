import type { ThemeColorOption } from "@/features/design-editor/adapter/theme-options";

/**
 * The Theme tab's option list is whatever the document's real palette source
 * supplied — the web theme's tokens, the ad lane's brand kit — and NOTHING
 * otherwise.
 *
 * Founder ruling 2026-09-04: the six-colour fixture palette that used to stand
 * in here (the dummy frontend's sample-site swatches, mint `#00F59B` among
 * them) is removed outright. It was never a brand's colours, and on a live
 * write path an invented swatch is a fabrication the user can commit. A
 * document with no theme therefore shows an empty Theme tab, which is the
 * truth: there is nothing to pick from yet. This generalises RULING A23
 * (2026-08-21), which had let the ad lane opt out of the fixture; now no lane
 * has one to opt out of.
 */
export function resolveInspectorThemeColors(
  options: readonly ThemeColorOption[] | undefined,
): readonly ThemeColorOption[] {
  return options ?? [];
}
