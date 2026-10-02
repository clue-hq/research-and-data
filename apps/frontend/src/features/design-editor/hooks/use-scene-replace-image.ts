"use client";

import { useCallback, useEffect, useRef } from "react";
import {
  sceneImagePlacementOperations,
  sceneImageReplacementTarget,
} from "../adapter/scene-apply";
import { uploadWebAsset } from "../data/assets";
import type { AssetRecord, Node, Operation } from "../engine/scene/contracts";
import type { SceneWriteGate } from "./use-scene-manual-edits";

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
 * uses, and no new UI. EVERY refusal reaches it: the API's own words for an
 * upload failure, and one of the four sentences below for the refusals this file
 * decides (Task 3 — until then those four were silent, which is exactly why the
 * flow read as "upload does nothing"). And the returned promise REJECTS on every path where
 * the document did not take the file, which is what puts `InspectorImageUpload`'s
 * local preview back: a panel showing a picture the document does not have is
 * the defect this lane has now paid for five times.
 */

/** The rejection every refused pick carries. Its message is diagnostic only and
 * is never rendered — what the user reads reaches the inspector's error slot
 * instead, in the API's words, the engine's, or one of the four sentences
 * below. */
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
  /** FIX 1: may a write land — armed, engine live, and (task 4) not locked
   * behind a running design turn? Asked BEFORE the upload, because a refusal
   * after it strands a minted asset. The whole gate rather than a boolean, so
   * the ONE refusal that has words can use them (fix round 1, I3). */
  writeGate: () => SceneWriteGate;
  /** Clears both inline slots. A new pick supersedes what the last one said. */
  clearMessages: () => void;
  /** The document the pick was aimed at. Compared after the upload beside the
   * node id, because node ids are per-document and the seed script writes
   * template slugs (`image_hero`) — two ads routinely carry the same one, so a
   * node-only guard let an artifact tab switched mid-upload write into an ad the
   * user never touched. (AD4.A step 3 review; the AI suite had the identical gap
   * and both were closed in one change.) */
  documentId: string | null;
  /** The session's PRIMARY selection, resolved against the live scene. */
  node: Node | null;
  /** Sets the inspector's existing inline error line. */
  onError: (message: string) => void;
  /** Task 4 (I3): sets the inspector's existing inline NOTE line — the slot a
   * refusal that is a STATE (the agent-run lock) belongs in, never the error
   * line. Same slot every other note on this lane uses; no new UI. */
  onNote: (message: string) => void;
  upload: (file: File) => Promise<AssetRecord>;
}

/**
 * THE FOUR SENTENCES A REFUSAL SAYS. Until Task 3 every one of these paths threw
 * a diagnostic-only `SceneReplaceImageRefused` and put NOTHING in the error
 * slot: the panel's preview snapped back and the flow read as "upload does
 * nothing" — the founder's report, and the actual bug. The rejection still
 * happens (it is what reverts the preview); it is no longer the ONLY thing that
 * happens. Exported because Task 4's picker refuses on the same grounds and must
 * say the same words, not a second vocabulary for the same states.
 */
export const NOT_ACCEPTING_EDITS = "This document isn't accepting edits right now.";
export const NOT_AN_IMAGE_TARGET = "Select an unlocked image to replace.";
export const SELECTION_MOVED =
  "The selection changed while the upload was running — try again.";
