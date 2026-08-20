"use client";

import { useEffect, useMemo, useState, useSyncExternalStore } from "react";
import { textMeasurementSignature } from "../adapter/scene-canvas-view";
import { designBffConfig } from "../data/design-bff";
import { loadCanvasKit } from "../engine/scene/canvaskit/loadCanvasKit";
import { skiaMeasurements } from "../engine/scene/canvaskit/skiaMeasurements";
import type { PageId, Scene } from "../engine/scene/contracts";
import { fetchBrandKitDetail, fetchDocument } from "../engine/scene/documentStore";
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
  PLATFORM_DEFAULT_BRAND_KIT_ID,
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

export interface SceneDocumentState {
  kind: "loading" | "ready" | "error";
  scene: Scene | null;
  engine: WasmEngine | null;
  pageId: PageId | null;
  title: string | null;
  error: string | null;
  engineStatus: SceneEngineStatus;
  /** The renderAdapter's kit-token generation: descriptors and text
   * measurements built before the kit lands resolve to skeleton values, so
   * every memo keyed on the scene keys on this too. */
  tokenGeneration: number;
  /** Adopt the engine's current (relaid) scene as the rendered one. */
  refresh: () => void;
}

type LoadState =
  | { kind: "loading" }
  | { kind: "error"; message: string }
  | {
      kind: "ready";
      scene: Scene;
      engine: WasmEngine | null;
      pageId: PageId | null;
      title: string;
    };

const ENGINE_ACTIVE: SceneEngineStatus = {
  engineDisabled: false,
  reason: null,
  detail: null,
};

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
  const [engineStatus, setEngineStatus] =
    useState<SceneEngineStatus>(ENGINE_ACTIVE);

  const tokenGeneration = useSyncExternalStore(
    subscribeTokenColors,
    tokenColorsGenerationSnapshot,
    tokenColorsGenerationSnapshot,
  );

  useEffect(() => {
    let cancelled = false;
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
        setLoad({
          kind: "ready",
          scene: engine ? engine.scene : loaded.scene,
          engine,
          pageId: firstPageId(engine ? engine.scene : loaded.scene),
          title: loaded.title,
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
    };
  }, [documentId, reloadToken]);

  const scene = load.kind === "ready" ? load.scene : null;
  const engine = load.kind === "ready" ? load.engine : null;

  // Brand kit leg. Keyed on the ref's VALUE (`id@version`), never the object:
  // `scene.meta.brand_kit` gets a fresh identity on every scene update, and an
  // object-keyed dep re-fetched the same kit thousands of times per turn in the
  // source shell. A failed fetch leaves the previous map (or none) in place —
  // the canvas falls back to the pre-kit heuristic rather than blocking.
  const brandKitRefKey = scene
    ? `${scene.meta.brand_kit?.id ?? PLATFORM_DEFAULT_BRAND_KIT_ID}@${
        scene.meta.brand_kit?.version ?? ""
      }`
    : null;
  useEffect(() => {
    if (!brandKitRefKey) {
      return;
    }
    let cancelled = false;
    const config = designBffConfig();
    const brandKitId = brandKitRefKey.slice(0, brandKitRefKey.lastIndexOf("@"));
    void (async () => {
      try {
        const detail = await fetchBrandKitDetail(config, brandKitId);
        if (cancelled) {
          return;
        }
        // Colors + type roles + numbers in one install, so paint, text
        // measurement and radii all resolve from the kit.
        setKitTokenMaps(buildKitTokenMaps(detail));
        const registered = await loadKitFontFaces(config, detail);
        if (registered && !cancelled) {
          notifyKitFontsChanged();
        }
      } catch {
        // API down or kit gone: keep whatever map the canvas already had.
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [brandKitRefKey]);

  // Curated font-library leg: register only the faces whose family this scene
  // references. The manifest is module-cached and the face registry dedupes,
  // so a re-run over already-loaded families makes no network calls.
  useEffect(() => {
    if (!scene) {
      return;
    }
    let cancelled = false;
    const config = designBffConfig();
    void loadLibraryFontFaces(scene, config)
      .then((registered) => {
        if (registered && !cancelled) {
          notifyKitFontsChanged();
        }
      })
      .catch(() => {
        // API down: leave the canvas on the fonts it already has.
      });
    return () => {
      cancelled = true;
    };
  }, [scene]);

  // C4 measure-then-inject. The dep is a digest of TEXT MEASUREMENT INPUTS
  // only — never the whole scene: `setMeasurements` relayouts and hands back a
  // new scene, so a scene-keyed effect would loop forever.
  const textSignature = useMemo(
    () => (scene ? textMeasurementSignature(scene, tokenGeneration) : ""),
    [scene, tokenGeneration],
  );
  useEffect(() => {
    if (!engine || !textSignature) {
      return;
    }
    let cancelled = false;
    void loadCanvasKit().then((bundle) => {
      if (cancelled || !bundle?.fontProvider) {
        return;
      }
      engine.setMeasurements(
        skiaMeasurements(bundle.ck, bundle.fontProvider, engine.scene),
      );
      if (!cancelled) {
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
  }, [engine, textSignature]);

  return useMemo<SceneDocumentState>(() => {
    return {
      kind: load.kind,
      scene,
      engine,
      pageId: load.kind === "ready" ? load.pageId : null,
      title: load.kind === "ready" ? load.title : null,
      error: load.kind === "error" ? load.message : null,
      engineStatus,
      tokenGeneration,
      refresh: () => {
        setLoad((current) =>
          current.kind === "ready" && current.engine
            ? { ...current, scene: current.engine.scene }
            : current,
        );
      },
    };
  }, [engine, engineStatus, load, scene, tokenGeneration]);
}
