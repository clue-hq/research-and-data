import type {
  Node,
  NodeId,
  Operation,
  PageId,
  Scene,
} from "../engine/scene/contracts";
import { updateTextNode } from "../engine/scene/operations";
import { nodeDescriptor } from "../engine/scene/renderAdapter";
import {
  getNode,
  parentComputedOrigin,
  topLevelAncestorId,
} from "../engine/scene/sceneQueries";
import { deriveSelectionChromeModel } from "../engine/scene/selectionChrome";
import type { WorkspaceViewport } from "../engine/scene/workspaceViewport";
import {
  selectionOutlineForBox,
  type SceneArtboardModel,
} from "./scene-canvas-view";

/**
 * Rung B of the rich-text ladder (`docs/superpowers/plans/2026-08-24-rich-text-editing.md`,
 * founder-directed 2026-08-24): every decision double-click inline text editing
 * makes that is NOT a DOM event.
 *
 * This SUPERSEDES the AD4.C §1.9/§7 "no double-click text" scope line. The
 * behaviour is the design subsystem's own `TextEditOverlay` +
 * `CanvasKitCanvas`'s `editing`/`onDoubleClick`/`commitTextEdit` trio
 * (`subsystems/clue-design/apps/editor/src/components/canvas/`), ported rather
 * than reinvented: CanvasKit cannot host a caret, so the session is a DOM
 * `<textarea>` positioned over the node and styled to match it, the painted
 * text under it is suppressed, and the commit is one `updateTextNode` batch.
 *
 * The component around this file owns pointer events, focus and a CanvasKit
 * surface, so — as everywhere on this lane — what could be a function IS one,
 * here, proven against AD2.2's harvested bytes.
 *
 * ── THE SPACES ───────────────────────────────────────────────────────────
 * `scene-gestures.ts` names all three. This file needs two of them: the
 * selection box arrives in SCENE units and the overlay is a DOM sibling of the
 * canvas, so its geometry is STAGE px — the same space the G-A selection
 * outline is stroked in, produced by the same `selectionOutlineForBox`. That
 * is deliberate: the caret must sit exactly where the outline would, at every
 * zoom and every pan, and two derivations could disagree.
 *
 * Font metrics come from the RENDER DESCRIPTOR (descriptor px = canvas px at
 * zoom 1), so they are multiplied by the viewport zoom here — upstream's own
 * `fontSize * zoom`. `lineHeight` is a ratio and is NOT scaled.
 */

/** The label a committed session writes under — the lane's convention is that
 * the intent names the SURFACE the edit came from. */
export const SCENE_TEXT_EDIT_INTENT = "canvas: text edit";

/**
 * Upstream's own floor (`TextEditOverlay.tsx`: `Math.max(8, …)`). A text node
 * the solver gave no width or height is still editable — the caret needs
 * somewhere to stand — so the overlay never collapses to nothing.
 */
export const MIN_TEXT_EDIT_SIZE_PX = 8;

/**
 * What a double-click resolves to.
 *
 * `edit` also SELECTS the node (upstream selects and opens in one step): a
 * caret in a node the inspector is not showing would be two disagreeing
 * surfaces.
 */
export type SceneDoubleClickEffect =
  | { kind: "edit"; nodeId: NodeId }
  | { kind: "select"; nodeId: NodeId }
  | { kind: "none" };

/**
 * The double-click decision: open a caret session, drill out to a container,
 * or do nothing.
 *
 * Upstream's order exactly (`CanvasKitCanvas.tsx:800-832`): a TEXT hit opens
 * the session; anything else — including a click on empty workspace — drills
 * the selection out to its top-level container, which is how a container whose
 * background is fully covered by its children is reachable at all.
 *
 * Two refusals are the platform's, and both are the standing constraints
 * rather than new policy:
 *
 *  • **LOCKED** — §1.0/§4's "lock gates every write path". The write side
 *    (`scene-apply.ts`) refuses a locked node anyway, so opening a caret over
 *    one would be a session that can only end in a silent no-op.
 *  • **`gestureDisabled`** — Gate G-H: while an agent turn is in flight the
 *    human's direct manipulation is off. Only OPENING is gated; a session
 *    already open is not force-killed by a turn start (D10 CAS is the net),
 *    the same posture an in-flight gesture takes.
 *
 * Neither refusal falls through to the drill-out: the pointer-down that
 * preceded this double-click already selected the node, so there is nothing
 * left to say.
 *
 * Ruling C-9's freeze-on-grab deliberately does NOT fire here. A layout-managed
 * text node opens a session like any other: a content edit re-solves the
 * layout, which is the solver doing its job, not a refusal to work around.
 */
export function sceneDoubleClickEffect({
  gestureDisabled,
  nodeId,
  scene,
  selectedNodeId,
}: {
  gestureDisabled: boolean;
  /** The representable hit (§5's nearest schema-bearing node), or null for a
   * double-click that landed on nothing. */
  nodeId: NodeId | null;
  scene: Scene | null;
  selectedNodeId: NodeId | null;
}): SceneDoubleClickEffect {
  if (!scene) {
    return { kind: "none" };
  }
  const node = getNode(scene, nodeId);
  if (node?.kind.kind === "text") {
    if (gestureDisabled || node.locked) {
      return { kind: "none" };
    }
    return { kind: "edit", nodeId: node.id };
  }
  const from = selectedNodeId ?? nodeId;
  const top = topLevelAncestorId(scene, from);
  if (!top || top === from) {
    // Already at the top of its chain (or nothing to drill from): upstream
    // re-selects what is already selected, which changes nothing.
    return { kind: "none" };
  }
  return { kind: "select", nodeId: top };
}

