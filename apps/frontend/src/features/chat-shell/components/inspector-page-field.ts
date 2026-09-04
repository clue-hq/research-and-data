/**
 * F5 task 19: the pure decisions the web inspector's Page section makes — the
 * route field's draft/commit rules, the page id a new page's name slugs to,
 * and the two structural refusals on Remove.
 *
 * They live in this sibling module — not inside the component — so they are
 * testable under `tsx --test` with no DOM, exactly as `inspector-field-draft.ts`
 * is. Nothing here knows about React, the session, or the write adapters: a
 * decision is data, and the component is the only thing that fires a write.
 *
 * Founder correction 2026-09-04: the section now has TWO groups — "This page"
 * (the page on screen; its Name and Route fields WRITE to it) and "New page"
 * (a name and a route for the page Add creates). The first shipping shape had
 * one Name/Route pair over the live page and a bare "Add a page" box that
 * derived its route silently; a marketer typed the NEW page's name into the
 * live page's Name box, re-routed the home page by accident, and then hit
 * "route already used" against the page they had just renamed. So: the new
 * page's route is visible and editable before Add, and a collision names the
 * page that holds the route.
 */

import { routeIsValid } from "@/features/design-editor/engine/webDocuments";

/**
 * The route grammar, in the words the AGENT already uses (`web_substrate.py`'s
 * `add_page` docstring). One product, one sentence: a marketer who was refused
 * by the agent and a marketer who was refused by this field read the same rule.
 */
export const INVALID_ROUTE_MESSAGE =
  'Routes are "/" or lowercase segments like "/pricing" — no capitals, no spaces, no trailing slash.';

/**
 * The engine's `op.route_exists` refusal, said plainly. This is the SERVER's
 * wording (a page added by an agent turn between this document load and this
 * commit); a collision the field can see locally names the page instead
 * (`routeTakenMessage`), because the field knows which page it is.
 */
export const ROUTE_TAKEN_MESSAGE = "That route is already used by another page.";

/** A page has to be named before it can be added — an empty box has nothing to
 * slug, and minting "/page" for it would be inventing the user's intent. */
export const NAME_THE_PAGE_MESSAGE = "Name the page first.";

/** Two pages cannot share an id, and the id IS the name's slug — so a second
 * "Home" (or "home", or "HOME") is refused by name, not by the engine. */
export const PAGE_NAME_TAKEN_MESSAGE = "A page with that name already exists.";

/** A page as the Page section sees it — enough to name a collision. */
export interface PageRef {
  id: string;
  name: string;
  route: string;
}

/** The local collision refusal: it names the page that holds the route, so a
 * marketer who just renamed the home page to the route they wanted can see
 * exactly what happened. */
export function routeTakenMessage(pageName: string): string {
  return `That route is already used by the page "${pageName}".`;
}

export type RouteFieldDecision =
  | { kind: "commit"; route: string }
  | { kind: "refuse"; message: string }
  | { kind: "noop" };

/**
 * What a blur/Enter on the live page's route field does.
 *
 * `current` is the LIVE document route for this page and `siblings` the OTHER
 * pages (the caller excludes this page). Order is load-bearing:
 *   1. unchanged → `noop` (never a write, and it can never self-refuse on a
 *      sibling list that mistakenly includes this page's own route);
 *   2. ungrammatical → `refuse` (the engine would reject it as
 *      `op.route_invalid`, so the field says so without spending a round trip);
 *   3. already taken → `refuse`, naming the holder (the engine's
 *      `op.route_exists`, same reason);
 *   4. otherwise → `commit` the trimmed route.
 *
 * A refusal returns no route at all, which is what makes "no write fires on an
 * invalid draft" structural rather than a habit of the component.
 */
export function routeFieldDecision(
  draft: string,
  current: string,
  siblings: readonly PageRef[],
): RouteFieldDecision {
  const route = draft.trim();
  if (route === current) return { kind: "noop" };
  if (!routeIsValid(route)) return { kind: "refuse", message: INVALID_ROUTE_MESSAGE };
  const holder = siblings.find((candidate) => candidate.route === route);
  if (holder) return { kind: "refuse", message: routeTakenMessage(holder.name) };
  return { kind: "commit", route };
}

