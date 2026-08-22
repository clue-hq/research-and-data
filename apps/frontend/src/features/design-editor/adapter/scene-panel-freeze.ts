import type { NodeId, Scene } from "../engine/scene/contracts";
import { isNodeFreezableOnGesture } from "../engine/scene/sceneQueries";
import { finiteNumber } from "./scene-hydrate";

/**
 * C-9 PANEL PARITY — what the inspector panel must do with one geometry commit.
 *
 * Ruling C-9 (founder, already shipped on the canvas by Lane C): the end user
 * is a marketer. Auto-layout is the AGENT's tool, and a human manipulating a
 * node must never be refused by the solver. On the canvas the answer is
 * freeze-on-grab — the press bakes the document's layout to free placement
 * (idempotent; zero-motion is the engine's INTENT and is proven only for a
 * fixed-size container — see the closing paragraph) and the very same gesture
 * continues as a free drag.
 *
 * This module is that same physics for the PANEL, and it is deliberately only
 * the DECISION: the hook owns the sequence (freeze → persist → rebuild the
 * operation against the post-freeze scene), exactly as the canvas host owns its
 * own (`scene-artifact-canvas.tsx`'s `freezeLayoutForPress`). Both surfaces ask
 * ONE predicate — `isNodeFreezableOnGesture`, the engine-mirroring allow-list
 * in `sceneQueries.ts` — which is imported here and never re-implemented, so
 * the canvas and the panel can never drift into two opinions about which nodes
 * the solver owns.
 *
 * THE TWO ROW FAMILIES THIS REPLACES, which are NOT the same case today:
 *
 *  • Position X/Y and Rotation are refused outright on a solver-managed node —
 *    `positionOperation` (`scene-apply.ts:615`) and the rotation arm (`:943`)
 *    both return `null` behind `isNodeDirectGeometryEditable`. The panel draws
 *    no disabled state for them (`scene-hydrate.ts` states the rows
 *    unconditionally), so the input accepts the number and the write silently
 *    evaporates — the AD4 signature defect. Its display half is Ruling C9-P2,
 *    fixed in `scene-hydrate.ts`'s `solvedManagedOffset`: the row now states
 *    the SOLVED parent-relative offset — the frame the freeze bakes and the
 *    write therefore lands in — instead of the dead stored transform.
 *  • Width/Height are NOT refused: Ruling L12 leaves that arm ungated
 *    (`scene-apply.ts:970-998`), the engine accepts the size patch, and the
 *    next relayout re-solves the Stack — so the edited node takes its size and
 *    ITS SIBLINGS MOVE. Freeze-first REPLACES that behaviour, by the founder's
 *    own words for this slice ("changing the size via the corner handles… the
 *    position of that node or any surrounding nodes should not change"). It is
 *    a disclosed behaviour change, not a repair of a dead path.
 *
 * WHAT IS NOT HERE. The engine's zero-motion guarantee for a HUG-height
 * container is unproven (the wasm fixture's container is fixed-size; the ad's
 * `auto_row_copy` is width-fixed / height-hug), so nothing in this slice claims
 * it. The claim made here is only about which rows freeze first.
 */

/**
 * The rows the solver owns — the ones a freeze changes the answer for.
 *
 * Exactly the property names `sceneChangeToOperation` routes to its geometry
 * arms (`scene-apply.ts`: `case "position.x"`, `"position.y"`, `"rotation"`,
 * `"width"`, `"height"`). Paint, type, layout INPUTS (gap, padding, align) and
 * §1.0's lock are all outside it: none of them is refused by solver ownership,
 * so none of them may fire a document-wide freeze.
 */
export const PANEL_GEOMETRY_PROPERTIES: ReadonlySet<string> = new Set([
  "position.x",
  "position.y",
  "rotation",
  "width",
  "height",
]);

/**
 * `"freeze-then-write"` — bake the layout first, then write against the scene
 * the freeze returned.
 * `"write"` — today's path, untouched: build the operation and apply it.
 * `"refuse"` — no write is possible (a locked node's geometry, a node the
 * scene does not carry, a value the adapter would not parse). The ordinary path
 * already answers these with `null`; saying so here keeps a freeze from firing
 * for a write that cannot land.
 */
