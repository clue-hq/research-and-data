"use client";

import React, { useCallback, useEffect, useRef, useState } from "react";
import Link from "next/link";

import { editorApiBaseUrl } from "@/engine/editorConfig";
import {
  fetchWebDocument,
  fetchWebRenderHtml,
  fetchWebTheme,
  listDialogComponents,
  setTextOp,
  webDocumentHasContent,
  webPromptStorageKey,
  type LoadedWebDocument,
  type WebDoc,
  type WebNode,
  type WebTheme
} from "@/engine/webDocuments";
import {
  useWebAgentTurn,
  type WebRunEvent,
  type WebTurnDoneEnvelope
} from "@/hooks/useWebAgentTurn";
import { useWebBridgeSelection } from "@/hooks/useWebBridgeSelection";
import { useWebManualEdits } from "@/hooks/useWebManualEdits";
import { WebInspectorPanel } from "@/components/web/WebInspectorPanel";
import { selectionChipLabel, type WebSelection } from "@/engine/webBridge";

/**
 * The website-mode editor shell: loads the web document, drives agent turns
 * through {@link useWebAgentTurn}, and renders the generated site into a
 * sandboxed preview iframe beside a chat rail. Deliberately imports NO
 * scene/canvas code — the website surface is a separate, light bundle.
 *
 * Per docs/frontend-practices.md rule 2, the turn *lifecycle* (start → SSE →
 * done/error) lives in the hook; this component only binds fields, composes
 * the data layer's fetch wrappers for load/render, and renders the transcript.
 */

/** The Tailwind browser runtime the rendered page loads. Served from the Next
 * dev server; a srcdoc iframe resolves this relative URL against the parent
 * origin. See public/vendor/README.md. */
const TAILWIND_RUNTIME_SRC = "/vendor/tailwind-browser.js";

type ShellState =
  | { kind: "loading" }
  | { kind: "ready"; document: LoadedWebDocument }
  | { kind: "wrong-kind"; document: LoadedWebDocument }
  | { kind: "error"; message: string };

/** The preview width chips. `fluid` fills the pane; the rest pin an exact
 * device width the pane scrolls to. */
type WidthMode = "fluid" | "1440" | "768" | "375";
const WIDTH_CHIPS: { mode: WidthMode; label: string }[] = [
  { mode: "fluid", label: "Fluid" },
  { mode: "1440", label: "1440" },
  { mode: "768", label: "768" },
  { mode: "375", label: "375" }
];

/** The selection context a turn was sent with (the active chip), surfaced as a
 * small prefix on the user message bubble. */
interface TurnContext {
  nodeId: string;
}

/** One completed turn in the chat transcript. */
interface TurnRecord {
  id: string;
  prompt: string;
  context: TurnContext | null;
  activity: string[];
  summary: string | null;
  status: "applied" | "failed";
}

/** The in-flight turn's prompt (its live activity is derived from the hook). */
interface PendingTurn {
  id: string;
  prompt: string;
  context: TurnContext | null;
}

type RenderStatus = "idle" | "loading" | "ready" | "error";

/** The rail's two modes: the agent chat (default) and the manual inspector. */
type RailMode = "chat" | "inspect";

/** The default page a manual op targets when nothing is selected — the first
 * page, falling back to the conventional "home". */
function defaultPageId(webDoc: WebDoc | null): string {
  const first = webDoc?.pages?.[0]?.id;
  return typeof first === "string" && first.length > 0 ? first : "home";
}

/** Locate a node (and its page) by id across the loaded WebDoc. */
function findWebNode(
  webDoc: WebDoc | null,
  nodeId: string | null
): { node: WebNode; pageId: string } | null {
  if (!webDoc || !nodeId || !Array.isArray(webDoc.pages)) {
    return null;
  }
  for (const page of webDoc.pages) {
    const node = page.nodes?.[nodeId];
    if (node) {
      return { node, pageId: page.id };
    }
  }
  return null;
}

/** True when keyboard focus sits in an editable field (composer/inspector
 * inputs) or an iframe — where undo/redo shortcuts must defer to the field. */
function focusIsEditable(): boolean {
  const active = document.activeElement as HTMLElement | null;
  if (!active) {
    return false;
  }
  const tag = active.tagName;
  return (
    tag === "INPUT" ||
    tag === "TEXTAREA" ||
    tag === "SELECT" ||
    tag === "IFRAME" ||
    active.isContentEditable
  );
}

