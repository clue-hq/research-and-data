"use client";

import { useEffect, useRef, useState } from "react";
import {
  exportFilename,
  parseSceneExportRequest,
  sceneExportProfile,
  sceneExportResultMessage,
} from "../adapter/scene-export";
import { designBffConfig } from "../data/design-bff";
import type { PageId, Scene } from "../engine/scene/contracts";
import { createApiExportRunner } from "../engine/scene/exportRunner";

/**
 * AD4.D step 2 (§1.11): the export menu's request, answered.
 *
 * The REQUEST leg already existed and is untouched — the menu's controller
 * dispatches `clue:artifact-export-request`
 * (`use-image-export-controller.ts:39`) and, until now, nothing listened. This
 * hook is the listener: it turns an accepted request into the extracted
 * runner's one POST and drops the returned artifact straight into the browser's
 * downloads (the standing ruling: a direct download, no new chrome).
 *
 * ── WHY THE LISTENER LOOKS LIKE `use-scene-inspector-writes.ts` ─────────────
 * Same ref discipline, for the same reason: every live value rides a ref, so a
 * re-render mid-export never re-arms the listener (which would drop the request
 * the user just made) and the handler always reads the CURRENT scene rather
 * than the one it closed over. It goes one step FURTHER than that sibling and
 * arms with NO dependency at all — a write hook can be inert before a document
 * loads, but an export request that arrives then still has to be answered
 * (honestly, with a refusal) rather than fall on no listener; the reasoning is
 * at the effect. The `kind !== "ad"` guard inside `parseSceneExportRequest` is
 * what keeps the two lanes' listeners apart on one window, exactly as the
 * action-menu listener's is.
 *
 * ── EXPORT IS A READ (ruling R-D3 / Gate G-H) ──────────────────────────────
 * Exports are NOT gated on the agent-turn flag and touch no `threadBusy`
 * plumbing, because they persist nothing: the extracted runner hardwires
 * `persist_preflight: false` in its payload (`exportRunner.ts:124`, with the
 * full reasoning at that site — the endpoint's default writes the token-BAKED
 * preflight scene back into the document and bumps its version behind the edit
 * queue's back). This file must never send a `persist_preflight` of its own;
 * the flag is verified there, not duplicated here.
 *
 * ── WHAT IS STATE HERE, AND WHY IT IS ALLOWED ──────────────────────────────
 * The AD4.R MVP state model: the accepted engine scene owns document truth and
 * React holds only UI facts. `exportStatus` is operation feedback — what the
 * last export attempt did — which is a UI fact and nothing else. It claims
 * nothing about the document, and the export writes nothing to it.
 */

/**
 * PORTED, not imported, from the standalone editor's
 * `subsystems/clue-design/apps/editor/src/components/exportArtifactActions.ts`
 * (`downloadDataUrl`, lines 7–30; `dataUrlToBlob`, lines 73–88). Nothing here
 * may import from `subsystems/`, so the mechanics are mirrored: the anchor
 * carries the filename and `rel="noopener"`, the bytes go out as an OBJECT URL
 * (a multi-megabyte `href="data:…"` is what browsers refuse or truncate) with a
 * fall back to the raw data URL if the blob cannot be built, and the object URL
 * is revoked on the next tick — after the click has consumed it.
 *
 * ONE deviation from upstream, deliberate: this returns whether a file actually
 * left. Upstream's callers announce nothing, so a silent no-op costs them
 * nothing; this lane's status line would otherwise say "PNG exported" about a
 * download that never happened.
 */
function downloadDataUrl(dataUrl: string | null, filename: string): boolean {
  if (!dataUrl || typeof document === "undefined") {
    return false;
  }
  const anchor = document.createElement("a");
  anchor.download = filename;
  anchor.rel = "noopener";

  let objectUrl: string | null = null;
  try {
    objectUrl = URL.createObjectURL(dataUrlToBlob(dataUrl));
    anchor.href = objectUrl;
  } catch {
    anchor.href = dataUrl;
  }

  document.body.append(anchor);
  anchor.click();
  anchor.remove();

  const created = objectUrl;
  if (created) {
    window.setTimeout(() => URL.revokeObjectURL(created), 0);
  }
  return true;
}

