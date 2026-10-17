// The site element inspector's Link row (plan 2, ruling R5), as pure decisions: what the row shows for
// the selected text, and the section's whole new props after one change. A link is written where it
// already lives — our sections' and the shell's link props, a clone's href slot or link replacement —
// or, in rich text, as an <a> around the highlighted words (or the whole text). The row (site-link-row.tsx)
// only draws these; the session writes the props as one save.
import { EDITS_PROP } from "@clue/site-kit/edits";
import type { ElementSelection } from "@clue/site-kit/editor-protocol";
import { canonicalJson, componentProps, getAtPath, setAtPath, withComponentProps } from "@clue/site-kit/editor-site";
import { isRichLink, linkAt, linkWords, richText } from "@clue/site-kit/rich";
import { STALE_WORDS } from "@/features/site-editor/model/site-selection";
import type { SiteDocument } from "@clue/site-kit/site-document";

export type LinkSelection = { componentId: string; componentType: string; target: string; element: ElementSelection | null };
export type LinkRowState =
  | { kind: "link"; href: string; newTab: boolean; removable: boolean; shared: boolean }
  | { kind: "none"; reason: string };
export type LinkChange = { href: string; newTab: boolean } | null;
type Edited = { props: Record<string, unknown>; site: SiteDocument };

export const ADDRESS_RULE = "Use a page of this site (like /analysis), a web address starting with https://, a #section or a mailto: address.";

/** The site's pages, home first, each with its title (the route when it has none). */
export function sitePages(site: SiteDocument): { route: string; title: string }[] {
  const routes = Object.keys(site.pages).sort((a, b) => (a === "/" ? -1 : b === "/" ? 1 : a < b ? -1 : a > b ? 1 : 0));
  return routes.map((route) => ({ route, title: String(site.pages[route]?.root.props.title || "") || route }));
}

/** The element's stored rich text and the range a link acts on: the highlighted words, else all of it;
 * `stale` when the stored text no longer holds the highlighted words there. */
function richRange(props: Record<string, unknown>, element: ElementSelection): { html: string; start: number; end: number; stale: boolean } | null {
  if (!element.rich) return null;
  const stored = getAtPath(props, element.rich.prop);
  const html = typeof stored === "string" ? stored : (element.rich.fallback ?? "");
  const words = element.words;
  if (!words) return { end: richText(html).length, html, stale: false, start: 0 };
  return { end: words.end, html, stale: richText(html).slice(words.start, words.end) !== words.text, start: words.start };
}

const keyList = (value: unknown): string[] => (Array.isArray(value) ? value.filter((entry): entry is string => typeof entry === "string") : []);

/** What the row shows for the selected text. */
export function linkRowState(site: SiteDocument | null, selection: LinkSelection | null): LinkRowState {
  const element = selection?.element;
  const props = site && selection && element ? componentProps(site, selection.target, selection.componentId) : null;
  if (!selection || !element || !props) return { kind: "none", reason: "Select a piece of text." };
  // Text that is itself a link (or sits in one) changes that link: a link is never nested in another.
  const source = element.link?.source;
  const range = source ? null : richRange(props, element);
  if (range?.stale) return { kind: "none", reason: STALE_WORDS };
  if (range) {
    const current = linkAt(range.html, range.start, range.end);
    return current
      ? { href: current.href, kind: "link", newTab: current.newTab, removable: true, shared: false }
      : { href: "", kind: "link", newTab: false, removable: false, shared: false };
  }
  if (source?.kind === "prop") {
    return { href: String(getAtPath(props, source.href) ?? ""), kind: "link", newTab: getAtPath(props, source.newTab) === true, removable: false, shared: false };
  }
  const newTab = keyList(props.newTab).includes(element.key);
  if (source?.kind === "slot") {
    const value = (props.slots as Record<string, unknown> | undefined)?.[source.slot];
    return { href: typeof value === "string" && value ? value : (element.link?.href ?? ""), kind: "link", newTab, removable: false, shared: false };
  }
  if (source?.kind === "replacement") {
    const entry = ((props.links as { find?: string; replace?: string }[] | undefined) ?? []).find((link) => link.find === source.find);
    return { href: entry?.replace ?? element.link?.href ?? source.find, kind: "link", newTab, removable: false, shared: source.shared };
  }
  if (source?.kind === "fixed") return { kind: "none", reason: source.reason };
  if (selection.target === "shell") return { kind: "none", reason: "Text in the header and footer cannot become a link yet." };
  if (selection.componentType === "ClonedSection") {
    return { kind: "none", reason: "This text is copied from the seller's page and has no slot, so it cannot become a link." };
  }
  return { kind: "none", reason: "This text cannot become a link." };
}

