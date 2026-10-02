import {
  HANDLE_HIT_RADIUS,
  dragActionToOperations,
  resizeActionToOperation,
} from "../engine/scene/canvaskitGestures";
import type { NodeId, Operation, PageId, Rect, Scene } from "../engine/scene/contracts";
import type {
  GestureAction,
  Modifiers,
  PressTarget,
} from "../engine/scene/gestureMachine";
import {
  getNode,
  isNodeDirectGeometryEditable,
  isNodeFreezableOnGesture,
} from "../engine/scene/sceneQueries";
import { deriveSelectionChromeModel } from "../engine/scene/selectionChrome";
import {
  handlePoint,
  type Box,
  type Point,
  type ResizeHandle,
} from "../engine/scene/transformerMath";
import type { SceneArtboardModel, ScenePreview } from "./scene-canvas-view";

/**
 * AD4.C: every decision on-canvas direct manipulation makes that is NOT a DOM
 * event or a WebGL call — the twin of AD2.5's `scene-selection.ts` for the
 * WRITE half of the pointer.
 *
 * The component around this file owns pointer events and a CanvasKit surface,
 * so (as everywhere on this lane) what could be a function IS one, here,
 * proven against AD2.2's harvested bytes. The host below it is thin: it
 * converts a pointer event into a workspace point, asks this file what the
 * press grabbed, feeds the pure `gestureReducer`, and applies the effect this
 * file resolves for each action it gets back.
 *
 * ── THREE SPACES, AND WHICH ONE EACH THING SPEAKS ────────────────────────
 * `canvaskitGestures.ts` names them, and the whole file is about not mixing
 * them up:
 *
 *   • **stage px** — the pointer's offset inside the stage div, and the units
 *     the G-A selection overlay is stroked in. Pan and zoom live here.
 *   • **descriptor px** — canvas px at zoom 1 (= scene units x the page's
 *     `unitScale`). The gesture machine, the transformer math, the operation
 *     builders and the draw descriptors ALL work here, so this is the space
 *     every `PressTarget` box and every preview box below is in.
 *   • **scene units** — the engine's own `computed` coordinates, which
 *     `engine.hitTest` takes and which `deriveSelectionChromeModel` answers in.
 *
 * The two conversions are `workspace point - artboard origin` (stage→
 * descriptor, once the viewport is undone) and `x unitScale` (scene→
 * descriptor). Both are invisible on the seeded `pt` page (unitScale 1) and
 * wrong by 96x on an `in` one, which is why both are unit-tested against a
 * non-identity unit — the same trap AD2.5's divide and G-A's multiply are.
 *
 * ── WHAT V1 IS (§1.9) ────────────────────────────────────────────────────
 * Drag-to-move and CORNER resize, and nothing else: no rotate handle, no
 * marquee, no drag-reorder of managed children, no managed resize. Those are
 * all reachable in the shared machinery this file drives, so each one is
 * refused HERE, deliberately and by name, rather than left to chance.
 */

/**
 * The artboard's origin in descriptor space.
 *
 * The platform mounts ONE artboard, and `sceneArtboardModel` places it at the
 * workspace origin (`rect: {x: 0, y: 0, …}`) — where the upstream editor has a
 * placement grid of pages, each with its own offset. So the page origin the
 * operation builders take is the zero point, and the descriptor boxes below are
 * page-local already.
 *
 * It is not a decorative zero: `canvasDragOperations`/`canvasResizeOperation`
 * subtract exactly this value back off (`canvasOperations.ts:88-89`) after
 * `dragActionToOperations` adds it on (`canvaskitGestures.ts:94-95`), so any
 * other value would cancel out identically. Zero is the honest one.
 */
export const SCENE_PAGE_ORIGIN: Point = { x: 0, y: 0 };

/**
 * Ruling C-6: v1 accepts the FOUR CORNERS and nothing else — G-A drew four
 * handles, so four are all a press can grab.
 */
