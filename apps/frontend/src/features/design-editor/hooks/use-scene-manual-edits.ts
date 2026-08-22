"use client";

import { useCallback, useEffect, useRef, useState, type RefObject } from "react";
import {
  NO_HISTORY_DELTA,
  afterRedo,
  afterUndo,
  afterWrite,
  historyDepths,
  type SceneHistoryDelta,
} from "../adapter/scene-history";
import {
  SCENE_WRITE_FALLBACK_ERROR,
  historyFailureToMessages,
  reconcileToMessages,
  structuredEditFailureToMessage,
} from "../adapter/scene-reconcile";
import type { SceneCanvasControls } from "../components/scene-artifact-canvas";
import { designBffConfig } from "../data/design-bff";
import type { DesignEditorConfig } from "../engine/config";
import type { Operation, Scene } from "../engine/scene/contracts";
import { createEditQueue, type EditQueuePort } from "../engine/scene/editQueue";
import {
  applyStructuredEdit,
  redoDocument,
  undoDocument,
  type StructuredEdit,
} from "../engine/scene/structuredEdits";

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
 *
 * ── AD3.3: undo/redo ──────────────────────────────────────────────────────
 * A history step is the OPPOSITE shape to a write, and deliberately so. The
 * server owns the stacks, so the step is a plain `POST /documents/{id}/undo`
 * with nothing local about it, and the way its result reaches the screen is a
 * RELOAD — the same adoption path a divergence takes. The engine's local scene
 * is never patched by hand: the server has just rewritten the document, and
 * inventing an equivalent local edit would be exactly the fabrication the
 * optimistic write path avoids by applying the engine's own operations.
 *
 * Its control flow is lifted from the website lane's `runHistory`
 * (`use-web-manual-edits.ts:170-199`) — single-flight, both message lines
 * cleared first, a 409 empty stack resynced in silence — with the two
 * mechanical adaptations this lane needs: the queue's cached `base_version` is
 * re-based on the version the step returned (it is stale the moment the server
 * writes without us), and the depth bookkeeping below records the step.
 */