let messageSeq = 0;
function nextMessageId(): string {
  messageSeq += 1;
  return `web-msg-${messageSeq}`;
}

/** The selected node's text, collapsed to one line and clipped for the chip's
 * muted excerpt. */
const CHIP_EXCERPT_MAX = 40;
function chipExcerpt(text: string): string {
  const collapsed = text.trim().replace(/\s+/g, " ");
  return collapsed.length > CHIP_EXCERPT_MAX
    ? `${collapsed.slice(0, CHIP_EXCERPT_MAX - 1)}…`
    : collapsed;
}

/** Known web progress event types → human copy. Unknown types are prettified
 * from the raw type text. */
const KNOWN_EVENT_LABELS: Record<string, string> = {
  web_page_authored: "Page authored",
  web_preview_rendered: "Previews rendered (3 widths)",
  web_theme_resolved: "Theme resolved",
  web_turn_started: "Started",
  web_turn_planned: "Planned the build"
};

function humanizeWebEvent(type: string): string {
  const known = KNOWN_EVENT_LABELS[type];
  if (known) {
    return known;
  }
  const cleaned = type.replace(/^web_/, "").replace(/[_-]+/g, " ").trim();
  return cleaned ? cleaned.charAt(0).toUpperCase() + cleaned.slice(1) : type;
}

/** Condense a run's progress events into human labels, collapsing consecutive
 * duplicates. */
function condenseEvents(events: WebRunEvent[]): string[] {
  const labels: string[] = [];
  for (const event of events) {
    const label = humanizeWebEvent(event.type);
    if (labels.length === 0 || labels[labels.length - 1] !== label) {
      labels.push(label);
    }
  }
  return labels;
}

function readStoredBrief(documentId: string): string | null {
  try {
    const stored = window.sessionStorage.getItem(webPromptStorageKey(documentId));
    return stored && stored.trim() ? stored : null;
  } catch {
    return null;
  }
}

function clearStoredBrief(documentId: string): void {
  try {
    window.sessionStorage.removeItem(webPromptStorageKey(documentId));
  } catch {
    /* storage unavailable — nothing to clear */
  }
}