export const CORNER_RESIZE_HANDLES: ResizeHandle[] = [
  "top-left",
  "top-right",
  "bottom-left",
  "bottom-right",
];

/**
 * Which CORNER handle a descriptor-space press is grabbing, or null.
 *
 * The four corners are tested directly rather than by filtering
 * `handleAtPoint`'s answer, and the difference is not stylistic. That helper
 * serves the upstream overlay, which draws all nine handles: it tests the
 * rotate hotspot FIRST and then returns the nearest of all eight resize zones.
 * Filtering its answer therefore silently DISCARDS a perfectly good corner grab
 * whenever a zone v1 does not offer happens to be nearer — and the two cases
 * where that happens are exactly the cases where a resize is hardest to aim:
 *
 *  • a THIN or SMALL selection, where an edge zone lies between the pointer and
 *    the corner it is trying to reach (the edge midpoint of a 6px-tall box is
 *    3px from two corners, so the edge always won);
 *  • LOW ZOOM, where the radius is 7 SCREEN px = `7/zoom` descriptor px and
 *    overruns the 22px rotate offset, putting an invisible, in-v1-unreachable
 *    rotate zone on top of the corner the user can actually see.
 *
 * Asking the corners directly cannot lose to a zone that does not exist here.
 * Everything that decides a HIT is `handleAtPoint`'s own arithmetic, kept
 * deliberately identical: `handlePoint` places the (rotated) corner, the radius
 * is the same shared `HANDLE_HIT_RADIUS`, it is divided by the same zoom to
 * stay screen-constant, and nearest-within-tolerance wins. The one deliberate
 * departure is stricter, not different: a degenerate `zoom` (zero, negative,
 * NaN) falls back to 1 rather than dividing raw as `handleAtPoint` does, where
 * a zero would make the tolerance infinite and every corner a hit. No clamped
 * viewport can produce such a zoom, so this only ever errs safe.
 */
export function cornerHandleAtPoint(
  point: Point,
  box: Box,
  rotation: number,
  zoom: number,
  radius = HANDLE_HIT_RADIUS,
): ResizeHandle | null {
  const scale = Number.isFinite(zoom) && zoom > 0 ? zoom : 1;
  const tolerance = radius / scale;
  let best: { handle: ResizeHandle; distance: number } | null = null;
  for (const handle of CORNER_RESIZE_HANDLES) {
    const corner = handlePoint(box, handle, rotation);
    const distance = Math.hypot(point.x - corner.x, point.y - corner.y);
    if (distance <= tolerance && (!best || distance < best.distance)) {
      best = { handle, distance };
    }
  }
  return best?.handle ?? null;
}

/**
 * The modifiers a press carries into the reducer.
 *
 * Shift is the reducer's aspect lock on a corner resize, so it must reach a
 * handle press intact. An EMPTY press carries none, and that is a v1 ruling
 * rather than a detail: the reducer clears the selection only on a
 * *non-additive* empty press (`gestureMachine.ts:96-100`), because upstream
 * keeps a multi-selection alive under a held modifier — but AD2.5 cleared
 * UNCONDITIONALLY, and multi-select is AD4.E's, not this task's. Carrying the
 * live modifier would therefore have quietly changed the read path's behaviour:
 * Shift-clicking empty workspace would stop clearing.
 */
export function scenePressModifiers(
  target: PressTarget,
  modifiers: Modifiers,
): Modifiers {
  return target.kind === "empty" ? {} : modifiers;
}

