"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import type { FrameToAppMessage } from "@clue/site-kit/editor-protocol";
import { canonicalJson, componentProps, getAtPath, withAssetAt } from "@clue/site-kit/editor-site";
import type { SiteDocument } from "@clue/site-kit/site-document";
import { AGENT_RUN_LOCK_NOTE } from "@/features/chat-shell/model/agent-run-lock";
import { httpSiteRepository, type SiteRepository } from "../data/site.repository";
import { siteCanvasState } from "../model/site-canvas-state";
import {
  acceptsFrameEdits,
  frameSyncFor,
  initialRoute,
  linksFresh,
  siteFrameMode,
  siteInitKey,
} from "../model/site-frame-sync";
import { cloneLabelsOf, siteLayerRows, type SiteLayerRow } from "../model/site-layers";
import {
  commitFieldEdit,
  siteInspectorTitle,
  type SiteInspectorBinding,
  type SiteSelection,
} from "../model/site-selection";
import { siteStageMounted, type SiteStageBinding } from "../model/site-stage";
import { useSiteDocument } from "./use-site-document";
import { useSiteEditorOrigin } from "./use-site-editor-origin";
import { useSiteFrameHost, type SiteFrameHost } from "./use-site-frame-host";
import { useSiteImages, type SiteImageFieldBinding, type SiteImages } from "./use-site-images";
import { useSiteSaves, type SiteSaves } from "./use-site-saves";
import { fieldsHaveImage, type SiteImageTarget } from "./site-images.logic";

const DEFAULT_REPOSITORY = httpSiteRepository();

/** The app's copy of the site (ruling: the app holds the site JSON and is the only side that saves). */
export interface AppSite {
  documentId: string;
  site: SiteDocument;
  version: number;
}

export interface SiteEditingSession {
  activeDocumentId: string | null;
  imageField: (path: string, value: string) => SiteImageFieldBinding | null;
  images: SiteImages;
  inspector: SiteInspectorBinding;
  post: SiteFrameHost["post"];
  reload: () => void;
  reloadNonce: number;
  route: string;
  saves: SiteSaves;
  /** The active selection (null outside edit mode or for another document). */
  selection: SiteSelection | null;
  setSite: (site: SiteDocument) => void;
  site: SiteDocument | null;
  stage: SiteStageBinding;
  version: number | null;
}

