import type {
  Node,
  NodeId,
  Operation,
  PageId,
  Scene,
  TextNode,
  TextSpan,
} from "../engine/scene/contracts";
import { updateTextNode } from "../engine/scene/operations";
import { nodeDescriptor } from "../engine/scene/renderAdapter";
import { getNode, parentComputedOrigin } from "../engine/scene/sceneQueries";
import {
  normalizeSpans,
  spanValidationIssues,
  spansStableKey,
  spansVectorForContentEdit,
} from "../engine/scene/textSpans";
import { deriveSelectionChromeModel } from "../engine/scene/selectionChrome";
import type { WorkspaceViewport } from "../engine/scene/workspaceViewport";
import {
  selectionOutlineForBox,
  type SceneArtboardModel,
} from "./scene-canvas-view";
import { representableHit } from "./scene-selection";
import {
  selectionClickTarget,
  selectionDrillDown,
} from "./scene-selection-ladder";

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
 * Rung C: the label a RANGE-STYLING action writes under. A separate intent from
 * the session's own commit because it is a separate edit with a separate cause
 * — founder-visible item 5: each formatting action is its own undo frame, and
 * the history should be able to say which is which.
 */
export const SCENE_TEXT_STYLE_INTENT = "canvas: text style";

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
  /**
   * Task 4 (scene live-streaming rung A): a caret this document would happily
   * have opened, refused because a design turn is running on it.
   *
   * Its own kind rather than `none` so the host can SAY so. `none` is "nothing
   * to do here" — a double-click on empty workspace, a node already at the top
   * of its chain — and a refusal that renders as nothing-to-do is exactly the
   * silence the founder's lock exists to replace.
   */
  | { kind: "locked" }
  | { kind: "none" };

/**
 * The double-click decision: drill one level toward the pointer, open a caret
 * session, or do nothing.
 *
 * ── R2, THE DRILL (selection model v2, founder rulings 2026-09-04) ────────
 * This SUPERSEDES Rung B's drill-OUT. Upstream (`CanvasKitCanvas.tsx:800-832`)
 * opened a session on a text hit and otherwise drilled the selection OUT to its
 * top-level container — the only way a container fully covered by its children
 * was reachable at all. Plan 3 then added a button shortcut (a double-click on
 * a button opened the caret on its label). Both are gone: R1 now selects the
 * outermost UNIT on the click itself, so the container is reachable without
 * this function, and what a double-click owes the user is the opposite motion —
 * a way IN.
 *
 * So the order is: with the selection a proper ancestor of the pointer's
 * deepest hit, select the next representable level down (`selectionDrillDown`);
 * with the selection already that deepest node and text, open the caret; and
 * with the selection somewhere else entirely, re-sync to R1's click target
 * (the pointer-down that preceded this double-click normally makes that a
 * no-op). A double-click therefore walks a group → its member → the caret, one
 * click-pair per level, and never has to guess at a level it skipped.
 *
 * Two refusals are the platform's, and both are the standing constraints
 * rather than new policy:
 *
 *  • **LOCKED** — §1.0/§4's "lock gates every write path". The write side
 *    (`scene-apply.ts`) refuses a locked node anyway, so opening a caret over
 *    one would be a session that can only end in a silent no-op.
 *  • **`gestureDisabled`** — Gate G-H, now the founder's agent-run lock (task 4):
 *    while a design turn is running on this document the human's direct
 *    manipulation is off. It answers `locked` rather than `none`, so the host
 *    can put the lock's own sentence in front of the user instead of leaving a
 *    caret that mysteriously never appears.
 *
 *    Only OPENING is gated here. A session already open is not killed by this
 *    function — but it is no longer merely left to the D10 CAS net either: the
 *    founder default is that the lock ENGAGING force-COMMITS an open session
 *    first (`engageSceneWriteLock` in `hooks/use-scene-manual-edits.ts`), so
 *    typed work lands rather than being stranded behind a closed gate.
 *
 * Neither refusal falls through to anything else: the drill above has already
 * had its say, and the pointer-down that preceded this double-click already
 * selected the node, so a refused caret leaves nothing left to do.
 *
 * ── C-9, TRUTHFULLY (F5, review 2026-08-24) ──────────────────────────────
 * This docstring used to claim the C-9 freeze "does NOT fire" for a text-edit
 * press. That was false, and the correction is a correction of the PROSE only:
 * a double-click's first pointer-down runs `freezeLayoutForPress` like any
 * press on a freezable node, so opening a caret on a layout-managed text node
 * has already baked the document's layout to free placement — exactly as a
 * plain selection click on that node does, which is ratified AD4.C-3 /
 * ruling C-10 behaviour and NOT this lane's to change. What is true is that the
 * text session itself adds NO freeze of its own: it opens on the post-press
 * scene and its commit is an ordinary content/spans write, so a managed node
 * re-solves around the new content like the solver is meant to.
 *
 * Whether the freeze should wait for a drag threshold — so that pure clicks and
 * double-clicks stop freezing at all — is a live founder question recorded on
 * the plan, not a defect of this function.
 */
