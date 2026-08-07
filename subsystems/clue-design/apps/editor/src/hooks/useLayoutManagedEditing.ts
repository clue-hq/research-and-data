import { useEffect, useRef, useState } from "react";

/**
 * Advanced per-document opt-out from handoff-absolute: with the toggle on,
 * the editor skips BOTH freeze seams (the accept-time bake and the
 * first-gesture freeze) so agent auto-layout stays live under human edits.
 * Forward-only — enabling never un-freezes containers that are already Free;
 * disabling re-enables freezing at the next seam.
 *
 * The value governs the session immediately and persists per change (a
 * checkbox, not a draft-then-Save flow). On a fresh canvas there is no
 * document yet — the value stays local and auto-persists once the first
 * Accept creates the document (same contract as standing instructions).
 */
export interface UseLayoutManagedEditingDeps {
  activeDocumentId: string | null;
  /** Value loaded with the document (false on a fresh canvas). */
  initialEnabled: boolean;
  saveRunner: (documentId: string, enabled: boolean) => Promise<boolean>;
}

export function useLayoutManagedEditing(deps: UseLayoutManagedEditingDeps) {
  const { activeDocumentId, initialEnabled, saveRunner } = deps;

  const [enabled, setEnabledState] = useState(initialEnabled);

  const persist = (documentId: string, next: boolean) => {
    saveRunner(documentId, next).catch(() => {
      // Best-effort persistence: the local value keeps governing this
      // session's freeze seams; a reload falls back to the stored value.
    });
  };

  const setEnabled = (next: boolean) => {
    setEnabledState(next);
    if (activeDocumentId) {
      persist(activeDocumentId, next);
    }
  };

  // Auto-persist a value toggled BEFORE the document existed: when the first
  // Accept mints the id, a non-default value saves itself once.
  const enabledRef = useRef(enabled);
  enabledRef.current = enabled;
  const previousDocumentIdRef = useRef(activeDocumentId);
  useEffect(() => {
    const appeared = previousDocumentIdRef.current === null && activeDocumentId !== null;
    previousDocumentIdRef.current = activeDocumentId;
    if (appeared && activeDocumentId !== null && enabledRef.current !== initialEnabled) {
      persist(activeDocumentId, enabledRef.current);
    }
  }, [activeDocumentId]);

  return { enabled, setEnabled };
}
