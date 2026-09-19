"use client";

import { useState } from "react";
import { RotateCcw } from "lucide-react";
import { documents, storageKey } from "../model/documents";
import { DocumentSession } from "./document-session";

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
