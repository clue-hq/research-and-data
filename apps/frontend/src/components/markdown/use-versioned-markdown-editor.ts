"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { markdownCanSave, type MarkdownEditorStatus } from "@/components/markdown/markdown-session";
import {
  acceptMarkdownDocument, acceptMarkdownDocumentSave, changeMarkdownDocumentBody,
  discardMarkdownDocumentDraft, markdownDocumentSessionDirty, type MarkdownDocumentSession, type MarkdownDocument,
} from "./markdown-document-session";

export function useVersionedMarkdownEditor<D extends MarkdownDocument>(document: D | undefined, {
  scopeKey, canWrite, saveDocument, onSaved,
}: { scopeKey: string; canWrite: boolean; saveDocument: (base: D, body: string) => Promise<D>; onSaved?: (saved: D) => void }) {
  const [sessions, setSessions] = useState<Record<string, MarkdownDocumentSession<D>>>({});
  const [savingKey, setSavingKey] = useState<string | null>(null);
  const inFlight = useRef(false);
  const key = JSON.stringify([scopeKey, document?.path]);
  const session = document ? acceptMarkdownDocument(sessions[key], document) : undefined;
  // Accept clean external replacements before painting. Typing and version UUIDs alone do not
  // reset the editor. Dirty sessions keep their original document/revision as the save base.
  if (session && session !== sessions[key]) setSessions({ ...sessions, [key]: session });
  const canEdit = canWrite && !!session?.base.version && session.base.bodyLoaded !== false;
  const dirty = !!session && markdownDocumentSessionDirty(session);
  const hasDrafts = Object.values(sessions).some(markdownDocumentSessionDirty);

  const setBody = useCallback((body: string) => {
    if (!canEdit || inFlight.current) return;
    setSessions((current) => current[key] ? { ...current, [key]: changeMarkdownDocumentBody(current[key], body) } : current);
  }, [canEdit, key]);
  const setEditorStatus = useCallback((validation: MarkdownEditorStatus) => {
    setSessions((current) => {
      const item = current[key];
      if (!item || (item.validation.error === validation.error && item.validation.viewMode === validation.viewMode)) return current;
      return { ...current, [key]: { ...item, validation } };
    });
  }, [key]);

  function discard() {
    if (!document || inFlight.current) return;
    setSessions((current) => current[key] ? { ...current, [key]: discardMarkdownDocumentDraft(current[key], document) } : current);
  }

  async function save() {
    if (!session || !dirty || !canEdit || !markdownCanSave(session.validation) || inFlight.current) return;
    inFlight.current = true;
    setSavingKey(key);
    setSessions((current) => ({ ...current, [key]: { ...current[key], error: null } }));
    try {
      const saved = await saveDocument(session.base, session.body);
      setSessions((current) => ({ ...current, [key]: acceptMarkdownDocumentSave(current[key], saved, session.body) }));
      onSaved?.(saved);
    } catch (error) {
      setSessions((current) => ({ ...current, [key]: { ...current[key], error: error instanceof Error ? error.message : "Could not save your changes. Please try again." } }));
    } finally {
      inFlight.current = false;
      setSavingKey(null);
    }
  }

  useEffect(() => {
    if (!hasDrafts) return;
    const warnBeforeLeaving = (event: BeforeUnloadEvent) => { event.preventDefault(); };
    window.addEventListener("beforeunload", warnBeforeLeaving);
    return () => window.removeEventListener("beforeunload", warnBeforeLeaving);
  }, [hasDrafts]);

  return {
    documentKey: key, body: session?.body ?? "", resetKey: session?.resetKey ?? 0,
    canEdit, dirty, discard, editorOpened: session?.opened ?? false,
    mode: canEdit ? session?.mode ?? "preview" : "preview",
    error: session?.error, save, setBody, setEditorStatus,
    canSave: canEdit && dirty && !!session && markdownCanSave(session.validation) && savingKey === null,
    saving: savingKey === key, busy: savingKey !== null, saved: session?.saved && !dirty,
    setMode(mode: "preview" | "edit") {
      setSessions((current) => current[key] ? { ...current, [key]: { ...current[key], mode, opened: current[key].opened || mode === "edit" } } : current);
    },
  };
}