export function WebEditorApp({ documentId }: { documentId: string }): React.ReactElement {
  const [state, setState] = useState<ShellState>({ kind: "loading" });
  const [widthMode, setWidthMode] = useState<WidthMode>("fluid");
  const [composer, setComposer] = useState("");

  const [history, setHistory] = useState<TurnRecord[]>([]);
  const [pending, setPending] = useState<PendingTurn | null>(null);
  const pendingRef = useRef<PendingTurn | null>(null);
  pendingRef.current = pending;

  // Bumped on each applied turn OR manual edit to quietly refetch the render +
  // document meta (and theme).
  const [reloadNonce, setReloadNonce] = useState(0);
  const [renderHtml, setRenderHtml] = useState<string | null>(null);
  const [renderStatus, setRenderStatus] = useState<RenderStatus>("idle");
  const [renderError, setRenderError] = useState<string | null>(null);

  const [railMode, setRailMode] = useState<RailMode>("chat");
  const [theme, setTheme] = useState<WebTheme | null>(null);
  // The inspector's selected node id — persisted across the manual-edit reload
  // (node ids are stable) and re-validated against the fresh doc below.
  const [activeNodeId, setActiveNodeId] = useState<string | null>(null);

  // The live preview iframe and the per-render bridge nonce. A fresh nonce is
  // minted for every render fetch and validated on every inbound bridge message
  // (useWebBridgeSelection); a message tagged with a prior render's nonce is
  // dropped. The ref lets the selection listener read the current nonce without
  // re-arming on each fetch.
  const iframeRef = useRef<HTMLIFrameElement>(null);
  const nonceRef = useRef<string>("");

  const document = state.kind === "ready" ? state.document : null;
  const webDoc = document?.webDoc ?? null;
  const hasContent = webDocumentHasContent(webDoc);
  const baseVersion = document?.currentVersion ?? null;
  const defaultPage = defaultPageId(webDoc);

  const reload = useCallback(() => setReloadNonce((nonce) => nonce + 1), []);
  const manualEdits = useWebManualEdits({ documentId, baseVersion, onReload: reload });

  // Persist a committed contenteditable edit as a set_text op, targeting the
  // node's own page (falling back to the default page).
  const handleTextCommit = useCallback(
    (nodeId: string, html: string) => {
      const located = findWebNode(webDoc, nodeId);
      manualEdits.applyOps(
        [setTextOp(located ? located.pageId : defaultPage, nodeId, html)],
        "text_commit"
      );
    },
    [webDoc, defaultPage, manualEdits]
  );

  // Mirror an inbound bridge selection into the persisted inspector id: a node
  // selection sets it; an explicit clear (click-off / Escape inside the iframe)
  // empties it. This runs ONLY on real `select` messages — a render rebuild
  // calls resetSelection (not onSelect), so the inspector stays on its stable
  // node id across a manual-edit reload.
  const handleBridgeSelect = useCallback((next: WebSelection | null) => {
    setActiveNodeId(next ? next.nodeId : null);
  }, []);

  const { selection, clearSelection, resetSelection, previewComponent, selectNode } =
    useWebBridgeSelection({
      iframeRef,
      nonceRef,
      onTextCommit: handleTextCommit,
      onSelect: handleBridgeSelect
    });

  // Clicking the gray canvas region AROUND the iframe (never the rail/topbar,
  // and iframe-internal clicks stay in the frame) clears the selection and tells
  // the frame to drop its highlight.
  const clearFromBackdrop = useCallback(() => {
    setActiveNodeId(null);
    clearSelection();
  }, [clearSelection]);

  // After a reload, drop the inspector selection if the node no longer exists.
  useEffect(() => {
    if (activeNodeId && !findWebNode(webDoc, activeNodeId)) {
      setActiveNodeId(null);
    }
  }, [webDoc, activeNodeId]);

  const located = findWebNode(webDoc, activeNodeId);
  const inspectorNode = located?.node ?? null;
  const inspectorPageId = located?.pageId ?? defaultPage;
  const dialogs = React.useMemo(() => listDialogComponents(webDoc), [webDoc]);

  // Keep the latest run events readable inside the hook's onDone callback (which
  // fires before the next render), so a settled turn's activity is captured.
  const eventsRef = useRef<WebRunEvent[]>([]);

  const handleTurnDone = useCallback((envelope: WebTurnDoneEnvelope) => {
    const settled = pendingRef.current;
    const status: TurnRecord["status"] = envelope.status === "applied" ? "applied" : "failed";
    const summary = typeof envelope.summary === "string" ? envelope.summary : null;
    if (settled) {
      const record: TurnRecord = {
        id: settled.id,
        prompt: settled.prompt,
        context: settled.context,
        activity: condenseEvents(eventsRef.current),
        summary,
        status
      };
      setHistory((current) => [...current, record]);
      setPending(null);
    }
    if (status === "applied") {
      setReloadNonce((nonce) => nonce + 1);
    }
  }, []);

  const turn = useWebAgentTurn({ documentId, onDone: handleTurnDone });
  eventsRef.current = turn.events;
  const isRunning = turn.phase === "running";

  // A transport error never reaches onDone — commit the failed record here.
  useEffect(() => {
    if (turn.phase !== "error") {
      return;
    }
    const settled = pendingRef.current;
    if (!settled) {
      return;
    }
    const record: TurnRecord = {
      id: settled.id,
      prompt: settled.prompt,
      context: settled.context,
      activity: condenseEvents(eventsRef.current),
      summary: turn.error,
      status: "failed"
    };
    setHistory((current) => [...current, record]);
    setPending(null);
  }, [turn.phase, turn.error]);

  // Load (and quietly refetch on reloadNonce) the document. Only the first load
  // shows the full loading state; a post-turn refetch keeps the shell in place.
  useEffect(() => {
    let cancelled = false;
    setState((prev) =>
      prev.kind === "ready" || prev.kind === "wrong-kind" ? prev : { kind: "loading" }
    );
    fetchWebDocument({ apiBaseUrl: editorApiBaseUrl() }, documentId)
      .then((loaded) => {
        if (cancelled) return;
        setState(
          loaded.docKind === "web"
            ? { kind: "ready", document: loaded }
            : { kind: "wrong-kind", document: loaded }
        );
      })
      .catch((cause: unknown) => {
        if (cancelled) return;
        setState({
          kind: "error",
          message:
            cause instanceof Error ? cause.message : "This website could not be loaded."
        });
      });
    return () => {
      cancelled = true;
    };
  }, [documentId, reloadNonce]);

  // Show the live preview once the document has content or a turn has applied.
  const shouldRender = state.kind === "ready" && (hasContent || reloadNonce > 0);

  useEffect(() => {
    if (!shouldRender) {
      return;
    }
    let cancelled = false;
    // The DOM is about to be rebuilt: rotate the bridge nonce (invalidating any
    // in-flight message from the old render) and drop the stale selection.
    const nonce = crypto.randomUUID();
    nonceRef.current = nonce;
    resetSelection();
    setRenderStatus("loading");
    setRenderError(null);
    fetchWebRenderHtml({ apiBaseUrl: editorApiBaseUrl() }, documentId, TAILWIND_RUNTIME_SRC, {
      nonce
    })
      .then((result) => {
        if (cancelled) return;
        setRenderHtml(result.html);
        setRenderStatus("ready");
      })
      .catch((cause: unknown) => {
        if (cancelled) return;
        setRenderError(
          cause instanceof Error ? cause.message : "The preview could not be rendered."
        );
        setRenderStatus("error");
      });
    return () => {
      cancelled = true;
    };
  }, [documentId, shouldRender, reloadNonce, resetSelection]);

  // Fetch the resolved theme (inspector swatches) once there is content, and
  // refresh it alongside each reload. Theme failure is non-fatal — the
  // inspector just shows no swatches.
  useEffect(() => {
    if (!shouldRender) {
      return;
    }
    let cancelled = false;
    fetchWebTheme({ apiBaseUrl: editorApiBaseUrl() }, documentId)
      .then((resolved) => {
        if (!cancelled) setTheme(resolved);
      })
      .catch(() => {
        if (!cancelled) setTheme(null);
      });
    return () => {
      cancelled = true;
    };
  }, [documentId, shouldRender, reloadNonce]);

  // Undo/redo keyboard: ⌘Z / ⇧⌘Z (Ctrl on non-mac). Ignored while a turn runs,
  // a mutation is in flight, or focus is in an editable field / the iframe.
  const undoDepth = document?.undoDepth ?? 0;
  const redoDepth = document?.redoDepth ?? 0;
  const historyBusy = isRunning || manualEdits.busy;
  const canUndo = undoDepth > 0 && !historyBusy;
  const canRedo = redoDepth > 0 && !historyBusy;
  const { undo, redo } = manualEdits;
  useEffect(() => {
    const onKeyDown = (event: KeyboardEvent) => {
      if (!(event.metaKey || event.ctrlKey) || event.key.toLowerCase() !== "z") {
        return;
      }
      if (historyBusy || focusIsEditable()) {
        return;
      }
      event.preventDefault();
      if (event.shiftKey) {
        if (redoDepth > 0) redo();
      } else if (undoDepth > 0) {
        undo();
      }
    };
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, [historyBusy, undoDepth, redoDepth, undo, redo]);

  const startTurn = useCallback(
    (prompt: string) => {
      const trimmed = prompt.trim();
      if (!trimmed || isRunning) {
        return;
      }
      // Snapshot the active chip so the turn targets it and the bubble records
      // the context, even though the chip itself persists after send.
      const context: TurnContext | null = selection ? { nodeId: selection.nodeId } : null;
      const targetNodeIds = selection ? [selection.nodeId] : undefined;
      setPending({ id: nextMessageId(), prompt: trimmed, context });
      setComposer("");
      turn.start(trimmed, null, targetNodeIds);
    },
    [isRunning, turn, selection]
  );

  // Queued-brief handoff (runs once, after the first successful load): auto-send
  // on an empty document, prefill the composer on one that already has content.
  const briefHandledRef = useRef(false);
  useEffect(() => {
    if (state.kind !== "ready" || briefHandledRef.current) {
      return;
    }
    briefHandledRef.current = true;
    const brief = readStoredBrief(documentId);
    if (!brief) {
      return;
    }
    clearStoredBrief(documentId);
    if (webDocumentHasContent(state.document.webDoc)) {
      setComposer(brief);
    } else {
      startTurn(brief);
    }
  }, [state, documentId, startTurn]);

  const onComposerSubmit = (event: React.FormEvent) => {
    event.preventDefault();
    startTurn(composer);
  };

  const onComposerKeyDown = (event: React.KeyboardEvent<HTMLTextAreaElement>) => {
    if (event.key === "Enter" && !event.shiftKey) {
      event.preventDefault();
      startTurn(composer);
    }
  };

  const title = document?.title ?? "Website";
  const liveActivity = pending ? condenseEvents(turn.events) : [];
  const holderStyle: React.CSSProperties | undefined =
    widthMode === "fluid" ? undefined : { width: `${widthMode}px` };

  const renderCanvas = (): React.ReactElement => {
    if (renderHtml) {
      return (
        <>
          <div className="web-canvas-pane">
            <div
              className={`web-preview-holder${widthMode === "fluid" ? " is-fluid" : ""}`}
              style={holderStyle}
            >
              <iframe
                ref={iframeRef}
                className="web-preview-frame"
                sandbox="allow-scripts"
                srcDoc={renderHtml}
                title="Website preview"
              />
            </div>
          </div>
          {isRunning ? (
            <span className="status-pill web-generating-pill" role="status">
              <span className="dot" />
              Generating…
            </span>
          ) : null}
        </>
      );
    }

    if (renderStatus === "error") {
      return (
        <div className="web-canvas-frame" role="alert">
          <span className="status-pill is-error">Preview failed</span>
          <p className="web-empty-hint">{renderError}</p>
        </div>
      );
    }

    if (isRunning || renderStatus === "loading") {
      return (
        <div className="web-canvas-frame" role="status">
          <span className="status-pill">
            <span className="dot web-loading-dot" />
            Generating your website…
          </span>
          <p className="web-empty-hint">The agent is authoring your pages.</p>
        </div>
      );
    }

    return (
      <div className="web-canvas-frame">
        <p className="title web-empty-title">Your website will render here</p>
        <p className="web-empty-hint">
          Describe what you want in the chat and the agent will build it.
        </p>
      </div>
    );
  };

  return (
    <>
      <header className="web-topbar">
        <span className="web-topbar-title">{title}</span>
        <span className="web-beta-pill">Website · beta</span>
        <span className="web-topbar-spacer" />
        {state.kind === "ready" ? (
          <div className="web-history-group" role="group" aria-label="History">
            <button
              type="button"
              className="web-history-btn"
              onClick={undo}
              disabled={!canUndo}
              aria-label="Undo"
              title="Undo (⌘Z)"
            >
              ↺
            </button>
            <button
              type="button"
              className="web-history-btn"
              onClick={redo}
              disabled={!canRedo}
              aria-label="Redo"
              title="Redo (⇧⌘Z)"
            >
              ↻
            </button>
          </div>
        ) : null}
        {state.kind === "ready" ? (
          <div className="web-width-group" role="group" aria-label="Preview width">
            {WIDTH_CHIPS.map((chip) => (
              <button
                key={chip.mode}
                type="button"
                className={`web-width-chip${widthMode === chip.mode ? " is-selected" : ""}`}
                aria-pressed={widthMode === chip.mode}
                onClick={() => setWidthMode(chip.mode)}
              >
                {chip.label}
              </button>
            ))}
          </div>
        ) : null}
        <Link href="/new" className="web-back-link">
          New project
        </Link>
      </header>

      {state.kind === "loading" ? (
        <div className="web-notice" role="status">
          <p>Loading website…</p>
        </div>
      ) : state.kind === "error" ? (
        <div className="web-notice" role="alert">
          <span className="status-pill is-error">Couldn’t open this website</span>
          <p>{state.message}</p>
        </div>
      ) : state.kind === "wrong-kind" ? (
        <div className="web-notice" role="alert">
          <span className="status-pill is-error">Not a website document</span>
          <p>This document is a design, not a website. Open it in the canvas editor instead.</p>
          <Link
            className="btn btn-ghost btn-sm"
            href={`/?document=${encodeURIComponent(documentId)}`}
          >
            Open in editor
          </Link>
        </div>
      ) : (
        <main className="web-workspace">
          {/* Clicks that land on the canvas region backdrop (padding around the
              iframe — never the frame's own content, which is isolated) clear the
              selection. */}
          <section className="web-canvas-region" onClick={clearFromBackdrop}>
            {renderCanvas()}
          </section>

          <aside className="web-chat" aria-label="Website chat">
            <div className="web-rail-head" role="tablist" aria-label="Rail mode">
              <button
                type="button"
                role="tab"
                aria-selected={railMode === "chat"}
                className={`web-rail-tab${railMode === "chat" ? " is-selected" : ""}`}
                onClick={() => setRailMode("chat")}
              >
                Chat
              </button>
              <button
                type="button"
                role="tab"
                aria-selected={railMode === "inspect"}
                className={`web-rail-tab${railMode === "inspect" ? " is-selected" : ""}`}
                onClick={() => setRailMode("inspect")}
              >
                Inspect
              </button>
            </div>

            {railMode === "inspect" ? (
              <div className="web-insp-scroll">
                <WebInspectorPanel
                  node={inspectorNode}
                  pageId={inspectorPageId}
                  theme={theme}
                  dialogs={dialogs}
                  previewComponent={previewComponent}
                  selectNode={selectNode}
                  applyOps={manualEdits.applyOps}
                  busy={manualEdits.busy}
                  note={manualEdits.note}
                  error={manualEdits.error}
                />
              </div>
            ) : (
              <>
            <div className="web-chat-scroll">
              {history.length === 0 && !pending ? (
                <p className="web-chat-empty">
                  Describe your website and the agent will build it — layout, copy, and styling.
                </p>
              ) : null}

              {history.map((record) => (
                <React.Fragment key={record.id}>
                  <div className="web-msg is-user">
                    {record.context ? (
                      <span className="web-msg-context">
                        <span className="web-context-glyph" aria-hidden="true">
                          &lt;/&gt;
                        </span>
                        {record.context.nodeId}
                      </span>
                    ) : null}
                    {record.prompt}
                  </div>
                  {record.activity.length > 0 ? (
                    <ul className="web-activity">
                      {record.activity.map((label, index) => (
                        <li key={`${record.id}-act-${index}`}>{label}</li>
                      ))}
                    </ul>
                  ) : null}
                  {record.summary != null ? (
                    <div
                      className={`web-msg is-agent${
                        record.status === "failed" ? " is-error" : ""
                      }`}
                    >
                      {record.summary}
                    </div>
                  ) : null}
                </React.Fragment>
              ))}

              {pending ? (
                <>
                  <div className="web-msg is-user">
                    {pending.context ? (
                      <span className="web-msg-context">
                        <span className="web-context-glyph" aria-hidden="true">
                          &lt;/&gt;
                        </span>
                        {pending.context.nodeId}
                      </span>
                    ) : null}
                    {pending.prompt}
                  </div>
                  {liveActivity.length > 0 ? (
                    <ul className="web-activity is-live">
                      {liveActivity.map((label, index) => (
                        <li key={`live-act-${index}`}>{label}</li>
                      ))}
                    </ul>
                  ) : null}
                </>
              ) : null}
            </div>

            <form className="web-composer" onSubmit={onComposerSubmit}>
              {selection ? (
                <div className="web-context-chip">
                  <span className="web-context-glyph" aria-hidden="true">
                    &lt;/&gt;
                  </span>
                  <span className="web-context-chip-label">{selectionChipLabel(selection)}</span>
                  {selection.text ? (
                    <span className="web-context-chip-excerpt">{chipExcerpt(selection.text)}</span>
                  ) : null}
                  <button
                    type="button"
                    className="web-context-chip-clear"
                    onClick={clearSelection}
                    aria-label="Clear selected element"
                  >
                    ×
                  </button>
                </div>
              ) : null}
              <div className="web-composer-row">
                <textarea
                  value={composer}
                  onChange={(event) => setComposer(event.target.value)}
                  onKeyDown={onComposerKeyDown}
                  placeholder={isRunning ? "The agent is working…" : "Describe a change…"}
                  rows={1}
                  disabled={isRunning}
                  aria-label="Message the website agent"
                />
                <button
                  type="submit"
                  className="btn btn-primary"
                  disabled={isRunning || composer.trim().length === 0}
                >
                  Send
                </button>
              </div>
            </form>
              </>
            )}
          </aside>
        </main>
      )}
    </>
  );
}