export const SAME_IMAGE_IN_USE = "That's the image already in use.";

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
    const documentId = before.documentId;
    // FIX 1 (review): nothing armed, or no live engine (D9 read-only) — states
    // in which `applyOps` refuses SILENTLY, so a post-upload refusal would leave
    // a minted asset behind an empty error slot. Reachable: CanvasKit fails to
    // activate, the scene still loads and the layer tree still selects, so the
    // button is live over an engine that can apply nothing.
    //
    // ASKED FIRST, BEFORE THE TARGET CHECK, and deliberately: in view mode
    // NOTHING is editable, so "select an unlocked image" would send the user
    // hunting for a selection that could never have worked. The document-level
    // truth comes first, in the clipboard lane's wording.
    //
    // MERGED with the live-streaming lock (rung A, task 4): `writeGate` is the
    // same question `canApply` asked, with the answer's REASON attached. Every
    // refusal still speaks (Task 3's rule) — but in the slot that fits it: a
    // gate that carries a note (the design agent's run) says it in the NOTE
    // slot, in the lock's own words, because a locked editor is a state to wait
    // out, not a failure; every other refusal (nothing armed, a dead engine)
    // goes to the error slot as before.
    const gate = before.writeGate();
    if (!documentId || !gate.allowed) {
      if (gate.note !== null) {
        before.onNote(gate.note);
      } else {
        before.onError(NOT_ACCEPTING_EDITS);
      }
      throw new SceneReplaceImageRefused(
        documentId ? (gate.refusal ?? "the write path is not armed") : "no document is armed",
      );
    }
    // Not an image selection, or §4's lock — REFUSED BEFORE THE TRANSPORT. An
    // upload that mints an asset and then cannot place it is a half write: a
    // registry row nothing references.
    if (!target || !sceneImageReplacementTarget(target)) {
      before.onError(NOT_AN_IMAGE_TARGET);
      throw new SceneReplaceImageRefused("this selection takes no image");
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
    // BOTH HALVES — the same node id in a DIFFERENT document is a different
    // node (the `documentId` dep says why).
    if (
      !after.node ||
      after.node.id !== target.id ||
      after.documentId !== documentId
    ) {
      after.onError(SELECTION_MOVED);
      throw new SceneReplaceImageRefused("the selection moved during the upload");
    }
    if (!sceneImageReplacementTarget(after.node)) {
      after.onError(NOT_AN_IMAGE_TARGET);
      throw new SceneReplaceImageRefused("the node was locked during the upload");
    }
    const operations = sceneImagePlacementOperations(after.node, record);
    // A change that changes nothing is not a write — the deduplicated upload
    // handed back the picture this node already carries. It used to RESOLVE
    // silently, which is indistinguishable from a broken upload: the user picked
    // a file, waited, and read nothing. It now says so and rejects, so the
    // panel's preview reverts to the picture the document actually holds — which
    // is the same picture, so nothing visibly moves except the explanation.
    if (!operations) {
      after.onError(SAME_IMAGE_IN_USE);
      throw new SceneReplaceImageRefused("the asset is already in use");
    }
    if (!after.applyOps(operations, REPLACE_IMAGE_INTENT)) {
      throw new SceneReplaceImageRefused("the engine refused the batch");
    }
  };
}

export function useSceneReplaceImage(options: {
  applyOps: (operations: Operation[], intent?: string) => boolean;
  clearMessages: () => void;
  documentId: string | null;
  node: Node | null;
  onError: (message: string) => void;
  onNote: (message: string) => void;
  /** Injectable for tests; the platform's BFF upload by default. */
  upload?: (file: File) => Promise<AssetRecord>;
  writeGate: () => SceneWriteGate;
}): (file: File) => Promise<void> {
  const {
    applyOps,
    clearMessages,
    documentId,
    node,
    onError,
    onNote,
    upload = uploadWebAsset,
    writeGate,
  } = options;
  // Latest-value ref so the handler keeps one identity while always reading
  // current props (written in a passive effect, per this repo's react-hooks
  // rules — the same adaptation every other hook on this lane made).
  const depsRef = useRef<SceneReplaceImageDeps>({
    applyOps,
    clearMessages,
    documentId,
    node,
    onError,
    onNote,
    upload,
    writeGate,
  });
  useEffect(() => {
    depsRef.current = {
      applyOps,
      clearMessages,
      documentId,
      node,
      onError,
      onNote,
      upload,
      writeGate,
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
