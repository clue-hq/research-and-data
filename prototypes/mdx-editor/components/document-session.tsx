"use client";

import dynamic from "next/dynamic";
import { useCallback, useEffect, useRef, useState } from "react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import { Eye, Pencil, FileText } from "lucide-react";
import { storageKey, type DemoDocument } from "../model/documents";
import { bodyAfterChange, canSaveDraft } from "../model/draft";
import type { EditorProps, EditorState } from "./initialized-editor";

const VisualEditor = dynamic(() => import("./initialized-editor"), {
  ssr: false, loading: () => <p className="editor-loading" role="status">Loading editor…</p>,
});

export function DocumentSession({ document, readOnly, variant = "standalone" }: {
  document: DemoDocument; readOnly: boolean; variant?: "standalone" | "plan";
}) {
  const [initial, setInitial] = useState<string | null>(null);
  const [saved, setSaved] = useState(document.body);
  const [body, setBody] = useState(document.body);
  const [mode, setMode] = useState<"edit" | "preview">(variant === "plan" ? "preview" : "edit");
  const [editorOpened, setEditorOpened] = useState(variant !== "plan");
  const [epoch, setEpoch] = useState(0);
  const [editorPermission, setEditorPermission] = useState(readOnly);
  const [initialViewMode, setInitialViewMode] = useState<EditorState["viewMode"]>("rich-text");
  const [editorState, setEditorState] = useState<EditorState>({ error: null, viewMode: "rich-text" });
  const [storageError, setStorageError] = useState<string | null>(null);
  const normalizedBase = useRef<string | null>(null);
  const savedRef = useRef(saved);
  const viewModeRef = useRef<EditorState["viewMode"]>("rich-text");

  useEffect(() => {
    let restored = document.body;
    try { restored = localStorage.getItem(storageKey(document.id)) ?? document.body; }
    catch { setStorageError("Browser storage is unavailable. Your changes can stay open, but cannot be saved here."); }
    savedRef.current = restored;
    setSaved(restored); setBody(restored); setInitial(restored);
  }, [document]);

  useEffect(() => {
    if (editorPermission === readOnly) return;
    // MDXEditor's source editor rebuilds from its visual value on a permission change.
    // Start from our current source draft instead, so pending source edits survive.
    setInitial(body);
    setInitialViewMode(viewModeRef.current);
    setEpoch((value) => value + 1);
    setEditorPermission(readOnly);
  }, [readOnly, editorPermission, body]);

  const onChange = useCallback<NonNullable<EditorProps["onChange"]>>((next, initialNormalization) => {
    if (initialNormalization && viewModeRef.current !== "source") {
      if (initial === savedRef.current) normalizedBase.current = next;
      return;
    }
    setBody(bodyAfterChange(savedRef.current, normalizedBase.current, next));
  }, [initial]);
  const onError = useCallback<NonNullable<EditorProps["onError"]>>(({ error }) => {
    // The draft already retains the original body (or the latest source edit).
    // An import failure must not replace it with empty or trimmed parser output.
    setEditorState((previous) => ({ ...previous, error }));
  }, []);
  const onState = useCallback((state: EditorState) => {
    viewModeRef.current = state.viewMode;
    setEditorState(state);
  }, []);

  const dirty = body !== saved;
  const sourceNeedsCheck = editorState.viewMode === "source";
  const saveEnabled = canSaveDraft(saved, body, readOnly, Boolean(editorState.error) || sourceNeedsCheck);

  function save() {
    if (!saveEnabled) return;
    try {
      localStorage.setItem(storageKey(document.id), body);
      savedRef.current = body;
      normalizedBase.current = body;
      setSaved(body); setStorageError(null);
    } catch { setStorageError("Could not save in this browser. Your draft is still here; try Save again."); }
  }

  function discard() {
    setBody(saved); setInitial(saved); normalizedBase.current = null;
    setInitialViewMode("rich-text");
    viewModeRef.current = "rich-text";
    setEditorState({ error: null, viewMode: "rich-text" });
    // An explicit Discard starts a fresh history. Preview/Edit never remounts the editor.
    setEpoch((value) => value + 1);
  }

  return <section className={`document-panel ${variant === "plan" ? "plan-document" : ""}`} aria-label={document.title}>
    <header className="document-header">
      <div className="document-identity"><FileText size={variant === "plan" ? 12 : 16} aria-hidden="true" /><span title={document.title}>{variant === "plan" ? document.title : document.path}</span></div>
      <div className="document-actions">
        {(variant !== "plan" || mode === "edit") && <span className="save-status" role="status">{readOnly ? "Read only" : dirty ? "Unsaved changes" : "Saved"}</span>}
        <div className="segmented" aria-label="Document view">
          <button type="button" aria-pressed={mode === "preview"} onClick={() => setMode("preview")}><Eye size={14} />Preview</button>
          <button type="button" aria-pressed={mode === "edit"} onClick={() => { setEditorOpened(true); setMode("edit"); }}><Pencil size={14} />Edit</button>
        </div>
        {(variant !== "plan" || mode === "edit") && <>
          <button type="button" className="button secondary" disabled={!dirty || readOnly} onClick={discard}>Discard</button>
          <button type="button" className="button primary" disabled={!saveEnabled} onClick={save}>Save</button>
        </>}
      </div>
    </header>
    <div className="document-scroll" aria-busy={initial === null}>
      {storageError && <p className="document-notice critical" role="alert">{storageError}</p>}
      {initial === null && <p className="editor-loading" role="status">Loading document…</p>}
      {sourceNeedsCheck && dirty && !readOnly && <p className="document-notice">Switch to Rich text to check your changes before saving.</p>}
      <div hidden={mode !== "edit"} className="editing-surface">
        {editorOpened && initial !== null && editorPermission === readOnly && <VisualEditor key={epoch} markdown={initial} initialViewMode={initialViewMode} readOnly={readOnly} onChange={onChange} onError={onError} onState={onState} />}
      </div>
      {mode === "preview" && initial !== null && <article className="document-prose document-preview" aria-label="Document preview">
        <ReactMarkdown remarkPlugins={[remarkGfm]} components={{ table: ({ children }) => <div className="preview-table" tabIndex={0} role="region" aria-label="Scrollable table"><table>{children}</table></div> }}>{body}</ReactMarkdown>
      </article>}
    </div>
  </section>;
}