/** What a press grabbed, plus whether a MOVE may promote it into a gesture. */
export interface SceneGesturePress {
  target: PressTarget;
  /**
   * Ruling C-5 / R5, enforced at the SOURCE rather than at the commit: the
   * host dispatches `move` events only while this is true, so a press that
   * may not drag never reaches `beginGesture` at all — no preview, no
   * committed action, nothing to filter out later. The press itself still
   * reduces to a `select`, so a locked node, a layout-managed child and a
   * press made while an agent turn is in flight all stay selectable.
   *
   * It is also what keeps the marquee out of v1: an empty press is never
   * armed, so the reducer's `empty → marquee` promotion (`gestureMachine.ts`
   * `beginGesture`) has no way to fire, and click-on-empty keeps its AD2.5
   * meaning — clear the selection.
   */
  armed: boolean;
}

/** A press on nothing: AD2.5's clear-selection, and never a gesture. */
export const EMPTY_SCENE_PRESS: SceneGesturePress = {
  target: { kind: "empty" },
  armed: false,
};

/**
 * A workspace-space pointer point in artboard-local DESCRIPTOR px.
 *
 * The first half of AD2.5's chain (`sceneHitPoint`), stopped one step early —
 * before the `unitScale` divide that takes it into the engine's units. That is
 * the space the gesture machine and the operation builders speak, so it is the
 * space the reducer's origin, its move points and every box below are in.
 *
 * Deliberately NOT bounds-checked, where `sceneHitPoint` is: a selection box
 * at the page edge carries handles centred ON that edge, so half of a corner
 * handle's grab radius lies outside the artboard and a press there is a real
 * resize, not a press on nothing. The bounds check belongs to the NODE path,
 * which still runs through `sceneHitPoint` unchanged.
 */
export function sceneDescriptorPoint(
  workspacePoint: Point,
  artboard: SceneArtboardModel,
): Point {
  return {
    x: workspacePoint.x - artboard.rect.x,
    y: workspacePoint.y - artboard.rect.y,
  };
}

/**
 * The corner handle this press is grabbing on the CURRENT selection, or null.
 *
 * Asked FIRST, before the hit test — the upstream host's own order
 * (`CanvasKitCanvas.tsx:587-615`): a handle sits half outside its node's box,
 * over whatever is behind it, so resolving the hit first would make the
 * bottom-right handle of a node select the frame under it instead of resizing.
 *
 * Gated on the chrome model's `showResizeHandles`, which is the same predicate
 * the overlay renders handles from — so a press can only ever grab a handle
 * that is actually drawn. `layoutManagedEditing` is deliberately never passed
 * (§1.9: no managed resize in v1), which leaves `showResizeHandles` equal to
 * `showHandles`, i.e. `isNodeDirectGeometryEditable`.
 *
 * The grab radius is `HANDLE_HIT_RADIUS` in SCREEN px. `cornerHandleAtPoint`
 * divides it by the scale between its point space and the screen — and because
 * descriptor px ARE workspace units here (`sceneArtboardModel`'s rect is the
 * page box in descriptor px, and the viewport is what maps workspace→screen),
 * that scale is exactly `viewport.zoom`, with `unitScale` already folded into
 * the box. Both are tested.
 */
export function scenePressHandleTarget({
  artboard,
  gesturesEnabled,
  pageId,
  point,
  scene,
  selectedNodeId,
  zoom,
}: {
  artboard: SceneArtboardModel;
  /** R5: false while the G-H gate holds — no handles, so nothing to grab. */
  gesturesEnabled: boolean;
  pageId: PageId | null;
  /** The press, in artboard-local descriptor px. */
  point: Point;
  scene: Scene;
  selectedNodeId: NodeId | null;
  /** The viewport's zoom — what makes the grab radius screen-constant. */
  zoom: number;
}): PressTarget | null {
  if (!gesturesEnabled || !selectedNodeId) {
    return null;
  }
  const { selectionBox, showResizeHandles } = deriveSelectionChromeModel(scene, {
    activePageId: pageId,
    selectedNodeId,
  });
  if (!selectionBox || !showResizeHandles) {
    return null;
  }
  const box = descriptorBox(selectionBox.box, artboard.page.unitScale);
  // Ruling C-6: the four corners, asked directly — never the rotate hotspot or
  // an edge zone, which v1 neither draws nor offers.
  const handle = cornerHandleAtPoint(point, box, selectionBox.rotation, zoom);
  if (!handle) {
    return null;
  }
  return {
    kind: "handle",
    nodeId: selectionBox.nodeId,
    handle,
    box,
    rotation: selectionBox.rotation,
  };
}

