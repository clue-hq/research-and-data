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
import {
  listImageAssets,
  saveSearchedLogo,
  searchLogos,
  type LogoSearchResponse,
  type LogoSearchResult,
} from "../data/assets";
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

/** The panel's two tabs: the workspace library, and a lookup for any company's logo. */
export type AssetLibraryTab = "library" | "logo-search";

/**
 * The Logo search tab's state (founder request 2026-10-16). A search shows every version the shared
 * lookup found and saves nothing; clicking one saves THAT version and places it through the same
 * batch a library pick uses.
 */
export interface LogoSearchState {
  query: string;
  /** "idle" before the first search; "done" carries `results`, possibly empty. */
  status: "idle" | "searching" | "done";
  /** The query the shown results answer — the empty state names it, not the edited box. */
  searchedFor: string;
  name: string | null;
  results: LogoSearchResult[];
  /** The version being saved and placed, so its tile can say so. */
  savingAssetId: string | null;
  error: string | null;
}

const IDLE_LOGO_SEARCH: LogoSearchState = {
  query: "",
  status: "idle",
  searchedFor: "",
  name: null,
  results: [],
  savingAssetId: null,
  error: null,
};

export interface SceneAssetLibraryBinding {
  tab: AssetLibraryTab;
  setTab: (tab: AssetLibraryTab) => void;
  logoSearch: LogoSearchState;
  setLogoQuery: (query: string) => void;
  searchLogos: () => void;
  pickLogo: (assetId: string) => void;
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
  search?: (url: string) => Promise<LogoSearchResponse>;
  save?: (url: string, assetId: string) => Promise<AssetRecord>;
}): SceneAssetLibraryBinding {
  const {
    applyOps, canApply, documentId, kitEntries, list = listImageAssets, node, onError,
    search = searchLogos, save = saveSearchedLogo,
  } = options;
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
  const [tab, setTab] = useState<AssetLibraryTab>("library");
  const [logoSearch, setLogoSearch] = useState<LogoSearchState>(IDLE_LOGO_SEARCH);

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
    setTab("library");
    setLogoSearch(IDLE_LOGO_SEARCH);
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

  const logoSearchRef = useRef(logoSearch);
  useEffect(() => { logoSearchRef.current = logoSearch; });
  const setLogoQuery = useCallback(
    (value: string) => setLogoSearch((current) => ({ ...current, query: value })),
    [],
  );

  // Only the newest search may write its answer: a slow lookup for the previous company must never
  // replace the results for the one the person typed after it.
  const searchGeneration = useRef(0);
  const runLogoSearch = useCallback(() => {
    const url = logoSearchRef.current.query.trim();
    if (!url) return;
    const generation = ++searchGeneration.current;
    setLogoSearch((current) => ({
      ...current, status: "searching", searchedFor: url, results: [], name: null, error: null,
    }));
    void search(url)
      .then((response) => {
        if (generation !== searchGeneration.current) return;
        setLogoSearch((current) => ({
          ...current, status: "done", name: response.name, results: response.logos,
        }));
      })
      .catch((cause: unknown) => {
        if (generation !== searchGeneration.current) return;
        setLogoSearch((current) => ({
          ...current, status: "idle", error: cause instanceof Error ? cause.message : String(cause),
        }));
      });
  }, [search]);

  const pickLogo = useCallback((assetId: string) => {
    const deps = depsRef.current;
    const current = logoSearchRef.current;
    if (current.savingAssetId) return;
    // The placement's own gates, asked BEFORE the save: a logo that cannot be placed is not saved.
    if (!deps.documentId || !deps.canApply()) {
      deps.onError(NOT_ACCEPTING_EDITS);
      return;
    }
    if (!deps.node || !sceneImageReplacementTarget(deps.node)) {
      deps.onError(NOT_AN_IMAGE_TARGET);
      return;
    }
    const url = current.searchedFor;
    setLogoSearch((state) => ({ ...state, savingAssetId: assetId, error: null }));
    void save(url, assetId)
      .then((record) => {
        // The saved logo joins the Library tab at once, under Logos.
        setRegistry((records) => [record, ...records.filter((item) => item.id !== record.id)]);
        createSceneAssetLibraryPick(() => depsRef.current, () => record)(record.id);
        setLogoSearch((state) => ({ ...state, savingAssetId: null }));
      })
      .catch((cause: unknown) => {
        setLogoSearch((state) => ({
          ...state, savingAssetId: null, error: cause instanceof Error ? cause.message : String(cause),
        }));
      });
  }, [save]);

  const thumbnailUrl = useCallback(
    (record: AssetRecord) => `${DESIGN_API_BFF_PREFIX}/assets/${encodeURIComponent(record.id)}/bytes`,
    [],
  );

  return {
    category, close, error, isOpen, items, loading, logoSearch, open, pick, pickLogo, query, refresh,
    searchLogos: runLogoSearch, setCategory, setLogoQuery, setQuery, setTab, tab, thumbnailUrl,
  };
}
