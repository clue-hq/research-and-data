// The site element inspector's Arrange and Hide (plan 4), as pure decisions over the app's own copy
// of the site: where a move is written (spec §4.8, ruling R5), the move itself, and hiding a header
// or footer part (R9). The session writes each result as one save, one undo step.
import { cloneOrderOf, type BrandData } from "@clue/site-kit";
import { EDITS_PROP, editsOf, withStyleOverride, type Edits, type StyleOverride } from "@clue/site-kit/edits";
import type { Arrange, ElementSelection } from "@clue/site-kit/editor-protocol";
import { canonicalJson, componentProps, getAtPath, setAtPath, withComponentProps } from "@clue/site-kit/editor-site";
import { SHELL_TARGET, type SiteDocument } from "@clue/site-kit/site-document";

export const FIXED_MOVE = "This part's place is set by the section's design; ask the agent to move it.";

export type MoveWrite = { kind: "array"; prop: string } | { kind: "order" } | { kind: "fixed"; reason: string };
type Place = { componentId: string; target: string };
type Section = Place & { componentType: string };

const escape = (text: string) => text.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
const ITEM = /^(.+)\.(\d+)$/;

/** Where a move of this element is written, decided from the stored site (ruling R5): its array prop
 * (`<prop>.<n>` among `<prop>.<m>` siblings, `<prop>` an array), else the parent's `order` (a copied
 * section, the header or footer), else nowhere (our fixed layouts, an agent's plain layout). */
export function moveWrite(site: SiteDocument, section: Section, arrange: Arrange): MoveWrite {
  const props = componentProps(site, section.target, section.componentId);
  const item = ITEM.exec(arrange.item);
  if (props && item) {
    const prop = item[1];
    const list = getAtPath(props, prop);
    const sibling = new RegExp(`^${escape(prop)}\\.(\\d+)$`);
    const inList = (key: string) => {
      const match = sibling.exec(key);
      return match !== null && Array.isArray(list) && Number(match[1]) < list.length;
    };
    if (Array.isArray(list) && arrange.siblings.every(inList)) return { kind: "array", prop };
  }
  if (section.target === SHELL_TARGET || section.componentType === "ClonedSection") return { kind: "order" };
  return { kind: "fixed", reason: FIXED_MOVE };
}

/** The props with the keys under `<prop>.<a>` and `<prop>.<b>` swapped: in `_edits` (the element, its
 * parts and its styled spans, and inside any `order`) and in the styled spans (`data-s`) of every text
 * in the two items. A key that merely starts the same (`stats.10` for `stats.1`) is never touched. */
export function remapItemKeys(props: Record<string, unknown>, prop: string, a: number, b: number): Record<string, unknown> {
  const rename = (key: string) => renameItemKey(key, prop, a, b);
  const next: Record<string, unknown> = { ...props };
  const edits = editsOf(props);
  if (Object.keys(edits).length) {
    next[EDITS_PROP] = Object.fromEntries(
      Object.entries(edits).map(([key, override]) => [rename(key), override.order ? { ...override, order: override.order.map(rename) } : override]),
    ) as Edits;
  }
  const spans = (value: unknown): unknown => {
    if (typeof value === "string") return value.replace(/data-s="([^"]*)"/g, (_, key: string) => `data-s="${rename(key)}"`);
    if (Array.isArray(value)) return value.map(spans);
    if (value && typeof value === "object") return Object.fromEntries(Object.entries(value).map(([k, v]) => [k, spans(v)]));
    return value;
  };
  const list = getAtPath(next, prop);
  if (Array.isArray(list)) {
    return setAtPath(next, prop, list.map((entry, index) => (index === a || index === b ? spans(entry) : entry)));
  }
  return next;
}

/** One move of the selected element up or down among its neighbours: the edited site, the
 * component's whole new props, the selected element's key where it now is (`selectedKey`, by default
 * the moving item: inside an array item its key follows the item's place; a copied or shell element,
 * and an element moved through the wrapper around it, keeps its own, review I1), and where the item
 * now sits among its neighbours (so a second press before the canvas reports back builds on this
 * one, review I6). Null at the ends, for a fixed layout, or when nothing changes. `brand`: to drop a
 * copied section's `order` that is back to the captured one. */