export interface SceneManualEdits {
  /** Apply a batch locally and persist it. No-op on an empty batch, on a
   * disabled engine, and on an engine-rejected batch.
   *
   * AD4.A step 2: it REPORTS whether the batch was taken. The event-driven
   * property rows ignore the answer — they have already gated themselves and a
   * refusal has already said so in the slots below — but the Replace-image flow
   * cannot: its panel control is holding a local preview of the picked file, so
   * "the engine refused this batch" is the difference between a preview that
   * states the document and one that lies about it. */
  applyOps: (operations: Operation[], intent?: string) => boolean;
  /**
   * AD4.C-3 / ruling C-12: persist operations the engine has ALREADY applied.
   *
   * The canvas's freeze-on-grab is the one write on this lane that does not
   * start life as a batch: `engine.applyStructuredEdit(freezeLayoutEdit())`
   * applies it and hands back the operations it performed. Those operations
   * must still reach the server, but they must NOT be applied a second time —
   * so this is `applyOps` with its first step removed, and everything after it
   * (the remembered scene, the history delta, the queue, the busy accounting)
   * identical.
   *
   * `scene` is the POST-apply scene the engine returned. It seeds the queue's
   * drain-time divergence check, exactly as `outcome.scene` does for a normal
   * write.
   *
   * Never call this with operations nobody has applied — the local engine and
   * the server would diverge on the next drain, which is precisely the failure
   * the optimistic ordering exists to avoid.
   */
  persistAppliedOps: (operations: Operation[], scene: Scene) => boolean;
  /**
   * AD4.A step 2 review (FIX 1): could a batch land right now — an armed
   * document, a mounted canvas, and a live engine?
   *
   * `applyOps` answers the same question, but only by trying, and TWO of its
   * three `false` branches say nothing at all: "not armed" and "the engine is
   * unavailable" (D9 read-only, silent on purpose because the canvas's own G-D
   * banner already explains it — the justification that covers the third
   * branch, an engine-REJECTED batch, does not cover these two, which never
   * reach the engine's words). That silence is correct for a write that costs
   * nothing to attempt and wrong for one that SPENDS first: the Replace-image
   * flow uploads the file, minting a real asset row, before it has an operation
   * to apply. Asked up front, the refusal costs nothing and strands nothing.
   */
  canApply: () => boolean;
  /**
   * AD4.B step 4 (§1.5): one DOCUMENT-LEVEL STRUCTURED EDIT — today, group and
   * ungroup.
   *
   * It is a second kind of write, not a variant of `applyOps`, because the
   * engine models it as one: `groupEdit`/`ungroupEdit` are `StructuredEdit`s
   * (`engine/scene/structuredEdits.ts`), the server expands them into canonical
   * operations, and the client is deliberately not the authority on that
   * expansion — re-deriving "which inserts and moves make a group" here would
   * be exactly the fabrication this lane's optimistic path avoids by applying
   * only the engine's own operations.
   *
   * So it takes the SHAPE OF A HISTORY STEP rather than of a write: single
   * flight, drain the write queue first, POST, re-base the queue on the version
   * that came back, and adopt the result by RELOADING. No local apply, because
   * there is nothing honest to apply locally.
   *
   * No-op while another document step is in flight and when no document is
   * armed. A refusal reaches the inspector's existing inline error line in the
   * server's own words; nothing new is invented for it.
   */
  applyEdit: (edit: StructuredEdit) => void;
  /** AD3.3: one server history step. No-op while another step is in flight and
   * when no document is armed; the result arrives as a reload. */
  undo: () => void;
  redo: () => void;
  /** AD3.3: the stack is empty, so the step would do nothing — the action
   * menu's row disables off this. Computed from the loaded document's real
   * depths plus the steps taken since that load. Deliberately NOT raised by
   * `busy`: the single-flight guard already drops a second step, and disabling
   * mid-flight would only flicker the row. */
  undoDisabled: boolean;
  redoDisabled: boolean;
  /** True while an enqueued batch has not yet drained, or a history step is in
   * flight. */
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
  /** AD3.3: the loaded document's real stack depths, and the load counter that
   * says when they were last refreshed (`use-scene-document.ts`). Zero/zero
   * before anything has loaded, which disables both controls. */
  undoDepth?: number;
  redoDepth?: number;
  loadGeneration?: number;
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
  const {
    config,
    controlsRef,
    documentId,
    loadGeneration = 0,
    onReload,
    redoDepth = 0,
    undoDepth = 0,
  } = options;

  const [busy, setBusy] = useState(false);
  const [note, setNote] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  const mountedRef = useRef(true);
  const pendingRef = useRef(0);
  // AD3.3: a history step is single-flight (the website lane's `busyRef`,
  // `use-web-manual-edits.ts:91`). Separate from `pendingRef`, which COUNTS
  // write batches and deliberately gates nothing — the two answer different
  // questions, and only this one refuses work.
  const historyRef = useRef(false);
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

  // AD3.3: what has happened since the loaded base — the ONLY thing that keeps
  // the disabled states honest between reloads, because a successful write
  // deliberately does not refetch the document (see the header). React state,
  // not a ref: it drives `undoDisabled`/`redoDisabled`, so it must re-render.
  const [delta, setDelta] = useState(NO_HISTORY_DELTA);
  // A fresh authoritative base arrived: everything the delta was counting is
  // already inside the depths that came with it, so carrying it forward would
  // double-count. Done as React's own adjust-state-on-prop-change (a
  // render-time comparison, the pattern `scene-artifact-canvas.tsx:308-315`
  // uses), never as an effect — an effect would render one frame of the stale
  // count first, and this repo's react-hooks lint bars set-state in an effect.
  const [lastLoadGeneration, setLastLoadGeneration] = useState(loadGeneration);
  if (lastLoadGeneration !== loadGeneration) {
    setLastLoadGeneration(loadGeneration);
    setDelta(NO_HISTORY_DELTA);
  }
  const depths = historyDepths(
    { redo: redoDepth, undo: undoDepth },
    lastLoadGeneration === loadGeneration ? delta : NO_HISTORY_DELTA,
  );

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