/**
 * The press target for the node a hit test resolved to (§5's representable
 * ancestor), and whether it may be dragged.
 *
 * The box is the HIT node's own laid-out box, read through the same
 * `deriveSelectionChromeModel` oracle the overlay reads the SELECTED node's
 * from — so the geometry the drag starts from and the geometry the outline
 * draws can never be derived two different ways. A node the engine has not laid
 * out yet has no box at all; it still selects (AD2.5's behaviour, and the
 * harvest's honest at-rest state is `computed: null` on every node), but there
 * is nothing to move, so the press is not armed.
 */
export function scenePressNodeTarget({
  artboard,
  gesturesEnabled,
  nodeId,
  pageId,
  scene,
}: {
  artboard: SceneArtboardModel;
  gesturesEnabled: boolean;
  nodeId: NodeId | null;
  pageId: PageId | null;
  scene: Scene;
}): SceneGesturePress {
  if (!nodeId || !scene.nodes[nodeId]) {
    return EMPTY_SCENE_PRESS;
  }
  const { selectionBox } = deriveSelectionChromeModel(scene, {
    activePageId: pageId,
    selectedNodeId: nodeId,
  });
  const box = selectionBox
    ? descriptorBox(selectionBox.box, artboard.page.unitScale)
    : { x: 0, y: 0, width: 0, height: 0 };
  return {
    target: {
      kind: "node",
      nodeId,
      box,
      rotation: selectionBox?.rotation ?? 0,
    },
    // Ruling C-5: a node whose press cannot commit must not preview either, or
    // the ad appears to move and then snaps back with nothing said. LOCKED
    // nodes are that case and stay refused here.
    //
    // Ruling C-9 narrows it to LOCKED alone. A layout-MANAGED node is no
    // longer refused: the human's press freezes the document's auto-layout
    // first (zero-motion, silent — `shouldFreezeLayoutOnPress` below), which
    // makes the very same node directly editable, so by the time the drag
    // commits the builders take it. Arming against the PRE-freeze scene is
    // correct and is what upstream does: the freeze moves nothing, so the box
    // this press starts from is numerically identical either side of it.
    armed:
      gesturesEnabled &&
      Boolean(selectionBox) &&
      (isNodeDirectGeometryEditable(scene, nodeId) ||
        isNodeFreezableOnGesture(scene, nodeId)),
  };
}

/**
 * Ruling C-9 (handoff-absolute freeze-on-grab): must this press bake the
 * document's auto-layout to free placement BEFORE the gesture starts?
 *
 * The agent works in auto-layout; the human does not know what auto-layout is
 * and must never be refused by it. Upstream's MVP editor answers this by
 * firing a whole-document `freeze_layout` structured edit on the pointer-down
 * that grabs a solver-owned node, then letting the SAME press continue as a
 * free drag (`CanvasKitCanvas.tsx:1056-1076`). The edit is zero-motion (every
 * child is baked to the position it already solved at) and idempotent (an
 * empty operation batch once nothing is left to freeze), so firing it on a
 * click that never becomes a drag costs nothing and changes nothing.
 *
 * `isNodeFreezableOnGesture` is an explicit allow-list — "blocked for NO
 * reason other than solver ownership" — so this refuses a locked node, a
 * node that is already directly editable (nothing to gain), and a press on
 * nothing.
 *
 * Ruling C-10: BOTH `node` and `handle` targets freeze. Upstream guards on
 * `node` alone, which is safe only because upstream never draws handles on a
 * managed node; this platform does (C-9 widened `showResizeHandles`), and a
 * drawn handle that grabs and then silently commits nothing is exactly the
 * defect class C-5 exists to prevent.
 *
 * `gesturesEnabled` is the G-H gate, and it belongs here for a stronger reason
 * than symmetry: a freeze is a WRITE. While an agent turn is in flight no
 * write of the human's may land, so mid-turn no freeze fires and managed nodes
 * keep the select-only behaviour they had before this ruling.
 */
