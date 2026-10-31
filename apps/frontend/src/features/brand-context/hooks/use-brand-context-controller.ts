import { useAssetLibrary } from "./use-asset-library";
import type { CreativeType } from "../model/asset-context";
import { useEffect, useMemo, useRef, useState } from "react";
import { useKnowledgeEditor } from "./use-knowledge-editor";
import { pickSelectedDocument } from "../model/knowledge-selection";
import type {
  BrandAssetCategory,
  BrandAssetSortDirection,
  BrandAssetSortKey,
  BrandAssetView,
  BrandColorMode,
  BrandContextInitialState,
  BrandContextSection,
  BrandContextWorkspace,
  BrandTextStyle,
  BrandTypeface,
} from "../model/brand-context";

type BrandDialog = "new-style" | "new-typeface" | null;
type AssetEditingField = "description" | "name" | null;

const assetFilterOptions: ReadonlyArray<{ label: string; value: "all" | BrandAssetCategory }> = [
  { label: "All assets", value: "all" },
  { label: "Logos", value: "logo" },
  { label: "Backgrounds", value: "background" },
  { label: "Mockups", value: "mockup" },
  { label: "Uploads", value: "upload" },
  { label: "AI-generated images", value: "ai-generated" },
];

const assetSortOptions: ReadonlyArray<{ label: string; value: BrandAssetSortKey }> = [
  { label: "Name", value: "name" },
  { label: "Type", value: "type" },
  { label: "Size", value: "size" },
  { label: "Created", value: "created" },
];

