import type { FieldDescription } from "@clue/site-kit/editor-protocol";
import { componentProps, pageFor, setAtPath, withComponentProps } from "@clue/site-kit/editor-site";
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

export function siteInspectorTitle(site: SiteDocument | null, route: string, selectedRow: SiteLayerRow | undefined): string {
  if (selectedRow) return selectedRow.label;
  const title = site ? pageFor(site, route)?.root.props.title : undefined;
  return title && title.trim() ? title : route;
}
