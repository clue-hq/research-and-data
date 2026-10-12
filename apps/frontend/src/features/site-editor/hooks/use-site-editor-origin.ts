"use client";

import { useEffect, useState } from "react";
import { fetchSiteEditorSession } from "../data/site-editor-session";

export interface SiteEditorOrigin {
  error: string | null;
  loaded: boolean;
  origin: string | null;
}

// One read per page: every mount shares it; a failed read is retried by the next mount.
let shared: Promise<string | null> | null = null;
function loadOrigin(): Promise<string | null> {
  shared ??= fetchSiteEditorSession()
    .then((session) => session.editorOrigin)
    .catch((error: unknown) => {
      shared = null;
      throw error;
    });
  return shared;
}

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
