/**
 * F5 task 21: the pure decision the web inspector's Page card makes — the route
 * field's draft/commit rules.
 *
 * Copied from the platform shell's `inspector-page-field.ts` so the two editor
 * copies refuse a route in the same words and in the same order; the dev shell
 * carries only the route field (no add/remove), so only the route decision and
 * its two messages come across.
 *
 * It lives in this sibling module — not inside the component — so it is
 * testable with no DOM. Nothing here knows about React or the write adapters: a
 * decision is data, and the component is the only thing that fires a write.
 */

import { routeIsValid } from "@/engine/webDocuments";

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
  siblingRoutes: readonly string[]
): RouteFieldDecision {
  const route = draft.trim();
  if (route === current) return { kind: "noop" };
  if (!routeIsValid(route)) return { kind: "refuse", message: INVALID_ROUTE_MESSAGE };
  if (siblingRoutes.includes(route)) return { kind: "refuse", message: ROUTE_TAKEN_MESSAGE };
  return { kind: "commit", route };
}
