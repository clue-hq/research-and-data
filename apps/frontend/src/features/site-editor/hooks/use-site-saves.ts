"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import type { SiteDocument } from "@clue/site-kit/site-document";
import type { SiteRepository } from "../data/site.repository";
import { IDLE_SITE_SAVE_STATE, SiteSaveController, type SiteSaveState, type SiteSettled } from "./site-save-controller";

export interface SiteSaves extends SiteSaveState {
  save: (site: SiteDocument, intent?: string) => void;
  undo: () => void;
  redo: () => void;
  restore: (batchId: string) => void;
  adopt: (loaded: { version: number; undoDepth: number; redoDepth: number }) => void;
  isIdle: () => boolean;
  /** Every site this tab has edited is idle: nothing in flight or queued (a closed site's save may
   * still be on its way). */
  allIdle: () => boolean;
  /** The version the queue's next write will be based on, read now (React state lags a render). */
  knownVersion: () => number | null;
  requestReloadWhenIdle: () => void;
  reportError: (message: string) => void;
  clearMessages: () => void;
  /** K6-2: where `settled` counts failures from (see the controller). */
  failureMark: (documentId: string) => number;
  /** K6-2: once every write to this document is done (a publish waits for it), failing with the
   * reason of a write refused after `since`. A document this tab never edited has nothing on its way. */
  settled: (documentId: string, since?: number) => Promise<SiteSettled>;
}

/** One controller per site document (kept across visits); the open one's state mirrored for rendering. */
export function useSiteSaves({
  documentId,
  lockNote,
  onReload,
  onSuperseded,
  repository,
}: {
  documentId: string | null;
  lockNote: string;
  onReload: () => void;
  /** Called the moment a history step lands or a save is refused (see the controller). Must be
   * stable: it is handed to the controller, which is rebuilt when it changes. */
  onSuperseded?: () => void;
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
  // One controller per document for the life of this hook, kept across visits: leaving a site and
  // coming back while its save is still in flight must find that save (and its version), or the new
  // visit adopts the pre-save read and its next edit is refused (sync-fix review F4).
  // (New inputs start a new registry; they are stable in practice.)
  const controllers = useMemo(
    () =>
      new ControllerRegistry(
        (documentId) =>
          new SiteSaveController({
            documentId,
            lockNote,
            onReload: () => setReloadRequests((count) => count + 1),
            onState: setState,
            onSuperseded,
            repository,
          }),
      ),
    [lockNote, onSuperseded, repository],
  );
  const controller = useMemo(() => (documentId ? controllers.forDocument(documentId) : null), [controllers, documentId]);
  // Attach in the effect, not at construction: StrictMode's simulated unmount disposes and then
  // re-attaches the same controller, and a real unmount or document switch leaves it disposed.
  useEffect(() => {
    controller?.attach();
    return () => controller?.dispose();
  }, [controller]);
  // Switching documents shows that document's controller state (idle for a new one): React's
  // adjust-state-on-prop-change pattern (render-time comparison), never a setState in an effect.
  const [owner, setOwner] = useState(controller);
  if (owner !== controller) {
    setOwner(controller);
    // A document seen before resumes from its controller's own state (a save may still be in flight).
    setState(controller?.snapshot ?? IDLE_SITE_SAVE_STATE);
  }
  const actions = useMemo(
    () => ({
      adopt: (loaded: { version: number; undoDepth: number; redoDepth: number }) => controller?.adopt(loaded),
      allIdle: () => controllers.allIdle(),
      clearMessages: () => controller?.clearMessages(),
      isIdle: () => controller?.isIdle() ?? true,
      knownVersion: () => controller?.snapshot.baseVersion ?? null,
      redo: () => controller?.redo(),
      reportError: (message: string) => controller?.reportError(message),
      requestReloadWhenIdle: () => controller?.requestReloadWhenIdle(),
      restore: (batchId: string) => controller?.restore(batchId),
      save: (site: SiteDocument, intent?: string) => controller?.save(site, intent),
      failureMark: (documentId: string) => controllers.failureMark(documentId),
      settled: (documentId: string, since?: number) => controllers.settled(documentId, since),
      undo: () => controller?.undo(),
    }),
    [controller, controllers],
  );
  return { ...state, ...actions };
}

/** The controllers this hook made, one per document. */
class ControllerRegistry {
  private readonly byDocument = new Map<string, SiteSaveController>();

  constructor(private readonly create: (documentId: string) => SiteSaveController) {}

  forDocument(documentId: string): SiteSaveController {
    const existing = this.byDocument.get(documentId);
    if (existing) return existing;
    const created = this.create(documentId);
    this.byDocument.set(documentId, created);
    return created;
  }

  failureMark(documentId: string): number {
    return this.byDocument.get(documentId)?.mark() ?? 0;
  }

  settled(documentId: string, since?: number): Promise<SiteSettled> {
    return this.byDocument.get(documentId)?.settled(since) ?? Promise.resolve({ ok: true, version: null });
  }

  allIdle(): boolean {
    for (const controller of this.byDocument.values()) if (!controller.isIdle()) return false;
    return true;
  }
}
