"use client";

import { useCallback, useEffect, useRef, useState, type RefObject } from "react";
import {
  SCENE_WRITE_FALLBACK_ERROR,
  reconcileToMessages,
} from "../adapter/scene-reconcile";
import type { SceneCanvasControls } from "../components/scene-artifact-canvas";
import { designBffConfig } from "../data/design-bff";
import type { DesignEditorConfig } from "../engine/config";
import type { Operation, Scene } from "../engine/scene/contracts";
import { createEditQueue, type EditQueuePort } from "../engine/scene/editQueue";

/**
 * AD3.2: the ad (scene) lane's manual-editing controller — the ONE write path
 * behind every inspector commit, and the twin of the website lane's
 * `use-web-manual-edits.ts`. Same responsibilities (one place owns the write
 * policy; the panels only build operations and call `applyOps`), same two
 * message slots, same mounted-ref discipline.
 *
 * The ONE deliberate divergence from the web lane, and the reason this file
 * exists at all: **the write is OPTIMISTIC**, because the extracted queue
 * requires it.
 *
 *   1. apply the batch to the LIVE wasm engine (`controls.applyOperations`),
 *   2. repaint + mirror the new scene up (the canvas's own `refresh()` does
 *      both — it re-renders and fires `onSceneChange`, which rehydrates the
 *      inspector and the layer tree),
 *   3. only THEN `enqueueOperations` to persist.
 *
 * Order is not a preference here. `engine/scene/editQueue.ts` re-fetches the
 * server document when a batch drains and compares it to `localScene()`; any
 * difference fires `onReconcile({kind:"divergence"})`. Persisting before
 * applying locally would therefore report divergence on EVERY successful edit
 * and show the D10 reload note on every keystroke.
 *
 * And there is **no reload on success** — where the web lane fires `onReload`
 * after every accepted apply (it has no local engine, so a refetch is its only
 * way to see the result), the optimistic apply has already put the new value
 * on screen and in the inspector. The reload nonce is bumped ONLY when a
 * reconcile event says the server disagrees; the reload IS the adoption path
 * for the server's authoritative scene (D10's web-style posture), which is why
 * `event.serverScene` is never adopted by hand here.
 */

export interface SceneManualEdits {
  /** Apply a batch locally and persist it. No-op on an empty batch, on a
   * disabled engine, and on an engine-rejected batch. */
  applyOps: (operations: Operation[], intent?: string) => void;
  /** AD3.3 wires the engine's undo/redo stacks; today a documented no-op. */
  undo: () => void;
  redo: () => void;
  /** True while an enqueued batch has not yet drained. */
  busy: boolean;
  /** A transient informational message (the D10 quiet-reload note). */
  note: string | null;
  /** An inline error (an engine-refused edit, or a server rejection). */
  error: string | null;
  clearMessages: () => void;
  /** Set the same inline error from an adjacent write path that fails BEFORE
   * any operation exists. State only: the inspector already renders this slot
   * (`ImageInspector`'s `error` prop) and no new failure UI is authorized. */
  reportError: (message: string) => void;
}

export interface UseSceneManualEditsOptions {
  /** The active design document, or null when nothing is armed. */
  documentId: string | null;
  /** The mounted canvas's imperative seam — the live engine and its scene. */
  controlsRef: RefObject<SceneCanvasControls | null>;
  /** The session's reload nonce bump: refetch the authoritative document. */
  onReload: () => void;
  /** Injectable for tests/server callers; the real BFF transport by default. */
  config?: DesignEditorConfig;
}

interface QueueHandle {
  apiBaseUrl: string;
  documentId: string;
  queue: EditQueuePort;
}