export function shouldFreezeLayoutOnPress({
  gesturesEnabled,
  scene,
  target,
}: {
  gesturesEnabled: boolean;
  scene: Scene;
  target: PressTarget;
}): boolean {
  if (!gesturesEnabled) {
    return false;
  }
  if (target.kind !== "node" && target.kind !== "handle") {
    return false;
  }
  return isNodeFreezableOnGesture(scene, target.nodeId);
}

/**
 * After the C-9 freeze has been applied: may this press actually arm?
 *
 * Asked of the NODE, against the POST-freeze scene — never inferred from the
 * size of the freeze's operation batch. `build_freeze_layout` iterates the
 * whole document and skips only LOCKED containers, so a batch can be non-empty
 * (it freed some other Stack) while the pressed node's own container stayed
 * locked and solver-owned. Reading "non-empty" as "this node was freed" armed
 * exactly the press that cannot commit — the C-5 defect (grab, preview, commit
 * nothing) the guard exists to prevent — in any document with two or more
 * Stack containers, which is the normal shape of an agent-generated ad.
 *
 * `isNodeDirectGeometryEditable` is the same predicate the operation builders
 * refuse on, so this answers the question the commit will actually be asked,
 * one gesture earlier.
 */
export function pressArmedAfterFreeze(
  scene: Scene | null,
  target: PressTarget,
): boolean {
  if (!scene) {
    return false;
  }
  if (target.kind !== "node" && target.kind !== "handle") {
    return false;
  }
  return isNodeDirectGeometryEditable(scene, target.nodeId);
}

/**
 * Ruling C-12: what a freeze outcome hands to the PERSIST path — and nothing
 * else.
 *
 * The engine has ALREADY applied these operations (`applyStructuredEdit` is
 * apply-and-report, not a plan), so they must reach the edit queue WITHOUT
 * being applied a second time — never through the ordinary `applyOps` write
 * path, which applies first. Persisting them as one plain operation batch is
 * also what makes the freeze its own undo frame, upstream parity: one ⌘Z
 * undoes the drag, a second restores auto-layout.
 *
 * An empty batch is the idempotent already-frozen case, and it is dropped
 * here rather than at the queue: a document that is already free has nothing
 * to persist, and the design API's own edits route answers an empty batch
 * with a 422.
 */
export function freezeOperationsToPersist(
  outcome: { accepted: boolean; operations: Operation[] } | null,
): Operation[] {
  if (!outcome || !outcome.accepted) {
    return [];
  }
  return outcome.operations;
}

/** Anything above this on x/y/width (and on a non-text height) is motion. */
const FREEZE_MOTION_TOLERANCE = 1e-6;
/** A text node's un-baked hug height re-measures within a pixel — see above. */
const FREEZE_TEXT_HEIGHT_TOLERANCE = 1.0;

/** One node whose solved box is not where it was before the freeze. */
export interface FreezeMotionEntry {
  id: NodeId;
  before: Rect;
  after: Rect;
}

/** The answer `freezeMotionReport` gives: every node the freeze moved. */
export interface FreezeMotionReport {
  moved: FreezeMotionEntry[];
}