/** Upstream `exportArtifactActions.ts:73-88`, verbatim in behaviour: a base64
 * payload is decoded byte-by-byte (`atob` yields latin-1 chars, so a `charCodeAt`
 * copy is the only way to keep binary formats intact), a percent-encoded one is
 * decoded as text. */
function dataUrlToBlob(dataUrl: string): Blob {
  const [metadata, payload] = dataUrl.split(",", 2);
  if (!metadata || payload === undefined) {
    throw new Error("Invalid data URL");
  }
  const mimeType = /^data:([^;,]+)/.exec(metadata)?.[1] ?? "application/octet-stream";
  if (metadata.includes(";base64")) {
    const binary = atob(payload);
    const bytes = new Uint8Array(binary.length);
    for (let index = 0; index < binary.length; index += 1) {
      bytes[index] = binary.charCodeAt(index);
    }
    return new Blob([bytes], { type: mimeType });
  }
  return new Blob([decodeURIComponent(payload)], { type: mimeType });
}

export function useSceneExport({
  documentId,
  pageId,
  scene,
  title,
}: {
  /** The active design document. The listener does NOT arm on it — see the
   * unconditional arming below — but every status is STAMPED with it, so one
   * artifact's outcome can never be announced under another's. */
  documentId: string | null;
  /** The page the canvas is rendering (§5: one artboard). The export names it
   * explicitly rather than exporting every page the document happens to hold. */
  pageId: PageId | null;
  /** The LIVE engine scene the canvas mirrored up. With a `documentId` the
   * runner's payload does not carry it (the server reads its own copy), but the
   * request contract requires one, and the mirror is the relaid scene the user
   * is actually looking at. */
  scene: Scene | null;
  /** The fallback download title, for a request that carried none (the sharing
   * menu's shape). The DETAIL's title wins — it is what the tab said at the
   * moment the user pressed Export. */
  title: string | null;
}): { exportStatus: string | null } {
  // STAMPED with the document it is about and DERIVED against the current one —
  // the discipline the scene, the selection, the zoom, the history and the
  // palette all follow in `use-scene-editing-session.ts`, and for the same
  // reason. Without the stamp, switching artifacts after an export re-mounts
  // the menu's `aria-live` span still holding the PREVIOUS ad's "PNG exported",
  // which then outranks the controller's line forever (the menu reads
  // `exportStatus ?? controller.statusMessage`) — a finished operation
  // announced about a document it never touched. Derivation rather than a
  // clearing effect, because this repo's react-hooks rules forbid setting state
  // from an effect.
  const [status, setStatus] = useState<{
    forDocumentId: string | null;
    message: string;
  } | null>(null);
  const exportStatus =
    status && status.forDocumentId === documentId ? status.message : null;

  // Latest-value refs so the one listener reads current state without re-arming
  // (written passively, per this repo's react-hooks rules) — the
  // `use-scene-inspector-writes.ts` pattern.
  const documentIdRef = useRef(documentId);
  const pageIdRef = useRef(pageId);
  const sceneRef = useRef(scene);
  const titleRef = useRef(title);
  useEffect(() => {
    documentIdRef.current = documentId;
    pageIdRef.current = pageId;
    sceneRef.current = scene;
    titleRef.current = title;
  });

  // Ruling R-D6: one export at a time, and a second request is REFUSED rather
  // than queued. A ref, not state, because the answer must be true the instant
  // the second event arrives — a re-render later is too late.
  const inFlightRef = useRef(false);

  // ARMED UNCONDITIONALLY, and deliberately not on `documentId` (review fix,
  // finding 1). Arming on it made the "No document to export" refusal below
  // dead code for the one case it names: during the pre-load window there was
  // no listener at all, so pressing Export produced no export AND no refusal,
  // leaving the span announcing the controller's optimistic "PNG export
  // requested at 1x" — an announcement of something that did not happen, which
  // is precisely what R-D7 exists to prevent. Every live value already rides a
  // ref, so there is nothing for the effect to depend on: it arms once per
  // mount and the guards inside answer for whatever state the session is in.
  useEffect(() => {
    /** One place to write a status, so every message is stamped with the
     * document it is about. Stamped with the LIVE id rather than the armed one:
     * a refusal or an outcome is addressed to whoever is looking now. */
    const report = (message: string) =>
      setStatus({ forDocumentId: documentIdRef.current, message });

    const onExportRequest = (event: Event) => {
      const request = parseSceneExportRequest((event as CustomEvent).detail);
      // Not this lane's export (another artifact kind, the sharing menu's ZIP).
      // The event bus serves other kinds, so this is a silent non-event.
      if (!request) return;

      const armedDocumentId = documentIdRef.current;
      const armedScene = sceneRef.current;
      // Nothing loaded yet, or the empty-artboard state: there is nothing to
      // export. Refused out loud rather than by a status line that never
      // changes.
      if (!armedDocumentId || !armedScene) {
        report("No document to export");
        return;
      }
      if (inFlightRef.current) {
        report("Export already in progress");
        return;
      }
      // Ruling R-D7: set SYNCHRONOUSLY, in the same event the controller sets
      // its own optimistic "…export requested" line — this one is threaded into
      // the span over that one, so it must already be the newer fact when the
      // menu re-renders.
      report(`Exporting ${request.format}…`);

      const armedPageId = pageIdRef.current;

      void (async () => {
        // EVERYTHING that can throw is inside the try, so the `finally` always
        // clears the single-flight flag (review fix, finding 3). The flag is
        // raised here rather than before the call: an async function body runs
        // synchronously up to its first `await`, so it is already true by the
        // time this listener returns and a second request still cannot slip
        // past the guard above — but a throw from `exportFilename`,
        // `designBffConfig` or `createApiExportRunner` can no longer wedge it
        // raised forever.
        inFlightRef.current = true;
        try {
          const filename = exportFilename(
            request.title ?? titleRef.current ?? "",
            request.format,
          );
          // Captured per call, never at module scope: `designBffConfig()` reads
          // `window.location.origin`. Traffic goes through the authenticated
          // BFF — never browser→FastAPI.
          const config = designBffConfig();
          const runExport = createApiExportRunner({
            apiBaseUrl: config.apiBaseUrl,
            documentId: armedDocumentId,
            fetchImpl: config.fetchImpl,
          });
          const result = await runExport({
            scene: armedScene,
            profile: sceneExportProfile(request.format, request.scale),
            pageIds: armedPageId ? [armedPageId] : [],
            documentId: armedDocumentId,
          });
          // The A39/A41 discipline: an export takes seconds, and the user can
          // switch artifact tabs inside them. A file for the ad they LEFT is
          // not something they asked for, so it is dropped rather than
          // downloaded.
          if (documentIdRef.current !== armedDocumentId) {
            report("Export cancelled — document changed");
            return;
          }
          if (result.status !== "ok") {
            report(sceneExportResultMessage(request.format, result));
            return;
          }
          // §1.11 exports ONE artboard, so `artifacts[0]` is the deliverable.
          if (!downloadDataUrl(result.artifacts[0]?.data_url ?? null, filename)) {
            // An "ok" carrying no bytes is not a success the user can use, and
            // announcing one would be this lane's signature defect: the panel
            // stating something that did not happen.
            report(`${request.format} export returned no file`);
            return;
          }
          report(sceneExportResultMessage(request.format, result));
        } catch (cause) {
          // A transport throw (the runner's non-2xx, an offline fetch) is the
          // user's answer too — never an unhandled rejection.
          if (documentIdRef.current !== armedDocumentId) {
            report("Export cancelled — document changed");
            return;
          }
          report(cause instanceof Error ? cause.message : String(cause));
        } finally {
          inFlightRef.current = false;
        }
      })();
    };
    window.addEventListener("clue:artifact-export-request", onExportRequest);
    return () =>
      window.removeEventListener("clue:artifact-export-request", onExportRequest);
  }, []);

  return { exportStatus };
}
