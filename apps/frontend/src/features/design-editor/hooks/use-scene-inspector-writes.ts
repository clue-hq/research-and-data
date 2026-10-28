"use client";

import { artifactHistoryKey } from "../adapter/history-keys";
import { useEffect, useRef, type RefObject } from "react";
import {
  sceneCanvasChangeToOperation,
  sceneChangeToOperation,
} from "../adapter/scene-apply";
import { freezeOperationsToPersist } from "../adapter/scene-gestures";
import { rootFrameId } from "../adapter/scene-hydrate";
import type { ScenePalette } from "../adapter/scene-palette";
import { panelWriteIntent } from "../adapter/scene-panel-freeze";
import type { SceneCanvasControls } from "../components/scene-artifact-canvas";
import type { Node, Operation, PageId, Scene } from "../engine/scene/contracts";
import { getPage } from "../engine/scene/sceneQueries";
import type { KitTokenMaps } from "../engine/scene/tokenColors";
import { freezeLayoutEdit } from "../engine/scene/structuredEdits";
import {
  useSceneManualEdits,
  type SceneManualEdits,
} from "./use-scene-manual-edits";

/**
 * AD3.2: the ad lane's write wiring — the structural twin of the website
 * lane's `use-inspector-writes.ts`. It listens to the inspector's
 * `clue:inspector-property-change` events, maps each ADDRESSABLE change
 * through the pure AD3.1 `sceneChangeToOperation` adapter, and hands the
 * operation to the manual-edits controller (optimistic apply → persist).
 *
 * AD3.3 adds the second pair of listeners this file's twin also owns — the
 * action menu's Undo/Redo requests and the ⌘Z/⇧⌘Z shortcuts — at the foot of
 * the file.
 *
 * ── THE ADDRESSING RULING (AD3.2) ────────────────────────────────────────
 * The web lane's gate demands `typeof detail.documentVersion === "number"`,
 * because its write sends that number as `base_version`. **The ad lane does not
 * send one**: the edit queue owns `base_version` internally — it fetches and
 * tracks it (`editQueue.ts:110-113,152`) — so a copy on the event would be a
 * second, staler source of the same fact.
 *
 * (AD3.3 CORRECTION: this paragraph used to give a second reason — that
 * `documentStore.fetchDocument` "does not parse `current_version`". It does
 * now: AD3.3 added that parse alongside the undo/redo stack depths the history
 * controls need. The ruling is unchanged, because it never depended on that —
 * the queue still owns the version, the scene still carries none, and the gate
 * below still asserts something strictly stronger.)
 *
 * So this gate asserts what the ad lane actually HAS, which is strictly
 * stronger evidence than a version integer:
 *
 *   • `detail.property` is a string,
 *   • `detail.selectionId` is a string AND is the session's current primary
 *     selection (an event addressed to anything else is not this user's),
 *   • the live scene for the ACTIVE document really contains a node with that
 *     id (so the write can never be aimed at a node that is not there),
 *   • the write path is armed: an active document, a live scene, and mounted
 *     canvas controls.
 *
 * `addressing.documentVersion` therefore stays `null` on this lane — see the
 * comment at its construction site.
 *
 * ── AD4.0: THE SECOND GATE, FOR §1.1's CANVAS ROWS ───────────────────────
 * The gate above requires a NON-NULL primary selection, so the §1.1 canvas
 * schema — an EMPTY selection editing the PAGE — could never write through it.
 * AD3.2 said the lane that added those rows "must widen this gate deliberately,
 * not discover it by accident". This is that widening; `canvasWriteTarget`
 * below IS the gate, exported so it can be tested as the pure decision it is.
 *
 * A canvas event states something positive rather than merely missing:
 *
 *   • `detail.selectionType` is `"canvas"` — the schema that raised it says so
 *     itself (`image-inspector.tsx`'s `AdCanvasInspector` stamps it, and every
 *     controller puts it on the wire, `use-inspector-controller.ts:196-213`).
 *     This is the fact stated directly rather than inferred from an absence.
 *   • `detail.artifactId` is this session's ACTIVE artifact — the event comes
 *     from a panel wired to the document this hook is armed for, not from one
 *     still mounted for the tab the user just left.
 *   • `detail.selectionId` IS this session's primary selection — the same
 *     assertion the node path makes, and the thing that keeps the two lanes'
 *     listeners apart on one window. An event carrying no addressing at all
 *     (the dummy fixture path, `dispatchInspectorEvent` with no third
 *     argument) leaves it `undefined`, which is never equal to a session's
 *     `string | null`, so it is refused here and again by the node path.
 *   • that selection is one the canvas schema can legitimately be showing:
 *     `null`, or the page's ROOT FRAME.
 *   • the live scene really carries the page the write will name — the same
 *     "the write can never be aimed at something that is not there" rule the
 *     node path applies to its node.
 *
 * ── AD4.0 step 2: WHY THE ROOT FRAME IS THE SECOND ENTRY STATE ───────────
 * The step-1 gate keyed on `selectionId === null` alone, which is only ONE of
 * the two ways the canvas schema reaches the screen. `sceneSelectionFor`
 * routes the page's root frame to the CANVAS schema (`scene-hydrate.ts`; AD2.5
 * proves it — "a hit on the root frame alone resolves to it (the canvas
 * selection)"), so clicking the artboard background, or the "Ad artboard" row
 * in Layers, renders the very same panel with `selectionId = <root frame id>`.
 * Every §1.1 row was then routed to the NODE adapter, which maps none of them:
 * browser-proven at review — picking a size preset with the artboard selected
 * left the document at 1200x1200 while the select displayed the new size, a
 * panel actively stating a size the document never got.
 *
 * Root frame ⇒ canvas schema is EXACTLY-ONE-WAY: `sceneSelectionFor` returns
 * `"canvas"` for the root frame and for nothing else (every other frame gets
 * the auto-layout schema, and no other kind can match), so a node id that is
 * not the root frame never legitimately carries `selectionType: "canvas"` and
 * is refused here.
 *
 * A canvas event that this gate accepts is therefore ANSWERED HERE and nowhere
 * else: mapped or refused, the listener returns. It briefly fell through to
 * the node path instead, on the theory that §1.0's lock could arrive stamped
 * `"canvas"` — it cannot. `InspectorHeader` renders the lock button only
 * inside `elementActions` (`inspector-primitives.tsx`), and
 * `image-inspector.tsx` passes `elementActions={selection !== "canvas" && …}`,
 * so NEITHER entry state renders a lock at all. The fall-through protected
 * nothing and cost something real: a refused canvas event retried against
 * `sceneChangeToOperation` with the ROOT FRAME as its node, where
 * `strokeColor`, `strokeWidth`, `position.x/y` and `rotation` are mapped with
 * no kind guard — so a future canvas row that happened to reuse one of those
 * names would have written the artboard after the canvas adapter deliberately
 * refused it. (§1.0's lock row consequently has NO surface on the canvas
 * schema: the artboard cannot be locked or unlocked from the panel. That is
 * the dummy's own composition and is recorded as a founder-facing gap, not
 * worked around here.)
 *
 * What keeps the two LANES apart here is not the artifact id (the web session
 * is handed the same `activeArtifactId`) but the same thing that keeps the
 * undo/redo listeners apart: exactly one lane is `enabled`, so exactly one has
 * a `documentId` and this effect is only armed for the ad one — and the web
 * inspector is not even mounted while an ad artifact is active.
 *
 * The page id is the SESSION's (`firstPageId`, resolved by the canvas that
 * rendered it), not a re-derivation here: `Scene.pages` is an unordered
 * `Record` with no ordering field, so `Object.keys(...)[0]` would be a guess —
 * and it must be the very page `hydrateSceneCanvasState` read, or the write
 * would not be the inverse of what the panel is showing.
 */