/**
 * The page id a new page's NAME slugs to: lowercase, every run of anything else
 * folded to one dash, no leading/trailing dash. A slug that would start with a
 * digit is prefixed `p-`, because both the engine's page-id grammar and the
 * agent tool's (`[a-z][a-z0-9_-]*`) want a leading letter. An empty slug falls
 * back to `page` — the caller refuses an unnamed page before it gets here, so
 * this fallback exists only so the function is total.
 */
export function pageIdFromName(name: string): string {
  const slug = name
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, "-")
    .replace(/^-+|-+$/g, "");
  if (slug === "") return "page";
  return /^[0-9]/.test(slug) ? `p-${slug}` : slug;
}

/** The route a new page's name SUGGESTS — `/` + the name's slug — shown in the
 * New page route box as the marketer types, until they edit the route
 * themselves. Empty for an empty name, so the box does not say "/page". */
export function suggestedRouteForName(name: string): string {
  const trimmed = name.trim();
  return trimmed === "" ? "" : `/${pageIdFromName(trimmed)}`;
}

export type AddPageDecision =
  | { kind: "commit"; page: { id: string; name: string; route: string } }
  | { kind: "refuse"; message: string };

/**
 * What "Add page" does with the typed name and route: the id is the name's
 * slug; the route is the typed one, or the name's suggested route when the
 * box was left empty. Refusals, in order, all checked locally before any round
 * trip: unnamed; a name whose slug is already a page id; an ungrammatical
 * route (`Asset Store` → `/asset-store`, which is never a first segment: it is
 * served beside a published site); a route another page holds — named.
 */
export function addPageDecision(
  name: string,
  routeDraft: string,
  pages: readonly PageRef[],
): AddPageDecision {
  const trimmed = name.trim();
  if (trimmed === "") return { kind: "refuse", message: NAME_THE_PAGE_MESSAGE };
  const id = pageIdFromName(trimmed);
  if (pages.some((candidate) => candidate.id === id)) {
    return { kind: "refuse", message: PAGE_NAME_TAKEN_MESSAGE };
  }
  const route = routeDraft.trim() || suggestedRouteForName(trimmed);
  if (!routeIsValid(route)) return { kind: "refuse", message: INVALID_ROUTE_MESSAGE };
  const holder = pages.find((candidate) => candidate.route === route);
  if (holder) return { kind: "refuse", message: routeTakenMessage(holder.name) };
  return { kind: "commit", page: { id, name: trimmed, route } };
}

/**
 * Whether Remove may act at all. Two structural refusals, both of which the
 * engine or the published site would enforce anyway — the button is simply
 * disabled rather than offering an action that cannot succeed:
 *   • the document's LAST page (the engine refuses `remove_page` for it), and
 *   • the home page `/` (a site with no `/` serves nothing at its own root).
 */
export function pageIsRemovable(
  page: { route: string } | null | undefined,
  pageCount: number,
): boolean {
  if (!page) return false;
  if (pageCount <= 1) return false;
  return page.route !== "/";
}

/**
 * The sentence the Page section shows for a refusal that came back from the
 * SERVER. The design API flattens every checked-apply rejection to one envelope
 * code and keeps the engine's own code beside it
 * (`WebOperationsError.engineCode`), so the two refusals this section can
 * provoke are said in the same words the field uses when it catches them
 * locally — a marketer never sees two wordings for one rule, and never sees
 * engine prose (`route `/x` is already taken`).
 *
 * Any other code keeps the server's own message: guessing at a refusal we do
 * not model would be worse than repeating what the server actually said.
 */
export function pageWriteMessage(
  engineCode: string | null,
  serverMessage: string | null,
): string | null {
  if (engineCode === "op.route_exists") return ROUTE_TAKEN_MESSAGE;
  if (engineCode === "op.route_invalid") return INVALID_ROUTE_MESSAGE;
  return serverMessage;
}