  /** `busy` reports BOTH kinds of in-flight work through one flag, because the
   * inspector shows one. Derived from the two counters rather than set by each
   * caller, so a write draining cannot switch the flag off under a history step
   * that is still running. */
  const syncBusy = useCallback(() => {
    if (!mountedRef.current) {
      return;
    }
    setBusy(pendingRef.current > 0 || historyRef.current);
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

  /**
   * Everything a write does AFTER the engine has accepted it: remember the
   * scene, record the history step, hand the batch to the queue, and account
   * for it in `busy`.
   *
   * Extracted at AD4.C-3 because there are now TWO ways a batch reaches this
   * point — an inspector edit that this controller applied (`applyOps`), and
   * the canvas's freeze-on-grab, which the engine had already applied before
   * the controller ever saw it (`persistAppliedOps`). The step they do not
   * share is the apply; every step below it must stay identical, so it lives
   * in one place rather than being written twice.
   */
  const enqueueApplied = useCallback(
    (forDocumentId: string, operations: Operation[], scene: Scene) => {
      lastSceneRef.current = scene;
      // AD3.3: the batch the engine accepted is the batch that gets persisted,
      // so from here the document has one more undoable step and no redo stack.
      // Recorded at the hand-off rather than at the server's ack because every
      // path where the server does NOT take it — a rejection, a divergence, a
      // failed request — ends in `onReconcile`, which reloads; and a reload
      // replaces this count with the server's own depths. A miscount cannot
      // outlive the fetch that corrects it.
      setDelta(afterWrite);
      // The callers' `intent` argument (the interface accepts one, for
      // signature parity with the web lane) stops HERE, deliberately: the only
      // label `EnqueueOptions` carries is `checkpoint`, and upstream
      // checkpoints are the Compare/Revert anchors for agent TURNS. Stamping
      // one per inspector keystroke would bury that history under hundreds of
      // labels nobody can revert to. The queue takes no `intent` of its own
      // (`editQueue.ts:120-128` sends operations/actor/source/base_version),
      // so there is nothing else honest to do with it.
      const queue = ensureQueue(forDocumentId, scene);
      queue.enqueueOperations(operations);
      // `busy` REPORTS the in-flight batch; it does not gate the next one. The
      // queue is ordered and the local apply already landed, so blocking here
      // would drop a keystroke rather than delay it — the opposite of the web
      // lane, whose single-flight gate exists because it has no local engine.
      pendingRef.current += 1;
      syncBusy();
      // Settled on BOTH outcomes: the queue's chain swallows its own errors
      // (they arrive as `request_failed` reconcile events instead), but a
      // one-sided `.then` here would leave `busy` stuck true — and raise an
      // unhandled rejection — if that ever stopped being true.
      const settle = () => {
        pendingRef.current -= 1;
        syncBusy();
      };
      void queue.idle().then(settle, settle);
    },
    [ensureQueue, syncBusy],
  );

  /** The two silent refusals of `applyOps` below, asked without applying. */
  const canApply = useCallback(() => {
    const controls = controlsHolderRef.current.current;
    return Boolean(documentIdRef.current && controls?.canApply());
  }, []);

  const applyOps = useCallback(
    (operations: Operation[]) => {
      if (operations.length === 0) {
        return false;
      }
      const forDocumentId = documentIdRef.current;
      const controls = controlsHolderRef.current.current;
      // Not armed: no document, or no mounted canvas to apply through.
      if (!forDocumentId || !controls) {
        return false;
      }
      const outcome = controls.applyOperations(operations);
      // The engine is unavailable (D9 read-only). Nothing was applied, so
      // nothing may be persisted — and nothing is SAID here either: the
      // canvas's own G-D banner already explains the read-only state, and a
      // second message about it would be new failure UI.
      if (!outcome) {
        return false;
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
        return false;
      }
      setNote(null);
      setError(null);
      enqueueApplied(forDocumentId, operations, outcome.scene);
      // The engine took it and it is queued. NOT "the server accepted it" —
      // that answer arrives asynchronously through `onReconcile`, which owns
      // the reload and both message slots.
      return true;
    },
    [enqueueApplied],
  );

  /**
   * AD4.C-3 / ruling C-12: the canvas's freeze-on-grab, whose operations the
   * engine has already applied. Everything below the apply is shared with
   * `applyOps` (see `enqueueApplied`); the two differences are deliberate:
   *
   *  • it does not apply anything — doing so would apply the batch twice;
   *  • it does not touch the two message slots. A freeze is a silent
   *    consequence of the user grabbing something, not a write they asked for,
   *    so it must not wipe an inspector error they are still reading.
   */
  const persistAppliedOps = useCallback(
    (operations: Operation[], scene: Scene) => {
      if (operations.length === 0) {
        return false;
      }
      const forDocumentId = documentIdRef.current;
      if (!forDocumentId) {
        return false;
      }
      enqueueApplied(forDocumentId, operations, scene);
      return true;
    },
    [enqueueApplied],
  );

  /**
   * AD3.3: one server-side DOCUMENT STEP — a history step, or (AD4.B step 4) a
   * structured edit. Lifted from the website lane's `runHistory`
   * (`use-web-manual-edits.ts:170-199`) with this lane's two additions, and
   * generalized over `perform` once §1.5's group/ungroup turned out to need the
   * identical control flow rather than a second copy of it.
   *
   * The success path does three things and adopts nothing by hand:
   *  1. **re-base the queue.** The server just wrote the document without us,
   *     so the queue's cached `base_version` is stale and the next inspector
   *     edit would be refused as a concurrent write. `resync` takes the version
   *     the step returned — the same re-basing the reconcile path does, for the
   *     same reason. (Both routes answer with the same
   *     `{document:{current_version}}` envelope — `dto.py`'s `document_summary`
   *     — so `currentVersionOf` reads either.)
   *  2. **record the step** (`recordStep`), so the two menu rows keep telling
   *     the truth between reloads.
   *  3. **reload.** The canvas refetches, the engine is rebuilt from the
   *     server's scene, and the inspector re-reads it — the one adoption path.
   *
   * `describeFailure` returns the line to show, or `null` for the one refusal
   * that means "nothing happened and nothing needs saying" (an empty history
   * stack), which resyncs by reloading instead.
   */
  const runDocumentStep = useCallback(
    (
      perform: (
        apiBaseUrl: string,
        forDocumentId: string,
        // Optional exactly as `DesignEditorConfig.fetchImpl` is: both routes
        // default to the receiver-safe wrapper when the config carries none.
        fetchImpl?: typeof fetch,
      ) => Promise<Record<string, unknown>>,
      recordStep: (delta: SceneHistoryDelta) => SceneHistoryDelta,
      describeFailure: (cause: unknown) => string | null,
    ) => {
      // Single-flight: a second step while one is in flight would race the
      // first onto a stack the server has not finished moving.
      if (historyRef.current) {
        return;
      }
      const forDocumentId = documentIdRef.current;
      if (!forDocumentId) {
        return;
      }
      const resolved = configRef.current ?? designBffConfig();
      historyRef.current = true;
      syncBusy();
      setNote(null);
      setError(null);
      const settle = () => {
        historyRef.current = false;
        syncBusy();
      };
      // AD3.3 review: DRAIN THE WRITE QUEUE FIRST. A document step is a second
      // writer against the same document, and the queue's cached base_version
      // belongs to the batches already in it — so an undo that lands between a
      // batch's local apply and its POST makes the server refuse that batch
      // (409), and D10 then drops the user's edit with a "moved on" note it did
      // not earn. Waiting is ordering, not blocking: the queue is already
      // serial, the batches are one keystroke each, and nothing is discarded.
      // (The web lane gets this free — one busy flag covers edits and history
      // because it has no queue.)
      const pending = queueRef.current;
      const drained =
        pending?.documentId === forDocumentId
          ? pending.queue.idle()
          : Promise.resolve();
      void drained
        .catch(() => undefined)
        .then(() =>
          perform(resolved.apiBaseUrl, forDocumentId, resolved.fetchImpl),
        )
        .then((payload) => {
          settle();
          // A step for a document the user has already left must not re-base
          // the queue that took its place, or move a count that is not its own.
          if (!mountedRef.current || documentIdRef.current !== forDocumentId) {
            return;
          }
          const active = queueRef.current;
          if (active?.documentId === forDocumentId) {
            active.queue.resync(currentVersionOf(payload));
          }
          setDelta(recordStep);
          onReloadRef.current();
        })
        .catch((cause: unknown) => {
          settle();
          if (!mountedRef.current || documentIdRef.current !== forDocumentId) {
            return;
          }
          const message = describeFailure(cause);
          if (message === null) {
            // The stack raced empty: nothing happened, nothing to say. The
            // reload re-reads the real depths, which is what disagreed.
            onReloadRef.current();
            return;
          }
          // A refusal about THIS step, in the server's own words (never the
          // upstream sentence's internal prose). No reload: the document is
          // unchanged, so there is nothing new to adopt.
          setError(message);
        });
    },
    [syncBusy],
  );

  const runHistory = useCallback(
    (step: "undo" | "redo") => {
      runDocumentStep(
        step === "undo" ? undoDocument : redoDocument,
        step === "undo" ? afterUndo : afterRedo,
        (cause) => {
          const failure = historyFailureToMessages(cause);
          return failure.emptyStack ? null : failure.error;
        },
      );
    },
    [runDocumentStep],
  );

  const undo = useCallback(() => runHistory("undo"), [runHistory]);
  const redo = useCallback(() => runHistory("redo"), [runHistory]);

  /**
   * AD4.B step 4 (§1.5): group / ungroup.
   *
   * NO `base_version` IS SENT, deliberately and for the history step's exact
   * reason: the drain above IS the ordering discipline, and the queue owns the
   * only copy of that number (the AD3.2 addressing ruling). `require_base_version`
   * therefore does not fire, so a 409 from this route is a real refusal about
   * this edit rather than a concurrent-writer event — which is why
   * `structuredEditFailureToMessage` has no quiet branch and always says
   * something.
   *
   * `afterWrite`, not `afterUndo`: the server commits a new envelope and drops
   * the redo stack, exactly as an operation batch does.
   */
  const applyEdit = useCallback(
    (edit: StructuredEdit) => {
      runDocumentStep(
        (apiBaseUrl, forDocumentId, fetchImpl) =>
          applyStructuredEdit(apiBaseUrl, forDocumentId, edit, {
            fetchImpl,
          }).then((result) => result.response),
        afterWrite,
        structuredEditFailureToMessage,
      );
    },
    [runDocumentStep],
  );

  return {
    applyEdit,
    applyOps,
    busy,
    canApply,
    clearMessages,
    error,
    note,
    persistAppliedOps,
    redo,
    redoDisabled: depths.redo === 0,
    reportError,
    undo,
    undoDisabled: depths.undo === 0,
  };
}

/**
 * The version the history step committed at, from its own response — the
 * envelope shape `POST /documents/{id}/{undo,redo}` returns
 * (`{document: {current_version}}`, `lumen_api/dto.py::document_summary`).
 * `structuredEdits.undoDocument` hands back the raw payload, so this is the one
 * place that reads it; anything unexpected reads as `null`, which makes the
 * queue refetch the version on its next batch instead of trusting a guess.
 */
function currentVersionOf(payload: Record<string, unknown>): number | null {
  const document = payload.document;
  if (!document || typeof document !== "object") {
    return null;
  }
  const version = (document as { current_version?: unknown }).current_version;
  return typeof version === "number" ? version : null;
}
