"use client";

import React, { useEffect, useState } from "react";

import { publicAssetBytesUrl } from "@/engine/assetLibrary";
import { fetchLibraryAssets } from "@/engine/brandLibrary";
import type { AssetRecord } from "@/engine/contracts";

/** Image-bearing kinds a human may promote into a logo slot — fonts and
 * documents are never logos. */
const PICKABLE_KINDS = new Set(["logo", "vector", "raster_image"]);

/**
 * Human logo curation: a flat grid of the asset library's images so the user
 * can promote the REAL logo into a kit slot when the scraper guessed wrong
 * (or found nothing). Selection workflow stays in the page — this component
 * only lists and reports the click.
 */
export function KitLogoPicker({
  apiBaseUrl,
  slot,
  busy,
  onSelect,
  onCancel
}: {
  apiBaseUrl: string;
  slot: string;
  busy: boolean;
  onSelect: (assetId: string) => void;
  onCancel: () => void;
}): React.ReactElement {
  const [records, setRecords] = useState<AssetRecord[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    let cancelled = false;
    fetchLibraryAssets({ apiBaseUrl })
      .then((assets) => {
        if (!cancelled) {
          setRecords(assets.filter((asset) => PICKABLE_KINDS.has(asset.kind)));
          setLoading(false);
        }
      })
      .catch((cause: unknown) => {
        if (!cancelled) {
          setError(cause instanceof Error ? cause.message : "Could not load assets.");
          setLoading(false);
        }
      });
    return () => {
      cancelled = true;
    };
  }, [apiBaseUrl]);

  return (
    <div className="kit-logo-group" data-testid="logo-picker">
      <p className="eyebrow">Choose the {slot} logo from your library</p>
      {loading ? <span className="caption">Loading assets…</span> : null}
      {error ? <span className="caption">{error}</span> : null}
      <div className="grid-cards kit-logo-grid">
        {records.map((asset) => (
          <button
            key={asset.id}
            type="button"
            className="kit-logo-cell"
            data-testid={`pick-${asset.id}`}
            disabled={busy}
            onClick={() => onSelect(asset.id)}
          >
            <div className="asset-thumb">
              <img
                src={publicAssetBytesUrl(apiBaseUrl, asset) ?? undefined}
                alt={asset.label ?? asset.id}
              />
            </div>
            <span className="caption">{asset.label ?? asset.id}</span>
          </button>
        ))}
      </div>
      <button type="button" className="btn btn-ghost btn-sm" onClick={onCancel} disabled={busy}>
        Cancel
      </button>
    </div>
  );
}
