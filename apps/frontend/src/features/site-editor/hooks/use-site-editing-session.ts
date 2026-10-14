"use client";

import { useCallback, useEffect, useMemo, useRef, useState, useSyncExternalStore } from "react";
import type { FrameToAppMessage } from "@clue/site-kit/editor-protocol";
import { componentProps, getAtPath, pageFor, shortcutFor, withAssetAt } from "@clue/site-kit/editor-site";
import type { SiteDocument } from "@clue/site-kit/site-document";
import { AGENT_RUN_LOCK_NOTE } from "@/features/chat-shell/model/agent-run-lock";
import type { PendingAnnotation } from "@/features/design-editor/adapter/annotations";
import { useWebAnnotations, type WebAnnotationsSession } from "@/features/design-editor/hooks/use-web-annotations";
import { httpSiteRepository, type SiteRepository } from "../data/site.repository";
import { siteAnnotationAddress } from "../model/site-annotations";
import { siteCanvasState } from "../model/site-canvas-state";
import {
  acceptsFrameEdits,
  frameSyncFor,
  initialRoute,
  linksFresh,
  siteFrameMode,
  siteInitKey,
} from "../model/site-frame-sync";
import { siteHistoryActionFromEvent, siteHistoryDisabled } from "../model/site-history";
import { cloneLabelsOf, componentLabel, siteLayerRows, type SiteLayerRow } from "../model/site-layers";
import {
  EMPTY_ROUTE_HISTORY,
  parseRouteInput,
  sitePageRows,
  stepRoute,
  visitRoute,
  type RouteHistory,
} from "../model/site-pages";
import {
  commitFieldEdit,
  siteInspectorTitle,
  type SiteInspectorBinding,
  type SiteSelection,
} from "../model/site-selection";
import { siteStageMounted, type SiteStageBinding } from "../model/site-stage";
import { loadDecision, SiteWorkingCopy } from "../model/site-working-copy";
import { useSiteDocument } from "./use-site-document";
import { useSiteEditorOrigin } from "./use-site-editor-origin";
import { useSiteFrameHost, type SiteFrameHost } from "./use-site-frame-host";
import { useSiteImages, type SiteImageFieldBinding, type SiteImages } from "./use-site-images";
import { useSiteSaves, type SiteSaves } from "./use-site-saves";
import { useSiteVersions } from "./use-site-versions";
import { fieldsHaveImage, type SiteImageTarget } from "./site-images.logic";

const DEFAULT_REPOSITORY = httpSiteRepository();

