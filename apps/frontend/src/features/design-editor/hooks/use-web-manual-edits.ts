"use client";

// W3.2: the manual-editing controller, ported verbatim from the design
// editor's `apps/editor/src/hooks/useWebManualEdits.ts`. The ONLY changes:
// this header, the "use client" directive, the import paths (extracted
// engine), the config source (`designBffConfig()` replaces the dev shell's
// `editorApiBaseUrl()` — the W2.1 BFF contract), and the same mechanical
// ref-write adaptation as the W2.2 port (latest-value refs update in a
// passive effect; this repo's react-hooks lint makes render-time ref writes
// an error). Undo/redo ride along — W3.4 wires them to the action menu.

import { useCallback, useEffect, useRef, useState } from "react";

import { designBffConfig } from "../data/design-bff";
import { type DesignEditorConfig } from "../engine/config";
import {
  applyWebOperations,
  webRedo,
  webUndo,
  WebOperationsError,
  type WebOperation
} from "../engine/webDocuments";

/**
 * The manual-editing controller — the one write path for inspector facet edits,
 * contenteditable commits, and undo/redo. Per docs/frontend-practices.md rule
 * 2, all of this workflow policy (base-version tracking, 409/422 handling, the
 * post-mutation reload) lives here, not in the panels; the inspector builds an
 * op and calls `applyOps`, the topbar calls `undo`/`redo`.
 *
 * Base version: read from the loaded document (`current_version`) via a ref so
 * every send carries the latest committed version without re-arming callbacks.
 * After any successful mutation the hook fires `onReload` — the shell's quiet
 * doc + render refetch — which feeds a fresh `baseVersion` back in.
 *
 * Recoverable rejections surface differently, matching the server contract:
 *   • 409 base-version → an info `note` ("Document moved on — reloaded") and a
 *     reload (the edit is dropped; the user re-applies against fresh state).
 *   • 422 invalid batch → the first diagnostic message as an inline `error`
 *     (the doc is unchanged, so no reload).
 * Exactly one mutation runs at a time (`busy`).
 */
export interface WebManualEdits {
  /** Persist a manual-edit batch. No-op while a mutation is in flight or the
   * batch is empty. */
  applyOps: (operations: WebOperation[], intent?: string) => void;
  undo: () => void;
  redo: () => void;
  busy: boolean;
  /** A transient informational message (409 reload); cleared on the next send. */
  note: string | null;
  /** An inline error (422 diagnostic or transport failure); cleared on the next
   * send or via {@link WebManualEdits.clearMessages}. */
  error: string | null;
  /** F5 task 19: the ENGINE's own refusal code behind the current `error`
   * (`op.route_exists`, `op.route_invalid`, …), when the server sent one. The
   * controller stays prose-agnostic — it surfaces the code and lets the panel
   * that provoked the write say the refusal in ITS own words (the inspector's
   * route field does exactly this). Null for a transport failure, a locally
   * reported error, or any refusal the server sent no code for. */
  errorEngineCode: string | null;
  clearMessages: () => void;
  /** W4.2 (§1 row 12): set the same inline error line from an adjacent write
   * path that fails BEFORE any operation exists — today the Replace-image
   * upload. State only: the inspector already renders this slot, and the W3.3
   * founder ruling forbids any new failure UI. */
  reportError: (message: string) => void;
}

export interface UseWebManualEditsOptions {
  documentId: string;
  /** The loaded document's committed version, sent as `base_version`. */
  baseVersion: number | null;
  /** The shell's quiet refetch of doc + render (bumps its reload nonce). */
  onReload: () => void;
  config?: DesignEditorConfig;
  // Injectable for tests; default to the real wrappers.
  applyImpl?: typeof applyWebOperations;
  undoImpl?: typeof webUndo;
  redoImpl?: typeof webRedo;
}

