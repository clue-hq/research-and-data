"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import type {
  ImageExportFormat,
  ImageExportPreview,
  ImageExportScale,
} from "@/features/chat-shell/model/image-export";
import {
  exportFilename,
  exportStatusFor,
  parseSceneExportRequest,
  previewAnchorsMatch,
  previewCacheKey,
  previewCacheLookup,
  previewCacheStore,
  previewRenderMode,
  sceneExportProfile,
  sceneExportResultMessage,
  sceneExportScaleMultiplier,
  type SceneExportPreviewCache,
  type SceneExportStatus,
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
 * ── AD4.D STEP 3: THE PREVIEW LEG ──────────────────────────────────────────
 * The menu's collapsible preview region runs the SAME export at the SAME
 * settings and shows the returned image (§1.11 — the designed hook hosts the
 * real render). It is a second, independent leg of the same hook rather than a
 * hook of its own, because it shares every input the download leg reads (the
 * document, the page, the live scene) and the one status line they both speak
 * through. What it does NOT share is the single-flight flag: a download in
 * progress must not swallow a preview request, or opening the region while a
 * 4x PNG downloads would show nothing and say nothing.
 *
 * ── WHAT IS STATE HERE, AND WHY IT IS ALLOWED ──────────────────────────────
 * The AD4.R MVP state model: the accepted engine scene owns document truth and
 * React holds only UI facts. `exportStatus` is operation feedback — what the
 * last export attempt did — which is a UI fact and nothing else. It claims
 * nothing about the document, and the export writes nothing to it. The preview
 * (and its cache) is the same species: a picture OF a scene, keyed on that
 * scene's identity, never a source of truth about it. Every one of them is
 * STAMPED with what produced it and DERIVED against what is live now, so a
 * render can go stale but can never be mistaken for current.
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
export function downloadDataUrl(dataUrl: string | null, filename: string): boolean {
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
  awaitWritesSettled,
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
  /** R-D19: resolves once the document's queued write batches have been
   * persisted. BOTH legs await it immediately before rendering, because the
   * server renders its PERSISTED copy and this lane applies edits optimistically
   * — see the ruling section in the header. Optional so the pre-load and
   * fixture paths compose without a write controller; absent means "nothing is
   * being written", which is true on both. */
  awaitWritesSettled?: (documentId: string) => Promise<void>;
}): {
  /** §1.11: the render to show in the designed preview region, paired with the
   * element that hosts it, or `null` when there is nothing TRUE to show — no
   * request yet, one in flight, one that failed, one whose scene or document the
   * session has since moved past, or a payload neither element can display.
   * Every one of those is the SAME picture on screen (the dummy's designed empty
   * region, ruling R-D14), so the menu needs no way to tell them apart and is
   * deliberately handed none. The two travel as ONE value so "a URL with no way
   * to render it" is not a state anything downstream can be handed. */
  exportPreview: ImageExportPreview | null;
  exportStatus: SceneExportStatus | null;
  /** §1.11: show the preview region at these settings — called when it opens
   * and on every format/scale change while it is open. */
  requestExportPreview: (format: ImageExportFormat, scale: ImageExportScale) => void;
} {
  // STAMPED with the document it is about and DERIVED against the current one —
  // the discipline the scene, the selection, the zoom, the history and the
  // palette all follow in `use-scene-editing-session.ts`, and for the same
  // reason. Without the stamp, switching artifacts after an export re-mounts
  // the menu's `aria-live` span still holding the PREVIOUS ad's "PNG exported",
  // which then outranks the controller's line forever (the menu reads
  // `exportStatus ?? controller.statusMessage`) — a finished operation
  // announced about a document it never touched. Derivation rather than a
  // clearing effect, because this repo's react-hooks rules forbid setting state
  // from an effect. The one exception — a `null` stamp, meaning a refusal made
  // when no document was loaded, which must OUTLIVE the document's arrival —
  // lives in `exportStatusFor`, where its reasoning is written out.
  const [status, setStatus] = useState<
    (SceneExportStatus & { forDocumentId: string | null }) | null
  >(null);
  const exportStatus = exportStatusFor(status, documentId);

  // Latest-value refs so the one listener reads current state without re-arming
  // (written passively, per this repo's react-hooks rules) — the
  // `use-scene-inspector-writes.ts` pattern.
  const documentIdRef = useRef(documentId);
  const pageIdRef = useRef(pageId);
  const sceneRef = useRef(scene);
  const titleRef = useRef(title);
  const awaitWritesSettledRef = useRef(awaitWritesSettled);
  useEffect(() => {
    documentIdRef.current = documentId;
    pageIdRef.current = pageId;
    sceneRef.current = scene;
    titleRef.current = title;
    awaitWritesSettledRef.current = awaitWritesSettled;
  });

  /** One place to write a status, so every message is stamped with the document
   * it is about. Stamped with the LIVE id rather than the one the operation
   * armed against: a refusal or an outcome is addressed to whoever is looking
   * now. Both legs report through it — a preview failure and a download failure
   * are the same line in the same span (ruling R-D14: the region itself stays
   * the honest empty state and says nothing on its own).
   *
   * `failed` says whether the user asked for a file and got none. It is what
   * lets the menu render the outcome VISIBLY instead of only to a screen
   * reader; it defaults to false so the two progress lines stay quiet. */
  const report = useCallback((message: string, failed = false) => {
    setStatus({ failed, forDocumentId: documentIdRef.current, message });
  }, []);

  // Ruling R-D6: one export at a time, and a second request is REFUSED rather
  // than queued. A ref, not state, because the answer must be true the instant
  // the second event arrives — a re-render later is too late.
  const inFlightRef = useRef(false);

  // ── The preview leg's own state ───────────────────────────────────────────
  // The render, stamped with everything that has to still be true for it to be
  // shown: the document, the scene OBJECT (ruling R-D13's identity anchor), and
  // the `(format, scale)` key it was rendered at.
  const [preview, setPreview] = useState<{
    forDocumentId: string;
    forScene: Scene;
    forKey: string;
    dataUrl: string;
  } | null>(null);
  // What the menu is asking to see RIGHT NOW, set synchronously by
  // `requestExportPreview`. Without it, flipping PNG→SVG would keep the PNG on
  // screen until the SVG came back — an image labelled as a format it is not.
  // Mirrored onto a ref at the same instant because a resolving export has to
  // read it from inside its own closure, where the state value is the one
  // captured at request time.
  const [requestedKey, setRequestedKey] = useState<string | null>(null);
  const requestedKeyRef = useRef<string | null>(null);

  // Every render this scene has already produced, so reopening the region or
  // flipping back to a format the user already looked at costs nothing. A ref:
  // it is read inside the request and is never itself rendered, so writing it
  // must not schedule one.
  const previewCacheRef = useRef<SceneExportPreviewCache | null>(null);
  // Coalescing, not refusal: the keys whose export is in flight. A second
  // request for the SAME key while it runs is a no-op (the answer is already
  // coming), while a request for a DIFFERENT key runs — the user flipping
  // format while a render is outstanding must get the format they flipped to,
  // not silence. Bounded by the key space (3 formats x 4 scales).
  //
  // ANCHORED to the same `(document, scene)` pair as the cache (review finding
  // 1), and this is load-bearing rather than symmetry for its own sake. Keyed on
  // `"FORMAT:scale"` alone, the guard swallowed the one request that most needed
  // to run: with a PNG@2x export in flight against scene S1, a write mirrors up
  // S2, the user reopens the region — the cache correctly misses, but the guard
  // saw `"PNG:2"` in flight and returned, so nothing re-requested, while the S1
  // export it deferred to was already destined for the discard path below. The
  // region then sat blank with no export pending. An export started against
  // moved-on anchors can satisfy nobody, so it must not be something a live
  // request can coalesce onto.
  const previewInFlightRef = useRef<{
    forDocumentId: string;
    forScene: Scene;
    keys: Set<string>;
  } | null>(null);

  // DERIVED, like every other stamped value here. `null` unless the render is of
  // this document, of the live scene object, AND of the settings the menu is
  // showing — which is what makes "the document moved on" and "the user flipped
  // format" both resolve to the designed empty region rather than to a picture
  // that is no longer the answer to anything. The render MODE is resolved in the
  // same breath, so the fourth way there is nothing true to show — a payload
  // neither element can host — lands in the same `null`.
  const previewMode = preview ? previewRenderMode(preview.dataUrl) : null;
  const exportPreview =
    preview &&
    previewMode &&
    documentId !== null &&
    scene !== null &&
    // The SHARED predicate, not a hand-rolled repeat of it (final review,
    // finding 4) — its whole purpose is that the cache lookup, the cache store,
    // the in-flight registry and this display gate cannot disagree about what
    // "same document, same scene" means.
    previewAnchorsMatch(preview, documentId, scene) &&
    preview.forKey === requestedKey
      ? { dataUrl: preview.dataUrl, mode: previewMode }
      : null;

  const requestExportPreview = useCallback(
    (format: ImageExportFormat, scale: ImageExportScale) => {
      const armedDocumentId = documentIdRef.current;
      const armedScene = sceneRef.current;
      const key = previewCacheKey(format, sceneExportScaleMultiplier(scale));
      // Nothing to render yet. Silent, unlike the download's refusal: the user
      // pressed nothing — the region opened, or the format changed — so there
      // is no action to report the outcome of, and the empty region already
      // says what there is to say.
      if (!armedDocumentId || !armedScene) return;

      requestedKeyRef.current = key;
      setRequestedKey(key);

      const cached = previewCacheLookup(
        previewCacheRef.current,
        armedDocumentId,
        armedScene,
        key,
      );
      if (cached !== null) {
        setPreview({
          forDocumentId: armedDocumentId,
          forScene: armedScene,
          forKey: key,
          dataUrl: cached,
        });
        return;
      }
      // A GENERATION per anchor pair. When the anchors move, the outstanding
      // exports keep running (nothing can cancel a fetch already sent) but they
      // are left behind in the old generation, so they neither block nor are
      // blocked by requests against the live scene. Each closure below holds a
      // reference to the generation it registered in, so a doomed export's
      // `finally` retires its OWN key and can never clear the live generation's
      // entry for the same key.
      let inFlight = previewInFlightRef.current;
      if (!previewAnchorsMatch(inFlight, armedDocumentId, armedScene)) {
        inFlight = {
          forDocumentId: armedDocumentId,
          forScene: armedScene,
          keys: new Set(),
        };
        previewInFlightRef.current = inFlight;
      }
      if (inFlight.keys.has(key)) return;

      void (async () => {
        // Same shape as the download leg's: raised before the first `await` (an
        // async body runs synchronously to there, so a duplicate request in the
        // same tick still coalesces) and cleared in `finally`, so a throw from
        // `designBffConfig` or `createApiExportRunner` cannot wedge the key
        // permanently un-previewable.
        inFlight.keys.add(key);
        try {
          const config = designBffConfig();
          const runExport = createApiExportRunner({
            apiBaseUrl: config.apiBaseUrl,
            documentId: armedDocumentId,
            fetchImpl: config.fetchImpl,
          });
          // R-D19, and the preview leg needs it MORE than the download does:
          // an unwaited render is not just shown stale, it is CACHED under the
          // post-edit scene anchor, which poisons that key until the scene
          // object next changes. The revalidation below still runs after.
          await awaitWritesSettledRef.current?.(armedDocumentId);
          const result = await runExport({
            scene: armedScene,
            profile: sceneExportProfile(format, sceneExportScaleMultiplier(scale)),
            pageIds: pageIdRef.current ? [pageIdRef.current] : [],
            documentId: armedDocumentId,
          });
          // Post-await revalidation, and it is the whole reason this leg is safe:
          // an export takes seconds, in which the user can switch artifacts and
          // the agent or the inspector can commit a write that mirrors up a NEW
          // scene. A render of a scene the document no longer holds is not shown
          // and — the part that matters — not CACHED either, or it would be
          // served again later under an anchor it was never true of.
          if (
            documentIdRef.current !== armedDocumentId ||
            sceneRef.current !== armedScene
          ) {
            return;
          }
          if (result.status !== "ok") {
            report(sceneExportResultMessage(format, result), true);
            return;
          }
          // §1.11 exports ONE artboard, so `artifacts[0]` is the deliverable.
          const dataUrl = result.artifacts[0]?.data_url ?? null;
          if (!dataUrl) {
            report(`${format} export returned no file`, true);
            return;
          }
          previewCacheRef.current = previewCacheStore(
            previewCacheRef.current,
            armedDocumentId,
            armedScene,
            key,
            dataUrl,
          );
          // CACHED unconditionally above, DISPLAYED only if it is still what the
          // menu is asking for. The two concurrent-export orderings are why this
          // is a guard and not just the derivation: flip PNG→SVG while the PNG
          // runs and both exports are live, so whichever resolves LAST would
          // otherwise take the one preview slot. Without this the late SVG
          // overwrites a correct, on-screen PNG and the region blanks out — not
          // a stale image (the derivation still refuses to draw it), but a right
          // one disappearing for no reason the user can see. The SVG is in the
          // cache either way, so flipping to it is instant.
          if (requestedKeyRef.current !== key) return;
          setPreview({
            forDocumentId: armedDocumentId,
            forScene: armedScene,
            forKey: key,
            dataUrl,
          });
        } catch (cause) {
          if (
            documentIdRef.current !== armedDocumentId ||
            sceneRef.current !== armedScene
          ) {
            return;
          }
          report(cause instanceof Error ? cause.message : String(cause), true);
        } finally {
          inFlight.keys.delete(key);
        }
      })();
    },
    [report],
  );

  // ARMED UNCONDITIONALLY, and deliberately not on `documentId` (review fix,
  // finding 1). Arming on it made the "No document to export" refusal below
  // dead code for the one case it names: during the pre-load window there was
  // no listener at all, so pressing Export produced no export AND no refusal,
  // leaving the span announcing the controller's optimistic "PNG export
  // requested at 1x" — an announcement of something that did not happen, which
  // is precisely what R-D7 exists to prevent. Every live value already rides a
  // ref, so there is nothing for the effect to depend on: it arms once per
  // mount and the guards inside answer for whatever state the session is in.
  // (`report` is the one name in the dependency list, and it is a
  // `useCallback([])` — permanently the same function, so this is still an
  // arms-once effect. It was hoisted out of the body at step 3 so the preview
  // leg speaks through the same stamped status line.)
  useEffect(() => {
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
        report("No document to export", true);
        return;
      }
      if (inFlightRef.current) {
        report("Export already in progress", true);
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
          // R-D19: the file must contain the edit the user just made. The
          // server renders its PERSISTED copy, and this lane's writes land
          // optimistically on a chained promise, so without this wait an export
          // fired inside that window downloads the PRE-edit document and
          // announces "PNG exported" over it. Bounded — the proof is at
          // `use-scene-manual-edits.ts`'s `awaitWritesSettled`.
          await awaitWritesSettledRef.current?.(armedDocumentId);
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
            report("Export cancelled — document changed", true);
            return;
          }
          if (result.status !== "ok") {
            report(sceneExportResultMessage(request.format, result), true);
            return;
          }
          // §1.11 exports ONE artboard, so `artifacts[0]` is the deliverable.
          if (!downloadDataUrl(result.artifacts[0]?.data_url ?? null, filename)) {
            // An "ok" carrying no bytes is not a success the user can use, and
            // announcing one would be this lane's signature defect: the panel
            // stating something that did not happen.
            report(`${request.format} export returned no file`, true);
            return;
          }
          report(sceneExportResultMessage(request.format, result));
        } catch (cause) {
          // A transport throw (the runner's non-2xx, an offline fetch) is the
          // user's answer too — never an unhandled rejection.
          if (documentIdRef.current !== armedDocumentId) {
            report("Export cancelled — document changed", true);
            return;
          }
          report(cause instanceof Error ? cause.message : String(cause), true);
        } finally {
          inFlightRef.current = false;
        }
      })();
    };
    window.addEventListener("clue:artifact-export-request", onExportRequest);
    return () =>
      window.removeEventListener("clue:artifact-export-request", onExportRequest);
  }, [report]);

  return { exportPreview, exportStatus, requestExportPreview };
}
