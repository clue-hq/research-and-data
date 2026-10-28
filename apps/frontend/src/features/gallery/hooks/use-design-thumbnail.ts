"use client";

import { useEffect, useState } from "react";
import { nextThumbnailRetry, thumbnailState } from "../model/design-thumbnail";

type Loaded = { failed: boolean; path?: string; src: string | null };

/**
 * A design thumbnail that may still be rendering in the background (2026-10-29).
 *
 * Fetches `path` and reads `X-Thumbnail-State`: a `fresh` or `stale` image is shown (as an
 * object URL), a `pending` answer shows nothing yet, and a stale or pending answer is asked
 * for again on the `nextThumbnailRetry` schedule until the card is this version's. An image
 * URL with no such header is simply shown. `failed` is a request that did not succeed.
 */
export function useDesignThumbnail(path: string | undefined): { failed: boolean; src: string | null } {
  const [loaded, setLoaded] = useState<Loaded>({ failed: false, src: null });

  useEffect(() => {
    if (!path) return;
    let cancelled = false;
    let timer: ReturnType<typeof setTimeout> | undefined;
    const objectUrls: string[] = [];

    const load = async (attempt: number) => {
      try {
        // A retry must reach the server, never a copy the browser kept.
        const response = await fetch(path, { cache: attempt === 0 ? "default" : "no-store" });
        if (cancelled) return;
        if (!response.ok) {
          setLoaded({ failed: true, path, src: null });
          return;
        }
        const state = thumbnailState(response.status, response.headers.get("x-thumbnail-state"));
        if (state !== "pending") {
          const url = URL.createObjectURL(await response.blob());
          if (cancelled) {
            URL.revokeObjectURL(url);
            return;
          }
          objectUrls.push(url);
          setLoaded({ failed: false, path, src: url });
        }
        const delay = nextThumbnailRetry(state, attempt);
        if (delay !== null) timer = setTimeout(() => void load(attempt + 1), delay);
      } catch {
        if (!cancelled) setLoaded({ failed: true, path, src: null });
      }
    };

    void load(0);
    return () => {
      cancelled = true;
      if (timer) clearTimeout(timer);
      for (const url of objectUrls) URL.revokeObjectURL(url);
    };
  }, [path]);

  return loaded.path === path ? { failed: loaded.failed, src: loaded.src } : { failed: false, src: null };
}