export type PanelWriteIntent = "freeze-then-write" | "write" | "refuse";

/**
 * Whether the COMMITTED VALUE is one `sceneChangeToOperation` would actually
 * turn into a geometry operation — asked before any freeze fires.
 *
 * The freeze is a document-wide write: it converts every unlocked Stack to
 * Free, persists a batch to the server and burns an undo step. Firing it for a
 * commit the adapter is going to answer with `null` spends all of that for no
 * write, no motion and no message — so the adapter's OWN value rules are
 * mirrored here, and only here, ahead of the decision:
 *   • the value must be a string (`scene-apply.ts:688` coerces anything else to
 *     `null` and returns), and `finiteNumber` (imported, not re-implemented)
 *     must parse it — the `case "position.x"`/`"rotation"` guards;
 *   • width/height additionally refuse anything below 1 (`scene-apply.ts:983`:
 *     the ad's size fields are free text, so the MVP's `min={1}` is a refusal
 *     rather than a browser-enforced minimum).
 * These are duplicated deliberately and minimally — the adapter stays the sole
 * authority on what WRITES; this only decides what is worth freezing for.
 */
function geometryValueWritable(property: string, value: unknown): boolean {
  if (typeof value !== "string") {
    return false;
  }
  const parsed = finiteNumber(value);
  if (parsed === null) {
    return false;
  }
  return property === "width" || property === "height" ? parsed >= 1 : true;
}

/**
 * One panel property change → what the write path should do about the solver.
 *
 * ORDER IS LOAD-BEARING. The property test comes FIRST so that §1.0's lock row
 * — the one row `sceneChangeToOperation` decides ahead of its own lock gate —
 * keeps working on a locked node; testing the lock first would make a locked
 * node permanently locked, which is the trap the adapter documents at its own
 * `case "locked"`.
 *
 * The hook asks this TWICE: once against the live scene to decide whether to
 * freeze, and once against the POST-freeze scene to decide whether the write
 * may now land. The second ask is the `c81cd209` pattern — ask the NODE, never
 * the size of the freeze's operation batch — because `build_freeze_layout`
 * skips LOCKED containers while still freeing every other Stack, so a non-empty
 * batch does not mean THIS node was freed.
 */
export function panelWriteIntent(
  scene: Scene,
  nodeId: NodeId | null,
  property: string,
  /** The committed value, exactly as the event carries it (`unknown`, like
   * `SceneChangeDetail.value`). Geometry rows are decided against it: a freeze
   * fires only where a real write follows. */
  value: unknown,
): PanelWriteIntent {
  // Not a row the solver has an opinion about → nothing here applies.
  if (!PANEL_GEOMETRY_PROPERTIES.has(property)) {
    return "write";
  }
  if (!nodeId) {
    return "refuse";
  }
  const node = scene.nodes[nodeId];
  // The write can never be aimed at a node that is not there — and a freeze is
  // a document-wide write, far too much to fire for a phantom selection.
  if (!node) {
    return "refuse";
  }
  // C-9 removed the MANAGED refusal and left the LOCK exactly where it was:
  // locked nodes keep their lock/unlock gate, managed nodes need no unlock at
  // all. (`isNodeFreezableOnGesture` refuses a locked node too; stating it
  // here is what makes the refusal legible rather than a fall-through.)
  if (node.locked) {
    return "refuse";
  }
  // A value the adapter would refuse produces no operation on ANY node, so
  // there is nothing for a freeze to enable — and a document-wide freeze for a
  // typo (`abc` in X, `0` in Width) would convert every Stack in the document,
  // persist a batch and burn an undo step with nothing to show for it. Said as
  // `"refuse"` because that is the truth about the commit; the hook lets it
  // fall through to the ordinary path, which answers `null` exactly as before,
  // so no non-managed row changes behaviour.
  if (!geometryValueWritable(property, value)) {
    return "refuse";
  }
  return isNodeFreezableOnGesture(scene, nodeId) ? "freeze-then-write" : "write";
}
