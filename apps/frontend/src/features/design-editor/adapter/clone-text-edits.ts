import type { WebFragmentTextOverride, WebPageSummary } from "../engine/webDocuments";

/** One human text edit inside a clone, as the inspector lists it. */
export interface CloneTextEditRow {
  path: string;
  override: WebFragmentTextOverride;
}

/**
 * Which node owns the "Cloned text edits" list for the current selection, and
 * what is on it (R-A6, slice 3).
 *
 * The overrides live on the FRAGMENT node — that is where the engine stores
 * one, and where the write op must be addressed. But a pin is born wrapped in
 * its own section (`insert_cloned_section`), and clicking the band on canvas
 * usually selects that wrapper, so a wrapper whose ONLY child is a fragment
 * resolves to that fragment rather than showing nothing. A section holding
 * anything else is an ordinary section and owns no list at all.
 *
 * `null` means "this selection has no such list" — the section must not be on
 * screen. An EMPTY list is different: it is a clone nobody has edited yet, and
 * whether that renders as nothing is the section's own decision, not this one's.
 */
export function cloneTextEditsFor(
  page: WebPageSummary | undefined,
  selectedNodeId: string | null,
): { nodeId: string; overrides: CloneTextEditRow[] } | null {
  const nodes = page?.nodes;
  if (!nodes || !selectedNodeId) return null;
  const selected = nodes[selectedNodeId];
  if (!selected) return null;

  let fragment = selected.kind === "fragment" ? selected : undefined;
  if (!fragment) {
    const children = selected.children ?? [];
    if (children.length !== 1) return null;
    const only = nodes[children[0]];
    if (!only || only.kind !== "fragment") return null;
    fragment = only;
  }

  const overrides = Object.entries(fragment.text_overrides ?? {})
    .map(([path, override]) => ({ path, override }))
    // Sorted by path so the list does not reshuffle between reloads (the engine
    // serializes a BTreeMap, but the wire is JSON and key order is not a promise).
    .sort((a, b) => (a.path < b.path ? -1 : a.path > b.path ? 1 : 0));
  return { nodeId: fragment.id, overrides };
}