/**
 * Whether a freeze moved anything — the runtime half of the zero-motion
 * contract the engine tests pin offline.
 *
 * A freeze is a pure re-expression of the solve: it bakes each managed
 * container's placement into Free coordinates so the very press that fired it
 * can drag. If it MOVES a node, the ad visibly jumps under the human's finger
 * (2026-09-20: every container in the agent's ads is `fill`-width, and the old
 * bake snapped hugged rows to the artboard edge on first grab). That is an
 * ENGINE defect, never something the canvas can repair — so this reports it
 * loudly and changes nothing: ruling C-9 stands, the press goes on to arm.
 *
 * Compared per node id off `computed.layout_bounds`, the same numbers the
 * gesture machine captured at press time. Ids absent on either side are
 * ignored: a node that the freeze did not place (or that has no solved box
 * yet) has no "before" and "after" to disagree.
 *
 * Tolerances mirror the engine's own real-ad test: x / y / width to 1e-6,
 * because those are baked Fixed extents and a baked transform and any drift
 * there is a real regression; a TEXT node's height to 1.0px, because a hug
 * height is deliberately left un-baked and re-measures within a pixel of its
 * whole-pixel-rounded Stack height. Unlike that test there is no node
 * allow-list here — this runs over documents nobody enumerated.
 */
export function freezeMotionReport(before: Scene, after: Scene): FreezeMotionReport {
  const moved: FreezeMotionEntry[] = [];
  for (const [id, beforeNode] of Object.entries(before.nodes)) {
    const afterNode = after.nodes[id];
    const wasBox = beforeNode?.computed?.layout_bounds;
    const nowBox = afterNode?.computed?.layout_bounds;
    if (!wasBox || !nowBox) {
      continue;
    }
    const isText = beforeNode.kind.kind === "text" || afterNode.kind.kind === "text";
    const heightTolerance = isText ? FREEZE_TEXT_HEIGHT_TOLERANCE : FREEZE_MOTION_TOLERANCE;
    const drifted =
      Math.abs(nowBox.x - wasBox.x) > FREEZE_MOTION_TOLERANCE ||
      Math.abs(nowBox.y - wasBox.y) > FREEZE_MOTION_TOLERANCE ||
      Math.abs(nowBox.width - wasBox.width) > FREEZE_MOTION_TOLERANCE ||
      Math.abs(nowBox.height - wasBox.height) > heightTolerance;
    if (drifted) {
      moved.push({ id: id as NodeId, before: { ...wasBox }, after: { ...nowBox } });
    }
  }
  return { moved };
}

/** What the host does with one reduced `GestureAction`. */
export type SceneGestureEffect =
  | { kind: "none" }
  /** Ruling C-8: `additive` is dropped — multi-select is not this task's. */
  | { kind: "select"; nodeId: NodeId | null }
  /** A live, uncommitted gesture: a render-time override, never a write. */
  | { kind: "preview"; preview: ScenePreview | null }
  /** The gesture ended: drop the preview, then write these (if any). */
  | { kind: "commit"; operations: Operation[]; intent: string };

/**
 * The action the reducer returned, resolved into the one thing the host does.
 *
 * The whole of AD4.C's R2 in one pure function, so the host holds no policy:
 *
 *  • `select` → the canvas's existing `commitSelection`.
 *  • an uncommitted `drag`/`resize` → the preview override. The document scene
 *    is NEVER touched by a gesture in flight (AD4.R: the engine scene owns
 *    document values), so Escape or a pointer-cancel is just "drop the
 *    preview" and the artboard repaints at the document's own truth.
 *  • a committed `drag`/`resize` → the EXISTING operation builders, which is
 *    the whole point of the shared machinery: the geometry rules (guide
 *    snapping, parent-bounds clamping, pinned-descendant carry, the
 *    scale-factor resize) are the design subsystem's, not re-derived here.
 *
 * `rotate` and `marquee` are unreachable in v1 by construction — no rotate
 * target is ever built (Ruling C-6) and an empty press is never armed, so the
 * reducer's marquee promotion cannot fire — and are refused here as the second
 * lock on the same door.
 *
 * An empty `operations` array is a real answer, not a failure: it is what the
 * builders return for a node they refuse. The host must not call the write path
 * with it — a write that changes nothing is not a write.
 */
