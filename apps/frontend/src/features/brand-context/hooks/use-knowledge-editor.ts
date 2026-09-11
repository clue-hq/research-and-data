import { useCallback, useEffect, useState } from "react";
import type { BrandKnowledgeDocument } from "../model/brand-context";

export function useKnowledgeEditor(document: BrandKnowledgeDocument | undefined) {
  const [mode, setMode] = useState<"preview" | "edit">("preview");
  const [editorOpened, setEditorOpened] = useState(false);
  const [drafts, setDrafts] = useState<Record<string, { body: string; original: string }>>({});
  const path = document?.path;
  const original = document?.body ?? "";
  const body = path ? drafts[path]?.body ?? original : "";
  const dirty = path !== undefined && drafts[path] !== undefined;
  const hasDrafts = Object.keys(drafts).length > 0;

  const setBody = useCallback((value: string) => {
    if (!path) return;
    setDrafts((current) => {
      const base = current[path]?.original ?? original;
      const next = { ...current };
      if (value === base) delete next[path];
      else next[path] = { body: value, original: base };
      return next;
    });
  }, [original, path]);

  function discard() {
    if (!path) return;
    setDrafts((current) => {
      const next = { ...current };
      delete next[path];
      return next;
    });
  }

  useEffect(() => {
    if (!hasDrafts) return;
    const warnBeforeLeaving = (event: BeforeUnloadEvent) => { event.preventDefault(); };
    window.addEventListener("beforeunload", warnBeforeLeaving);
    return () => window.removeEventListener("beforeunload", warnBeforeLeaving);
  }, [hasDrafts]);

  return {
    body, dirty, discard, editorOpened, mode, setBody,
    setMode(next: "preview" | "edit") {
      if (next === "edit") setEditorOpened(true);
      setMode(next);
    },
  };
}
