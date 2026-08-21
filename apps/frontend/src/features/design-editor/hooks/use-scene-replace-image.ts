"use client";

import { useCallback, useEffect, useRef } from "react";
import {
  sceneImagePlacementOperations,
  sceneImageReplacementTarget,
} from "../adapter/scene-apply";
import { uploadWebAsset } from "../data/assets";
import type { AssetRecord, Node, Operation } from "../engine/scene/contracts";

/**
 * AD4.A step 2 (§1.3 row 1): the ad lane's Replace-image flow — the ad-side
 * twin of the website lane's `use-replace-image.ts`, and deliberately the same
 * shape, for the same reason every other scene hook mirrors its web sibling.
 *
 * WHY THIS LIVES IN THE HOOK LAYER. Components may not import `data/` or the
 * engine (eslint enforces it), so the panel cannot call the uploader; it takes
 * a plain `(file: File) => void | Promise<void>` prop and the transport lives
 * behind the seam, exactly as `WebInspector`'s `onReplaceImage` already does.
 * The dummy's own markup, classes, labels and its local FileReader preview are
 * untouched — the control that fired an event into the void
 * (`clue:inspector-action`, which nothing listens for) now fires this.
 *
 * WHAT IS AND IS NOT HERE. Every DECISION is the adapter's
 * (`sceneImageReplacementTarget` / `sceneImagePlacementOperations` in
 * `scene-apply.ts`, beside §1.3's other rows — the ONE placement rule the AI
 * suite's Generate and Accept share, so an alt text a user authored survives
 * every way a new picture reaches this node) and every operation is the
 * engine's (`buildNodePlacementOperations`); this file owns only the
 * sequencing — gate, upload, re-gate, hand off — and the two things that are
 * genuinely stateful about it: the re-entrancy guard and the latest-value deps.
 *
 * THE TRANSPORT IS THE PLATFORM'S EXISTING ONE, NOT A SECOND COPY.
 * `data/assets.ts::uploadWebAsset` already posts multipart `file` to the
 * AUTHENTICATED `/api/clue/design/assets` BFF mount (never the headerless
 * `design-public` passthrough, which that upstream route refuses) and already
 * shapes every refusal the design API can return — a structured
 * `detail:{code,message}`, FastAPI's bare-string `detail` (the 413 size
 * refusal), a non-JSON body, and a 200 carrying no record. `POST /assets` is
 * ONE route with ONE client; the `Web` in its name is W4.2 lineage, not lane
 * ownership. (The engine's own `assetLibrary.ts::uploadAsset` is the same call,
 * but parses the body with an unguarded `response.json()` and reads `detail`
 * only as an object, so a bare-string diagnostic would be dropped and a gateway
 * HTML body would surface a `SyntaxError` in the inspector's error line. The
 * engine is verbatim upstream and is not edited to fix that.)
 *
 * FAILURE IS VISIBLE AND NEVER OUTLIVES ITSELF. The message goes to the
 * inspector's EXISTING inline error slot (`ImageInspector`'s `error` prop, fed
 * by the manual-edits controller's `reportError`) — the same slot the CAS path
 * uses, and no new copy. And the returned promise REJECTS on every path where
 * the document did not take the file, which is what puts `InspectorImageUpload`'s
 * local preview back: a panel showing a picture the document does not have is
 * the defect this lane has now paid for five times.
 */

/** The rejection every refused pick carries. Its message is diagnostic only and
 * is never rendered — a refusal the user should read about reaches the
 * inspector's error slot instead, in the API's or the engine's own words. */
export class SceneReplaceImageRefused extends Error {
  constructor(reason: string) {
    super(`replace image refused: ${reason}`);
    this.name = "SceneReplaceImageRefused";
  }
}

export interface SceneReplaceImageDeps {
  /** The manual-edits controller's one write path (optimistic apply → CAS
   * queue). `false` means the batch did not land; when it is an engine
   * REJECTION the controller has already put the engine's words in the error
   * slot, and the two branches that say nothing are pre-empted by `canApply`. */
  applyOps: (operations: Operation[], intent?: string) => boolean;
  /** FIX 1: is the write path armed and the engine live? Asked BEFORE the
   * upload, because a refusal after it strands a minted asset. */
  canApply: () => boolean;
  /** Clears both inline slots. A new pick supersedes what the last one said. */
  clearMessages: () => void;
  /** The session's PRIMARY selection, resolved against the live scene. */
  node: Node | null;
  /** Sets the inspector's existing inline error line. */
  onError: (message: string) => void;
  upload: (file: File) => Promise<AssetRecord>;
}

/** The intent label, for signature parity with the write path's other callers.
 * It stops at `applyOps`, which documents why the queue takes none. */
const REPLACE_IMAGE_INTENT = "inspector: replace image";

