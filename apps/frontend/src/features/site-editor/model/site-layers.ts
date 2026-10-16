import type { BrandData } from "@clue/site-kit";
import { pageFor } from "@clue/site-kit/editor-site";
import { SHELL_TARGET, type SiteDocument } from "@clue/site-kit/site-document";

/** One Layers row: the header, a page section, or the footer. */
export interface SiteLayerRow {
  active: boolean;
  componentId: string;
  icon: "div" | "layout-template";
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
  selection: { componentId: string; target: string } | null;
  site: SiteDocument | null;
}): SiteLayerRow[] {
  const page = site ? pageFor(site, route) : null;
  if (!site || !page) return [];
  const isActive = (target: string, componentId: string) =>
    selection?.target === target && selection.componentId === componentId;
  const shellRow = (part: "header" | "footer"): SiteLayerRow => ({
    active: isActive(SHELL_TARGET, part),
    componentId: part,
    icon: "div",
    key: `shell#${part}`,
    label: part === "header" ? "Header" : "Footer",
    target: SHELL_TARGET,
  });
  return [
    ...(site.shell ? [shellRow("header")] : []),
    ...page.content.map((item) => ({
      active: isActive(route, item.props.id),
      componentId: item.props.id,
      icon: "layout-template" as const,
      key: `${route}#${item.props.id}`,
      label: componentLabel(item.type, item.props, cloneLabels),
      target: route,
    })),
    ...(site.shell ? [shellRow("footer")] : []),
  ];
}
