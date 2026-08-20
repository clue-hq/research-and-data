"use client";

import { useEffect, useRef, type RefObject } from "react";
import {
  sceneCanvasChangeToOperation,
  sceneChangeToOperation,
} from "../adapter/scene-apply";
import type { SceneCanvasControls } from "../components/scene-artifact-canvas";
import type { PageId, Scene } from "../engine/scene/contracts";
import { getPage } from "../engine/scene/sceneQueries";
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
 * schema — an empty selection editing the PAGE — could never write through it.
 * AD3.2 said the lane that added those rows "must widen this gate deliberately,
 * not discover it by accident". This is that widening, and it is a SEPARATE
 * branch: the node path below is untouched, still demanding everything it did.
 *
 * A canvas event states something positive rather than merely missing:
 *
 *   • `detail.selectionId` is exactly `null` — the controller HAS addressing
 *     and that addressing says "no node is selected". An event carrying no
 *     addressing at all (the dummy fixture path, `dispatchInspectorEvent` with
 *     no third argument) leaves it `undefined` and is refused here, then
 *     refused again by the node path's `typeof … !== "string"`.
 *   • `detail.artifactId` is this session's ACTIVE artifact — the event comes
 *     from a panel wired to the document this hook is armed for, not from one
 *     still mounted for the tab the user just left.
 *   • this session's own primary selection is `null` too, so the session and
 *     the event agree that the CANVAS is what is selected.
 *   • the live scene really carries the page the write will name — the same
 *     "the write can never be aimed at something that is not there" rule the
 *     node path applies to its node.
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

export function useSceneInspectorWrites({
  artifactId,
  canvasControls,
  documentId,
  loadGeneration,
  onReload,
  pageId,
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
  /** The session's reload nonce bump. */
  onReload: () => void;
  /** AD4.0: the page the canvas is rendering (§5: one artboard), the very one
   * `hydrateSceneCanvasState` read. */
  pageId: PageId | null;
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
    onReload,
    redoDepth,
    undoDepth,
  });

  // Latest-value refs so the one listener reads current state without
  // re-arming (written passively, per this repo's react-hooks rules).
  const applyOpsRef = useRef(edits.applyOps);
  const artifactIdRef = useRef(artifactId);
  const controlsRef = useRef(canvasControls);
  const pageIdRef = useRef(pageId);
  const primaryNodeIdRef = useRef(primaryNodeId);
  const sceneRef = useRef(scene);
  useEffect(() => {
    applyOpsRef.current = edits.applyOps;
    artifactIdRef.current = artifactId;
    controlsRef.current = canvasControls;
    pageIdRef.current = pageId;
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
        value?: unknown;
      } | null;
      if (!detail || typeof detail.property !== "string") return;

      // ── AD4.0 / §1.1: the CANVAS (page) rows ───────────────────────────
      // Its own gate, reasoned out in the header above. `=== null` (not
      // `!== "string"`) is the point: an addressed "nothing is selected", not
      // an event that simply carries no addressing.
      if (detail.selectionId === null) {
        if (
          typeof detail.artifactId !== "string" ||
          detail.artifactId !== artifactIdRef.current
        )
          return;
        // The session must agree the canvas is what is selected.
        if (primaryNodeIdRef.current !== null) return;
        const liveCanvas = sceneRef.current;
        const livePageId = pageIdRef.current;
        // The scene the engine is holding must really carry that page.
        if (!liveCanvas || !livePageId || !getPage(liveCanvas, livePageId))
          return;
        if (!controlsRef.current.current) return;
        const pageOperation = sceneCanvasChangeToOperation(
          {
            property: detail.property,
            selectionId: null,
            value: detail.value,
          },
          liveCanvas,
          livePageId,
        );
        // The same null contract: an unmapped property or an unparseable value
        // produces no operation, and no operation is no write.
        if (!pageOperation) return;
        applyOpsRef.current([pageOperation], `inspector: ${detail.property}`);
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
      const live = sceneRef.current;
      if (!live) return;
      // The scene the engine is holding must really carry that node — the
      // adapter needs the Node itself, and a miss means the selection and the
      // scene disagree (a reload mid-edit), which is never a write.
      const node = live.nodes[detail.selectionId];
      if (!node) return;
      // Armed: a mounted canvas to apply through. (`applyOps` re-checks both
      // this and the document id — it is the one write path and cannot depend
      // on a caller having gated first.)
      if (!controlsRef.current.current) return;
      const operation = sceneChangeToOperation(
        {
          property: detail.property,
          selectionId: detail.selectionId,
          value: detail.value,
        },
        node,
        live,
      );
      // The AD3.1 null contract: an unmapped property, an unparseable value or
      // a locked node produces no operation, and no operation is no write.
      if (!operation) return;
      applyOpsRef.current([operation], `inspector: ${detail.property}`);
    };
    window.addEventListener("clue:inspector-property-change", onChange);
    return () =>
      window.removeEventListener("clue:inspector-property-change", onChange);
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
  useEffect(() => {
    redoRef.current = edits.redo;
    undoRef.current = edits.undo;
  });

  useEffect(() => {
    if (!documentId) return;
    const onAction = (event: Event) => {
      const detail = (event as CustomEvent).detail as {
        action?: unknown;
        kind?: unknown;
      } | null;
      // The kind guard is what keeps the two lanes' listeners apart on one
      // window — the header stamps the active artifact's kind onto every
      // request (`artifact-header.tsx:78`), so a web artifact's Undo can never
      // reach the ad document, and vice versa.
      if (detail?.kind !== "ad") return;
      if (detail.action === "undo") undoRef.current();
      if (detail.action === "redo") redoRef.current();
    };
    const onKeyDown = (event: KeyboardEvent) => {
      if (!(event.metaKey || event.ctrlKey) || event.key.toLowerCase() !== "z")
        return;
      // Native text-editing undo owns focused inputs/contenteditables — an
      // inspector field mid-edit must undo the TYPING, not the document.
      const target = event.target as HTMLElement | null;
      if (
        target &&
        (target.isContentEditable ||
          target.tagName === "INPUT" ||
          target.tagName === "TEXTAREA")
      )
        return;
      event.preventDefault();
      if (event.shiftKey) redoRef.current();
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
