import { useEffect, useRef, useState } from "react";

/**
 * 2e: per-document standing agent instructions. The draft is editable any
 * time; the trimmed value rides with EVERY turn payload immediately (no save
 * needed for the current session), while Save persists it on the document so
 * it survives reloads. On a fresh canvas there is no document yet — the
 * instructions stay local and are auto-persisted once the first Accept
 * creates the document.
 */
export interface UseAgentInstructionsDeps {
  activeDocumentId: string | null;
  /** Instructions loaded with the document (null on a fresh canvas). */
  initialInstructions: string | null;
  saveRunner: (documentId: string, instructions: string | null) => Promise<string | null>;
}

export function useAgentInstructions(deps: UseAgentInstructionsDeps) {
  const { activeDocumentId, initialInstructions, saveRunner } = deps;

  const [draft, setDraft] = useState(initialInstructions ?? "");
  const [savedValue, setSavedValue] = useState<string | null>(initialInstructions);
  const [isSaving, setIsSaving] = useState(false);
  const [saveError, setSaveError] = useState<string | null>(null);

  /** The value each turn carries (trimmed; empty → none). */
  const instructions = draft.trim() || null;
  const isDirty = instructions !== savedValue;

  const save = async () => {
    if (!activeDocumentId || isSaving || !isDirty) {
      return;
    }
    setIsSaving(true);
    setSaveError(null);
    try {
      const persisted = await saveRunner(activeDocumentId, instructions);
      setSavedValue(persisted);
    } catch (error) {
      setSaveError(
        error instanceof Error ? error.message : "Saving the instructions failed."
      );
    } finally {
      setIsSaving(false);
    }
  };

  // Auto-persist instructions typed BEFORE the document existed: when the
  // first Accept mints the id, dirty instructions save themselves once.
  const saveRef = useRef(save);
  saveRef.current = save;
  const previousDocumentIdRef = useRef(activeDocumentId);
  useEffect(() => {
    const appeared = previousDocumentIdRef.current === null && activeDocumentId !== null;
    previousDocumentIdRef.current = activeDocumentId;
    if (appeared) {
      void saveRef.current();
    }
  }, [activeDocumentId]);

  return {
    instructions,
    draft,
    setDraft,
    isDirty,
    isSaving,
    saveError,
    canSave: activeDocumentId !== null,
    save
  };
}
