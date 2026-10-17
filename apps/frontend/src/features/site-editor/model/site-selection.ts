import { EDITS_PROP, editsOf, withStyleOverride, type StyleOverride } from "@clue/site-kit/edits";
import type { ElementSelection, ElementSummary, FieldDescription } from "@clue/site-kit/editor-protocol";
import { canonicalJson, componentProps, pageFor, setAtPath, withComponentProps } from "@clue/site-kit/editor-site";
import type { SiteDocument } from "@clue/site-kit/site-document";
import type { SiteLayerRow } from "./site-layers";

/** What the frame said is selected (Contract 6 `selected`), stamped with its document. The values
 * are never taken from the message: the dock reads them from the app's own copy of the site. */
export interface SiteSelection {
  componentId: string;
  componentType: string;
  documentId: string;
  fields: FieldDescription[];
  target: string;
  /** The selected text element of the section (site element inspector), or null for the section. */
  element: ElementSelection | null;
  /** The section's text elements, for Layers. */
  elements: ElementSummary[];
}

/** Everything the dock draws, as data and callbacks (presentation never reaches the session). */
export interface SiteInspectorBinding {
  disabled: boolean;
  error: string | null;
  fields: readonly FieldDescription[] | null;
  layers: readonly SiteLayerRow[];
  note: string | null;
  onCommit: (name: string, value: unknown) => void;
  onSelectLayer: (row: SiteLayerRow) => void;
  /** Remount identity: a new selection starts with fresh drafts and sections. */
  selectionKey: string;
  title: string;
  values: Record<string, unknown> | null;
  /** The selected text element, as the frame described it (its computed look), or null. */
  element: ElementSelection | null;
  /** That element's manual styling, read from the app's own copy of the site (never the message). */
  elementOverride: StyleOverride | null;
  /** One committed style change: the element's whole new override (one save, one undo step). */
  onStyleCommit: (key: string, override: StyleOverride) => void;
  /** The brand's colours for the colour picker's Theme tab: label = token, value = its CSS colour. */
  palette: readonly { label: string; value: string }[];
  /** The brand's font families with their weights. */
  fonts: readonly { family: string; weights: number[] }[];
}

/** One committed field value → the edited site and the component's whole new props. */
export function commitFieldEdit(
  site: SiteDocument,
  selection: { componentId: string; target: string },
  name: string,
  value: unknown,
): { props: Record<string, unknown>; site: SiteDocument } | null {
  const props = componentProps(site, selection.target, selection.componentId);
  if (!props) return null;
  const edited = withComponentProps(site, selection.target, selection.componentId, setAtPath(props, name, value));
  if (edited === site) return null;
  const nextProps = componentProps(edited, selection.target, selection.componentId);
  return nextProps ? { props: nextProps, site: edited } : null;
}

/** One committed style → the edited site and the component's whole new props: the element's
 * override replaces its entry in `_edits` (an empty override removes the entry, an empty `_edits`
 * removes the prop). Null when nothing changes or the component is gone. */
export function commitStyleEdit(
  site: SiteDocument,
  selection: { componentId: string; target: string },
  key: string,
  override: StyleOverride,
): { props: Record<string, unknown>; site: SiteDocument } | null {
  const props = componentProps(site, selection.target, selection.componentId);
  if (!props) return null;
  const edits = withStyleOverride(editsOf(props), key, override);
  const { [EDITS_PROP]: _previous, ...rest } = props;
  const next = Object.keys(edits).length ? { ...rest, [EDITS_PROP]: edits } : rest;
  if (canonicalJson(next) === canonicalJson(props)) return null;
  const edited = withComponentProps(site, selection.target, selection.componentId, next);
  if (edited === site) return null;
  const nextProps = componentProps(edited, selection.target, selection.componentId);
  return nextProps ? { props: nextProps, site: edited } : null;
}

/** The selected element's manual styling in the site as it is now, or null. */
export function elementOverrideOf(
  site: SiteDocument | null,
  selection: { componentId: string; target: string; element: ElementSelection | null } | null,
): StyleOverride | null {
  if (!site || !selection?.element) return null;
  const props = componentProps(site, selection.target, selection.componentId);
  return props ? (editsOf(props)[selection.element.key] ?? null) : null;
}

export function siteInspectorTitle(site: SiteDocument | null, route: string, selectedRow: SiteLayerRow | undefined): string {
  if (selectedRow) return selectedRow.label;
  const title = site ? pageFor(site, route)?.root.props.title : undefined;
  return title && title.trim() ? title : route;
}
