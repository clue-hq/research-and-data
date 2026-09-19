"use client";

import { useEffect, useMemo, useRef, useState, useSyncExternalStore } from "react";
import { textMeasurementSignature } from "../adapter/scene-canvas-view";
import { designBffConfig } from "../data/design-bff";
import { loadCanvasKit } from "../engine/scene/canvaskit/loadCanvasKit";
import {
  injectSkiaMeasurements,
  skiaLineMeasurements,
  skiaRequestedMeasurements,
  skiaMeasurements,
} from "../engine/scene/canvaskit/skiaMeasurements";
import type { RenderContext } from "../engine/scene/renderContext";
import type { Diagnostic, PageId, Scene } from "../engine/scene/contracts";
import { fetchDocument } from "../engine/scene/documentStore";
import { loadKitFontFaces } from "../engine/scene/kitFonts";
import { loadLibraryFontFaces } from "../engine/scene/libraryFonts";
import {
  notifyKitFontsChanged,
  setKitTokenMaps,
  subscribeTokenColors,
  tokenColorsGenerationSnapshot,
} from "../engine/scene/renderAdapter";
import { firstPageId } from "../engine/scene/sceneQueries";
import {
  buildKitTokenMaps,
} from "../engine/scene/tokenColors";
import {
  WasmEngine,
  activateWasmCore,
  type WasmCoreActivation,
} from "../engine/scene/wasmEngine";

/**
 * AD2.3: one scene document, loaded and made renderable.
 *
 * The canvas component may not reach the transport itself (presentation
 * components are lint-barred from `data/`), and the load sequence is a
 * data/engine concern in any case, so it lives here — the same split the
 * website lane uses between `use-web-render` and `WebArtifactCanvas`. AD2.7's
 * `useSceneEditingSession` will own this leg once selection, layers and writes
 * join it; until then this hook is exactly the read path:
 *
 *  1. the **stamp handshake first** (D9): `activateWasmCore` compares the
 *     vendored wasm module's `{schema_version, engine_commit}` against the
 *     design API's `/build-info` THROUGH the BFF. Unavailable — module
 *     missing, API unreachable, versions apart — means no engine, and the
 *     scene renders as the server's own read-only snapshot. Never a silent
 *     pretence that editing is live: the reason and detail go to the console
 *     AND, since Gate G-D (founder, 2026-08-21), to the canvas's own banner in
 *     the MVP editor's words — the same `reason`/`detail` pair drives both.
 *  2. the document fetch through `designBffConfig()`.
 *  3. the brand kit's token maps + font faces, then the curated library faces
 *     the scene references — both async, both re-rendering through the
 *     renderAdapter's token generation when they land.
 *  4. the C4 measure-then-inject pass: SkParagraph metrics into the engine,
 *     then adopt the relaid scene.
 *
 * Ported from `EditorApp.tsx:590-672` (the kit + library font legs) and
 * `CanvasKitCanvas.tsx:355-371` (the measurement pass), minus everything that
 * belongs to the design subsystem's own multi-document dev shell.
 */

export type SceneEngineUnavailableReason = Extract<
  WasmCoreActivation,
  { status: "unavailable" }
>["reason"];

export interface SceneEngineStatus {
  /** True when the canvas is showing a server snapshot with no live engine —
   * hit-testing and every future edit are refused rather than faked. */
  engineDisabled: boolean;
  reason: SceneEngineUnavailableReason | null;
  detail: string | null;
}

/**
 * AD3.3: the document's server-side history, as of the load that is on screen.
 *
 * The two depths are the server's own stacks (`documentStore.fetchDocument`
 * parses them from `undo_stack`/`redo_stack`), and `loadGeneration` is what
 * makes them usable: it advances on every COMPLETED load, so a consumer that
 * counts steps taken since a load can tell "the same base I already counted
 * against" from "a fresh authoritative base, start again". Without it, a reload
 * whose depths happen to match the counted ones would be invisible.
 */
export interface SceneDocumentHistory {
  loadGeneration: number;
  undoDepth: number;
  redoDepth: number;
}