/**
 * A committed draft as operations, or null when nothing may be written.
 *
 * ONE `updateTextNode` — so a whole editing session, however long, is one
 * atomic batch and therefore ONE undo frame (the same contract a canvas
 * gesture keeps, Ruling C-3).
 *
 * Null in every honest no-write case, and each is a real path:
 *
 *  • the draft equals the stored content — a blur that typed nothing is not an
 *    edit, and the session closes silently;
 *  • the node is LOCKED or not text — the write side would refuse it anyway;
 *  • the node is GONE — a D10 reload or an agent turn replaced the scene under
 *    the open session; the draft is discarded rather than written to whatever
 *    now holds that id.
 *
 * The EMPTY string is a legal commit: a text node that says nothing is a real
 * edit and a node that survives (rung A's `case "content"` takes the same
 * position). D4, stated so it is not rediscovered: the engine clears a spanned
 * node's spans when the content changes and byte-identical spans arrive, so a
 * session commit today drops any range styling — honest and undoable; rung C
 * sends a remapped spans vector alongside.
 */
export function textEditCommitOperations(
  node: Node | null,
  draft: string,
): Operation[] | null {
  if (!node || node.kind.kind !== "text" || node.locked) {
    return null;
  }
  if (draft === node.kind.content) {
    return null;
  }
  return [updateTextNode(node, { content: draft })];
}

/** The DOM edit surface's style, in the units CSS takes. */
export interface SceneTextEditStyle {
  color: string;
  fontFamily: string;
  /** Stage px (descriptor px × zoom). */
  fontSize: number;
  fontStyle: "italic" | "normal";
  fontWeight: number;
  /** Stage px, same reason as `fontSize`. */
  letterSpacing: number;
  /** A RATIO, so it is never scaled by the zoom. */
  lineHeight: number;
  textAlign: "left" | "center" | "right" | "justify";
  /** A7a: consumed as a computed `paddingTop` by the overlay, which needs the
   * live content height only a DOM measurement can give. */
  valign: "top" | "center" | "bottom";
}

/** Everything the DOM edit surface is drawn from, in STAGE px. */
export interface SceneTextEditModel {
  nodeId: NodeId;
  /** The STORED content — `text_transform` applies to painted glyphs only, so
   * the caret edits the raw string (upstream parity). */
  content: string;
  height: number;
  left: number;
  /** Degrees, about the box origin — the same pivot the draw loop and the G-A
   * outline rotate about. */
  rotation: number;
  style: SceneTextEditStyle;
  top: number;
  width: number;
}

/**
 * The open session's overlay model, or null when there is no session to draw.
 *
 * The box is not re-derived: `deriveSelectionChromeModel` is the engine's own
 * selection-chrome oracle and `selectionOutlineForBox` is G-A's own stage-px
 * conversion, so the caret's box and the outline's box are one derivation.
 *
 * Null — no overlay element at all — in every honest empty case: no session, a
 * node the scene no longer carries (a D10 reload or an agent turn landing
 * mid-session), a node that is no longer text, and a node with **no computed
 * geometry**, where a box guessed from `transform` would put the caret
 * somewhere the text is not. The host reads that null as "the session closed".
 */
export function sceneTextEditModel({
  artboard,
  editingNodeId,
  pageId,
  scene,
  viewport,
}: {
  artboard: SceneArtboardModel | null;
  editingNodeId: NodeId | null;
  pageId: PageId | null;
  scene: Scene | null;
  viewport: WorkspaceViewport;
}): SceneTextEditModel | null {
  if (!scene || !artboard || !editingNodeId) {
    return null;
  }
  const node = getNode(scene, editingNodeId);
  const page = pageId ? scene.pages[pageId] : null;
  if (!node || node.kind.kind !== "text" || !page) {
    return null;
  }
  const { selectionBox } = deriveSelectionChromeModel(scene, {
    activePageId: pageId,
    selectedNodeId: editingNodeId,
  });
  if (!selectionBox) {
    return null;
  }
  const outline = selectionOutlineForBox({
    artboard,
    box: selectionBox.box,
    nodeId: editingNodeId,
    rotation: selectionBox.rotation,
    viewport,
  });
  if (!outline) {
    return null;
  }
  // The descriptor is the ONE place font tokens, style tokens and paint are
  // resolved, so the overlay reads what the painter reads. Only its text
  // payload and fill are used — the geometry above is the chrome oracle's.
  const descriptor = nodeDescriptor(
    scene,
    node,
    page,
    parentComputedOrigin(scene, editingNodeId),
  );
  const text = descriptor.text;
  if (!text) {
    return null;
  }
  const scale =
    Number.isFinite(viewport.zoom) && viewport.zoom > 0 ? viewport.zoom : 1;
  return {
    nodeId: editingNodeId,
    content: text.content,
    height: Math.max(MIN_TEXT_EDIT_SIZE_PX, outline.height),
    left: outline.x,
    rotation: outline.rotation,
    style: {
      color: descriptor.fill,
      fontFamily: text.fontFamily,
      fontSize: text.fontSize * scale,
      fontStyle: text.italic ? "italic" : "normal",
      fontWeight: text.fontWeight,
      letterSpacing: text.letterSpacing * scale,
      lineHeight: text.lineHeight,
      textAlign: text.align,
      valign: text.valign,
    },
    top: outline.y,
    width: Math.max(MIN_TEXT_EDIT_SIZE_PX, outline.width),
  };
}