export function useBrandContextController({
  initial,
  workspace,
  scopeKey,
  canWriteKnowledge,
}: {
  initial: BrandContextInitialState;
  workspace: BrandContextWorkspace;
  scopeKey: string;
  canWriteKnowledge: boolean;
}) {
  const assetLibrary = useAssetLibrary(workspace.assets, scopeKey, canWriteKnowledge);
  const assets = assetLibrary.assets;
  const [creativeTypeFilter, setCreativeTypeFilter] = useState("all");
  const [usageFilter, setUsageFilter] = useState("all");
  const [sourceFilter, setSourceFilter] = useState("all");
  const copyTimer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const defaultDocument = workspace.knowledgeFolders
    .flatMap((folder) => folder.documents)
    .find((document) => document.path === initial.filePath)
    ?? workspace.knowledgeFolders.flatMap((folder) => folder.documents)[0];

  const [section, setSection] = useState(initial.section);
  const [colorMode, setColorModeState] = useState(initial.colorMode);
  const [assetView, setAssetViewState] = useState(initial.assetView);
  // The requested path wins even before it has loaded: the kit's Design brief streams in after
  // the documents, and a link to it should land on it once it arrives.
  const [selectedDocumentPath, setSelectedDocumentPath] = useState(
    initial.filePath ?? defaultDocument?.path ?? "",
  );
  const [openFolderIds, setOpenFolderIds] = useState<Set<string>>(
    () => new Set(defaultDocument ? [defaultDocument.folderId] : []),
  );
  const [assetQuery, setAssetQuery] = useState("");
  const [assetCategoryFilter, setAssetCategoryFilterState] = useState<"all" | BrandAssetCategory>("all");
  const [assetFilterOpen, setAssetFilterOpen] = useState(false);
  const [assetSortKey, setAssetSortKey] = useState<BrandAssetSortKey>("created");
  const [assetSortDirection, setAssetSortDirection] = useState<BrandAssetSortDirection>("descending");
  const [assetMenuId, setAssetMenuId] = useState<string | null>(null);
  const [assetRenameId, setAssetRenameId] = useState<string | null>(null);
  const [assetRenameValue, setAssetRenameValue] = useState("");
  const [hiddenAssetIds, setHiddenAssetIds] = useState<Set<string>>(
    () => new Set(),
  );
  const [selectedAssetId, setSelectedAssetId] = useState<string | null>(
    assets.some((asset) => asset.id === initial.assetId)
      ? initial.assetId ?? null
      : null,
  );
  const [assetEditingField, setAssetEditingField] = useState<AssetEditingField>(null);
  const [dialog, setDialog] = useState<BrandDialog>(null);
  const [addedTypefaces, setAddedTypefaces] = useState<BrandTypeface[]>([]);
  const [removedTypefaceIds, setRemovedTypefaceIds] = useState<Set<string>>(() => new Set());
  const typefaces = useMemo(() => [
    ...workspace.typefaces.filter((typeface) => !removedTypefaceIds.has(typeface.id)),
    ...addedTypefaces.filter((typeface) => !workspace.typefaces.some((font) => font.family.toLowerCase() === typeface.family.toLowerCase())),
  ], [addedTypefaces, removedTypefaceIds, workspace.typefaces]);
  const [typefaceMenuId, setTypefaceMenuId] = useState<string | null>(null);
  const [fontSearch, setFontSearch] = useState("");
  const [customFontName, setCustomFontName] = useState("");
  const [textStyles, setTextStyles] = useState(workspace.textStyles);
  // The brand kit streams in after the documents (2026-10-15), so the first render may have no
  // styles yet. Seed them once when the kit lands; later refreshes keep local additions.
  const [stylesSeeded, setStylesSeeded] = useState(workspace.textStyles.length > 0);
  if (!stylesSeeded && workspace.textStyles.length > 0) {
    setStylesSeeded(true);
    setTextStyles(workspace.textStyles);
  }
  const [newStyle, setNewStyle] = useState<BrandTextStyle>({
    fontFamily: workspace.typefaces[0]?.family ?? "Satoshi Variable",
    fontSize: 18,
    fontWeight: 600,
    id: "new-style",
    lineHeight: 28,
    name: "Body-large",
    recommendedUse: "one or two line sentences",
  });
  const [shareCopied, setShareCopied] = useState(false);

  useEffect(() => () => {
    if (copyTimer.current) clearTimeout(copyTimer.current);
  }, []);

  useEffect(() => {
    function onKeyDown(event: KeyboardEvent) {
      if (event.key !== "Escape" || selectedAssetId) return;
      if (assetRenameId) {
        setAssetRenameId(null);
        setAssetRenameValue("");
      } else if (assetMenuId) {
        setAssetMenuId(null);
      } else if (assetFilterOpen) {
        setAssetFilterOpen(false);
      } else if (typefaceMenuId) {
        setTypefaceMenuId(null);
      } else if (dialog) {
        setDialog(null);
      }
    }

    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, [assetFilterOpen, assetMenuId, assetRenameId, dialog, selectedAssetId, typefaceMenuId]);

  const allDocuments = useMemo(
    () => workspace.knowledgeFolders.flatMap((folder) => folder.documents),
    [workspace.knowledgeFolders],
  );
  const selectedDocument = pickSelectedDocument(allDocuments, selectedDocumentPath);
  // The generated product catalog is read-only: the product actions change it (spec 2026-10-15).
  const knowledgeEditor = useKnowledgeEditor(selectedDocument, {
    scopeKey,
    canWrite: canWriteKnowledge && !selectedDocument?.generated,
  });
  const selectedAsset = selectedAssetId
    ? assets.find((asset) => asset.id === selectedAssetId) ?? null
    : null;
  const filteredAssets = useMemo(() => {
    const query = assetQuery.trim().toLocaleLowerCase();
    const visibleAssets = assets
      .filter((asset) => !hiddenAssetIds.has(asset.id))
      .filter((asset) => assetCategoryFilter === "all" || asset.category === assetCategoryFilter)
      .filter((asset) => creativeTypeFilter === "all" || (asset.context?.creative_type ?? "unknown") === creativeTypeFilter)
      .filter((asset) => usageFilter === "all" || asset.context?.usage_roles.includes(usageFilter as never))
      .filter((asset) => sourceFilter === "all" || asset.sources?.includes(sourceFilter as never))
      .filter((asset) => !query || `${asset.name} ${asset.description} ${asset.type} ${asset.context?.creative_type ?? ""} ${asset.context?.tags.join(" ") ?? ""}`.toLocaleLowerCase().includes(query));

    return [...visibleAssets].sort((left, right) => {
      let comparison = 0;
      if (assetSortKey === "name") comparison = left.name.localeCompare(right.name);
      if (assetSortKey === "type") comparison = left.type.localeCompare(right.type);
      if (assetSortKey === "size") comparison = left.sizeBytes - right.sizeBytes;
      if (assetSortKey === "created") comparison = Date.parse(left.createdAt) - Date.parse(right.createdAt);
      return assetSortDirection === "ascending" ? comparison : -comparison;
    });
  }, [assetCategoryFilter, assetQuery, assetSortDirection, assetSortKey, hiddenAssetIds, assets, creativeTypeFilter, usageFilter, sourceFilter]);
  const filteredTypefaces = useMemo(() => {
    const query = fontSearch.trim().toLocaleLowerCase();
    return typefaces.filter((typeface) =>
      typeface.family.toLocaleLowerCase().includes(query),
    );
  }, [fontSearch, typefaces]);

  function syncRoute(next: {
    assetId?: string | null;
    assetView?: BrandAssetView;
    colorMode?: BrandColorMode;
    filePath?: string;
    section?: BrandContextSection;
  }) {
    const params = new URLSearchParams();
    const nextSection = next.section ?? section;
    params.set("section", nextSection);

    if (nextSection === "colors") {
      params.set("theme", next.colorMode ?? colorMode);
    }
    if (nextSection === "assets") {
      params.set("view", next.assetView ?? assetView);
      const assetId = next.assetId === undefined ? selectedAssetId : next.assetId;
      if (assetId) params.set("asset", assetId);
    }
    if (nextSection === "knowledge") {
      const path = next.filePath ?? selectedDocument?.path;
      if (path) params.set("file", path);
    }

    // The section, document and asset live in this client's state; the address only records
    // them for sharing and reloads. `router.replace` re-ran the whole server page (every
    // document and the brand kit, ~2 s) on each click — the native history call updates the
    // address and Next's router without a server round trip (Next 16 "Native History API").
    window.history.replaceState(null, "", `/brand-context?${params.toString()}`);
  }

  function selectSection(nextSection: BrandContextSection) {
    setSection(nextSection);
    syncRoute({ section: nextSection });
  }

  function selectDocument(documentId: string) {
    const document = allDocuments.find((item) => item.id === documentId);
    if (!document) return;
    setSelectedDocumentPath(document.path);
    setSection("knowledge");
    setOpenFolderIds((current) => new Set(current).add(document.folderId));
    syncRoute({ filePath: document.path, section: "knowledge" });
  }

  /** Open a document by path, even one that has not loaded yet — a renamed product's page
   * appears at its new path after the refresh that follows the rename. */
  function openDocumentPath(path: string) {
    setSelectedDocumentPath(path);
    setSection("knowledge");
    setOpenFolderIds((current) => new Set(current).add(path.split("/")[0]));
    syncRoute({ filePath: path, section: "knowledge" });
  }

  function openAsset(assetId: string) {
    setSelectedAssetId(assetId);
    setAssetEditingField(null);
    setAssetMenuId(null);
    syncRoute({ assetId, section: "assets" });
  }

  function beginAssetRename(assetId: string) {
    const asset = assets.find((item) => item.id === assetId);
    if (!asset) return;
    setAssetRenameId(assetId);
    setAssetRenameValue(asset.name);
    setAssetMenuId(null);
  }

  async function commitAssetRename() {
    if (!assetRenameId) return;
    const nextName = assetRenameValue.trim();
    if (nextName && !(await assetLibrary.save(assetRenameId, {title: nextName}))) return;
    setAssetRenameId(null);
    setAssetRenameValue("");
  }

  async function deleteAsset(assetId: string) {
    // Hidden at once; the design API archives it so neither the page nor the design agent finds
    // it again. A refusal puts the card back (the library shows the error).
    setHiddenAssetIds((current) => new Set(current).add(assetId));
    setAssetMenuId(null);
    if (selectedAssetId === assetId) closeAsset();
    if (!(await assetLibrary.remove(assetId))) {
      setHiddenAssetIds((current) => {
        const next = new Set(current);
        next.delete(assetId);
        return next;
      });
    }
  }

  function editAssetDetails(assetId: string) {
    setSelectedAssetId(assetId);
    setAssetEditingField("name");
    setAssetMenuId(null);
    syncRoute({ assetId, section: "assets" });
  }

  async function closeAsset() {
    if (selectedAssetId && !(await assetLibrary.edits.flush(selectedAssetId))) return;
    setSelectedAssetId(null);
    setAssetEditingField(null);
    syncRoute({ assetId: null, section: "assets" });
  }

  function addCustomFont(file: File) {
    const family = file.name.replace(/\.(otf|ttf|woff2?|eot)$/i, "");
    setCustomFontName(file.name);
    setFontSearch(family);
  }

  function createTypeface() {
    const family = fontSearch.trim() || customFontName.replace(/\.[^.]+$/, "");
    if (!family) return;
    if (!typefaces.some((typeface) => typeface.family.toLocaleLowerCase() === family.toLocaleLowerCase())) {
      setAddedTypefaces((current) => [
        ...current,
        { family, id: `custom-${family.toLocaleLowerCase().replace(/[^a-z0-9]+/g, "-")}`, source: "custom" },
      ]);
    }
    setDialog(null);
    setFontSearch("");
    setCustomFontName("");
  }

  function createTextStyle() {
    setTextStyles((current) => [
      ...current,
      { ...newStyle, id: `style-${crypto.randomUUID()}` },
    ]);
    setDialog(null);
  }

  function useTypefaceInNewStyle(typefaceId: string) {
    const typeface = typefaces.find((item) => item.id === typefaceId);
    if (!typeface) return;
    setNewStyle((current) => ({ ...current, fontFamily: typeface.family }));
    setTypefaceMenuId(null);
    setDialog("new-style");
  }

  function removeTypeface(typefaceId: string) {
    if (typefaces.find((typeface) => typeface.id === typefaceId)?.source !== "custom") return;
    setAddedTypefaces((current) => current.filter((typeface) => typeface.id !== typefaceId));
    setRemovedTypefaceIds((current) => new Set(current).add(typefaceId));
    setTypefaceMenuId(null);
  }

  async function shareCurrentView() {
    await navigator.clipboard?.writeText(window.location.href);
    setShareCopied(true);
    if (copyTimer.current) clearTimeout(copyTimer.current);
    copyTimer.current = setTimeout(() => setShareCopied(false), 4000);
  }

  return {
    assetLibrary,
    creativeTypeFilter, setCreativeTypeFilter, usageFilter, setUsageFilter, sourceFilter, setSourceFilter,
    flushAssetDraft() {
      if (selectedAsset) void assetLibrary.edits.flush(selectedAsset.id);
    },
    setCreativeType(value: CreativeType) {
      if (selectedAsset) void assetLibrary.save(selectedAsset.id, {creative_type: value});
    },
    addCustomFont,
    assetDraft: selectedAsset ? { description: selectedAsset.description, name: selectedAsset.name } : null,
    assetEditingField,
    assetFilterOpen,
    assetFilterOptions,
    assetMenuId,
    assetQuery,
    assetRenameId,
    assetRenameValue,
    assetCategoryFilter,
    assetSortDirection,
    assetSortKey,
    assetSortOptions,
    assetView,
    beginAssetRename,
    cancelAssetRename() {
      setAssetRenameId(null);
      setAssetRenameValue("");
    },
    closeAsset,
    closeAssetFilter() {
      setAssetFilterOpen(false);
    },
    closeAssetMenu() {
      setAssetMenuId(null);
    },
    closeDialog() {
      setDialog(null);
    },
    colorMode,
    commitAssetRename,
    createTextStyle,
    createTypeface,
    customFontName,
    dialog,
    deleteAsset,
    filteredAssets,
    filteredTypefaces,
    fontSearch,
    knowledgeEditor,
    newStyle,
    editAssetDetails,
    openAsset,
    openFolderIds,
    openNewStyleDialog() {
      setDialog("new-style");
    },
    openNewTypefaceDialog() {
      setDialog("new-typeface");
    },
    removeTypeface,
    section,
    selectDocument,
    openDocumentPath,
    selectedAsset,
    selectedDocument,
    selectSection,
    setAssetDraft(field: "description" | "name", value: string) {
      if (!selectedAsset) return;
      if (!assetLibrary.canWrite) return;
      assetLibrary.edits.stage(selectedAsset.id, field === "name" ? {title: value} : {description: value});
    },
    setAssetEditingField,
    setAssetRenameValue,
    setAssetQuery,
    setAssetCategoryFilter(nextCategory: "all" | BrandAssetCategory) {
      setAssetCategoryFilterState(nextCategory);
      setAssetFilterOpen(false);
    },
    setAssetSort(nextKey: BrandAssetSortKey) {
      if (nextKey === assetSortKey) {
        setAssetSortDirection((current) => current === "ascending" ? "descending" : "ascending");
      } else {
        setAssetSortKey(nextKey);
        setAssetSortDirection("ascending");
      }
    },
    setAssetView(nextView: BrandAssetView) {
      setAssetViewState(nextView);
      syncRoute({ assetView: nextView, section: "assets" });
    },
    setColorMode(nextMode: BrandColorMode) {
      setColorModeState(nextMode);
      syncRoute({ colorMode: nextMode, section: "colors" });
    },
    setFontSearch,
    setNewStyle<K extends keyof BrandTextStyle>(field: K, value: BrandTextStyle[K]) {
      setNewStyle((current) => ({ ...current, [field]: value }));
    },
    shareCopied,
    shareCurrentView,
    textStyles,
    toggleAssetFilter() {
      setAssetFilterOpen((current) => !current);
      setAssetMenuId(null);
    },
    toggleAssetMenu(assetId: string) {
      setAssetMenuId((current) => current === assetId ? null : assetId);
      setAssetFilterOpen(false);
    },
    toggleFolder(folderId: string) {
      setOpenFolderIds((current) => {
        const next = new Set(current);
        if (next.has(folderId)) next.delete(folderId);
        else next.add(folderId);
        return next;
      });
    },
    typefaces,
    typefaceMenuId,
    toggleTypefaceMenu(typefaceId: string) {
      setTypefaceMenuId((current) => current === typefaceId ? null : typefaceId);
    },
    useTypefaceInNewStyle,
  };
}

export type BrandContextController = ReturnType<typeof useBrandContextController>;
