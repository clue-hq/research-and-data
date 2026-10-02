"use client";

import { useState } from "react";
import { ChevronRight, ChevronsUpDown, FileText, X } from "lucide-react";
import "./file-card.css";

export default function FileCardPreview() {
  const [current, setCurrent] = useState(false);
  const [open, setOpen] = useState(false);
  return <>
    <header className="demo-header"><img src="/clue/logo.svg" width={86} height={30} alt="Clue" /><div><h1>Document link in chat</h1><p>Visual preview · Sample content</p></div></header>
    <main className="file-card-demo">
      <div className="demo-controls"><div className="segmented" aria-label="Card version"><button aria-pressed={current} onClick={() => setCurrent(true)}>Current</button><button aria-pressed={!current} onClick={() => setCurrent(false)}>Proposed</button></div></div>
      <section className="file-card-chat" aria-label="Sample chat">
        <p className="file-card-user">Can you put the audience profile together?</p>
        <img src="/clue/logo.svg" width={54} height={20} alt="Clue" />
        <p>I’ve updated the audience profile with the priorities we discussed.</p>
        {current ? <div className="file-card-old"><div><button onClick={() => setOpen(true)}>Regional clinic profile <ChevronRight size={14} /></button><span>Revision 2</span><ChevronsUpDown size={14} /></div><hr /></div> : <button className="file-card-link" onClick={() => setOpen(true)} aria-label="Open Regional clinic profile">
          <span className="file-card-glyph"><FileText size={18} aria-hidden="true" /></span>
          <span className="file-card-labels"><span className="file-card-title">Regional clinic profile</span><span className="file-card-meta">Document · Revision 2</span></span>
          <ChevronRight size={14} aria-hidden="true" />
        </button>}
        {open && <section className="file-card-document" aria-label="Sample file"><header><span>Regional clinic profile</span><button aria-label="Close sample file" onClick={() => setOpen(false)}><X size={14} /></button></header><h2>Regional clinic profile</h2><p>Focus on regional clinics whose operations teams need to reduce repetitive intake work.</p><p>Start with the account shortlist, then tailor outreach to the buying committee.</p></section>}
      </section>
      <p className="file-card-caption">The whole row opens the file. No empty summary, divider, or expand control.</p>
    </main>
  </>;
}
