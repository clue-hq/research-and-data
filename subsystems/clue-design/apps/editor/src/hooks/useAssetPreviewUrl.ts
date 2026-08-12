import { useEffect, useState } from "react";

import {
  fetchAssetRecord,
  publicAssetBytesUrl,
  publicAssetThumbnailUrl
} from "@/engine/assetLibrary";
import type { AssetRecord } from "@/engine/contracts";
import { editorApiBaseUrl } from "@/engine/editorConfig";

/**
 * Public preview URL for an asset the caller knows only by ID.
 *
 * `<img src>` cannot send `X-Workspace-Id`, so the only servable URL shape is
 * the content-addressed `/asset-store/{digest}` — which requires the record.
 * Sites that already hold an `AssetRecord` call `publicAsset*Url` directly;
 * this hook is for the id-only sites (kit JSON variants, stored logo ids): it
 * resolves the record through the header-authenticated registry
 * (`GET /assets/{id}` via lumenFetch) and returns the public URL, or null
 * while resolving / when the asset is unknown or digest-less.
 *
 * Records are immutable enough for a per-page-load cache (bytes are
 * content-addressed; a re-render must not refetch per cell).
 */
const recordCache = new Map<string, Promise<AssetRecord | null>>();

function resolveRecord(apiBaseUrl: string, assetId: string): Promise<AssetRecord | null> {
  let pending = recordCache.get(assetId);
  if (!pending) {
    pending = fetchAssetRecord({ apiBaseUrl }, assetId).catch(() => {
      // A transport failure is not knowledge — do not cache it as "unknown".
      recordCache.delete(assetId);
      return null;
    });
    recordCache.set(assetId, pending);
  }
  return pending;
}

export function resetAssetPreviewCacheForTests(): void {
  recordCache.clear();
}

export function useAssetPreviewUrl(
  assetId: string | null | undefined,
  prefer: "thumbnail" | "bytes" = "thumbnail"
): string | null {
  const [url, setUrl] = useState<string | null>(null);

  useEffect(() => {
    if (!assetId) {
      setUrl(null);
      return;
    }
    let cancelled = false;
    const apiBaseUrl = editorApiBaseUrl();
    void resolveRecord(apiBaseUrl, assetId).then((record) => {
      if (!cancelled) {
        setUrl(
          prefer === "bytes"
            ? publicAssetBytesUrl(apiBaseUrl, record)
            : publicAssetThumbnailUrl(apiBaseUrl, record)
        );
      }
    });
    return () => {
      cancelled = true;
    };
  }, [assetId, prefer]);

  return url;
}
