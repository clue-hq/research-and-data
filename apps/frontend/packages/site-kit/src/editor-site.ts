// The edits both sides of the editor protocol make, as pure functions over Contract 1's site
// document. The app (which saves) and the editor frame (which renders) call the SAME functions,
// so an edit can never mean two different things on the two sides of the boundary.
import { SHELL_TARGET, isShellId, type SiteDocument, type SitePage, type SiteTarget } from "./site-document";

/** JSON with object keys sorted, so two equal sites compare equal whatever their key order. */
export function canonicalJson(value: unknown): string {
  return JSON.stringify(value, (_key, raw: unknown) => {
    if (raw && typeof raw === "object" && !Array.isArray(raw)) {
      return Object.fromEntries(
        Object.entries(raw as Record<string, unknown>).sort(([left], [right]) => (left < right ? -1 : left > right ? 1 : 0)),
      );
    }
    return raw;
  });
}

const segmentsOf = (path: string) => path.split(".");

/** Read a dotted path ("stats.0.value", "slots.headline"). */
export function getAtPath(value: unknown, path: string): unknown {
  let cursor: unknown = value;
  for (const segment of segmentsOf(path)) {
    if (cursor === null || typeof cursor !== "object") return undefined;
    cursor = (cursor as Record<string, unknown>)[segment];
  }
  return cursor;
}

/** Write a dotted path, copying every level along it; numeric segments index arrays. */
export function setAtPath<T>(value: T, path: string, next: unknown): T {
  const [head, ...rest] = segmentsOf(path);
  const container = value as unknown;
  const current =
    container !== null && typeof container === "object" ? (container as Record<string, unknown>)[head] : undefined;
  const child = rest.length
    ? setAtPath(current ?? (/^\d+$/.test(rest[0]) ? [] : {}), rest.join("."), next)
    : next;
  if (Array.isArray(container) && /^\d+$/.test(head)) {
    const copy = [...container];
    copy[Number(head)] = child;
    return copy as T;
  }
  const base = container !== null && typeof container === "object" ? (container as Record<string, unknown>) : {};
  return { ...base, [head]: child } as T;
}

export function pageFor(site: SiteDocument, route: string): SitePage | null {
  return Object.hasOwn(site.pages, route) ? site.pages[route] : null;
}

export function withPage(site: SiteDocument, route: string, page: SitePage): SiteDocument {
  return { ...site, pages: { ...site.pages, [route]: page } };
}

/** A component as stored: a page section by its `props.id`, or the shell's header or footer entry
 * (plan 6: both are sections, `{type, props}`). */
export function componentEntry(
  site: SiteDocument,
  target: SiteTarget,
  componentId: string,
): { type: string; props: Record<string, unknown> } | null {
  if (target === SHELL_TARGET) {
    return site.shell && isShellId(componentId) ? site.shell[componentId] : null;
  }
  return pageFor(site, target)?.content.find((entry) => entry.props.id === componentId) ?? null;
}

/** A component's props: a page section by its `props.id`, or the shell's header/footer. */
export function componentProps(
  site: SiteDocument,
  target: SiteTarget,
  componentId: string,
): Record<string, unknown> | null {
  return componentEntry(site, target, componentId)?.props ?? null;
}

/** Replace a component's props. The id is always kept (and a shell entry's type); an unknown
 * component changes nothing (the same object comes back, so callers can tell). */
export function withComponentProps(
  site: SiteDocument,
  target: SiteTarget,
  componentId: string,
  props: Record<string, unknown>,
): SiteDocument {
  if (target === SHELL_TARGET) {
    if (!site.shell || !isShellId(componentId)) return site;
    const entry = site.shell[componentId];
    return { ...site, shell: { ...site.shell, [componentId]: { ...entry, props: { ...props, id: componentId } } } };
  }
  const page = pageFor(site, target);
  if (!page) return site;
  const index = page.content.findIndex((entry) => entry.props.id === componentId);
  if (index < 0) return site;
  const content = page.content.map((entry, position) =>
    position === index ? { ...entry, props: { ...props, id: componentId } } : entry,
  );
  return withPage(site, target, { ...page, content });
}

/** Put an `/asset-store/<sha256>` url at a component's prop path. */
export function withAssetAt(
  site: SiteDocument,
  target: SiteTarget,
  componentId: string,
  prop: string,
  url: string,
): SiteDocument {
  const props = componentProps(site, target, componentId);
  if (!props) return site;
  return withComponentProps(site, target, componentId, setAtPath(props, prop, url));
}

/** The page a site-internal link points at, or null for anything else (another site, a path
 * the site has no page for, a protocol-relative url). */
export function internalRoute(href: string, site: SiteDocument): string | null {
  if (!href.startsWith("/") || href.startsWith("//")) return null;
  const path = href.split(/[?#]/, 1)[0] || "/";
  const route = path.length > 1 ? path.replace(/\/+$/, "") : path;
  return pageFor(site, route) ? route : null;
}

/** The agent-section digests a site needs, sorted (an init must re-run when this changes). */
export function sectionDigests(site: SiteDocument): string[] {
  return Object.values(site.agent_sections).sort();
}

export type ShortcutDecision = "undo" | "redo" | "swallow" | null;

/** ⌘Z / Ctrl+Z → undo, ⇧⌘Z / Ctrl+Y → redo, ⌘I → swallow (Puck's own preview toggle belongs to
 * the app's Edit button). Native text undo owns a focused input or editable text — the web
 * lane's rule (`use-inspector-writes.ts`). */
export function shortcutFor(event: {
  ctrlKey: boolean;
  key: string;
  metaKey: boolean;
  shiftKey: boolean;
  target: unknown;
}): ShortcutDecision {
  if (!event.metaKey && !event.ctrlKey) return null;
  const key = event.key.toLowerCase();
  if (key === "i") return "swallow";
  if (key !== "z" && key !== "y") return null;
  const target = event.target as { isContentEditable?: boolean; tagName?: string } | null;
  if (
    target &&
    (target.isContentEditable === true ||
      target.tagName === "INPUT" ||
      target.tagName === "TEXTAREA" ||
      target.tagName === "SELECT")
  ) {
    return null;
  }
  if (key === "y") return "redo";
  return event.shiftKey ? "redo" : "undo";
}