/** What the §1.1 canvas rows need to write: the live scene, the page they
 * name, and the selection the event was raised under (`null` for the empty
 * selection, the root frame's id when the artboard itself is selected). */
export interface SceneCanvasWriteTarget {
  pageId: PageId;
  scene: Scene;
  selectionId: string | null;
}

/**
 * AD4.0 step 2: the canvas gate as a pure decision — `null` when this event is
 * not a §1.1 canvas write for this session. The reasoning is the header block
 * above; this function is where it is enforced, and the only reason it is
 * exported is that a `useEffect` listener cannot be tested without a DOM while
 * a pure function can (the `createReplaceImageHandler` precedent).
 */
export function canvasWriteTarget(
  detail: {
    artifactId?: unknown;
    selectionId?: unknown;
    selectionType?: unknown;
  },
  session: {
    artifactId: string | null;
    pageId: PageId | null;
    primaryNodeId: string | null;
    scene: Scene | null;
  },
): SceneCanvasWriteTarget | null {
  // The raising schema names itself — no inference from an absence.
  if (detail.selectionType !== "canvas") {
    return null;
  }
  if (
    typeof detail.artifactId !== "string" ||
    detail.artifactId !== session.artifactId
  ) {
    return null;
  }
  // The event's selection IS the session's. `===` against a `string | null`
  // covers both entry states at once and still refuses an unaddressed event
  // (`undefined`), which is what step 1's `selectionId === null` was for.
  const selectionId = session.primaryNodeId;
  if (detail.selectionId !== selectionId) {
    return null;
  }
  const { pageId, scene } = session;
  // The scene the engine is holding must really carry that page.
  if (!scene || !pageId || !getPage(scene, pageId)) {
    return null;
  }
  // Empty selection, or the artboard itself. Any other node carrying
  // `selectionType: "canvas"` (the §5 fallback schema, a stale panel) is not a
  // canvas write — the panel would be showing that NODE's values while this
  // wrote the page.
  if (selectionId !== null && selectionId !== rootFrameId(scene, pageId)) {
    return null;
  }
  return { pageId, scene, selectionId };
}