export function sceneDoubleClickEffect({
  gestureDisabled,
  stack,
  pageId,
  scene,
  selectedNodeId,
}: {
  gestureDisabled: boolean;
  /** The engine's hit stack under the double-click, outer→inner; empty for a
   * double-click that landed on nothing. */
  stack: NodeId[];
  pageId: PageId | null;
  scene: Scene | null;
  selectedNodeId: NodeId | null;
}): SceneDoubleClickEffect {
  if (!scene) {
    return { kind: "none" };
  }
  const deepest = representableHit(stack, scene, pageId);
  if (deepest === null) {
    return { kind: "none" };
  }
  // R2, first: one level toward the pointer. Selection is never a write, so a
  // locked node and a locked run both still drill — only the caret below is
  // gated.
  const drill = selectionDrillDown({ stack, scene, pageId, selectedNodeId });
  if (drill !== null) {
    return { kind: "select", nodeId: drill };
  }
  const selected = getNode(scene, selectedNodeId);
  if (selected && selected.id === deepest && selected.kind.kind === "text") {
    // The NODE's own lock is asked first and answers `none`: it is a document
    // fact that outlives the run, so "editing unlocks when it finishes" would
    // be a promise this node is not going to keep.
    if (selected.locked) {
      return { kind: "none" };
    }
    if (gestureDisabled) {
      return { kind: "locked" };
    }
    return { kind: "edit", nodeId: selected.id };
  }
  // Neither the hit nor its ancestor is selected (the pointer-down that
  // preceded us normally makes that untrue): re-sync to R1's click target.
  const target = selectionClickTarget(stack, scene, pageId);
  return target !== null && target !== selectedNodeId
    ? { kind: "select", nodeId: target }
    : { kind: "none" };
}

/**
 * A committed session as operations, or null when nothing may be written.
 *
 * ONE `updateTextNode` — so a whole editing session, however long, is one
 * atomic batch and therefore ONE undo frame (the same contract a canvas
 * gesture keeps, Ruling C-3). Rung C adds a second caller with the same
 * shape: one FORMATTING action, committed immediately, is likewise one batch
 * and one undo frame (founder-visible item 5).
 *
 * Null in every honest no-write case, and each is a real path:
 *
 *  • nothing changed — neither the content nor the spans. A blur that typed
 *    nothing is not an edit, and the session closes silently;
 *  • the node is LOCKED or not text — the write side would refuse it anyway;
 *  • the node is GONE — a D10 reload or an agent turn replaced the scene under
 *    the open session; the draft is discarded rather than written to whatever
 *    now holds that id.
 *
 * The EMPTY string is a legal commit: a text node that says nothing is a real
 * edit and a node that survives (rung A's `case "content"` takes the same
 * position). So is an EMPTY spans vector — un-bolding the only bold run leaves
 * a node with no spans, and `spans: []` is how that reaches the engine.
 *
 * ── THE SPANS CHANNEL (rung C) ───────────────────────────────────────────
 * `spans` absent (rung B's two-argument call) means this session authors no
 * spans at all: the write carries content alone, and the engine's D4 rule
 * clears any stored range styling a content change would otherwise strand.
 *
 * `spans` present means the session MAINTAINED a vector across its edits, and
 * both channels ride the one batch. It goes out through
 * `spansVectorForContentEdit` — called LAST, immediately before the write, and
 * never re-normalized afterwards, because its whole job is to produce a vector
 * the engine cannot mistake for a stale carry-forward (D4,
 * `operations.rs:620-631`), and normalizing would merge that deliberate split
 * straight back together.
 *
 * The content rides along whenever the draft is dirty, even for a pure
 * formatting action: span offsets index the string they were computed in, and
 * committing them against a stale stored content would point them at other
 * text.
 */
export function textEditCommitOperations(
  node: Node | null,
  draft: string,
  /** The session's working spans, or absent for a session that authors none. */
  spans?: readonly TextSpan[] | null,
): Operation[] | null {
  if (!node || node.kind.kind !== "text" || node.locked) {
    return null;
  }
  const contentChanged = draft !== node.kind.content;
  if (spans === undefined || spans === null) {
    return contentChanged ? [updateTextNode(node, { content: draft })] : null;
  }
  const stored = node.kind.spans ?? [];
  const vector = spansVectorForContentEdit(node.kind, draft, spans);
  const spansChanged =
    spansStableKey(vector) !==
    spansStableKey(normalizeSpans(node.kind.content, stored));
  if (!contentChanged && !spansChanged) {
    return null;
  }
  const issues = spanValidationIssues(draft, vector);
  if (issues.length > 0) {
    // Unreachable by construction — every `textSpans.ts` exit normalizes onto
    // the five rules — and load-bearing anyway: the engine validates spans at
    // LAYOUT, not at apply, so an invalid vector applies clean and then drops
    // the node out of measurement (LUMV0906) with nothing refused. Loud in
    // dev/test; in production the spans channel is dropped and the content
    // edit still lands, which is the honest degradation.
    if (process.env.NODE_ENV !== "production") {
      throw new Error(
        `refusing to write an invalid spans vector: ${issues.join("; ")}`,
      );
    }
    return contentChanged ? [updateTextNode(node, { content: draft })] : null;
  }
  return [updateTextNode(node, { content: draft, spans: vector })];
}

