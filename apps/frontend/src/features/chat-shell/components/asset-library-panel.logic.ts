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

/** The panel's own popups are PORTALLED out of it: Base UI renders the category chip's listbox (and
 * the Replace-image menu) at the document root, so `panel.contains` reports a press on an option as
 * OUTSIDE, and the dismiss listeners would close the panel before the choice landed. A target that
 * reports one of these surfaces as an ancestor is ours, wherever the DOM put it. */
const OWNED_POPUP_SELECTOR = '[role="listbox"], [role="option"], [role="menu"], [role="menuitem"]';
/** Escape belongs to the OPEN listbox first — Base UI holds focus inside its popup while it is up,
 * and one Escape may not close both the popup and the panel behind it. */
const OPEN_LISTBOX_SELECTOR = '[role="listbox"]';

/** True when `target` can answer `closest(selector)` and reports a match. Pure and fake-friendly:
 * the tests pass a plain object with a `closest`, a real listener passes `event.target`, and
 * anything without a `closest` (a stub string, a null target) simply does not match. */
function targetClosest(target: unknown, selector: string): boolean {
  const closest = (target as { closest?: (selector: string) => unknown } | null | undefined)?.closest;
  return typeof closest === "function" && Boolean(closest.call(target, selector));
}

export function shouldCloseOnKey(key: string, target?: unknown): boolean {
  if (key !== "Escape") return false;
  return !targetClosest(target, OPEN_LISTBOX_SELECTOR);
}

/** `panel` is typed for BOTH shapes that answer "is this node inside me?": a real element, whose
 * DOM `contains(node: Node | null)` is narrower than `unknown`, and the tests' pure stub. */
export function shouldCloseOnPointer(target: unknown, panel: { contains: (node: never) => boolean } | null): boolean {
  if (targetClosest(target, OWNED_POPUP_SELECTOR)) return false;
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

/** A logo search tile's two lines: what the version is (and the background it is for, when the
 * source claimed one), then who served it. */
export function logoResultCaption(logo: { kind: string; background: "light" | "dark" | null; source: string }) {
  return {
    title: logo.background ? `${logo.kind} · ${logo.background} bg` : logo.kind,
    source: logo.source,
  };
}

/** The results heading: the company's domain and how many versions came back. */
export function logoSearchHeading(name: string | null, count: number): string {
  const versions = count === 1 ? "1 version found" : `${count} versions found`;
  return name ? `${name} · ${versions}` : versions;
}