/**
 * AD4.E (§1.9 / §1.12): the action-menu request decision as a pure function —
 * which history step, if any, a `clue:artifact-action-request` detail asks this
 * lane to take. Exported for the reason `canvasWriteTarget` above is: a
 * `useEffect` listener cannot be exercised without a DOM, a pure function can.
 *
 * Two refusals, both deliberate. The KIND guard keeps the two lanes' listeners
 * apart on one window — the header stamps the active artifact's kind onto every
 * request (`use-artifact-action-menu-controller.ts:42-52`), so a web artifact's
 * Undo can never reach the ad document. The ACTION guard keeps §7's rows
 * (Duplicate / Archive / Delete, which share the same dispatch and are not yet
 * backed) out of document history.
 */
export function adActionRequest(detail: unknown): "undo" | "redo" | null {
  if (typeof detail !== "object" || detail === null) return null;
  const { action, kind } = detail as { action?: unknown; kind?: unknown };
  if (kind !== "ad") return null;
  if (action === "undo" || action === "redo") return action;
  return null;
}

export function useSceneInspectorWrites({
  artifactId,
  canvasControls,
  documentId,
  loadGeneration,
  lockNote,
  locked,
  onReload,
  onScreen = true,
  pageId,
  palette,
  tokenMaps,
  primaryNodeId,
  redoDepth,
  scene,
  undoDepth,
}: {
  /** AD4.0: the session's active artifact tab — the id its inspector stamps on
   * every event as `addressing.artifactId`. The canvas gate below compares
   * against it; the node gate has the selection id instead. */
  artifactId: string | null;
  /** The mounted canvas's imperative seam (the live engine). */
  canvasControls: RefObject<SceneCanvasControls | null>;
  /** The active design document, or null when nothing is armed. */
  documentId: string | null;
  /** AD3.3: the loaded document's history, mirrored up by the canvas — the
   * base the controller's step count is added to. */
  loadGeneration?: number;
  /** Task 4: the copy a lock refusal shows, or null when there is none. */
  lockNote?: string | null;
  /** Task 4: a design turn is running on this document — the lane is view-only.
   * Passed straight through; the whole policy lives in the write controller. */
  locked?: boolean;
  /** The session's reload nonce bump. */
  onReload: () => void;
  /** The artifact is on screen: undo/redo keys act only then (review finding S2b-6). */
  onScreen?: boolean;
  /** AD4.0: the page the canvas is rendering (§5: one artboard), the very one
   * `hydrateSceneCanvasState` read. */
  pageId: PageId | null;
  /** AD4.0 step 3 (§1.6): the document's brand vocabulary — what a token row's
   * picked LABEL is validated against. `null` (no kit, a fetch that failed, a
   * kit still in flight) means no token write can be validated, so none
   * happens; the hex rows are untouched by it. */
  palette: ScenePalette | null;
  tokenMaps?: KitTokenMaps | null;
  /** The session's primary selection — `selectedIds[0]`, already resolved
   * against the live scene. */
  primaryNodeId: string | null;
  redoDepth?: number;
  /** The live scene the canvas mirrored up (the very one the engine holds). */
  scene: Scene | null;
  undoDepth?: number;
}): SceneManualEdits {
  const edits = useSceneManualEdits({
    controlsRef: canvasControls,
    documentId,
    loadGeneration,
    lockNote,
    locked,
    onReload,
    redoDepth,
    undoDepth,
  });

  // Latest-value refs so the one listener reads current state without
  // re-arming (written passively, per this repo's react-hooks rules).
  const applyOpsRef = useRef(edits.applyOps);
  const canApplyRef = useRef(edits.canApply);
  const reportNoteRef = useRef(edits.reportNote);
  const artifactIdRef = useRef(artifactId);
  const controlsRef = useRef(canvasControls);
  const pageIdRef = useRef(pageId);
  const paletteRef = useRef(palette);
  const tokenMapsRef = useRef(tokenMaps);
  // C-9 panel parity: the persist-ONLY seam, for the freeze the panel fires.
  // It is `applyOps` minus the apply, because `applyStructuredEdit` has already
  // applied the freeze to the engine — routing its batch through `applyOps`
  // would apply it twice.
  const persistAppliedOpsRef = useRef(edits.persistAppliedOps);
  const primaryNodeIdRef = useRef(primaryNodeId);
  const sceneRef = useRef(scene);
  useEffect(() => {
    applyOpsRef.current = edits.applyOps;
    canApplyRef.current = edits.canApply;
    reportNoteRef.current = edits.reportNote;
    artifactIdRef.current = artifactId;
    controlsRef.current = canvasControls;
    pageIdRef.current = pageId;
    paletteRef.current = palette;
    tokenMapsRef.current = tokenMaps;
    persistAppliedOpsRef.current = edits.persistAppliedOps;
    primaryNodeIdRef.current = primaryNodeId;
    sceneRef.current = scene;
  });

  useEffect(() => {
    if (!documentId) return;
    const onChange = (event: Event) => {
      const detail = (event as CustomEvent).detail as {
        artifactId?: unknown;
        documentVersion?: unknown;
        property?: unknown;
        selectionId?: unknown;
        selectionType?: unknown;
        value?: unknown;
      } | null;
      if (!detail || typeof detail.property !== "string") return;

      // ── AD4.0 / §1.1: the CANVAS (page + root frame) rows ──────────────
      // The gate is `canvasWriteTarget`, reasoned out in the header above; it
      // accepts BOTH entry states (empty selection, artboard selected).
      const canvas = canvasWriteTarget(detail, {
        artifactId: artifactIdRef.current,
        pageId: pageIdRef.current,
        primaryNodeId: primaryNodeIdRef.current,
        scene: sceneRef.current,
      });
      if (canvas) {
        if (!controlsRef.current.current) return;
        const canvasOperation = sceneCanvasChangeToOperation(
          {
            property: detail.property,
            selectionId: canvas.selectionId,
            value: detail.value,
          },
          canvas.scene,
          canvas.pageId,
          paletteRef.current,
        );
        // The same null contract: an unmapped property or an unparseable value
        // produces no operation, and no operation is no write.
        if (!canvasOperation) return;
        applyOpsRef.current([canvasOperation], `inspector: ${detail.property}`);
        return;
      }

      // ── AD3.1/AD3.2: the node-addressed rows, unchanged ────────────────
      // Not addressable → not a write (the W3.1 null contract, ad-side).
      if (typeof detail.selectionId !== "string") return;
      // The event must be for the node this session actually holds. This is
      // also what keeps the two lanes' listeners apart on one window: a web
      // event's selectionId is a web node id, which is never the ad session's
      // primary selection.
      if (primaryNodeIdRef.current !== detail.selectionId) return;
      const live = controlsRef.current.current?.sceneSnapshot() ?? sceneRef.current;
      if (!live) return;
      // The scene the engine is holding must really carry that node — the
      // adapter needs the Node itself, and a miss means the selection and the
      // scene disagree (a reload mid-edit), which is never a write.
      const node = live.nodes[detail.selectionId];
      if (!node) return;
      // Armed: a mounted canvas to apply through. (`applyOps` re-checks both
      // this and the document id — it is the one write path and cannot depend
      // on a caller having gated first.)
      const controls = controlsRef.current.current;
      if (!controls) return;

      // ── C-9 (founder): the PANEL's half of freeze-on-grab ────────────────
      // A human editing a node is never refused by auto-layout. Lane C gave
      // the canvas that physics; this gives it to a geometry row typed in the
      // panel. `panelWriteIntent` is the whole decision (and asks the CANVAS's
      // own `isNodeFreezableOnGesture`, never a second opinion); the sequence
      // below is the canvas host's `freezeLayoutForPress`, mirrored exactly.
      //
      // DISCLOSED BEHAVIOUR CHANGE, by the founder's own words for this slice:
      // Width/Height on a managed child are not refused today (Ruling L12) —
      // they write, and the solver re-flows the siblings. After this, the
      // freeze lands first and nothing but the edited node moves.
      //
      // `"refuse"` (a geometry row on a LOCKED node) deliberately falls
      // through to the ordinary path rather than returning here: that path
      // already refuses it at `scene-apply.ts:667` and stays the single
      // authority on what writes. The only thing this branch changes is
      // whether a freeze fires first.
      // The VALUE is part of the decision: a freeze is a document-wide write
      // (every unlocked Stack → Free), persisted and undoable, so it may not
      // fire for a commit `sceneChangeToOperation` is about to answer with
      // `null` — a typo in X, or a Width below the adapter's floor of 1, would
      // otherwise convert the whole document and burn an undo step with no
      // write, no motion and no message.
      const intent = panelWriteIntent(
        live,
        detail.selectionId,
        detail.property,
        detail.value,
      );
      let writeNode: Node = node;
      let writeScene: Scene = live;
      if (intent === "freeze-then-write") {
        const outcome = controls.applyStructuredEdit(freezeLayoutEdit());
        const frozen = freezeOperationsToPersist(outcome);
        if (outcome && frozen.length > 0) {
          // Persist WITHOUT re-applying, and seed the queue's divergence check
          // from `outcome.scene` — the POST-freeze scene the engine returned,
          // never `sceneRef.current`, which is still the pre-freeze one inside
          // this same tick (the ref is written in a PASSIVE effect, so React
          // has not re-rendered yet). Persisted whether or not THIS node was
          // freed: the operations are already in the engine, and whatever they
          // freed must reach the server or the two diverge on the next drain.
          persistAppliedOpsRef.current(frozen, outcome.scene);
        }
        const post = outcome?.scene ?? null;
        // Ask the NODE on the post-freeze scene, never the size of the batch
        // (`build_freeze_layout` skips LOCKED containers while still freeing
        // every other Stack, so a non-empty batch does not mean this node was
        // freed — the c81cd209 rule). A node still solver-owned here is the
        // locked-container case: refuse honestly rather than write nothing.
        if (!post) return;
        const freed = panelWriteIntent(
          post,
          detail.selectionId,
          detail.property,
          detail.value,
        );
        if (freed !== "write") return;
        const frozenNode = post.nodes[detail.selectionId];
        if (!frozenNode) return;
        // The operation MUST be rebuilt from the post-freeze node: the freeze
        // BAKES each managed child's transform to its solved parent-relative
        // offset (`editing.rs:1888-1938`), and both `positionOperation` and the
        // rotation arm spread `node.transform`. Rebuilding from the pre-freeze
        // node — whose stored transform is (0,0) on the harvested ad while its
        // true offset is ~(708,77) — would teleport the untouched axis.
        writeNode = frozenNode;
        writeScene = post;
      }

      const effectiveNode = controls.presentationSnapshot?.()?.nodes[writeNode.id] ?? null;
      const operation = sceneChangeToOperation(
        {
          property: detail.property,
          selectionId: detail.selectionId,
          value: detail.value,
        },
        writeNode,
        writeScene,
        paletteRef.current,
        tokenMapsRef.current,
        effectiveNode,
      );
      // The AD3.1 null contract: an unmapped property, an unparseable value or
      // a locked node produces no operation, and no operation is no write.
      if (!operation) {
        if (detail.property.startsWith("padding.") && writeNode.layout?.padding_token && !effectiveNode?.layout) {
          reportNoteRef.current("Padding is bound to an unavailable Brand Kit value. Restore the exact kit or reload before editing one side.");
        }
        return;
      }
      applyOpsRef.current([operation], `inspector: ${detail.property}`);
    };

    // The colour square's live preview (founder 2026-10-29): the operation a write
    // would build, applied to the canvas ENGINE only and never queued for saving — the
    // picker sends the real write once, when the drag ends. Anything a write would
    // refuse (the agent lock, a locked node), anything that needs the panel's
    // freeze-on-grab, or anything that maps to no operation is simply not shown.
    const onPreview = (event: Event) => {
      const detail = (event as CustomEvent).detail as {
        artifactId?: unknown;
        documentVersion?: unknown;
        property?: unknown;
        selectionId?: unknown;
        selectionType?: unknown;
        value?: unknown;
      } | null;
      if (!detail || typeof detail.property !== "string") return;
      const controls = controlsRef.current.current;
      if (!controls || !canApplyRef.current()) return;
      const canvas = canvasWriteTarget(detail, {
        artifactId: artifactIdRef.current,
        pageId: pageIdRef.current,
        primaryNodeId: primaryNodeIdRef.current,
        scene: sceneRef.current,
      });
      let operation: Operation | null = null;
      if (canvas) {
        operation = sceneCanvasChangeToOperation(
          { property: detail.property, selectionId: canvas.selectionId, value: detail.value },
          canvas.scene,
          canvas.pageId,
          paletteRef.current,
        );
      } else {
        if (typeof detail.selectionId !== "string") return;
        if (primaryNodeIdRef.current !== detail.selectionId) return;
        const live = controls.sceneSnapshot() ?? sceneRef.current;
        const node = live?.nodes[detail.selectionId];
        if (!live || !node) return;
        if (panelWriteIntent(live, detail.selectionId, detail.property, detail.value) !== "write") return;
        operation = sceneChangeToOperation(
          { property: detail.property, selectionId: detail.selectionId, value: detail.value },
          node,
          live,
          paletteRef.current,
          tokenMapsRef.current,
          controls.presentationSnapshot?.()?.nodes[node.id] ?? null,
        );
      }
      if (operation) controls.applyOperations([operation]);
    };

    window.addEventListener("clue:inspector-property-change", onChange);
    window.addEventListener("clue:inspector-property-preview", onPreview);
    return () => {
      window.removeEventListener("clue:inspector-property-change", onChange);
      window.removeEventListener("clue:inspector-property-preview", onPreview);
    };
  }, [documentId]);

  // ── AD3.3: the two ways a user asks for a history step ───────────────────
  // The action menu's Undo/Redo rows (which already dispatch
  // `clue:artifact-action-request` with `{action, kind}` —
  // `use-artifact-action-menu-controller.ts:42-52`) and the ⌘Z / ⇧⌘Z
  // shortcuts. Ported structurally from the website lane's pair
  // (`use-inspector-writes.ts:118-166`), with `"ad"` in place of `"web"`.
  //
  // Scope, unchanged from that precedent: the SERVER-owned document history,
  // never a general chrome undo.
  const undoRef = useRef(edits.undo);
  const redoRef = useRef(edits.redo);
  const onScreenRef = useRef(onScreen);
  useEffect(() => {
    redoRef.current = edits.redo;
    undoRef.current = edits.undo;
    onScreenRef.current = onScreen;
  });

  useEffect(() => {
    if (!documentId) return;
    const onAction = (event: Event) => {
      // AD4.E: the whole decision — the kind guard that keeps the two lanes'
      // listeners apart on one window, and the action guard that keeps §7's
      // unbacked rows out of history — lives in `adActionRequest` above, where
      // it can be tested without a DOM. This listener only performs it.
      const step = adActionRequest((event as CustomEvent).detail);
      if (step === "undo") undoRef.current();
      if (step === "redo") redoRef.current();
    };
    const onKeyDown = (event: KeyboardEvent) => {
      // S2b-6: only while the artifact is on screen; typing keeps its own undo.
      const step = artifactHistoryKey(event, onScreenRef.current);
      if (!step) return;
      event.preventDefault();
      if (step === "redo") redoRef.current();
      else undoRef.current();
    };
    window.addEventListener("clue:artifact-action-request", onAction);
    window.addEventListener("keydown", onKeyDown);
    return () => {
      window.removeEventListener("clue:artifact-action-request", onAction);
      window.removeEventListener("keydown", onKeyDown);
    };
  }, [documentId]);

  return edits;
}