export function useSceneManualEdits(
  options: UseSceneManualEditsOptions,
): SceneManualEdits {
  const { config, controlsRef, documentId, onReload } = options;

  const [busy, setBusy] = useState(false);
  const [note, setNote] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  const mountedRef = useRef(true);
  const pendingRef = useRef(0);
  const queueRef = useRef<QueueHandle | null>(null);
  // The last scene the engine accepted — the fallback `localScene()` reads
  // when the canvas has unmounted mid-flight (the queue's reconcile runs after
  // the batch lands, which can outlive the surface). Never the FIRST choice:
  // the live canvas snapshot also carries a reload or an agent turn.
  const lastSceneRef = useRef<Scene | null>(null);

  // Latest-value refs so the callbacks keep a stable identity while always
  // reading current props. Written in a passive effect, never at render time —
  // this repo's react-hooks lint makes a render-time ref write an error (the
  // same mechanical adaptation `use-web-manual-edits.ts:96-101` made).
  const configRef = useRef(config);
  const controlsHolderRef = useRef(controlsRef);
  const documentIdRef = useRef(documentId);
  const onReloadRef = useRef(onReload);
  useEffect(() => {
    configRef.current = config;
    controlsHolderRef.current = controlsRef;
    documentIdRef.current = documentId;
    onReloadRef.current = onReload;
  });

  useEffect(() => {
    mountedRef.current = true;
    return () => {
      mountedRef.current = false;
    };
  }, []);

  // A different document is a different queue: the base_version it tracks and
  // the batches it has in flight belong to the document they were made for.
  // Dropping the reference is the whole teardown — the port has no dispose,
  // and an in-flight batch for the previous document must still finish (it
  // resyncs ITSELF; the guard in `onReconcile` keeps its events off screen).
  // The remembered scene goes with it: it is this document's, and handing it
  // to the next document's queue would fake a divergence against a scene from
  // a different ad.
  useEffect(() => {
    return () => {
      lastSceneRef.current = null;
      queueRef.current = null;
    };
  }, [documentId]);

  const clearMessages = useCallback(() => {
    setNote(null);
    setError(null);
  }, []);

  const reportError = useCallback((message: string) => {
    if (!mountedRef.current) {
      return;
    }
    setNote(null);
    setError(message);
  }, []);

  /**
   * One queue per `(documentId, apiBaseUrl)`, built lazily at the first write:
   * `designBffConfig()` reads `window.location.origin`, so it cannot be called
   * during render on the server, and a document nobody edits should open no
   * queue at all.
   *
   * `seedScene` is the scene the engine just produced, so `localScene()` is
   * total from birth — the queue is never created without something to
   * reconcile against.
   */
  const ensureQueue = useCallback(
    (forDocumentId: string, seedScene: Scene): EditQueuePort => {
      const resolved = configRef.current ?? designBffConfig();
      const existing = queueRef.current;
      if (
        existing &&
        existing.documentId === forDocumentId &&
        existing.apiBaseUrl === resolved.apiBaseUrl
      ) {
        return existing.queue;
      }
      // Declared before the factory call so `onReconcile` closes over THIS
      // queue: a late event from a replaced queue must resync itself, never
      // the one that took its place.
      let queue: EditQueuePort | null = null;
      queue = createEditQueue({
        apiBaseUrl: resolved.apiBaseUrl,
        documentId: forDocumentId,
        fetchImpl: resolved.fetchImpl,
        localScene: () =>
          controlsHolderRef.current.current?.sceneSnapshot() ??
          lastSceneRef.current ??
          seedScene,
        onReconcile: (event) => {
          // Re-arm first: the queue halts itself on a rejection or a transport
          // failure, and `resync` is what clears that and re-bases it on the
          // server's version (null → it refetches on the next batch).
          queue?.resync(event.serverVersion);
          // A message about a document the user has already left would be a
          // lie about what is on screen.
          if (!mountedRef.current || queueRef.current?.queue !== queue) {
            return;
          }
          const messages = reconcileToMessages(event);
          setNote(messages.note);
          setError(messages.error);
          // The reload is the adoption path: it refetches the document, builds
          // a fresh engine from the server's scene and repaints — which is why
          // `event.serverScene` is never installed by hand.
          onReloadRef.current();
        },
      });
      queueRef.current = {
        apiBaseUrl: resolved.apiBaseUrl,
        documentId: forDocumentId,
        queue,
      };
      return queue;
    },
    [],
  );

  const applyOps = useCallback(
    (operations: Operation[]) => {
      if (operations.length === 0) {
        return;
      }
      const forDocumentId = documentIdRef.current;
      const controls = controlsHolderRef.current.current;
      // Not armed: no document, or no mounted canvas to apply through.
      if (!forDocumentId || !controls) {
        return;
      }
      const outcome = controls.applyOperations(operations);
      // The engine is unavailable (D9 read-only). Nothing was applied, so
      // nothing may be persisted — and nothing is SAID here either: the
      // canvas's own G-D banner already explains the read-only state, and a
      // second message about it would be new failure UI.
      if (!outcome) {
        return;
      }
      if (!outcome.accepted) {
        // The engine refused the batch and changed nothing. Its own words go
        // in the inspector's existing error line; the server never sees it.
        setNote(null);
        setError(
          outcome.message ??
            outcome.diagnostics[0]?.message ??
            SCENE_WRITE_FALLBACK_ERROR,
        );
        return;
      }
      lastSceneRef.current = outcome.scene;
      setNote(null);
      setError(null);
      // The callers' `intent` argument (the interface accepts one, for
      // signature parity with the web lane) stops HERE, deliberately: the only
      // label `EnqueueOptions` carries is `checkpoint`, and upstream
      // checkpoints are the Compare/Revert anchors for agent TURNS. Stamping
      // one per inspector keystroke would bury that history under hundreds of
      // labels nobody can revert to. The queue takes no `intent` of its own
      // (`editQueue.ts:120-128` sends operations/actor/source/base_version),
      // so there is nothing else honest to do with it.
      const queue = ensureQueue(forDocumentId, outcome.scene);
      queue.enqueueOperations(operations);
      // `busy` REPORTS the in-flight batch; it does not gate the next one. The
      // queue is ordered and the local apply already landed, so blocking here
      // would drop a keystroke rather than delay it — the opposite of the web
      // lane, whose single-flight gate exists because it has no local engine.
      pendingRef.current += 1;
      setBusy(true);
      // Settled on BOTH outcomes: the queue's chain swallows its own errors
      // (they arrive as `request_failed` reconcile events instead), but a
      // one-sided `.then` here would leave `busy` stuck true — and raise an
      // unhandled rejection — if that ever stopped being true.
      const settle = () => {
        pendingRef.current -= 1;
        if (pendingRef.current === 0 && mountedRef.current) {
          setBusy(false);
        }
      };
      void queue.idle().then(settle, settle);
    },
    [ensureQueue],
  );

  // AD3.3 owns undo/redo (the engine's inverse operations + the queue). They
  // are declared here so the surface AD3.3 fills is already the one the shell
  // consumes; until then the session keeps `undoDisabled`/`redoDisabled` true,
  // so nothing can call them.
  const undo = useCallback(() => undefined, []);
  const redo = useCallback(() => undefined, []);

  return {
    applyOps,
    busy,
    clearMessages,
    error,
    note,
    redo,
    reportError,
    undo,
  };
}
