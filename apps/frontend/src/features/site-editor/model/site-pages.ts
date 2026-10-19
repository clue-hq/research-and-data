import { pageFor } from "@clue/site-kit/editor-site";
import type { SiteDocument } from "@clue/site-kit/site-document";

/** One row of the page panel. Pages have no id or name of their own: the route is the identity
 * and the page title (`root.props.title`) is what the row says, falling back to the route. */
export interface SitePageRow {
  active: boolean;
  home: boolean;
  route: string;
  title: string;
}

export function sitePageRows(site: SiteDocument | null, activeRoute: string): SitePageRow[] {
  if (!site) return [];
  const routes = Object.keys(site.pages).sort((left, right) =>
    left === "/" ? -1 : right === "/" ? 1 : left < right ? -1 : left > right ? 1 : 0,
  );
  return routes.map((route) => {
    const title = pageFor(site, route)?.root.props.title?.trim();
    return { active: route === activeRoute, home: route === "/", route, title: title || route };
  });
}

export function filterPageRows(rows: readonly SitePageRow[], query: string): SitePageRow[] {
  const needle = query.trim().toLowerCase();
  if (!needle) return [...rows];
  return rows.filter((row) => row.title.toLowerCase().includes(needle) || row.route.includes(needle));
}

/** The URL toolbar's back/forward: the pages the frame has shown, in order. */
export interface RouteHistory {
  entries: string[];
  index: number;
}

export const EMPTY_ROUTE_HISTORY: RouteHistory = { entries: [], index: -1 };

export function visitRoute(history: RouteHistory, route: string): RouteHistory {
  if (history.entries[history.index] === route) return history;
  const entries = [...history.entries.slice(0, history.index + 1), route];
  return { entries, index: entries.length - 1 };
}

export function stepRoute(history: RouteHistory, step: -1 | 1): { history: RouteHistory; route: string | null } {
  const index = history.index + step;
  if (index < 0 || index >= history.entries.length) return { history, route: null };
  return { history: { ...history, index }, route: history.entries[index] };
}

/** An address typed in the bar → a route the site has, or null (plan Q6 (a): the bar then shows
 * the current route again, saying nothing). */
export function parseRouteInput(text: string, site: SiteDocument | null): string | null {
  if (!site) return null;
  const trimmed = text.trim().toLowerCase();
  const withSlash = trimmed.startsWith("/") ? trimmed : `/${trimmed}`;
  const route = withSlash.length > 1 ? withSlash.replace(/\/+$/, "") || "/" : "/";
  return pageFor(site, route) ? route : null;
}

/** What the URL toolbar needs. */
export interface SiteUrlBinding {
  back: () => void;
  canBack: boolean;
  canForward: boolean;
  forward: () => void;
  /** Jump to a typed address; false when the site has no such page. */
  go: (text: string) => boolean;
  reload: () => void;
  route: string;
}
