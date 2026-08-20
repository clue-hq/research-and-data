"use client";

import { useEffect, useRef, type RefObject } from "react";
import { sceneChangeToOperation } from "../adapter/scene-apply";
import type { SceneCanvasControls } from "../components/scene-artifact-canvas";
import type { Scene } from "../engine/scene/contracts";
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
 * ── THE ADDRESSING RULING (AD3.2) ────────────────────────────────────────
 * The web lane's gate demands `typeof detail.documentVersion === "number"`,
 * because its write sends that number as `base_version`. **The ad lane cannot
 * honestly produce it**: `documentStore.fetchDocument` does not parse
 * `current_version` (read-only extracted code), the scene carries no document
 * version, and fetching the document a second time just to read one integer
 * would break this session's own principle — "One fetch, one engine, one
 * scene" (`use-scene-editing-session.ts:44-50`). The edit queue owns
 * `base_version` internally anyway: it fetches and tracks it
 * (`editQueue.ts:110-113,152`), which is precisely why the ad lane has no need
 * of a copy.
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
 * One consequence to know before extending this: the gate requires a NON-NULL
 * primary selection, so the §1.1 canvas schema (an empty selection editing the
 * root frame's background) cannot write through it. That is correct today —
 * `scene-apply.ts` maps no canvas row yet — but the lane that adds those rows
 * must widen this gate deliberately, not discover it by accident.
 */

export function useSceneInspectorWrites({
  canvasControls,
  documentId,
  onReload,
  primaryNodeId,
  scene,
}: {
  /** The mounted canvas's imperative seam (the live engine). */
  canvasControls: RefObject<SceneCanvasControls | null>;
  /** The active design document, or null when nothing is armed. */
  documentId: string | null;
  /** The session's reload nonce bump. */
  onReload: () => void;
  /** The session's primary selection — `selectedIds[0]`, already resolved
   * against the live scene. */
  primaryNodeId: string | null;
  /** The live scene the canvas mirrored up (the very one the engine holds). */
  scene: Scene | null;
}): SceneManualEdits {
  const edits = useSceneManualEdits({
    controlsRef: canvasControls,
    documentId,
    onReload,
  });

  // Latest-value refs so the one listener reads current state without
  // re-arming (written passively, per this repo's react-hooks rules).
  const applyOpsRef = useRef(edits.applyOps);
  const controlsRef = useRef(canvasControls);
  const primaryNodeIdRef = useRef(primaryNodeId);
  const sceneRef = useRef(scene);
  useEffect(() => {
    applyOpsRef.current = edits.applyOps;
    controlsRef.current = canvasControls;
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

  // ── AD3.3 insertion point ────────────────────────────────────────────────
  // Undo/redo (the action menu's `clue:artifact-action-request` items and the
  // ⌘Z/⇧⌘Z shortcuts, as `use-inspector-writes.ts:118-166` binds them for the
  // web lane) belong here. NOTHING is wired today: the controller's `undo`/
  // `redo` are no-ops and the session keeps both menu entries disabled, so a
  // listener now would be an affordance that does nothing.

  return edits;
}