export function sceneGestureEffect(
  action: GestureAction,
  scene: Scene,
  pageId: PageId | null,
): SceneGestureEffect {
  if (action.kind === "select") {
    return { kind: "select", nodeId: action.nodeId };
  }
  if (action.kind !== "drag" && action.kind !== "resize") {
    // "none", and the two v1 refuses to reach: "rotate" and "marquee".
    return { kind: "none" };
  }
  const page = pageId ? scene.pages[pageId] : null;
  const node = getNode(scene, action.nodeId);
  if (!page || !node) {
    return { kind: "none" };
  }
  // Rotation is not a v1 gesture, so it is the node's own, unchanged — the
  // same value upstream reads off the render descriptor.
  const rotation = node.transform.rotation;
  if (!action.committed) {
    return {
      kind: "preview",
      preview: { nodeId: action.nodeId, box: action.box, rotation },
    };
  }
  if (action.kind === "drag") {
    return {
      kind: "commit",
      operations: dragActionToOperations(
        action.box,
        scene,
        node,
        page,
        SCENE_PAGE_ORIGIN,
      ),
      intent: SCENE_DRAG_INTENT,
    };
  }
  const operation = resizeActionToOperation(
    action.box,
    rotation,
    scene,
    node,
    page,
    SCENE_PAGE_ORIGIN,
    // §1.9: `allowManagedResize` stays false — no managed resize in v1.
  );
  return {
    kind: "commit",
    operations: operation ? [operation] : [],
    intent: SCENE_RESIZE_INTENT,
  };
}

/**
 * The write labels, following the lane's own convention: the intent names the
 * SURFACE the edit came from (`"inspector: <property>"` at
 * `use-scene-inspector-writes.ts:301,337`), so a canvas gesture says canvas.
 */
export const SCENE_DRAG_INTENT = "canvas: drag";
export const SCENE_RESIZE_INTENT = "canvas: resize";

/**
 * Whether the G-A corner handles are offered for the current selection.
 *
 * Three conditions, and each says something different:
 *
 *  • the chrome model's `showResizeHandles` — the DOCUMENT's answer (a locked
 *    or layout-managed node cannot be dragged, so a handle on it would be a
 *    fake affordance; that is the same reason the handles waited for this task
 *    at all);
 *  • `!engineDisabled` — with no engine there is no hit test, no apply and no
 *    selection change (AD2.5/G-D), so nothing a handle promises can happen;
 *  • `!gestureDisabled` — Gate G-H: while an agent turn is in flight the
 *    human's direct manipulation is off, so the affordance goes with it.
 *
 * The OUTLINE is unaffected by all three: a locked node, a read-only canvas and
 * an in-flight turn all still show the user what is selected.
 */
export function sceneSelectionHandlesVisible({
  engineDisabled,
  gestureDisabled,
  pageId,
  scene,
  selectedNodeId,
}: {
  engineDisabled: boolean;
  gestureDisabled: boolean;
  pageId: PageId | null;
  scene: Scene | null;
  selectedNodeId: NodeId | null;
}): boolean {
  if (!scene || !selectedNodeId || engineDisabled || gestureDisabled) {
    return false;
  }
  return deriveSelectionChromeModel(scene, {
    activePageId: pageId,
    selectedNodeId,
  }).showResizeHandles;
}

/** A scene-unit box in descriptor px — G-A's own multiply
 * (`selectionOutlineForBox`), applied to a box rather than a rect. */
function descriptorBox(box: Box, unitScale: number): Box {
  const scale = Number.isFinite(unitScale) && unitScale > 0 ? unitScale : 1;
  return {
    x: box.x * scale,
    y: box.y * scale,
    width: box.width * scale,
    height: box.height * scale,
  };
}
