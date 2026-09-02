"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  sceneImagePlacementOperations,
  sceneImageReplacementTarget,
} from "../adapter/scene-apply";
import {
  composeAssetLibrary,
  filterAssetLibrary,
  type AssetLibraryCategory,
  type AssetLibraryItem,
  type KitLibraryEntry,
} from "../adapter/scene-asset-library";
import { listImageAssets } from "../data/assets";
import { DESIGN_API_BFF_PREFIX } from "../data/design-bff";
import type { AssetRecord, Node, Operation } from "../engine/scene/contracts";
import {
  NOT_ACCEPTING_EDITS,
  NOT_AN_IMAGE_TARGET,
  SAME_IMAGE_IN_USE,
} from "./use-scene-replace-image";

/**
 * The asset-library picker's binding (spec §4.1–4.3). The ONE decision it does not own is the
 * placement: `pick` is the Replace-image upload flow with the upload removed — the same adapter
 * gate and the same `upsert_asset` + `place_asset_in_node` batch, so a pick and an upload are
 * indistinguishable in the document's history (one undo frame each, founder ruling R-E).
 */

export const LIBRARY_PICK_INTENT = "inspector: replace image from library";
const ASSET_GONE = "That image is no longer in the library.";

export interface SceneAssetLibraryDeps {
  applyOps: (operations: Operation[], intent?: string) => boolean;
  canApply: () => boolean;
  documentId: string | null;
  node: Node | null;
  onError: (message: string) => void;
}

/** Pure: guards in the replace path's order, then one batch or one sentence. Returns whether the
 * engine took the batch. */
export function createSceneAssetLibraryPick(
  readDeps: () => SceneAssetLibraryDeps,
  findRecord: (assetId: string) => AssetRecord | null,
): (assetId: string) => boolean {
  return (assetId) => {
    const deps = readDeps();
    if (!deps.documentId || !deps.canApply()) {
      deps.onError(NOT_ACCEPTING_EDITS);
      return false;
    }
    if (!deps.node || !sceneImageReplacementTarget(deps.node)) {
      deps.onError(NOT_AN_IMAGE_TARGET);
      return false;
    }
    const record = findRecord(assetId);
    if (!record) {
      deps.onError(ASSET_GONE);
      return false;
    }
    const operations = sceneImagePlacementOperations(deps.node, record);
    if (!operations) {
      deps.onError(SAME_IMAGE_IN_USE);
      return false;
    }
    return deps.applyOps(operations, LIBRARY_PICK_INTENT);
  };
}

export interface SceneAssetLibraryBinding {
  isOpen: boolean;
  open: () => void;
  close: () => void;
  items: AssetLibraryItem[];
  loading: boolean;
  error: string | null;
  query: string;
  setQuery: (query: string) => void;
  category: AssetLibraryCategory | "all";
  setCategory: (category: AssetLibraryCategory | "all") => void;
  pick: (assetId: string) => void;
  refresh: () => void;
  thumbnailUrl: (record: AssetRecord) => string;
}

export function useSceneAssetLibrary(options: SceneAssetLibraryDeps & {
  kitEntries: readonly KitLibraryEntry[];
  list?: () => Promise<AssetRecord[]>;
}): SceneAssetLibraryBinding {
  const { applyOps, canApply, documentId, kitEntries, list = listImageAssets, node, onError } = options;
  // The document this picker was opened for, STAMPED and DERIVED rather than
  // reset in an effect (`react-hooks/set-state-in-effect` forbids the effect
  // form, and the session stamps everything that must not survive an artifact
  // switch for the same reason): switching ads closes the picker by
  // construction, so it can never stay open over a document it cannot write to.
  const [openFor, setOpenFor] = useState<string | null>(null);
  const isOpen = openFor !== null && openFor === documentId;
  const [registry, setRegistry] = useState<AssetRecord[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [query, setQuery] = useState("");
  const [category, setCategory] = useState<AssetLibraryCategory | "all">("all");

  // Latest-value ref, written in a passive effect (this repo's react-hooks rule).
  const depsRef = useRef<SceneAssetLibraryDeps>({ applyOps, canApply, documentId, node, onError });
  useEffect(() => {
    depsRef.current = { applyOps, canApply, documentId, node, onError };
  });
  const registryRef = useRef(registry);
  useEffect(() => { registryRef.current = registry; });

  const fetchGeneration = useRef(0);
  const refresh = useCallback(() => {
    const generation = ++fetchGeneration.current;
    setLoading(true);
    setError(null);
    void list()
      .then((records) => { if (generation === fetchGeneration.current) setRegistry(records); })
      .catch((cause: unknown) => {
        if (generation !== fetchGeneration.current) return;
        setError(cause instanceof Error ? cause.message : String(cause));
      })
      .finally(() => { if (generation === fetchGeneration.current) setLoading(false); });
  }, [list]);

  // Fetch on OPEN, never on mount — the picker is rare and the registry is not small. Opening also
  // RESETS the two tools (spec R-D: search and the type filter are the panel's own, fresh each
  // time) — persisting them meant reopening after a search showed a filtered grid with the "In use"
  // tile hidden, which reads as a broken library rather than a live filter.
  const open = useCallback(() => {
    setQuery("");
    setCategory("all");
    setOpenFor(documentId);
    refresh();
  }, [documentId, refresh]);
  const close = useCallback(() => setOpenFor(null), []);

  const inUseAssetId = node?.kind.kind === "image" ? node.kind.asset_id : null;
  const items = useMemo(
    () => filterAssetLibrary(composeAssetLibrary({ registry, kitEntries, inUseAssetId }), { query, category }),
    [category, inUseAssetId, kitEntries, query, registry],
  );

  const pickRef = useRef<((assetId: string) => boolean) | null>(null);
  const pick = useCallback((assetId: string) => {
    pickRef.current ??= createSceneAssetLibraryPick(
      () => depsRef.current,
      (id) => registryRef.current.find((record) => record.id === id) ?? null,
    );
    pickRef.current(assetId);
  }, []);

  const thumbnailUrl = useCallback(
    (record: AssetRecord) => `${DESIGN_API_BFF_PREFIX}/assets/${encodeURIComponent(record.id)}/bytes`,
    [],
  );

  return { category, close, error, isOpen, items, loading, open, pick, query, refresh, setCategory, setQuery, thumbnailUrl };
}