export interface SiteEditingSession {
  activeDocumentId: string | null;
  annotations: WebAnnotationsSession;
  history: { redoDisabled: boolean; undoDisabled: boolean };
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
  onSendAnnotation,
  repository = DEFAULT_REPOSITORY,
  warm,
}: {
  activeArtifactId: string | null;
  documentIds: Record<string, string> | undefined;
  editing: boolean;
  enabled: boolean;
  locked: boolean;
  onSendAnnotation?: (note: string) => void;
  repository?: SiteRepository;
  warm: boolean;
}): SiteEditingSession {
  const activeDocumentId = enabled && activeArtifactId ? (documentIds?.[activeArtifactId] ?? null) : null;
  const origin = useSiteEditorOrigin(enabled || warm);
  const [reloadNonce, setReloadNonce] = useState(0);
  const reload = useCallback(() => setReloadNonce((nonce) => nonce + 1), []);
  const load = useSiteDocument({ documentId: activeDocumentId, reloadNonce, repository });
  // The app's working copy (ruling: the app holds the site JSON and is the only side that saves).
  // An external store, so every write path reads the CURRENT copy, never a render's closure.
  const [copy] = useState(() => new SiteWorkingCopy());
  // A history step that lands, or a save refused, makes the copy out of date until its reload is
  // adopted; canvas proposals and dock edits in that window are refused (sync-fix review F1).
  const supersede = useCallback(() => copy.supersede(), [copy]);
  const saves = useSiteSaves({
    documentId: activeDocumentId,
    lockNote: AGENT_RUN_LOCK_NOTE,
    onReload: reload,
    onSuperseded: supersede,
    repository,
  });
  const working = useSyncExternalStore(copy.subscribe, copy.get, copy.get);
  const currentSite = working && working.documentId === activeDocumentId ? working : null;
  useEffect(() => {
    // Leaving a document drops its copy; coming back waits for a fresh read (S2b-3).
    copy.forget();
  }, [activeDocumentId, copy]);
  // Each load replaces the copy only when it is not older than what the save queue wrote, and never
  // while edits are on their way (then it asks for a reload once the queue drains) — a reload read
  // before our own save landed used to be adopted and erase that save (S2b-3, K3-3).
  const { adopt: adoptSaves, isIdle: savesIdle, knownVersion, requestReloadWhenIdle } = saves;
  useEffect(() => {
    const loaded = load.loaded;
    if (!loaded || loaded.documentId !== activeDocumentId) return;
    const decision = loadDecision({ loadedVersion: loaded.version, knownVersion: knownVersion(), idle: savesIdle() });
    if (decision === "stale") return;
    if (decision === "defer") {
      requestReloadWhenIdle();
      return;
    }
    copy.adoptLoad(loaded.documentId, loaded.site);
    adoptSaves(loaded);
  }, [activeDocumentId, adoptSaves, copy, knownVersion, load.loaded, requestReloadWhenIdle, savesIdle]);

  const [routeState, setRouteState] = useState<{ documentId: string; route: string } | null>(null);
  const route = routeState && routeState.documentId === activeDocumentId ? routeState.route : "/";
  const [routeHistory, setRouteHistory] = useState<{ documentId: string; history: RouteHistory } | null>(null);
  const routeTrail = routeHistory && routeHistory.documentId === activeDocumentId ? routeHistory.history : EMPTY_ROUTE_HISTORY;
  const [initGeneration, setInitGeneration] = useState(0);
  const [shownDocumentId, setShownDocumentId] = useState<string | null>(null);
  const [frameError, setFrameError] = useState<{ documentId: string; message: string } | null>(null);
  const mode = siteFrameMode({ editing, locked });
  const [selection, setSelection] = useState<SiteSelection | null>(null);
  const openLibraryRef = useRef<((target: SiteImageTarget) => void) | null>(null);
  const annotateRef = useRef<((payload: { componentId: string; geometry: PendingAnnotation["geometry"]; route: string }) => void) | null>(null);
  const stepRef = useRef<(action: "undo" | "redo") => void>(() => undefined);

  const latest = useRef({ editing, locked, save: saves.save });
  useEffect(() => {
    latest.current = { editing, locked, save: saves.save };
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
        setRouteHistory((previous) => ({
          documentId: message.documentId,
          history: visitRoute(previous && previous.documentId === message.documentId ? previous.history : EMPTY_ROUTE_HISTORY, message.payload.route),
        }));
        return;
      case "changed": {
        // Review focus 5: an edit outside edit mode, or under the agent-run lock, is never saved.
        if (!acceptsFrameEdits({ editing: now.editing, locked: now.locked })) return;
        // A proposal made over an older copy than the app's is refused: the frame is about to show
        // the newer copy and drops that unsent typing (a stale canvas never overwrites a newer copy).
        if (copy.propose(message.documentId, message.payload.site, message.payload.baseRev) === "accepted") {
          now.save(message.payload.site);
        }
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
      case "annotate":
        annotateRef.current?.(message.payload);
        return;
      case "shortcut":
        stepRef.current(message.payload.action);
        return;
      default:
        return;
    }
  }, [copy]);
  const frame = useSiteFrameHost({ editorOrigin: origin.origin, onMessage: handleFrameMessage });
  const { boot, post } = frame;

  // Keep the frame in step: init for a new document, new agent sections or a rebooted frame;
  // replace_site for each new revision of the working copy (an agent checkpoint, a history step, a
  // refused save going back). The dock's own patches set `sent.rev` when they go out.
  const sent = useRef<{ initKey: string | null; rev: number | null }>({ initKey: null, rev: null });
  useEffect(() => {
    if (!activeDocumentId || !currentSite || load.status !== "ready" || !load.brand || boot === 0) return;
    // The URL toolbar's reload bumps `initGeneration`, which forces a fresh init from a fresh read.
    const initKey = `${siteInitKey(activeDocumentId, currentSite.site, boot)}|${initGeneration}`;
    const sync = frameSyncFor({
      frameReady: true,
      initKey,
      sentInitKey: sent.current.initKey,
      sentRev: sent.current.rev,
      rev: currentSite.rev,
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
      sent.current = { initKey, rev: currentSite.rev };
      post(
        "init",
        {
          brand: load.brand,
          device: "Desktop",
          mode,
          rev: currentSite.rev,
          route: initialRoute(currentSite.site, route),
          sections: load.links,
          site: currentSite.site,
        },
        activeDocumentId,
      );
      return;
    }
    if (sync.kind === "replace") {
      sent.current = { ...sent.current, rev: sync.rev };
      post("replace_site", { rev: sync.rev, site: currentSite.site }, activeDocumentId);
    }
  }, [activeDocumentId, boot, currentSite, initGeneration, load.brand, load.links, load.loadedAt, load.status, mode, post, reload, route]);

  // Edit / preview, sent once per change after the frame shows this document.
  const sentMode = useRef<string | null>(null);
  useEffect(() => {
    if (!activeDocumentId || shownDocumentId !== activeDocumentId) return;
    const key = `${activeDocumentId}|${boot}|${mode}`;
    if (sentMode.current === key) return;
    sentMode.current = key;
    post("set_mode", { mode }, activeDocumentId);
  }, [activeDocumentId, boot, mode, post, shownDocumentId]);

  // The dock (C5): the selected section's fields over the app's own copy of the site, and Layers.
  const activeSelection = editing && selection && selection.documentId === activeDocumentId ? selection : null;
  const cloneLabels = useMemo(() => cloneLabelsOf(load.brand), [load.brand]);
  const layers = siteLayerRows({ cloneLabels, route, selection: activeSelection, site: currentSite?.site ?? null });
  const values =
    activeSelection && currentSite ? componentProps(currentSite.site, activeSelection.target, activeSelection.componentId) : null;
  const save = saves.save;
  const commitField = useCallback(
    (name: string, value: unknown) => {
      // The CURRENT copy, never a render's closure: a canvas edit accepted a moment ago is in it.
      const current = copy.get();
      if (!activeSelection || !current || current.documentId !== activeDocumentId || !acceptsFrameEdits({ editing, locked })) return;
      const edit = commitFieldEdit(current.site, activeSelection, name, value);
      if (!edit) return;
      const rev = copy.edit(current.documentId, edit.site);
      if (rev === null) return;
      sent.current = { ...sent.current, rev };
      post("set_props", { componentId: activeSelection.componentId, props: edit.props, rev, route: activeSelection.target }, current.documentId);
      save(edit.site, `inspector: edit ${name}`);
    },
    [activeDocumentId, activeSelection, copy, editing, locked, post, save],
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
      const current = copy.get();
      if (!current || current.documentId !== activeDocumentId || !acceptsFrameEdits({ editing, locked })) return false;
      const props = componentProps(current.site, target.target, target.componentId);
      if (!props) return false;
      if (getAtPath(props, target.prop) === url) return true;
      const edited = withAssetAt(current.site, target.target, target.componentId, target.prop, url);
      const rev = copy.edit(current.documentId, edited);
      if (rev === null) return false;
      sent.current = { ...sent.current, rev };
      post("insert_asset", { componentId: target.componentId, prop: target.prop, rev, route: target.target, url }, current.documentId);
      save(edited, `inspector: set image ${target.prop}`);
      return true;
    },
    [activeDocumentId, copy, editing, locked, post, save],
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
  // C7: the web lane's annotations, one session per document, scoped by route.
  const annotations = useWebAnnotations(activeDocumentId, route);
  const openAnnotation = annotations.open;
  useEffect(() => {
    annotateRef.current = ({ componentId, geometry, route: target }) => {
      if (!acceptsFrameEdits({ editing, locked }) || !currentSite) return;
      const shellPart = target === "shell" ? componentId : null;
      const item = shellPart ? null : pageFor(currentSite.site, target)?.content.find((entry) => entry.props.id === componentId);
      const componentType = shellPart ? (shellPart === "header" ? "SiteHeader" : "SiteFooter") : (item?.type ?? "Section");
      const name = shellPart
        ? shellPart === "header" ? "Header" : "Footer"
        : componentLabel(componentType, item?.props ?? {}, cloneLabels);
      openAnnotation({ address: siteAnnotationAddress(target, componentId, componentType), geometry, name, textLike: false });
    };
  });
  const canvasAnnotations = useMemo(
    () => ({
      add: (note?: string) => {
        annotations.add(note);
      },
      dismiss: annotations.dismiss,
      editNote: annotations.editNote,
      onSend: onSendAnnotation,
      pending: annotations.state.pending,
    }),
    [annotations, onSendAnnotation],
  );
  // C8: one history path — the server's stack — from the menu, the app's keyboard and the frame's.
  const undo = saves.undo;
  const redo = saves.redo;
  useEffect(() => {
    stepRef.current = (action) => {
      if (!activeDocumentId || locked) return;
      if (action === "undo") undo();
      else redo();
    };
  });
  useEffect(() => {
    if (!activeDocumentId) return;
    const onAction = (event: Event) => {
      const action = siteHistoryActionFromEvent((event as CustomEvent).detail);
      if (action) stepRef.current(action);
    };
    const onKeyDown = (event: KeyboardEvent) => {
      const decision = shortcutFor(event);
      if (decision !== "undo" && decision !== "redo") return;
      event.preventDefault();
      stepRef.current(decision);
    };
    window.addEventListener("clue:artifact-action-request", onAction);
    window.addEventListener("keydown", onKeyDown);
    return () => {
      window.removeEventListener("clue:artifact-action-request", onAction);
      window.removeEventListener("keydown", onKeyDown);
    };
  }, [activeDocumentId]);
  const history = {
    redoDisabled: siteHistoryDisabled({ depth: saves.redoDepth, locked }),
    undoDisabled: siteHistoryDisabled({ depth: saves.undoDepth, locked }),
  };
  // C9: versions from the server; a restore is an undoable write that queues behind a pending save.
  const versions = useSiteVersions({
    documentId: activeDocumentId,
    repository,
    restore: saves.restore,
    version: saves.baseVersion,
  });
  // C10: the page panel and the URL toolbar. Navigation always goes through the frame; its
  // `navigated` answer moves the active row, the route field and the history.
  const navigate = useCallback(
    (target: string) => {
      if (activeDocumentId) post("navigate", { route: target }, activeDocumentId);
    },
    [activeDocumentId, post],
  );
  const step = useCallback(
    (direction: -1 | 1) => {
      if (!activeDocumentId) return;
      const moved = stepRoute(routeTrail, direction);
      if (!moved.route) return;
      setRouteHistory({ documentId: activeDocumentId, history: moved.history });
      post("navigate", { route: moved.route }, activeDocumentId);
    },
    [activeDocumentId, routeTrail, post],
  );
  const pages = { open: navigate, rows: sitePageRows(currentSite?.site ?? null, route) };
  const url = {
    back: () => step(-1),
    canBack: routeTrail.index > 0,
    canForward: routeTrail.index >= 0 && routeTrail.index < routeTrail.entries.length - 1,
    forward: () => step(1),
    go: (text: string) => {
      const target = parseRouteInput(text, currentSite?.site ?? null);
      if (target) navigate(target);
      return target !== null;
    },
    reload: () => {
      setInitGeneration((generation) => generation + 1);
      reload();
    },
    route,
  };
  const inspector: SiteInspectorBinding = {
    disabled: locked,
    error: saves.error,
    fields: activeSelection?.fields ?? null,
    layers,
    // The lock's own sentence while it holds (the Edit pill carries the same words).
    note: saves.note ?? (locked ? AGENT_RUN_LOCK_NOTE : null),
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
    annotations,
    history,
    imageField,
    images,
    inspector,
    post,
    reload,
    reloadNonce,
    route,
    saves,
    selection: activeSelection,
    site: currentSite?.site ?? null,
    stage: {
      canvas: {
        annotations: canvasAnnotations,
        editing: acceptsFrameEdits({ editing, locked }),
        errorMessage: canvas.message,
        iframeRef: frame.iframeRef,
        renderKind: canvas.kind,
        src: frame.src,
      },
      mounted: siteStageMounted({ editorOrigin: origin.origin, enabled, warm }),
      pages,
      url,
      versions: activeDocumentId ? versions : null,
    },
    version: saves.baseVersion,
  };
}
