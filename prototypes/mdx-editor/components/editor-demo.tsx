"use client";

import dynamic from "next/dynamic";
import { useCallback, useEffect, useRef, useState } from "react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import { Eye, Pencil, FileText, RotateCcw } from "lucide-react";
import { documents, storageKey, type DemoDocument } from "../model/documents";
import { bodyAfterChange, canSaveDraft } from "../model/draft";
import type { EditorProps, EditorState } from "./initialized-editor";

const VisualEditor = dynamic(() => import("./initialized-editor"), {
  ssr: false, loading: () => <p className="editor-loading" role="status">Loading editor…</p>,
});

function DocumentSession({ document, readOnly }: { document: DemoDocument; readOnly: boolean }) {
  const [initial, setInitial] = useState<string | null>(null);
  const [saved, setSaved] = useState(document.body);
  const [body, setBody] = useState(document.body);
  const [mode, setMode] = useState<"edit" | "preview">("edit");
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

  return <section className="document-panel" aria-label={document.title}>
    <header className="document-header">
      <div className="document-identity"><FileText size={16} aria-hidden="true" /><span>{document.path}</span></div>
      <div className="document-actions">
        <span className="save-status" role="status">{readOnly ? "Read only" : dirty ? "Unsaved changes" : "Saved"}</span>
        <div className="segmented" aria-label="Document view">
          <button type="button" aria-pressed={mode === "preview"} onClick={() => setMode("preview")}><Eye size={14} />Preview</button>
          <button type="button" aria-pressed={mode === "edit"} onClick={() => setMode("edit")}><Pencil size={14} />Edit</button>
        </div>
        <button type="button" className="button secondary" disabled={!dirty || readOnly} onClick={discard}>Discard</button>
        <button type="button" className="button primary" disabled={!saveEnabled} onClick={save}>Save</button>
      </div>
    </header>
    {storageError && <p className="document-notice critical" role="alert">{storageError}</p>}
    {sourceNeedsCheck && dirty && !readOnly && <p className="document-notice">Switch to Rich text to check your changes before saving.</p>}
    <div hidden={mode !== "edit"} className="editing-surface">
      {initial !== null && editorPermission === readOnly && <VisualEditor key={epoch} markdown={initial} initialViewMode={initialViewMode} readOnly={readOnly} onChange={onChange} onError={onError} onState={onState} />}
    </div>
    {mode === "preview" && <article className="document-prose document-preview" aria-label="Document preview">
      <ReactMarkdown remarkPlugins={[remarkGfm]} components={{ table: ({ children }) => <div className="preview-table" tabIndex={0} role="region" aria-label="Scrollable table"><table>{children}</table></div> }}>{body}</ReactMarkdown>
    </article>}
  </section>;
}

export default function EditorDemo() {
  const [active, setActive] = useState("plan");
  const [visited, setVisited] = useState(["plan"]);
  const [width, setWidth] = useState("full");
  const [readOnly, setReadOnly] = useState(false);
  const [resetCounts, setResetCounts] = useState<Record<string, number>>({});
  const [resetError, setResetError] = useState<string | null>(null);

  function selectDocument(id: string) {
    setActive(id);
    setVisited((values) => values.includes(id) ? values : [...values, id]);
  }

  function resetSample() {
    try {
      localStorage.removeItem(storageKey(active));
      setResetCounts((values) => ({ ...values, [active]: (values[active] ?? 0) + 1 }));
      setResetError(null);
    } catch { setResetError("Could not reset browser storage. Your current draft is unchanged."); }
  }

  return <>
    <header className="demo-header">
      {/* Use the local brand SVG, with no image service or production dependency. */}
      {/* eslint-disable-next-line @next/next/no-img-element */}
      <img src="/clue/logo.svg" width={86} height={30} alt="Clue" />
      <div><h1>Document editor</h1><p>Interactive prototype · Sample content</p></div>
    </header>
    <main className="demo-main">
      <div className="demo-controls">
        <label>Document<select value={active} onChange={(event) => selectDocument(event.target.value)}>{documents.map((item) => <option key={item.id} value={item.id}>{item.label}</option>)}</select></label>
        <label>Panel width<select value={width} onChange={(event) => setWidth(event.target.value)}><option value="full">Full · 880 px</option><option value="narrow">Narrow · 440 px</option><option value="compact">Compact · 360 px</option></select></label>
        <label className="checkbox-label"><input type="checkbox" checked={readOnly} onChange={(event) => setReadOnly(event.target.checked)} />Read only</label>
        <button type="button" className="button secondary reset-button" onClick={resetSample}><RotateCcw size={14} />Reset sample</button>
      </div>
      {resetError && <p role="alert" className="critical">{resetError}</p>}
      <div className={`document-frame ${width}`}>
        {documents.filter((item) => visited.includes(item.id)).map((item) => <div key={`${item.id}:${resetCounts[item.id] ?? 0}`} hidden={active !== item.id}><DocumentSession document={item} readOnly={readOnly} /></div>)}
      </div>
      <footer className="demo-footer"><p>Select text to format it, edit table cells, or use Source to see the Markdown.</p><p>Save keeps this sample in this browser. Live project and Knowledge documents are untouched.</p></footer>
    </main>
  </>;
}