export function useSiteEditingSession({
  activeArtifactId,
  documentIds,
  editing,
  enabled,
  locked,
  repository = DEFAULT_REPOSITORY,
  warm,
}: {
  activeArtifactId: string | null;
  documentIds: Record<string, string> | undefined;
  editing: boolean;
  enabled: boolean;
  locked: boolean;
  repository?: SiteRepository;
  warm: boolean;
}): SiteEditingSession {
  const activeDocumentId = enabled && activeArtifactId ? (documentIds?.[activeArtifactId] ?? null) : null;
  const origin = useSiteEditorOrigin(enabled || warm);
  const [reloadNonce, setReloadNonce] = useState(0);
  const reload = useCallback(() => setReloadNonce((nonce) => nonce + 1), []);
  const load = useSiteDocument({ documentId: activeDocumentId, reloadNonce, repository });
  const saves = useSiteSaves({ documentId: activeDocumentId, lockNote: AGENT_RUN_LOCK_NOTE, onReload: reload, repository });

  // Adopt each load as the app's copy: React's adjust-state-on-prop-change pattern, never a setState
  // inside an effect (this repo's react-hooks rule).
  const [appSite, setAppSite] = useState<AppSite | null>(null);
  const [adopted, setAdopted] = useState(load.loaded);
  if (load.loaded !== adopted) {
    setAdopted(load.loaded);
    if (load.loaded) {
      setAppSite({ documentId: load.loaded.documentId, site: load.loaded.site, version: load.loaded.version });
    }
  }
  const currentSite = appSite && appSite.documentId === activeDocumentId ? appSite : null;
  const adopt = saves.adopt;
  useEffect(() => {
    if (load.loaded) adopt(load.loaded);
  }, [adopt, load.loaded]);

  const [routeState, setRouteState] = useState<{ documentId: string; route: string } | null>(null);
  const route = routeState && routeState.documentId === activeDocumentId ? routeState.route : "/";
  const [shownDocumentId, setShownDocumentId] = useState<string | null>(null);
  const [frameError, setFrameError] = useState<{ documentId: string; message: string } | null>(null);
  const mode = siteFrameMode({ editing, locked });
  const [selection, setSelection] = useState<SiteSelection | null>(null);
  const openLibraryRef = useRef<((target: SiteImageTarget) => void) | null>(null);

  const latest = useRef({ currentSite, editing, locked, save: saves.save });
  useEffect(() => {
    latest.current = { currentSite, editing, locked, save: saves.save };
  });

  const handleFrameMessage = useCallback((message: FrameToAppMessage) => {
    const now = latest.current;
    switch (message.type) {
      case "ready":
        // A rebooted frame shows no document until its next init lands: the canvas reads
        // "Loading preview…" until the new `navigated`.
        setShownDocumentId(null);
        setSelection(null);
        return;
      case "navigated":
        setShownDocumentId(message.documentId);
        setRouteState({ documentId: message.documentId, route: message.payload.route });
        setFrameError(null);
        return;
      case "changed": {
        const current = now.currentSite;
        if (!current || message.documentId !== current.documentId) return;
        // Review focus 5: an edit outside edit mode, or under the agent-run lock, is never saved.
        if (!acceptsFrameEdits({ editing: now.editing, locked: now.locked })) return;
        if (canonicalJson(message.payload.site) === canonicalJson(current.site)) return;
        setAppSite({ ...current, site: message.payload.site });
        now.save(message.payload.site);
        return;
      }
      case "error":
        setFrameError({ documentId: message.documentId, message: message.payload.message || message.payload.code });
        return;
      case "selected":
        setSelection({
          componentId: message.payload.componentId,
          componentType: message.payload.componentType,
          documentId: message.documentId,
          fields: message.payload.fields,
          target: message.payload.route,
        });
        return;
      case "deselected":
        setSelection(null);
        return;
      case "request_asset":
        openLibraryRef.current?.({ componentId: message.payload.componentId, prop: message.payload.prop, target: message.payload.route });
        return;
      default:
        // annotate / shortcut: Tasks 11-12 add their cases here.
        return;
    }
  }, []);
  const frame = useSiteFrameHost({ editorOrigin: origin.origin, onMessage: handleFrameMessage });
  const { boot, post } = frame;

  // Keep the frame in step: init for a new document, new agent sections or a rebooted frame;
  // replace_site for a new version of the same document (an agent checkpoint, a history step).
  const sent = useRef<{ initKey: string | null; version: number | null }>({ initKey: null, version: null });
  useEffect(() => {
    if (!activeDocumentId || !currentSite || load.status !== "ready" || !load.brand || boot === 0) return;
    const initKey = siteInitKey(activeDocumentId, currentSite.site, boot);
    const sync = frameSyncFor({
      frameReady: true,
      initKey,
      sentInitKey: sent.current.initKey,
      sentVersion: sent.current.version,
      version: currentSite.version,
    });
    if (sync.kind === "init") {
      // Review focus 4: never hand the frame links that may already have expired.
      if (!linksFresh(load.loadedAt, Date.now(), load.links.length)) {
        // A microtask later, not in the effect body: react-hooks/set-state-in-effect forbids the
        // synchronous call (the idiom `use-project-workspace-controller.ts` uses). A re-run before
        // it fires cancels it and decides again.
        let cancelled = false;
        queueMicrotask(() => {
          if (!cancelled) reload();
        });
        return () => {
          cancelled = true;
        };
      }
      sent.current = { initKey, version: currentSite.version };
      post(
        "init",
        {
          brand: load.brand,
          device: "Desktop",
          mode,
          route: initialRoute(currentSite.site, route),
          sections: load.links,
          site: currentSite.site,
        },
        activeDocumentId,
      );
      return;
    }
    if (sync.kind === "replace") {
      sent.current = { ...sent.current, version: sync.version };
      post("replace_site", { site: currentSite.site, version: sync.version }, activeDocumentId);
    }
  }, [activeDocumentId, boot, currentSite, load.brand, load.links, load.loadedAt, load.status, mode, post, reload, route]);

  // Edit / preview, sent once per change after the frame shows this document.
  const sentMode = useRef<string | null>(null);
  useEffect(() => {
    if (!activeDocumentId || shownDocumentId !== activeDocumentId) return;
    const key = `${activeDocumentId}|${boot}|${mode}`;
    if (sentMode.current === key) return;
    sentMode.current = key;
    post("set_mode", { mode }, activeDocumentId);
  }, [activeDocumentId, boot, mode, post, shownDocumentId]);

  const setSite = useCallback(
    (site: SiteDocument) => {
      setAppSite((previous) => (previous && previous.documentId === activeDocumentId ? { ...previous, site } : previous));
    },
    [activeDocumentId],
  );

  // The dock (C5): the selected section's fields over the app's own copy of the site, and Layers.
  const activeSelection = editing && selection && selection.documentId === activeDocumentId ? selection : null;
  const cloneLabels = useMemo(() => cloneLabelsOf(load.brand), [load.brand]);
  const layers = siteLayerRows({ cloneLabels, route, selection: activeSelection, site: currentSite?.site ?? null });
  const values =
    activeSelection && currentSite ? componentProps(currentSite.site, activeSelection.target, activeSelection.componentId) : null;
  const save = saves.save;
  const commitField = useCallback(
    (name: string, value: unknown) => {
      if (!activeSelection || !currentSite || !activeDocumentId || !acceptsFrameEdits({ editing, locked })) return;
      const edit = commitFieldEdit(currentSite.site, activeSelection, name, value);
      if (!edit) return;
      setAppSite({ ...currentSite, site: edit.site });
      post("set_props", { componentId: activeSelection.componentId, props: edit.props, route: activeSelection.target }, activeDocumentId);
      save(edit.site, `inspector: edit ${name}`);
    },
    [activeDocumentId, activeSelection, currentSite, editing, locked, post, save],
  );
  const selectLayer = useCallback(
    (row: SiteLayerRow) => {
      if (!activeDocumentId || !editing) return;
      post("select", { componentId: row.componentId, route: row.target }, activeDocumentId);
    },
    [activeDocumentId, editing, post],
  );
  // C6: every image path (library pick, upload, generate, accepted edit) ends here.
  const writableRef = useRef<() => boolean>(() => false);
  useEffect(() => {
    writableRef.current = () => acceptsFrameEdits({ editing, locked });
  });
  const currentUrl = useCallback(
    (target: SiteImageTarget) => {
      const props = currentSite ? componentProps(currentSite.site, target.target, target.componentId) : null;
      const value = getAtPath(props, target.prop);
      return typeof value === "string" ? value : "";
    },
    [currentSite],
  );
  const insertAsset = useCallback(
    (target: SiteImageTarget, url: string): boolean => {
      if (!currentSite || !activeDocumentId || !acceptsFrameEdits({ editing, locked })) return false;
      const props = componentProps(currentSite.site, target.target, target.componentId);
      if (!props) return false;
      if (getAtPath(props, target.prop) === url) return true;
      const edited = withAssetAt(currentSite.site, target.target, target.componentId, target.prop, url);
      setAppSite({ ...currentSite, site: edited });
      post("insert_asset", { componentId: target.componentId, prop: target.prop, route: target.target, url }, activeDocumentId);
      save(edited, `inspector: set image ${target.prop}`);
      return true;
    },
    [activeDocumentId, currentSite, editing, locked, post, save],
  );
  const images = useSiteImages({
    clearMessages: saves.clearMessages,
    currentUrl,
    documentId: activeDocumentId,
    imagesVisible: activeSelection ? fieldsHaveImage(activeSelection.fields) : false,
    kit: load.brand?.kit ?? null,
    onError: saves.reportError,
    place: insertAsset,
    writable: () => writableRef.current(),
  });
  useEffect(() => {
    openLibraryRef.current = images.openLibraryFor;
  });
  const imageField = useCallback(
    (path: string, value: string): SiteImageFieldBinding | null =>
      activeSelection ? images.field({ componentId: activeSelection.componentId, prop: path, target: activeSelection.target }, value) : null,
    [activeSelection, images],
  );
  const inspector: SiteInspectorBinding = {
    disabled: locked,
    error: saves.error,
    fields: activeSelection?.fields ?? null,
    layers,
    note: saves.note,
    onCommit: commitField,
    onSelectLayer: selectLayer,
    selectionKey: activeSelection ? `${activeSelection.target}#${activeSelection.componentId}` : `page:${route}`,
    title: siteInspectorTitle(currentSite?.site ?? null, route, layers.find((row) => row.active)),
    values,
  };

  const canvas = siteCanvasState({
    documentId: activeDocumentId,
    editorOrigin: origin.origin,
    editorOriginError: origin.error,
    editorOriginLoaded: origin.loaded,
    frameError: frameError && frameError.documentId === activeDocumentId ? frameError.message : null,
    frameReady: boot > 0,
    loadError: load.error,
    loadStatus: load.status,
    shownDocumentId,
    site: currentSite?.site ?? null,
  });

  return {
    activeDocumentId,
    imageField,
    images,
    inspector,
    post,
    reload,
    reloadNonce,
    route,
    saves,
    selection: activeSelection,
    setSite,
    site: currentSite?.site ?? null,
    stage: {
      canvas: { errorMessage: canvas.message, iframeRef: frame.iframeRef, renderKind: canvas.kind, src: frame.src },
      mounted: siteStageMounted({ editorOrigin: origin.origin, enabled, warm }),
    },
    version: currentSite?.version ?? null,
  };
}
