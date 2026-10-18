// The site element inspector's box panel (plan 4), as pure decisions: plan 3's Fill, Stroke and Layout
// (site-button-panel.logic) for any box, plus the gap between its children and how they line up
// (ruling R3), and which keys a selection's parts write (a section's own box is two, ruling R2).
import type { StyleOverride } from "@clue/site-kit/edits";
import type { ComputedBox, ComputedContainer, ElementSelection, SectionBox } from "@clue/site-kit/editor-protocol";
import { BOX_RANGE, buttonPanelPatch, buttonPanelValues, size, type ButtonPanelChange, type ButtonPanelValues, type PaletteChoice } from "./site-button-panel.logic";

export const BOX_GAP_NOTE = "This box stacks its contents with the brand's spacing; gap applies to rows and grids.";
export const SECTION_WIDTH_NOTE = "A section always spans the page.";

type Align = ComputedContainer["contentAlign"];

export interface BoxPanelValues extends ButtonPanelValues {
  gap: string;
  /** Whether the browser uses a gap for this box (a row, a stack or a grid; ruling R4). */
  gapLive: boolean;
  layout: ComputedContainer["layout"];
  contentAlign: Align;
}

export type BoxPanelChange = ButtonPanelChange | { kind: "gap"; value: string } | { kind: "contentAlign"; to: Align };

const asContainer = (box: ComputedBox | ComputedContainer): ComputedContainer | null => ("layout" in box ? box : null);

/** What the rows show: the override where it sets something, else the box as drawn. */
export function boxPanelValues(override: StyleOverride | null, box: ComputedBox | ComputedContainer, palette: readonly PaletteChoice[]): BoxPanelValues {
  const container = asContainer(box);
  const layout = container?.layout ?? "text";
  const gap = override?.gap ?? container?.gap ?? 0;
  return {
    ...buttonPanelValues(override, box, palette),
    contentAlign: override?.contentAlign?.to ?? container?.contentAlign ?? "start",
    gap: String(Math.round(gap * 10) / 10),
    gapLive: layout !== "text",
    layout,
  };
}

/** The box's whole new override after one change, or null when the input cannot be a value (refused,
 * never clamped). Choosing what is already shown returns the override as it was. */
export function boxPanelPatch(override: StyleOverride | null, change: BoxPanelChange, box: ComputedBox | ComputedContainer): StyleOverride | null {
  const base: StyleOverride = override ?? {};
  const shown = boxPanelValues(base, box, []);
  if (change.kind === "gap") {
    const value = size(change.value, BOX_RANGE);
    if (value === null || !shown.gapLive) return null;
    return String(value) === shown.gap && base.gap !== undefined ? base : { ...base, gap: value };
  }
  if (change.kind === "contentAlign") {
    // Stored with the CSS it sets: the box's layout as drawn now (ruling R3).
    if (base.contentAlign?.along === shown.layout && base.contentAlign.to === change.to) return base;
    return { ...base, contentAlign: { along: shown.layout, to: change.to } };
  }
  return buttonPanelPatch(override, change, box);
}

/** One part of the panel: the key it writes, that key's manual styling, the box as drawn. */
export type BoxTarget = { key: string; override: StyleOverride | null; box: ComputedBox | ComputedContainer };

/** Which keys the panel writes for the selection: a box (and a button's box) writes Fill, Stroke and
 * Layout on itself; a section's own box writes Fill and Stroke on its outer box and Layout on its inner
 * box, with Width disabled (`widthNote`). Null when the selection has no box (text, an image). */
export function boxTargets(input: {
  element: Pick<ElementSelection, "key" | "kind" | "container" | "box"> | null;
  elementOverride: StyleOverride | null;
  sectionBox: SectionBox | null;
  sectionBoxOverrides: { outer: StyleOverride | null; inner: StyleOverride | null };
}): { paint: BoxTarget; layout: BoxTarget & { widthNote: string | null } } | null {
  const { element } = input;
  if (element) {
    const box = element.kind === "container" ? element.container : element.kind === "button" ? element.box : null;
    if (!box) return null;
    const target = { box, key: element.key, override: input.elementOverride };
    return { layout: { ...target, widthNote: null }, paint: target };
  }
  const section = input.sectionBox;
  if (!section) return null;
  return {
    layout: { box: section.inner.container, key: section.inner.key, override: input.sectionBoxOverrides.inner, widthNote: SECTION_WIDTH_NOTE },
    paint: { box: section.outer.box, key: section.outer.key, override: input.sectionBoxOverrides.outer },
  };
}