export function useWebManualEdits(options: UseWebManualEditsOptions): WebManualEdits {
  const {
    documentId,
    baseVersion,
    onReload,
    config,
    applyImpl = applyWebOperations,
    undoImpl = webUndo,
    redoImpl = webRedo
  } = options;

  const [busy, setBusy] = useState(false);
  const [note, setNote] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  // F5 task 19: moves in lockstep with `error` — always set/cleared in the same
  // place, so the pair can never describe two different failures.
  const [errorEngineCode, setErrorEngineCode] = useState<string | null>(null);

  const busyRef = useRef(false);
  const mountedRef = useRef(true);
  // Latest-value refs so the callbacks keep a stable identity while always
  // reading current props (updated in a passive effect, per this repo's
  // react-hooks rules).
  const baseVersionRef = useRef(baseVersion);
  const onReloadRef = useRef(onReload);
  useEffect(() => {
    baseVersionRef.current = baseVersion;
    onReloadRef.current = onReload;
  });

  useEffect(() => {
    mountedRef.current = true;
    return () => {
      mountedRef.current = false;
    };
  }, []);

  const settle = useCallback(() => {
    busyRef.current = false;
    if (mountedRef.current) {
      setBusy(false);
    }
  }, []);

  const clearMessages = useCallback(() => {
    setNote(null);
    setError(null);
    setErrorEngineCode(null);
  }, []);

  // W4.2 (§1 row 12): the Replace-image upload fails before there is any batch
  // to send, so it borrows this same inline slot instead of growing a second
  // failure surface. Guarded by `mountedRef` like every other setter here.
  const reportError = useCallback((message: string) => {
    if (!mountedRef.current) {
      return;
    }
    setNote(null);
    setError(message);
    // A locally reported failure has no server refusal behind it.
    setErrorEngineCode(null);
  }, []);

  const base = useCallback(() => config ?? designBffConfig(), [config]);

  const applyOps = useCallback(
    (operations: WebOperation[], intent?: string) => {
      if (busyRef.current || operations.length === 0) {
        return;
      }
      busyRef.current = true;
      setBusy(true);
      setNote(null);
      setError(null);
      setErrorEngineCode(null);
      void applyImpl(base(), documentId, operations, {
        baseVersion: baseVersionRef.current,
        intent
      })
        .then(() => {
          settle();
          onReloadRef.current();
        })
        .catch((cause: unknown) => {
          settle();
          if (!mountedRef.current) {
            return;
          }
          if (cause instanceof WebOperationsError && cause.kind === "base_version") {
            setNote("Document moved on — reloaded.");
            onReloadRef.current();
            return;
          }
          setError(
            cause instanceof Error ? cause.message : "This edit could not be applied."
          );
          setErrorEngineCode(
            cause instanceof WebOperationsError ? cause.engineCode : null
          );
        });
    },
    [applyImpl, base, documentId, settle]
  );

  const runHistory = useCallback(
    (impl: typeof webUndo) => {
      if (busyRef.current) {
        return;
      }
      busyRef.current = true;
      setBusy(true);
      setNote(null);
      setError(null);
      setErrorEngineCode(null);
      void impl(base(), documentId)
        .then(() => {
          settle();
          onReloadRef.current();
        })
        .catch((cause: unknown) => {
          settle();
          if (!mountedRef.current) {
            return;
          }
          // 409 undo.empty/redo.empty just means the stack raced empty; resync
          // depths quietly rather than alarming the user.
          if (cause instanceof WebOperationsError && cause.status === 409) {
            onReloadRef.current();
            return;
          }
          setError(cause instanceof Error ? cause.message : "History step failed.");
        });
    },
    [base, documentId, settle]
  );

  const undo = useCallback(() => runHistory(undoImpl), [runHistory, undoImpl]);
  const redo = useCallback(() => runHistory(redoImpl), [runHistory, redoImpl]);

  return {
    applyOps,
    undo,
    redo,
    busy,
    note,
    error,
    errorEngineCode,
    clearMessages,
    reportError
  };
}
