"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  composeAssetLibrary,
  filterAssetLibrary,
  kitLibraryEntries,
  type AssetLibraryCategory,
} from "@/features/design-editor/adapter/scene-asset-library";
import type { SceneImageAiBinding } from "@/features/design-editor/adapter/scene-image-ai";
import { listImageAssets, uploadWebAsset } from "@/features/design-editor/data/assets";
import { DESIGN_API_BFF_PREFIX } from "@/features/design-editor/data/design-bff";
import type { AssetRecord } from "@/features/design-editor/engine/scene/contracts";
import type { SceneAssetLibraryBinding } from "@/features/design-editor/hooks/use-scene-asset-library";
import { editSceneAsset, generateSceneAsset } from "@/features/design-editor/hooks/use-scene-image-ai";
import {
  EMPTY_SITE_IMAGE_AI,
  SITE_IMAGE_NOT_SAVED,
  appAssetSrc,
  assetIdForUrl,
  assetStoreUrlOf,
  createSiteImageAiRunner,
  siteImageAiBinding,
  type SiteImageAiDeps,
  type SiteImageAiRunner,
  type SiteImageAiState,
  type SiteImageTarget,
} from "./site-images.logic";

const ASSET_GONE = "That image is no longer in the library.";

export interface SiteImageFieldBinding {
  ai: SceneImageAiBinding;
  onFileSelect: (file: File) => Promise<void>;
  onOpenLibrary: () => void;
  previewSrc: string;
}

export interface SiteImages {
  field: (target: SiteImageTarget, value: string) => SiteImageFieldBinding;
  library: SceneAssetLibraryBinding | null;
  openLibraryFor: (target: SiteImageTarget) => void;
  uploadToLibraryTarget: (file: File) => Promise<void>;
}

/** The site lane's asset library binding (the ad lane's panel, unchanged) and its upload and AI
 * paths. Every path ends in `place(target, url)` — the session's insert_asset + save. */
