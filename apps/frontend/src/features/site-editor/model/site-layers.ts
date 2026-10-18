import type { BrandData } from "@clue/site-kit";
import { pageFor } from "@clue/site-kit/editor-site";
import type { ElementSummary } from "@clue/site-kit/editor-protocol";
import { SHELL_TARGET, type SiteDocument } from "@clue/site-kit/site-document";

/** One Layers row: the header, a page section, or the footer — or (depth 1 and deeper, plan 4) one
 * element of the selected one, nested by the box it sits in. */
export interface SiteLayerRow {
  active: boolean;
  componentId: string;
  /** Element rows only: the element this row selects. */
  elementKey?: string;
  depth?: number;
  icon: "div" | "image" | "layout-template" | "type" | "rectangle";
  key: string;
  label: string;
  target: string;
}

/** Each element kind's Layers icon: a button (plan 3) and a box (plan 4) show as boxes, as in the web
 * inspector's layers. */
const ELEMENT_ICON: Record<ElementSummary["kind"], SiteLayerRow["icon"]> = { button: "rectangle", container: "div", image: "image", text: "type" };

// site-kit's own section labels (sections.tsx), never its Puck-panel labels "(agent)" / "Cloned section".
const BUILT_IN_LABELS: Readonly<Record<string, string>> = {
  CtaBand: "Call to action band",
  FeatureSplit: "Feature split",
  ProofCard: "Proof card",
  StatsBand: "Stats band",
};

export function cloneLabelsOf(brand: BrandData | null): Record<string, string> {
  if (!brand) return {};
  return Object.fromEntries(Object.values(brand.clones).map((clone) => [clone.id, clone.label]));
}

/** A section's name for the marketer. A cloned section is called by its own label ("Hero — …");
 * the marketer never sees "clone" or "component" (founder ruling). */
export function componentLabel(type: string, props: Record<string, unknown>, cloneLabels: Readonly<Record<string, string>>): string {
  if (type === "ClonedSection") return cloneLabels[String(props.fragmentId ?? "")] || "Section";
  const builtIn = BUILT_IN_LABELS[type];
  if (builtIn) return builtIn;
  const words = type.replace(/([a-z0-9])([A-Z])/g, "$1 $2").toLowerCase();
  return words.charAt(0).toUpperCase() + words.slice(1);
}

export function siteLayerRows({
  cloneLabels,
  route,
  selection,
  site,
}: {
  cloneLabels: Readonly<Record<string, string>>;
  route: string;
  selection: { componentId: string; target: string; elementKey?: string | null; elements?: readonly ElementSummary[] } | null;
  site: SiteDocument | null;
}): SiteLayerRow[] {
  const page = site ? pageFor(site, route) : null;
  if (!site || !page) return [];
  const selectedElement = selection?.elementKey ?? null;
  const isSelected = (target: string, componentId: string) =>
    selection?.target === target && selection.componentId === componentId;
  // The section row is active while the section itself is selected; with an element selected, the
  // element's row is.
  const isActive = (target: string, componentId: string) => isSelected(target, componentId) && selectedElement === null;
  /** The selected section's elements right under its row, each one deeper than the box it sits in. */
  const elementRows = (target: string, componentId: string): SiteLayerRow[] => {
    if (!isSelected(target, componentId)) return [];
    const elements = selection?.elements ?? [];
    const parentOf = new Map(elements.map((element) => [element.key, element.parent ?? null]));
    const depthOf = (key: string): number => {
      let depth = 1;
      // Bounded by the list's length, so a parent loop in a bad message cannot hang the dock.
      for (let up = parentOf.get(key) ?? null; up !== null && depth <= elements.length; up = parentOf.get(up) ?? null) depth += 1;
      return depth;
    };
    return elements.map((element) => ({
      active: element.key === selectedElement,
      componentId,
      depth: depthOf(element.key),
      elementKey: element.key,
      icon: ELEMENT_ICON[element.kind],
      key: `${target}#${componentId}~${element.key}`,
      // A hidden header or footer part (plan 4) stays listed, so it can be shown again.
      label: element.hidden ? `${element.label} (hidden)` : element.label,
      target,
    }));
  };
  const shellRow = (part: "header" | "footer"): SiteLayerRow => ({
    active: isActive(SHELL_TARGET, part),
    componentId: part,
    icon: "div",
    key: `shell#${part}`,
    label: part === "header" ? "Header" : "Footer",
    target: SHELL_TARGET,
  });
  return [
    ...(site.shell ? [shellRow("header"), ...elementRows(SHELL_TARGET, "header")] : []),
    ...page.content.flatMap((item) => [
      {
        active: isActive(route, item.props.id),
        componentId: item.props.id,
        icon: "layout-template" as const,
        key: `${route}#${item.props.id}`,
        label: componentLabel(item.type, item.props, cloneLabels),
        target: route,
      },
      ...elementRows(route, item.props.id),
    ]),
    ...(site.shell ? [shellRow("footer"), ...elementRows(SHELL_TARGET, "footer")] : []),
  ];
}

/** The space below the list inside its section (the section's own bottom padding). */
const LAYER_LIST_BOTTOM_GAP = 16;
/** The least height Layers keeps; with less room the whole panel scrolls instead. */
const LAYER_LIST_MIN_HEIGHT = 240;

/** Founder 2026-10-19: Layers runs to the bottom of the panel's dock (which ends at the chat box's top
 * when it is open). `listTop` is the list's top inside the dock's scrolled content. */
export function layerListHeight({
  dockHeight,
  listTop,
  bottomGap = LAYER_LIST_BOTTOM_GAP,
}: {
  dockHeight: number;
  listTop: number;
  /** What sits below the list inside its section (padding and border), measured where it can be. */
  bottomGap?: number;
}): number {
  return Math.max(LAYER_LIST_MIN_HEIGHT, Math.floor(dockHeight - listTop - Math.ceil(bottomGap)));
}
