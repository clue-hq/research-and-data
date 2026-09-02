import type { AssetLibraryCategory, AssetLibraryItem } from "@/features/design-editor/adapter/scene-asset-library";

/** The picker's rules, kept out of the panel so every one of them is tested (the lane's
 * presentation-components-carry-no-logic convention). */

export const ASSET_LIBRARY_CATEGORIES: ReadonlyArray<{ label: string; value: AssetLibraryCategory | "all" }> = [
  { label: "All images", value: "all" },
  { label: "Logos", value: "logo" },
  { label: "Backgrounds", value: "background" },
  { label: "Mockups", value: "mockup" },
  { label: "Uploads", value: "upload" },
  { label: "AI-generated images", value: "ai-generated" },
];

export function splitLibrarySections(items: readonly AssetLibraryItem[]) {
  return {
    brand: items.filter((item) => item.pinned),
    workspace: items.filter((item) => !item.pinned),
  };
}

export function shouldCloseOnKey(key: string): boolean {
  return key === "Escape";
}

/** `panel` is typed for BOTH shapes that answer "is this node inside me?": a real element, whose
 * DOM `contains(node: Node | null)` is narrower than `unknown`, and the tests' pure stub. */
export function shouldCloseOnPointer(target: unknown, panel: { contains: (node: never) => boolean } | null): boolean {
  return !panel || !target || !panel.contains(target as never);
}

/** Arrow-key focus movement over a `columns`-wide grid of `count` cells; null for keys the grid
 * does not own (Tab keeps its native meaning). */
export function nextFocusIndex(current: number, key: string, count: number, columns: number): number | null {
  if (count === 0) return null;
  const last = count - 1;
  switch (key) {
    case "ArrowRight": return Math.min(last, current + 1);
    case "ArrowLeft": return Math.max(0, current - 1);
    case "ArrowDown": return current + columns <= last ? current + columns : current;
    case "ArrowUp": return current - columns >= 0 ? current - columns : current;
    default: return null;
  }
}