export function useSiteImages({
  clearMessages,
  currentUrl,
  documentId,
  imagesVisible,
  kit,
  onError,
  place,
  writable,
}: {
  clearMessages: () => void;
  currentUrl: (target: SiteImageTarget) => string;
  documentId: string | null;
  /** The dock is showing an image field: load the registry so Edit can find the source asset. */
  imagesVisible: boolean;
  kit: unknown;
  onError: (message: string) => void;
  place: (target: SiteImageTarget, url: string) => boolean;
  writable: () => boolean;
}): SiteImages {
  const [libraryTarget, setLibraryTarget] = useState<(SiteImageTarget & { documentId: string }) | null>(null);
  const [registry, setRegistry] = useState<AssetRecord[]>([]);
  const [registryLoaded, setRegistryLoaded] = useState(false);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [query, setQuery] = useState("");
  const [category, setCategory] = useState<AssetLibraryCategory | "all">("all");
  const [ai, setAi] = useState(EMPTY_SITE_IMAGE_AI);

  const latest = useRef({ clearMessages, currentUrl, documentId, libraryTarget, onError, place, registry, writable });
  useEffect(() => {
    latest.current = { clearMessages, currentUrl, documentId, libraryTarget, onError, place, registry, writable };
  });

  const generation = useRef(0);
  const refresh = useCallback(() => {
    const run = ++generation.current;
    setLoading(true);
    setError(null);
    void listImageAssets()
      .then((records) => {
        if (run !== generation.current) return;
        setRegistry(records as unknown as AssetRecord[]);
        setRegistryLoaded(true);
      })
      .catch((cause: unknown) => {
        if (run === generation.current) setError(cause instanceof Error ? cause.message : String(cause));
      })
      .finally(() => {
        if (run === generation.current) setLoading(false);
      });
  }, []);
  useEffect(() => {
    if (!imagesVisible || !documentId || registryLoaded) return;
    // A microtask later, not in the effect body: react-hooks/set-state-in-effect forbids the
    // synchronous call (the session's idiom). A re-run before it fires cancels it and decides again.
    let cancelled = false;
    queueMicrotask(() => {
      if (!cancelled) refresh();
    });
    return () => {
      cancelled = true;
    };
  }, [documentId, imagesVisible, refresh, registryLoaded]);

  const lastTarget = useRef<SiteImageTarget | null>(null);
  const openLibraryFor = useCallback(
    (target: SiteImageTarget) => {
      if (!documentId) return;
      lastTarget.current = target;
      setQuery("");
      setCategory("all");
      setLibraryTarget({ ...target, documentId });
      refresh();
    },
    [documentId, refresh],
  );
  const isOpen = libraryTarget !== null && libraryTarget.documentId === documentId;
  const kitEntries = useMemo(() => kitLibraryEntries(kit), [kit]);
  const inUseAssetId = isOpen && libraryTarget ? assetIdForUrl(registry, currentUrl(libraryTarget)) : null;
  const items = useMemo(
    () => filterAssetLibrary(composeAssetLibrary({ inUseAssetId, kitEntries, registry }), { category, query }),
    [category, inUseAssetId, kitEntries, query, registry],
  );

  const placeFile = useCallback(async (target: SiteImageTarget, file: File) => {
    const now = latest.current;
    if (!now.writable()) throw new Error("not writable");
    let url: string | null;
    try {
      url = assetStoreUrlOf(await uploadWebAsset(file));
    } catch (cause) {
      now.onError(cause instanceof Error ? cause.message : String(cause));
      throw cause;
    }
    if (!url) {
      now.onError(SITE_IMAGE_NOT_SAVED);
      throw new Error(SITE_IMAGE_NOT_SAVED);
    }
    if (!latest.current.place(target, url)) throw new Error("not placed");
  }, []);

  const pick = useCallback((assetId: string) => {
    const now = latest.current;
    const target = now.libraryTarget;
    if (!target || target.documentId !== now.documentId || !now.writable()) return;
    const record = now.registry.find((candidate) => candidate.id === assetId);
    if (!record) {
      now.onError(ASSET_GONE);
      return;
    }
    const url = assetStoreUrlOf(record);
    if (!url) {
      now.onError(SITE_IMAGE_NOT_SAVED);
      return;
    }
    if (now.place(target, url)) setLibraryTarget(null);
  }, []);

  const uploadToLibraryTarget = useCallback(
    async (file: File) => {
      const target = latest.current.libraryTarget;
      if (!target) return;
      await placeFile(target, file);
      refresh();
    },
    [placeFile, refresh],
  );

  // A stable publisher rather than the raw setter, so the dependency-less effect below carries no
  // `setState` identifier (the precedent is use-scene-image-ai.ts).
  const publishAi = useCallback((next: SiteImageAiState) => setAi(next), []);
  const aiDeps = useRef<SiteImageAiDeps | null>(null);
  useEffect(() => {
    aiDeps.current = {
      clearMessages,
      currentUrl,
      documentId,
      edit: editSceneAsset,
      generate: generateSceneAsset,
      onError,
      place,
      publish: publishAi,
      sourceAssetId: (url) => assetIdForUrl(latest.current.registry, url),
      writable,
    };
  });
  // Built on first use rather than during render: the runner closes over the deps ref, and this
  // repo's react-hooks/refs rule forbids handing a ref to a function at render time (the precedent
  // is use-scene-image-ai.ts). One runner per mount keeps the staged candidate.
  const runnerRef = useRef<SiteImageAiRunner | null>(null);
  const runnerOf = useCallback(() => {
    runnerRef.current ??= createSiteImageAiRunner(() => {
      if (!aiDeps.current) throw new Error("site image deps read before the first render committed");
      return aiDeps.current;
    });
    return runnerRef.current;
  }, []);
  const runner = useMemo<SiteImageAiRunner>(
    () => ({
      accept: (target) => runnerOf().accept(target),
      edit: (target, instruction, transparentBackground) => runnerOf().edit(target, instruction, transparentBackground),
      generate: (target, prompt) => runnerOf().generate(target, prompt),
      reject: () => runnerOf().reject(),
      saveAsNew: () => runnerOf().saveAsNew(),
    }),
    [runnerOf],
  );

  const field = useCallback(
    (target: SiteImageTarget, value: string): SiteImageFieldBinding => ({
      ai: siteImageAiBinding({ ai, canEdit: assetIdForUrl(registry, value) !== null, documentId, runner, target, url: value }),
      onFileSelect: (file) => placeFile(target, file),
      onOpenLibrary: () => openLibraryFor(target),
      previewSrc: appAssetSrc(value),
    }),
    [ai, documentId, openLibraryFor, placeFile, registry, runner],
  );

  const library: SceneAssetLibraryBinding | null = documentId
    ? {
        category,
        close: () => setLibraryTarget(null),
        error,
        isOpen,
        items,
        loading,
        open: () => {
          if (lastTarget.current) openLibraryFor(lastTarget.current);
        },
        pick,
        query,
        refresh,
        setCategory,
        setQuery,
        thumbnailUrl: (record) => `${DESIGN_API_BFF_PREFIX}/assets/${encodeURIComponent(record.id)}/bytes`,
      }
    : null;

  return { field, library, openLibraryFor, uploadToLibraryTarget };
}
