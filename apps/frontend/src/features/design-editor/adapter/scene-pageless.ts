import type { PageId, Scene } from "../engine/scene/contracts";
import { firstPageId } from "../engine/scene/sceneQueries";

/**
 * genad2 Task 5 — the ZERO-PAGE lifecycle of a scene (ad) document.
 *
 * The platform's `open_design_leg@4` births a chat-born ad as a document with
 * `pages: {}` (genad2 ruling 1: the design agent authors every page, and the
 * platform mints none). So there is now a real, reachable window in which a
 * document exists, its gallery card exists, its tab auto-opens — and it has no
 * page at all until a later agent turn authors one.
 *
 * This module is the whole decision for that window, in one pure place, because
 * two surfaces have to agree about it: the canvas stage (which would otherwise
 * paint an unexplained empty workspace) and the ad inspector's canvas schema
 * (which would otherwise show `DEFAULT_STATE`'s invented `1200`x`1200` and a
 * `Linkedin square` preset over a document that measures nothing). The same
 * only-facts-are-displayed rule the AD4.0 review applied to page sizes applies
 * here at the extreme: with no page, there is no size, no preset and no
 * background, so the panel states none of them.
 *
 * The copy lives here rather than in a component for the reason
 * `scene-engine-banners.ts` gives for its own: pure, so the wording is pinned by
 * a plain unit test.
 *
 * FOUNDER-DESIGN FLAG (open, recorded 2026-08-23): only the WORDS below are
 * ratified. The neutral state's *visual* — typography, illustration, placement,
 * whether the inspector says anything at all — is an unmade design decision.
 * Both render sites therefore ship this sentence as PLAIN TEXT in the idiom
 * their surface already has (the stage: a centred line on the empty workspace;
 * the inspector: its existing `.inspectorStatusNote` line), and neither invents
 * styled UI. See the presentation-truth rule: the dummy frontend is the only
 * source of designed UI.
 *
 * KNOWN RESIDUAL under the same flag (recorded 2026-08-23, Task-7 sweep): the
 * artifact header still reads "100%" zoom over a pageless document, which has
 * nothing to zoom. It is stale chrome rather than a fabricated measurement (no
 * size, preset or dimension is claimed anywhere), so it was left alone — the
 * header's zoom control is part of the same undesigned empty state and should
 * be decided with it, not patched piecemeal by this lane.
 */

/**
 * What a zero-page document says, verbatim (founder copy, 2026-08-23).
 *
 * One string, shared by both render sites: a second wording would be this
 * lane authoring product copy, which it may not.
 */
export const PAGELESS_SCENE_NOTICE =
  "Design hasn't created the page yet — it will appear when generation completes. Send a message to start (or retry).";

/**
 * Does this loaded document have no page at all?
 *
 * Note what this is NOT: "the page has not loaded". A null scene is an
 * unanswered document, and the two must never collapse — see
 * `scenePagelessNotice`.
 */
export function isPagelessScene(scene: Scene): boolean {
  return Object.keys(scene.pages).length === 0;
}

/**
 * The line the canvas stage shows, or `null` for "say nothing".
 *
 * Three states, deliberately distinct:
 *
 *  • **not loaded** (`scene === null`) → null. The document has not answered
 *    yet, so claiming the agent has not authored a page would be a fabrication
 *    in the other direction.
 *  • **loaded, zero pages** → the notice. This is the honest window.
 *  • **loaded, has pages** → null, whatever `pageId` says. The notice is earned
 *    by the document's own emptiness, never by an unresolved page id.
 */
export function scenePagelessNotice(
  scene: Scene | null,
  pageId: PageId | null,
): string | null {
  if (!scene || !isPagelessScene(scene)) {
    return null;
  }
  // A pageless scene cannot have resolved a page id; if one is somehow present
  // the document is not the state this notice describes.
  return pageId === null ? PAGELESS_SCENE_NOTICE : null;
}

/**
 * Editor Quality Plan 2, item D — the page the canvas should DRAW.
 *
 * `use-scene-document` picks `pageId = firstPageId(loaded.scene)` ONCE at
 * load. A chat-born ad loads pageless (`open_design_leg@4` births `pages: {}`),
 * so that id stays null even after the reveal pump has applied a streamed
 * `add_page` — the engine has the page, the drawn scene has the page, and the
 * stage kept showing the pageless notice until a checkpoint reload replaced
 * the loaded scene. This is the one derivation both the artboard model and
 * the notice read: the loaded id when there is one, else the first page of
 * whatever scene is being drawn.
 */
export function effectiveScenePageId(
  loadedPageId: PageId | null,
  drawnScene: Scene | null,
): PageId | null {
  if (loadedPageId !== null) {
    return loadedPageId;
  }
  return drawnScene ? firstPageId(drawnScene) : null;
}
