import type { BrandData } from "@clue/site-kit";
import { pageFor } from "@clue/site-kit/editor-site";
import type { ElementSummary } from "@clue/site-kit/editor-protocol";
import { SHELL_TARGET, type SiteDocument } from "@clue/site-kit/site-document";

/** One Layers row: the header, a page section, or the footer — or (depth 1) one text element of the
 * selected one. */
export interface SiteLayerRow {
  active: boolean;
  componentId: string;
  /** Depth-1 rows only: the text element this row selects. */
  elementKey?: string;
  depth?: 0 | 1;
  icon: "div" | "layout-template" | "type" | "rectangle";
  key: string;
  label: string;
  target: string;
}

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
  /** The selected section's text elements and buttons, right under its row. */
  const elementRows = (target: string, componentId: string): SiteLayerRow[] =>
    isSelected(target, componentId)
      ? (selection?.elements ?? []).map((element) => ({
          active: element.key === selectedElement,
          componentId,
          depth: 1 as const,
          elementKey: element.key,
          // A button (plan 3) shows as a box, as in the web inspector's layers.
          icon: element.kind === "button" ? ("rectangle" as const) : ("type" as const),
          key: `${target}#${componentId}~${element.key}`,
          label: element.label,
          target,
        }))
      : [];
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