export interface SceneDocumentState {
  kind: "loading" | "ready" | "error";
  scene: Scene | null;
  presentationScene: Scene | null;
  engine: WasmEngine | null;
  pageId: PageId | null;
  title: string | null;
  error: string | null;
  engineStatus: SceneEngineStatus;
  /** The loaded document's committed version. */
  currentVersion: number | null;
  /** AD3.3: the loaded document's undo/redo stack depths, and the counter that
   * says when they were last refreshed. See {@link SceneDocumentHistory}. */
  undoDepth: number;
  redoDepth: number;
  loadGeneration: number;
  /** The renderAdapter's kit-token generation: descriptors and text
   * measurements built before the kit lands resolve to skeleton values, so
   * every memo keyed on the scene keys on this too. */
  tokenGeneration: number;
  /** Live renderer-only font failures. Scene/preflight diagnostics cannot
   * carry these because they arise while the browser loads/registers faces. */
  fontDiagnostics: Diagnostic[];
  measurementIncomplete: boolean;
  /** Adopt the engine's current (relaid) scene as the rendered one. */
  refresh: () => void;
}

type LoadState =
  | { kind: "loading" }
  | { kind: "error"; message: string }
  | {
      kind: "ready";
      scene: Scene;
      renderContext: RenderContext | null;
      engine: WasmEngine | null;
      pageId: PageId | null;
      title: string;
      /** AD3.3: carried in the SAME state as the scene, so the depths on screen
       * always belong to the load the scene came from. */
      history: SceneDocumentHistory;
      currentVersion: number | null;
    };

const NO_HISTORY: SceneDocumentHistory = {
  loadGeneration: 0,
  undoDepth: 0,
  redoDepth: 0,
};

const ENGINE_ACTIVE: SceneEngineStatus = {
  engineDisabled: false,
  reason: null,
  detail: null,
};

const NO_DIAGNOSTICS: Diagnostic[] = [];

/**
 * The handshake is a property of this origin's build, not of a document, so it
 * runs once per page load: a reload token or a second artifact must not re-import
 * the wasm module and re-hit `/build-info`. The promise is memoised, never its
 * failure semantics — an `unavailable` activation is a real, reported value.
 */
let activation: Promise<WasmCoreActivation> | null = null;

function activateEngineOnce(): Promise<WasmCoreActivation> {
  const config = designBffConfig();
  activation ??= activateWasmCore({
    apiBaseUrl: config.apiBaseUrl,
    fetchImpl: config.fetchImpl,
  });
  return activation;
}

