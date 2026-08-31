"use client";

import { useEffect, useState } from "react";
import { designBffConfig } from "../data/design-bff";
import { fetchWebTheme, type WebTheme } from "../engine/webDocuments";

/**
 * W4.0: the mounted document's compiled theme — the color picker's real token
 * palette — fetched once per document id through the authenticated BFF.
 *
 * A theme only decorates a control that already works, so any failure or
 * refusal simply yields `null` (no retry loop, no error surface) and the
 * picker falls back to the dummy's fixture palette. No document → no fetch.
 * The loaded theme carries the id it was fetched for and is returned only for
 * that id, so a switched document never shows the previous one's colors and
 * no state is set synchronously inside the effect.
 *
 * Lives in hooks/ (not the presentation component) per the repo seam rule:
 * presentation receives typed props/context and never imports data/ or the
 * engine. Same idiom as `useWebRender`.
 */
export function useWebTheme(documentId: string | null): WebTheme | null {
  const [loaded, setLoaded] = useState<{
    documentId: string;
    theme: WebTheme;
  } | null>(null);

  useEffect(() => {
    if (!documentId) return;
    let cancelled = false;
    fetchWebTheme(designBffConfig(), documentId)
      .then((theme) => {
        if (!cancelled) setLoaded({ documentId, theme });
      })
      .catch(() => undefined);
    return () => {
      cancelled = true;
    };
  }, [documentId]);

  return loaded && loaded.documentId === documentId ? loaded.theme : null;
}
