"use client";

import { useState, type KeyboardEvent } from "react";
import { ArrowUp, AtSign, ChevronDown, ChevronUp, FileText, Images, Maximize2, Minimize2, PanelRight, RotateCcw, Users, X } from "lucide-react";
import { documents, storageKey, type DemoDocument } from "../model/documents";
import { DocumentSession } from "./document-session";

// A separate sample identity keeps the approved editor demo's saved content intact.
const plan: DemoDocument = { ...documents[0], id: "plan-tab", title: "New logo campaign" };
const tabs = [
  { id: "gallery", label: "Gallery", Icon: Images },
  { id: "target-accounts", label: "Target accounts", Icon: Users },
  { id: "plan", label: "Plan", Icon: FileText },
] as const;
type Surface = typeof tabs[number]["id"];

export default function PlanTabDemo() {
  const [surface, setSurface] = useState<Surface>("plan");
  const [hasPlan, setHasPlan] = useState(true);
  const [panelOpen, setPanelOpen] = useState(true);
  const [width, setWidth] = useState("split");
  const [maximized, setMaximized] = useState(false);
  const [readOnly, setReadOnly] = useState(false);
  const [expanded, setExpanded] = useState(true);
  const [resetKey, setResetKey] = useState(0);
  const [resetError, setResetError] = useState<string | null>(null);
  const [announcement, setAnnouncement] = useState("");

  function openPlan() { setSurface("plan"); setPanelOpen(true); }

  function onTabKeyDown(event: KeyboardEvent<HTMLDivElement>) {
    if (!["ArrowLeft", "ArrowRight", "Home", "End"].includes(event.key)) return;
    const buttons = Array.from(event.currentTarget.querySelectorAll<HTMLButtonElement>("[role=tab]"));
    const current = buttons.indexOf(event.target as HTMLButtonElement);
    if (current < 0) return;
    event.preventDefault();
    const next = event.key === "Home" ? 0 : event.key === "End" ? buttons.length - 1
      : (current + (event.key === "ArrowRight" ? 1 : -1) + buttons.length) % buttons.length;
    buttons[next]?.focus();
    buttons[next]?.click();
  }

  function simulatePlanArrival() {
    setHasPlan(true);
    openPlan();
    setAnnouncement("Sample plan received. The Plan tab is open.");
  }

  function resetSample() {
    try {
      localStorage.removeItem(storageKey(plan.id));
      setResetKey((value) => value + 1);
      setHasPlan(true); setReadOnly(false); openPlan();
      setResetError(null); setAnnouncement("Sample plan reset.");
    } catch { setResetError("Could not reset browser storage. Your draft is unchanged."); }
  }

  return <>
    <header className="demo-header">
      {/* Local brand asset, matching the editor prototype. */}
      {/* eslint-disable-next-line @next/next/no-img-element */}
      <img src="/clue/logo.svg" width={86} height={30} alt="Clue" />
      <div><h1>Plan tab</h1><p>Interactive preview · Sample project</p></div>
    </header>
    <main className="plan-demo-main">
      <div className="demo-controls plan-demo-controls">
        <label>State<select value={hasPlan ? "ready" : "empty"} onChange={(event) => { setHasPlan(event.target.value === "ready"); openPlan(); }}><option value="ready">Plan ready</option><option value="empty">No plan yet</option></select></label>
        <label>Layout<select value={width} onChange={(event) => { setWidth(event.target.value); setMaximized(false); setPanelOpen(true); }}><option value="split">Chat + plan</option><option value="full">Full panel</option><option value="compact">Narrow · 360 px</option></select></label>
        <label className="checkbox-label"><input type="checkbox" checked={readOnly} onChange={(event) => setReadOnly(event.target.checked)} />Read only</label>
        <button className="button secondary" type="button" onClick={simulatePlanArrival}>Simulate plan arrival</button>
        <button className="button secondary" type="button" onClick={resetSample}><RotateCcw size={14} />Reset sample</button>
      </div>
      {resetError && <p className="critical" role="alert">{resetError}</p>}
      <p className="plan-sr-only" role="status">{announcement}</p>

      <div className={`plan-demo-shell layout-${width} ${maximized ? "is-maximized" : ""} ${panelOpen ? "is-panel-open" : "is-panel-closed"}`}>
        <section className="plan-chat" aria-label="Sample chat">
          <header className="plan-chat-header"><span>New logo campaign</span><button className="button secondary" type="button" onClick={() => { setPanelOpen(true); setMaximized(false); setWidth("split"); setSurface("gallery"); }}><PanelRight size={14} />Gallery</button></header>
          <div className="plan-chat-messages">
            <p className="plan-user-message">Let’s put the campaign plan together.</p>
            <div className="plan-agent-label"><img src="/clue/logo.svg" width={60} height={22} alt="Clue" /></div>
            <p>{hasPlan ? "Here’s the plan for the new logo campaign. Start with the account shortlist, then tailor the first message to each buying committee." : "Let’s settle the strategy, ideal customer profile and products first. I’ll use those decisions to write the campaign plan."}</p>
            {hasPlan && <section className="plan-chat-card" aria-label="Proposed plan">
              <header>
                <button type="button" className="plan-card-open" onClick={openPlan}><FileText size={14} /><span>Proposed a plan</span></button>
                <button type="button" className="plan-icon-button" aria-label={expanded ? "Collapse plan summary" : "Expand plan summary"} aria-expanded={expanded} aria-controls="plan-summary" onClick={() => setExpanded((value) => !value)}>{expanded ? <ChevronUp size={14} /> : <ChevronDown size={14} />}</button>
              </header>
              <div id="plan-summary" hidden={!expanded} className="plan-card-summary"><strong>New logo campaign</strong><p>A focused account list, relevant outreach and ten qualified conversations next quarter.</p><button className="button secondary" type="button" onClick={openPlan}>Open plan</button></div>
            </section>}
          </div>
          <div className="plan-composer" aria-label="Sample composer">
            <p>How can I help you?</p>
            <div><AtSign size={14} /><span>Grok 4.6 <ChevronDown size={12} /></span><button type="button" className="button primary" disabled aria-label="Send (preview only)"><ArrowUp size={14} /></button></div>
          </div>
        </section>

        <section className="plan-workspace" aria-label="Project workspace" hidden={!panelOpen}>
          <header className="plan-tab-header">
            <div role="tablist" aria-label="Project surfaces" className="plan-tabs" onKeyDown={onTabKeyDown}>
              {tabs.map(({ id, label, Icon }) => <button key={id} id={`tab-${id}`} type="button" role="tab" aria-selected={surface === id} aria-controls={`pane-${id}`} tabIndex={surface === id ? 0 : -1} onClick={() => setSurface(id)}><Icon size={12} /><span>{label}</span></button>)}
            </div>
            <div className="plan-panel-actions">
              <button type="button" className="plan-icon-button" aria-label={maximized || width === "full" ? "Restore split view" : "Maximize panel"} onClick={() => { if (width === "full") setWidth("split"); else setMaximized((value) => !value); }}>{maximized || width === "full" ? <Minimize2 size={14} /> : <Maximize2 size={14} />}</button>
              <button type="button" className="plan-icon-button" aria-label="Close panel" onClick={() => { setPanelOpen(false); setMaximized(false); }}><X size={14} /></button>
            </div>
          </header>
          <div role="tabpanel" id="pane-plan" aria-labelledby="tab-plan" hidden={surface !== "plan"} className="plan-pane" tabIndex={0}>
            <div hidden={!hasPlan} className="plan-session"><DocumentSession key={resetKey} document={plan} readOnly={readOnly} variant="plan" /></div>
            {!hasPlan && <div className="plan-empty"><FileText size={24} aria-hidden="true" /><h2>No plan yet.</h2><p>Once the strategy, the profile and the products are settled, the plan is written here.</p></div>}
          </div>
          <div role="tabpanel" id="pane-gallery" aria-labelledby="tab-gallery" hidden={surface !== "gallery"} className="plan-pane" tabIndex={0}><div className="plan-empty"><Images size={24} aria-hidden="true" /><h2>No artifacts yet</h2><p>Your campaign assets will appear here.</p></div></div>
          <div role="tabpanel" id="pane-target-accounts" aria-labelledby="tab-target-accounts" hidden={surface !== "target-accounts"} className="plan-pane" tabIndex={0}><div className="plan-empty"><Users size={24} aria-hidden="true" /><h2>No target accounts yet</h2><p>Add accounts to start building your campaign.</p></div></div>
        </section>
      </div>
      <footer className="plan-demo-footer"><p>Review the Plan tab, document header and empty state. Click the chat’s plan card to reopen it.</p><p>Sample content only. Save keeps edits in this browser; “Simulate plan arrival” demonstrates the tab opening without running an agent.</p></footer>
    </main>
  </>;
}