export function commitMove(
  site: SiteDocument,
  section: Section,
  arrange: Arrange,
  direction: "up" | "down",
  brand?: Pick<BrandData, "clones"> | null,
  selectedKey: string = arrange.item,
): { props: Record<string, unknown>; site: SiteDocument; key: string; arrange: Arrange } | null {
  const props = componentProps(site, section.target, section.componentId);
  const at = arrange.siblings.indexOf(arrange.item);
  const to = at + (direction === "up" ? -1 : 1);
  if (!props || at < 0 || to < 0 || to >= arrange.siblings.length) return null;
  const write = moveWrite(site, section, arrange);
  let next: Record<string, unknown>;
  let key = selectedKey;
  let after: Arrange;
  if (write.kind === "fixed") return null;
  if (write.kind === "array") {
    const a = Number(ITEM.exec(arrange.item)![2]);
    const b = Number(ITEM.exec(arrange.siblings[to])![2]);
    const list = [...(getAtPath(props, write.prop) as unknown[])];
    [list[a], list[b]] = [list[b], list[a]];
    next = remapItemKeys(setAtPath(props, write.prop, list), write.prop, a, b);
    key = renameItemKey(selectedKey, write.prop, a, b);
    after = { ...arrange, item: `${write.prop}.${b}` };
  } else {
    const order = [...arrange.siblings];
    [order[at], order[to]] = [order[to], order[at]];
    after = { ...arrange, siblings: order };
    const edits = editsOf(props);
    const clone = section.componentType === "ClonedSection" ? brand?.clones[String(props.fragmentId ?? "")] : undefined;
    const captured = clone ? cloneOrderOf(clone, arrange.parent) : null;
    const back = captured !== null && canonicalJson(captured) === canonicalJson(order);
    const override: StyleOverride = { ...edits[arrange.parent], order: back ? undefined : order };
    const updated = withStyleOverride(edits, arrange.parent, override);
    next = { ...props };
    if (Object.keys(updated).length) next[EDITS_PROP] = updated;
    else delete next[EDITS_PROP];
  }
  if (canonicalJson(next) === canonicalJson(props)) return null;
  const edited = withComponentProps(site, section.target, section.componentId, next);
  const nextProps = componentProps(edited, section.target, section.componentId);
  return nextProps ? { arrange: after, key, props: nextProps, site: edited } : null;
}

/** A key under `<prop>.<a>` renamed to `<prop>.<b>` and back (remapItemKeys' rule for one key). */
function renameItemKey(key: string, prop: string, a: number, b: number): string {
  return key.replace(new RegExp(`^${escape(prop)}\\.(${a}|${b})(?=$|[.~])`), (_, index: string) => `${prop}.${Number(index) === a ? b : a}`);
}

/** What the Arrange section shows for the selection: whether each move can be made, and why not when
 * the part's place is fixed. Null when the element has no neighbours. */
export function arrangeState(
  site: SiteDocument | null,
  selection: (Section & { element: Pick<ElementSelection, "arrange"> | null }) | null,
): { canUp: boolean; canDown: boolean; note: string | null } | null {
  const arrange = selection?.element?.arrange;
  if (!site || !selection || !arrange) return null;
  const write = moveWrite(site, selection, arrange);
  if (write.kind === "fixed") return { canDown: false, canUp: false, note: write.reason };
  const at = arrange.siblings.indexOf(arrange.item);
  return { canDown: at >= 0 && at < arrange.siblings.length - 1, canUp: at > 0, note: null };
}

/** Hiding or showing a header or footer part (ruling R9): `hidden: true` in its `_edits` entry, or the
 * property removed (an entry left empty goes with it). Null when nothing changes. */
export function commitHidden(site: SiteDocument, place: Place, key: string, hidden: boolean): { props: Record<string, unknown>; site: SiteDocument } | null {
  if (place.target !== SHELL_TARGET) return null;
  const props = componentProps(site, place.target, place.componentId);
  if (!props) return null;
  const edits = editsOf(props);
  const updated = withStyleOverride(edits, key, { ...edits[key], hidden: hidden ? true : undefined });
  const next: Record<string, unknown> = { ...props };
  if (Object.keys(updated).length) next[EDITS_PROP] = updated;
  else delete next[EDITS_PROP];
  if (canonicalJson(next) === canonicalJson(props)) return null;
  const edited = withComponentProps(site, place.target, place.componentId, next);
  const nextProps = componentProps(edited, place.target, place.componentId);
  return nextProps ? { props: nextProps, site: edited } : null;
}

/** Whether the selected header or footer part is hidden; null for anything that cannot be hidden. */
export function hideState(
  site: SiteDocument | null,
  selection: (Place & { element: Pick<ElementSelection, "key"> | null }) | null,
): { hidden: boolean; part: "header" | "footer" } | null {
  if (!site || !selection?.element || selection.target !== SHELL_TARGET) return null;
  if (selection.componentId !== "header" && selection.componentId !== "footer") return null;
  const props = componentProps(site, selection.target, selection.componentId);
  return props ? { hidden: editsOf(props)[selection.element.key]?.hidden === true, part: selection.componentId } : null;
}