/** Why an address cannot be a link here, or null when it can. */
export function addressProblem(site: SiteDocument, href: string): string | null {
  if (!isRichLink(href)) return ADDRESS_RULE;
  if (!href.startsWith("/")) return null;
  const route = href.split(/[?#]/)[0].replace(/(.)\/$/, "$1") || "/";
  const routes = sitePages(site).map((page) => page.route);
  return routes.includes(route) ? null : `This site has no page ${route}. Its pages are ${routes.join(", ")}.`;
}

function withoutAtPath(value: Record<string, unknown>, path: string): Record<string, unknown> {
  const [head, ...rest] = path.split(".");
  if (!(head in value)) return value;
  const copy: Record<string, unknown> | unknown[] = Array.isArray(value) ? [...value] : { ...value };
  if (!rest.length) {
    delete (copy as Record<string, unknown>)[head];
  } else {
    const child = (copy as Record<string, unknown>)[head];
    if (child && typeof child === "object") (copy as Record<string, unknown>)[head] = withoutAtPath(child as Record<string, unknown>, rest.join("."));
  }
  return copy as Record<string, unknown>;
}

function withNewTabKey(props: Record<string, unknown>, key: string, on: boolean): Record<string, unknown> {
  const keys = keyList(props.newTab).filter((entry) => entry !== key);
  const next = on ? [...keys, key] : keys;
  if (next.length) return { ...props, newTab: next };
  return withoutAtPath(props, "newTab");
}

/** The section's whole new props after one link change (null removes a link in rich text), or a
 * refusal with what to write instead; null when nothing changes or nothing can be changed. */
export function linkPatch(site: SiteDocument, selection: LinkSelection, change: LinkChange): Edited | { refused: string } | null {
  const element = selection.element;
  const props = element ? componentProps(site, selection.target, selection.componentId) : null;
  if (!element || !props) return null;
  const link = change ? { href: change.href.trim(), newTab: change.newTab } : null;
  if (link) {
    const problem = addressProblem(site, link.href);
    if (problem) return { refused: problem };
  }
  const source = element.link?.source;
  const range = source ? null : richRange(props, element);
  let next: Record<string, unknown> | null = null;
  if (range) {
    if (range.stale) return { refused: STALE_WORDS };
    if (range.end <= range.start) return null;
    next = setAtPath(props, element.rich!.prop, linkWords(range.html, range.start, range.end, link));
  } else if (!link) {
    return null; // a link that is part of the section stays; only rich text links are removed
  } else if (source?.kind === "prop") {
    next = setAtPath(props, source.href, link.href);
    next = link.newTab ? setAtPath(next, source.newTab, true) : withoutAtPath(next, source.newTab);
  } else if (source?.kind === "slot") {
    next = withNewTabKey({ ...props, slots: { ...((props.slots as Record<string, unknown> | undefined) ?? {}), [source.slot]: link.href } }, element.key, link.newTab);
  } else if (source?.kind === "replacement") {
    const links = ((props.links as { find: string; replace: string }[] | undefined) ?? []).filter((entry) => entry.find !== source.find);
    next = withNewTabKey({ ...props, links: [...links, { find: source.find, replace: link.href }] }, element.key, link.newTab);
  }
  if (!next || canonicalJson(next) === canonicalJson(props)) return null;
  // A link never touches the section's styling.
  if (props[EDITS_PROP] !== undefined) next[EDITS_PROP] = props[EDITS_PROP];
  const edited = withComponentProps(site, selection.target, selection.componentId, next);
  const nextProps = componentProps(edited, selection.target, selection.componentId);
  return nextProps ? { props: nextProps, site: edited } : null;
}
