"use client";

import React, { useEffect, useState } from "react";
import Link from "next/link";

import { editorApiBaseUrl } from "@/engine/editorConfig";
import {
  fetchWebDocument,
  webPromptStorageKey,
  type LoadedWebDocument
} from "@/engine/webDocuments";

/**
 * The website-mode editor shell (P0): loads the web document, shows an empty
 * dashed canvas frame with an empty-state, and — if a brief was stashed at the
 * gate — a queued-brief card. Deliberately imports NO scene/canvas code; the
 * real editing surface lands with generation in the next slice.
 */

type ShellState =
  | { kind: "loading" }
  | { kind: "ready"; document: LoadedWebDocument }
  | { kind: "wrong-kind"; document: LoadedWebDocument }
  | { kind: "error"; message: string };

export function WebEditorApp({ documentId }: { documentId: string }): React.ReactElement {
  const [state, setState] = useState<ShellState>({ kind: "loading" });
  const [queuedPrompt, setQueuedPrompt] = useState<string | null>(null);

  // Read the stashed brief once (set by /new right before navigation).
  useEffect(() => {
    try {
      const stored = window.sessionStorage.getItem(webPromptStorageKey(documentId));
      if (stored && stored.trim()) setQueuedPrompt(stored);
    } catch {
      /* storage unavailable — no queued brief to show */
    }
  }, [documentId]);

  useEffect(() => {
    let cancelled = false;
    setState({ kind: "loading" });
    fetchWebDocument({ apiBaseUrl: editorApiBaseUrl() }, documentId)
      .then((document) => {
        if (cancelled) return;
        setState(
          document.docKind === "web"
            ? { kind: "ready", document }
            : { kind: "wrong-kind", document }
        );
      })
      .catch((cause: unknown) => {
        if (cancelled) return;
        setState({
          kind: "error",
          message: cause instanceof Error ? cause.message : "This website could not be loaded."
        });
      });
    return () => {
      cancelled = true;
    };
  }, [documentId]);

  const title =
    state.kind === "ready" || state.kind === "wrong-kind" ? state.document.title : "Website";

  return (
    <>
      <header className="web-topbar">
        <span className="web-topbar-title">{title}</span>
        <span className="web-beta-pill">Website · beta</span>
        <span className="web-topbar-spacer" />
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
          <p>
            This document is a design, not a website. Open it in the canvas editor instead.
          </p>
          <Link className="btn btn-ghost btn-sm" href={`/?document=${encodeURIComponent(documentId)}`}>
            Open in editor
          </Link>
        </div>
      ) : (
        <main className="web-main">
          <div className="web-canvas-frame">
            <p className="title web-empty-title">Your website will render here</p>
            <p className="web-empty-hint">Generation lands in the next slice.</p>
            {queuedPrompt ? (
              <div className="web-brief-card">
                <span className="web-brief-label">Queued brief</span>
                <p className="web-brief-body">{queuedPrompt}</p>
              </div>
            ) : null}
          </div>
        </main>
      )}
    </>
  );
}