/**
 * D2 (live walk, 2026-08-24): the CSS `font-family` DECLARATION that actually
 * resolves to a scene family in the DOM.
 *
 * The overlay asked for the scene's family verbatim — `font-family: Inter` —
 * and got a system SERIF, while CanvasKit painted true Inter underneath, so
 * the caret's wrapping visibly disagreed with the canvas it is meant to sit
 * exactly on top of. Nothing registers a DOM face under the bare name "Inter":
 * `app/globals.css` imports `@fontsource-variable/inter`, whose face registers
 * as **"Inter Variable"**, while the scene grammar and CanvasKit's
 * `INTER_FAMILY` both say "Inter". One name for the painter, another for the
 * DOM.
 *
 * So the overlay emits a STACK rather than a name, and its three entries are
 * this repo's three registration paths in trust order:
 *
 *  1. **the declared family** — `libraryFonts.ts` and `kitFonts.ts` both add
 *     their faces to `document.fonts` under `face.family`, the family the
 *     scene itself names, so a kit or library family hits here;
 *  2. **`<family> Variable`** — fontsource-variable's own naming, which is how
 *     the bundled Inter is present in the DOM at all;
 *  3. **`sans-serif`** — the honest floor. A serif fallback is what the defect
 *     LOOKED like; a missing family should at least land in the right species.
 *
 * This is not special-casing one font: `features/projects/config/project-canvas-fonts.ts`
 * already writes the identical `Inter → "Inter Variable", …` mapping by hand
 * for the same reason, which is the corroboration that the naming convention
 * is real rather than a guess. It is deliberately NOT imported — that map is
 * another feature's three-entry dummy-screen constant, not a registry, and the
 * design editor's families come from the scene, not from its keys.
 *
 * Every name is quoted and every quote inside a name is escaped, so a family
 * carrying punctuation cannot break out of the declaration and take the whole
 * rule down with it (which would be a serif again).
 */
export function domFontFamilyStack(family: string): string {
  const declared = family.trim();
  if (declared.length === 0) {
    return "sans-serif";
  }
  const quote = (name: string) =>
    `"${name.replace(/\\/g, "\\\\").replace(/"/g, '\\"')}"`;
  const names = declared.endsWith(" Variable")
    ? [declared]
    : [declared, `${declared} Variable`];
  return [...names.map(quote), "sans-serif"].join(", ");
}

/** The DOM edit surface's style, in the units CSS takes. */
export interface SceneTextEditStyle {
  color: string;
  /** A CSS font-family DECLARATION, not a bare family name — see
   * {@link domFontFamilyStack} for why the DOM needs the stack. */
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
  /** The node's DECLARED family, un-quoted — what the font registry is asked
   * about (`model.style.fontFamily` is the DOM stack, which it cannot answer
   * for). Plan 1 item B: the toolbar names it in the no-face reason. */
  family: string;
  /** The STORED content — `text_transform` applies to painted glyphs only, so
   * the caret edits the raw string (upstream parity). */
  content: string;
  height: number;
  left: number;
  /** Degrees, about the box origin — the same pivot the draw loop and the G-A
   * outline rotate about. */
  rotation: number;
  style: SceneTextEditStyle;
  /**
   * Rung C: the node's STORED text kind, carried whole.
   *
   * The range toolbar cannot work from the string alone — `formatStateForRange`
   * and `applyStyleToRange` resolve override semantics against the node's own
   * base (a span whose weight equals the node's is no override at all), and the
   * session seeds its working vector from `text.spans`. Carrying the kind here
   * keeps the overlay reading ONE derivation of the session's subject, the same
   * way its geometry comes from one box model.
   */
  text: TextNode;
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
    family: text.fontFamily,
    style: {
      color: descriptor.fill,
      fontFamily: domFontFamilyStack(text.fontFamily),
      fontSize: text.fontSize * scale,
      fontStyle: text.italic ? "italic" : "normal",
      fontWeight: text.fontWeight,
      letterSpacing: text.letterSpacing * scale,
      lineHeight: text.lineHeight,
      textAlign: text.align,
      valign: text.valign,
    },
    text: node.kind,
    top: outline.y,
    width: Math.max(MIN_TEXT_EDIT_SIZE_PX, outline.width),
  };
}
