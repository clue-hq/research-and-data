// The site element inspector's Header group (plan 6, rulings R10 and R12): the header stays at the
// top while the page scrolls, and/or sits over the first section. Both are facts on the header's own
// box (`_edits.root`), saved, undone and published like any other change.
import { EDITS_PROP, ROOT_KEY, editsOf, withStyleOverride } from "@clue/site-kit/edits";
import { canonicalJson, componentProps, withComponentProps } from "@clue/site-kit/editor-site";
import { SHELL_TARGET, type SiteDocument } from "@clue/site-kit/site-document";

export type HeaderPlacement = { sticky: boolean; overlay: boolean };

/** The header's placement, when the header itself is selected (not one of its elements); null otherwise. */
export function headerPlacementState(
  site: SiteDocument | null,
  selection: { target: string; componentId: string; element: unknown } | null,
): HeaderPlacement | null {
  if (!site || !selection || selection.target !== SHELL_TARGET || selection.componentId !== "header" || selection.element) return null;
  const props = componentProps(site, SHELL_TARGET, "header");
  if (!props) return null;
  const root = editsOf(props)[ROOT_KEY];
  return { sticky: root?.sticky === true, overlay: root?.overlay === true };
}

/** Sticky or overlay turned on or off: written to, or removed from, the header's `_edits.root` (an
 * entry left empty goes with it). Null when nothing changes. */
export function commitHeaderPlacement(
  site: SiteDocument,
  which: "sticky" | "overlay",
  on: boolean,
): { props: Record<string, unknown>; site: SiteDocument } | null {
  const props = componentProps(site, SHELL_TARGET, "header");
  if (!props) return null;
  const edits = editsOf(props);
  const updated = withStyleOverride(edits, ROOT_KEY, { ...edits[ROOT_KEY], [which]: on ? true : undefined });
  const next: Record<string, unknown> = { ...props };
  if (Object.keys(updated).length) next[EDITS_PROP] = updated;
  else delete next[EDITS_PROP];
  if (canonicalJson(next) === canonicalJson(props)) return null;
  const edited = withComponentProps(site, SHELL_TARGET, "header", next);
  const nextProps = componentProps(edited, SHELL_TARGET, "header");
  return nextProps ? { props: nextProps, site: edited } : null;
}
