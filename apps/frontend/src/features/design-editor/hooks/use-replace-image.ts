"use client";

import { useCallback, useEffect, useRef } from "react";
import { uploadWebAsset } from "../data/assets";
import type { AssetRecord } from "../engine/asset-types";
import {
  replaceAssetOp,
  upsertAssetOp,
  type LoadedWebDocument,
  type WebOperation,
} from "../engine/webDocuments";
import type { WebArtifactSelection } from "./use-web-artifact-selection";

/**
 * W4.2 (mapping contract §1 row 12, lane B): the Replace-image flow.
 *
 * The dummy's direct-file-upload UX is preserved verbatim — the inspector's
 * button opens a file input and previews the picked file locally; this hook is
 * the real path behind its `onFileSelect`. The File travels by PROP from the
 * presentation component to here (components may not import `data/`), and the
 * document change follows the upstream editor's proven flow exactly: upload the
 * asset, then apply `upsert_asset` (only when the record is new to the
 * document) + `replace_asset` as ONE batch — one undo step — with intent
 * `"replace_image"`.
 *
 * Failure surfaces through the manual-edits controller's existing inline error
 * slot (W3.3 founder ruling: inline only — never new failure UI).
 */

export interface ReplaceImageDeps {
  /** The manual-edits controller's one write path (base_version, 409/422). */
  applyOps: (operations: WebOperation[], intent?: string) => void;
  document: LoadedWebDocument | null;
  /** Sets the inspector's existing inline error line. */
  onError: (message: string) => void;
  selection: WebArtifactSelection | null;
  upload: (file: File) => Promise<AssetRecord>;
}

/**
 * The pure runner behind the hook — a closure whose only state is the
 * re-entrancy gate, so it is testable without React. `readDeps` is read at
 * call time, so the returned handler keeps one identity while always seeing
 * the current selection/document.
 *
 * The gate covers the UPLOAD; the apply half is already single-flight inside
 * the manual-edits controller (its `busy` discipline), which this never
 * bypasses.
 */
export function createReplaceImageHandler(
  readDeps: () => ReplaceImageDeps,
): (file: File) => Promise<void> {
  let inFlight = false;
  return async (file: File): Promise<void> => {
    if (inFlight) return;
    const { applyOps, document, onError, selection, upload } = readDeps();
    // Not an image selection, or no loaded document → not a write. Same null
    // contract as the W3.1/W3.2 event path: dummy state can never upload.
    if (!selection || selection.node.kind !== "image") return;
    const page = document?.webDoc?.pages?.find((candidate) =>
      Boolean(candidate.nodes?.[selection.node.id]),
    );
    if (!page) return;

    const documentId = document?.documentId ?? null;

    inFlight = true;
    try {
      const record = await upload(file);
      // AD4.A step 3 review (2026-08-21): a ONE-LINE SAFETY FIX carried over
      // from the ad lane's blocker, not a behaviour change. An upload takes
      // seconds, and `applyOps` is bound to the document that was loaded when
      // this handler captured it — so a user who moved to another document
      // while the bytes were travelling had this batch written into the
      // document they LEFT, keyed on a base version that has since moved to the
      // one they are in. Nothing else about this flow changes: the guard only
      // decides whether the write happens, and on the passing path every value
      // used below is the one it always was.
      //
      // (Two known gaps in this hook are deliberately NOT touched here, both
      // recorded for lane B: a selection that moves WITHIN the same document
      // still writes, and the placement's alt text is not this lane's ruling to
      // change — see A38's reasoning on the ad side.)
      if (readDeps().document?.documentId !== documentId) {
        return;
      }
      // The record is already on the document → a plain replace needs no
      // upsert first (upstream WebEditorApp's `docHasAsset`).
      const assets =
        (document?.webDoc?.assets as Record<string, unknown> | undefined) ?? {};
      const inDoc = Object.prototype.hasOwnProperty.call(assets, record.id);
      const replace = replaceAssetOp(page.id, selection.node.id, record.id);
      applyOps(
        inDoc ? [replace] : [upsertAssetOp(record), replace],
        "replace_image",
      );
    } catch (cause) {
      onError(
        cause instanceof Error
          ? cause.message
          : "This image could not be uploaded.",
      );
    } finally {
      inFlight = false;
    }
  };
}

export function useReplaceImage(options: {
  applyOps: (operations: WebOperation[], intent?: string) => void;
  document: LoadedWebDocument | null;
  onError: (message: string) => void;
  selection: WebArtifactSelection | null;
  /** Injectable for tests; the real BFF upload by default. */
  upload?: (file: File) => Promise<AssetRecord>;
}): (file: File) => void {
  const { applyOps, document, onError, selection, upload = uploadWebAsset } =
    options;
  // Latest-value ref so the handler keeps one identity while always reading
  // current props (updated in a passive effect, per this repo's react-hooks
  // rules — the same adaptation the W3.2 port made).
  const depsRef = useRef<ReplaceImageDeps>({
    applyOps,
    document,
    onError,
    selection,
    upload,
  });
  useEffect(() => {
    depsRef.current = { applyOps, document, onError, selection, upload };
  });

  // Built on first use rather than during render: the runner closes over the
  // deps ref, and this repo's react-hooks rules forbid handing a ref to a
  // function at render time. One runner per mount keeps the re-entrancy gate.
  const handlerRef = useRef<((file: File) => Promise<void>) | null>(null);
  return useCallback((file: File) => {
    handlerRef.current ??= createReplaceImageHandler(() => depsRef.current);
    void handlerRef.current(file);
  }, []);
}
