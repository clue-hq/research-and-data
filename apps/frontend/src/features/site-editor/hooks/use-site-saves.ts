"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import type { SiteDocument } from "@clue/site-kit/site-document";
import type { SiteRepository } from "../data/site.repository";
import { IDLE_SITE_SAVE_STATE, SiteSaveController, type SiteSaveState } from "./site-save-controller";

export interface SiteSaves extends SiteSaveState {
  save: (site: SiteDocument, intent?: string) => void;
  undo: () => void;
  redo: () => void;
  restore: (batchId: string) => void;
  adopt: (loaded: { version: number; undoDepth: number; redoDepth: number }) => void;
  reportError: (message: string) => void;
  clearMessages: () => void;
}

/** One controller per open site document; its state mirrored for rendering. */
export function useSiteSaves({
  documentId,
  lockNote,
  onReload,
  repository,
}: {
  documentId: string | null;
  lockNote: string;
  onReload: () => void;
  repository: SiteRepository;
}): SiteSaves {
  // Latest-value ref, written in a passive effect (this repo's react-hooks rule).
  const onReloadRef = useRef(onReload);
  useEffect(() => {
    onReloadRef.current = onReload;
  });
  // The controller asks for a reload by bumping a counter, and a passive effect hands that to the
  // latest `onReload`. A callback that reads the ref may not be handed to the controller during
  // render (react-hooks/refs), and making `onReload` a memo dependency would rebuild the
  // controller, dropping an in-flight save, whenever the parent passes a new function.
  // `handledReloads` makes it once per request, even when React re-runs the effect.
  const [reloadRequests, setReloadRequests] = useState(0);
  const handledReloads = useRef(0);
  useEffect(() => {
    if (reloadRequests === handledReloads.current) return;
    handledReloads.current = reloadRequests;
    onReloadRef.current();
  }, [reloadRequests]);
  const [state, setState] = useState<SiteSaveState>(IDLE_SITE_SAVE_STATE);
  const controller = useMemo(
    () =>
      documentId
        ? new SiteSaveController({
            documentId,
            lockNote,
            onReload: () => setReloadRequests((count) => count + 1),
            onState: setState,
            repository,
          })
        : null,
    [documentId, lockNote, repository],
  );
  // Attach in the effect, not at construction: StrictMode's simulated unmount disposes and then
  // re-attaches the same controller, and a real unmount or document switch leaves it disposed.
  useEffect(() => {
    controller?.attach();
    return () => controller?.dispose();
  }, [controller]);
  // A new document starts from an idle state: React's adjust-state-on-prop-change pattern
  // (render-time comparison), never a setState inside an effect.
  const [owner, setOwner] = useState(controller);
  if (owner !== controller) {
    setOwner(controller);
    setState(IDLE_SITE_SAVE_STATE);
  }
  const actions = useMemo(
    () => ({
      adopt: (loaded: { version: number; undoDepth: number; redoDepth: number }) => controller?.adopt(loaded),
      clearMessages: () => controller?.clearMessages(),
      redo: () => controller?.redo(),
      reportError: (message: string) => controller?.reportError(message),
      restore: (batchId: string) => controller?.restore(batchId),
      save: (site: SiteDocument, intent?: string) => controller?.save(site, intent),
      undo: () => controller?.undo(),
    }),
    [controller],
  );
  return { ...state, ...actions };
}