/**
 * The pure runner behind the hook — a closure whose only state is the
 * re-entrancy gate, so it is testable without React (the
 * `createReplaceImageHandler` precedent). `readDeps` is read at call time AND
 * AGAIN after the upload, so the handler keeps one identity while always seeing
 * the current selection.
 *
 * THE SECOND READ IS NOT DEFENSIVE PADDING. An upload takes seconds, and
 * `applyOps` writes to whatever document is armed at the moment it is called —
 * so a selection that moved (or an artifact tab that changed) between the pick
 * and the response would land this placement on a node the user is no longer
 * looking at, or in another ad entirely. It also re-asks §4's lock, which can
 * be turned on from the panel header while the bytes are travelling.
 */
export function createSceneReplaceImageHandler(
  readDeps: () => SceneReplaceImageDeps,
): (file: File) => Promise<void> {
  let inFlight = false;
  return async (file: File): Promise<void> => {
    // A second pick while one is in flight is refused rather than queued: the
    // two would race onto the same node and the panel could end up previewing
    // the loser.
    if (inFlight) {
      throw new SceneReplaceImageRefused("another upload is in flight");
    }
    const before = readDeps();
    const target = before.node;
    // Not an image selection, or §4's lock — REFUSED BEFORE THE TRANSPORT. An
    // upload that mints an asset and then cannot place it is a half write: a
    // registry row nothing references.
    if (!target || !sceneImageReplacementTarget(target)) {
      throw new SceneReplaceImageRefused("this selection takes no image");
    }
    // FIX 1 (review): the same rule applied to the OTHER half of "can this land
    // at all". Nothing armed, or no live engine (D9 read-only) — states in which
    // `applyOps` refuses SILENTLY, so a post-upload refusal would leave a minted
    // asset behind an empty error slot. Reachable: CanvasKit fails to activate,
    // the scene still loads and the layer tree still selects, so the button is
    // live over an engine that can apply nothing.
    if (!before.canApply()) {
      throw new SceneReplaceImageRefused("the write path is not armed");
    }
    // A new attempt supersedes what the last one said — a refusal about a file
    // the user has already replaced is no longer true. Cleared HERE rather than
    // at entry so a pick this gate refuses (a locked node, a dead engine)
    // remains the complete non-event every other §4 refusal on this lane is,
    // messages included.
    before.clearMessages();

    inFlight = true;
    let record: AssetRecord;
    try {
      record = await before.upload(file);
    } catch (cause) {
      // The API's own diagnostic, in the inspector's existing slot.
      before.onError(cause instanceof Error ? cause.message : String(cause));
      throw cause;
    } finally {
      inFlight = false;
    }

    const after = readDeps();
    if (!after.node || after.node.id !== target.id) {
      throw new SceneReplaceImageRefused("the selection moved during the upload");
    }
    if (!sceneImageReplacementTarget(after.node)) {
      throw new SceneReplaceImageRefused("the node was locked during the upload");
    }
    const operations = sceneImagePlacementOperations(after.node, record);
    // A change that changes nothing is not a write — the deduplicated upload
    // handed back the picture this node already carries. Not a failure either:
    // the document really does hold it, so the preview stays.
    if (!operations) {
      return;
    }
    if (!after.applyOps(operations, REPLACE_IMAGE_INTENT)) {
      throw new SceneReplaceImageRefused("the engine refused the batch");
    }
  };
}

export function useSceneReplaceImage(options: {
  applyOps: (operations: Operation[], intent?: string) => boolean;
  canApply: () => boolean;
  clearMessages: () => void;
  node: Node | null;
  onError: (message: string) => void;
  /** Injectable for tests; the platform's BFF upload by default. */
  upload?: (file: File) => Promise<AssetRecord>;
}): (file: File) => Promise<void> {
  const {
    applyOps,
    canApply,
    clearMessages,
    node,
    onError,
    upload = uploadWebAsset,
  } = options;
  // Latest-value ref so the handler keeps one identity while always reading
  // current props (written in a passive effect, per this repo's react-hooks
  // rules — the same adaptation every other hook on this lane made).
  const depsRef = useRef<SceneReplaceImageDeps>({
    applyOps,
    canApply,
    clearMessages,
    node,
    onError,
    upload,
  });
  useEffect(() => {
    depsRef.current = {
      applyOps,
      canApply,
      clearMessages,
      node,
      onError,
      upload,
    };
  });

  // Built on first use rather than during render: the runner closes over the
  // deps ref, and this repo's react-hooks rules forbid handing a ref to a
  // function at render time. One runner per mount keeps the re-entrancy gate.
  const handlerRef = useRef<((file: File) => Promise<void>) | null>(null);
  return useCallback((file: File) => {
    handlerRef.current ??= createSceneReplaceImageHandler(() => depsRef.current);
    return handlerRef.current(file);
  }, []);
}
