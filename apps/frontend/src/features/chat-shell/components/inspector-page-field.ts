/**
 * F5 task 19: the pure decisions the web inspector's Page section makes — the
 * route field's draft/commit rules, the page id a new page's name slugs to,
 * and the two structural refusals on Remove.
 *
 * They live in this sibling module — not inside the component — so they are
 * testable under `tsx --test` with no DOM, exactly as `inspector-field-draft.ts`
 * is. Nothing here knows about React, the session, or the write adapters: a
 * decision is data, and the component is the only thing that fires a write.
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
 * The engine's `op.route_exists` refusal, said plainly. The field refuses a
 * collision it can see locally BEFORE the round trip; the same sentence is what
 * the write path shows when the server is the one that catches it (a page added
 * by an agent turn between this document load and this commit).
 */
export const ROUTE_TAKEN_MESSAGE = "That route is already used by another page.";

/** A page has to be named before it can be added — an empty box has nothing to
 * slug, and minting "/page" for it would be inventing the user's intent. */
export const NAME_THE_PAGE_MESSAGE = "Name the page first.";

export type RouteFieldDecision =
  | { kind: "commit"; route: string }
  | { kind: "refuse"; message: string }
  | { kind: "noop" };

/**
 * What a blur/Enter on the route field does.
 *
 * `current` is the LIVE document route for this page and `siblingRoutes` the
 * routes of the OTHER pages (the caller excludes this page). Order is
 * load-bearing:
 *   1. unchanged → `noop` (never a write, and it can never self-refuse on a
 *      sibling list that mistakenly includes this page's own route);
 *   2. ungrammatical → `refuse` (the engine would reject it as
 *      `op.route_invalid`, so the field says so without spending a round trip);
 *   3. already taken → `refuse` (the engine's `op.route_exists`, same reason);
 *   4. otherwise → `commit` the trimmed route.
 *
 * A refusal returns no route at all, which is what makes "no write fires on an
 * invalid draft" structural rather than a habit of the component.
 */
export function routeFieldDecision(
  draft: string,
  current: string,
  siblingRoutes: readonly string[],
): RouteFieldDecision {
  const route = draft.trim();
  if (route === current) return { kind: "noop" };
  if (!routeIsValid(route)) return { kind: "refuse", message: INVALID_ROUTE_MESSAGE };
  if (siblingRoutes.includes(route)) return { kind: "refuse", message: ROUTE_TAKEN_MESSAGE };
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

export type AddPageDecision =
  | { kind: "commit"; page: { id: string; name: string; route: string } }
  | { kind: "refuse"; message: string };

/**
 * What "Add page" does with the typed name: the id is the name's slug and the
 * route is `/` + that slug, so a marketer names a page and gets the obvious
 * URL. Both engine refusals are checked locally first — the derived route can
 * still be ungrammatical (`Asset Store` → `/asset-store`, which is never a
 * first segment: it is served beside a published site) or already taken.
 */
export function addPageDecision(
  name: string,
  siblingRoutes: readonly string[],
): AddPageDecision {
  const trimmed = name.trim();
  if (trimmed === "") return { kind: "refuse", message: NAME_THE_PAGE_MESSAGE };
  const id = pageIdFromName(trimmed);
  const route = `/${id}`;
  if (!routeIsValid(route)) return { kind: "refuse", message: INVALID_ROUTE_MESSAGE };
  if (siblingRoutes.includes(route)) return { kind: "refuse", message: ROUTE_TAKEN_MESSAGE };
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
