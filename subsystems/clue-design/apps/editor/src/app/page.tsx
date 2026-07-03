"use client";

import dynamic from "next/dynamic";
import { useEffect, useState } from "react";
import { fetchDocument } from "@/engine/documentStore";
import { editorApiBaseUrl } from "@/engine/editorConfig";
import type { Scene } from "@/engine/contracts";

const EditorApp = dynamic(() => import("@/components/EditorApp"), {
  ssr: false
});

const apiBaseUrl = editorApiBaseUrl();

/**
 * Phase 2a document identity: `?document=<id>` reopens a persisted document
 * (its scene becomes the editor's initial scene); without the param the
 * editor starts on a fresh untitled canvas and auto-creates a document at
 * the first persisting action.
 */
type DocumentLoadState =
  | { kind: "loading" }
  | { kind: "ready"; documentId: string | null; scene: Scene | null }
  | { kind: "error"; documentId: string; message: string };

export default function Home() {
  const [loadState, setLoadState] = useState<DocumentLoadState>({ kind: "loading" });

  useEffect(() => {
    const requestedDocumentId = new URLSearchParams(window.location.search).get("document");
    if (!requestedDocumentId) {
      setLoadState({ kind: "ready", documentId: null, scene: null });
      return;
    }
    let cancelled = false;
    fetchDocument({ apiBaseUrl }, requestedDocumentId)
      .then((document) => {
        if (!cancelled) {
          setLoadState({ kind: "ready", documentId: document.documentId, scene: document.scene });
        }
      })
      .catch((error: unknown) => {
        if (!cancelled) {
          setLoadState({
            kind: "error",
            documentId: requestedDocumentId,
            message: error instanceof Error ? error.message : "The document could not be loaded."
          });
        }
      });
    return () => {
      cancelled = true;
    };
  }, []);

  const startNewDesign = () => {
    const url = new URL(window.location.href);
    url.searchParams.delete("document");
    window.history.replaceState(null, "", url);
    setLoadState({ kind: "ready", documentId: null, scene: null });
  };

  if (loadState.kind === "loading") {
    return (
      <div className="document-load-screen" role="status">
        <p>Loading design…</p>
      </div>
    );
  }

  if (loadState.kind === "error") {
    return (
      <div className="document-load-screen" role="alert">
        <div className="document-load-error">
          <strong>Couldn’t open this document</strong>
          <p>
            <code>{loadState.documentId}</code> — {loadState.message}
          </p>
          <button type="button" onClick={startNewDesign}>
            Start a new design
          </button>
        </div>
      </div>
    );
  }

  return (
    <EditorApp
      key={loadState.documentId ?? "untitled"}
      documentId={loadState.documentId ?? undefined}
      initialScene={loadState.scene ?? undefined}
      initialSelectedNodeId={null}
    />
  );
}
