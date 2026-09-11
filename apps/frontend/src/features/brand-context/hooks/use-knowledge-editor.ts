import { useCallback, useEffect, useRef, useState } from "react";
import { useRouter } from "next/navigation";
import type { BrandKnowledgeDocument } from "../model/brand-context";
import { saveKnowledgeDocument } from "../data/brand-knowledge-actions";

type Draft = { body: string; base: BrandKnowledgeDocument };

export function useKnowledgeEditor(document: BrandKnowledgeDocument | undefined) {
  const router = useRouter();
  const [mode, setMode] = useState<"preview" | "edit">("preview");
  const [editorOpened, setEditorOpened] = useState(false);
  const [drafts, setDrafts] = useState<Record<string, Draft>>({});
  const [savedDocuments, setSavedDocuments] = useState<Record<string, BrandKnowledgeDocument>>({});
  const [errors, setErrors] = useState<Record<string, string>>({});
  const [savingPath, setSavingPath] = useState<string | null>(null);
  const inFlight = useRef(false);
  const path = document?.path;
  const saved = path ? savedDocuments[path] : undefined;
  const source = saved && (saved.version ?? 0) >= (document?.version ?? 0) ? saved : document;
  const draft = path ? drafts[path] : undefined;
  const body = draft?.body ?? source?.body ?? "";
  const canEdit = !!source?.version && source.bodyLoaded !== false;
  const hasDrafts = Object.keys(drafts).length > 0;

  const setBody = useCallback((value: string) => {
    if (!path || !source || !canEdit || inFlight.current) return;
    setDrafts((current) => {
      const base = current[path]?.base ?? source;
      const next = { ...current };
      if (value === base.body) delete next[path];
      else next[path] = { body: value, base };
      return next;
    });
  }, [canEdit, path, source]);

  function discard() {
    if (!path || inFlight.current) return;
    setDrafts((current) => { const next = { ...current }; delete next[path]; return next; });
    setErrors((current) => ({ ...current, [path]: "" }));
  }

  async function save() {
    if (!path || !draft || !canEdit || inFlight.current) return;
    inFlight.current = true;
    setSavingPath(path);
    setErrors((current) => ({ ...current, [path]: "" }));
    try {
      const result = await saveKnowledgeDocument(draft.base, draft.body);
      setSavedDocuments((current) => ({ ...current, [path]: result }));
      setDrafts((current) => {
        const next = { ...current };
        if (next[path]?.body === draft.body) delete next[path];
        else if (next[path]) next[path] = { ...next[path], base: result };
        return next;
      });
      router.refresh();
    } catch (error) {
      setErrors((current) => ({ ...current, [path]: error instanceof Error ? error.message : "Could not save your changes. Please try again." }));
    } finally {
      inFlight.current = false;
      setSavingPath(null);
    }
  }

  useEffect(() => {
    if (!hasDrafts) return;
    const warnBeforeLeaving = (event: BeforeUnloadEvent) => { event.preventDefault(); };
    window.addEventListener("beforeunload", warnBeforeLeaving);
    return () => window.removeEventListener("beforeunload", warnBeforeLeaving);
  }, [hasDrafts]);

  return {
    body, canEdit, dirty: !!draft, discard, editorOpened, mode: canEdit ? mode : "preview",
    error: path ? errors[path] : undefined, save, setBody,
    saving: savingPath === path, busy: savingPath !== null,
    saved: !!saved && !draft,
    setMode(next: "preview" | "edit") {
      if (next === "edit") setEditorOpened(true);
      setMode(next);
    },
  };
}