export function useSceneDocument(
  documentId: string,
  reloadToken = 0,
): SceneDocumentState {
  const [load, setLoad] = useState<LoadState>({ kind: "loading" });
  const [measurementState, setMeasurementState] = useState<{
    engine: WasmEngine; incomplete: boolean;
  } | null>(null);
  const [engineStatus, setEngineStatus] =
    useState<SceneEngineStatus>(ENGINE_ACTIVE);
  const [kitFontDiagnosticState, setKitFontDiagnosticState] = useState<{
    forBrandKitRef: string;
    diagnostics: Diagnostic[];
  } | null>(null);
  const [libraryFontDiagnosticState, setLibraryFontDiagnosticState] = useState<{
    forDocumentId: string;
    diagnostics: Diagnostic[];
  } | null>(null);
  // AD3.3: bumped by each COMPLETED load (the first fetch and every
  // reload-token refetch), never by a failed one — a load that threw brought no
  // new base with it. A ref, because it is read and advanced inside the async
  // load below, and it is the value stamped into that load's state.
  const loadGenerationRef = useRef(0);
  // The kit whose token maps are currently installed in the module-scoped
  // registry (`null` = the deterministic fallback maps). The clears below are
  // guarded on it: a reload-token refetch of the SAME pinned kit must not wipe
  // maps the brand-kit effect (keyed on the pin value) will never re-install.
  const activeLoadRef = useRef(0);

  const tokenGeneration = useSyncExternalStore(
    subscribeTokenColors,
    tokenColorsGenerationSnapshot,
    tokenColorsGenerationSnapshot,
  );

  useEffect(() => {
    let cancelled = false;
    const generation = ++activeLoadRef.current;
    void (async () => {
      const config = designBffConfig();
      // 1. Stamp handshake FIRST — the engine's availability decides whether
      //    the scene is editable at all, so it is never inferred later.
      const activated = await activateEngineOnce();
      if (cancelled) {
        return;
      }
      if (activated.status === "unavailable") {
        console.warn(
          `[clue-design] canvas editing is disabled (${activated.reason}): ${activated.detail}`,
        );
        setEngineStatus({
          engineDisabled: true,
          reason: activated.reason,
          detail: activated.detail,
        });
      } else {
        setEngineStatus(ENGINE_ACTIVE);
      }
      try {
        const loaded = await fetchDocument(config, documentId);
        if (cancelled) {
          return;
        }
        // The engine relays out on construction and adopts the RELAID scene;
        // rendering the raw fetched scene instead would draw geometry the
        // engine disagrees with (the coordinate-model desync).
        const engine =
          activated.status === "active"
            ? new WasmEngine(activated.module, loaded.scene)
            : null;
        engine?.setRenderContext(loaded.renderContext);
        setKitTokenMaps(buildKitTokenMaps(null));
        loadGenerationRef.current += 1;
        setLoad({
          kind: "ready",
          scene: engine ? engine.scene : loaded.scene,
          renderContext: loaded.renderContext,
          engine,
          pageId: firstPageId(engine ? engine.scene : loaded.scene),
          title: loaded.title,
          // AD3.3: the server's own stack depths for THIS load.
          currentVersion: loaded.currentVersion,
          history: {
            loadGeneration: loadGenerationRef.current,
            undoDepth: loaded.undoDepth,
            redoDepth: loaded.redoDepth,
          },
        });
      } catch (error) {
        if (cancelled) {
          return;
        }
        setLoad({
          kind: "error",
          message: error instanceof Error ? error.message : String(error),
        });
      }
    })();
    return () => {
      cancelled = true;
      if (activeLoadRef.current === generation) activeLoadRef.current += 1;
    };
  }, [documentId, reloadToken]);

  const scene = load.kind === "ready" ? load.scene : null;
  const engine = load.kind === "ready" ? load.engine : null;

  const presentationScene = engine?.presentationScene ?? scene;
  const renderContext = load.kind === "ready" ? load.renderContext : null;
  const contextKey = renderContext?.context_key ?? null;
  const derivationStatus = engine?.derivation.status ?? "unavailable";
  const inputRevision = engine?.derivation.input_revision ?? 0;
  const kitFontDiagnostics = contextKey && kitFontDiagnosticState?.forBrandKitRef === contextKey
    ? kitFontDiagnosticState.diagnostics : NO_DIAGNOSTICS;
  useEffect(() => {
    if (!engine || !contextKey || !renderContext || derivationStatus !== "ready") return;
    let cancelled = false;
    const generation = activeLoadRef.current;
    const current = () => !cancelled && activeLoadRef.current === generation
      && engine.derivation.context_key === contextKey && engine.derivation.status === "ready";
    const config = designBffConfig();
    // Palette maps are compatibility data only. Canonical paint already has resolved literals.
    const detail = renderContext.brand_kit;
    setKitTokenMaps(buildKitTokenMaps(detail));
    const diagnostics: Diagnostic[] = [];
    void loadKitFontFaces({ ...config, isCurrent: current, onFaceDiagnostic: d => diagnostics.push(d) }, detail)
      .then(registered => { if (registered && current()) notifyKitFontsChanged(); })
      .catch(error => {
        diagnostics.push({ severity: "error", phase: "brand", code: "EDITOR_KIT_FONT_FAMILY_UNAVAILABLE",
          message: `Selected Brand Kit fonts could not be loaded (${String(error)}).`,
          subject: { kind: "document" }, hint: "Restore the selected kit's font assets." });
      }).finally(() => {
        if (current()) setKitFontDiagnosticState({ forBrandKitRef: contextKey, diagnostics });
      });
    return () => { cancelled = true; };
  }, [contextKey, engine, renderContext, derivationStatus]);

  // Curated font-library leg: register only the faces whose family this scene
  // references. The manifest is module-cached and the face registry dedupes,
  // so a re-run over already-loaded families makes no network calls.
  useEffect(() => {
    if (!presentationScene) return;
    let cancelled = false;
    const generation = activeLoadRef.current;
    const expectedContext = engine?.derivation.context_key;
    const current = () => !cancelled && generation === activeLoadRef.current
      && (!engine || (engine.derivation.context_key === expectedContext && engine.derivation.status === "ready"));
    const config = designBffConfig();
    const diagnostics: Diagnostic[] = [];
    void loadLibraryFontFaces(presentationScene, {
      ...config,
      isCurrent: current,
      onFaceDiagnostic: (diagnostic) => diagnostics.push(diagnostic),
    })
      .then((registered) => {
        if (current()) {
          setLibraryFontDiagnosticState({
            forDocumentId: documentId,
            diagnostics,
          });
        }
        if (registered && current()) {
          notifyKitFontsChanged();
        }
      })
      .catch((error) => {
        if (!current()) {
          return;
        }
        setLibraryFontDiagnosticState({
          forDocumentId: documentId,
          diagnostics: [
            {
              severity: "error",
              phase: "brand",
              code: "EDITOR_FONT_LIBRARY_LOAD_FAILED",
              message: `Font Library loading failed (${error instanceof Error ? error.message : "unexpected failure"}); canvas and server export use deterministic Inter fallback for unavailable families.`,
              subject: { kind: "document" },
              hint: "Restore the Font Library response or its registered assets; the editor will not hide this degradation.",
            },
          ],
        });
      });
    return () => {
      cancelled = true;
    };
  }, [documentId, presentationScene, engine]);

  const libraryFontDiagnostics =
    scene && libraryFontDiagnosticState?.forDocumentId === documentId
      ? libraryFontDiagnosticState.diagnostics
      : NO_DIAGNOSTICS;
  const fontDiagnostics = useMemo(
    () => [...kitFontDiagnostics, ...libraryFontDiagnostics],
    [kitFontDiagnostics, libraryFontDiagnostics],
  );

  // C4 measure-then-inject. The dep is a digest of TEXT MEASUREMENT INPUTS
  // only — never the whole scene: `setMeasurements` relayouts and hands back a
  // new scene, so a scene-keyed effect would loop forever.
  const textSignature = useMemo(
    () => (presentationScene ? `${contextKey}:${textMeasurementSignature(presentationScene, tokenGeneration)}` : ""),
    [presentationScene, contextKey, tokenGeneration],
  );
  useEffect(() => {
    if (!engine || !textSignature || engine.derivation.status !== "ready") {
      return;
    }
    let cancelled = false;
    const revision = engine.derivation.input_revision;
    const generation = activeLoadRef.current;
    void loadCanvasKit().then((bundle) => {
      if (cancelled || generation !== activeLoadRef.current || revision !== engine.derivation.input_revision || !bundle?.fontProvider) {
        return;
      }
      // Bound once: the narrowing above does not reach inside the pass
      // closures below.
      const { ck, fontProvider } = bundle;
      // Pass 1 (Wave 3 C4): unconstrained extents, so hug boxes take Skia's
      // size. Pass 2 (Plan 4 item F): the line boxes, keyed on the boxes pass
      // 1 solved. It ITERATES because the line records move boxes themselves
      // — the taffy-keyed record gives a wrapped hug box CanvasKit's height,
      // which the validate-keyed record from the same round has already
      // named at its old value — so the pass re-runs until the solved sizes
      // stop changing (bounded; see `injectSkiaMeasurements`). The effect's
      // own signature includes those sizes, so its outer re-run then finds
      // nothing left to change.
      const measured = injectSkiaMeasurements(engine, {
        unconstrained: (scene) => skiaMeasurements(ck, fontProvider, scene),
        lines: (scene) => skiaLineMeasurements(ck, fontProvider, scene),
        requests: (scene, requests) => skiaRequestedMeasurements(ck, fontProvider, scene, requests),
      });
      if (!cancelled) {
        setMeasurementState({ engine, incomplete: !measured.converged });
        setLoad((current) =>
          current.kind === "ready" && current.engine === engine
            ? { ...current, scene: engine.scene }
            : current,
        );
      }
    });
    return () => {
      cancelled = true;
    };
  }, [engine, textSignature, inputRevision]);

  return useMemo<SceneDocumentState>(() => {
    // Before the first load there is no history to report, and zero depths are
    // the honest answer: they disable the history controls rather than offering
    // a step against a document nobody has read yet.
    const history = load.kind === "ready" ? load.history : NO_HISTORY;
    return {
      kind: load.kind,
      scene,
      presentationScene,
      engine,
      pageId: load.kind === "ready" ? load.pageId : null,
      title: load.kind === "ready" ? load.title : null,
      error: load.kind === "error" ? load.message : null,
      engineStatus,
      currentVersion: load.kind === "ready" ? load.currentVersion : null,
      loadGeneration: history.loadGeneration,
      redoDepth: history.redoDepth,
      undoDepth: history.undoDepth,
      tokenGeneration,
      fontDiagnostics,
      measurementIncomplete: measurementState?.engine === engine && measurementState.incomplete,
      refresh: () => {
        setLoad((current) =>
          current.kind === "ready" && current.engine
            ? { ...current, scene: current.engine.scene }
            : current,
        );
      },
    };
  }, [engine, engineStatus, fontDiagnostics, load, measurementState, scene, presentationScene, tokenGeneration]);
}
