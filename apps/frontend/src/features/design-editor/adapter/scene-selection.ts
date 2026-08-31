import type { NodeId, PageId, Scene } from "../engine/scene/contracts";
import { descriptorToScene } from "../engine/scene/canvaskitGestures";
import type { Point } from "../engine/scene/workspaceLayout";
import type { SceneArtboardModel } from "./scene-canvas-view";
import { rootFrameId, sceneSelectionFor } from "./scene-hydrate";

/**
 * AD2.5: the two pure decisions behind clicking a rendered ad.
 *
 * The component around this file owns pointer events and a WebGL surface, so
 * everything that could be a function IS one, here, proven against AD2.2's
 * harvested bytes: where the pointer lands in the engine's own units, and which
 * node the engine's answer actually selects.
 *
 * Both are ported from the design editor's own `CanvasKitCanvas`
 * (`subsystems/clue-design/apps/editor/src/components/canvas/CanvasKitCanvas.tsx:589-617`
 * and its `updateHoverFromEvent` twin above it), collapsed to ONE artboard: the
 * platform mounts a single document inside the dummy's artboard hole, so the
 * source's `artboardAtWorkspacePoint(workspaceModel, …)` lookup over a
 * placement grid becomes a bounds check against the one artboard's rect.
 */

/**
 * A workspace-space pointer point in SCENE units, or null when it misses the
 * artboard entirely.
 *
 * The whole coordinate trap lives in these three lines, in this order:
 *
 *  1. subtract the artboard's workspace origin — the point becomes
 *     artboard-local **descriptor px** (canvas px at zoom 1);
 *  2. divide by the page's `unitScale` — descriptor px become the engine's own
 *     `computed` units, which is what `engine.hitTest` takes. Skipping this is
 *     silent and invisible on a `pt`/`px` page (unitScale 1, which the seeded
 *     ad is) and wrong by 96x on an `in` page.
 *
 * Outside the artboard there is no scene point at all — the caller must not
 * hit-test, because page-space coordinates outside the page box are not
 * meaningfully "empty canvas", they are nothing. The source editor spells this
 * as "no artboard under the pointer → no hit"; with one artboard it is a rect
 * containment test, edges inclusive.
 */
export function sceneHitPoint(
  workspacePoint: Point,
  artboard: SceneArtboardModel,
): Point | null {
  const { rect } = artboard;
  if (
    workspacePoint.x < rect.x ||
    workspacePoint.y < rect.y ||
    workspacePoint.x > rect.x + rect.width ||
    workspacePoint.y > rect.y + rect.height
  ) {
    return null;
  }
  return descriptorToScene(
    { x: workspacePoint.x - rect.x, y: workspacePoint.y - rect.y },
    artboard.page.unitScale,
  );
}

/**
 * The node a hit stack SELECTS — the topmost member that has an inspector
 * schema at all (mapping contract §5's representable-ancestor rule).
 *
 * `stack` is `HitResult.stack` exactly as the engine returns it: **bottom-to-
 * top**, so the last member is the topmost node under the pointer. The walk
 * therefore runs backwards, which is the top-down order §5 asks for; passing a
 * pre-reversed stack would silently select the outermost container instead.
 *
 * Representability is not re-decided here. `sceneSelectionFor` is the single
 * oracle (AD2.4) — it returns null for line / vector / instance, the three
 * kinds the ad inspector has no v1 schema for — so a kind list is never written
 * twice and a future schema addition changes selection behaviour for free. The
 * root frame needs `rootFrameId` because it routes to the *canvas* schema
 * rather than a frame's, which is why the page id is an argument; an unknown
 * page only changes which schema the frame gets, never whether it is
 * selectable.
 *
 * A stack member missing from the scene is skipped rather than throwing: the
 * engine answers from its own relaid scene and the rendered snapshot can lag it
 * by a frame, and a stale id must degrade to "select the thing under it", never
 * crash the shell.
 *
 * Returns null for an empty stack (a click on nothing) and for a stack of only
 * unrepresentable nodes — both mean "clear the selection", never a guess.
 */
export function representableHit(
  stack: NodeId[],
  scene: Scene,
  pageId: PageId | null,
): NodeId | null {
  const root = pageId ? rootFrameId(scene, pageId) : null;
  for (let index = stack.length - 1; index >= 0; index -= 1) {
    const node = scene.nodes[stack[index]];
    if (node && sceneSelectionFor(node, root) !== null) {
      return node.id;
    }
  }
  return null;
}
