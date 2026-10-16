"use client";

import { useEffect, useState } from "react";
import { fetchSiteEditorSession } from "../data/site-editor-session";

export interface SiteEditorOrigin {
  error: string | null;
  loaded: boolean;
  origin: string | null;
}

function loadOrigin(): Promise<string | null> {
  return fetchSiteEditorSession().then((session) => session.editorOrigin);
}

/** The workspace's editor address, read once per mount of the editor. Never cached for the page
 * (review finding K3-4): the address belongs to the workspace, which the browser cannot see (its id
 * never reaches the client), and switching workspace is a soft navigation — a page-wide cache served
 * the PREVIOUS workspace's editor after a switch. A switch re-enters the app at its home, which
 * unmounts every editor, so the next one reads the new workspace's address. */
export function useSiteEditorOrigin(enabled: boolean): SiteEditorOrigin {
  const [state, setState] = useState<SiteEditorOrigin>({ error: null, loaded: false, origin: null });
  useEffect(() => {
    if (!enabled || state.loaded) return;
    let live = true;
    loadOrigin()
      .then((origin) => {
        if (live) setState({ error: null, loaded: true, origin });
      })
      .catch((error: unknown) => {
        if (live) setState({ error: error instanceof Error ? error.message : String(error), loaded: true, origin: null });
      });
    return () => {
      live = false;
    };
  }, [enabled, state.loaded]);
  return state;
}
